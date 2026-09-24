import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Source } from './notebook-shared'
import { NotebookStudio } from './notebook-studio'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const sources: Source[] = [
  {
    id: 's1',
    type: 'url',
    title: 'Mars page',
    status: 'ready',
    error_message: null,
    chunk_count: 4,
    original_filename: null
  },
  {
    id: 's2',
    type: 'pdf',
    title: null,
    status: 'processing',
    error_message: null,
    chunk_count: 0,
    original_filename: 'x.pdf'
  }
]

const podcasts = [
  {
    id: 'p1',
    title: 'Mars — audio overview',
    status: 'completed',
    style: 'conversational',
    audio_url: '/onb-api/podcasts/tts-audio/podcast_1.wav',
    audio_path: null,
    duration_seconds: 199,
    outline: null,
    transcript: [{ speaker: 'Speaker 1', dialogue: 'Welcome.' }],
    error_message: null,
    created_at: '2026-09-01T00:00:00Z'
  },
  {
    id: 'p2',
    title: 'Script only',
    status: 'script_only',
    style: 'interview',
    audio_url: null,
    audio_path: null,
    duration_seconds: null,
    outline: null,
    transcript: [],
    error_message: null,
    created_at: '2026-09-01T00:00:00Z'
  },
  {
    id: 'p3',
    title: 'Broken',
    status: 'error',
    style: 'debate',
    audio_url: null,
    audio_path: null,
    duration_seconds: null,
    outline: null,
    transcript: [],
    error_message: "Client error '404 Not Found'",
    created_at: null
  }
]

const transformations = [
  {
    id: 't1',
    source_id: 's1',
    transformation_type: 'summarize',
    transformed_content: 'Perseverance landed in Jezero crater.',
    model_used: 'llama3.1:8b',
    created_at: '2026-09-01T00:00:00Z'
  }
]

beforeEach(() => {
  harvisApi.mockReset()
  harvisApi.mockImplementation(
    routeApi({
      'GET /api/workspace/providers': () => ({ providers: [{ status: 'online', models: ['llama3.1:8b'] }] }),
      'GET /api/notebooks/transformations/types': () => ({
        transformations: [
          { id: 'summary', name: 'Summary', description: '' },
          { id: 'key_points', name: 'Key Points', description: '' }
        ]
      }),
      'GET /api/notebooks/podcasts/styles': () => ({
        styles: [{ id: 'conversational', name: 'Conversational', description: '' }]
      }),
      [`GET /api/notebooks/podcasts/by-notebook/${NB}`]: () => ({ podcasts, count: 3 }),
      [`GET /api/notebooks/${NB}/transformations`]: () => ({ transformations, total_count: 1, has_more: false }),
      [`POST /api/notebooks/${NB}/sources/s1/transform`]: () => transformations[0],
      [`POST /api/notebooks/${NB}/notes`]: () => ({ id: 'n9' })
    })
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('NotebookStudio', () => {
  it('lists past summaries with their source, model and a save-as-note action', async () => {
    renderWithQuery(<NotebookStudio notebookId={NB} sources={sources} title="Mars" />)

    expect(await screen.findByText('Perseverance landed in Jezero crater.')).toBeTruthy()
    expect(screen.getByText(/of Mars page/).textContent).toContain('llama3.1:8b')

    fireEvent.click(screen.getAllByRole('button', { name: 'Save as note' })[0])

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/notes`,
        expect.objectContaining({ body: expect.stringContaining('"title":"Summary: Mars page"') })
      )
    )
  })

  it('runs a transformation with the enum id the backend accepts and the online model', async () => {
    renderWithQuery(<NotebookStudio notebookId={NB} sources={sources} title="Mars" />)
    await screen.findByText('Perseverance landed in Jezero crater.')

    const make = await screen.findByRole('button', { name: 'Make it' })
    await waitFor(() => expect((make as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(make)

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/sources/s1/transform`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ transformation: 'summarize', model: 'llama3.1:8b' })
        })
      )
    )
  })

  it('shows a player for finished audio, and honest text for script-only and failed ones', async () => {
    const { container } = renderWithQuery(<NotebookStudio notebookId={NB} sources={sources} title="Mars" />)

    await screen.findByText('Mars — audio overview')
    const audio = container.querySelector('audio')
    expect(audio?.getAttribute('src')).toBe('/api/notebooks/podcasts/tts-audio/podcast_1.wav')
    expect(screen.getByText(/speech service was not reachable/)).toBeTruthy()
    expect(screen.getByText("Client error '404 Not Found'")).toBeTruthy()
  })

  it('generates through the SSE stream with the ready sources and reports progress', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('event: progress\ndata: {"step":"outline","message":"Writing the outline…"}\n\n')
        )
        controller.enqueue(new TextEncoder().encode('event: result\ndata: {"id":"p4","status":"completed"}\n\n'))
        controller.close()
      }
    })
    const fetchMock = vi.fn(async () => new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    renderWithQuery(<NotebookStudio notebookId={NB} sources={sources} title="Mars" />)
    await screen.findByText('Mars — audio overview')

    fireEvent.click(screen.getByRole('button', { name: /generate/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/notebooks/podcasts/generate/stream')
    expect(JSON.parse(init.body as string)).toMatchObject({
      notebook_id: NB,
      source_ids: ['s1'],
      generate_audio: true,
      speakers: 2,
      style: 'conversational',
      duration_minutes: 5,
      title: 'Mars — audio overview'
    })

    // Progress clears once the stream closes and the list is refetched.
    await waitFor(() => expect(screen.queryByText('Writing the outline…')).toBeNull())
    expect(harvisApi.mock.calls.filter(c => String(c[0]).includes('/podcasts/by-notebook/')).length).toBeGreaterThan(1)
  })

  it('surfaces the stream error event instead of hanging', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: error\ndata: {"error":"No content available"}\n\n'))
        controller.close()
      }
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(body, { status: 200 }))
    )

    renderWithQuery(<NotebookStudio notebookId={NB} sources={sources} title="Mars" />)
    await screen.findByText('Mars — audio overview')
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))

    expect(await screen.findByText('No content available')).toBeTruthy()
    expect(screen.getByRole('button', { name: /generate/i })).toBeTruthy()
  })
})
