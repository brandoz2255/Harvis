import {
  cn,
  Codicon,
  host,
  Popover,
  PopoverContent,
  PopoverTrigger,
  StatusDot,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { fetchRuns, runsKey } from './api'
import { $dockedRun } from './dock'
import { relativeTime } from './format'
import { statusTone } from './run-detail'

// What each composer mode does to the next message (owui_compat workspace_bridge).
const MODES = [
  {
    id: 'auto',
    label: 'Auto',
    icon: 'sparkle',
    hint: 'Answers in chat, and starts a workspace run when a task needs one'
  },
  { id: 'chat', label: 'Chat', icon: 'comment', hint: 'Always answers in chat. Never starts a run' },
  { id: 'agent', label: 'Agent', icon: 'rocket', hint: 'Every message becomes a workspace run with tools' },
  { id: 'orchestrate', label: 'Team', icon: 'organization', hint: 'A planner splits the job and hands steps to agents' }
] as const

type Mode = (typeof MODES)[number]['id']

const modeKey = ['harvis', 'chat-mode'] as const

export function ChatModePill() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')

  const { data: mode = 'auto' } = useQuery({
    queryFn: () => host.request<{ mode: Mode }>('harvis.chat_mode.get').then(r => r.mode),
    queryKey: modeKey,
    staleTime: 60_000
  })

  const { data: runs } = useQuery({ enabled: open, queryFn: fetchRuns, queryKey: runsKey })

  const current = MODES.find(m => m.id === mode) ?? MODES[0]

  const choose = async (next: Mode) => {
    setError('')

    try {
      await host.request('harvis.chat_mode.set', { mode: next })
      queryClient.setQueryData(modeKey, next)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label={`Mode: ${current.label}`}
          className={cn(
            'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors',
            mode === 'auto'
              ? 'border-transparent text-(--ui-text-secondary) hover:bg-accent/60'
              : 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/15'
          )}
          type="button"
        >
          <Codicon name={current.icon} size="0.8rem" />
          {current.label}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-1.5" side="top">
        <p className="px-2 pt-1 pb-1.5 text-xs font-medium text-(--ui-text-tertiary)">
          How Harvis handles your next message
        </p>
        {MODES.map(m => (
          <button
            className={cn(
              'flex w-full items-start gap-2.5 rounded-md px-2 py-2 text-left hover:bg-accent/60',
              m.id === mode && 'bg-accent/50'
            )}
            key={m.id}
            onClick={() => void choose(m.id)}
            type="button"
          >
            <Codicon className="mt-0.5" name={m.icon} size="0.9rem" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{m.label}</span>
              <span className="block text-xs text-(--ui-text-tertiary)">{m.hint}</span>
            </span>
            {m.id === mode && <Codicon className="ml-auto mt-0.5" name="check" size="0.85rem" />}
          </button>
        ))}
        {error && <p className="px-2 py-1 text-xs text-destructive">{error}</p>}
        {runs && runs.length > 0 && (
          <>
            <p className="mt-1.5 border-t px-2 pt-2 pb-1 text-xs font-medium text-(--ui-text-tertiary)">
              Recent workspace runs
            </p>
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
          </>
        )}
      </PopoverContent>
    </Popover>
  )
}
