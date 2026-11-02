import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookSourceInsights, pickSummary } from './notebook-source-insights'
import type { Source } from './notebook-shared'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const base = { id: 's1', status: 'ready', title: 'Mars page', type: 'url' }

const done = {
  ...base,
  metadata: {
    insights_status: 'done',
    suggested_questions: ['What did Perseverance find?'],
    summary_insight_id: 'i2'
  }
} as unknown as Source

beforeEach(() => {
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      'GET /onb-api/sources/s1/insights': () => [
        { content: '- the questions row', id: 'i3', insight_type: 'custom' },
        { content: '**Dense summary** of Mars', id: 'i2', insight_type: 'summarize' }
      ],
      'POST /api/notebooks/nb/notes': () => ({ id: 'n1' })
    })
  )
})

afterEach(cleanup)

describe('NotebookSourceInsights', () => {
  it('shows the summary the backend named, with its questions, and saves it as a note', async () => {
    const onAsk = vi.fn()
    renderWithQuery(<NotebookSourceInsights notebookId="nb" onAsk={onAsk} source={done} />)

    expect(await screen.findByText(/Dense summary/)).toBeTruthy()
    expect(screen.queryByText(/the questions row/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'What did Perseverance find?' }))
    expect(onAsk).toHaveBeenCalledWith('What did Perseverance find?')

    fireEvent.click(screen.getByRole('button', { name: 'Save as note' }))
    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        '/api/notebooks/nb/notes',
        expect.objectContaining({ body: expect.stringContaining('Summary: Mars page') })
      )
    )
    expect(await screen.findByText('Saved to notes')).toBeTruthy()
  })

  it('shows progress while pending and the reason when it failed', () => {
    const pending = { ...base, metadata: { insights_status: 'pending' } } as unknown as Source
    const { unmount } = renderWithQuery(<NotebookSourceInsights notebookId="nb" source={pending} />)
    expect(screen.getByText(/Writing a summary/)).toBeTruthy()
    unmount()

    const failed = {
      ...base,
      metadata: { insights_error: 'No chat model is installed', insights_status: 'error' }
    } as unknown as Source
    renderWithQuery(<NotebookSourceInsights notebookId="nb" source={failed} />)
    expect(screen.getByText(/No chat model is installed/)).toBeTruthy()
    expect(harvisApi).not.toHaveBeenCalled()
  })

  it('renders nothing for a source without insights', () => {
    const { container } = renderWithQuery(<NotebookSourceInsights notebookId="nb" source={base as unknown as Source} />)
    expect(container.textContent).toBe('')
  })

  it('does not fall back to another summary when a specific one was named but is gone', () => {
    expect(pickSummary([{ content: 'x', id: 'a', insight_type: 'summarize' }], 'gone')).toBeUndefined()
    expect(pickSummary([{ content: 'x', id: 'a', insight_type: 'summarize' }])?.id).toBe('a')
  })
})
