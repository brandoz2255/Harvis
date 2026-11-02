/** Re-read and re-embed sources (`POST /api/notebooks/{id}/reindex`, `.../sources/{sid}/reindex`). */

import { harvisApi } from './api'

export interface ReindexResult {
  message: string
  queued: number
  skipped?: { reason: string; source_id: string; title: null | string }[]
}

export const reindexSource = (notebookId: string, sourceId: string) =>
  harvisApi<ReindexResult>(`/api/notebooks/${notebookId}/sources/${sourceId}/reindex`, { method: 'POST' })

export const reindexNotebook = (notebookId: string) =>
  harvisApi<ReindexResult>(`/api/notebooks/${notebookId}/reindex`, { method: 'POST' })

/** One line for what a notebook-wide re-index did, including why some sources were left alone. */
export function reindexSummary(result: ReindexResult): string {
  const skipped = result.skipped ?? []

  const head = result.queued
    ? `Re-reading ${result.queued} source${result.queued === 1 ? '' : 's'}.`
    : 'Nothing to re-read.'

  if (skipped.length === 0) {
    return head
  }

  return `${head} Skipped ${skipped.length}: ${skipped.map(s => `${s.title || 'Untitled'} (${s.reason})`).join('; ')}`
}
