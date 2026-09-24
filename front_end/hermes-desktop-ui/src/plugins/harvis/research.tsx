/**
 * Deep Research — the page over `/api/research/*` (python_back_end/deep_research).
 * Ask a question, Harvis plans searches, reads pages over several rounds and
 * writes a cited report. Running jobs show their live phase; finished ones keep
 * the report, the sources, and the visual report the backend renders.
 */

import {
  Button,
  cn,
  Codicon,
  DetailColumn,
  EmptyState,
  ListColumn,
  MasterDetail,
  PageSearchShell,
  StatusDot,
  Streamdown,
  Textarea,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'

import { harvisApi } from './api'
import { relativeTime } from './format'

interface ActiveResearch {
  session_id: string
  query: string
  progress: Progress
  started_at: number
}

interface LibraryItem {
  id: string
  query: string
  source_count: number
  status: string
  duration: string
  rounds: number | string
  completed_at: number
}

interface Progress {
  phase?: string
  round?: number
  total_sources?: number
  queries?: number
  title?: string
  url?: string
  message?: string
  model?: string
}

interface ResearchDetail {
  query: string
  status: string
  result: string
  sources: { url: string; title: string }[]
  stats?: Record<string, number | string> | null
  completed_at?: number
}

const DEPTHS = [
  { id: 'quick', label: 'Quick', hint: 'About 2 minutes, 2 rounds', rounds: 2, time: 150 },
  { id: 'standard', label: 'Standard', hint: 'About 5 minutes, Harvis decides the rounds', rounds: 0, time: 300 },
  { id: 'deep', label: 'Deep', hint: 'Up to 15 minutes, more sources', rounds: 0, time: 900 }
] as const

const PHASE_LABEL: Record<string, string> = {
  probing: 'Waking up the model',
  planning: 'Planning the searches',
  searching: 'Searching the web',
  reading: 'Reading pages',
  analyzing: 'Weighing what it found',
  writing: 'Writing the report',
  warning: 'Working around a problem',
  error: 'Stopped with an error'
}

const activeKey = ['harvis', 'research', 'active'] as const
const libraryKey = ['harvis', 'research', 'library'] as const

const fetchActive = () => harvisApi<{ active: ActiveResearch[] }>('/api/research/active').then(r => r.active ?? [])

const fetchLibrary = () =>
  harvisApi<{ research: LibraryItem[] }>('/api/research/library?limit=100').then(r => r.research ?? [])

function progressLine(progress: Progress) {
  const phase = PHASE_LABEL[progress.phase ?? ''] ?? 'Starting'
  const bits = [
    progress.round ? `round ${progress.round}` : '',
    progress.total_sources ? `${progress.total_sources} pages read` : ''
  ].filter(Boolean)

  return bits.length ? `${phase}, ${bits.join(', ')}` : phase
}

function NewResearch({ onStarted }: { onStarted: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [depth, setDepth] = useState<(typeof DEPTHS)[number]['id']>('standard')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const start = async () => {
    const preset = DEPTHS.find(d => d.id === depth) ?? DEPTHS[1]
    setBusy(true)
    setError('')

    try {
      const res = await harvisApi<{ session_id: string }>('/api/research/start', {
        method: 'POST',
        body: JSON.stringify({ query: query.trim(), max_rounds: preset.rounds, max_time: preset.time })
      })

      setQuery('')
      onStarted(res.session_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">New research</h2>
        <p className="text-sm text-(--ui-text-tertiary)">
          Ask something that needs more than one search. Harvis reads the web in rounds and writes a report with
          sources. It keeps going if you leave this page.
        </p>
      </div>
      <Textarea
        className="min-h-32 text-sm"
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && query.trim() && !busy) {
            void start()
          }
        }}
        placeholder="e.g. What are the cheapest ways to run a 30B model at home in 2026, and what does each cost?"
        value={query}
      />
      <div className="grid gap-2 sm:grid-cols-3">
        {DEPTHS.map(d => (
          <button
            className={cn(
              'rounded-lg border px-3 py-2 text-left transition-colors',
              depth === d.id ? 'border-primary/50 bg-primary/10' : 'hover:bg-accent/50'
            )}
            key={d.id}
            onClick={() => setDepth(d.id)}
            type="button"
          >
            <span className="block text-sm font-medium">{d.label}</span>
            <span className="block text-xs text-(--ui-text-tertiary)">{d.hint}</span>
          </button>
        ))}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button disabled={!query.trim() || busy} onClick={() => void start()}>
        <Codicon name="telescope" size="0.9rem" />
        {busy ? 'Starting…' : 'Start research'}
      </Button>
    </div>
  )
}

function RunningResearch({ item, onCancelled }: { item: ActiveResearch; onCancelled: () => void }) {
  const [cancelling, setCancelling] = useState(false)
  const progress = item.progress ?? {}

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">{item.query}</h2>
      <div className="flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm">
        <StatusDot tone="warn" />
        <span className="min-w-0 flex-1">{progressLine(progress)}</span>
        <Button
          disabled={cancelling}
          onClick={async () => {
            setCancelling(true)

            try {
              await harvisApi(`/api/research/cancel/${item.session_id}`, { method: 'POST' })
              onCancelled()
            } finally {
              setCancelling(false)
            }
          }}
          size="sm"
          variant="ghost"
        >
          Stop
        </Button>
      </div>
      {progress.phase === 'reading' && progress.url && (
        <p className="truncate text-xs text-(--ui-text-tertiary)">Reading {progress.title || progress.url}</p>
      )}
      {progress.message && <p className="text-xs text-(--ui-text-tertiary)">{progress.message}</p>}
      <p className="text-xs text-(--ui-text-tertiary)">
        Started {relativeTime(new Date(item.started_at * 1000).toISOString())}. The report appears here when it is done.
      </p>
    </div>
  )
}

