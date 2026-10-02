import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ComposerAttachment } from '@/store/composer'

import { toChatMessages } from './chat-messages'
import {
  HARVIS_FILES_PATH,
  harvisFileUrl,
  HarvisUploadError,
  historyAttachmentRefs,
  isBrowserShell,
  pendingBrowserUpload,
  promptFiles,
  trackBrowserUpload,
  uploadHarvisFile
} from './harvis-uploads'

const ORIGIN = 'https://harvis.example'

function response(status: number, body: unknown, statusText = ''): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, statusText })
}

describe('isBrowserShell', () => {
  afterEach(() => {
    Reflect.deleteProperty(window, 'hermesDesktop')
  })

  it('is true only for the web shim, never for Electron or no bridge at all', () => {
    expect(isBrowserShell()).toBe(false)
    Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { saveImageBuffer: vi.fn() } })
    expect(isBrowserShell()).toBe(false)
    Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { webShell: true } })
    expect(isBrowserShell()).toBe(true)
  })
})

describe('uploadHarvisFile', () => {
  it('posts the file as multipart with the session cookie and returns the file reference', async () => {
    const fetchImpl = vi.fn(async () =>
      response(200, { id: 'f1', filename: 'sales.csv', meta: { content_type: 'text/csv', size: 120 } })
    )

    const uploaded = await uploadHarvisFile(new File(['a,b'], 'sales.csv', { type: 'text/csv' }), fetchImpl)

    expect(uploaded).toEqual({ id: 'f1', name: 'sales.csv', contentType: 'text/csv', size: 120 })
    expect(fetchImpl).toHaveBeenCalledOnce()

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]

    expect(url).toBe(HARVIS_FILES_PATH)
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBeInstanceOf(File)
  })

  it('surfaces the server message when the upload is refused (size cap)', async () => {
    const detail = 'File too large: uploads are limited to 50 MB on this server (HARVIS_MAX_UPLOAD_MB).'
    const fetchImpl = vi.fn(async () => response(413, { detail }))

    const err = await uploadHarvisFile(new File(['x'], 'big.pdf'), fetchImpl).catch(e => e)

    expect(err).toBeInstanceOf(HarvisUploadError)
    expect(err.status).toBe(413)
    expect(err.message).toBe(detail)
  })

  it('falls back to the status line when the failure body is not JSON', async () => {
    const fetchImpl = vi.fn(async () => response(502, '', 'Bad Gateway'))

    await expect(uploadHarvisFile(new File(['x'], 'a.txt'), fetchImpl)).rejects.toThrow('502 Bad Gateway')
  })

  it('rejects a 200 that names no file id', async () => {
    const fetchImpl = vi.fn(async () => response(200, { filename: 'a.txt' }))

    await expect(uploadHarvisFile(new File(['x'], 'a.txt'), fetchImpl)).rejects.toThrow('no file id')
  })
})

describe('promptFiles', () => {
  const chip = (overrides: Partial<ComposerAttachment>): ComposerAttachment => ({
    id: 'x',
    kind: 'file',
    label: 'x',
    ...overrides
  })

  it('names each finished upload once and skips path, terminal and failed chips', () => {
    const files = promptFiles([
      chip({ id: 'a', fileId: 'f1' }),
      chip({ id: 'b', kind: 'image', fileId: 'f2' }),
      chip({ id: 'c', fileId: 'f1' }),
      chip({ id: 'd', path: '/tmp/local.txt' }),
      chip({ id: 'e', kind: 'terminal', detail: 'ls' }),
      chip({ id: 'f', uploadState: 'error' }),
      undefined as unknown as ComposerAttachment
    ])

    expect(files).toEqual([{ id: 'f1' }, { id: 'f2' }])
  })
})

describe('historyAttachmentRefs', () => {
  it('renders an image upload by its content URL and a document by name', () => {
    const refs = historyAttachmentRefs(
      [
        { type: 'file', id: 'img 1', name: 'cat.png', content_type: 'image/png', size: 10 },
        { type: 'file', id: 'f2', name: 'Q3 report.pdf', content_type: 'application/pdf', size: 10 },
        { type: 'file', id: 'f3', content_type: 'text/csv' },
        { bogus: true },
        'f4'
      ],
      ORIGIN
    )

    expect(refs).toEqual([`@image:${ORIGIN}/api/v1/files/img%201/content`, '@file:`Q3 report.pdf`', '@file:f3'])
    expect(harvisFileUrl('f1', ORIGIN)).toBe(`${ORIGIN}${HARVIS_FILES_PATH}f1/content`)
  })

  it('ignores rows without attachments', () => {
    expect(historyAttachmentRefs(undefined, ORIGIN)).toEqual([])
    expect(historyAttachmentRefs('nope', ORIGIN)).toEqual([])
    expect(historyAttachmentRefs([], ORIGIN)).toEqual([])
  })

  it('reaches the hydrated user bubble as attachment refs, even with empty text', () => {
    const messages = toChatMessages([
      {
        role: 'user',
        content: '',
        timestamp: 1,
        attachments: [{ type: 'file', id: 'f1', name: 'sales.csv', content_type: 'text/csv', size: 3 }]
      },
      { role: 'assistant', content: 'Three rows.', timestamp: 2 },
      { role: 'user', content: 'thanks', timestamp: 3 }
    ])

    expect(messages).toHaveLength(3)
    expect(messages[0]!.role).toBe('user')
    expect(messages[0]!.attachmentRefs).toEqual(['@file:sales.csv'])
    expect(messages[2]!.attachmentRefs).toBeUndefined()
  })
})

describe('trackBrowserUpload', () => {
  it('exposes the in-flight upload until it settles', async () => {
    let finish!: (patch: { fileId: string }) => void
    const upload = new Promise<{ fileId: string }>(resolve => {
      finish = resolve
    })

    trackBrowserUpload('chip', upload)
    expect(pendingBrowserUpload('chip')).toBe(upload)

    finish({ fileId: 'f1' })
    await upload
    await Promise.resolve()

    expect(pendingBrowserUpload('chip')).toBeUndefined()
  })
})
