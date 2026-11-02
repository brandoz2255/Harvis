/**
 * Citation markers in a saved answer. The server now rewrites every marker to
 * `[k]`, but older answers (and models that ignore the format) still carry
 * `【SOURCE 2】`, `[SOURCE 2]`, `[Source 2, Para 3]`, `[SOURCE 1, SOURCE 2]`, `[S2]`.
 * All of them become plain `[n]` so they line up with the numbered list below the answer.
 */

const MARKER = /\s*[[【]\s*(?:sources?|src|s(?=\d))\s*[:#]?\s*\d+[^\]】]*[\]】]/gi
const NUMBER = /\b(?:sources?|src|s)\s*[:#]?\s*(\d+)/gi

export function normalizeCitationMarkers(text: string): string {
  return text.replace(MARKER, marker => {
    const inner = marker.trim().slice(1, -1)
    const first = inner.match(/\d+/)?.[0]
    const numbers = [...inner.matchAll(NUMBER)].map(m => m[1])
    const picked = numbers.length > 0 ? numbers : first ? [first] : []

    return picked.length > 0 ? ' ' + [...new Set(picked)].map(n => `[${n}]`).join(' ') : marker
  })
}

/** A passage an answer leans on, from the stream's `done` event, saved history, or a note's `source_meta`. */
export interface NotebookCitation {
  chunk_id?: null | string
  end_char?: null | number
  /** The `[n]` the answer uses; absent on saved history, where position decides. */
  index?: number
  page?: null | number
  quote?: null | string
  section?: null | string
  snippet?: null | string
  source_id: null | string
  source_title?: null | string
  start_char?: null | number
}

/** The server's answer when no passage was close enough to the question. */
export const REFUSAL_TEXT = 'I could not find that in your sources.'

const str = (v: unknown) => (typeof v === 'string' && v ? v : null)
const offset = (v: unknown) => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null)

export function asCitation(raw: unknown): NotebookCitation | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const r = raw as Record<string, unknown>
  const page = offset(r.page)

  return {
    chunk_id: str(r.chunk_id),
    end_char: offset(r.end_char),
    index: typeof r.index === 'number' && r.index > 0 ? r.index : undefined,
    page: page && page > 0 ? page : null,
    quote: str(r.quote),
    section: str(r.section),
    snippet: str(r.snippet),
    source_id: str(r.source_id),
    source_title: str(r.source_title),
    start_char: offset(r.start_char)
  }
}

/** Tolerant of anything a saved message or note may hold; entries that are not citations are dropped. */
export function asCitations(raw: unknown): NotebookCitation[] {
  return Array.isArray(raw) ? raw.map(asCitation).filter((c): c is NotebookCitation => c !== null) : []
}

/** `[n]` → the citation behind it: its own `index` when it has one, otherwise its place in the list. */
export function citationLookup(citations: readonly NotebookCitation[]): Map<number, NotebookCitation> {
  const out = new Map<number, NotebookCitation>()

  citations.forEach((c, i) => {
    const n = c.index ?? i + 1

    if (!out.has(n)) {
      out.set(n, c)
    }
  })

  return out
}

export const CITE_SCHEME = '#cite-'

const CODE_SPAN = /(```[\s\S]*?```|`[^`\n]*`)/

/**
 * Turns each `[n]` that has a citation into a markdown link `[[n]](cite:n)` so the renderer can make it a
 * button. Code is left alone, as are escaped brackets and `[n](url)` links.
 */
export function linkCitations(markdown: string, known: ReadonlySet<number>): string {
  if (known.size === 0) {
    return markdown
  }

  return markdown
    .split(CODE_SPAN)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(/(\\)?\[(\d{1,3})\](?!\()/g, (m, escaped, n) =>
            escaped || !known.has(Number(n)) ? m : `[[${n}]](${CITE_SCHEME}${n})`
          )
    )
    .join('')
}

/** While an answer streams, a half-written `[SOURCE 1` at the end would flash as raw text. */
export const hidePartialMarker = (partial: string) => partial.replace(/\s*[[【][^\]】]{0,24}$/, '')

const squash = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The words of `needle` as a pattern that ignores differences in line breaks and spacing. */
function looseMatch(content: string, needle: string): null | { end: number; start: number } {
  const words = needle.split(/\s+/).filter(Boolean)

  if (words.length === 0) {
    return null
  }

  const hit = new RegExp(words.map(escapeRe).join('\\s+'), 'i').exec(content)

  return hit ? { end: hit.index + hit[0].length, start: hit.index } : null
}

export interface PassageTarget {
  end_char?: null | number
  page?: null | number
  quote?: null | string
  snippet?: null | string
  start_char?: null | number
}

export interface PassageRange {
  /** `start === end` is a point to scroll to (the top of a page), not text to mark. */
  end: number
  start: number
}

const MAX_NEEDLE = 120

/**
 * Where in the extracted text a citation points. Stored offsets win when the text there still matches the
 * snippet (a re-indexed source can shift them); otherwise the snippet is searched for, ignoring whitespace;
 * otherwise a known page start is the best we can do; otherwise null.
 */
export function locatePassage(
  content: string,
  target: PassageTarget,
  pageStarts?: null | readonly number[]
): null | PassageRange {
  const needle = (target.snippet || target.quote || '')
    .replace(/^[\s.…]+|[\s.…]+$/g, '')
    .slice(0, MAX_NEEDLE)
    .trim()

  const { end_char: end, start_char: start } = target

  if (start != null && end != null && start < end && end <= content.length) {
    const head = squash(needle).slice(0, 40)

    if (!head || squash(content.slice(start, end)).includes(head)) {
      return { end, start }
    }
  }

  if (needle) {
    const found = looseMatch(content, needle) ?? (needle.length > 40 ? looseMatch(content, needle.slice(0, 40)) : null)

    if (found) {
      return found
    }
  }

  const pageStart = target.page ? pageStarts?.[target.page - 1] : undefined

  return pageStart != null && pageStart >= 0 && pageStart <= content.length
    ? { end: pageStart, start: pageStart }
    : null
}

/** What to call a citation in a tooltip or a list: its source, plus the page when known. */
export function citationLabel(c: Pick<NotebookCitation, 'page' | 'source_title'>): string {
  return `${c.source_title || 'Source'}${c.page ? `, page ${c.page}` : ''}`
}

export const citationPassage = (c: Pick<NotebookCitation, 'quote' | 'snippet'>) => (c.snippet || c.quote || '').trim()
