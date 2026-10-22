import { reportUnauthorized } from '@/lib/harvis-session'

import type { HarvisDocExportFormat } from './harvis-doc'
import type { DocIssue } from './harvis-doc-files'

export const HARVIS_DOC_PREVIEW_PATH = '/hermes-api/api/harvis/docs/preview'
export const HARVIS_DOC_CHECK_PATH = '/hermes-api/api/harvis/docs/check'

/** A non-2xx answer; `status` tells "sandbox is down" (503) from a real failure. */
export class DocApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'DocApiError'
    this.status = status
  }
}

export interface DocPageRef {
  height: number
  index: number
  url: string
  width: number
}

export interface DocPreviewResult {
  format: string
  page_count: number
  pages: DocPageRef[]
}

export interface DocCheckResult {
  checked: {
    code: boolean
    model?: string
    render?: boolean
    vision: boolean
    vision_busy?: boolean
    vision_partial?: boolean
  }
  issues: DocIssue[]
}

interface DocRequest {
  format?: HarvisDocExportFormat['ext']
  signal?: AbortSignal
  source: string
  title?: string
}

/**
 * Same auth as the export route (`exportHarvisDoc`): same-origin cookie, and a
 * 401 asks the session watcher to re-check.
 */
async function docFetch(path: string, init: RequestInit): Promise<Response> {
  const res = await fetch(path, { credentials: 'include', ...init })

  if (res.ok) {
    return res
  }

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

  throw new DocApiError(res.status, detail)
}

const postJson = (path: string, body: unknown, signal?: AbortSignal) =>
  docFetch(path, {
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
    signal
  })

export async function fetchDocPreview({
  maxPages,
  signal,
  ...req
}: DocRequest & { maxPages?: number }): Promise<DocPreviewResult> {
  const res = await postJson(
    HARVIS_DOC_PREVIEW_PATH,
    {
      format: req.format,
      max_pages: maxPages,
      source: req.source,
      title: req.title || undefined
    },
    signal
  )

  return (await res.json()) as DocPreviewResult
}

/** One page PNG. It needs the cookie, so it cannot be a bare `<img src>`. */
export async function fetchDocPageImage(url: string, signal?: AbortSignal): Promise<Blob> {
  return (await docFetch(url, { signal })).blob()
}

export async function fetchDocCheck({
  signal,
  vision,
  ...req
}: DocRequest & { vision?: boolean }): Promise<DocCheckResult> {
  const res = await postJson(
    HARVIS_DOC_CHECK_PATH,
    {
      format: req.format,
      source: req.source,
      title: req.title || undefined,
      vision: Boolean(vision)
    },
    signal
  )

  return (await res.json()) as DocCheckResult
}
