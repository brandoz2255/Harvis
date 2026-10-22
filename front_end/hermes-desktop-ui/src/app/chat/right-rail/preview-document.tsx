import { useStore } from '@nanostores/react'
import { computed } from 'nanostores'
import { useEffect, useMemo, useState } from 'react'

import { DOC_KIND_ICON } from '@/components/assistant-ui/doc-card'
import { CodeCardIcon } from '@/components/chat/code-card'
import { writeClipboardText } from '@/components/ui/copy-button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useI18n } from '@/i18n'
import { arrivedParts, expectedParts, parseHarvisDoc } from '@/lib/harvis-doc'
import { MoreHorizontal } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { $liveDocs, type LiveDoc, liveDocKeyFromTarget } from '@/store/live-docs'
import type { PreviewTarget } from '@/store/preview'

import { DocCheckStrip } from './preview-document-check'
import { DocExportControl } from './preview-document-export'
import { useFollowLive } from './preview-document-follow'
import { DocPagesView } from './preview-document-pages'
import { buildDocParts, liveIndex } from './preview-document-parts'
import { SheetView } from './preview-document-sheet'
import { DeckStrip, DeckView, DocView, PdfView } from './preview-document-views'
import { PreviewEmptyState } from './preview-file'

/** A card that stops updating (scrolled out of the virtualised transcript, or a
 *  stream that died) must not leave the preview "writing" forever. */
const STALE_STREAM_MS = 30_000
const STALE_CHECK_MS = 3_000

function useFreshStreaming(live: LiveDoc): boolean {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!live.streaming) {
      return
    }

    setNow(Date.now())

    const id = window.setInterval(() => setNow(Date.now()), STALE_CHECK_MS)

    return () => window.clearInterval(id)
  }, [live.streaming, live.updatedAt])

  return live.streaming && now - live.updatedAt < STALE_STREAM_MS
}

/**
 * The right-rail view of a `harvis-doc`: the document as it is being written,
 * skeletons for the parts still to come, and the downloads. Reads the live
 * registry, so it keeps filling in as tokens arrive.
 */
export function DocumentPreview({ target }: { target: PreviewTarget }) {
  const { t } = useI18n()
  const key = liveDocKeyFromTarget(target)
  const $live = useMemo(() => computed($liveDocs, docs => (key ? docs[key] : undefined)), [key])
  const live = useStore($live)

  if (!live) {
    return <PreviewEmptyState body={t.docPreview.missingBody} title={t.docPreview.missingTitle} />
  }

  return <DocumentBody key={live.key} live={live} />
}

