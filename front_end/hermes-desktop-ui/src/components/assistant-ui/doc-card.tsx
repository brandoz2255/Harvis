'use client'

import { useMessagePartText } from '@assistant-ui/react'
import { useStore } from '@nanostores/react'
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'

import { DocExportControl } from '@/app/chat/right-rail/preview-document-export'
import { useSessionView } from '@/app/chat/session-view'
import { CodeCardIcon } from '@/components/chat/code-card'
import { WIDGET_SHELL_CLASS } from '@/components/chat/widget-shell'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { arrivedParts, expectedParts, type HarvisDocKind, parseHarvisDoc } from '@/lib/harvis-doc'
import { closedHarvisDocFences, downloadAllDocs, fileFormatLine } from '@/lib/harvis-doc-files'
import { Download, Loader2 } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { autoOpenLiveDoc, liveDocKey, openLiveDoc, upsertLiveDoc } from '@/store/live-docs'

export const DOC_KIND_ICON: Record<HarvisDocKind, string> = {
  deck: 'layout',
  doc: 'file',
  pdf: 'file-pdf',
  sheet: 'table'
}

interface DocCardProps {
  /** The turn ended with this fence still open (Stop, or a reply that never closed it). */
  cutOff?: boolean
  code: string
  streaming?: boolean
}

/**
 * Transcript stand-in for a `harvis-doc` fence: kind, title and progress in
 * place of the raw block. The document itself is built in the right rail.
 *
 * Unlike ArtifactCard, streaming DOES open the rail here — once the header
 * names the document, so the person watches it being written the way a
 * document tool would show it. That happens at most once per document per
 * page load (see autoOpenLiveDoc); closing the tab mid-stream keeps it closed.
 */
export function DocCard({ code, cutOff = false, streaming = false }: DocCardProps) {
  const { t } = useI18n()
  const copy = t.docCard
  const view = useSessionView()
  const runtimeId = useStore(view.$runtimeId)
  const storedId = useStore(view.$storedId)
  const sessionId = storedId || runtimeId || 'session'

  const doc = useMemo(() => parseHarvisDoc(code), [code])
  const title = doc.title.trim()

  // Freeze the key at the first title seen: a document with no front matter
  // takes its title from a heading that is still being typed, and a new chat's
  // id changes from the runtime id to the stored id mid-stream. Re-key only
  // when the card is handed a different block (it no longer extends the start
  // it was keyed on).
  const keyRef = useRef<{ key: string; prefix: string } | null>(null)

  if (title && (!keyRef.current || !code.startsWith(keyRef.current.prefix))) {
    keyRef.current = {
      key: liveDocKey(sessionId, title),
      prefix: code.slice(0, 64)
    }
  }

  const key = keyRef.current?.key ?? ''

  useEffect(() => {
    if (key) {
      upsertLiveDoc(key, sessionId, code, streaming, cutOff)
    }
  }, [code, cutOff, key, sessionId, streaming])

  useEffect(() => {
    if (streaming && key && title) {
      autoOpenLiveDoc(key, title)
    }
  }, [key, streaming, title])

  const arrived = arrivedParts(doc)
  const total = expectedParts(doc)
  const kindLabel = copy.kind[doc.kind]
  const noun = copy.noun[doc.kind]

  // Finished: "Presentation · PPTX · 8 slides". Writing: the progress replaces
  // the file type, since there is no file yet.
  const line =
    !doc.headerComplete && !title
      ? `${noun} · ${copy.starting}`
      : streaming
        ? `${noun} · ${copy.writing(doc.kind, Math.max(1, arrived), total)}`
        : `${fileFormatLine(doc.kind, noun)} · ${copy.done(doc.kind, arrived || doc.sections.length)}`

  return (
    <div
      className={cn(WIDGET_SHELL_CLASS, 'my-1.5 flex w-full max-w-md items-center gap-2.5 overflow-hidden')}
      data-slot="aui_doc-file"
    >
      <button
        className="group/doc flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 text-left"
        data-slot="aui_doc-card"
        data-streaming={streaming ? 'true' : 'false'}
        disabled={!key}
        onClick={() => key && openLiveDoc(key, title)}
        title={copy.open}
        type="button"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-muted/55 text-muted-foreground">
          <CodeCardIcon className="text-[1rem]" name={DOC_KIND_ICON[doc.kind]} />
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              'block truncate text-[length:var(--conversation-text-font-size)] font-medium text-foreground',
              streaming && 'shimmer text-foreground/55'
            )}
          >
            {title || kindLabel}
          </span>
          <span className="block truncate text-[length:var(--conversation-tool-font-size)] text-muted-foreground">
            {line}
          </span>
        </span>
      </button>
      <DocExportControl kind={doc.kind} source={code} streaming={streaming || !doc.headerComplete} title={doc.title} />
    </div>
  )
}

