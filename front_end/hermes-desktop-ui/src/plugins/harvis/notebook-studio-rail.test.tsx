import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Source } from './notebook-shared'
import { NotebookStudioRail } from './notebook-studio-rail'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const ready = [{ id: 's1', type: 'url', title: 'Mars page', status: 'ready' }] as unknown as Source[]

const quiz = {
  id: 'a1',
  kind: 'quiz',
  title: 'Quiz: Mars',
  format: 'json',
  content: { questions: [{ q: 'Which rover landed in 2021?', options: ['Curiosity', 'Perseverance'], answer: 1 }] },
  status: 'ready',
  audio_url: null,
  error_message: null,
  created_at: '2026-09-25T00:00:00Z'
}

let log: unknown[] = []

beforeEach(() => {
  harvisApi.mockReset()
  log = []
  harvisApi.mockImplementation(
    routeApi({
      [`GET /onb-api/notebooks/${NB}/artifacts`]: () => log,
      [`POST /onb-api/notebooks/${NB}/generate`]: () => {
        log = [quiz]
        return quiz
      },
      [`DELETE /onb-api/notebooks/${NB}/artifacts/a1`]: () => {
        log = []
        return { ok: true }
      },
      'GET /api/workspace/providers': () => ({ providers: [] })
    })
  )
})

afterEach(cleanup)

describe('NotebookStudioRail', () => {
  it('waits for a ready source before making anything', async () => {
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={[]} title="Mars" />)

    expect(await screen.findByText('Add a source to start making things.')).toBeTruthy()
    expect((screen.getByRole('button', { name: /Quiz/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('makes a quiz, opens it to take, and keeps it in the Generated log', async () => {
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={ready} title="Mars" />)
    await screen.findByText(/Nothing yet/)

    fireEvent.click(screen.getByRole('button', { name: /Quiz/ }))

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/onb-api/notebooks/${NB}/generate`,
        expect.objectContaining({ method: 'POST', body: expect.stringContaining('"kind":"quiz"') })
      )
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Perseverance' }))
    expect(screen.getByText('1 of 1 right so far')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Back to Studio' }))
    expect(await screen.findByText('Quiz: Mars')).toBeTruthy()
  })

  it('deletes a log item only on the second click', async () => {
    log = [quiz]
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={ready} title="Mars" />)
    await screen.findByText('Quiz: Mars')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(harvisApi.mock.calls.some(c => c[1]?.method === 'DELETE')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Click again to delete' }))
    await waitFor(() => expect(screen.queryByText('Quiz: Mars')).toBeNull())
  })
})
