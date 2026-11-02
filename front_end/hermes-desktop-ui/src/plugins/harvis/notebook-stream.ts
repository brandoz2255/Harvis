/**
 * Streaming chat over `POST /api/notebooks/{id}/chat/stream` (SSE). Events:
 * `sources` (the numbered passages the model sees), `delta` (answer text as written, with raw
 * `[SOURCE n]` markers), `done` (the saved answer with markers renumbered `[n]`, plus its citations),
 * `error`. `done.answer` is what to show once the stream ends.
 */

import { harvisApi } from './api'
import { asCitation, asCitations, type NotebookCitation } from './notebook-citations'
import { readSse, type SseEvent } from './notebook-shared'

interface ContextSource {
  source_id: string
  title: null | string
}

/** What a summary-based answer was built from. Titles and ids only; the server never puts source text here. */
export interface ContextReport {
  excluded: (ContextSource & { reason: string })[]
  mode: 'overview' | 'summary'
  opened: ContextSource[]
  summarized: ContextSource[]
}

export interface StreamedAnswer {
  answer: string
  citations: NotebookCitation[]
  context: ContextReport | null
  emptyNotebook: boolean
  messageId: null | string
  modelUsed: null | string
  /** No passage was close enough to the question; no model was asked. */
  refused: boolean
  /** The model answered but cited nothing. */
  unsupported: boolean
}

export interface ChatStreamHandlers {
  onDelta: (text: string) => void
  /** Candidate passages, keyed by the `[SOURCE n]` number. Arrives before the first delta. */
  onSources?: (sources: Map<number, NotebookCitation>) => void
}

const flag = (v: unknown) => v === true

const contextSources = (raw: unknown): ContextSource[] =>
  (Array.isArray(raw) ? raw : []).flatMap(item => {
    const r = item as { source_id?: unknown; title?: unknown } | null

    return typeof r?.source_id === 'string'
      ? [{ source_id: r.source_id, title: typeof r.title === 'string' ? r.title : null }]
      : []
  })

export function parseContext(raw: unknown): ContextReport | null {
  const r = raw as { excluded?: unknown; mode?: unknown; opened?: unknown; summarized?: unknown } | null

  if (!r || (r.mode !== 'overview' && r.mode !== 'summary')) {
    return null
  }

  const excluded = (Array.isArray(r.excluded) ? r.excluded : []).flatMap(item => {
    const reason = (item as { reason?: unknown } | null)?.reason

    return contextSources([item]).map(s => ({ ...s, reason: typeof reason === 'string' ? reason : 'no_summary' }))
  })

  return { excluded, mode: r.mode, opened: contextSources(r.opened), summarized: contextSources(r.summarized) }
}

const names = (list: ContextSource[]) => list.map(s => s.title || 'Untitled source').join(', ')

/** One line for under an answer: which sources were read as summaries, and which were left out. Empty when nothing to say. */
export function describeContext(report: ContextReport | null): string {
  if (!report) {
    return ''
  }

  const parts: string[] = []

  if (report.summarized.length) {
    parts.push(
      `${report.mode === 'overview' ? 'Overview from the summaries of' : 'Read as summaries:'} ${names(report.summarized)}.`
    )
  }

  if (report.opened.length) {
    parts.push(`No summary yet, so the start of the text was used for: ${names(report.opened)}.`)
  }

  const noSummary = report.excluded.filter(s => s.reason === 'no_summary')
  const unreadable = report.excluded.length - noSummary.length

  if (noSummary.length) {
    parts.push(`Left out, no summary yet: ${names(noSummary)}. Set them to Full to include them.`)
  }

  if (unreadable) {
    parts.push(`Left out, could not be read: ${unreadable} source${unreadable === 1 ? '' : 's'}.`)
  }

  return parts.join(' ')
}

export function parseSources(data: Record<string, unknown>): Map<number, NotebookCitation> {
  const out = new Map<number, NotebookCitation>()
  const list = Array.isArray(data.sources) ? data.sources : []

  for (const raw of list) {
    const n = (raw as { n?: unknown } | null)?.n
    const citation = asCitation(raw)

    if (citation && typeof n === 'number' && n > 0) {
      out.set(n, { ...citation, index: n })
    }
  }

  return out
}

export function parseDone(data: Record<string, unknown>): StreamedAnswer {
  return {
    answer: typeof data.answer === 'string' ? data.answer : '',
    citations: asCitations(data.citations),
    context: parseContext(data.context),
    emptyNotebook: flag(data.empty_notebook),
    messageId: typeof data.message_id === 'string' ? data.message_id : null,
    modelUsed: typeof data.model_used === 'string' ? data.model_used : null,
    refused: flag(data.refused),
    unsupported: flag(data.unsupported)
  }
}

export class StreamUnavailable extends Error {
  /** True when nothing was shown yet, so asking the JSON route instead repeats nothing the person saw. */
  readonly retryable: boolean

  constructor(message: string, retryable: boolean) {
    super(message)
    this.retryable = retryable
  }
}

/** Resolves with the finished answer, or rejects (`StreamUnavailable`) when the stream failed or never finished. */
export async function streamNotebookChat(
  notebookId: string,
  body: { message: string; model: string; source_ids?: string[]; summary_source_ids?: string[] },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<StreamedAnswer> {
  const state: {
    failure: string
    result: null | StreamedAnswer
    shown: boolean
  } = {
    failure: '',
    result: null,
    shown: false
  }

  const onEvent = ({ data, event }: SseEvent) => {
    if (event === 'sources') {
      handlers.onSources?.(parseSources(data))
    } else if (event === 'delta' && typeof data.text === 'string') {
      state.shown ||= data.text.length > 0
      handlers.onDelta(data.text)
    } else if (event === 'done') {
      state.result = parseDone(data)
    } else if (event === 'error') {
      state.failure =
        typeof data.message === 'string' && data.message ? data.message : 'The answer could not be written.'
    }
  }

  try {
    await readSse(`/api/notebooks/${encodeURIComponent(notebookId)}/chat/stream`, body, onEvent, signal)
  } catch (err) {
    if (signal?.aborted) {
      throw err
    }

    throw new StreamUnavailable(err instanceof Error ? err.message : String(err), !state.shown)
  }

  if (state.failure) {
    throw new StreamUnavailable(state.failure, !state.shown)
  }

  if (!state.result) {
    throw new StreamUnavailable('The answer stream ended early.', !state.shown)
  }

  return state.result
}

export interface ChatConfig {
  length: 'default' | 'longer' | 'shorter'
  output_language: null | string
  persona: null | string
  style: 'analyst' | 'custom' | 'default' | 'learning_guide'
}

export const chatConfigKey = (notebookId: string) => ['harvis', 'notebooks', notebookId, 'chat-config'] as const

export const DEFAULT_CHAT_CONFIG: ChatConfig = {
  length: 'default',
  output_language: null,
  persona: null,
  style: 'default'
}

export const fetchChatConfig = (notebookId: string) =>
  harvisApi<Partial<ChatConfig>>(`/api/notebooks/${encodeURIComponent(notebookId)}/chat-config`).then(c => ({
    ...DEFAULT_CHAT_CONFIG,
    ...c
  }))

export const saveChatConfig = (notebookId: string, config: ChatConfig) =>
  harvisApi<Partial<ChatConfig>>(`/api/notebooks/${encodeURIComponent(notebookId)}/chat-config`, {
    body: JSON.stringify(config),
    method: 'PUT'
  }).then(c => ({ ...DEFAULT_CHAT_CONFIG, ...c }))
