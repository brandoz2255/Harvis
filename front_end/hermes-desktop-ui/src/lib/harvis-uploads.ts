import { formatRefValue } from '@/components/assistant-ui/directive-text'
import type { ComposerAttachment, ComposerAttachmentPatch } from '@/store/composer'

import { reportUnauthorized } from './harvis-session'

/**
 * Chat attachments in the browser build.
 *
 * The desktop app stages a picked file by path through the gateway
 * (`image.attach`, `file.attach`). A browser has no paths and the Harvis
 * facade implements neither method, so the bytes go to Harvis' own upload
 * route instead and `prompt.submit` names the resulting ids in `files`.
 * `owui_compat.chat_completion._inject_files` then feeds them to the model.
 */

export const HARVIS_FILES_PATH = '/api/v1/files/'

/** The browser shim (`lib/desktop-shim`) marks itself; Electron never does. */
export function isBrowserShell(): boolean {
  return (
    typeof window !== 'undefined' &&
    (window as { hermesDesktop?: { webShell?: boolean } }).hermesDesktop?.webShell === true
  )
}

export interface HarvisUpload {
  id: string
  name: string
  contentType: string
  size: number
}

/** An upload the server refused, with the message it gave (e.g. the size cap). */
export class HarvisUploadError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
  }
}

async function failureMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => '')

  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail

    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
  } catch {
    // not JSON — fall through to the raw text
  }

  return text.trim() || `${res.status} ${res.statusText}`.trim()
}

export async function uploadHarvisFile(file: File, fetchImpl: typeof fetch = fetch): Promise<HarvisUpload> {
  const form = new FormData()
  form.append('file', file, file.name)

  // Same-origin, cookie-authenticated: nginx fronts the backend on this origin.
  const res = await fetchImpl(HARVIS_FILES_PATH, { method: 'POST', body: form, credentials: 'include' })

  if (!res.ok) {
    if (res.status === 401) {
      reportUnauthorized()
    }

    throw new HarvisUploadError(await failureMessage(res), res.status)
  }

  const body = (await res.json()) as {
    id?: unknown
    filename?: unknown
    meta?: { content_type?: unknown; size?: unknown }
  }

  if (typeof body.id !== 'string' || !body.id) {
    throw new HarvisUploadError('Upload returned no file id', res.status)
  }

  return {
    id: body.id,
    name: typeof body.filename === 'string' && body.filename ? body.filename : file.name,
    contentType:
      typeof body.meta?.content_type === 'string' && body.meta.content_type
        ? body.meta.content_type
        : file.type || 'application/octet-stream',
    size: typeof body.meta?.size === 'number' ? body.meta.size : file.size
  }
}

/** The `files` list for `prompt.submit`: every chip that finished uploading. */
export function promptFiles(attachments: readonly ComposerAttachment[]): { id: string }[] {
  const seen = new Set<string>()
  const out: { id: string }[] = []

  for (const attachment of attachments) {
    const id = attachment?.fileId

    if (id && !seen.has(id)) {
      seen.add(id)
      out.push({ id })
    }
  }

  return out
}

function pageOrigin(): string {
  return typeof window === 'undefined' ? '' : window.location.origin
}

/** Where the browser can fetch an upload back (owner-scoped, cookie-authenticated). */
export function harvisFileUrl(fileId: string, origin = pageOrigin()): string {
  return `${origin}${HARVIS_FILES_PATH}${encodeURIComponent(fileId)}/content`
}

export interface HistoryAttachment {
  id: string
  name?: string
  content_type?: string
}

function isHistoryAttachment(value: unknown): value is HistoryAttachment {
  return typeof value === 'object' && value !== null && typeof (value as { id?: unknown }).id === 'string'
}

/**
 * Attachment refs for a persisted user turn, in the shape the optimistic
 * bubble already renders: images become `@image:<url>` (DirectiveImage treats
 * an absolute URL as the source) and everything else `@file:<name>`.
 */
export function historyAttachmentRefs(raw: unknown, origin = pageOrigin()): string[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const refs: string[] = []

  for (const item of raw) {
    if (!isHistoryAttachment(item) || !item.id) {
      continue
    }

    if (typeof item.content_type === 'string' && item.content_type.startsWith('image/')) {
      refs.push(`@image:${harvisFileUrl(item.id, origin)}`)
    } else {
      refs.push(`@file:${formatRefValue(item.name || item.id)}`)
    }
  }

  return refs
}

/** Open the browser's own file picker; resolves to [] when it is cancelled. */
export function pickBrowserFiles(options: { accept?: string; multiple?: boolean } = {}): Promise<File[]> {
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = options.multiple ?? true

    if (options.accept) {
      input.accept = options.accept
    }

    input.style.display = 'none'

    const finish = () => {
      const files = Array.from(input.files ?? [])
      input.remove()
      resolve(files)
    }

    input.addEventListener('change', finish, { once: true })
    input.addEventListener('cancel', finish, { once: true })
    document.body.appendChild(input)
    input.click()
  })
}

export function readBlobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file'))
    reader.readAsDataURL(blob)
  })
}

// Uploads started from a drop/pick/paste keep running while the person types.
// Submit joins the one for each chip before reading its id (see
// use-prompt-actions/index.ts syncAttachmentsForSubmit).
const inFlight = new Map<string, Promise<ComposerAttachmentPatch>>()

export function trackBrowserUpload(id: string, upload: Promise<ComposerAttachmentPatch>): void {
  inFlight.set(id, upload)
  upload.finally(() => {
    if (inFlight.get(id) === upload) {
      inFlight.delete(id)
    }
  })
}

export function pendingBrowserUpload(id: string): Promise<ComposerAttachmentPatch> | undefined {
  return inFlight.get(id)
}
