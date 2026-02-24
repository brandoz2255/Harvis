'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  X,
  Terminal,
  Wrench,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  Loader2,
  Clock,
  Hash,
  Activity,
  History,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useOpenClawStore, type WorkspaceLogEvent } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

// ─── Stats bar ────────────────────────────────────────────────────────────────

interface StatsBarProps {
  elapsedMs: number
  toolCallCount: number
  eventCount: number
  isRunning: boolean
}

function StatsBar({ elapsedMs, toolCallCount, eventCount, isRunning }: StatsBarProps) {
  return (
    <div className="flex items-center gap-4 border-b border-border px-4 py-1.5 shrink-0 bg-muted/30">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3" />
        <span className={cn('font-mono tabular-nums', isRunning && 'text-violet-400')}>
          {formatDuration(elapsedMs)}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Wrench className="h-3 w-3" />
        <span>{toolCallCount} tool {toolCallCount === 1 ? 'call' : 'calls'}</span>
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Activity className="h-3 w-3" />
        <span>{eventCount} events</span>
      </div>
    </div>
  )
}

// ─── Individual log event renderers ──────────────────────────────────────────

function TokenLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <span className="text-foreground/90 font-mono text-xs leading-relaxed">
      {event.content}
    </span>
  )
}

interface ToolCallLineProps {
  event: WorkspaceLogEvent
  stepNumber: number
}

function ToolCallLine({ event, stepNumber }: ToolCallLineProps) {
  const [expanded, setExpanded] = useState(false)
  const hasArgs = event.args && Object.keys(event.args).length > 0
  const argsStr = hasArgs ? JSON.stringify(event.args, null, 2) : ''

  return (
    <div className="py-1">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full text-left group"
      >
        <span className="text-[10px] text-muted-foreground/60 font-mono w-5 shrink-0 text-right">
          #{stepNumber}
        </span>
        <span className="inline-flex items-center gap-1 bg-blue-500/15 border border-blue-500/30 text-blue-400 text-[11px] font-semibold px-2 py-0.5 rounded-full">
          <Wrench className="h-2.5 w-2.5" />
          {event.tool}
        </span>
        {hasArgs && (
          <ChevronDown
            className={cn(
              'h-3 w-3 text-muted-foreground/50 transition-transform',
              expanded && 'rotate-180'
            )}
          />
        )}
        {!hasArgs && (
          <span className="text-[10px] text-muted-foreground/40 italic">no args</span>
        )}
      </button>
      {expanded && hasArgs && (
        <div className="mt-1.5 ml-7">
          <pre className="text-[10px] text-muted-foreground bg-muted rounded px-3 py-2 overflow-x-auto leading-relaxed">
            {argsStr.length > 800 ? argsStr.slice(0, 800) + '\n…(truncated)' : argsStr}
          </pre>
        </div>
      )}
    </div>
  )
}

function ToolResultLine({ event }: { event: WorkspaceLogEvent }) {
  const success = event.success !== false
  const output = String(event.output ?? '')
  return (
    <div
      className={cn(
        'flex items-start gap-2 py-1 pl-2 border-l-2',
        success ? 'border-l-green-500/40' : 'border-l-red-500/40'
      )}
    >
      {success ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0 mt-0.5" />
      ) : (
        <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
      )}
      <pre
        className={cn(
          'text-[10px] text-muted-foreground overflow-y-auto overflow-x-auto max-h-32 max-w-full leading-relaxed whitespace-pre-wrap rounded px-2 py-1',
          success ? 'bg-green-500/5' : 'bg-red-500/5'
        )}
      >
        {output.length > 600 ? output.slice(0, 600) + '\n…(truncated)' : output || '(no output)'}
      </pre>
    </div>
  )
}

function LogLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <div className="flex items-start gap-2 py-0.5 text-muted-foreground">
      <ChevronRight className="h-3 w-3 shrink-0 mt-0.5 opacity-50" />
      <span className="text-xs leading-relaxed">{event.message}</span>
    </div>
  )
}

function DoneLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <div className="flex items-start gap-2 py-1.5 rounded-lg bg-green-500/10 px-3 mt-2">
      <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0 mt-0.5" />
      <div>
        <p className="text-xs font-semibold text-green-400">Workspace complete</p>
        {event.summary && (
          <p className="text-xs text-foreground/80 mt-0.5 leading-relaxed">{event.summary}</p>
        )}
      </div>
    </div>
  )
}

function CancelledLine() {
  return (
    <div className="flex items-center gap-2 py-1.5 rounded-lg bg-orange-500/10 px-3 mt-2">
      <XCircle className="h-4 w-4 text-orange-400 shrink-0" />
      <p className="text-xs font-semibold text-orange-400">Workspace cancelled</p>
    </div>
  )
}

function ErrorLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <div className="flex items-start gap-2 py-1.5 rounded-lg bg-red-500/10 px-3 mt-2">
      <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
      <div>
        <p className="text-xs font-semibold text-red-400">Error</p>
        {event.message && (
          <p className="text-xs text-foreground/80 mt-0.5">{event.message}</p>
        )}
      </div>
    </div>
  )
}

// Tracks tool_call step numbers across renders
function LogEvent({
  event,
  toolCallIndex,
}: {
  event: WorkspaceLogEvent
  toolCallIndex: number
}) {
  switch (event.type) {
    case 'token':       return <TokenLine event={event} />
    case 'tool_call':   return <ToolCallLine event={event} stepNumber={toolCallIndex} />
    case 'tool_result': return <ToolResultLine event={event} />
    case 'log':         return <LogLine event={event} />
    case 'done':        return <DoneLine event={event} />
    case 'cancelled':   return <CancelledLine />
    case 'error':       return <ErrorLine event={event} />
    default:            return null
  }
}

// ─── History tab types ────────────────────────────────────────────────────────

interface WorkspaceRun {
  id: string
  session_id: string
  task_brief: string
  status: 'running' | 'done' | 'cancelled' | 'error'
  started_at: string
  completed_at: string | null
  duration_ms: number | null
  event_count: number
  tool_calls: number
  final_summary: string | null
  error_message: string | null
}

interface StoredEvent {
  id: number
  workspace_id: string
  seq: number
  event_type: string
  payload: Record<string, unknown>
  ts: string
}

// ─── History sub-components ───────────────────────────────────────────────────

function StatusBadge({ status }: { status: WorkspaceRun['status'] }) {
  const styles = {
    running:   'text-violet-400 bg-violet-400/10 border-violet-400/30',
    done:      'text-green-400 bg-green-400/10 border-green-400/30',
    cancelled: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
    error:     'text-red-400 bg-red-400/10 border-red-400/30',
  }
  const labels = {
    running: 'Running', done: 'Done', cancelled: 'Cancelled', error: 'Error',
  }
  return (
    <span className={cn('text-[10px] font-medium px-1.5 py-0.5 rounded-full border', styles[status])}>
      {labels[status]}
    </span>
  )
}

function StoredEventLine({ event }: { event: StoredEvent }) {
  const p = event.payload
  switch (event.event_type) {
    case 'tool_call':
      return (
        <div className="flex items-center gap-2 py-0.5">
          <span className="inline-flex items-center gap-1 bg-blue-500/15 border border-blue-500/30 text-blue-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full">
            <Wrench className="h-2.5 w-2.5" />
            {String(p.tool ?? 'unknown')}
          </span>
        </div>
      )
    case 'tool_result':
      return (
        <div className={cn('flex items-start gap-1.5 py-0.5 pl-2 border-l-2', p.success !== false ? 'border-l-green-500/40' : 'border-l-red-500/40')}>
          {p.success !== false
            ? <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0 mt-0.5" />
            : <XCircle className="h-3 w-3 text-red-400 shrink-0 mt-0.5" />
          }
          <span className="text-[10px] text-muted-foreground truncate">
            {String(p.output ?? '').slice(0, 120) || '(no output)'}
          </span>
        </div>
      )
    case 'log':
      return (
        <div className="flex items-start gap-1.5 py-0.5 text-muted-foreground">
          <ChevronRight className="h-3 w-3 shrink-0 mt-0.5 opacity-50" />
          <span className="text-[10px]">{String(p.message ?? '')}</span>
        </div>
      )
    case 'done':
      return (
        <div className="flex items-start gap-1.5 py-1 rounded bg-green-500/10 px-2 mt-1">
          <CheckCircle2 className="h-3 w-3 text-green-400 shrink-0 mt-0.5" />
          <span className="text-[10px] font-medium text-green-400">Complete</span>
          {p.summary && (
            <span className="text-[10px] text-foreground/70 ml-1 truncate">{String(p.summary)}</span>
          )}
        </div>
      )
    case 'error':
      return (
        <div className="flex items-start gap-1.5 py-1 rounded bg-red-500/10 px-2 mt-1">
          <AlertCircle className="h-3 w-3 text-red-400 shrink-0 mt-0.5" />
          <span className="text-[10px] font-medium text-red-400">{String(p.message ?? 'Error')}</span>
        </div>
      )
    default:
      return null
  }
}

interface HistoryRunCardProps {
  run: WorkspaceRun
  onSelect: (run: WorkspaceRun) => void
  isSelected: boolean
}

