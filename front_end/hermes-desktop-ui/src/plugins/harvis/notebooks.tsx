/**
 * Notebooks — the page over `/api/notebooks/*` (python_back_end/notebooks).
 * A notebook holds sources (pages, files, pasted text, YouTube); Harvis splits
 * them into passages, embeds them, and answers questions with citations back
 * to the passage it used.
 *
 * Laid out like NotebookLM / open-notebook: the home is a grid of notebook
 * cards; opening one (`#/notebooks?nb=<id>`) puts you in its research
 * workspace — sources and notes, chat, and Studio side by side.
 */

import {
  Badge,
  Button,
  Codicon,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  PageSearchShell,
  RowButton,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useDeferredValue, useState } from 'react'
import { useSearchParams } from 'react-router'

import { harvisApi } from './api'
import { relativeTime } from './format'
import { NotebookDetail, UNTITLED } from './notebook-detail'
import { listKey, type NotebookInfo as NotebookRow } from './notebook-shared'

interface SearchHit {
  kind: 'note' | 'source'
  notebook_id: string
  notebook_title: null | string
  title: null | string
  snippet: null | string
}

/** Full-text hits inside sources and notes (`POST /api/notebooks/search`), for queries the titles alone don't match. */
function SearchHits({ onPick, query }: { onPick: (notebookId: string) => void; query: string }) {
  const hits = useQuery({
    enabled: query.length >= 2,
    queryFn: () =>
      harvisApi<{ results: SearchHit[] }>('/api/notebooks/search', {
        method: 'POST',
        body: JSON.stringify({ query, type: 'text', limit: 20, search_sources: true, search_notes: true })
      }).then(r => r.results ?? []),
    queryKey: ['harvis', 'notebooks', 'search', query],
    staleTime: 30_000
  })

  if (query.length < 2) {
    return null
  }

  const list = hits.data ?? []

  return (
    <div className="mt-3 space-y-1 border-t pt-2">
      <p className="px-2 text-[0.65rem] tracking-wide text-(--ui-text-tertiary) uppercase">In sources and notes</p>
      {hits.isLoading ? (
        <p className="px-2 text-xs text-(--ui-text-tertiary)">Searching…</p>
      ) : hits.error ? (
        <p className="px-2 text-xs text-destructive">{String(hits.error)}</p>
      ) : list.length === 0 ? (
        <p className="px-2 text-xs text-(--ui-text-tertiary)">No passages match.</p>
      ) : (
        list.map((hit, i) => (
          <button
            className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent/60"
            key={i}
            onClick={() => onPick(hit.notebook_id)}
            type="button"
          >
            <Codicon className="mt-0.5" name={hit.kind === 'note' ? 'note' : 'file'} size="0.8rem" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs">{hit.title || (hit.kind === 'note' ? 'Note' : 'Source')}</span>
              <span className="block truncate text-xs text-(--ui-text-tertiary)">
                {hit.notebook_title ?? 'Notebook'}
                {hit.snippet ? ` — ${hit.snippet.replace(/\s+/g, ' ').slice(0, 120)}` : ''}
              </span>
            </span>
          </button>
        ))
      )}
    </div>
  )
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function NotebookCard({ notebook, onDelete, onOpen }: { notebook: NotebookRow; onDelete: () => void; onOpen: () => void }) {
  return (
    <div className="group relative flex min-h-56 flex-col rounded-xl border bg-(--ui-bg-secondary) transition-colors hover:border-(--ui-stroke-secondary) hover:bg-accent/40">
      <RowButton
        aria-label={`Open ${notebook.title}`}
        className="flex flex-1 flex-col gap-3 p-4 text-left"
        onClick={onOpen}
      >
        <span className="text-3xl leading-none">
          {notebook.emoji || <Codicon className="text-(--ui-text-tertiary)" name="notebook" size="1.75rem" />}
        </span>
        <span className="line-clamp-2 pr-6 text-base font-semibold">{notebook.title}</span>
        {notebook.description && (
          <span className="line-clamp-4 text-sm text-(--ui-text-tertiary)">{notebook.description}</span>
        )}
        <span className="mt-auto flex flex-wrap items-center gap-1.5 pt-2 text-xs text-(--ui-text-tertiary)">
          <Badge variant="muted">{plural(notebook.source_count, 'source')}</Badge>
          {notebook.note_count > 0 && <Badge variant="muted">{plural(notebook.note_count, 'note')}</Badge>}
          <span className="ml-auto">{relativeTime(notebook.updated_at)}</span>
        </span>
      </RowButton>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            aria-label={`${notebook.title} options`}
            className="absolute top-3 right-3 inline-flex size-7 items-center justify-center rounded-md text-(--ui-text-tertiary) opacity-0 transition-opacity group-hover:opacity-100 hover:bg-accent/60 focus-visible:opacity-100 data-[state=open]:opacity-100"
            type="button"
          >
            <Codicon name="ellipsis" size="0.85rem" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onOpen}>
            <Codicon name="go-to-file" size="0.8rem" /> Open
          </DropdownMenuItem>
          <DropdownMenuItem className="text-destructive" onSelect={onDelete}>
            <Codicon name="trash" size="0.8rem" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function NewNotebookCard({ busy, onCreate }: { busy: boolean; onCreate: () => void }) {
  return (
    <RowButton
      className="flex min-h-56 flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-(--ui-text-secondary) transition-colors hover:bg-accent/40 disabled:opacity-60"
      disabled={busy}
      onClick={onCreate}
    >
      <Codicon name="add" size="1.5rem" />
      <span className="text-sm font-medium">{busy ? 'Creating…' : 'New notebook'}</span>
      <span className="max-w-52 text-center text-xs text-(--ui-text-tertiary)">
        Collect pages, PDFs and notes on one topic, then ask questions with citations.
      </span>
    </RowButton>
  )
}

export function NotebooksPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const open = params.get('nb')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState<NotebookRow | null>(null)

  const notebooks = useQuery({
    queryFn: () => harvisApi<{ notebooks: NotebookRow[] }>('/api/notebooks?limit=100').then(r => r.notebooks ?? []),
    queryKey: listKey
  })

  const q = search.trim().toLowerCase()
  const deferredQuery = useDeferredValue(search.trim())
  const rows = (notebooks.data ?? []).filter(
    nb => !q || nb.title.toLowerCase().includes(q) || (nb.description ?? '').toLowerCase().includes(q)
  )
  const refresh = () => void queryClient.invalidateQueries({ queryKey: listKey })
  const openNotebook = (id: string) => setParams({ nb: id })
  const backToGrid = () => setParams({})

  // Like NotebookLM: "New notebook" makes one straight away and drops you in it;
  // naming it can wait (Edit, or Auto-name once it has sources).
  const create = async () => {
    setCreating(true)
    setError('')

    try {
      const nb = await harvisApi<{ id: string }>('/api/notebooks', {
        method: 'POST',
        body: JSON.stringify({ title: UNTITLED })
      })

      refresh()
      openNotebook(nb.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  if (open) {
    return (
      <div className="flex h-full min-w-0 flex-col overflow-hidden bg-(--ui-chat-surface-background) pt-[calc(var(--titlebar-height)+0.5rem)]">
        <NotebookDetail
          key={open}
          notebookId={open}
          onBack={backToGrid}
          onDeleted={() => {
            refresh()
            backToGrid()
          }}
        />
      </div>
    )
  }

  return (
    <PageSearchShell
      onSearchChange={setSearch}
      searchPlaceholder="Search notebooks"
      searchTrailingAction={
        <Button disabled={creating} onClick={() => void create()} size="sm">
          <Codicon name="add" size="0.8rem" /> New notebook
        </Button>
      }
      searchValue={search}
    >
      <div className="h-full overflow-y-auto px-4 pb-6">
        <div className="mx-auto max-w-7xl space-y-3">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {notebooks.isLoading ? (
            <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
          ) : notebooks.error ? (
            <p className="text-xs text-destructive">{String(notebooks.error)}</p>
          ) : q && rows.length === 0 ? (
            <EmptyState title="No notebook titles match" />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {!q && <NewNotebookCard busy={creating} onCreate={() => void create()} />}
              {rows.map(nb => (
                <NotebookCard
                  key={nb.id}
                  notebook={nb}
                  onDelete={() => setDeleting(nb)}
                  onOpen={() => openNotebook(nb.id)}
                />
              ))}
            </div>
          )}
          <SearchHits onPick={openNotebook} query={deferredQuery} />
        </div>
      </div>
      <ConfirmDialog
        confirmLabel="Delete"
        description="Its sources, notes and chat go with it."
        destructive
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (deleting) {
            await harvisApi(`/api/notebooks/${deleting.id}`, { method: 'DELETE' })
            refresh()
          }
        }}
        open={deleting !== null}
        title={`Delete “${deleting?.title ?? 'notebook'}”?`}
      />
    </PageSearchShell>
  )
}
