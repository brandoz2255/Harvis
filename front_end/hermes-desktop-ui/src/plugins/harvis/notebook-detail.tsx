/**
 * One notebook as a research workspace, NotebookLM / open-notebook style: a
 * header (name and description, editable or auto-named from its sources, plus a
 * stats line) over three columns — Library (sources, then notes) | Chat |
 * Studio. When the page is too narrow for three columns the same panels fall
 * back to four tabs: Sources, Chat, Notes and Studio.
 */

import {
  Button,
  Codicon,
  EmptyState,
  Input,
  SegmentedControl,
  Textarea,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { NotebookChat } from './notebook-chat'
import { NotebookNotes } from './notebook-notes'
import {
  errorText,
  listKey,
  type NotebookInfo,
  notebookKey,
  type NotebookStats,
  type Source,
  sourcesKey,
  statsKey
} from './notebook-shared'
import { NotebookSources, useSourceWatchers } from './notebook-sources'
import { NotebookStudio } from './notebook-studio'

type Tab = 'chat' | 'notes' | 'sources' | 'studio'
type Layout = 'columns' | 'tabs'

/** The title the notebooks grid gives a new notebook; auto-named once it has a ready source. */
export const UNTITLED = 'Untitled notebook'

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

function Panel({ children, className, title }: { children: ReactNode; className?: string; title: string }) {
  return (
    <section className={className}>
      <h3 className="mb-2 text-[0.65rem] font-medium tracking-wide text-(--ui-text-tertiary) uppercase">{title}</h3>
      {children}
    </section>
  )
}

function EditDetails({ notebook, onDone }: { notebook: NotebookInfo; onDone: () => void }) {
  const [title, setTitle] = useState(notebook.title)
  const [description, setDescription] = useState(notebook.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  return (
    <form
      className="space-y-1.5"
      onSubmit={async event => {
        event.preventDefault()
        setBusy(true)
        setError('')

        try {
          await harvisApi(`/api/notebooks/${notebook.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ title: title.trim(), description: description.trim() || null })
          })
          onDone()
        } catch (err) {
          setError(errorText(err))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Input aria-label="Title" onChange={e => setTitle(e.target.value)} value={title} />
      <Textarea
        aria-label="Description"
        className="min-h-16 text-sm"
        onChange={e => setDescription(e.target.value)}
        placeholder="What this notebook is for (optional)"
        value={description}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex justify-end gap-1.5">
        <Button onClick={onDone} size="sm" type="button" variant="ghost">
          Cancel
        </Button>
        <Button disabled={!title.trim() || busy} size="sm" type="submit">
          Save
        </Button>
      </div>
    </form>
  )
}

function StatsLine({ stats }: { stats: NotebookStats | undefined }) {
  if (!stats) {
    return null
  }

  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const parts = [
    plural(stats.source_count, 'source'),
    plural(stats.chunk_count, 'passage'),
    plural(stats.note_count, 'note')
  ]

  if (stats.message_count > 0) {
    parts.push(plural(stats.message_count, 'message'))
  }

  if (stats.processing_sources > 0) {
    parts.push(`${stats.processing_sources} still being read`)
  }

  return <p className="text-xs text-(--ui-text-tertiary)">{parts.join(' · ')}</p>
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
  /** Shown as a Back button in the header when set (the notebooks grid). */
  onBack?: () => void
  onDeleted: () => void
}) {
  const queryClient = useQueryClient()
  const [rootRef, layout] = useLayout(forcedLayout)
  const [editing, setEditing] = useState(false)
  const [naming, setNaming] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<null | Tab>(null)

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

  const refreshHeader = () => {
    void queryClient.invalidateQueries({ queryKey: notebookKey(notebookId) })
    void queryClient.invalidateQueries({ queryKey: listKey })
  }

  const autoname = async () => {
    setNaming(true)
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/autoname`, { method: 'POST' })
      refreshHeader()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setNaming(false)
    }
  }

  // A notebook made from the grid starts as "Untitled notebook"; name it from
  // its sources the first time one is ready (once per open, never over a real name).
  const triedAutoname = useRef(false)
  const untitled = notebook.data?.title === UNTITLED
  const anyReady = (sources.data ?? []).some(s => s.status === 'ready')

  useEffect(() => {
    if (untitled && anyReady && !triedAutoname.current) {
      triedAutoname.current = true
      void autoname()
    }
    // autoname is recreated every render; the ref keeps this to one call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [untitled, anyReady])

  if (notebook.error) {
    return <EmptyState description={errorText(notebook.error)} title="Could not open this notebook" />
  }

  const list = sources.data ?? []
  const ready = list.some(s => s.status === 'ready')
  const current: Tab = tab ?? (ready ? 'chat' : 'sources')
  const nb = notebook.data
  const count = (n: number) => (n > 0 ? ` (${n})` : '')

  const header = (
    <div className="space-y-1">
      {editing && nb ? (
        <EditDetails
          notebook={nb}
          onDone={() => {
            setEditing(false)
            refreshHeader()
          }}
        />
      ) : (
        <div className="flex items-start gap-2">
          {onBack && (
            <Button aria-label="All notebooks" onClick={onBack} size="sm" title="All notebooks" variant="ghost">
              <Codicon name="arrow-left" size="0.8rem" />
            </Button>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold">
              {nb?.emoji ? `${nb.emoji} ` : ''}
              {nb?.title ?? (notebook.isLoading ? 'Loading…' : 'Notebook')}
            </h2>
            {nb?.description && <p className="text-sm text-(--ui-text-tertiary)">{nb.description}</p>}
            <StatsLine stats={stats.data} />
          </div>
          <Button disabled={!nb} onClick={() => setEditing(true)} size="sm" variant="ghost">
            <Codicon name="edit" size="0.8rem" /> Edit
          </Button>
          <Button
            disabled={naming || list.length === 0}
            onClick={() => void autoname()}
            size="sm"
            title="Let Harvis name this notebook from its sources"
            variant="ghost"
          >
            <Codicon name="sparkle" size="0.8rem" /> {naming ? 'Naming…' : 'Auto-name'}
          </Button>
          <Button
            onClick={async () => {
              if (window.confirm('Delete this notebook and all its sources?')) {
                try {
                  await harvisApi(`/api/notebooks/${notebookId}`, { method: 'DELETE' })
                  onDeleted()
                } catch (err) {
                  setError(errorText(err))
                }
              }
            }}
            size="sm"
            variant="ghost"
          >
            <Codicon name="trash" size="0.8rem" /> Delete
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )

  const status = sources.isLoading ? (
    <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
  ) : sources.error ? (
    <p className="text-xs text-destructive">{errorText(sources.error)}</p>
  ) : null

  const panel = (which: Tab) =>
    which === 'sources' ? (
      <NotebookSources notebookId={notebookId} sources={list} />
    ) : which === 'chat' ? (
      <NotebookChat notebookId={notebookId} ready={ready} />
    ) : which === 'notes' ? (
      <NotebookNotes notebookId={notebookId} />
    ) : (
      <NotebookStudio notebookId={notebookId} sources={list} title={nb?.title ?? 'Notebook'} />
    )

  const column = 'min-h-0 overflow-y-auto px-4 py-3'

  // One stable root so the width observer keeps watching across layout flips.
  return (
    <div className="flex h-full min-h-0 flex-col" data-layout={layout} ref={rootRef}>
      {layout === 'columns' ? (
        <>
          <div className="shrink-0 border-b px-4 pb-3">{header}</div>
          {status ? (
            <div className="p-4">{status}</div>
          ) : (
            <div className="grid min-h-0 flex-1 grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)_minmax(16rem,24rem)]">
              <div className={`${column} space-y-6 border-r`}>
                <Panel title={`Sources${count(list.length)}`}>{panel('sources')}</Panel>
                <Panel title={`Notes${count(stats.data?.note_count ?? nb?.note_count ?? 0)}`}>{panel('notes')}</Panel>
              </div>
              <div className={column}>{panel('chat')}</div>
              <div className={`${column} border-l`}>
                <Panel title="Studio">{panel('studio')}</Panel>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-4">
          {header}
          <SegmentedControl
            onChange={setTab}
            options={[
              { id: 'sources', label: `Sources${count(list.length)}` },
              { id: 'chat', label: 'Chat' },
              { id: 'notes', label: `Notes${count(stats.data?.note_count ?? nb?.note_count ?? 0)}` },
              { id: 'studio', label: 'Studio' }
            ]}
            value={current}
          />
          {status ?? panel(current)}
        </div>
      )}
    </div>
  )
}
