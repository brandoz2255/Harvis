/**
 * What the notebook's chat should read, shared between the Sources tab (which
 * sets it) and the chat (which sends it), plus a one-slot "ask this" mailbox so
 * a suggested question on a source can land in the chat box.
 *
 * Contract for the chat: call `contextPayload(notebookId, sources)` and send it
 * as `context` to `/onb-api/chat/execute`. Every ready source appears with its
 * mode ('off' | 'insights' | 'full'); the server drops 'off' ones and answers
 * "no sources in context" when all are off. `selectedSourceIds` is the same
 * choice as a plain id list for routes that only take `source_ids`; the native chat also
 * sends `summarySourceIds` (a subset of it) so those sources are read as summaries.
 */

import { useSyncExternalStore } from 'react'

import type { Source } from './notebook-shared'

export type ContextLevel = 'full' | 'insights' | 'off'

export const CONTEXT_LEVELS: { description: string; id: ContextLevel; label: string }[] = [
  { description: 'Chat reads the whole source', id: 'full', label: 'Full' },
  { description: 'Chat reads only the summary and key points', id: 'insights', label: 'Summary' },
  { description: 'Chat ignores this source', id: 'off', label: 'Off' }
]

export const DEFAULT_LEVEL: ContextLevel = 'full'

const STORE_KEY = 'harvis.notebooks.context-levels'

type Levels = Record<string, ContextLevel>

const isLevel = (v: unknown): v is ContextLevel => v === 'full' || v === 'insights' || v === 'off'

function load(): Record<string, Levels> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORE_KEY) ?? '{}')

    if (!parsed || typeof parsed !== 'object') {
      return {}
    }

    const out: Record<string, Levels> = {}

    for (const [nb, levels] of Object.entries(parsed as Record<string, unknown>)) {
      if (levels && typeof levels === 'object') {
        out[nb] = Object.fromEntries(Object.entries(levels).filter(([, v]) => isLevel(v))) as Levels
      }
    }

    return out
  } catch {
    return {}
  }
}

let state: Record<string, Levels> = load()
const listeners = new Set<() => void>()

function commit(next: Record<string, Levels>) {
  state = next

  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(next))
  } catch {
    // storage blocked: the choice lasts for this page only
  }

  listeners.forEach(l => l())
}

const subscribe = (l: () => void) => {
  listeners.add(l)

  return () => void listeners.delete(l)
}

const NONE: Levels = {}

export const getContextLevels = (notebookId: string): Levels => state[notebookId] ?? NONE

export const levelOf = (levels: Levels, sourceId: string): ContextLevel => levels[sourceId] ?? DEFAULT_LEVEL

export function setContextLevel(notebookId: string, sourceId: string, level: ContextLevel) {
  const current = { ...(state[notebookId] ?? {}) }

  if (level === DEFAULT_LEVEL) {
    delete current[sourceId]
  } else {
    current[sourceId] = level
  }

  commit({ ...state, [notebookId]: current })
}

export function useContextLevels(notebookId: string): Levels {
  return useSyncExternalStore(
    subscribe,
    () => getContextLevels(notebookId),
    () => NONE
  )
}

const readable = (sources: readonly Source[]) => sources.filter(s => s.status === 'ready')

/** The `context` body for `/onb-api/chat/execute`: one entry per ready source with its level. */
export function contextPayload(notebookId: string, sources: readonly Source[]) {
  const levels = getContextLevels(notebookId)

  return {
    notes: [] as { id: string; mode: ContextLevel }[],
    sources: readable(sources).map(s => ({ id: s.id, mode: levelOf(levels, s.id) }))
  }
}

/** Ids of the ready sources the chat may read (anything not 'off'). */
export function selectedSourceIds(notebookId: string, sources: readonly Source[]): string[] {
  const levels = getContextLevels(notebookId)

  return readable(sources)
    .filter(s => levelOf(levels, s.id) !== 'off')
    .map(s => s.id)
}

/** Ids of the ready sources set to Summary: the chat reads their stored summary instead of searching them. */
export function summarySourceIds(notebookId: string, sources: readonly Source[]): string[] {
  const levels = getContextLevels(notebookId)

  return readable(sources)
    .filter(s => levelOf(levels, s.id) === 'insights')
    .map(s => s.id)
}

/** True when every ready source is read in full, so a request needs no source list at all. */
export const isDefaultSelection = (notebookId: string, sources: readonly Source[]): boolean => {
  const levels = getContextLevels(notebookId)

  return readable(sources).every(s => levelOf(levels, s.id) === DEFAULT_LEVEL)
}

// --- "Ask this" mailbox ----------------------------------------------------------

export interface Pending {
  at: number
  notebookId: string
  text: string
}

let pending: null | Pending = null
const pendingListeners = new Set<() => void>()

/** Hand a question to the notebook's chat. The chat takes it with `takePendingQuestion`. */
export function requestQuestion(notebookId: string, text: string) {
  pending = { at: Date.now(), notebookId, text }
  pendingListeners.forEach(l => l())
}

const subscribePending = (l: () => void) => {
  pendingListeners.add(l)

  return () => void pendingListeners.delete(l)
}

/** The queued question for this notebook, or null. A new request is a new object even when the text repeats. */
export function usePendingQuestion(notebookId: string): null | Pending {
  return useSyncExternalStore(
    subscribePending,
    () => (pending?.notebookId === notebookId ? pending : null),
    () => null
  )
}

/** Clear the mailbox once the chat has used the question. */
export function takePendingQuestion(notebookId: string): string {
  if (pending?.notebookId !== notebookId) {
    return ''
  }

  const { text } = pending
  pending = null
  pendingListeners.forEach(l => l())

  return text
}
