/**
 * One notebook as a research workspace, laid out like Gemini Notebook: a header
 * bar (back, name, Ask all, Share), then three panels side by side: Sources on
 * the left, Chat in the middle with the notebook's overview pinned to its top,
 * and Studio on the right (its outputs and notes). Either side panel collapses
 * to a thin strip. When the page is too narrow for three panels the same three
 * fall back to tabs.
 */

import { Button, Codicon, EmptyState, SegmentedControl, useQuery } from '@hermes/plugin-sdk'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { AskAllButton } from './notebook-ask-all'
import { NotebookChat } from './notebook-chat'
import { NotebookOverview } from './notebook-overview'
import { usePendingQuestion } from './notebook-selection'
import { errorText, type NotebookInfo, notebookKey, type Source, sourcesKey } from './notebook-shared'
import { NotebookShareButton } from './notebook-share'
import { insightsPending } from './notebook-source-meta'
import { NotebookSources, useSourceWatchers } from './notebook-sources'
import { NotebookStudioRail } from './notebook-studio-rail'

export { UNTITLED } from './notebook-overview'

type Tab = 'chat' | 'sources' | 'studio'
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

function Panel({
  children,
  collapsed,
  flush,
  onToggle,
  side,
  title
}: {
  children: ReactNode
  collapsed?: boolean
  /** The child scrolls itself (the chat pins its composer to the bottom). */
  flush?: boolean
  onToggle?: () => void
  side?: 'left' | 'right'
  title: string
}) {
  const toggle = onToggle && (
    <Button
      aria-label={collapsed ? `Show ${title}` : `Hide ${title}`}
      onClick={onToggle}
      size="xs"
      title={collapsed ? `Show ${title}` : `Hide ${title}`}
      variant="ghost"
    >
      <Codicon name={side === 'right' ? 'layout-sidebar-right' : 'layout-sidebar-left'} size="0.85rem" />
    </Button>
  )

  if (collapsed) {
    return (
      <section
        aria-label={title}
        className="flex min-h-0 flex-col items-center rounded-xl border bg-(--ui-bg-secondary) py-2"
      >
        {toggle}
      </section>
    )
  }

  return (
    <section
      aria-label={title}
      className="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-(--ui-bg-secondary)"
    >
      <div className="flex shrink-0 items-center gap-1 border-b px-4 py-2">
        {side === 'right' && toggle}
        <h3 className="flex-1 text-sm font-medium">{title}</h3>
        {side !== 'right' && toggle}
      </div>
      <div className={flush ? 'flex min-h-0 flex-1 flex-col' : 'min-h-0 flex-1 overflow-y-auto p-3'}>{children}</div>
    </section>
  )
}

