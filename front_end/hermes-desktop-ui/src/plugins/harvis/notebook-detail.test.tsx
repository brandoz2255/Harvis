import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookDetail } from './notebook-detail'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const notebook = {
  id: NB,
  title: 'Mars Rover Exploration Texts',
  description: 'Everything about Perseverance',
  emoji: '🪐',
  source_count: 1,
  note_count: 0,
  updated_at: '2026-09-01T00:00:00Z'
}

const stats = {
  source_count: 1,
  chunk_count: 12,
  note_count: 2,
  message_count: 3,
  ready_sources: 1,
  processing_sources: 0
}

function mockRoutes(sources: unknown[]) {
  harvisApi.mockImplementation(
    routeApi({
      [`GET /api/notebooks/${NB}/sources`]: () => sources,
      [`GET /api/notebooks/${NB}/stats`]: () => stats,
      [`GET /api/notebooks/${NB}/notes`]: () => ({ notes: [] }),
      [`GET /api/notebooks/${NB}/chat/history`]: () => ({ messages: [] }),
      [`GET /api/notebooks/${NB}`]: () => notebook,
      [`POST /api/notebooks/${NB}/autoname`]: () => ({ title: 'Mars Rover Exploration Texts', emoji: '🚀' }),
      [`PATCH /api/notebooks/${NB}`]: () => notebook,
      'GET /api/workspace/providers': () => ({ providers: [] })
    })
  )
}

beforeEach(() => {
  harvisApi.mockReset()
})

afterEach(cleanup)

describe('NotebookDetail', () => {
  it('shows the emoji, title, description and stats line', async () => {
    mockRoutes([])
    renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)

    expect((await screen.findByRole('heading', { level: 2, name: /Mars Rover/ })).textContent).toContain(
      '🪐 Mars Rover Exploration Texts'
    )
    expect(screen.getByText('Everything about Perseverance')).toBeTruthy()
    expect(await screen.findByText('1 source · 12 passages · 2 notes · 3 messages')).toBeTruthy()
  })

  it('opens on Sources when nothing is ready yet, and on Chat once a source is', async () => {
    mockRoutes([])
    const first = renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)
    expect(await first.findByText(/No sources yet/)).toBeTruthy()
    first.unmount()

    mockRoutes([
      {
        id: 's1',
        type: 'url',
        title: 'Mars page',
        status: 'ready',
        error_message: null,
        chunk_count: 4,
        original_filename: null
      }
    ])
    renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)
    expect(await screen.findByPlaceholderText('Ask something about these sources')).toBeTruthy()
  })

  it('auto-names through POST /autoname and refreshes the header', async () => {
    mockRoutes([
      {
        id: 's1',
        type: 'url',
        title: 'Mars page',
        status: 'ready',
        error_message: null,
        chunk_count: 4,
        original_filename: null
      }
    ])
    renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)
    await screen.findByText(/Mars Rover Exploration Texts/)

    const button = screen.getByRole('button', { name: /auto-name/i })
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(button)

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/autoname`,
        expect.objectContaining({ method: 'POST' })
      )
    )
    const getCalls = () => harvisApi.mock.calls.filter(c => c[0] === `/api/notebooks/${NB}` && !c[1]?.method).length
    await waitFor(() => expect(getCalls()).toBeGreaterThan(1))
  })

  it('renames and describes through PATCH', async () => {
    mockRoutes([])
    renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)
    await screen.findByText(/Mars Rover Exploration Texts/)

    const edit = screen.getByRole('button', { name: /edit/i })
    await waitFor(() => expect((edit as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(edit)
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Rover notes' } })
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}`,
        expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ title: 'Rover notes', description: null }) })
      )
    )
  })

  it('reports a notebook that cannot be opened', async () => {
    harvisApi.mockImplementation(async () => {
      throw new Error('Notebook not found')
    })
    renderWithQuery(<NotebookDetail notebookId={NB} onDeleted={() => undefined} />)

    expect(await screen.findByText('Could not open this notebook')).toBeTruthy()
  })
})
