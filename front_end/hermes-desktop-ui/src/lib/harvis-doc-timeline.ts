/** Dates and the timeline block. Tolerant like the rest of harvis-doc-blocks: never throws. */

import { bodyLines, metaLine } from './harvis-doc-blocks'

// ─── dates ──────────────────────────────────────────────────────────────

const MONTHS = [
  'january',
  'february',
  'march',
  'april',
  'may',
  'june',
  'july',
  'august',
  'september',
  'october',
  'november',
  'december'
]

export const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAY_MS = 86_400_000

// Whole month names, their three-letter forms and "sept": the same spellings the export reads.
function monthIndex(word: string): number {
  const w = word.toLowerCase()

  return MONTHS.findIndex(name => name === w || name.slice(0, 3) === w || (w === 'sept' && name === 'september'))
}

function utc(year: number, month: number, day: number): number | null {
  if (year < 1900 || year > 2200) {
    return null
  }

  const ms = Date.UTC(year, month, day)
  const back = new Date(ms)

  return back.getUTCFullYear() === year && back.getUTCMonth() === month && back.getUTCDate() === day ? ms : null
}

export interface ParsedDate {
  hasYear: boolean
  ms: number
}

/** ISO, "Oct 26", "Oct 26 2026", "26 Oct"; a missing year is `defaultYear`. Null when it is not a date. */
export function parseDocDate(text: string, defaultYear: number): ParsedDate | null {
  const t = text.trim().replace(/\s+/g, ' ')
  let y: number | undefined
  let m = -1
  let d = 0
  let explicit = false
  let hit: RegExpExecArray | null

  if ((hit = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t))) {
    ;[y, m, d, explicit] = [+hit[1], +hit[2] - 1, +hit[3], true]
  } else if ((hit = /^([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?$/.exec(t))) {
    ;[m, d] = [monthIndex(hit[1]), +hit[2]]

    if (hit[3]) {
      ;[y, explicit] = [+hit[3], true]
    }
  } else if ((hit = /^(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3,9})\.?(?:,? (\d{4}))?$/.exec(t))) {
    ;[m, d] = [monthIndex(hit[2]), +hit[1]]

    if (hit[3]) {
      ;[y, explicit] = [+hit[3], true]
    }
  }

  if (m < 0 || m > 11 || d < 1) {
    return null
  }

  const ms = utc(y ?? defaultYear, m, d)

  return ms === null ? null : { hasYear: explicit, ms }
}

// ─── timeline ───────────────────────────────────────────────────────────

export interface TimelineItem {
  /** Date text as written, "Oct 26 to Nov 1" for a span. */
  dateText: string
  end: number | null
  endText: string
  /** The `*` marked milestone, drawn in the accent colour. */
  key: boolean
  label: string
  span: boolean
  start: number | null
  startText: string
}

export interface Timeline {
  items: TimelineItem[]
  /** Every item has a parseable date, so the bars are drawn to scale. */
  scaled: boolean
  subtitle: string
  title: string
}

export interface TimelineOptions {
  /** Year for dates written without one; defaults to the current year. */
  year?: number
}

export function parseTimeline(code: string, options: TimelineOptions = {}): Timeline {
  const year = options.year ?? new Date().getFullYear()
  const timeline: Timeline = { items: [], scaled: false, subtitle: '', title: '' }

  for (const line of bodyLines(code)) {
    const meta = metaLine(line, ['title', 'subtitle'])

    if (meta) {
      timeline[meta[0] as 'subtitle' | 'title'] = meta[1]
      continue
    }

    const cells = line.split('|').map(cell => cell.trim())
    const key = cells[0].startsWith('*')
    const label = cells[0].replace(/^\*+\s*/, '')

    // An item needs a date cell; a prose line must not turn off the to-scale layout.
    if (!label || !cells[1]) {
      continue
    }

    const startText = cells[1] ?? ''
    const endText = cells[2] ?? ''
    const start = startText ? parseDocDate(startText, year) : null
    const end = endText ? parseDocDate(endText, year) : null
    const span = Boolean(endText)
    let [from, to] = [start?.ms ?? null, end?.ms ?? null]

    if (span && from !== null && to !== null && to < from) {
      // "Dec 20 to Jan 5": the end belongs to the next year unless it says otherwise.
      const next = end && !end.hasYear ? parseDocDate(endText, year + 1) : null

      if (next) {
        to = next.ms
      }

      if (to < from) {
        ;[from, to] = [to, from]
      }
    }

    timeline.items.push({
      dateText: span ? `${startText} to ${endText}` : startText,
      end: span ? to : null,
      endText,
      key,
      label,
      span,
      start: from,
      startText
    })
  }

  timeline.scaled =
    timeline.items.length > 0 && timeline.items.every(i => i.start !== null && (!i.span || i.end !== null))

  return timeline
}

/** First and last instant a scaled timeline covers; a single day gets a day of margin each side. */
export function timelineRange(timeline: Timeline): { max: number; min: number } {
  const stamps = timeline.items.flatMap(i => [i.start, i.end]).filter((v): v is number => v !== null)

  if (!stamps.length) {
    return { max: DAY_MS, min: 0 }
  }

  const [min, max] = [Math.min(...stamps), Math.max(...stamps)]

  return min === max ? { max: max + DAY_MS, min: min - DAY_MS } : { max, min }
}

/** Week ticks from the first date, thinned so there are never more than `limit`. */
export function weekTicks(min: number, max: number, limit = 10): { label: string; ms: number }[] {
  const weeks = Math.max(1, Math.floor((max - min) / (7 * DAY_MS)) + 1)
  const step = Math.max(1, Math.ceil(weeks / limit))
  const ticks: { label: string; ms: number }[] = []

  for (let ms = min; ms <= max; ms += 7 * DAY_MS * step) {
    ticks.push({ label: formatDay(ms), ms })
  }

  return ticks
}

export function formatDay(ms: number): string {
  const d = new Date(ms)

  return `${MONTH_ABBR[d.getUTCMonth()]} ${d.getUTCDate()}`
}
