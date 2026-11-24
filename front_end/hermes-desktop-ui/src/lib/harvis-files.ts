/**
 * Harvis' own file route, `/api/v1/files/<id>/content`, as chat links see it.
 *
 * A made document's `download_url` and an uploaded file both live there. The
 * route has no extension and sends the file as an attachment, so the regular
 * path preview (which guesses the kind from the extension and reads through
 * `/api/fs`) cannot open it. These helpers fetch it with the page's sign-in
 * cookie instead. Only the browser build is same-origin with the backend.
 */

import type { HermesReadFileTextResult } from '@/global'

const HARVIS_FILE_ROUTE_RE = /^\/api\/v1\/files\/[\w-]+\/content\/?$/i
// Backend and facade routes the model may name. They are not files on disk.
const SERVER_ROUTE_RE = /^\/(?:api|hermes-api|ws)(?:[/?#]|$)/i

export function isHarvisFileRoute(target: string | null | undefined): boolean {
  return !!target && HARVIS_FILE_ROUTE_RE.test(target.trim())
}

/** A server route that is not a file, e.g. `/api/chat`. Links to one stay plain links. */
export function isServerRoute(target: string | null | undefined): boolean {
  return !!target && !isHarvisFileRoute(target) && SERVER_ROUTE_RE.test(target.trim())
}

export function canFetchHarvisFiles(): boolean {
  return (
    typeof window !== 'undefined' &&
    (window as { hermesDesktop?: { webShell?: boolean } }).hermesDesktop?.webShell === true
  )
}

export interface HarvisFile {
  blob: Blob
  mimeType: string
  name: string
}

function filenameFrom(disposition: string | null): string {
  if (!disposition) {
    return ''
  }

  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition)?.[1]

  if (star) {
    try {
      return decodeURIComponent(star.trim().replace(/^"|"$/g, ''))
    } catch {
      // fall through to the plain filename
    }
  }

  return (/filename\s*=\s*("?)([^";]+)\1/i.exec(disposition)?.[2] || '').trim()
}

export async function fetchHarvisFile(route: string, fetchImpl: typeof fetch = fetch): Promise<HarvisFile> {
  const res = await fetchImpl(route.trim(), { credentials: 'include' })

  if (!res.ok) {
    throw new Error(
      res.status === 404 ? 'That file is gone or is not yours.' : `${res.status} ${res.statusText}`.trim()
    )
  }

  const blob = await res.blob()
  const mimeType = (res.headers.get('content-type') || blob.type || 'application/octet-stream').split(';')[0].trim()

  return { blob, mimeType: mimeType.toLowerCase(), name: filenameFrom(res.headers.get('content-disposition')) }
}

export function blobDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()

    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the file'))
    reader.readAsDataURL(blob)
  })
}

export async function readHarvisFileDataUrl(route: string): Promise<string> {
  return blobDataUrl((await fetchHarvisFile(route)).blob)
}

export async function readHarvisFileText(route: string): Promise<HermesReadFileTextResult> {
  const file = await fetchHarvisFile(route)
  const bytes = new Uint8Array(await file.blob.arrayBuffer())

  return {
    binary: bytes.subarray(0, 8000).includes(0),
    byteSize: bytes.byteLength,
    mimeType: file.mimeType,
    path: route,
    text: new TextDecoder().decode(bytes)
  }
}

/** Save the file through a temporary link: the browser build has no native save dialog. */
export async function downloadHarvisFile(route: string, fallbackName = 'file'): Promise<void> {
  const file = await fetchHarvisFile(route)
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')

  link.href = url
  link.download = file.name || fallbackName
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
