import { arrivedParts, type HarvisDoc, type HarvisDocSection } from '@/lib/harvis-doc'

export type DocPartState = 'active' | 'done' | 'pending'

export interface DocPart {
  index: number
  /** Heading or outline name; empty for an untitled intro. */
  label: string
  /** Null while the part is only an outline entry. */
  section: HarvisDocSection | null
  state: DocPartState
}

/**
 * The parts a document view lays out: what has been written, then the outline
 * entries still to come (only while streaming; a finished document does not
 * keep skeletons for parts the model never wrote). The last written part is
 * `active` while streaming.
 */
export function buildDocParts(doc: HarvisDoc, streaming: boolean): DocPart[] {
  const written: { label: string; section: HarvisDocSection | null }[] =
    doc.kind === 'sheet'
      ? doc.sheets.map(sheet => ({ label: sheet.name, section: null }))
      : doc.sections.map(section => ({ label: section.title, section }))

  const titled = arrivedParts(doc)
  const parts: DocPart[] = written.map((part, index) => ({
    ...part,
    index,
    state: streaming && index === written.length - 1 ? 'active' : 'done'
  }))

  if (streaming) {
    doc.outline.slice(titled).forEach((label, i) => {
      parts.push({ index: written.length + i, label, section: null, state: 'pending' })
    })
  }

  return parts
}

/** Index of the part being written right now, or -1. */
export function liveIndex(parts: DocPart[]): number {
  return parts.findIndex(part => part.state === 'active')
}

const NOTES_RE = /^\s*(?:speaker\s+)?notes?\s*:\s*(.*)$/i

/** Split a slide body into what is shown and its speaker notes (from the first `Notes:` line). */
export function splitNotes(body: string): { notes: string; text: string } {
  const lines = body.split('\n')
  const at = lines.findIndex(line => NOTES_RE.test(line))

  if (at < 0) {
    return { notes: '', text: body }
  }

  const first = NOTES_RE.exec(lines[at])?.[1] ?? ''

  return {
    notes: [first, ...lines.slice(at + 1)].join('\n').trim(),
    text: lines.slice(0, at).join('\n').trimEnd()
  }
}
