import { Badge, Button, cn, Codicon, GlyphSpinner, StatusDot, Streamdown } from '@hermes/plugin-sdk'
import { useState } from 'react'

import type { TimelineRow } from './timeline'

function Prose({ className, text }: { className?: string; text: string }) {
  return (
    <div className={cn('harvis-prose max-w-full text-sm leading-relaxed wrap-anywhere', className)}>
      <Streamdown controls={false} mode="static" parseIncompleteMarkdown={false}>
        {text}
      </Streamdown>
    </div>
  )
}

function Mono({ children }: { children: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md bg-(--ui-bg-quinary) px-3 py-2 font-mono text-xs leading-5 whitespace-pre-wrap text-(--ui-text-secondary)">
      {children}
    </pre>
  )
}

function ToolRow({ row }: { row: Extract<TimelineRow, { kind: 'tool' }> }) {
  const [open, setOpen] = useState(false)
  const hasBody = Boolean(row.args || row.output)

  return (
    <div className="text-sm">
      <button
        className="row-hover flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--ui-text-secondary) hover:text-foreground"
        disabled={!hasBody}
        onClick={() => setOpen(v => !v)}
        type="button"
      >
        {row.state === 'running' ? (
          <GlyphSpinner className="size-3.5" />
        ) : (
          <Codicon name={row.state === 'failed' ? 'error' : 'tools'} size="0.85rem" />
        )}
        <span className="font-mono text-[0.8125rem]">{row.tool}</span>
        {row.state === 'failed' && <Badge variant="destructive">failed</Badge>}
        {hasBody && <Codicon className="ml-auto" name={open ? 'chevron-down' : 'chevron-right'} size="0.75rem" />}
      </button>
      {open && (
        <div className="space-y-2 px-2 pb-2 pl-8">
          {row.args && <Mono>{row.args}</Mono>}
          {row.output && <Mono>{row.output.length > 20_000 ? `${row.output.slice(0, 20_000)}\n…` : row.output}</Mono>}
        </div>
      )}
    </div>
  )
}

function ApprovalRow({
  row,
  onDecide
}: {
  row: Extract<TimelineRow, { kind: 'approval' }>
  onDecide: (actionId: string, approve: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [local, setLocal] = useState<'' | 'approved' | 'denied'>('')
  const resolved = row.resolved || local

  const decide = async (approve: boolean) => {
    setBusy(true)

    try {
      await onDecide(row.actionId, approve)
      setLocal(approve ? 'approved' : 'denied')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 rounded-lg bg-(--ui-bg-quaternary) px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Codicon name="shield" size="0.9rem" />
        <span>Needs your approval: {row.tool}</span>
        {row.risk && <Badge variant="outline">{row.risk}</Badge>}
      </div>
      {row.reason && <p className="text-sm text-(--ui-text-secondary)">{row.reason}</p>}
      {row.args && <Mono>{row.args}</Mono>}
      {resolved ? (
        <p className="text-sm text-(--ui-text-tertiary)">{resolved === 'approved' ? 'Approved.' : 'Denied.'}</p>
      ) : (
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void decide(true)} size="sm">
            Approve
          </Button>
          <Button disabled={busy} onClick={() => void decide(false)} size="sm" variant="outline">
            Deny
          </Button>
        </div>
      )}
    </div>
  )
}

export function TimelineRowView({
  row,
  onDecide,
  onSuggestion
}: {
  row: TimelineRow
  onDecide: (actionId: string, approve: boolean) => Promise<void>
  onSuggestion: (text: string) => void
}) {
  switch (row.kind) {
    case 'goal':
      return (
        <p className="text-sm text-(--ui-text-secondary)">
          <span className="text-(--ui-text-tertiary)">Goal · </span>
          {row.text}
        </p>
      )

    case 'plan':
      return (
        <div className="space-y-1.5">
          <div className="text-xs font-medium tracking-wide text-(--ui-text-tertiary) uppercase">Plan</div>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {row.steps.map((step, i) => (
              <li key={i}>
                {step.label && <span className="font-medium">{step.label}: </span>}
                <span className="text-(--ui-text-secondary)">{step.task}</span>
              </li>
            ))}
          </ol>
        </div>
      )

    case 'agent':
      return (
        <div className="flex items-start gap-2 text-sm">
          <span className="mt-1.5">
            <StatusDot tone={row.state === 'running' ? 'warn' : row.state === 'failed' ? 'bad' : 'good'} />
          </span>
          <div className="min-w-0">
            <span className="font-medium">{row.label || 'Agent'}</span>
            {row.model && <span className="ml-2 text-xs text-(--ui-text-tertiary)">{row.model}</span>}
            {row.summary && <p className="mt-0.5 line-clamp-3 text-(--ui-text-secondary)">{row.summary}</p>}
          </div>
        </div>
      )

    case 'tool':
      return <ToolRow row={row} />

    case 'log':
      return <p className="font-mono text-xs leading-5 text-(--ui-text-tertiary)">{row.message}</p>

    case 'message':
      return (
        <div className="space-y-1">
          <div className="text-xs font-medium text-(--ui-text-tertiary)">{row.label}</div>
          <Prose text={row.content} />
        </div>
      )

    case 'text':
      return (
        <div className="space-y-1">
          {row.label && <div className="text-xs font-medium text-(--ui-text-tertiary)">{row.label}</div>}
          <Prose text={row.content} />
        </div>
      )

    case 'approval':
      return <ApprovalRow onDecide={onDecide} row={row} />

    case 'final':
      return (
        <div className="space-y-2 border-t border-(--ui-stroke-tertiary) pt-4">
          <div className="text-xs font-medium tracking-wide text-(--ui-text-tertiary) uppercase">Result</div>
          <Prose className="text-[0.9375rem]" text={row.content} />
        </div>
      )

    case 'suggestions':
      return (
        <div className="space-y-1.5">
          <div className="text-xs font-medium tracking-wide text-(--ui-text-tertiary) uppercase">Next</div>
          <div className="flex flex-wrap gap-2">
            {row.items.map(item => (
              <Button key={item} onClick={() => onSuggestion(item)} size="sm" variant="secondary">
                {item}
              </Button>
            ))}
          </div>
        </div>
      )

    case 'error':
      return (
        <div className="space-y-1 rounded-lg bg-destructive/10 px-4 py-3 text-sm">
          <div className="font-medium text-destructive">{row.message}</div>
          {row.hint && <p className="text-(--ui-text-secondary)">{row.hint}</p>}
        </div>
      )
  }
}