function DocumentBody({ live }: { live: LiveDoc }) {
  const { t } = useI18n()
  const copy = t.docPreview
  const streaming = useFreshStreaming(live)
  const [stripOpen, setStripOpen] = useState(true)
  const [mode, setMode] = useState<'live' | 'preview'>('live')
  // Pages are fetched the first time Preview is shown, not before.
  const [previewOpened, setPreviewOpened] = useState(false)

  const doc = useMemo(() => parseHarvisDoc(live.source), [live.source])
  const parts = useMemo(() => buildDocParts(doc, streaming), [doc, streaming])
  const active = liveIndex(parts)
  const arrived = arrivedParts(doc)
  const total = expectedParts(doc)
  const title = doc.title.trim() || copy.untitled
  const isSheet = doc.kind === 'sheet'

  const follow = useFollowLive({
    active,
    enabled: streaming && !isSheet && active >= 0,
    signature: live.source.length.toString()
  })

  const status = streaming
    ? t.docCard.writing(doc.kind, Math.max(1, arrived), total)
    : t.docCard.done(doc.kind, arrived || doc.sections.length)

  const View = { deck: DeckView, doc: DocView, pdf: PdfView, sheet: SheetView }[doc.kind]
  const ticks = Math.max(total, parts.length)
  const previewing = mode === 'preview'

  const pick = (next: 'live' | 'preview') => {
    setMode(next)

    if (next === 'preview') {
      setPreviewOpened(true)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-transparent" data-slot="doc-preview">
      <header className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-1.5">
        <CodeCardIcon className="shrink-0 text-[0.9375rem] text-muted-foreground" name={DOC_KIND_ICON[doc.kind]} />
        <span className="shrink-0 text-[0.625rem] font-medium tracking-wide text-muted-foreground uppercase">
          {t.docCard.kind[doc.kind]}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">{title}</span>
        <span
          className={cn(
            'shrink-0 text-[0.625rem] text-muted-foreground',
            streaming && 'animate-pulse motion-reduce:animate-none'
          )}
          data-slot="doc-status"
        >
          {streaming ? copy.writing : copy.done}
        </span>
        <DocExportControl kind={doc.kind} source={live.source} streaming={streaming} title={doc.title} />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              aria-label={copy.moreActions}
              className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              type="button"
            >
              <MoreHorizontal className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40" sideOffset={6}>
            <DropdownMenuItem onSelect={() => void writeClipboardText(live.source)}>{copy.copySource}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <div className="flex shrink-0 items-center gap-2 border-b border-border/40 px-3 py-1">
        <div aria-label={copy.progressAria} className="flex shrink-0 items-center gap-0.5" role="img">
          {Array.from({ length: Math.min(ticks, 24) }, (_, i) => {
            const state = parts[i]?.state ?? 'pending'

            return (
              <span
                className={cn(
                  'h-1 w-3 rounded-full',
                  state === 'done' && 'bg-primary/70',
                  state === 'active' && 'animate-pulse bg-primary motion-reduce:animate-none',
                  state === 'pending' && 'bg-muted-foreground/25'
                )}
                key={`tick-${i}`}
              />
            )
          })}
        </div>
        <span className="min-w-0 flex-1 truncate text-[0.625rem] text-muted-foreground">{status}</span>
        {doc.kind === 'deck' && !previewing && (
          <button
            className="shrink-0 rounded px-1.5 py-0.5 text-[0.625rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            onClick={() => setStripOpen(open => !open)}
            type="button"
          >
            {stripOpen ? copy.hideSlides : copy.showSlides}
          </button>
        )}
        <div
          aria-label={copy.view.aria}
          className="flex shrink-0 items-center rounded-md bg-muted/55 p-0.5"
          data-slot="doc-view-switch"
          role="group"
        >
          {(['live', 'preview'] as const).map(value => (
            <button
              aria-pressed={mode === value}
              className={cn(
                'rounded px-1.5 py-0.5 text-[0.625rem] font-medium transition-colors',
                mode === value
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              key={value}
              onClick={() => pick(value)}
              type="button"
            >
              {copy.view[value]}
            </button>
          ))}
        </div>
      </div>

      <DocCheckStrip complete={!streaming} kind={doc.kind} source={live.source} title={doc.title} />

      {previewOpened && (
        <div className={cn('min-h-0 flex-1', !previewing && 'hidden')}>
          <DocPagesView
            active={previewing}
            complete={!streaming}
            kind={doc.kind}
            source={live.source}
            title={doc.title}
          />
        </div>
      )}

      {!previewing && doc.kind === 'deck' && (
        <DeckStrip onSelect={follow.scrollToPart} open={stripOpen} parts={parts} />
      )}

      {previewing ? null : isSheet ? (
        <div className="min-h-0 flex-1">
          <SheetView doc={doc} parts={parts} streaming={streaming} />
        </div>
      ) : (
        <div className="relative min-h-0 flex-1">
          <div className="size-full overflow-y-auto" onScroll={follow.onScroll} ref={follow.scrollRef}>
            <View doc={doc} parts={parts} streaming={streaming} />
          </div>
          {follow.paused && (
            <button
              className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-[0.6875rem] font-medium text-primary-foreground shadow-md transition-opacity hover:opacity-90"
              onClick={follow.jump}
              type="button"
            >
              {copy.jumpToLive}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
