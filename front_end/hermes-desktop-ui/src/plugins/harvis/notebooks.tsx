/**
 * Notebooks — the page over `/api/notebooks/*` (python_back_end/notebooks).
 * A notebook holds sources (pages, files, pasted text, YouTube); Harvis splits
 * them into passages, embeds them, and answers questions with citations back
 * to the passage it used.
 */

import {
  Button,
  cn,
  Codicon,
  DetailColumn,
  EmptyState,
  Input,
  ListColumn,
  MasterDetail,
  PageSearchShell,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useDeferredValue, useState } from 'react'

import { harvisApi } from './api'
import { relativeTime } from './format'
import { NotebookDetail } from './notebook-detail'
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

function NewNotebook({ onCreated }: { onCreated: (id: string) => void }) {
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">New notebook</h2>
        <p className="text-sm text-(--ui-text-tertiary)">
          Collect pages, PDFs, and notes on one topic, then ask questions. Answers only use what you added and point to
          the passage they came from.
        </p>
      </div>
      <form
        className="flex gap-1.5"
        onSubmit={async event => {
          event.preventDefault()
          setBusy(true)
          setError('')

          try {
            const nb = await harvisApi<{ id: string }>('/api/notebooks', {
              method: 'POST',
              body: JSON.stringify({ title: title.trim() })
            })

            setTitle('')
            onCreated(nb.id)
          } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Input
          className="min-w-0 flex-1"
          onChange={e => setTitle(e.target.value)}
          placeholder="e.g. CSI sensing papers"
          value={title}
        />
        <Button disabled={!title.trim() || busy} type="submit">
          Create
        </Button>
      </form>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

export function NotebooksPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('new')

  const notebooks = useQuery({
    queryFn: () => harvisApi<{ notebooks: NotebookRow[] }>('/api/notebooks?limit=100').then(r => r.notebooks ?? []),
    queryKey: listKey
  })

  const q = search.trim().toLowerCase()
  const deferredQuery = useDeferredValue(search.trim())
  const rows = (notebooks.data ?? []).filter(nb => !q || nb.title.toLowerCase().includes(q))
  const refresh = () => void queryClient.invalidateQueries({ queryKey: listKey })

  return (
    <PageSearchShell
      onSearchChange={setSearch}
      searchPlaceholder="Search notebooks"
      searchTrailingAction={
        <Button onClick={() => setSelected('new')} size="sm">
          <Codicon name="add" size="0.8rem" /> New notebook
        </Button>
      }
      searchValue={search}
    >
      <MasterDetail resizeId="harvis-notebooks-split" split="wide">
        <ListColumn>
          {notebooks.isLoading ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">Loading…</p>
          ) : notebooks.error ? (
            <p className="px-2 text-xs text-destructive">{String(notebooks.error)}</p>
          ) : rows.length === 0 ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">{q ? 'Nothing matches.' : 'No notebooks yet.'}</p>
          ) : (
            rows.map(nb => (
              <button
                className={cn(
                  'flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-accent/60',
                  selected === nb.id && 'bg-accent/70'
                )}
                key={nb.id}
                onClick={() => setSelected(nb.id)}
                type="button"
              >
                {nb.emoji ? (
                  <span className="mt-0.5 w-[0.9rem] text-center text-sm leading-none">{nb.emoji}</span>
                ) : (
                  <Codicon className="mt-0.5" name="notebook" size="0.9rem" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{nb.title}</span>
                  <span className="block text-xs text-(--ui-text-tertiary)">
                    {nb.source_count} source{nb.source_count === 1 ? '' : 's'}
                    {nb.note_count > 0 ? ` · ${nb.note_count} note${nb.note_count === 1 ? '' : 's'}` : ''} ·{' '}
                    {relativeTime(nb.updated_at)}
                  </span>
                </span>
              </button>
            ))
          )}
          <SearchHits onPick={setSelected} query={deferredQuery} />
        </ListColumn>
        <DetailColumn>
          {selected === 'new' ? (
            <NewNotebook
              onCreated={id => {
                refresh()
                setSelected(id)
              }}
            />
          ) : (notebooks.data ?? []).some(nb => nb.id === selected) || notebooks.isFetching ? (
            <NotebookDetail
              key={selected}
              notebookId={selected}
              onDeleted={() => {
                refresh()
                setSelected('new')
              }}
            />
          ) : (
            <EmptyState title="This notebook is gone" />
          )}
        </DetailColumn>
      </MasterDetail>
    </PageSearchShell>
  )
}
