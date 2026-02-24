'use client'

import { useEffect, useRef } from 'react'
import {
  X,
  Terminal,
  Wrench,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronRight,
  Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useOpenClawStore, type WorkspaceLogEvent } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

// ─── Individual log event renderers ──────────────────────────────────────────

function TokenLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <span className="text-foreground/90 font-mono text-xs leading-relaxed">
      {event.content}
    </span>
  )
}

function ToolCallLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <div className="flex items-start gap-2 py-1">
      <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
        <Wrench className="h-3.5 w-3.5 text-blue-400" />
        <span className="text-xs font-semibold text-blue-400">{event.tool}</span>
      </div>
      {event.args && Object.keys(event.args).length > 0 && (
        <pre className="text-[10px] text-muted-foreground overflow-x-auto max-w-full leading-relaxed">
          {JSON.stringify(event.args, null, 2).slice(0, 200)}
          {JSON.stringify(event.args).length > 200 ? '…' : ''}
        </pre>
      )}
    </div>
  )
}

function ToolResultLine({ event }: { event: WorkspaceLogEvent }) {
  return (
    <div className="flex items-start gap-2 py-1 pl-2 border-l-2 border-l-green-500/40">
      {event.success !== false ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0 mt-0.5" />
      ) : (
        <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
      )}
      <pre className="text-[10px] text-muted-foreground overflow-x-auto max-w-full leading-relaxed whitespace-pre-wrap">
        {String(event.output ?? '').slice(0, 400)}
        {(event.output?.length ?? 0) > 400 ? '\n…(truncated)' : ''}
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

function LogEvent({ event }: { event: WorkspaceLogEvent }) {
  switch (event.type) {
    case 'token':       return <TokenLine event={event} />
    case 'tool_call':   return <ToolCallLine event={event} />
    case 'tool_result': return <ToolResultLine event={event} />
    case 'log':         return <LogLine event={event} />
    case 'done':        return <DoneLine event={event} />
    case 'cancelled':   return <CancelledLine />
    case 'error':       return <ErrorLine event={event} />
    default:            return null
  }
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

  // Infer status from last terminal event
  const lastEvent = logEvents[logEvents.length - 1]
  const isDone = lastEvent?.type === 'done'
  const isCancelled = lastEvent?.type === 'cancelled'
  const isError = lastEvent?.type === 'error'
  const isRunning = !isDone && !isCancelled && !isError

  // Group consecutive tokens into blocks so they don't render as 100 separate divs
  const tokenBuffer = logEvents
    .filter((e) => e.type === 'token')
    .map((e) => e.content ?? '')
    .join('')

  // Non-token events for the progress log
  const nonTokenEvents = logEvents.filter((e) => e.type !== 'token')

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

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border px-4 pt-1 shrink-0">
        {(['progress', 'logs'] as const).map((tab) => (
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
                  <LogEvent key={event.id} event={event} />
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
