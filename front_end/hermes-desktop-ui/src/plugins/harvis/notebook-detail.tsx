/**
 * One notebook as a research workspace, laid out like open-notebook: a Library
 * (Sources / Notes) on the left, the chat in the middle with the notebook's
 * overview pinned to its top, and the Studio rail on the right. When the page
 * is too narrow for three columns the same panels fall back to four tabs:
 * Sources, Notes, Chat and Studio.
 */

import { Button, Codicon, EmptyState, SegmentedControl, useQuery } from '@hermes/plugin-sdk'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { NotebookChat } from './notebook-chat'
import { NotebookNotes } from './notebook-notes'
import { NotebookOverview } from './notebook-overview'
import {
  errorText,
  type NotebookInfo,
  notebookKey,
  type NotebookStats,
  type Source,
  sourcesKey,
  statsKey
} from './notebook-shared'
import { NotebookSources, useSourceWatchers } from './notebook-sources'
import { NotebookStudioRail } from './notebook-studio-rail'

export { UNTITLED } from './notebook-overview'

type Tab = 'chat' | 'notes' | 'sources' | 'studio'
type Layout = 'columns' | 'tabs'

/** Three columns need roughly this much width before chat gets cramped. */
const COLUMNS_MIN_WIDTH = 1024

/** 'columns' once the workspace is wide enough, else 'tabs' (also the answer before the first measurement). */
function useLayout(forced: Layout | undefined) {
  const ref = useRef<HTMLDivElement>(null)
  const [layout, setLayout] = useState<Layout>(forced ?? 'tabs')

  useEffect(() => {
    const el = ref.current

    if (forced || !el || typeof ResizeObserver === 'undefined') {
      return
    }

    const measure = () => setLayout(el.clientWidth >= COLUMNS_MIN_WIDTH ? 'columns' : 'tabs')
    const observer = new ResizeObserver(measure)

    measure()
    observer.observe(el)

    return () => observer.disconnect()
  }, [forced])

  return [ref, forced ?? layout] as const
}

function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex min-h-0 flex-col overflow-hidden rounded-xl border bg-(--ui-bg-secondary) ${className}`}>
      {children}
    </div>
  )
}

export function NotebookDetail({
  layout: forcedLayout,
  notebookId,
  onBack,
  onDeleted
}: {
  /** Force a layout instead of measuring the available width. */
  layout?: Layout
  notebookId: string
  /** Shown as a Back button in the overview when set (the notebooks grid). */
  onBack?: () => void
  onDeleted: () => void
}) {
  const [rootRef, layout] = useLayout(forcedLayout)
  const [tab, setTab] = useState<null | Tab>(null)
  const [library, setLibrary] = useState<'notes' | 'sources'>('sources')

  const notebook = useQuery({
    queryFn: () => harvisApi<NotebookInfo>(`/api/notebooks/${notebookId}`),
    queryKey: notebookKey(notebookId)
  })

  const sources = useQuery({
    queryFn: () => harvisApi<Source[]>(`/api/notebooks/${notebookId}/sources`),
    queryKey: sourcesKey(notebookId),
    // The SSE status watcher below is the fast path; this is the fallback when it can't connect.
    refetchInterval: query => {
      const list = query.state.data as Source[] | undefined

      return list?.some(s => s.status === 'pending' || s.status === 'processing') ? 4000 : false
    }
  })

  const stats = useQuery({
    queryFn: () => harvisApi<NotebookStats>(`/api/notebooks/${notebookId}/stats`),
    queryKey: statsKey(notebookId)
  })

  useSourceWatchers(notebookId, sources.data ?? [])

  if (notebook.error) {
    return <EmptyState description={errorText(notebook.error)} title="Could not open this notebook" />
  }

  const list = sources.data ?? []
  const ready = list.some(s => s.status === 'ready')
  const current: Tab = tab ?? (ready ? 'chat' : 'sources')
  const nb = notebook.data
  const noteCount = stats.data?.note_count ?? nb?.note_count ?? 0
  const count = (n: number) => (n > 0 ? ` (${n})` : '')

  const status = sources.isLoading ? (
    <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
  ) : sources.error ? (
    <p className="text-xs text-destructive">{errorText(sources.error)}</p>
  ) : null

  const chat = (
    <NotebookChat
      intro={(ask, empty) => (
        <NotebookOverview ask={ask} empty={empty} notebook={nb} onBack={onBack} onDeleted={onDeleted} sources={list} />
      )}
      notebookId={notebookId}
      ready={ready}
    />
  )

  const studio = <NotebookStudioRail notebookId={notebookId} sources={list} title={nb?.title ?? 'Notebook'} />

  // One stable root so the width observer keeps watching across layout flips.
  return (
    <div className="flex h-full min-h-0 flex-col" data-layout={layout} ref={rootRef}>
      {layout === 'columns' ? (
        status ? (
          <div className="p-6">{status}</div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)_minmax(16rem,20rem)] gap-6 p-6">
            <Card>
              <div className="shrink-0 p-3 pb-0">
                <SegmentedControl
                  onChange={setLibrary}
                  options={[
                    { id: 'sources', label: `Sources${count(list.length)}` },
                    { id: 'notes', label: `Notes${count(noteCount)}` }
                  ]}
                  value={library}
                />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {library === 'sources' ? (
                  <NotebookSources notebookId={notebookId} sources={list} />
                ) : (
                  <NotebookNotes notebookId={notebookId} />
                )}
              </div>
            </Card>
            <Card>
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{chat}</div>
            </Card>
            <div className="flex min-h-0 flex-col border-l pl-6">
              <h3 className="mb-2 flex shrink-0 items-center gap-1.5 text-sm font-semibold">Studio</h3>
              <div className="min-h-0 flex-1 overflow-y-auto">{studio}</div>
            </div>
          </div>
        )
      ) : (
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {/* The Chat tab carries the full overview; the other tabs keep a way back and the name. */}
          {(current !== 'chat' || status) && (
            <div className="flex items-center gap-1.5">
              {onBack && (
                <Button aria-label="All notebooks" onClick={onBack} size="xs" title="All notebooks" variant="ghost">
                  <Codicon name="arrow-left" size="0.8rem" />
                </Button>
              )}
              <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">
                {nb ? `${nb.emoji || '📓'} ${nb.title}` : 'Loading…'}
              </h2>
            </div>
          )}
          <SegmentedControl
            onChange={setTab}
            options={[
              { id: 'sources', label: `Sources${count(list.length)}` },
              { id: 'notes', label: `Notes${count(noteCount)}` },
              { id: 'chat', label: 'Chat' },
              { id: 'studio', label: 'Studio' }
            ]}
            value={current}
          />
          {status ??
            (current === 'sources' ? (
              <NotebookSources notebookId={notebookId} sources={list} />
            ) : current === 'notes' ? (
              <NotebookNotes notebookId={notebookId} />
            ) : current === 'chat' ? (
              chat
            ) : (
              studio
            ))}
        </div>
      )}
    </div>
  )
}
