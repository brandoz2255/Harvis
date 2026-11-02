import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  describeContext,
  parseContext,
  parseDone,
  parseSources,
  StreamUnavailable,
  streamNotebookChat
} from './notebook-stream'

const sse = (event: string, data: Record<string, unknown>) =>
  `event: ${event}\ndata: ${JSON.stringify({ type: event, ...data })}\n\n`

function respond(chunks: string[], init: { ok?: boolean; status?: number } = {}) {
  const enc = new TextEncoder()

  const body = new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach(chunk => c.enqueue(enc.encode(chunk)))
      c.close()
    }
  })

  const ok = init.ok ?? true

  return vi
    .fn()
    .mockResolvedValue(
      ok
        ? { body, ok, status: 200, statusText: 'OK' }
        : { body: null, json: async () => ({ detail: 'Not Found' }), ok, status: init.status ?? 500, statusText: 'x' }
    )
}

afterEach(() => vi.unstubAllGlobals())

describe('streamNotebookChat', () => {
  it('forwards deltas and sources, then resolves with the done payload', async () => {
    vi.stubGlobal(
      'fetch',
      respond([
        sse('sources', { sources: [{ n: 2, snippet: 'sn', source_id: 'a', start_char: 3, end_char: 9 }] }),
        // A frame split across two network chunks must still parse.
        sse('delta', { text: 'Hello ' }).slice(0, 20),
        sse('delta', { text: 'Hello ' }).slice(20) + sse('delta', { text: 'world [SOURCE 2]' }),
        sse('done', {
          answer: 'Hello world [1]',
          citations: [{ index: 1, source_id: 'a', start_char: 3, end_char: 9 }],
          message_id: 'm1',
          refused: false,
          unsupported: false
        })
      ])
    )

    let text = ''
    let sources = new Map()

    const answer = await streamNotebookChat(
      'nb 1',
      { message: 'q', model: 'm' },
      { onDelta: t => (text += t), onSources: s => (sources = s) }
    )

    expect(text).toBe('Hello world [SOURCE 2]')
    expect(sources.get(2)).toMatchObject({ end_char: 9, index: 2, source_id: 'a', start_char: 3 })
    expect(answer).toMatchObject({ answer: 'Hello world [1]', messageId: 'm1', refused: false })
    expect(answer.citations[0]).toMatchObject({ index: 1, start_char: 3 })
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/notebooks/nb%201/chat/stream')
  })

  it('marks an error before any text as retryable, and one after text as not', async () => {
    vi.stubGlobal('fetch', respond([sse('error', { message: 'No model' })]))
    const early = await streamNotebookChat('nb', { message: 'q', model: 'm' }, { onDelta: () => undefined }).catch(
      e => e
    )

    expect(early).toBeInstanceOf(StreamUnavailable)
    expect(early).toMatchObject({ message: 'No model', retryable: true })

    vi.stubGlobal('fetch', respond([sse('delta', { text: 'Some' }), sse('error', { message: 'Cut off' })]))
    const late = await streamNotebookChat('nb', { message: 'q', model: 'm' }, { onDelta: () => undefined }).catch(
      e => e
    )

    expect(late).toMatchObject({ message: 'Cut off', retryable: false })
  })

  it('treats a missing route and an early end as retryable', async () => {
    vi.stubGlobal('fetch', respond([], { ok: false, status: 404 }))
    const missing = await streamNotebookChat('nb', { message: 'q', model: 'm' }, { onDelta: () => undefined }).catch(
      e => e
    )

    expect(missing).toMatchObject({ message: 'Not Found', retryable: true })

    vi.stubGlobal('fetch', respond([sse('sources', { sources: [] })]))
    const ended = await streamNotebookChat('nb', { message: 'q', model: 'm' }, { onDelta: () => undefined }).catch(
      e => e
    )

    expect(ended).toMatchObject({ message: 'The answer stream ended early.', retryable: true })
  })
})

describe('parsers', () => {
  it('parseSources ignores entries without a number or a source', () => {
    expect(
      parseSources({ sources: [{ n: 0, source_id: 'a' }, { source_id: 'a' }, 4, { n: 1, source_id: 'b' }] }).size
    ).toBe(1)
    expect(parseSources({}).size).toBe(0)
  })

  it('parseDone defaults every flag to false', () => {
    expect(parseDone({ answer: 'x' })).toEqual({
      answer: 'x',
      citations: [],
      context: null,
      emptyNotebook: false,
      messageId: null,
      modelUsed: null,
      refused: false,
      unsupported: false
    })
  })

  it('parseContext keeps titles and ids, and ignores anything that is not a summary report', () => {
    expect(parseContext(null)).toBeNull()
    expect(parseContext({ mode: 'other' })).toBeNull()
    expect(
      parseContext({
        excluded: [{ reason: 'no_summary', source_id: 'b', title: 'Log' }, 5],
        mode: 'summary',
        summarized: [{ source_id: 'a', title: null }, { title: 'no id' }]
      })
    ).toEqual({
      excluded: [{ reason: 'no_summary', source_id: 'b', title: 'Log' }],
      mode: 'summary',
      opened: [],
      summarized: [{ source_id: 'a', title: null }]
    })
  })

  it('describeContext says what was read and what was left out, and nothing when there is no report', () => {
    expect(describeContext(null)).toBe('')
    expect(describeContext({ excluded: [], mode: 'summary', opened: [], summarized: [] })).toBe('')
    expect(
      describeContext({
        excluded: [
          { reason: 'no_summary', source_id: 'b', title: 'Log' },
          { reason: 'unreadable', source_id: 'c', title: 'Hidden' }
        ],
        mode: 'overview',
        opened: [{ source_id: 'd', title: null }],
        summarized: [{ source_id: 'a', title: 'Page' }]
      })
    ).toBe(
      'Overview from the summaries of Page. No summary yet, so the start of the text was used for: Untitled source. ' +
        'Left out, no summary yet: Log. Set them to Full to include them. Left out, could not be read: 1 source.'
    )
  })
})
