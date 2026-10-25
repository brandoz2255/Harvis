import { atom } from 'nanostores'

import { exportFormats, type HarvisDocExportFormat, type HarvisDocKind, isHarvisDocLanguage } from './harvis-doc'
import { exportHarvisDoc, saveBlob } from './harvis-doc-export'

type Ext = HarvisDocExportFormat['ext']

/** The format a kind downloads first, and the one the preview renders. */
export function primaryExt(kind: HarvisDocKind): Ext {
  return exportFormats(kind)[0].ext
}

/**
 * Second line of a finished file card: "Presentation · PPTX". A PDF is its own
 * noun, so it reads just "PDF".
 */
export function fileFormatLine(kind: HarvisDocKind, noun: string): string {
  const ext = primaryExt(kind).toUpperCase()

  return noun.toUpperCase() === ext ? ext : `${noun} · ${ext}`
}

export interface DocFile {
  source: string
  title: string
}

export async function downloadDocFile(file: DocFile, ext: Ext): Promise<void> {
  const { blob, filename } = await exportHarvisDoc(file.source, ext, file.title)

  saveBlob(filename, blob)
}

/**
 * Every document in its primary format, one after another: browsers (and the
 * desktop shell) ask before saving a burst of simultaneous downloads, and one
 * failure must not stop the rest. Returns how many failed.
 */
export async function downloadAllDocs(
  files: readonly (DocFile & { kind: HarvisDocKind })[],
  onProgress?: (done: number, total: number) => void
): Promise<number> {
  let failed = 0
  let done = 0

  onProgress?.(0, files.length)

  for (const file of files) {
    try {
      await downloadDocFile(file, primaryExt(file.kind))
    } catch {
      failed += 1
    }

    done += 1
    onProgress?.(done, files.length)
  }

  return failed
}

/**
 * Bodies of the `harvis-doc` fences in a message that have a closing fence.
 * Mirrors `openHarvisDocFence` in harvis-doc.ts: a closing fence is the same
 * character, at least as long as the opener, with nothing after it. As in
 * CommonMark, a fence may sit in a list item (the opener's column is its indent): the closer
 * may be indented that far, and body lines lose that indent.
 */
export function closedHarvisDocFences(text: string): string[] {
  if (!/harvis-?doc/i.test(text)) {
    return []
  }

  const out: string[] = []
  let open: {
    body: string[]
    char: string
    indent: number
    isDoc: boolean
    len: number
  } | null = null

  for (const line of text.split('\n')) {
    if (!open) {
      const m = /^( {0,3}(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?)(`{3,}|~{3,})\s*(.*)$/.exec(line)

      if (m) {
        open = {
          body: [],
          char: m[2][0],
          indent: m[1].length,
          isDoc: isHarvisDocLanguage(m[3].split(/\s/)[0]),
          len: m[2].length
        }
      }

      continue
    }

    const close = new RegExp(`^ {0,${open.indent + 3}}(\`{3,}|~{3,})\\s*$`).exec(line)

    if (close && close[1][0] === open.char && close[1].length >= open.len) {
      if (open.isDoc) {
        out.push(open.body.join('\n'))
      }

      open = null
    } else {
      open.body.push(open.indent ? line.replace(new RegExp(`^ {0,${open.indent}}`), '') : line)
    }
  }

  return out
}

export interface DocIssue {
  message: string
  severity: 'error' | 'warn'
  where: string
}

/** The revision request the doc skills recognise (see doc_revision.py). */
export function docFixMessage(issues: readonly DocIssue[]): string {
  return `Fix these issues in the document:\n${issues.map(i => `- ${i.where}: ${i.message}`).join('\n')}`
}

/**
 * `sessionId` is the chat that owns the document (the id its live doc was filed under). The
 * sender resolves it to a runtime chat and resolves `false` when it cannot address that chat
 * or the chat refuses the send; any other result counts as sent.
 */
type DocFixSender = (text: string, sessionId?: string) => Promise<unknown> | unknown

/**
 * How the panel sends a revision turn. The app registers its normal prompt
 * submit here once (same pattern as the follow-up cards' starter); with none
 * registered the "Fix it" button stays disabled rather than guessing at a
 * session.
 */
export const $docFixSender = atom<DocFixSender | null>(null)

export function setDocFixSender(sender: DocFixSender | null): void {
  $docFixSender.set(sender)
}
