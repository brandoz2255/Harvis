import { Button, cn, Codicon, GlyphSpinner, StatusDot, type StatusTone, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  ACTIVE_STATUSES,
  cancelRun,
  decideAction,
  FAILED_STATUSES,
  rerunRun,
  runsKey,
  streamRun,
  type WorkspaceEvent,
  type WorkspaceRun
} from './api'
import { buildTimeline } from './timeline'
import { TimelineRowView } from './timeline-rows'
import { formatDuration, formatTokens, relativeTime } from './format'

export function statusTone(status: string): StatusTone {
  if (ACTIVE_STATUSES.has(status)) {
    return 'warn'
  }

  return FAILED_STATUSES.has(status) ? 'bad' : status === 'done' ? 'good' : 'muted'
}

/** Buffers the SSE tail and flushes once per animation frame — a run emits
 *  thousands of token fragments, and one React commit per fragment would pin
 *  the renderer. */
function useRunEvents(runId: string) {
  const [events, setEvents] = useState<WorkspaceEvent[]>([])
  const [live, setLive] = useState(true)
  const pending = useRef<WorkspaceEvent[]>([])
  const frame = useRef(0)

  useEffect(() => {
    setEvents([])
    setLive(true)
    pending.current = []

    const flush = () => {
      frame.current = 0
      const batch = pending.current
      pending.current = []
      setEvents(prev => prev.concat(batch))
    }

    const stop = streamRun(
      runId,
      event => {
        pending.current.push(event)

        if (!frame.current) {
          frame.current = requestAnimationFrame(flush)
        }
      },
      () => {
        if (frame.current) {
          cancelAnimationFrame(frame.current)
        }

        flush()
        setLive(false)
      }
    )

    return () => {
      stop()

      if (frame.current) {
        cancelAnimationFrame(frame.current)
        frame.current = 0
      }
    }
  }, [runId])

  return { events, live }
}

export function RunDetail({
  run,
  runId,
  onOpenRun,
  onSuggestion,
  compact = false
}: {
  run: undefined | WorkspaceRun
  runId: string
  onOpenRun: (id: string) => void
  onSuggestion: (text: string) => void
  /** Docked above the composer: tighter padding, capped height. */
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const { events, live } = useRunEvents(runId)
  const timeline = useMemo(() => buildTimeline(events), [events])
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  const status = timeline.finished ? (timeline.success ? 'done' : 'error') : (run?.status ?? 'running')
  const active = live && !timeline.finished && ACTIVE_STATUSES.has(status)

  useEffect(() => {
    if (!timeline.finished) {
      return
    }

    void queryClient.invalidateQueries({ queryKey: runsKey })
  }, [timeline.finished, queryClient])

  useEffect(() => {
    if (active) {
      bottom.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [active, timeline.rows.length])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setActionError('')

    try {
      return await fn()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: runsKey })
    }
  }

  const rerun = async () => {
    const result = (await act(() => rerunRun(runId))) as undefined | { workspace_id?: string }

    if (result?.workspace_id) {
      onOpenRun(result.workspace_id)
    }
  }

  const tokens = timeline.tokens || (run ? (run.prompt_tokens ?? 0) + (run.completion_tokens ?? 0) : 0)

  return (
    <div className={cn('flex min-h-0 flex-col', !compact && 'flex-1')}>
      <header className={cn('shrink-0 space-y-2', compact ? 'px-3 pt-2 pb-2' : 'px-6 pt-5 pb-4')}>
        {!compact && (
          <h2 className="text-lg leading-snug font-semibold text-balance">{run?.task_brief || 'Workspace run'}</h2>
        )}
        <div
          className={cn(
            'flex flex-wrap items-center gap-x-4 gap-y-1 text-(--ui-text-tertiary)',
            compact ? 'text-xs' : 'text-sm'
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            <StatusDot tone={statusTone(status)} />
            <span className="capitalize">{active ? 'running' : status}</span>
          </span>
          {run?.model_name && <span>{run.model_name}</span>}
          {run?.duration_ms ? <span>{formatDuration(run.duration_ms)}</span> : null}
          {tokens > 0 && <span>{formatTokens(tokens)} tokens</span>}
          {run?.tool_calls ? <span>{run.tool_calls} tool calls</span> : null}
          {run?.started_at && <span>{relativeTime(run.started_at)}</span>}
          <span className="ml-auto flex gap-2">
            {active ? (
              <Button disabled={busy} onClick={() => void act(() => cancelRun(runId))} size="sm" variant="outline">
                <Codicon name="debug-stop" size="0.85rem" />
                Stop
              </Button>
            ) : (
              <Button disabled={busy} onClick={() => void rerun()} size="sm" variant="outline">
                <Codicon name="refresh" size="0.85rem" />
                Run again
              </Button>
            )}
          </span>
        </div>
        {actionError && <p className="text-sm text-destructive">{actionError}</p>}
      </header>
      <div
        className={cn(
          'min-h-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]',
          compact ? 'max-h-[min(24rem,45vh)]' : 'flex-1'
        )}
      >
        <div className={cn('w-full space-y-4', compact ? 'px-3 pb-3' : 'mx-auto max-w-4xl px-6 pb-10')}>
          {timeline.rows.length === 0 && (
            <div className="flex items-center gap-2 py-6 text-sm text-(--ui-text-tertiary)">
              {live ? <GlyphSpinner /> : null}
              {live ? 'Waiting for the first step' : 'This run recorded no steps.'}
            </div>
          )}
          {timeline.rows.map(row => (
            <TimelineRowView
              key={row.key}
              onDecide={(actionId, approve) => decideAction(runId, actionId, approve).then(() => undefined)}
              onSuggestion={onSuggestion}
              row={row}
            />
          ))}
          {active && timeline.rows.length > 0 && (
            <div className="flex items-center gap-2 text-sm text-(--ui-text-tertiary)">
              <GlyphSpinner />
              Working
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>
    </div>
  )
}
