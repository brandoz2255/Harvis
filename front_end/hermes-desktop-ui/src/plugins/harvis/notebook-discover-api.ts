/** Calls and shapes for Discover: web search results, deep-research runs, adding pages as sources. */

import { harvisApi } from './api'

export interface FoundPage {
  site: string
  snippet: string
  title: string
  url: string
}

export interface AddResult {
  added: { id: string; title: string; url: string }[]
  skipped: { reason: string; url: string }[]
}

export interface DeepStatus {
  error?: string
  message: string
  phase: string
  query: string
  session_id: string
  status: 'cancelled' | 'done' | 'error' | 'running' | string
}

export interface DeepImport {
  already_added: boolean
  cited: FoundPage[]
  source: { id: string; title: string }
}

const base = (notebookId: string) => `/api/notebooks/${encodeURIComponent(notebookId)}/discover`

const post = <T>(path: string, body?: unknown) =>
  harvisApi<T>(path, { method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) })

export const searchWeb = (notebookId: string, query: string) =>
  post<{ message?: string; results: FoundPage[] }>(`${base(notebookId)}/search`, { max_results: 8, query })

export const addPages = (notebookId: string, pages: Pick<FoundPage, 'title' | 'url'>[]) =>
  post<AddResult>(`${base(notebookId)}/add`, { items: pages.map(p => ({ title: p.title, url: p.url })) })

export const startDeep = (notebookId: string, query: string, model?: null | string) =>
  post<{ session_id: string }>(`${base(notebookId)}/deep`, { model: model || undefined, query })

export const deepStatus = (notebookId: string, sessionId: string) =>
  harvisApi<DeepStatus>(`${base(notebookId)}/deep/${encodeURIComponent(sessionId)}`)

export const cancelDeep = (notebookId: string, sessionId: string) =>
  post<{ cancelled: boolean }>(`${base(notebookId)}/deep/${encodeURIComponent(sessionId)}/cancel`)

export const importDeep = (notebookId: string, sessionId: string) =>
  post<DeepImport>(`${base(notebookId)}/deep/${encodeURIComponent(sessionId)}/import`)

/** "Added 3 sources. 1 skipped: Already in this notebook." */
export function addSummary(r: AddResult): string {
  const added = r.added.length
  const head =
    added === 0 ? 'Nothing was added.' : `Added ${added} source${added === 1 ? '' : 's'}; they are being read now.`
  const reasons = [...new Set(r.skipped.map(s => s.reason))]

  return reasons.length > 0 ? `${head} Skipped ${r.skipped.length}: ${reasons.join(' ')}` : head
}
