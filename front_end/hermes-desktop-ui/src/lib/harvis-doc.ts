/**
 * The `harvis-doc` fence: one block the model writes when asked for a deck,
 * document, spreadsheet or PDF. It is parsed on every streamed token, so every
 * function here must accept a truncated prefix of a valid block and return the
 * best reading of what has arrived so far.
 *
 *   ````harvis-doc
 *   ---
 *   kind: deck            (deck | doc | sheet | pdf)
 *   title: Q3 Security Review
 *   outline:
 *     - Title
 *     - Threat landscape
 *   ---
 *   # Q3 Security Review          (deck: slides split on lines that are exactly ---)
 *   ---
 *   ## Threat landscape           (doc/pdf: sections split on ## headings)
 *   ````                          (sheet: one ## Sheet name + markdown table per sheet)
 *
 * The backend parses the same block for export (plugins/hermes_ui/docs_parse.py);
 * keep the two readings in step.
 */

export const HARVIS_DOC_LANGUAGE = 'harvis-doc'

export type HarvisDocKind = 'deck' | 'doc' | 'pdf' | 'sheet'

export const HARVIS_DOC_KINDS: readonly HarvisDocKind[] = ['deck', 'doc', 'pdf', 'sheet']

export interface HarvisDocSection {
  /** Markdown body without the section's own heading line. */
  body: string
  /** Heading text, or the outline label when the section has no heading yet. */
  title: string
}

export interface HarvisDocSheet {
  name: string
  /** Header row first. Cells are raw strings; a leading `=` marks a formula. */
  rows: string[][]
}

export interface HarvisDoc {
  /** The header's closing `---` has arrived. Before that only kind/title may be known. */
  headerComplete: boolean
  kind: HarvisDocKind
  outline: string[]
  sections: HarvisDocSection[]
  /** Sheet kind only; empty otherwise. */
  sheets: HarvisDocSheet[]
  title: string
}

