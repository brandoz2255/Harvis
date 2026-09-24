/**
 * Shared types, query keys and small helpers for the Notebooks page. Every
 * shape here mirrors python_back_end/notebooks/{models,router}.py exactly.
 */

import { useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'

export interface Source {
  id: string
  type: string
  title: null | string
  status: 'error' | 'pending' | 'processing' | 'ready'
  error_message: null | string
  chunk_count: null | number
  original_filename: null | string
  created_at?: string
}

export interface Citation {
  source_id: null | string
  source_title: null | string
  page: null | number
  quote: null | string
}

export interface ChatMessage {
  role: string
  content: string
  citations: Citation[]
}

export interface Note {
  id: string
  type: 'ai_note' | 'highlight' | 'summary' | 'user_note'
  title: null | string
  content: string
  is_pinned: boolean
  source_meta: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface NotebookInfo {
  id: string
  title: string
  description: null | string
  emoji: null | string
  source_count: number
  note_count: number
  updated_at: string
}

export interface NotebookStats {
  source_count: number
  chunk_count: number
  note_count: number
  message_count: number
  ready_sources: number
  processing_sources: number
}

export interface Transformation {
  id: string
  source_id: null | string
  transformation_type: string
  transformed_content: string
  model_used: null | string
  created_at: string
}

export interface TransformationType {
  id: string
  name: string
  description: string
}

export interface PodcastLine {
  speaker?: string
  dialogue?: string
  text?: string
}

export interface Podcast {
  id: string
  title: string
  status: string
  style: string
  audio_url: null | string
  audio_path: null | string
  duration_seconds: null | number
  outline: null | string
  transcript: PodcastLine[]
  error_message: null | string
  created_at: null | string
}

export const listKey = ['harvis', 'notebooks', 'list'] as const
export const notebookKey = (id: string) => ['harvis', 'notebooks', id] as const
export const sourcesKey = (id: string) => ['harvis', 'notebooks', id, 'sources'] as const
export const notesKey = (id: string) => ['harvis', 'notebooks', id, 'notes'] as const
export const chatKey = (id: string) => ['harvis', 'notebooks', id, 'chat'] as const
export const statsKey = (id: string) => ['harvis', 'notebooks', id, 'stats'] as const
export const transformationsKey = (id: string) => ['harvis', 'notebooks', id, 'transformations'] as const
export const podcastsKey = (id: string) => ['harvis', 'notebooks', id, 'podcasts'] as const

export const sourceLabel = (s: Pick<Source, 'original_filename' | 'title'>) =>
  s.title || s.original_filename || 'Untitled source'

export const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err))

/** `/transformations/types` lists `summary`, but `TransformationRequest.transformation` only accepts `summarize`. */
const TRANSFORM_IDS: Record<string, string> = { summary: 'summarize' }

export const toTransformationType = (id: string) => TRANSFORM_IDS[id] ?? id

export const transformationLabel = (type: string, types?: TransformationType[]) =>
  types?.find(t => toTransformationType(t.id) === type)?.name ??
  type.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())

/** Podcast rows store whatever prefix the frontend of the day used; only the file name is stable. */
export function podcastAudioUrl(p: Pick<Podcast, 'audio_path' | 'audio_url'>): null | string {
  const raw = p.audio_url || p.audio_path

  if (!raw) {
    return null
  }

  const file = raw.split('/').pop()

  return file ? `/api/notebooks/podcasts/tts-audio/${encodeURIComponent(file)}` : null
}

/** Pinned notes first, then newest edit first. */
export const sortNotes = (notes: Note[]) =>
  [...notes].sort((a, b) =>
    a.is_pinned !== b.is_pinned ? (a.is_pinned ? -1 : 1) : Date.parse(b.updated_at) - Date.parse(a.updated_at)
  )

export interface CreateNoteBody {
  type?: Note['type']
  title?: null | string
  content: string
  source_meta?: Record<string, unknown>
  is_pinned?: boolean
}

export const createNote = (notebookId: string, body: CreateNoteBody) =>
  harvisApi<Note>(`/api/notebooks/${notebookId}/notes`, { method: 'POST', body: JSON.stringify(body) })

const MODEL_KEY = 'harvis.notebooks.model'

function readStoredModel() {
  try {
    return window.localStorage.getItem(MODEL_KEY) ?? ''
  } catch {
    return ''
  }
}

/** Chat-capable models from the providers Harvis can reach right now; embedding models can't answer. */
export function useChatModels() {
  return useQuery({
    queryFn: () =>
      harvisApi<{ providers: { status: string; models: string[] }[] }>('/api/workspace/providers').then(r =>
        (r.providers ?? [])
          .filter(p => p.status === 'online')
          .flatMap(p => p.models ?? [])
          .filter(m => !/embed|bge-|minilm/i.test(m))
      ),
    queryKey: ['harvis', 'notebooks', 'models'],
    staleTime: 60_000
  })
}

/** The remembered model when it is online, otherwise a sensible one that is. */
export function useChosenModel() {
  const models = useChatModels()
  const [model, setModel] = useState(readStoredModel)
  const available = models.data ?? []
  const chosen = available.includes(model)
    ? model
    : (available.find(m => /gpt-oss|llama3|qwen/.test(m)) ?? available[0])

  const choose = (value: string) => {
    setModel(value)

    try {
      window.localStorage.setItem(MODEL_KEY, value)
    } catch {
      // storage blocked: the choice lasts for this page only
    }
  }

  return { available, choose, chosen, loading: models.isLoading }
}

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

/** One `event:`/`data:` block of a text/event-stream body. Blocks without JSON data are dropped. */
export function parseSseBlock(block: string): null | SseEvent {
  let event = 'message'
  const data: string[] = []

  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).trimStart())
    }
  }

  if (data.length === 0) {
    return null
  }

  try {
    const parsed: unknown = JSON.parse(data.join('\n'))

    return {
      event,
      data: parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : { value: parsed }
    }
  } catch {
    return null
  }
}

/** POST a JSON body and read the SSE reply (EventSource is GET-only). Resolves when the server closes. */
export async function readSse(
  path: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(path, {
    body: JSON.stringify(body),
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
    signal
  })

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`

    try {
      const err = (await res.json()) as { detail?: unknown }

      if (typeof err.detail === 'string') {
        detail = err.detail
      }
    } catch {
      // non-JSON error body: keep the status line
    }

    throw new Error(detail)
  }

  if (!res.body) {
    throw new Error('The server sent no stream.')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const flush = (block: string) => {
    const parsed = parseSseBlock(block)

    if (parsed) {
      onEvent(parsed)
    }
  }

  for (;;) {
    const { done, value } = await reader.read()

    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })

    let cut = buffer.indexOf('\n\n')

    while (cut !== -1) {
      flush(buffer.slice(0, cut))
      buffer = buffer.slice(cut + 2)
      cut = buffer.indexOf('\n\n')
    }
  }

  if (buffer.trim()) {
    flush(buffer)
  }
}
