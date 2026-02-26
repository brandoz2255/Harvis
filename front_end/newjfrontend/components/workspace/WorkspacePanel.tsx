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
  Cpu,
  FileText,
  Pencil,
  Zap,
  RefreshCw,
  MessageSquare,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
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

const PHASE_CONFIG = {
  connecting: { label: 'Connecting', color: 'text-yellow-400', bg: 'bg-yellow-400/10 border-yellow-400/30', dot: 'bg-yellow-400' },
  thinking: { label: 'Thinking', color: 'text-violet-400', bg: 'bg-violet-400/10 border-violet-400/30', dot: 'bg-violet-400' },
  executing: { label: 'Executing', color: 'text-blue-400', bg: 'bg-blue-400/10 border-blue-400/30', dot: 'bg-blue-400' },
  done: { label: 'Complete', color: 'text-green-400', bg: 'bg-green-400/10 border-green-400/30', dot: 'bg-green-400' },
  error: { label: 'Error', color: 'text-red-400', bg: 'bg-red-400/10 border-red-400/30', dot: 'bg-red-400' },
  cancelled: { label: 'Cancelled', color: 'text-orange-400', bg: 'bg-orange-400/10 border-orange-400/30', dot: 'bg-orange-400' },
} as const

type Phase = keyof typeof PHASE_CONFIG

interface StatsBarProps {
  elapsedMs: number
  toolCallCount: number
  eventCount: number
  isRunning: boolean
  phase: Phase
}

