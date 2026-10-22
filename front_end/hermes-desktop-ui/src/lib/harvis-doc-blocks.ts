/**
 * Line-based readings of the rich blocks a `harvis-doc` body may hold. Every
 * parser here is tolerant: a malformed line is skipped (or kept as plain
 * text), and nothing throws, because the panel feeds them half-streamed text.
 * The backend reads the same blocks for export (docs_parse.py / docs_blocks.py).
 */

export const DOC_BLOCK_KINDS = ['timeline', 'chart', 'quadrant', 'cards', 'flow', 'csv'] as const

export type DocBlockKind = (typeof DOC_BLOCK_KINDS)[number]

/** The block a fence info string names (`timeline`, `Chart {x}`), or null for ordinary code. */
export function docBlockKind(language: string | undefined): DocBlockKind | null {
  const word = (language ?? '').trim().split(/\s+/)[0]?.toLowerCase() ?? ''

  return (DOC_BLOCK_KINDS as readonly string[]).includes(word) ? (word as DocBlockKind) : null
}

export interface FenceScan {
  closed: boolean
  language: string
  /** 1-based line of the opening fence, matching markdown node positions. */
  line: number
  /** Character offset where the opening fence line starts. */
  offset: number
}

// Markdown allows at most three spaces before a fence; four make an indented code block.
const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/
const QUOTE_RE = /^ {0,3}>[ ]?/

/** Peels up to `limit` blockquote markers off a line. */
function stripQuotes(line: string, limit = Infinity): { depth: number; rest: string } {
  let rest = line
  let depth = 0

  for (let hit; depth < limit && (hit = QUOTE_RE.exec(rest)); depth++) {
    rest = rest.slice(hit[0].length)
  }

  return { depth, rest }
}

/** Every top-level fenced block in the text, in order, with whether its closing fence has arrived. */
export function scanFences(text: string): FenceScan[] {
  const fences: FenceScan[] = []
  // `depth` is the blockquote nesting the fence opened in; leaving it ends the fence.
  let open: { char: string; depth: number; length: number; scan: FenceScan } | null = null
  let offset = 0
  const lines = text.split('\n')

  for (const [index, raw] of lines.entries()) {
    const start = offset
    const line = raw.replace(/\r$/, '')

    offset += raw.length + 1

    // Text ending in a newline: the next line has not started, so it cannot end anything yet.
    if (!line && index === lines.length - 1 && index > 0) {
      continue
    }

    if (open) {
      const { depth, rest } = stripQuotes(line, open.depth)

      if (depth === open.depth) {
        const match = FENCE_RE.exec(rest)

        if (match && match[1][0] === open.char && match[1].length >= open.length && !match[2].trim()) {
          open.scan.closed = true
          open = null
        }

        continue
      }

      open.scan.closed = true
      open = null
    }

    const match = FENCE_RE.exec(stripQuotes(line).rest)

    if (match && !(match[1][0] === '`' && match[2].includes('`'))) {
      const scan: FenceScan = { closed: false, language: match[2].trim(), line: index + 1, offset: start }

      fences.push(scan)
      open = { char: match[1][0], depth: stripQuotes(line).depth, length: match[1].length, scan }
    }
  }

  return fences
}

export function bodyLines(code: string): string[] {
  return code
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
}

export function metaLine(line: string, keys: readonly string[]): [string, string] | null {
  const match = /^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$/.exec(line)

  if (!match || line.includes('|') || line.includes('->')) {
    return null
  }

  const key = match[1].toLowerCase()

  return keys.includes(key) ? [key, match[2].trim()] : null
}

// ─── chart ──────────────────────────────────────────────────────────────

export type ChartType = 'bar' | 'line' | 'pie'

export interface ChartRow {
  label: string
  values: number[]
}

export interface ChartData {
  /** "$" or "" taken from the first value that carried one. */
  prefix: string
  rows: ChartRow[]
  /** One name per series; a single unnamed series is `['']`. */
  series: string[]
  suffix: string
  title: string
  type: ChartType
}

/** "1,200", "$3.5k", "12%" and plain numbers; null for anything else. */
export function parseChartNumber(token: string): number | null {
  const t = token.trim()
  const clean = t.replace(/[$€£¥,%\s]/g, '')
  const k = /k$/i.test(clean)
  const digits = k ? clean.slice(0, -1) : clean

  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(digits)) {
    return null
  }

  const value = Math.round(Number(digits) * (k ? 1000 : 1) * 1e6) / 1e6

  return Number.isFinite(value) ? value : null
}

