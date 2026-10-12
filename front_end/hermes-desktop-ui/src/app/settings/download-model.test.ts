import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadModel } from './harvis-api'
import type { PullEvent } from './pull-progress'

const enc = new TextEncoder()

function streamOf(...chunks: string[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) {
        controller.enqueue(enc.encode(c))
      }

      controller.close()
    }
  })
}

const sse = (event: object) => `data: ${JSON.stringify(event)}\n\n`

afterEach(() => vi.unstubAllGlobals())

describe('downloadModel', () => {
  it('posts with the cookie and reports events from a stream cut mid-block', async () => {
    const fetchMock = vi.fn(async () => {
      const all =
        sse({ status: 'pulling manifest' }) + sse({ status: 'success' }) + sse({ status: 'done', final: true })

      return new Response(streamOf(all.slice(0, 17), all.slice(17, 60), all.slice(60)), { status: 200 })
    })

    vi.stubGlobal('fetch', fetchMock)
    const seen: PullEvent[] = []

    await downloadModel('main-host', { tag: 'gemma3:4b' }, e => seen.push(e))

    expect(seen.map(e => e.status)).toEqual(['pulling manifest', 'success', 'done'])

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/cookbook/download')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(JSON.parse(String(init.body))).toEqual({ node: 'main-host', ollama_tag: 'gemma3:4b' })
  })

  it('sends repo and quant for a cookbook model without a tag', async () => {
    const fetchMock = vi.fn(async () => new Response(streamOf(sse({ status: 'success' })), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await downloadModel('n', { quant: 'Q4_K_M', repo: 'org/Model-GGUF' }, () => {})

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1]
    expect(JSON.parse(String(init.body))).toEqual({ node: 'n', quant: 'Q4_K_M', repo: 'org/Model-GGUF' })
  })

  it('turns an error event into a plain sentence', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(streamOf(sse({ error: 'ollama unreachable at http://x' })), { status: 200 }))
    )

    await expect(downloadModel('n', { tag: 'a' }, () => {})).rejects.toThrow('ollama unreachable at http://x.')
  })

  it('shows the server detail when the request is refused', async () => {
    const detail = 'This server is shared, so downloading models onto it is for admins.'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 403 }))
    )

    await expect(downloadModel('n', { tag: 'a' }, () => {})).rejects.toThrow(detail)
  })

  it('stops when aborted', async () => {
    const controller = new AbortController()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        init.signal?.throwIfAborted()

        return new Promise<Response>((_, reject) => {
          init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        })
      })
    )

    const run = downloadModel('n', { tag: 'a' }, () => {}, controller.signal)
    controller.abort()

    await expect(run).rejects.toMatchObject({ name: 'AbortError' })
  })
})
