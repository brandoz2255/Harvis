import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  type Note,
  parseSseBlock,
  podcastAudioUrl,
  readSse,
  sortNotes,
  toTransformationType,
  transformationLabel
} from './notebook-shared'

describe('parseSseBlock', () => {
  it('reads the event name and JSON data of one block', () => {
    expect(parseSseBlock('event: progress\ndata: {"step":"audio","message":"Voicing…"}')).toEqual({
      event: 'progress',
      data: { step: 'audio', message: 'Voicing…' }
    })
  })

  it('defaults to "message" and drops blocks without JSON', () => {
    expect(parseSseBlock('data: {"ok":true}')).toEqual({ event: 'message', data: { ok: true } })
    expect(parseSseBlock(': keepalive')).toBeNull()
    expect(parseSseBlock('data: not json')).toBeNull()
  })
})

describe('readSse', () => {
  afterEach(() => vi.unstubAllGlobals())

  const streamOf = (chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) {
          controller.enqueue(new TextEncoder().encode(c))
        }

        controller.close()
      }
    })

  it('POSTs the body and dispatches every block, even when a block spans chunks', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(streamOf(['event: progress\ndata: {"m":1}\n\nevent: res', 'ult\ndata: {"id":"p1"}\n\n']), {
          status: 200
        })
    )
    vi.stubGlobal('fetch', fetchMock)
    const seen: string[] = []

    await readSse('/api/x', { a: 1 }, e => seen.push(`${e.event}:${JSON.stringify(e.data)}`))

    expect(seen).toEqual(['progress:{"m":1}', 'result:{"id":"p1"}'])
    expect(fetchMock).toHaveBeenCalledWith('/api/x', expect.objectContaining({ method: 'POST', body: '{"a":1}' }))
  })

  it('throws the backend detail on a non-OK reply', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"detail":"No content available"}', { status: 400 }))
    )

    await expect(readSse('/api/x', {}, () => undefined)).rejects.toThrow('No content available')
  })
})

describe('podcastAudioUrl', () => {
  it('keeps only the file name so old prefixes still play through the current proxy', () => {
    expect(podcastAudioUrl({ audio_url: '/onb-api/podcasts/tts-audio/podcast_1.wav', audio_path: null })).toBe(
      '/api/notebooks/podcasts/tts-audio/podcast_1.wav'
    )
    expect(podcastAudioUrl({ audio_url: null, audio_path: '/tmp/podcasts/audio/p 2.mp3' })).toBe(
      '/api/notebooks/podcasts/tts-audio/p%202.mp3'
    )
    expect(podcastAudioUrl({ audio_url: null, audio_path: null })).toBeNull()
  })
})

describe('transformation ids', () => {
  it('maps the listed "summary" to the enum value the request accepts', () => {
    expect(toTransformationType('summary')).toBe('summarize')
    expect(toTransformationType('key_points')).toBe('key_points')
  })

  it('labels a stored type from the list, or from the id when the list is missing', () => {
    const types = [{ id: 'summary', name: 'Summary', description: '' }]
    expect(transformationLabel('summarize', types)).toBe('Summary')
    expect(transformationLabel('key_points')).toBe('Key points')
  })
})

describe('sortNotes', () => {
  it('puts pinned notes first, then the most recently edited', () => {
    const note = (id: string, is_pinned: boolean, updated_at: string) =>
      ({
        id,
        is_pinned,
        updated_at,
        created_at: updated_at,
        content: '',
        title: null,
        type: 'user_note',
        source_meta: {}
      }) as Note

    const sorted = sortNotes([
      note('old', false, '2026-01-01T00:00:00Z'),
      note('new', false, '2026-03-01T00:00:00Z'),
      note('pinned', true, '2025-01-01T00:00:00Z')
    ])

    expect(sorted.map(n => n.id)).toEqual(['pinned', 'new', 'old'])
  })
})