const FENCE_RE = /^\s*-{3,}\s*$/
const HEADING_RE = /^(#{1,6})\s+(.*?)\s*#*\s*$/
const CODE_FENCE_RE = /^\s*(`{3,}|~{3,})/

function normalizeKind(value: string): HarvisDocKind {
  const v = value.trim().toLowerCase()

  if (v === 'deck' || v === 'slides' || v === 'presentation' || v === 'pptx') {
    return 'deck'
  }

  if (v === 'sheet' || v === 'spreadsheet' || v === 'xlsx' || v === 'excel' || v === 'csv') {
    return 'sheet'
  }

  if (v === 'pdf') {
    return 'pdf'
  }

  return 'doc'
}

function unquote(value: string): string {
  const v = value.trim()

  if (v.length >= 2 && ((v[0] === '"' && v.endsWith('"')) || (v[0] === "'" && v.endsWith("'")))) {
    return v.slice(1, -1)
  }

  return v
}

interface Header {
  closed: boolean
  kind: HarvisDocKind
  outline: string[]
  rest: string
  title: string
}

function parseHeader(source: string): Header {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  // The last line has no newline after it yet, so it may be half a word.
  const tailOpen = !/\n$/.test(source.replace(/\r\n?/g, '\n'))
  let i = 0

  while (i < lines.length && !lines[i].trim()) {
    i++
  }

  // Nothing yet, or the first one or two dashes of the opening fence.
  if (i >= lines.length || (i === lines.length - 1 && tailOpen && /^\s*-{1,2}\s*$/.test(lines[i]))) {
    return { closed: false, kind: 'doc', outline: [], rest: '', title: '' }
  }

  // No front matter at all: the whole block is body.
  if (!FENCE_RE.test(lines[i])) {
    return { closed: true, kind: 'doc', outline: [], rest: lines.slice(i).join('\n'), title: '' }
  }

  let kind: HarvisDocKind = 'doc'
  let title = ''
  const outline: string[] = []
  let inOutline = false

  for (i = i + 1; i < lines.length; i++) {
    const line = lines[i]

    if (FENCE_RE.test(line)) {
      // Small models copy a "<body>" placeholder from the prompt; it is never content.
      const rest = lines.slice(i + 1).filter(l => !BODY_TAG_RE.test(l))

      return { closed: true, kind, outline, rest: rest.join('\n'), title }
    }

    // A half-typed title, kind or outline label must not leak into the
    // reading: the title keys the live document, so it only counts once whole.
    if (tailOpen && i === lines.length - 1) {
      break
    }

    const item = /^\s*[-*]\s+(.*)$/.exec(line)

    if (inOutline && item) {
      const label = unquote(item[1])

      if (label) {
        outline.push(label)
      }

      continue
    }

    const pair = /^\s*([A-Za-z_]+)\s*:\s*(.*)$/.exec(line)

    if (!pair) {
      continue
    }

    const key = pair[1].toLowerCase()
    const value = pair[2]
    inOutline = false

    if (key === 'kind' || key === 'type') {
      // "kind: deck   # deck | doc | ..." is how the contract's own example reads.
      kind = normalizeKind(unquote(value.split(' #')[0]))
    } else if (key === 'title') {
      title = unquote(value)
    } else if (key === 'outline' || key === 'sections' || key === 'slides' || key === 'sheets') {
      const inline = /^\[(.*?)\]?\s*$/.exec(value.trim())

      if (inline && value.trim()) {
        outline.push(...inline[1].split(',').map(unquote).filter(Boolean))
      } else {
        inOutline = true
      }
    }
  }

  return { closed: false, kind, outline, rest: '', title }
}

/** Drop a final line that is only the first characters of a heading or `---`
 *  separator, so it does not flash as body text before it becomes structure. */
function dropPartialTail(body: string): string {
  const cut = body.lastIndexOf('\n') + 1

  return /^(#{1,6}|-{1,2})$/.test(body.slice(cut).trim()) ? body.slice(0, cut) : body
}

function splitSlides(body: string): HarvisDocSection[] {
  const slides: string[][] = [[]]
  let inCode = false

  for (const line of body.split('\n')) {
    if (CODE_FENCE_RE.test(line)) {
      inCode = !inCode
    }

    const heading = inCode ? null : HEADING_RE.exec(line)
    const current = slides[slides.length - 1]

    if (!inCode && FENCE_RE.test(line)) {
      slides.push([])
    } else if (heading && heading[1].length <= 2 && current.some(l => l.trim())) {
      // Small models forget the `---`: a new title is a new slide.
      slides.push([line])
    } else {
      current.push(line)
    }
  }

  return slides
    .map(lines => lines.join('\n').trim())
    .filter(Boolean)
    .map(text => {
      const lines = text.split('\n')
      const heading = HEADING_RE.exec(lines[0])

      return heading ? { body: lines.slice(1).join('\n').trim(), title: heading[2] } : { body: text, title: '' }
    })
}

function splitSections(body: string): HarvisDocSection[] {
  const sections: HarvisDocSection[] = []
  let current: { lines: string[]; title: string } | null = null
  const lead: string[] = []
  let inCode = false

  for (const line of body.split('\n')) {
    // A `## ` inside a code fence is code, not a section (same as docs_parse.py).
    if (CODE_FENCE_RE.test(line)) {
      inCode = !inCode
    }

    const heading = inCode ? null : HEADING_RE.exec(line)

    // `#` is the document title and `###`+ live inside a section; `##` starts one.
    if (heading && heading[1].length === 2) {
      if (current) {
        sections.push({ body: current.lines.join('\n').trim(), title: current.title })
      }

      current = { lines: [], title: heading[2] }
    } else if (current) {
      current.lines.push(line)
    } else if (!(heading && heading[1].length === 1)) {
      lead.push(line)
    }
  }

  if (current) {
    sections.push({ body: current.lines.join('\n').trim(), title: current.title })
  }

  const intro = lead.join('\n').trim()

  return intro ? [{ body: intro, title: '' }, ...sections] : sections
}

const BODY_TAG_RE = /^\s*<\/?body>\s*$/i
const CELL_EMPHASIS_RE = /^(\*\*|__)(.+)\1$/

/** A sheet cell as shown: models bold whole cells (`**Total**`); the export keeps that as bold, so does the grid. */
export function sheetCellDisplay(raw: string): { bold: boolean; text: string } {
  const m = CELL_EMPHASIS_RE.exec(raw.trim())

  return m ? { bold: true, text: m[2].trim() } : { bold: false, text: raw }
}

function splitRow(line: string): string[] {
  let row = line.trim()

  if (row.startsWith('|')) {
    row = row.slice(1)
  }

  if (row.endsWith('|') && !row.endsWith('\\|')) {
    row = row.slice(0, -1)
  }

  return row.split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'))
}

const DIVIDER_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

export function parseSheetTable(body: string): string[][] {
  const rows: string[][] = []

  for (const line of body.split('\n')) {
    if (!line.includes('|') || DIVIDER_RE.test(line)) {
      continue
    }

    rows.push(splitRow(line))
  }

  return rows
}

