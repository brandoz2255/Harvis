import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotebookChat } from './notebook-chat'
import { requestQuestion, setContextLevel } from './notebook-selection'
import { renderWithQuery, routeApi } from './notebook-test-utils'

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }))

vi.mock('./api', () => ({ harvisApi }))

const NB = 'nb-1'

const src = (id: string) =>
  ({
    chunk_count: 3,
    created_at: '2026-09-01T00:00:00Z',
    error_message: null,
    id,
    original_filename: null,
    status: 'ready',
    title: id,
    type: 'text'
  }) as const

const source = {
  chunk_id: 'c1',
  end_char: 26,
  page: 3,
  quote: 'Jezero crater held a lake.',
  section: null,
  snippet: 'Jezero crater held a lake.',
  source_id: 's1',
  source_title: 'Mars page',
  start_char: 0
}

const sse = (event: string, data: Record<string, unknown>) =>
  `event: ${event}\ndata: ${JSON.stringify({ type: event, ...data })}\n\n`

/** A fetch Response whose body yields each chunk separately, like a real stream. */
function streamResponse(chunks: string[], ok = true, status = 200) {
  const enc = new TextEncoder()

  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(enc.encode(chunk))
      }

      controller.close()
    }
  })

  return ok
    ? ({ body, ok, status, statusText: 'OK' } as unknown as Response)
    : ({ body: null, json: async () => ({ detail: 'nope' }), ok, status, statusText: 'Bad' } as unknown as Response)
}

const jsonReply = {
  answer: 'It held a lake [1].',
  citations: [source],
  message_id: 'm-json',
  model_used: 'gemma4:e4b'
}

let history: unknown[] = []
const fetchMock = vi.fn()

