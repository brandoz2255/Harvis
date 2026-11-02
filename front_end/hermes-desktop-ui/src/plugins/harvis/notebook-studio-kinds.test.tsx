import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setContextLevel } from './notebook-selection'
import type { Source } from './notebook-shared'
import { durationsFor, PRESET_STYLES, STYLE_MAX_MINUTES, withPresetStyles } from './notebook-studio'
import { chatMadeArtifact, NotebookStudioRail } from './notebook-studio-rail'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-kinds'

const sources = [
  { id: 's1', type: 'url', title: 'Mars page', status: 'ready' },
  { id: 's2', type: 'pdf', title: 'Rover paper', status: 'ready' }
] as unknown as Source[]

const table = {
  id: 't1',
  kind: 'data_table',
  title: 'Rovers',
  format: 'json',
  content: { title: 'Rovers', columns: ['Name'], rows: [{ cells: ['Perseverance'], source: 'Mars page' }] },
  status: 'ready',
  audio_url: null,
  error_message: null,
  created_at: '2026-10-30T00:00:00Z'
}

const generateBodies = () =>
  harvisApi.mock.calls
    .filter(([path]) => path === `/onb-api/notebooks/${NB}/generate`)
    .map(([, init]) => JSON.parse((init as { body: string }).body))

beforeEach(() => {
  harvisApi.mockReset()
  window.localStorage.clear()
  harvisApi.mockImplementation(
    routeApi({
      [`GET /onb-api/notebooks/${NB}/artifacts`]: () => [],
      [`POST /onb-api/notebooks/${NB}/generate`]: () => table,
      [`GET /api/notebooks/${NB}/notes`]: () => ({ notes: [] }),
      'GET /api/workspace/providers': () => ({ providers: [] })
    })
  )
})

afterEach(cleanup)

describe('studio rail kinds', () => {
  it('offers Data Table and Slide Deck', async () => {
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={sources} title="Mars" />)
    expect(await screen.findByRole('button', { name: 'Data Table' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Slide Deck' })).toBeTruthy()
  })

  it("sends a tile's own instructions and no source list when nothing was changed", async () => {
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={sources} title="Mars" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Customize Data Table' }))
    const box = screen.getByPlaceholderText(/Write for a beginner/)
    fireEvent.change(box, { target: { value: '  Compare costs  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }))
    await waitFor(() => expect(generateBodies()).toHaveLength(1))
    const body = generateBodies()[0]
    expect(body.kind).toBe('data_table')
    expect(body.prompt).toBe('Compare costs')
    expect(body.source_ids).toBeUndefined()
  })

  it('leaves out sources set to Off', async () => {
    setContextLevel(NB, 's2', 'off')
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={sources} title="Mars" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Slide Deck' }))
    await waitFor(() => expect(generateBodies()).toHaveLength(1))
    expect(generateBodies()[0].source_ids).toEqual(['s1'])
  })

  it('refuses to generate when no source is selected', async () => {
    setContextLevel(NB, 's1', 'off')
    setContextLevel(NB, 's2', 'off')
    renderWithQuery(<NotebookStudioRail notebookId={NB} sources={sources} title="Mars" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Data Table' }))
    expect(await screen.findByText(/No source is selected/)).toBeTruthy()
    expect(generateBodies()).toHaveLength(0)
  })
})

describe('audio presets', () => {
  it('adds Brief and Critique when the server list lacks them, without duplicating its own', () => {
    const merged = withPresetStyles([{ description: 'x', id: 'conversational', name: 'Conversational' }])
    expect(merged.map(s => s.id)).toEqual(['conversational', ...PRESET_STYLES.map(p => p.id)])

    const own = { description: 'server wording', id: 'brief', name: 'Brief' }
    const kept = withPresetStyles([own])
    expect(kept.filter(s => s.id === 'brief')).toEqual([own])
  })

  it('caps Brief at three minutes and leaves other styles alone', () => {
    expect(STYLE_MAX_MINUTES.brief).toBe(3)
    expect(durationsFor('brief')).toEqual([3])
    expect(durationsFor('critique')).toEqual([3, 5, 10, 15])
  })
})

describe('artifacts a chat action makes', () => {
  const quiz = {
    ...table,
    id: 'q1',
    kind: 'quiz',
    title: 'Mars quiz',
    content: { title: 'Mars quiz', questions: [{ q: 'Red?', options: ['Yes', 'No'], answer: 0 }] },
    created_at: new Date().toISOString()
  }

  it('says it is waiting, then opens the artifact when it lands', async () => {
    let list: unknown[] = []
    harvisApi.mockImplementation(
      routeApi({
        [`GET /onb-api/notebooks/${NB}/artifacts`]: () => list,
        [`GET /api/notebooks/${NB}/notes`]: () => ({ notes: [] }),
        'GET /api/workspace/providers': () => ({ providers: [] })
      })
    )
    const { queryClient } = renderWithQuery(
      <NotebookStudioRail expecting="quiz" notebookId={NB} sources={sources} title="Mars" />
    )
    expect(await screen.findByTestId('chat-making')).toBeTruthy()
    list = [quiz]
    await queryClient.invalidateQueries()
    await waitFor(() => expect(document.body.textContent).toContain('Red?'))
    expect(screen.queryByTestId('chat-making')).toBeNull()
  })

  it('ignores an unknown kind', async () => {
    renderWithQuery(<NotebookStudioRail expecting="podcast" notebookId={NB} sources={sources} title="Mars" />)
    expect(await screen.findByRole('button', { name: 'Data Table' })).toBeTruthy()
    expect(screen.queryByTestId('chat-making')).toBeNull()
  })

  it('counts only a recent artifact of the asked kind', () => {
    const now = Date.parse('2026-10-30T12:00:00Z')
    const old = { ...quiz, created_at: '2026-10-30T11:00:00Z' } as never
    const fresh = { ...quiz, created_at: '2026-10-30T11:58:00Z' } as never
    expect(chatMadeArtifact([old], 'quiz', now)).toBeUndefined()
    expect(chatMadeArtifact([fresh], 'flashcards', now)).toBeUndefined()
    expect(chatMadeArtifact([old, fresh], 'quiz', now)).toBe(fresh)
  })
})
