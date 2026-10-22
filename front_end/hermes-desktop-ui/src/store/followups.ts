import { atom } from 'nanostores'

/**
 * Follow-up suggestion cards. After an agent run the Harvis backend emits
 * `harvis.followups` ({ items: [{ title, prompt }] }, max 3) just before
 * `message.complete`; the composer dock renders them as one-click cards that
 * start a new chat seeded with `prompt`.
 *
 * Keyed by RUNTIME session id (the id gateway events carry and the composer
 * is mounted with). Cards describe the turn that just ended, so the next
 * `message.start` on the session clears them.
 */
export interface Followup {
  prompt: string
  title: string
}

export const MAX_FOLLOWUPS = 3

export const $followupsBySession = atom<Record<string, Followup[]>>({})

/** Wire payloads are untrusted: keep well-formed, non-empty rows and cap them. */
export function parseFollowups(raw: unknown): Followup[] {
  if (!Array.isArray(raw)) {
    return []
  }

  const items: Followup[] = []

  for (const row of raw) {
    if (!row || typeof row !== 'object') {
      continue
    }

    const { prompt, title } = row as Record<string, unknown>
    const cleanPrompt = typeof prompt === 'string' ? prompt.trim() : ''
    const cleanTitle = typeof title === 'string' ? title.trim() : ''

    if (cleanPrompt && cleanTitle) {
      items.push({ prompt: cleanPrompt, title: cleanTitle })
    }

    if (items.length === MAX_FOLLOWUPS) {
      break
    }
  }

  return items
}

const sameItems = (a: readonly Followup[], b: readonly Followup[]): boolean =>
  a.length === b.length && a.every((item, index) => item.title === b[index].title && item.prompt === b[index].prompt)

/** Replace a session's cards. An empty list removes the entry, and an
 *  unchanged list keeps its reference so subscribers don't re-render. */
export function setSessionFollowups(sessionId: string, items: readonly Followup[]): void {
  if (!sessionId) {
    return
  }

  const current = $followupsBySession.get()

  if (items.length === 0) {
    clearSessionFollowups(sessionId)

    return
  }

  if (current[sessionId] && sameItems(current[sessionId], items)) {
    return
  }

  $followupsBySession.set({ ...current, [sessionId]: [...items] })
}

export function clearSessionFollowups(sessionId: string): void {
  const current = $followupsBySession.get()

  if (!(sessionId in current)) {
    return
  }

  const { [sessionId]: _dropped, ...rest } = current
  $followupsBySession.set(rest)
}

/** Opens a fresh chat and sends `prompt` as its first message. Registered by
 *  the app wiring (the only layer that owns the new-session + send flow). */
export type FollowupStarter = (prompt: string) => Promise<unknown> | unknown

let starter: FollowupStarter | null = null

export function setFollowupStarter(next: FollowupStarter | null): void {
  starter = next
}

/** Start a card's prompt in a new chat and retire the source session's cards.
 *  Returns false (cards kept) when nothing is registered to start it. */
export function startFollowup(sessionId: string, item: Followup): boolean {
  if (!starter) {
    return false
  }

  clearSessionFollowups(sessionId)
  void Promise.resolve(starter(item.prompt)).catch(() => undefined)

  return true
}