beforeEach(() => {
  history = []
  harvisApi.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  harvisApi.mockImplementation(
    routeApi({
      'GET /api/workspace/providers': () => ({ providers: [{ models: ['gemma4:e4b'], status: 'online' }] }),
      'GET /api/notebooks/meta/capabilities': () => {
        throw new Error('off')
      },
      [`GET /api/notebooks/${NB}/chat/history`]: () => ({ messages: history }),
      [`POST /api/notebooks/${NB}/chat`]: () => {
        history = [
          { content: 'What was Jezero?', id: 'u1', role: 'user' },
          { citations: [source], content: 'It held a lake [1].', id: 'm-json', role: 'assistant' }
        ]

        return jsonReply
      },
      [`GET /api/notebooks/${NB}/sources/s1/content`]: () => ({
        content: 'Jezero crater held a lake. More text.',
        length: 37,
        page_starts: null,
        source_id: 's1',
        title: 'Mars page',
        type: 'pdf'
      })
    })
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function ask(question: string) {
  const input = await screen.findByPlaceholderText('Ask something about these sources')
  // The model list loads asynchronously; Ask stays disabled until a model is chosen.
  fireEvent.change(input, { target: { value: question } })
  const button = screen.getByRole('button', { name: 'Ask' })
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(button)
}

/** The server saves the exchange before it says `done`, so the history the UI refetches already has it. */
function serveAnswer(chunks: string[], answer = 'It held a lake [1].') {
  fetchMock.mockImplementation(async () => {
    history = [
      { content: 'What was Jezero?', id: 'u1', role: 'user' },
      { citations: [source], content: answer, id: 'm1', model_used: 'gemma4:e4b', role: 'assistant' }
    ]

    return streamResponse(chunks)
  })
}

const answerEvents = (answer: string, extra: Record<string, unknown> = {}) => [
  sse('sources', { sources: [{ n: 1, ...source }] }),
  sse('delta', { text: 'It held ' }),
  sse('delta', { text: 'a lake [SOURCE 1].' }),
  sse('done', {
    answer,
    citations: [{ index: 1, ...source }],
    message_id: 'm1',
    model_used: 'gemma4:e4b',
    refused: false,
    unsupported: false,
    ...extra
  })
]

describe('NotebookChat', () => {
  it('streams the answer from /chat/stream with no top_k in the body', async () => {
    serveAnswer(answerEvents('It held a lake [1].'))

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`/api/notebooks/${NB}/chat/stream`)
    expect(init.credentials).toBe('include')
    expect(JSON.parse(init.body as string)).toEqual({ message: 'What was Jezero?', model: 'gemma4:e4b' })

    // The marker in the finished answer is a button that names its source.
    const chip = await screen.findByRole('button', { name: 'Source 1: Mars page, page 3' })
    expect(chip.textContent).toBe('[1]')
    expect(screen.getByText(/It held a lake/)).toBeTruthy()
  })

  it('opens the source viewer with the cited passage marked when a marker is clicked', async () => {
    serveAnswer(answerEvents('It held a lake [1].'))

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    fireEvent.click(await screen.findByRole('button', { name: 'Source 1: Mars page, page 3' }))

    const mark = await screen.findByTestId('cited-passage')
    expect(mark.textContent).toBe('Jezero crater held a lake.')
  })

  it('opens the same passage from the list under the answer', async () => {
    history = [
      { content: 'What was Jezero?', id: 'u1', role: 'user' },
      { citations: [source], content: 'It held a lake [1].', id: 'a1', model_used: 'gemma4:e4b', role: 'assistant' }
    ]

    renderWithQuery(<NotebookChat notebookId={NB} ready />)

    fireEvent.click(await screen.findByTitle('Open this passage in its source'))

    expect((await screen.findByTestId('cited-passage')).textContent).toBe('Jezero crater held a lake.')
  })

  it('falls back to the plain route when the stream is unavailable', async () => {
    fetchMock.mockResolvedValue(streamResponse([], false, 404))

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        `/api/notebooks/${NB}/chat`,
        expect.objectContaining({
          body: JSON.stringify({ message: 'What was Jezero?', model: 'gemma4:e4b' }),
          method: 'POST'
        })
      )
    )
    expect(await screen.findByRole('button', { name: 'Source 1: Mars page, page 3' })).toBeTruthy()
  })

  it('shows the error and keeps the question when text was already streamed and then failed', async () => {
    fetchMock.mockResolvedValue(
      streamResponse([sse('delta', { text: 'Half an ans' }), sse('error', { message: 'Model went away' })])
    )

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    expect(await screen.findByText('Model went away')).toBeTruthy()
    expect(harvisApi).not.toHaveBeenCalledWith(`/api/notebooks/${NB}/chat`, expect.anything())
    expect((screen.getByPlaceholderText('Ask something about these sources') as HTMLInputElement).value).toBe(
      'What was Jezero?'
    )
  })

  it('renders the answer as it arrives and keeps Stop available until the stream ends', async () => {
    const enc = new TextEncoder()

    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(enc.encode(sse('sources', { sources: [{ n: 1, ...source }] })))
          controller.enqueue(enc.encode(sse('delta', { text: 'It held a lake [SOURCE 1]' })))
          init.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')))
        }
      })

      return { body, ok: true, status: 200, statusText: 'OK' } as unknown as Response
    })

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    // Half-way through: the text is on screen, the marker is already a button, and the stream is still open.
    expect(await screen.findByText(/It held a lake/)).toBeTruthy()
    expect(await screen.findByRole('button', { name: 'Source 1: Mars page, page 3' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save as note' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(await screen.findByText('Stopped. Nothing was saved.')).toBeTruthy()
  })

  it('stops the stream when Stop is pressed and says nothing was saved', async () => {
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        })
    )

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')

    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }))

    expect(await screen.findByText('Stopped. Nothing was saved.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    expect(harvisApi).not.toHaveBeenCalledWith(`/api/notebooks/${NB}/chat`, expect.anything())
  })

  it('renders a refusal as not found in the sources, with no citations and no save action', async () => {
    history = [
      { content: 'Who won?', id: 'u1', role: 'user' },
      { citations: [], content: 'I could not find that in your sources.', id: 'a1', role: 'assistant' }
    ]

    renderWithQuery(<NotebookChat notebookId={NB} ready />)

    expect(await screen.findByText(/Not found in your sources/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save as note' })).toBeNull()
    expect(screen.queryByTitle('Open this passage in its source')).toBeNull()
    expect(screen.getByRole('button', { name: /Find sources/ })).toBeTruthy()
  })

  it('marks an answer that cites nothing as not cited and invents no list', async () => {
    history = [
      { content: 'Why?', id: 'u1', role: 'user' },
      { citations: [], content: 'Probably because of tides.', id: 'a1', role: 'assistant' }
    ]

    renderWithQuery(<NotebookChat notebookId={NB} ready />)

    expect(await screen.findByText(/Not cited\. No passage/)).toBeTruthy()
    expect(screen.queryByRole('list')).toBeNull()
  })

  it('searches the web with the question from the Find sources chip', async () => {
    history = [
      { content: 'Who won?', id: 'u1', role: 'user' },
      { citations: [], content: 'I could not find that in your sources.', id: 'a1', role: 'assistant' }
    ]
    harvisApi.mockImplementation(
      routeApi({
        'GET /api/workspace/providers': () => ({ providers: [] }),
        'GET /api/notebooks/meta/capabilities': () => ({ web_search: { ready: true, reason: '' } }),
        [`GET /api/notebooks/${NB}/chat/history`]: () => ({ messages: history }),
        [`POST /api/notebooks/${NB}/discover/search`]: () => ({
          results: [{ site: 'example.org', snippet: 's', title: 'The result', url: 'https://example.org/a' }]
        })
      })
    )

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    fireEvent.click(await screen.findByRole('button', { name: /Find sources/ }))

    expect(await screen.findByText('The result')).toBeTruthy()
    expect(harvisApi).toHaveBeenCalledWith(
      `/api/notebooks/${NB}/discover/search`,
      expect.objectContaining({ body: JSON.stringify({ max_results: 8, query: 'Who won?' }) })
    )
  })

  it('saves the answer as a note with its citations and offsets', async () => {
    fetchMock.mockResolvedValue(streamResponse(answerEvents('It held a lake [1].')))
    harvisApi.mockImplementation(
      routeApi({
        'GET /api/workspace/providers': () => ({ providers: [{ models: ['gemma4:e4b'], status: 'online' }] }),
        'GET /api/notebooks/meta/capabilities': () => ({}),
        [`GET /api/notebooks/${NB}/chat/history`]: () => ({
          messages: [
            { content: 'What was Jezero?', id: 'u1', role: 'user' },
            {
              citations: [{ ...source, end_char: null, start_char: null }],
              content: 'It held a lake [1].',
              id: 'm1',
              role: 'assistant'
            }
          ]
        }),
        [`POST /api/notebooks/${NB}/notes`]: () => ({ id: 'n1' })
      })
    )

    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    await ask('What was Jezero?')
    fireEvent.click(await screen.findByRole('button', { name: 'Save as note' }))

    await waitFor(() => {
      const call = harvisApi.mock.calls.find(([path]) => path === `/api/notebooks/${NB}/notes`)
      expect(call).toBeTruthy()
      const body = JSON.parse((call![1] as RequestInit).body as string)
      expect(body.content).toBe('It held a lake [1].')
      expect(body.source_meta.question).toBe('What was Jezero?')
      expect(body.source_meta.citations[0]).toMatchObject({ end_char: 26, source_id: 's1', start_char: 0 })
    })
  })
  describe('context levels', () => {
    it('sends only the sources that are not Off, in the stream body', async () => {
      const sources = [src('a'), src('b'), src('c')]
      setContextLevel('nb-ctx', 'b', 'off')
      serveAnswer(answerEvents('It held a lake [1].'))

      renderWithQuery(<NotebookChat notebookId="nb-ctx" ready sources={sources} />)
      await ask('What was Jezero?')

      await waitFor(() => expect(fetchMock).toHaveBeenCalled())
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(JSON.parse(init.body as string)).toEqual({
        message: 'What was Jezero?',
        model: 'gemma4:e4b',
        source_ids: ['a', 'c']
      })
      setContextLevel('nb-ctx', 'b', 'full')
    })

    it('sends source_ids on the JSON fallback too', async () => {
      const sources = [src('a'), src('b')]
      setContextLevel(NB, 'b', 'off')
      fetchMock.mockResolvedValue(streamResponse([], false, 404))

      renderWithQuery(<NotebookChat notebookId={NB} ready sources={sources} />)
      await ask('What was Jezero?')

      await waitFor(() =>
        expect(harvisApi).toHaveBeenCalledWith(
          `/api/notebooks/${NB}/chat`,
          expect.objectContaining({
            body: JSON.stringify({ message: 'What was Jezero?', model: 'gemma4:e4b', source_ids: ['a'] }),
            method: 'POST'
          })
        )
      )
      setContextLevel(NB, 'b', 'full')
    })

    it('names the Summary sources in summary_source_ids and keeps them in source_ids', async () => {
      const sources = [src('a'), src('b'), src('c')]
      setContextLevel('nb-sum', 'b', 'insights')
      setContextLevel('nb-sum', 'c', 'off')
      serveAnswer(answerEvents('It held a lake [1].'))

      renderWithQuery(<NotebookChat notebookId="nb-sum" ready sources={sources} />)
      await ask('What was Jezero?')

      await waitFor(() => expect(fetchMock).toHaveBeenCalled())
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(JSON.parse(init.body as string)).toEqual({
        message: 'What was Jezero?',
        model: 'gemma4:e4b',
        source_ids: ['a', 'b'],
        summary_source_ids: ['b']
      })
      setContextLevel('nb-sum', 'b', 'full')
      setContextLevel('nb-sum', 'c', 'full')
    })

    it('sends summary_source_ids on the JSON fallback too', async () => {
      const sources = [src('a'), src('b')]
      setContextLevel(NB, 'b', 'insights')
      fetchMock.mockResolvedValue(streamResponse([], false, 404))

      renderWithQuery(<NotebookChat notebookId={NB} ready sources={sources} />)
      await ask('What was Jezero?')

      await waitFor(() =>
        expect(harvisApi).toHaveBeenCalledWith(
          `/api/notebooks/${NB}/chat`,
          expect.objectContaining({
            body: JSON.stringify({
              message: 'What was Jezero?',
              model: 'gemma4:e4b',
              source_ids: ['a', 'b'],
              summary_source_ids: ['b']
            }),
            method: 'POST'
          })
        )
      )
      setContextLevel(NB, 'b', 'full')
    })

    it('says which sources were read as summaries and which had none, under the answer', async () => {
      const sources = [src('a'), src('b')]
      setContextLevel(NB, 'a', 'insights')
      setContextLevel(NB, 'b', 'insights')
      history = []
      fetchMock.mockImplementation(async () => {
        history = [
          { content: 'What was Jezero?', id: 'u1', role: 'user' },
          { citations: [source], content: 'It held a lake [1].', id: 'm1', model_used: 'gemma4:e4b', role: 'assistant' }
        ]

        return streamResponse(
          answerEvents('It held a lake [1].', {
            context: {
              excluded: [{ reason: 'no_summary', source_id: 'b', title: 'Rover log' }],
              mode: 'summary',
              opened: [],
              summarized: [{ source_id: 'a', title: 'Mars page' }]
            }
          })
        )
      })

      renderWithQuery(<NotebookChat notebookId={NB} ready sources={sources} />)
      await ask('What was Jezero?')

      expect(await screen.findByText(/Read as summaries: Mars page\./)).toBeTruthy()
      expect(screen.getByText(/Left out, no summary yet: Rover log\./)).toBeTruthy()
      setContextLevel(NB, 'a', 'full')
      setContextLevel(NB, 'b', 'full')
    })

    it('shows the overview note from the JSON fallback reply', async () => {
      harvisApi.mockImplementation(
        routeApi({
          'GET /api/workspace/providers': () => ({ providers: [{ models: ['gemma4:e4b'], status: 'online' }] }),
          'GET /api/notebooks/meta/capabilities': () => {
            throw new Error('off')
          },
          [`GET /api/notebooks/${NB}/chat/history`]: () => ({
            messages: [
              { content: 'Summarize everything', id: 'u1', role: 'user' },
              { citations: [], content: 'Overview text.', id: 'm-json', role: 'assistant' }
            ]
          }),
          [`POST /api/notebooks/${NB}/chat`]: () => ({
            answer: 'Overview text.',
            citations: [],
            context: {
              excluded: [],
              mode: 'overview',
              opened: [{ source_id: 'b', title: 'Rover log' }],
              summarized: [{ source_id: 'a', title: 'Mars page' }]
            },
            message_id: 'm-json',
            model_used: 'gemma4:e4b'
          })
        })
      )
      fetchMock.mockResolvedValue(streamResponse([], false, 404))

      renderWithQuery(<NotebookChat notebookId={NB} ready />)
      await ask('Summarize everything')

      expect(await screen.findByText(/Overview from the summaries of Mars page\./)).toBeTruthy()
      expect(screen.getByText(/No summary yet, so the start of the text was used for: Rover log\./)).toBeTruthy()
    })

    it('refuses to ask, and sends nothing, when every source is Off', async () => {
      const sources = [src('a'), src('b')]
      setContextLevel('nb-alloff', 'a', 'off')
      setContextLevel('nb-alloff', 'b', 'off')

      renderWithQuery(<NotebookChat notebookId="nb-alloff" ready sources={sources} />)
      await ask('What was Jezero?')

      expect(await screen.findByText(/Every source is set to Off/)).toBeTruthy()
      expect(fetchMock).not.toHaveBeenCalled()
      setContextLevel('nb-alloff', 'a', 'full')
      setContextLevel('nb-alloff', 'b', 'full')
    })
  })

  describe('Configure chat', () => {
    it('is hidden unless the notebook role is owner', async () => {
      const view = renderWithQuery(<NotebookChat notebookId={NB} ready />)
      await screen.findByPlaceholderText('Ask something about these sources')
      expect(screen.queryByRole('button', { name: 'Configure chat' })).toBeNull()
      view.unmount()

      renderWithQuery(<NotebookChat isOwner={false} notebookId={NB} ready />)
      await screen.findByPlaceholderText('Ask something about these sources')
      expect(screen.queryByRole('button', { name: 'Configure chat' })).toBeNull()
    })

    it('shows for the owner', async () => {
      renderWithQuery(<NotebookChat isOwner notebookId={NB} ready />)

      expect(await screen.findByRole('button', { name: 'Configure chat' })).toBeTruthy()
    })
  })

  it('puts a question handed over from a source into the input box', async () => {
    renderWithQuery(<NotebookChat notebookId={NB} ready />)
    const input = (await screen.findByPlaceholderText('Ask something about these sources')) as HTMLTextAreaElement

    requestQuestion(NB, 'What does this source say about water?')

    await waitFor(() => expect(input.value).toBe('What does this source say about water?'))
  })
})