export function parseChart(code: string): ChartData {
  const chart: ChartData = { prefix: '', rows: [], series: [''], suffix: '', title: '', type: 'bar' }
  let declared: string[] = []

  for (const line of bodyLines(code)) {
    const meta = metaLine(line, ['title', 'type', 'series'])

    if (meta) {
      const [key, value] = meta

      if (key === 'title') {
        chart.title = value
      } else if (key === 'type') {
        const type = value.toLowerCase()

        chart.type = type.startsWith('line') ? 'line' : ['pie', 'donut', 'doughnut'].includes(type) ? 'pie' : 'bar'
      } else {
        declared = value
          .split(',')
          .map(s => s.trim())
          .filter(Boolean)
      }

      continue
    }

    const colon = line.lastIndexOf(':')

    if (colon <= 0) {
      continue
    }

    // A comma is a thousands mark only when exactly three digits follow it.
    const tokens = line
      .slice(colon + 1)
      .split(/,(?!\d{3}(?!\d))/)
      .map(s => s.trim())
      .filter(Boolean)

    const values = tokens.map(parseChartNumber).filter((v): v is number => v !== null)

    if (!values.length) {
      continue
    }

    if (!chart.prefix && !chart.suffix) {
      const first = tokens.find(t => parseChartNumber(t) !== null) ?? ''

      chart.prefix = /^[-+]?([$€£¥])/.exec(first)?.[1] ?? ''
      chart.suffix = first.endsWith('%') ? '%' : ''
    }

    chart.rows.push({ label: line.slice(0, colon).trim(), values })
  }

  const width = Math.max(declared.length, ...chart.rows.map(r => r.values.length), 1)

  if (declared.length || width > 1) {
    chart.series = Array.from({ length: width }, (_, i) => declared[i] ?? `Series ${i + 1}`)
  }

  chart.rows.forEach(row => {
    while (row.values.length < chart.series.length) {
      row.values.push(0)
    }
  })

  return chart
}

/** 1200 -> "1,200", 3.14159 -> "3.14", with the unit the data carried. */
export function formatChartValue(value: number, prefix = '', suffix = ''): string {
  const body = Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })

  return `${value < 0 ? '-' : ''}${prefix}${body}${suffix}`
}

// ─── quadrant ───────────────────────────────────────────────────────────

export interface QuadrantCell {
  items: string[]
  name: string
}

export interface Quadrant {
  /** Top-left, top-right, bottom-left, bottom-right; always four. */
  cells: QuadrantCell[]
  title: string
  x: string
  y: string
}

export function parseQuadrant(code: string): Quadrant {
  const quadrant: Quadrant = { cells: [], title: '', x: '', y: '' }

  for (const line of bodyLines(code)) {
    const meta = metaLine(line, ['title', 'x', 'y'])

    if (meta) {
      quadrant[meta[0] as 'title' | 'x' | 'y'] = meta[1]
      continue
    }

    if (quadrant.cells.length >= 4) {
      continue
    }

    const colon = line.indexOf(':')
    const name = colon < 0 ? line : line.slice(0, colon).trim()

    if (!name) {
      continue
    }

    const items =
      colon < 0
        ? []
        : line
            .slice(colon + 1)
            .split(',')
            .map(s => s.trim())
            .filter(Boolean)

    quadrant.cells.push({ items, name })
  }

  while (quadrant.cells.length < 4) {
    quadrant.cells.push({ items: [], name: '' })
  }

  return quadrant
}

// ─── cards ──────────────────────────────────────────────────────────────

export interface DocCard {
  detail: string
  highlight: string
  title: string
}

export interface DocCards {
  cards: DocCard[]
  /** From a leading `title: X` line; empty when the block has none. */
  title: string
}

/** The cards of the block, with a leading `title: X` line read as the block's title instead of a card named "title: X". */
export function parseCardsBlock(code: string): DocCards {
  const lines = bodyLines(code)
  const meta = lines.length ? metaLine(lines[0], ['title']) : null

  const cards = (meta ? lines.slice(1) : lines).flatMap(line => {
    const [title = '', highlight = '', ...rest] = line.split('|').map(s => s.trim())

    return title ? [{ detail: rest.filter(Boolean).join(' | '), highlight, title }] : []
  })

  return { cards, title: meta?.[1] ?? '' }
}

export function parseCards(code: string): DocCard[] {
  return parseCardsBlock(code).cards
}

// ─── status chips ───────────────────────────────────────────────────────

export type StatusTone = 'amber' | 'blue' | 'gray' | 'green' | 'red'

const STATUS_TONES: Record<string, StatusTone> = {
  'at risk': 'red',
  blocked: 'red',
  complete: 'green',
  critical: 'red',
  doing: 'blue',
  done: 'green',
  high: 'red',
  'in progress': 'blue',
  low: 'gray',
  medium: 'amber',
  'not started': 'gray',
  'to do': 'gray',
  todo: 'gray'
}

/** Tone for a table cell whose whole text is a status word, else null. */
export function statusTone(cellText: string): StatusTone | null {
  const key = cellText.replace(/\*+/g, '').trim().replace(/\s+/g, ' ').toLowerCase()

  return Object.hasOwn(STATUS_TONES, key) ? STATUS_TONES[key] : null
}