function HistoryRunCard({ run, onSelect, isSelected }: HistoryRunCardProps) {
  return (
    <button
      onClick={() => onSelect(run)}
      className={cn(
        'w-full text-left rounded-lg border px-3 py-2.5 transition-colors',
        isSelected
          ? 'border-violet-500/50 bg-violet-500/10'
          : 'border-border hover:border-border/80 hover:bg-muted/50'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-foreground/90 leading-snug line-clamp-2 flex-1">
          {run.task_brief}
        </p>
        <StatusBadge status={run.status} />
      </div>
      <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-2.5 w-2.5" />
          {run.duration_ms != null ? formatDuration(run.duration_ms) : '—'}
        </span>
        <span className="flex items-center gap-1">
          <Wrench className="h-2.5 w-2.5" />
          {run.tool_calls}
        </span>
        <span className="ml-auto">{formatRelativeTime(run.started_at)}</span>
      </div>
    </button>
  )
}

// ─── History tab ──────────────────────────────────────────────────────────────

function HistoryTab() {
  const [runs, setRuns] = useState<WorkspaceRun[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRun, setSelectedRun] = useState<WorkspaceRun | null>(null)
  const [runEvents, setRunEvents] = useState<StoredEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)

  const fetchHistory = useCallback(async () => {
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch('/api/workspace/history', { headers })
      if (res.ok) {
        const data = await res.json()
        setRuns(data.runs ?? [])
      }
    } catch {
      // silently fail — history is a nice-to-have
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchRunEvents = useCallback(async (runId: string) => {
    setEventsLoading(true)
    setRunEvents([])
    try {
      const token = localStorage.getItem('token')
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`/api/workspace/run/${runId}/events`, { headers })
      if (res.ok) {
        const data = await res.json()
        setRunEvents(data.events ?? [])
      }
    } catch {
      // silently fail
    } finally {
      setEventsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  const handleSelectRun = (run: WorkspaceRun) => {
    setSelectedRun(run)
    fetchRunEvents(run.id)
  }

  const handleBack = () => {
    setSelectedRun(null)
    setRunEvents([])
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin mr-2" />
        <span className="text-xs">Loading history…</span>
      </div>
    )
  }

  // Detail view: events for a selected run
  if (selectedRun) {
    return (
      <div className="space-y-2">
        <button
          onClick={handleBack}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronRight className="h-3 w-3 rotate-180" />
          Back to history
        </button>
        <div className="rounded-lg border border-border px-3 py-2 bg-muted/20">
          <p className="text-xs font-medium text-foreground/90 leading-snug mb-1">
            {selectedRun.task_brief}
          </p>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <StatusBadge status={selectedRun.status} />
            {selectedRun.duration_ms != null && (
              <span>{formatDuration(selectedRun.duration_ms)}</span>
            )}
            <span>{formatRelativeTime(selectedRun.started_at)}</span>
          </div>
        </div>
        {eventsLoading ? (
          <div className="flex items-center gap-2 py-4 text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span className="text-xs">Loading events…</span>
          </div>
        ) : runEvents.length === 0 ? (
          <p className="text-xs text-muted-foreground py-4 text-center">No stored events found</p>
        ) : (
          <div className="space-y-0.5">
            {runEvents.map((evt) => (
              <StoredEventLine key={evt.id} event={evt} />
            ))}
          </div>
        )}
      </div>
    )
  }

  // List view
  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-muted-foreground gap-2">
        <History className="h-8 w-8 opacity-30" />
        <p className="text-xs">No workspace runs yet</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <HistoryRunCard
          key={run.id}
          run={run}
          onSelect={handleSelectRun}
          isSelected={selectedRun?.id === run.id}
        />
      ))}
    </div>
  )
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export function WorkspacePanel() {
  const {
    workspaceId,
    logEvents,
    finalSummary,
    currentTask,
    closeWorkspace,
    activeTab,
    setActiveTab,
  } = useOpenClawStore()

  const scrollRef = useRef<HTMLDivElement>(null)

  // Elapsed timer state
  const [elapsedMs, setElapsedMs] = useState(0)
  const startEpochRef = useRef<number>(Date.now())

  // Infer status from last terminal event
  const lastEvent = logEvents[logEvents.length - 1]
  const isDone = lastEvent?.type === 'done'
  const isCancelled = lastEvent?.type === 'cancelled'
  const isError = lastEvent?.type === 'error'
  const isRunning = !isDone && !isCancelled && !isError

  // Start/stop timer based on running state
  useEffect(() => {
    if (isRunning) {
      startEpochRef.current = Date.now()
      setElapsedMs(0)
      const interval = setInterval(() => {
        setElapsedMs(Date.now() - startEpochRef.current)
      }, 1000)
      return () => clearInterval(interval)
    }
  }, [isRunning])

  // Freeze timer on completion
  useEffect(() => {
    if (!isRunning) {
      setElapsedMs(Date.now() - startEpochRef.current)
    }
  }, [isRunning])

  // Compute stats
  const toolCallCount = logEvents.filter((e) => e.type === 'tool_call').length
  const eventCount = logEvents.filter((e) => e.type !== 'stream_end').length

  // Group consecutive tokens into blocks
  const tokenBuffer = logEvents
    .filter((e) => e.type === 'token')
    .map((e) => e.content ?? '')
    .join('')

  // Non-token events for the progress log
  const nonTokenEvents = logEvents.filter((e) => e.type !== 'token')

  // Build per-event tool_call index for step numbers
  let toolCallSeq = 0
  const toolCallIndices = logEvents.map((e) => {
    if (e.type === 'tool_call') {
      toolCallSeq += 1
      return toolCallSeq
    }
    return 0
  })
  // Map from event.id to its tool call index
  const toolCallIndexMap = new Map<string, number>()
  logEvents.forEach((e, i) => {
    if (e.type === 'tool_call') {
      toolCallIndexMap.set(e.id, toolCallIndices[i])
    }
  })

  // Auto-scroll to bottom as events arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logEvents.length])

  const handleCancel = async () => {
    if (!workspaceId) return
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    await fetch(`/api/workspace/cancel/${workspaceId}`, { method: 'POST', headers })
    closeWorkspace()
  }

  const taskBrief = currentTask?.description ?? 'Running workspace task…'

  const tabs = ['progress', 'logs', 'history'] as const

  return (
    <div className="flex h-full flex-col bg-card border-l border-border">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-500/20">
            <Terminal className="h-3.5 w-3.5 text-violet-400" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">Workspace</span>
              {isRunning && (
                <Loader2 className="h-3 w-3 animate-spin text-violet-400" />
              )}
              {isDone && (
                <span className="text-[10px] font-medium text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                  Done
                </span>
              )}
              {isCancelled && (
                <span className="text-[10px] font-medium text-orange-400 bg-orange-400/10 px-1.5 py-0.5 rounded-full">
                  Cancelled
                </span>
              )}
              {isError && (
                <span className="text-[10px] font-medium text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded-full">
                  Error
                </span>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground truncate max-w-[220px]">
              {taskBrief}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {isRunning && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCancel}
              className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>
          )}
          {!isRunning && (
            <Button
              variant="ghost"
              size="icon"
              onClick={closeWorkspace}
              className="h-7 w-7 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Stats bar — only shown on progress/logs tabs while there is activity */}
      {activeTab !== 'history' && (logEvents.length > 0 || !isRunning) && (
        <StatsBar
          elapsedMs={elapsedMs}
          toolCallCount={toolCallCount}
          eventCount={eventCount}
          isRunning={isRunning}
        />
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border px-4 pt-1 shrink-0">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'pb-2 px-1 text-xs font-medium capitalize transition-colors border-b-2 -mb-px',
              activeTab === tab
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden" ref={scrollRef}>
        <ScrollArea className="h-full">
          <div className="px-4 py-3 space-y-0.5">
            {activeTab === 'progress' && (
              <>
                {/* Streamed token output at the top */}
                {tokenBuffer && (
                  <div className="mb-3 rounded-lg bg-background/50 p-3 font-mono text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap border border-border/50">
                    {tokenBuffer}
                  </div>
                )}
                {/* Tool calls, results, logs, terminal events */}
                {nonTokenEvents.map((event) => (
                  <LogEvent
                    key={event.id}
                    event={event}
                    toolCallIndex={toolCallIndexMap.get(event.id) ?? 0}
                  />
                ))}
                {/* Running indicator */}
                {isRunning && logEvents.length === 0 && (
                  <div className="flex items-center gap-2 py-2 text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span className="text-xs">Connecting to workspace…</span>
                  </div>
                )}
              </>
            )}

            {activeTab === 'logs' && (
              <div className="space-y-0.5">
                {logEvents.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-4 text-center">
                    No log events yet
                  </p>
                ) : (
                  logEvents.map((event) => (
                    <div
                      key={event.id}
                      className="flex items-start gap-2 py-0.5 font-mono text-[10px] text-muted-foreground"
                    >
                      <span className="shrink-0 opacity-50">
                        {new Date(event.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </span>
                      <span className="uppercase text-violet-400/70 shrink-0 w-14">
                        {event.type}
                      </span>
                      <span className="break-all">
                        {event.content ??
                          event.message ??
                          event.summary ??
                          event.tool ??
                          ''}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'history' && <HistoryTab />}
          </div>
        </ScrollArea>
      </div>

      {/* Footer — final summary pill */}
      {finalSummary && (
        <div className="shrink-0 border-t border-border px-4 py-2">
          <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
            <span className="font-medium text-foreground">Summary: </span>
            {finalSummary}
          </p>
        </div>
      )}
    </div>
  )
}
