import type { Person, PersonControls } from './harvis-api'

/** Mirrors the backend's cap (plugins/people/routes.py `_MAX_LIMIT`). */
export const MAX_DAILY_LIMIT = 100_000

/** "3 / 20 today", "3 today", or "Chat off" for a limit of 0. */
export function usageLabel(p: Pick<Person, 'daily_message_limit' | 'messages_today'>): string {
  if (p.daily_message_limit === 0) {
    return 'Chat off'
  }

  return p.daily_message_limit === null
    ? `${p.messages_today} today`
    : `${p.messages_today} / ${p.daily_message_limit} today`
}

/** The messages-per-day box: blank means no limit. */
export function parseLimit(text: string): { ok: true; value: null | number } | { ok: false; error: string } {
  const trimmed = text.trim()

  if (!trimmed) {
    return { ok: true, value: null }
  }

  if (!/^\d+$/.test(trimmed)) {
    return { ok: false, error: 'Use a whole number, or leave it blank for no limit.' }
  }

  const value = Number(trimmed)

  if (value > MAX_DAILY_LIMIT) {
    return { ok: false, error: `At most ${MAX_DAILY_LIMIT.toLocaleString()} a day.` }
  }

  return { ok: true, value }
}

export function toggleModel(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter(m => m !== id) : [...list, id]
}

/** Server models plus any the person is limited to that the server no longer lists. */
export function modelChoices(server: string[], allowed: null | string[]): string[] {
  const extra = (allowed ?? []).filter(m => !server.includes(m))

  return [...server, ...extra]
}

export interface ControlsDraft {
  limit: string
  models: null | string[]
}

export function draftFor(p: Pick<Person, 'allowed_models' | 'daily_message_limit'>): ControlsDraft {
  return {
    limit: p.daily_message_limit === null ? '' : String(p.daily_message_limit),
    models: p.allowed_models === null ? null : [...p.allowed_models]
  }
}

const sameList = (a: null | string[], b: null | string[]) =>
  a === null || b === null ? a === b : a.length === b.length && a.every((m, i) => m === b[i])

/**
 * What Save sends: only the fields the admin changed. An error when the draft
 * cannot be saved as it stands (a bad number, or "only these models" with none picked).
 */
export function patchFrom(
  p: Pick<Person, 'allowed_models' | 'daily_message_limit'>,
  draft: ControlsDraft
): { patch: PersonControls; error: null | string } {
  const limit = parseLimit(draft.limit)

  if (!limit.ok) {
    return { patch: {}, error: limit.error }
  }

  if (draft.models !== null && draft.models.length === 0) {
    return { patch: {}, error: 'Pick at least one model, or choose Any model.' }
  }

  const patch: PersonControls = {}

  if (limit.value !== p.daily_message_limit) {
    patch.daily_message_limit = limit.value
  }

  if (!sameList(draft.models, p.allowed_models)) {
    patch.allowed_models = draft.models
  }

  return { patch, error: null }
}

export function lastSeen(iso: null | string, now = Date.now()): string {
  if (!iso) {
    return 'No messages this week'
  }

  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))

  if (mins < 2) {
    return 'Active just now'
  }

  if (mins < 60) {
    return `Active ${mins} min ago`
  }

  const hours = Math.round(mins / 60)

  if (hours < 24) {
    return `Active ${hours} h ago`
  }

  const days = Math.round(hours / 24)

  return `Active ${days} day${days === 1 ? '' : 's'} ago`
}
