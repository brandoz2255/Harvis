import { reportUnauthorized } from '@/lib/harvis-session'

import type { HarvisDocExportFormat } from './harvis-doc'

/** Same-origin Harvis route that turns a `harvis-doc` body into a file. */
export const HARVIS_DOC_EXPORT_PATH = '/hermes-api/api/harvis/docs/export'

export interface HarvisDocExportResult {
  blob: Blob
  filename: string
}

function filenameFromDisposition(header: null | string): string {
  if (!header) {
    return ''
  }

  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(header)

  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))
    } catch {
      // fall through to the plain form
    }
  }

  return /filename\s*=\s*"?([^";]+)"?/i.exec(header)?.[1]?.trim() ?? ''
}

/**
 * POST the document source and return the file bytes. Authenticates the way the
 * other `/hermes-api/api/harvis/*` calls do (`harvisFetch` in
 * app/settings/harvis-api.ts): same-origin cookie, a 401 asks the session
 * watcher to re-check. `harvisFetch` itself always parses JSON, so the blob
 * read lives here.
 */
export async function exportHarvisDoc(
  source: string,
  format: HarvisDocExportFormat['ext'],
  title: string
): Promise<HarvisDocExportResult> {
  const res = await fetch(HARVIS_DOC_EXPORT_PATH, {
    body: JSON.stringify({ format, source, title: title || undefined }),
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    method: 'POST'
  })

  if (!res.ok) {
    if (res.status === 401) {
      reportUnauthorized()
    }

    let detail = `${res.status} ${res.statusText}`

    try {
      const body = (await res.json()) as { detail?: unknown }

      if (typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // non-JSON error body: keep the status line
    }

    throw new Error(detail)
  }

  const fallback = `${
    title
      .trim()
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/^-+|-+$/g, '') || 'document'
  }.${format}`

  return {
    blob: await res.blob(),
    filename: filenameFromDisposition(res.headers.get('content-disposition')) || fallback
  }
}

/** Hand a blob to the browser (Electron shows its own save dialog). */
export function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')

  link.href = url
  link.download = filename
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
