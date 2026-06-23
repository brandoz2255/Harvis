'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ChefHat,
  Cpu,
  Download,
  HardDrive,
  RefreshCw,
  Server,
  Check,
  Loader2,
  AlertCircle,
  Gauge,
} from 'lucide-react'

// =============================================================================
// Cookbook — Harvis's hardware-aware model fit list (backed by /api/cookbook/*,
// the same llmfit-serve + Ollama proxy the Harvis shell uses). Served same-origin
// under /onb, this calls /api/cookbook directly (NOT the /onb-api facade) and
// reuses the shared Harvis OWUI JWT at localStorage.token.
// =============================================================================

interface CookbookNode {
  name: string
  role?: string
  alive: boolean
  latency_ms?: number | null
  llmfit_url?: string
  ollama_url?: string
  error?: string
}

interface CookbookModel {
  name: string
  params_b?: number
  parameter_count?: string
  best_quant?: string
  context_length?: number
  estimated_tps?: number
  fit_label?: string
  fit_level?: string
  memory_required_gb?: number
  downloadable?: boolean
  serving?: string
  ollama_tag?: string
  reason?: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any
}

interface InstalledModel {
  name: string
  model?: string
  size?: number
  details?: {
    parameter_size?: string
    quantization_level?: string
    family?: string
  }
}

function authToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}

