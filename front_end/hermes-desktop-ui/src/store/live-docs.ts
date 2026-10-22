import { atom } from 'nanostores'

import { openPreview, type PreviewTarget } from './preview'

/**
 * LIVE DOCUMENTS — `harvis-doc` blocks (deck, doc, sheet, pdf) as they are
 * written. The transcript card feeds the source in on every streamed token and
 * the right-rail document view reads it back, so the rail can show a document
 * being built before the message that carries it has finished.
 *
 * Identity: one document = one (session, slug of title). Regenerating "the Q3
 * review" updates the same document in place instead of stacking tabs.
 *
 * Memory-only, like the artifact registry: the transcript is the durable copy
 * and cards re-register as they render.
 */

export interface LiveDoc {
  key: string
  sessionId: string
  source: string
  /** The fence was still open at the last update. */
  streaming: boolean
  updatedAt: number
}

const MAX_LIVE_DOCS = 24

export const $liveDocs = atom<Record<string, LiveDoc>>({})

/** Keys already auto-opened this page load. A tab the user closed mid-stream
 *  stays closed; only the card's Open button brings it back. */
const autoOpened = new Set<string>()

export function liveDocSlug(title: string): string {
  const slug = title
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')

  return slug || 'document'
}

export function liveDocKey(sessionId: string, title: string): string {
  return `${sessionId}:${liveDocSlug(title)}`
}

export function upsertLiveDoc(key: string, sessionId: string, source: string, streaming: boolean): void {
  const docs = $liveDocs.get()
  const existing = docs[key]

  if (existing && existing.source === source && existing.streaming === streaming) {
    return
  }

  const next = { ...docs, [key]: { key, sessionId, source, streaming, updatedAt: Date.now() } }
  const keys = Object.keys(next)

  if (keys.length > MAX_LIVE_DOCS) {
    const oldest = keys.filter(k => k !== key).sort((a, b) => next[a].updatedAt - next[b].updatedAt)[0]

    delete next[oldest]
  }

  $liveDocs.set(next)
}

export function liveDocTarget(key: string, title: string): PreviewTarget {
  return { kind: 'artifact', label: title, source: `doc:${key}`, transient: true, url: `doc:${key}` }
}

/** The registry key behind a `doc:` rail target, or null for any other target. */
export function liveDocKeyFromTarget(target: Pick<PreviewTarget, 'url'>): string | null {
  return target.url.startsWith('doc:') ? target.url.slice(4) : null
}

export function openLiveDoc(key: string, title: string): void {
  autoOpened.add(key)
  openPreview(liveDocTarget(key, title))
}

/** Open the rail on `key` the first time it is asked this page load. Returns
 *  whether it opened. */
export function autoOpenLiveDoc(key: string, title: string): boolean {
  if (autoOpened.has(key)) {
    return false
  }

  openLiveDoc(key, title)

  return true
}

export function clearLiveDocs(): void {
  $liveDocs.set({})
  autoOpened.clear()
}