function StatsBar({ elapsedMs, toolCallCount, eventCount, isRunning, phase }: StatsBarProps) {
  const ps = PHASE_CONFIG[phase]
  return (
    <div className="flex items-center gap-3 border-b border-border px-4 py-2 shrink-0 bg-muted/20">
      {/* Phase pill */}
      <div className={cn('flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border', ps.bg, ps.color)}>
        {isRunning ? (
          <span className="relative flex h-2 w-2">
            <span className={cn('animate-ping absolute inline-flex h-full w-full rounded-full opacity-75', ps.dot)} />
            <span className={cn('relative inline-flex rounded-full h-2 w-2', ps.dot)} />
          </span>
        ) : (
          <span className={cn('h-2 w-2 rounded-full', ps.dot)} />
        )}
        {ps.label}
      </div>

      <div className="h-3 w-px bg-border" />

      {/* Counters */}
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3" />
        <span className={cn('font-mono tabular-nums', isRunning && 'text-violet-400')}>{formatDuration(elapsedMs)}</span>
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Wrench className="h-3 w-3" />
        <span>{toolCallCount}</span>
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Activity className="h-3 w-3" />
        <span>{eventCount}</span>
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

  // Display a friendlier label for common tools
  const toolConfig: Record<string, { icon: React.ReactNode; label: string }> = {
    exec: { icon: <Terminal className="h-3 w-3" />, label: 'Shell Command' },
    read: { icon: <FileText className="h-3 w-3" />, label: 'Read File' },
    write: { icon: <Pencil className="h-3 w-3" />, label: 'Write File' },
    run_code: { icon: <Zap className="h-3 w-3" />, label: 'Run Code' },
  }
  const config = toolConfig[event.tool ?? ''] ?? { icon: <Wrench className="h-3 w-3" />, label: event.tool ?? 'Tool' }

  // Show inline preview for exec commands
  const cmdPreview = event.tool === 'exec' && event.args?.command
    ? String(event.args.command).slice(0, 120)
    : null

  return (
    <div className="my-2 rounded-lg border border-blue-500/30 bg-blue-500/5 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 w-full text-left px-3 py-2 hover:bg-blue-500/10 transition-colors"
      >
        <span className="text-[10px] text-blue-400/70 font-mono w-5 shrink-0 text-right">
          #{stepNumber}
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-blue-300">
          {config.icon}
          {config.label}
        </span>
        {cmdPreview && (
          <code className="text-[10px] text-blue-400/60 font-mono truncate max-w-[200px]">
            {cmdPreview}
          </code>
        )}
        <span className="flex-1" />
        {hasArgs && (
          <ChevronDown
            className={cn(
              'h-3 w-3 text-blue-400/50 transition-transform shrink-0',
              expanded && 'rotate-180'
            )}
          />
        )}
      </button>
      {expanded && hasArgs && (
        <div className="border-t border-blue-500/20 px-3 py-2">
          <pre className="text-[10px] text-muted-foreground bg-muted/50 rounded px-3 py-2 overflow-x-auto leading-relaxed">
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
  const [expanded, setExpanded] = useState(output.length < 200)

  return (
    <div
      className={cn(
        'my-1 ml-4 rounded-lg border px-3 py-2',
        success
          ? 'border-green-500/30 bg-green-500/5'
          : 'border-red-500/30 bg-red-500/5'
      )}
    >
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-2 w-full text-left"
      >
        {success ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />
        )}
        <span className={cn(
          'text-[11px] font-medium',
          success ? 'text-green-400' : 'text-red-400'
        )}>
          {success ? 'Success' : 'Failed'}
        </span>
        {output.length > 0 && (
          <span className="text-[10px] text-muted-foreground/50">
            ({output.length} chars)
          </span>
        )}
        <span className="flex-1" />
        {output.length > 0 && (
          <ChevronDown
            className={cn(
              'h-3 w-3 text-muted-foreground/50 transition-transform',
              expanded && 'rotate-180'
            )}
          />
        )}
      </button>
      {expanded && output.length > 0 && (
        <pre
          className={cn(
            'mt-2 text-[10px] text-muted-foreground overflow-x-auto max-h-40 overflow-y-auto leading-relaxed whitespace-pre-wrap rounded px-2 py-1.5',
            success ? 'bg-green-500/5' : 'bg-red-500/5'
          )}
        >
          {output.length > 800 ? output.slice(0, 800) + '\n…(truncated)' : output || '(no output)'}
        </pre>
      )}
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

// ─── Collapsible AI response block ───────────────────────────────────────────

function CollapsibleTokenBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(true)
  const lineCount = text.split('\n').length

  return (
    <div className="rounded-lg border border-border/50 bg-background/50 overflow-hidden mb-2">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-2 w-full text-left px-3 py-1.5 hover:bg-muted/30 transition-colors"
      >
        <MessageSquare className="h-3 w-3 text-violet-400 shrink-0" />
        <span className="text-[11px] font-medium text-violet-300">AI Response</span>
        <span className="text-[10px] text-muted-foreground/50">{lineCount} lines</span>
        <span className="flex-1" />
        <ChevronDown className={cn('h-3 w-3 text-muted-foreground/50 transition-transform', expanded && 'rotate-180')} />
      </button>
      {expanded && (
        <div className="border-t border-border/30 px-3 py-2">
          <div className="font-mono text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
            {text}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Timeline event wrapper ─────────────────────────────────────────────────

function TimelineEvent({
  event,
  toolCallIndex,
}: {
  event: WorkspaceLogEvent
  toolCallIndex: number
}) {
  // Choose dot color based on event type
  const getDotColor = (type: string) => {
    switch (type) {
      case 'tool_call': return 'bg-blue-400'
      case 'tool_result': return event.success !== false ? 'bg-green-400' : 'bg-red-400'
      case 'done': return 'bg-green-400'
      case 'cancelled': return 'bg-orange-400'
      case 'error': return 'bg-red-400'
      case 'log': return 'bg-muted-foreground/50'
      default: return 'bg-muted-foreground/30'
    }
  }
  const dotColor = getDotColor(event.type)

  return (
    <div className="relative flex gap-3 py-0.5">
      {/* Timeline dot */}
      <span className={cn('relative z-10 mt-1.5 h-[9px] w-[9px] rounded-full shrink-0 ring-2 ring-card', dotColor)} />
      {/* Content */}
      <div className="flex-1 min-w-0">
        <LogEvent event={event} toolCallIndex={toolCallIndex} />
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
    case 'token': return <TokenLine event={event} />
    case 'tool_call': return <ToolCallLine event={event} stepNumber={toolCallIndex} />
    case 'tool_result': return <ToolResultLine event={event} />
    case 'log': return <LogLine event={event} />
    case 'done': return <DoneLine event={event} />
    case 'cancelled': return <CancelledLine />
    case 'error': return <ErrorLine event={event} />
    default: return null
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
    running: 'text-violet-400 bg-violet-400/10 border-violet-400/30',
    done: 'text-green-400 bg-green-400/10 border-green-400/30',
    cancelled: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
    error: 'text-red-400 bg-red-400/10 border-red-400/30',
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
  onRerun: (run: WorkspaceRun) => void
  isRerunning: boolean
}

function HistoryRunCard({ run, onSelect, isSelected, onRerun, isRerunning }: HistoryRunCardProps) {
  return (
    <div
      className={cn(
        'rounded-lg border transition-colors',
        isSelected
          ? 'border-violet-500/50 bg-violet-500/10'
          : 'border-border hover:border-border/80'
      )}
    >
      <button
        onClick={() => onSelect(run)}
        className="w-full text-left px-3 pt-2.5 pb-1.5"
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
      {/* Rerun action */}
      <div className="px-3 pb-2 flex justify-end">
        <button
          onClick={(e) => { e.stopPropagation(); onRerun(run) }}
          disabled={isRerunning}
          title="Re-run this task"
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-violet-400 transition-colors disabled:opacity-50"
        >
          {isRerunning
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <RefreshCw className="h-3 w-3" />}
          <span>Rerun</span>
        </button>
      </div>
    </div>
  )
}

// ─── History tab ──────────────────────────────────────────────────────────────

function HistoryTab() {
  const [runs, setRuns] = useState<WorkspaceRun[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRun, setSelectedRun] = useState<WorkspaceRun | null>(null)
  const [runEvents, setRunEvents] = useState<StoredEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [rerunningId, setRerunningId] = useState<string | null>(null)

  const {
    setWorkspaceId,
    setWorkspaceSessionId,
    setWorkspaceActive,
    addLogEvent,
    clearLogEvents,
    setFinalSummary,
    setSseAbortController,
    setActiveTab,
  } = useOpenClawStore()

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

  const handleRerun = async (run: WorkspaceRun) => {
    setRerunningId(run.id)
    try {
      const token = localStorage.getItem('token')
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`/api/workspace/run/${run.id}/rerun`, { method: 'POST', headers })
      if (!res.ok) throw new Error(`Rerun failed: ${res.status}`)
      const data = await res.json()
      const { workspace_id, session_id } = data

      setWorkspaceId(workspace_id)
      setWorkspaceSessionId(session_id)
      clearLogEvents()
      setFinalSummary('')
      setActiveTab('dashboard')
      setWorkspaceActive(true)

      const controller = new AbortController()
      setSseAbortController(controller)

      const streamRes = await fetch(`/api/workspace/stream/${workspace_id}`, {
        headers: { 'Authorization': `Bearer ${token ?? ''}` },
        signal: controller.signal,
      })
      if (!streamRes.body) return

      const reader = streamRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = '';
      (async () => {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.type === 'stream_end') return
              if (event.type === 'done') setFinalSummary(event.summary ?? '')
              addLogEvent(event)
            } catch { /* ignore malformed */ }
          }
        }
      })().catch(() => {})
    } catch (err) {
      console.error('Workspace rerun error:', err)
    } finally {
      setRerunningId(null)
    }
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
          onRerun={handleRerun}
          isRerunning={rerunningId === run.id}
        />
      ))}
    </div>
  )
}

// ─── Sidebar nav items ──────────────────────────────────────────────────────

import { LayoutDashboard, BookOpen, ScrollText } from 'lucide-react'

const SIDEBAR_ITEMS = [
  { key: 'dashboard' as const, icon: LayoutDashboard, label: 'Dashboard' },
  { key: 'playbooks' as const, icon: BookOpen, label: 'Playbooks' },
  { key: 'logs' as const, icon: ScrollText, label: 'Logs' },
]

// ─── AI response text deduplication ──────────────────────────────────────────

function deduplicateText(raw: string): string {
  if (!raw) return raw
  // Split into paragraphs and drop near-exact duplicates
  const paragraphs = raw.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
  const unique: string[] = []
  for (const p of paragraphs) {
    const isDuplicate = unique.some(existing => {
      // Jaccard-like: if ≥80% of words overlap, consider duplicate
      const wordsA = new Set(existing.toLowerCase().split(/\s+/))
      const wordsB = new Set(p.toLowerCase().split(/\s+/))
      const overlap = [...wordsA].filter(w => wordsB.has(w)).length
      return overlap / Math.max(wordsA.size, wordsB.size) > 0.8
    })
    if (!isDuplicate) unique.push(p)
  }
  return unique.join('\n\n')
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export function WorkspacePanel({ onContinueInChat }: { onContinueInChat?: (summary: string) => void }) {
  const {
    workspaceId,
    workspaceModel,
    logEvents,
    finalSummary,
    currentTask,
    closeWorkspace,
    activeTab,
    setActiveTab,
    setSuggestion,
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

  // Compute current phase for the stats bar
  const phase: Phase = isDone
    ? 'done'
    : isError
      ? 'error'
      : isCancelled
        ? 'cancelled'
        : logEvents.some(e => e.type === 'tool_call')
          ? 'executing'
          : logEvents.some(e => e.type === 'token')
            ? 'thinking'
            : 'connecting'

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

  // Group consecutive tokens into blocks, then deduplicate
  const rawTokenBuffer = logEvents
    .filter((e) => e.type === 'token')
    .map((e) => e.content ?? '')
    .join('')
  const tokenBuffer = deduplicateText(rawTokenBuffer)

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

  return (
    <div className="flex h-full bg-card border-l border-border">
      {/* ─── Mini Sidebar ──────────────────────────────────────────── */}
      <div className="flex flex-col items-center w-12 shrink-0 border-r border-border bg-muted/20 py-2 gap-1">
        {SIDEBAR_ITEMS.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            title={label}
            className={cn(
              'flex items-center justify-center w-9 h-9 rounded-lg transition-colors',
              activeTab === key
                ? 'bg-violet-500/20 text-violet-400'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
            )}
          >
            <Icon className="h-4 w-4" />
          </button>
        ))}
      </div>

      {/* ─── Content Area ──────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Harvis Workspace Control
              </span>
              <span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full border border-border/50">
                <Cpu className="h-2.5 w-2.5" />
                {workspaceModel === 'kimi' ? 'Kimi K2.5' : workspaceModel === 'gpt-oss' ? 'GPT-OSS 120B' : 'Local'}
              </span>
            </div>
            {/* Prominent task title */}
            <p className="text-sm font-semibold text-foreground leading-tight truncate">{taskBrief}</p>
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

        {/* Stats bar — shown on dashboard/logs while there is activity */}
        {activeTab !== 'playbooks' && (logEvents.length > 0 || !isRunning) && (
          <StatsBar
            elapsedMs={elapsedMs}
            toolCallCount={toolCallCount}
            eventCount={eventCount}
            isRunning={isRunning}
            phase={phase}
          />
        )}

        {/* Body */}
        <div className="flex-1 overflow-hidden" ref={scrollRef}>
          <ScrollArea className="h-full">
            <div className="px-4 py-3 space-y-0.5">

              {/* ═══ Dashboard ═══ */}
              {activeTab === 'dashboard' && (
                <>
                  {/* Collapsible AI response */}
                  {tokenBuffer && (
                    <CollapsibleTokenBlock text={tokenBuffer} />
                  )}

                  {/* Timeline of tool calls, results, logs, terminal events */}
                  {nonTokenEvents.length > 0 && (
                    <div className="relative mt-2">
                      {/* Vertical timeline line */}
                      <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />

                      <div className="space-y-1">
                        {nonTokenEvents.map((event) => (
                          <TimelineEvent
                            key={event.id}
                            event={event}
                            toolCallIndex={toolCallIndexMap.get(event.id) ?? 0}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Running indicator */}
                  {isRunning && (
                    <div className="relative mt-2">
                      {logEvents.length > 0 && (
                        <div className="absolute left-[7px] top-0 bottom-0 w-px bg-border" />
                      )}
                      <div className="flex items-center gap-3 pl-0">
                        <span className="relative flex h-[15px] w-[15px] items-center justify-center shrink-0">
                          <span className="animate-ping absolute h-3 w-3 rounded-full bg-violet-400/60" />
                          <span className="relative h-2 w-2 rounded-full bg-violet-400" />
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {logEvents.length === 0 ? 'Connecting to workspace…' : 'Agent is working…'}
                        </span>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* ═══ Logs ═══ */}
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

              {/* ═══ Playbooks ═══ */}
              {activeTab === 'playbooks' && <HistoryTab />}
            </div>
          </ScrollArea>
        </div>

        {/* Footer — final summary + follow-up actions */}
        {finalSummary && (
          <div className="shrink-0 border-t border-border px-4 py-2 space-y-2">
            <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
              <span className="font-medium text-foreground">Summary: </span>
              {finalSummary}
            </p>
            {!isRunning && (
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1.5 border-violet-500/30 text-violet-300 hover:bg-violet-500/10"
                  onClick={() => {
                    // Re-launch workspace with same task for follow-up
                    setSuggestion({
                      should_suggest: true,
                      auto_launch: true,
                      confidence: 1.0,
                      task_type: 'multi_step',
                      task_type_label: 'Follow-up task',
                      task_brief: 'Continue the previous workspace task',
                      reason: 'User chose to continue in workspace.',
                    })
                    closeWorkspace()
                  }}
                >
                  <RefreshCw className="h-3 w-3" />
                  Send to Workspace
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1.5 border-border text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    if (onContinueInChat && finalSummary) {
                      onContinueInChat(finalSummary)
                    }
                    closeWorkspace()
                  }}
                >
                  <MessageSquare className="h-3 w-3" />
                  Continue in Chat
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