/** Parse a whole or partial `harvis-doc` block. Never throws. */
export function parseHarvisDoc(source: string): HarvisDoc {
  const header = parseHeader(source ?? '')
  const body = dropPartialTail(header.rest)

  if (!header.closed) {
    return {
      headerComplete: false,
      kind: header.kind,
      outline: header.outline,
      sections: [],
      sheets: [],
      title: header.title
    }
  }

  let sections = header.kind === 'deck' ? splitSlides(body) : splitSections(body)
  let title = header.title

  if (!title) {
    const h1 = body
      .split('\n')
      .map(line => HEADING_RE.exec(line))
      .find(m => m && m[1].length === 1)
    title = h1?.[2] ?? sections[0]?.title ?? ''
  }

  // A doc whose only lead text is the H1 line shows nothing in its intro.
  sections = sections.filter((s, i) => s.title || s.body || i === sections.length - 1)

  const sheets =
    header.kind === 'sheet'
      ? sections
          .filter(s => s.title || s.body.includes('|'))
          .map((s, i) => ({ name: s.title || header.outline[i] || `Sheet${i + 1}`, rows: parseSheetTable(s.body) }))
      : []

  return { headerComplete: true, kind: header.kind, outline: header.outline, sections, sheets, title }
}

/** Parts written so far: slides, sheets, or titled sections (a leading intro is not counted). */
export function arrivedParts(doc: HarvisDoc): number {
  if (doc.kind === 'sheet') {
    return doc.sheets.length
  }

  return doc.kind === 'deck' ? doc.sections.length : doc.sections.filter(s => s.title).length
}

/** Number of parts the finished document will have: the outline, or what has arrived if longer. */
export function expectedParts(doc: HarvisDoc): number {
  return Math.max(doc.outline.length, arrivedParts(doc))
}

export interface HarvisDocExportFormat {
  ext: 'csv' | 'docx' | 'md' | 'pdf' | 'pptx' | 'xlsx'
  label: string
}

/** Download formats per kind, primary first. */
export function exportFormats(kind: HarvisDocKind): HarvisDocExportFormat[] {
  switch (kind) {
    case 'deck':
      return [
        { ext: 'pptx', label: 'PowerPoint' },
        { ext: 'pdf', label: 'PDF' }
      ]
    case 'sheet':
      return [
        { ext: 'xlsx', label: 'Excel' },
        { ext: 'csv', label: 'CSV' }
      ]
    case 'pdf':
      return [
        { ext: 'pdf', label: 'PDF' },
        { ext: 'docx', label: 'Word' }
      ]
    default:
      return [
        { ext: 'docx', label: 'Word' },
        { ext: 'pdf', label: 'PDF' },
        { ext: 'md', label: 'Markdown' }
      ]
  }
}

/** True for the fence language the model uses for these blocks. */
export function isHarvisDocLanguage(language: string | undefined): boolean {
  const lang = (language ?? '').trim().toLowerCase()

  return lang === HARVIS_DOC_LANGUAGE || lang === 'harvisdoc'
}

/**
 * Body of the LAST `harvis-doc` fence in `text` when that fence has not been
 * closed yet, else null. The fence renderer only sees the body, not whether a
 * closing fence follows, so the transcript uses this to tell a document still
 * being written from one the model finished while the message keeps going.
 */
export function openHarvisDocFence(text: string): string | null {
  if (!/harvis-?doc/i.test(text)) {
    return null
  }

  let open: { char: string; isDoc: boolean; len: number; start: number } | null = null
  let offset = 0

  for (const line of text.split('\n')) {
    const next = offset + line.length + 1

    if (!open) {
      const m = /^ {0,3}(`{3,}|~{3,})\s*(.*)$/.exec(line)

      if (m) {
        open = { char: m[1][0], isDoc: isHarvisDocLanguage(m[2].split(/\s/)[0]), len: m[1].length, start: next }
      }
    } else {
      const m = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line)

      if (m && m[1][0] === open.char && m[1].length >= open.len) {
        open = null
      }
    }

    offset = next
  }

  return open?.isDoc ? text.slice(Math.min(open.start, text.length)) : null
}

/** Spreadsheet column letters: 0 → A, 25 → Z, 26 → AA. */
export function columnLetter(index: number): string {
  let n = index + 1
  let out = ''

  while (n > 0) {
    const r = (n - 1) % 26
    out = String.fromCharCode(65 + r) + out
    n = Math.floor((n - 1) / 26)
  }

  return out
}
