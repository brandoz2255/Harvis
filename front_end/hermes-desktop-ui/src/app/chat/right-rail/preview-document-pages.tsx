import { type KeyboardEvent, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import type { HarvisDocKind } from '@/lib/harvis-doc'
import { primaryExt } from '@/lib/harvis-doc-files'
import { DocApiError, type DocPreviewResult, fetchDocPageImage, fetchDocPreview } from '@/lib/harvis-doc-preview-api'
import { ChevronLeft, ChevronRight } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** Edits to a finished document settle this long before the sandbox re-renders it. */
export const PAGES_REFRESH_DEBOUNCE_MS = 800

type Phase = 'error' | 'loading' | 'ready' | 'unavailable'

interface PagesState {
  message: string
  phase: Phase
  result: DocPreviewResult | null
}

interface DocPagesViewProps {
  /** The Preview tab is the one showing. Nothing is fetched while it is not. */
  active: boolean
  /** The document has finished streaming. Nothing is fetched before then. */
  complete: boolean
  kind: HarvisDocKind
  source: string
  title: string
}

/**
 * The exported file, as the sandbox renders it: one page image at a time with
 * Page N / M. Fetches only while active AND complete, never per streamed chunk,
 * and re-fetches (debounced) when a finished document's source changes. Stays
 * mounted behind the Live tab so flipping back and forth costs nothing.
 */
export function DocPagesView({ active, complete, kind, source, title }: DocPagesViewProps) {
  const { t } = useI18n()
  const copy = t.docPreview.pages
  const [state, setState] = useState<PagesState>({ message: '', phase: 'loading', result: null })
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState(0)
  const [images, setImages] = useState<Record<number, string>>({})
  const [brokenPages, setBrokenPages] = useState<Record<number, true>>({})
  const rendered = useRef<null | string>(null)
  const frame = useRef<HTMLDivElement>(null)
  const format = primaryExt(kind)
  const { result } = state
  const count = result?.pages.length ?? 0
  const total = Math.max(result?.page_count ?? 0, count)
  const current = Math.min(page, Math.max(count - 1, 0))

  useEffect(() => {
    // Render what is on screen once; a retry (attempt) forces a fresh one.
    const stamp = `${attempt}\0${format}\0${title}\0${source}`

    if (!active || !complete || rendered.current === stamp) {
      return
    }

    const controller = new AbortController()

    const run = async () => {
      setState(prev => ({ ...prev, message: '', phase: prev.result ? prev.phase : 'loading' }))

      try {
        const next = await fetchDocPreview({ format, signal: controller.signal, source, title })

        if (controller.signal.aborted) {
          return
        }

        rendered.current = stamp
        setState({ message: '', phase: next.pages.length ? 'ready' : 'error', result: next })
      } catch (error) {
        if (controller.signal.aborted) {
          return
        }

        setState(prev => ({
          message: error instanceof Error ? error.message : String(error),
          phase: error instanceof DocApiError && error.status === 503 ? 'unavailable' : 'error',
          result: prev.result
        }))
      }
    }

    // The first render of a document goes straight out; later edits wait.
    if (!rendered.current) {
      void run()

      return () => controller.abort()
    }

    const timer = window.setTimeout(() => void run(), PAGES_REFRESH_DEBOUNCE_MS)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [active, attempt, complete, format, source, title])

  // Page images need the session cookie, so each is fetched with it and shown
  // from an object URL that is revoked when the render it belongs to goes away.
  const store = useRef<null | {
    controller: AbortController
    pending: Set<number>
    urls: Map<number, string>
  }>(null)

  useEffect(() => {
    const owned = { controller: new AbortController(), pending: new Set<number>(), urls: new Map<number, string>() }

    store.current = owned
    setImages({})
    setBrokenPages({})

    return () => {
      owned.controller.abort()
      owned.urls.forEach(url => URL.revokeObjectURL(url))
      store.current = null
    }
  }, [result])

  useEffect(() => {
    const owned = store.current

    if (!owned || !result || !active || !complete) {
      return
    }

    for (const index of [current, current + 1]) {
      const ref = result.pages[index]

      if (!ref || owned.urls.has(index) || owned.pending.has(index)) {
        continue
      }

      owned.pending.add(index)

      fetchDocPageImage(ref.url, owned.controller.signal)
        .then(blob => {
          if (owned.controller.signal.aborted) {
            return
          }

          const url = URL.createObjectURL(blob)

          owned.urls.set(index, url)
          setImages(prev => ({ ...prev, [index]: url }))
        })
        .catch(() => {
          if (!owned.controller.signal.aborted) {
            setBrokenPages(prev => ({ ...prev, [index]: true }))
          }
        })
        .finally(() => owned.pending.delete(index))
    }
  }, [active, complete, current, result])

  // Arrow keys work straight after switching tabs, without stealing focus from
  // anything outside this panel (the composer, say).
  useEffect(() => {
    const node = frame.current

    if (active && state.phase === 'ready' && node) {
      const focused = document.activeElement

      if (!focused || focused === document.body || node.closest('[data-slot="doc-preview"]')?.contains(focused)) {
        node.focus({ preventScroll: true })
      }
    }
  }, [active, state.phase])

  const go = (delta: number) => setPage(Math.min(Math.max(current + delta, 0), Math.max(count - 1, 0)))

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return
    }

    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      go(-1)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      go(1)
    }
  }

  const ratio = result?.pages[current]
    ? `${result.pages[current].width} / ${result.pages[current].height}`
    : kind === 'deck'
      ? '16 / 9'
      : '210 / 297'

  const retry = () => {
    rendered.current = null
    setAttempt(n => n + 1)
  }

  let body: React.ReactNode

  if (!complete) {
    body = <Notice body={t.docPreview.view.previewWaiting} />
  } else if (state.phase === 'unavailable') {
    body = (
      <Notice
        action={
          <Button onClick={retry} size="sm" variant="outline">
            {copy.retry}
          </Button>
        }
        body={copy.unavailableBody}
        title={copy.unavailableTitle}
      />
    )
  } else if (state.phase === 'error') {
    body = (
      <Notice
        action={
          <Button onClick={retry} size="sm" variant="outline">
            {copy.retry}
          </Button>
        }
        body={state.message}
        title={copy.failed}
      />
    )
  } else if (!result) {
    body = <PageSkeleton label={copy.loading} ratio={ratio} />
  } else {
    const src = images[current]

    body = (
      <>
        <div className="flex shrink-0 items-center justify-center gap-2 border-b border-border/40 px-3 py-1">
          <Button aria-label={copy.prev} disabled={current <= 0} onClick={() => go(-1)} size="icon-sm" variant="ghost">
            <ChevronLeft className="size-3.5" />
          </Button>
          <span aria-live="polite" className="min-w-20 text-center text-xs text-muted-foreground tabular-nums">
            {copy.label(current + 1, count)}
          </span>
          <Button
            aria-label={copy.next}
            disabled={current >= count - 1}
            onClick={() => go(1)}
            size="icon-sm"
            variant="ghost"
          >
            <ChevronRight className="size-3.5" />
          </Button>
        </div>
        {total > count && (
          <p
            className="shrink-0 border-b border-border/40 px-3 py-1 text-center text-xs text-amber-600 dark:text-amber-400"
            data-slot="doc-pages-truncated"
            role="status"
          >
            {copy.truncated(count, total)}
          </p>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {src ? (
            <img
              alt={copy.pageAlt(current + 1, count, title)}
              className="block h-auto w-full rounded-md border border-border/60 bg-white shadow-sm"
              height={result.pages[current].height}
              loading="lazy"
              src={src}
              style={{ width: '100%' }}
              width={result.pages[current].width}
            />
          ) : brokenPages[current] ? (
            <Notice
              action={
                <Button onClick={retry} size="sm" variant="outline">
                  {copy.retry}
                </Button>
              }
              body=""
              title={copy.failed}
            />
          ) : (
            <PageSkeleton label={copy.loading} ratio={ratio} />
          )}
        </div>
      </>
    )
  }

  return (
    <div
      aria-label={t.docPreview.view.preview}
      className={cn('flex size-full min-h-0 flex-col outline-none', !active && 'hidden')}
      data-slot="doc-pages"
      onKeyDown={onKeyDown}
      ref={frame}
      tabIndex={0}
    >
      {body}
    </div>
  )
}

function PageSkeleton({ label, ratio }: { label: string; ratio: string }) {
  return (
    <div className="p-3" data-slot="doc-pages-skeleton">
      <div
        aria-busy="true"
        aria-label={label}
        className="w-full animate-pulse rounded-md border border-border/50 bg-muted/40 motion-reduce:animate-none"
        role="status"
        style={{ aspectRatio: ratio }}
      />
    </div>
  )
}

function Notice({ action, body, title }: { action?: React.ReactNode; body: string; title?: string }) {
  return (
    <div className="grid flex-1 place-items-center px-8 py-10 text-center" data-slot="doc-pages-notice" role="status">
      <div className="grid max-w-sm justify-items-center gap-2">
        {title && <div className="text-sm font-medium text-foreground">{title}</div>}
        {body && <div className="text-xs leading-relaxed text-muted-foreground">{body}</div>}
        {action && <div className="mt-2">{action}</div>}
      </div>
    </div>
  )
}