export function NotebookDetail({
  expecting,
  layout: forcedLayout,
  notebookId,
  onBack,
  onDeleted
}: {
  /** A Studio kind a chat action is making for this notebook; the rail waits for it and opens it. */
  expecting?: string
  /** Force a layout instead of measuring the available width. */
  layout?: Layout
  notebookId: string
  /** Shown as a Back button in the overview when set (the notebooks grid). */
  onBack?: () => void
  onDeleted: () => void
}) {
  const [rootRef, layout] = useLayout(forcedLayout)
  const [tab, setTab] = useState<null | Tab>(null)
  const [hidden, setHidden] = useState({ sources: false, studio: false })

  const notebook = useQuery({
    queryFn: () => harvisApi<NotebookInfo>(`/api/notebooks/${notebookId}`),
    queryKey: notebookKey(notebookId)
  })

  // Shared notebooks: chat_only people cannot read sources or notes, viewers cannot chat.
  const role = notebook.data?.role
  const canReadSources = role !== 'chat_only'
  const canChat = role !== 'viewer'

  const sources = useQuery({
    enabled: canReadSources,
    queryFn: () => harvisApi<Source[]>(`/api/notebooks/${notebookId}/sources`),
    queryKey: sourcesKey(notebookId),
    // The SSE status watcher below is the fast path; this is the fallback when it can't connect.
    refetchInterval: query => {
      const list = query.state.data as Source[] | undefined

      // Summaries are written in the background after a source turns ready, so keep looking until they land.
      return list?.some(s => s.status === 'pending' || s.status === 'processing') || insightsPending(list ?? [])
        ? 4000
        : false
    }
  })

  useSourceWatchers(notebookId, sources.data ?? [])

  // A suggested question on a source lands in the chat, so show the chat.
  const asked = usePendingQuestion(notebookId)

  useEffect(() => {
    if (asked) {
      setTab('chat')
    }
  }, [asked])

  if (notebook.error) {
    return <EmptyState description={errorText(notebook.error)} title="Could not open this notebook" />
  }

  const list = sources.data ?? []
  const ready = canReadSources ? list.some(s => s.status === 'ready') : true
  const current: Tab = tab ?? (expecting ? 'studio' : !canReadSources || (canChat && ready) ? 'chat' : 'sources')
  const nb = notebook.data
  const count = (n: number) => (n > 0 ? ` (${n})` : '')

  const tabOptions: { id: Tab; label: string }[] = [
    { id: 'sources', label: `Sources${count(list.length)}` },
    { id: 'chat', label: 'Chat' },
    { id: 'studio', label: 'Studio' }
  ]

  const status = !canReadSources ? null : sources.isLoading ? (
    <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
  ) : sources.error ? (
    <p className="text-xs text-destructive">{errorText(sources.error)}</p>
  ) : null

  const chat = !canChat ? (
    <p className="text-xs text-(--ui-text-tertiary)">
      You have view-only access to this notebook, so chat is not available.
    </p>
  ) : (
    <NotebookChat
      intro={(ask, empty) => (
        <NotebookOverview ask={ask} empty={empty} notebook={nb} onDeleted={onDeleted} sources={list} />
      )}
      isOwner={role === 'owner'}
      notebookId={notebookId}
      ready={ready}
      sources={list}
    />
  )

  const studio = (
    <NotebookStudioRail expecting={expecting} notebookId={notebookId} sources={list} title={nb?.title ?? 'Notebook'} />
  )

  const sourcesPanel = !canReadSources ? (
    <p className="text-xs text-(--ui-text-tertiary)">
      This notebook was shared for chat only, so its sources and notes are hidden.
    </p>
  ) : (
    <NotebookSources notebookId={notebookId} sources={list} />
  )

  const header = (
    <header className="flex shrink-0 items-center gap-1.5 border-b px-4 py-2" data-testid="notebook-toolbar">
      {onBack && (
        <Button aria-label="All notebooks" onClick={onBack} size="xs" title="All notebooks" variant="ghost">
          <Codicon name="arrow-left" size="0.8rem" />
        </Button>
      )}
      <span aria-hidden className="text-lg leading-none">
        {nb?.emoji || '📓'}
      </span>
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold" title={nb?.title}>
        {nb?.title ?? 'Loading…'}
      </h1>
      <AskAllButton />
      <NotebookShareButton isOwner={nb ? nb.is_owner !== false : true} notebookId={notebookId} />
    </header>
  )

  const side = (collapsed: boolean, open: string) => (collapsed ? '2.75rem' : open)
  const columns = `${side(hidden.sources, 'minmax(14rem,1fr)')} minmax(0,1.8fr) ${side(hidden.studio, 'minmax(14rem,1fr)')}`

  // One stable root so the width observer keeps watching across layout flips.
  return (
    <div className="flex h-full min-h-0 flex-col" data-layout={layout} ref={rootRef}>
      {header}
      {layout === 'columns' ? (
        status ? (
          <div className="p-6">{status}</div>
        ) : (
          <div className="grid min-h-0 flex-1 gap-3 p-3" style={{ gridTemplateColumns: columns }}>
            <Panel
              collapsed={hidden.sources}
              onToggle={() => setHidden(h => ({ ...h, sources: !h.sources }))}
              side="left"
              title="Sources"
            >
              {sourcesPanel}
            </Panel>
            <Panel flush={canChat} title="Chat">
              {canChat ? chat : <div className="p-3">{chat}</div>}
            </Panel>
            <Panel
              collapsed={hidden.studio}
              onToggle={() => setHidden(h => ({ ...h, studio: !h.studio }))}
              side="right"
              title="Studio"
            >
              {studio}
            </Panel>
          </div>
        )
      ) : (
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <SegmentedControl<Tab>
            onChange={setTab}
            options={tabOptions.filter(o => canReadSources || o.id === 'chat')}
            value={current}
          />
          {status ?? (current === 'sources' ? sourcesPanel : current === 'chat' ? chat : studio)}
        </div>
      )}
    </div>
  )
}
