import { Button, cn, Codicon, host, requestComposerInsert, StatusDot, useQuery, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { ACTIVE_STATUSES, fetchRuns, runsKey, type WorkspaceRun } from './api'
import { $dockedRun } from './dock'
import { RunDetail, statusTone } from './run-detail'

/**
 * Workspace runs live in the chat, not on their own page: while a run is going
 * (or one was reopened from the mode pill) it docks above the composer with its
 * live steps, Stop, and the approve / deny buttons for risky actions.
 */
export function RunDock() {
  const busy = useValue(host.state.busy)
  const docked = useValue($dockedRun)
  const [expanded, setExpanded] = useState<null | string>(null)

  const { data: runs } = useQuery({
    queryFn: fetchRuns,
    queryKey: runsKey,
    refetchInterval: query => {
      const list = query.state.data as undefined | WorkspaceRun[]

      return busy || list?.some(r => ACTIVE_STATUSES.has(r.status)) ? 4000 : 20_000
    }
  })

  const shown = (runs ?? []).filter(r => ACTIVE_STATUSES.has(r.status) || r.id === docked)

  if (shown.length === 0) {
    return null
  }

  return (
    <div className="mb-1.5 flex flex-col gap-1.5">
      {shown.map(run => {
        const open = expanded === run.id || (expanded === null && run.id === docked)

        return (
          <div className="overflow-hidden rounded-lg border bg-(--ui-surface-raised,var(--background))" key={run.id}>
            <div className="flex items-center gap-2 px-3 py-1.5 text-xs">
              <StatusDot tone={statusTone(run.status)} />
              <button
                className="min-w-0 flex-1 truncate text-left font-medium hover:underline"
                onClick={() => setExpanded(open ? '' : run.id)}
                type="button"
              >
                {run.status === 'awaiting_approval' ? 'Waiting for your approval: ' : ''}
                {run.task_brief || 'Workspace run'}
              </button>
              <Button onClick={() => setExpanded(open ? '' : run.id)} size="sm" variant="ghost">
                <Codicon name={open ? 'chevron-down' : 'chevron-up'} size="0.8rem" />
                {open ? 'Hide steps' : 'Show steps'}
              </Button>
              {run.id === docked && !ACTIVE_STATUSES.has(run.status) && (
                <Button aria-label="Close" onClick={() => $dockedRun.set(null)} size="sm" variant="ghost">
                  <Codicon name="close" size="0.8rem" />
                </Button>
              )}
            </div>
            <div className={cn('border-t', !open && 'hidden')}>
              {open && (
                <RunDetail
                  compact
                  onOpenRun={id => {
                    $dockedRun.set(id)
                    setExpanded(id)
                  }}
                  onSuggestion={text => requestComposerInsert(text)}
                  run={run}
                  runId={run.id}
                />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