function FinishedResearch({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { data, error, isLoading } = useQuery({
    queryFn: () => harvisApi<ResearchDetail>(`/api/research/detail/${id}`),
    queryKey: ['harvis', 'research', 'detail', id]
  })

  if (isLoading) {
    return <p className="text-sm text-(--ui-text-tertiary)">Loading the report…</p>
  }

  if (error || !data) {
    return <EmptyState description={error ? String(error) : undefined} title="Could not load this research" />
  }

  const stats = Object.entries(data.stats ?? {}).slice(0, 4)

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h2 className="text-lg font-semibold">{data.query}</h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-(--ui-text-tertiary)">
          {stats.map(([k, v]) => (
            <span className="rounded bg-(--ui-bg-tertiary) px-1.5 py-0.5" key={k}>
              {k}: {String(v)}
            </span>
          ))}
          <span className="flex-1" />
          <Button
            onClick={() => window.open(`/api/research/report/${id}`, '_blank', 'noopener')}
            size="sm"
            variant="outline"
          >
            <Codicon name="link-external" size="0.8rem" /> Visual report
          </Button>
          <Button onClick={() => void navigator.clipboard.writeText(data.result)} size="sm" variant="ghost">
            <Codicon name="copy" size="0.8rem" /> Copy
          </Button>
          <Button
            onClick={async () => {
              await harvisApi(`/api/research/${id}`, { method: 'DELETE' })
              onDeleted()
            }}
            size="sm"
            variant="ghost"
          >
            <Codicon name="trash" size="0.8rem" /> Delete
          </Button>
        </div>
      </div>
      <div className="prose prose-sm max-w-none text-sm dark:prose-invert">
        <Streamdown mode="static">{data.result || '_The research finished without a report._'}</Streamdown>
      </div>
      {data.sources.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-sm font-medium">Sources ({data.sources.length})</h3>
          <ol className="list-decimal space-y-1 pl-5 text-xs">
            {data.sources.map(s => (
              <li key={s.url}>
                <a className="text-primary hover:underline" href={s.url} rel="noreferrer" target="_blank">
                  {s.title || s.url}
                </a>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}

export function ResearchPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  // Chat replies link here as `#/research?id=rp-…` to open that run's report.
  const [params] = useSearchParams()
  const linked = params.get('id')
  const [selected, setSelected] = useState<string>(linked || 'new')

  useEffect(() => {
    if (linked) {
      setSelected(linked)
    }
  }, [linked])

  const active = useQuery({ queryFn: fetchActive, queryKey: activeKey, refetchInterval: 2000 })
  const library = useQuery({ queryFn: fetchLibrary, queryKey: libraryKey, refetchInterval: 15_000 })

  const running = active.data ?? []
  const q = search.trim().toLowerCase()
  const done = (library.data ?? []).filter(item => !q || item.query.toLowerCase().includes(q))
  const selectedRun = running.find(r => r.session_id === selected)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: activeKey })
    void queryClient.invalidateQueries({ queryKey: libraryKey })
  }

  const row = (id: string, title: string, meta: string, tone: 'good' | 'warn') => (
    <button
      className={cn(
        'flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-accent/60',
        selected === id && 'bg-accent/70'
      )}
      key={id}
      onClick={() => setSelected(id)}
      type="button"
    >
      <StatusDot className="mt-1.5" tone={tone} />
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 block text-sm">{title}</span>
        <span className="block text-xs text-(--ui-text-tertiary)">{meta}</span>
      </span>
    </button>
  )

  return (
    <PageSearchShell
      onSearchChange={setSearch}
      searchPlaceholder="Search past research"
      searchTrailingAction={
        <Button onClick={() => setSelected('new')} size="sm">
          <Codicon name="add" size="0.8rem" /> New research
        </Button>
      }
      searchValue={search}
    >
      <MasterDetail resizeId="harvis-research-split" split="wide">
        <ListColumn>
          {running.length > 0 && (
            <p className="px-2 pt-1 pb-1 text-xs font-medium text-(--ui-text-tertiary)">Running</p>
          )}
          {running.map(r => row(r.session_id, r.query, progressLine(r.progress ?? {}), 'warn'))}
          <p className="px-2 pt-2 pb-1 text-xs font-medium text-(--ui-text-tertiary)">Finished</p>
          {library.isLoading ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">Loading…</p>
          ) : done.length === 0 ? (
            <p className="px-2 text-xs text-(--ui-text-tertiary)">{q ? 'Nothing matches.' : 'No research yet.'}</p>
          ) : (
            done.map(item =>
              row(
                item.id,
                item.query,
                [
                  `${item.source_count} sources`,
                  item.duration,
                  item.completed_at ? relativeTime(new Date(item.completed_at * 1000).toISOString()) : ''
                ]
                  .filter(Boolean)
                  .join(' · '),
                'good'
              )
            )
          )}
        </ListColumn>
        <DetailColumn>
          {selected === 'new' ? (
            <NewResearch
              onStarted={id => {
                refresh()
                setSelected(id)
              }}
            />
          ) : selectedRun ? (
            <RunningResearch item={selectedRun} onCancelled={refresh} />
          ) : (
            <FinishedResearch
              id={selected}
              key={selected}
              onDeleted={() => {
                refresh()
                setSelected('new')
              }}
            />
          )}
        </DetailColumn>
      </MasterDetail>
    </PageSearchShell>
  )
}
