import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchHarvisFile, isHarvisFileRoute, isServerRoute } from './harvis-files'
import { normalizeOrLocalPreviewTarget } from './local-preview'

// jsdom's Blob is not the one undici's Response reads, so the response is hand-made.
function fileResponse(body: BlobPart, type: string, name: string) {
  return {
    blob: async () => new Blob([body], { type }),
    headers: new Headers({ 'content-disposition': `attachment; filename="${name}"`, 'content-type': type }),
    ok: true,
    status: 200,
    statusText: 'OK'
  } as unknown as Response
}

describe('Harvis file routes', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete (window as { hermesDesktop?: unknown }).hermesDesktop
  })

  it('tells the file route apart from other server routes', () => {
    expect(isHarvisFileRoute('/api/v1/files/abc-123/content')).toBe(true)
    expect(isServerRoute('/api/v1/files/abc-123/content')).toBe(false)
    expect(isServerRoute('/api/chat')).toBe(true)
    expect(isServerRoute('/hermes-api/api/sessions')).toBe(true)
    expect(isServerRoute('/home/user/api/notes.md')).toBe(false)
  })

  it('fetches with the sign-in cookie and reads the name the server gives', async () => {
    const fetchImpl = vi.fn(async () => fileResponse('%PDF-1.7', 'application/pdf', 'House Cats.pdf'))

    const file = await fetchHarvisFile('/api/v1/files/f1/content', fetchImpl as unknown as typeof fetch)

    expect(fetchImpl).toHaveBeenCalledWith('/api/v1/files/f1/content', { credentials: 'include' })
    expect(file).toMatchObject({ mimeType: 'application/pdf', name: 'House Cats.pdf' })
  })

  it('opens a made PDF in the side panel as a PDF, named after the file', async () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { webShell: true }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => fileResponse('%PDF-1.7', 'application/pdf', 'House Cats.pdf'))
    )

    const target = await normalizeOrLocalPreviewTarget('/api/v1/files/f1/content')

    expect(target).toMatchObject({ label: 'House Cats.pdf', path: '/api/v1/files/f1/content', previewKind: 'pdf' })
    expect(target?.dataUrl).toMatch(/^data:application\/pdf;base64,/)
  })

  it('opens a text file as text and a slide deck as a binary file', async () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { webShell: true }
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(fileResponse('# Notes', 'text/markdown', 'notes.md'))
        .mockResolvedValueOnce(
          fileResponse(
            'PK',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'House Cats.pptx'
          )
        )
    )

    expect(await normalizeOrLocalPreviewTarget('/api/v1/files/n1/content')).toMatchObject({
      label: 'notes.md',
      language: 'markdown',
      previewKind: 'text'
    })
    expect(await normalizeOrLocalPreviewTarget('/api/v1/files/d1/content')).toMatchObject({
      binary: true,
      label: 'House Cats.pptx',
      previewKind: 'binary'
    })
  })

  it('says plainly when the file is gone', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: false, status: 404, statusText: 'Not Found' }) as Response)

    await expect(fetchHarvisFile('/api/v1/files/x/content', fetchImpl as unknown as typeof fetch)).rejects.toThrow(
      'That file is gone or is not yours.'
    )
  })
})