interface DownloadAllFile {
  kind: HarvisDocKind
  source: string
  title: string
}

/**
 * "Download all" for a message that wrote two or more documents: each one in
 * its main format. Renders nothing for fewer than two.
 */
export function DocDownloadAll({ files }: { files: readonly DownloadAllFile[] }) {
  const { t } = useI18n()
  const copy = t.docCard
  const [progress, setProgress] = useState<null | {
    done: number
    total: number
  }>(null)
  const [failed, setFailed] = useState(0)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true

    return () => {
      mounted.current = false
    }
  }, [])

  if (files.length < 2) {
    return null
  }

  const run = async () => {
    setFailed(0)

    const count = await downloadAllDocs(files, (done, total) => mounted.current && setProgress({ done, total }))

    if (mounted.current) {
      setProgress(null)
      setFailed(count)
    }
  }

  return (
    <div className="my-1 flex items-center gap-2" data-slot="aui_doc-download-all">
      <Button
        className="h-7 gap-1.5 px-2.5 text-xs"
        disabled={progress !== null}
        onClick={() => void run()}
        size="sm"
        variant="outline"
      >
        {progress ? (
          <Loader2 className="size-3 animate-spin motion-reduce:animate-none" />
        ) : (
          <Download className="size-3" />
        )}
        <span>{progress ? copy.downloadingAll(progress.done, progress.total) : copy.downloadAll}</span>
      </Button>
      {failed > 0 && <span className="text-xs text-destructive">{copy.downloadAllFailed(failed)}</span>}
    </div>
  )
}

/** Body of the `harvis-doc` fence that is still open in the message, if any. */
export const OpenDocFenceContext = createContext<null | string>(null)

/**
 * `code` reaches the card through the markdown preprocessor, which drops trailing spaces and
 * list or indent prefixes, while the message text it is matched against is raw. Compare with
 * whitespace removed so those differences never read as a different (cut off) document.
 */
const squash = (text: string): string => text.replace(/\s+/g, '')

/**
 * The card the markdown renderer mounts for a `harvis-doc` fence. The fence
 * renderer only knows the part is still running, not whether THIS fence has
 * closed, so a finished document inside a message that keeps talking reads as
 * done instead of writing until the whole reply ends.
 */
export function TranscriptDocCard({ code, running }: { code: string; running: boolean }) {
  const open = useContext(OpenDocFenceContext)
  const { text } = useMessagePartText()
  const streaming = running && open !== null && squash(open).startsWith(squash(code))
  // A fence the turn never closed (Stop, or a reply that ended inside it) is a truncated document.
  const cutOff = useMemo(
    () => !streaming && !closedHarvisDocFences(text).some(fence => squash(fence) === squash(code)),
    [code, streaming, text]
  )

  // The button rides under the LAST finished document of the message, so it
  // appears once, after everything it downloads has been written.
  const files = useMemo(() => {
    const fences = closedHarvisDocFences(text)

    if (fences.length < 2 || squash(fences[fences.length - 1]) !== squash(code)) {
      return []
    }

    return fences.map(source => {
      const doc = parseHarvisDoc(source)

      return { kind: doc.kind, source, title: doc.title }
    })
  }, [code, text])

  return (
    <>
      <DocCard code={code} cutOff={cutOff} streaming={streaming} />
      {!streaming && <DocDownloadAll files={files} />}
    </>
  )
}