async function cookbookGet<T>(path: string): Promise<T> {
  const token = authToken()
  const res = await fetch(`/api/cookbook${path}`, {
    headers: {
      Accept: 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

function fmtGB(bytes?: number): string {
  if (!bytes) return ''
  return `${(bytes / 1e9).toFixed(1)} GB`
}

const FIT_COLORS: Record<string, string> = {
  excellent: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  good: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  tight: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  marginal: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  poor: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}

function fitColor(level?: string): string {
  if (!level) return 'bg-muted text-muted-foreground'
  const key = level.toLowerCase()
  for (const k of Object.keys(FIT_COLORS)) {
    if (key.includes(k)) return FIT_COLORS[k]
  }
  return 'bg-muted text-muted-foreground'
}

export function CookbookSection() {
  const [nodes, setNodes] = useState<CookbookNode[]>([])
  const [node, setNode] = useState<string>('')
  const [installed, setInstalled] = useState<InstalledModel[]>([])
  const [recommended, setRecommended] = useState<CookbookModel[]>([])
  const [system, setSystem] = useState<Record<string, unknown> | null>(null)
  const [loadingNodes, setLoadingNodes] = useState(true)
  const [loadingModels, setLoadingModels] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<Record<string, string>>({})

  // Load the node list once, pick a sensible default (the 'main' node if alive,
  // else the first alive node, else the first listed).
  useEffect(() => {
    let cancelled = false
    setLoadingNodes(true)
    cookbookGet<{ nodes: CookbookNode[] }>('/nodes')
      .then((res) => {
        if (cancelled) return
        const list = res?.nodes ?? []
        setNodes(list)
        const preferred =
          list.find((n) => n.role === 'main' && n.alive) ||
          list.find((n) => n.alive) ||
          list[0]
        if (preferred) setNode(preferred.name)
        else setError('No model nodes are configured.')
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoadingNodes(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const loadModels = useCallback(async (nodeName: string) => {
    if (!nodeName) return
    setLoadingModels(true)
    setError(null)
    const q = `?node=${encodeURIComponent(nodeName)}`
    const [inst, rec, sys] = await Promise.allSettled([
      cookbookGet<{ models: InstalledModel[]; error?: string }>(`/installed${q}`),
      cookbookGet<{ models: CookbookModel[]; system?: Record<string, unknown> }>(`/recommend${q}&limit=12`),
      cookbookGet<Record<string, unknown>>(`/system${q}`),
    ])
    if (inst.status === 'fulfilled') setInstalled(inst.value?.models ?? [])
    else setInstalled([])
    if (rec.status === 'fulfilled') {
      setRecommended(rec.value?.models ?? [])
      if (rec.value?.system) setSystem(rec.value.system)
    } else {
      setRecommended([])
    }
    if (sys.status === 'fulfilled') setSystem((prev) => sys.value ?? prev)
    // Surface an error only when everything failed (node unreachable).
    if (inst.status === 'rejected' && rec.status === 'rejected') {
      const reason = rec.reason instanceof Error ? rec.reason.message : String(rec.reason)
      setError(`Couldn't reach the model node "${nodeName}": ${reason}`)
    }
    setLoadingModels(false)
  }, [])

  useEffect(() => {
    if (node) loadModels(node)
  }, [node, loadModels])

  const handleDownload = useCallback(
    async (model: CookbookModel) => {
      const tag = model.ollama_tag || model.name
      if (!tag || !node) return
      setDownloading((prev) => ({ ...prev, [model.name]: 'Starting…' }))
      try {
        const token = authToken()
        const res = await fetch('/api/cookbook/download', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...(token ? { authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ node, ollama_tag: tag }),
        })
        if (!res.ok || !res.body) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body?.detail || `HTTP ${res.status}`)
        }
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const parts = buf.split('\n\n')
          buf = parts.pop() || ''
          for (const part of parts) {
            const line = part.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            try {
              const evt = JSON.parse(line.slice(5).trim())
              if (evt.error) throw new Error(evt.error)
              let label = evt.status || 'Downloading…'
              if (evt.total && evt.completed) {
                label = `${Math.round((evt.completed / evt.total) * 100)}%`
              }
              setDownloading((prev) => ({ ...prev, [model.name]: label }))
            } catch {
              /* ignore malformed line */
            }
          }
        }
        setDownloading((prev) => ({ ...prev, [model.name]: 'done' }))
        loadModels(node)
      } catch (e) {
        setDownloading((prev) => ({
          ...prev,
          [model.name]: `error: ${e instanceof Error ? e.message : String(e)}`,
        }))
      }
    },
    [node, loadModels]
  )

  const installedNames = new Set(installed.map((m) => (m.name || '').split(':')[0]))

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ChefHat className="h-5 w-5" />
              Cookbook — Local Models
            </CardTitle>
            <CardDescription>
              Models that fit this machine&apos;s hardware. Install what you need; cloud API keys are
              optional and live further down.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {nodes.length > 1 && (
              <Select value={node} onValueChange={setNode}>
                <SelectTrigger className="h-8 w-[160px] text-xs">
                  <Server className="h-3.5 w-3.5 mr-1" />
                  <SelectValue placeholder="Node" />
                </SelectTrigger>
                <SelectContent>
                  {nodes.map((n) => (
                    <SelectItem key={n.name} value={n.name}>
                      {n.name}
                      {n.role === 'main' ? ' (main)' : ''}
                      {!n.alive ? ' • offline' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => node && loadModels(node)}
              disabled={loadingModels || !node}
              title="Refresh"
            >
              <RefreshCw className={`h-4 w-4 ${loadingModels ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
        {system && (system.gpu_name || system.total_ram_gb || system.vram_gb) ? (
          <div className="flex flex-wrap items-center gap-3 pt-1 text-xs text-muted-foreground">
            {system.gpu_name ? (
              <span className="flex items-center gap-1">
                <Cpu className="h-3.5 w-3.5" />
                {String(system.gpu_name)}
                {system.vram_gb ? ` · ${String(system.vram_gb)} GB VRAM` : ''}
              </span>
            ) : null}
            {system.total_ram_gb ? (
              <span className="flex items-center gap-1">
                <HardDrive className="h-3.5 w-3.5" />
                {String(system.total_ram_gb)} GB RAM
              </span>
            ) : null}
          </div>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-6">
        {loadingNodes ? (
          <div className="flex items-center justify-center py-8">
            <LoadingSpinner size="lg" />
          </div>
        ) : error && installed.length === 0 && recommended.length === 0 ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <>
            {/* Installed models — what's ready to use right now */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">Installed</h3>
                <Badge variant="secondary" className="text-[10px]">
                  {installed.length}
                </Badge>
                <span className="text-xs text-muted-foreground">ready to use</span>
              </div>
              {loadingModels && installed.length === 0 ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                </div>
              ) : installed.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2">
                  No models pulled yet — install one from the recommendations below.
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {installed.map((m) => (
                    <div
                      key={m.name}
                      className="flex items-center justify-between rounded-lg border p-2.5 text-sm"
                    >
                      <div className="min-w-0">
                        <div className="font-medium truncate">{m.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {m.details?.parameter_size || ''}
                          {m.details?.quantization_level ? ` · ${m.details.quantization_level}` : ''}
                          {m.size ? ` · ${fmtGB(m.size)}` : ''}
                        </div>
                      </div>
                      <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 shrink-0">
                        <Check className="h-3 w-3 mr-0.5" />
                        Installed
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recommended (hardware-fit) models — the cookbook list */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Gauge className="h-4 w-4" />
                <h3 className="text-sm font-semibold">Recommended for this machine</h3>
              </div>
              {loadingModels && recommended.length === 0 ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> Ranking models…
                </div>
              ) : recommended.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2">
                  No recommendations available for this node.
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  {recommended.map((m) => {
                    const isInstalled = installedNames.has((m.ollama_tag || m.name).split(':')[0])
                    const dl = downloading[m.name]
                    const inProgress = dl !== undefined && dl !== 'done' && !dl?.startsWith('error')
                    return (
                      <div key={m.name} className="rounded-lg border p-2.5 text-sm space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium truncate">{m.name}</span>
                          {m.fit_label && (
                            <Badge className={`text-[10px] shrink-0 ${fitColor(m.fit_level)}`}>
                              {m.fit_label}
                            </Badge>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                          {m.params_b ? <span>{m.params_b}B params</span> : null}
                          {m.best_quant ? <span>{m.best_quant}</span> : null}
                          {m.estimated_tps ? <span>~{Math.round(m.estimated_tps)} tok/s</span> : null}
                          {m.memory_required_gb ? <span>{m.memory_required_gb} GB</span> : null}
                        </div>
                        <div className="flex items-center justify-between pt-0.5">
                          <span className="text-[10px] text-muted-foreground">
                            {m.serving === 'server' ? 'GPU server / vLLM' : 'Local (Ollama)'}
                          </span>
                          {isInstalled ? (
                            <Badge variant="outline" className="text-[10px]">
                              <Check className="h-3 w-3 mr-0.5" /> Installed
                            </Badge>
                          ) : dl === 'done' ? (
                            <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 text-[10px]">
                              <Check className="h-3 w-3 mr-0.5" /> Done
                            </Badge>
                          ) : m.serving !== 'server' ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs gap-1"
                              disabled={inProgress}
                              onClick={() => handleDownload(m)}
                              title={dl?.startsWith('error') ? dl : 'Install this model'}
                            >
                              {inProgress ? (
                                <>
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  {dl}
                                </>
                              ) : (
                                <>
                                  <Download className="h-3 w-3" />
                                  {dl?.startsWith('error') ? 'Retry' : 'Install'}
                                </>
                              )}
                            </Button>
                          ) : null}
                        </div>
                        {dl?.startsWith('error') && (
                          <p className="text-[10px] text-destructive">{dl}</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
