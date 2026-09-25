import { Codicon, Popover, PopoverContent, PopoverTrigger, StatusDot, useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { fetchRuns, runsKey } from './api'
import { $dockedRun } from './dock'
import { relativeTime } from './format'
import { statusTone } from './run-detail'

/**
 * There is no Auto / Chat / Agent / Team pill any more: Harvis decides per
 * message (answer in chat, or start a workspace run when the task needs one),
 * and the message itself can ask ("use a team", "just answer") — see
 * python_back_end/plugins/hermes_ui/chat.py requested_mode.
 *
 * What the pill also did — reopening a recent workspace run into the dock —
 * lives here as a small history button that only appears once there are runs.
 */
export function RecentRunsButton() {
  const [open, setOpen] = useState(false)
  const { data: runs } = useQuery({ queryFn: fetchRuns, queryKey: runsKey, staleTime: 30_000 })

  if (!runs || runs.length === 0) {
    return null
  }

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label="Recent workspace runs"
          className="inline-flex size-7 items-center justify-center rounded-full text-(--ui-text-secondary) transition-colors hover:bg-accent/60"
          type="button"
        >
          <Codicon name="history" size="0.85rem" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-1.5" side="top">
        <p className="px-2 pt-1 pb-1 text-xs font-medium text-(--ui-text-tertiary)">Recent workspace runs</p>
        {runs.slice(0, 5).map(run => (
          <button
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent/60"
            key={run.id}
            onClick={() => {
              $dockedRun.set(run.id)
              setOpen(false)
            }}
            type="button"
          >
            <StatusDot tone={statusTone(run.status)} />
            <span className="min-w-0 flex-1 truncate">{run.task_brief || 'Workspace run'}</span>
            {run.started_at && (
              <span className="shrink-0 text-(--ui-text-tertiary)">{relativeTime(run.started_at)}</span>
            )}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  )
}
