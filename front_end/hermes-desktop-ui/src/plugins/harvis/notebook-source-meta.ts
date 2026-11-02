/** Reads of a source's backend-written metadata: insights progress, suggested questions, ingest notices. */

import type { Source } from './notebook-shared'

export type InsightsState = 'done' | 'error' | 'none' | 'pending'

/** File types the Upload picker offers; the backend reads scanned PDFs with OCR. */
export const UPLOAD_ACCEPT =
  '.pdf,.txt,.md,.docx,.doc,.pptx,.xlsx,.xlsm,.epub,.html,.htm,.csv,.png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.ogg,.webm'

export const UPLOAD_HINT =
  'PDF (scans are read with OCR), Word, PowerPoint, Excel, ePub, text, Markdown, web pages, images, or audio.'

export function insightsState(source: Pick<Source, 'metadata' | 'status'>): InsightsState {
  if (source.status !== 'ready') {
    return 'none'
  }

  const status = source.metadata?.insights_status

  return status === 'done' || status === 'error' || status === 'pending' ? status : 'none'
}

export function suggestedQuestions(source: Pick<Source, 'metadata'>): string[] {
  const raw = source.metadata?.suggested_questions

  return Array.isArray(raw) ? raw.filter((q): q is string => typeof q === 'string' && q.trim().length > 0) : []
}

export const ingestNotice = (source: Pick<Source, 'metadata'>): string => source.metadata?.ingest_notice?.trim() || ''

export const needsReindex = (source: Pick<Source, 'metadata'>): boolean => source.metadata?.needs_reembed === true

/** True while any ready source is still having its summary written, so the list keeps polling. */
export const insightsPending = (sources: readonly Pick<Source, 'metadata' | 'status'>[]): boolean =>
  sources.some(s => insightsState(s) === 'pending')
