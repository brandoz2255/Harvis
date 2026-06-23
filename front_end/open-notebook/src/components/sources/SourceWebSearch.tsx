'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Loader2, Search, Plus, Check, Globe, ChevronDown, Sparkles } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useCreateSource } from '@/lib/hooks/use-sources'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

interface WebResult {
  title: string
  url: string
  snippet?: string
  source?: string
}
interface DeepSource {
  url: string
  title: string
  summary?: string
}

function authToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}
function authHeaders(): Record<string, string> {
  const t = authToken()
  return t ? { authorization: `Bearer ${t}` } : {}
}
function domainOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** A single compact result row (favicon + title + snippet) with an Add button. */
function ResultRow({
  url,
  title,
  snippet,
  imported,
  importing,
  onAdd,
}: {
  url: string
  title: string
  snippet?: string
  imported?: boolean
  importing?: boolean
  onAdd: () => void
}) {
  const domain = domainOf(url)
  return (
    <div className="flex items-start gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-muted/50">
      {domain ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`}
          alt=""
          className="h-4 w-4 rounded-sm mt-0.5 flex-shrink-0 object-contain"
          onError={(e) => {
            e.currentTarget.style.visibility = 'hidden'
          }}
        />
      ) : (
        <Globe className="h-4 w-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
      )}
      <div className="flex-1 min-w-0">
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium leading-tight line-clamp-1 hover:underline"
          onClick={(e) => e.stopPropagation()}
          title={title}
        >
          {title}
        </a>
        {snippet && <div className="text-xs text-muted-foreground line-clamp-1">{snippet}</div>}
      </div>
      <Button
        size="sm"
        variant={imported ? 'ghost' : 'outline'}
        className="h-6 px-1.5 text-xs gap-1 flex-shrink-0"
        disabled={imported || importing}
        onClick={onAdd}
      >
        {importing ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : imported ? (
          <Check className="h-3 w-3" />
        ) : (
          <Plus className="h-3 w-3" />
        )}
        {imported ? 'Added' : 'Add'}
      </Button>
    </div>
  )
}

/**
 * "Search the web for new sources" with two modes:
 *  - Fast: instant DuckDuckGo-backed list (/onb-api/sources/web-search).
 *  - Deep: the agentic deep-research engine (/api/research/*) → a synthesized
 *    report + Cited / Also-found source lists; the user picks which to import.
 * Each pick becomes a normal URL source.
 */
export function SourceWebSearch({
  notebookId,
  onImported,
}: {
  notebookId: string
  onImported?: () => void
}) {
  const createSource = useCreateSource()
  const [mode, setMode] = useState<'fast' | 'deep'>('fast')
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Fast
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<WebResult[] | null>(null)

  // Deep
  const [deepPhase, setDeepPhase] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [deepProgress, setDeepProgress] = useState('')
  const [report, setReport] = useState('')
  const [showReport, setShowReport] = useState(true)
  const [cited, setCited] = useState<DeepSource[]>([])
  const [alsoFound, setAlsoFound] = useState<DeepSource[]>([])
  const [deepTab, setDeepTab] = useState<'cited' | 'found'>('cited')

  // Import tracking (keyed by url)
  const [imported, setImported] = useState<Record<string, boolean>>({})
  const [importing, setImporting] = useState<Record<string, boolean>>({})
  const [addingAll, setAddingAll] = useState(false)

  const cancelRef = useRef(false)
  useEffect(() => {
    cancelRef.current = false
    return () => {
      cancelRef.current = true
    }
  }, [])

  const importOne = async (url: string, title: string) => {
    if (importing[url] || imported[url]) return
    setImporting((p) => ({ ...p, [url]: true }))
    try {
      await createSource.mutateAsync({ type: 'link', url, title, notebook_id: notebookId })
      setImported((p) => ({ ...p, [url]: true }))
      onImported?.()
    } catch {
      // error toast handled by the hook
    } finally {
      setImporting((p) => ({ ...p, [url]: false }))
    }
  }

  const addAll = async (list: DeepSource[]) => {
    setAddingAll(true)
    for (const s of list) {
      if (!imported[s.url]) await importOne(s.url, s.title)
    }
    setAddingAll(false)
  }

  const runFast = async () => {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    setResults(null)
    try {
      const res = await fetch('/onb/api/sources/web-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ query: q, max_results: 8 }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`)
      const data = await res.json()
      setResults((data.results as WebResult[]) || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const runDeep = async () => {
    const q = query.trim()
    if (!q) return
    cancelRef.current = false
    setError(null)
    setReport('')
    setCited([])
    setAlsoFound([])
    setShowReport(true)
    setDeepProgress('Starting research…')
    setDeepPhase('running')
    try {
      const start = await fetch('/api/research/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ query: q, max_rounds: 0, max_time: 300 }),
      })
      if (!start.ok) throw new Error((await start.json().catch(() => ({}))).detail || `HTTP ${start.status}`)
      const { session_id: sid } = await start.json()
      if (!sid) throw new Error('No research session id returned')

      // Poll status until it stops running (deep research is multi-round; minutes).
      for (let i = 0; i < 200 && !cancelRef.current; i++) {
        await sleep(2500)
        if (cancelRef.current) return
        const st = await fetch(`/api/research/status/${sid}`, { headers: authHeaders() })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null)
        if (!st) continue
        const p = st.progress || {}
        const msg = p.message || p.phase || p.stage || st.status
        if (typeof msg === 'string') setDeepProgress(msg)
        if (st.status && st.status !== 'running') break
      }
      if (cancelRef.current) return

      const peek = await fetch(`/api/research/result-peek/${sid}`, {
        method: 'POST',
        headers: authHeaders(),
      }).then((r) => r.json())
      const srcs: DeepSource[] = Array.isArray(peek.sources) ? peek.sources : []
      const raw: DeepSource[] = Array.isArray(peek.raw_findings) ? peek.raw_findings : []
      const citedUrls = new Set(srcs.map((s) => s.url))
      setReport(typeof peek.result === 'string' ? peek.result : '')
      setCited(srcs)
      setAlsoFound(raw.filter((r) => r.url && !citedUrls.has(r.url)))
      setDeepTab(srcs.length ? 'cited' : 'found')
      setDeepPhase('done')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setDeepPhase('error')
    }
  }

  const onSubmit = () => {
    if (!query.trim()) return
    if (mode === 'fast') runFast()
    else runDeep()
  }

  const deepBusy = deepPhase === 'running'
  const activeList = deepTab === 'cited' ? cited : alsoFound

  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 p-1.5 mb-3">
      {/* Row 1: search input */}
      <div className="flex items-center gap-2">
        <Globe className="h-4 w-4 text-muted-foreground flex-shrink-0" />
        <input
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          placeholder={mode === 'fast' ? 'Search the web for sources…' : 'Deep research a topic…'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
        />
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0 flex-shrink-0"
          onClick={onSubmit}
          disabled={loading || deepBusy || !query.trim()}
          aria-label="Search"
        >
          {loading || deepBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        </Button>
      </div>

      {/* Row 2: research-mode dropdown */}
      <div className="flex items-center gap-2 mt-1.5 pl-6">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-6 px-2 text-xs gap-1">
              {mode === 'fast' ? <Search className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
              {mode === 'fast' ? 'Fast Research' : 'Deep Research'}
              <ChevronDown className="h-3 w-3 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-48">
            <DropdownMenuItem onClick={() => setMode('fast')} className="gap-2">
              <Search className="h-3.5 w-3.5" />
              <div>
                <div className="text-xs font-medium">Fast Research</div>
                <div className="text-[10px] text-muted-foreground">Instant web results</div>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setMode('deep')} className="gap-2">
              <Sparkles className="h-3.5 w-3.5" />
              <div>
                <div className="text-xs font-medium">Deep Research</div>
                <div className="text-[10px] text-muted-foreground">Agentic report + sources</div>
              </div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {error && <p className="text-xs text-destructive mt-1.5 px-0.5">{error}</p>}

      {/* Fast mode */}
      {mode === 'fast' && (
        <>
          {loading && (
            <p className="text-xs text-muted-foreground mt-2 px-0.5 flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" />
              Researching websites…
            </p>
          )}
          {results && results.length === 0 && !loading && (
            <p className="text-xs text-muted-foreground mt-2 px-0.5">No results for that search.</p>
          )}
          {results && results.length > 0 && (
            <div className="mt-1.5 space-y-0.5 max-h-72 overflow-y-auto">
              {results.map((r) => (
                <ResultRow
                  key={r.url}
                  url={r.url}
                  title={r.title}
                  snippet={r.snippet}
                  imported={imported[r.url]}
                  importing={importing[r.url]}
                  onAdd={() => importOne(r.url, r.title)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Deep mode */}
      {mode === 'deep' && (
        <>
          {deepBusy && (
            <p className="text-xs text-muted-foreground mt-2 px-0.5 flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" />
              {deepProgress || 'Researching…'} <span className="opacity-60">(this can take a few minutes)</span>
            </p>
          )}

          {deepPhase === 'done' && (
            <div className="mt-2 space-y-2">
              {/* Report */}
              {report && (
                <div className="rounded-md border border-border/50 bg-background/40">
                  <button
                    className="w-full flex items-center justify-between px-2 py-1 text-xs font-medium"
                    onClick={() => setShowReport((s) => !s)}
                  >
                    <span>Report</span>
                    <span className="text-muted-foreground">{showReport ? 'Hide' : 'Show'}</span>
                  </button>
                  {showReport && (
                    <div className="px-2 pb-2 max-h-60 overflow-y-auto prose prose-sm dark:prose-invert max-w-none break-words [&_*]:!my-1">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
                    </div>
                  )}
                </div>
              )}

              {/* Source tabs */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1 text-xs">
                  <button
                    className={cn('px-1.5 py-0.5 rounded', deepTab === 'cited' ? 'bg-muted font-medium' : 'text-muted-foreground')}
                    onClick={() => setDeepTab('cited')}
                  >
                    Cited ({cited.length})
                  </button>
                  <button
                    className={cn('px-1.5 py-0.5 rounded', deepTab === 'found' ? 'bg-muted font-medium' : 'text-muted-foreground')}
                    onClick={() => setDeepTab('found')}
                  >
                    Also found ({alsoFound.length})
                  </button>
                </div>
                {activeList.length > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-1.5 text-xs gap-1"
                    disabled={addingAll}
                    onClick={() => addAll(activeList)}
                  >
                    {addingAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Add all
                  </Button>
                )}
              </div>

              <div className="space-y-0.5 max-h-72 overflow-y-auto">
                {activeList.length === 0 ? (
                  <p className="text-xs text-muted-foreground px-0.5 py-2">No sources in this list.</p>
                ) : (
                  activeList.map((s) => (
                    <ResultRow
                      key={s.url}
                      url={s.url}
                      title={s.title}
                      snippet={s.summary}
                      imported={imported[s.url]}
                      importing={importing[s.url]}
                      onAdd={() => importOne(s.url, s.title)}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
