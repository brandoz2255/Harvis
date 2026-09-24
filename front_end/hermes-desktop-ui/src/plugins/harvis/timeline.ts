/**
 * Reduces a workspace run's raw event stream into the rows the detail view
 * renders. Pure — no React — so it can be unit-tested and re-run on every
 * appended event without surprises.
 *
 * Token events arrive one fragment at a time (tens of thousands per run); they
 * fold into a single growing `text` row per agent until any other row
 * interrupts them. A `final_message` supersedes that streamed text.
 */

import type { WorkspaceEvent } from './api'

export type TimelineRow =
  | { kind: 'agent'; key: string; label: string; model: string; state: 'done' | 'failed' | 'running'; summary: string }
  | {
      kind: 'approval'
      key: string
      actionId: string
      tool: string
      reason: string
      risk: string
      args: string
      resolved: '' | 'approved' | 'denied'
    }
  | { kind: 'error'; key: string; message: string; hint: string }
  | { kind: 'final'; key: string; content: string }
  | { kind: 'goal'; key: string; text: string }
  | { kind: 'log'; key: string; message: string }
  | { kind: 'message'; key: string; label: string; content: string }
  | { kind: 'plan'; key: string; steps: { label: string; task: string }[] }
  | { kind: 'suggestions'; key: string; items: string[] }
  | { kind: 'text'; key: string; label: string; content: string }
  | { kind: 'tool'; key: string; tool: string; args: string; output: string; state: 'failed' | 'ok' | 'running' }

export interface RunTimeline {
  rows: TimelineRow[]
  finished: boolean
  success: boolean | null
  tokens: number
}

const str = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : JSON.stringify(v, null, 2))

export function buildTimeline(events: WorkspaceEvent[]): RunTimeline {
  const rows: TimelineRow[] = []
  let finished = false
  let success: boolean | null = null
  let tokens = 0
  let hasFinal = false

  events.forEach((event, i) => {
    const p = event.payload
    const key = `${i}`
    const label = str(p.agent_label || p.label)

    switch (event.type) {
      case 'token': {
        const last = rows.at(-1)

        if (last?.kind === 'text' && last.label === label) {
          last.content += str(p.content)
        } else {
          rows.push({ kind: 'text', key, label, content: str(p.content) })
        }

        return
      }

      case 'restated_goal':
        rows.push({ kind: 'goal', key, text: str(p.restated_goal) })

        return

      case 'plan': {
        const steps = Array.isArray(p.steps) ? (p.steps as Record<string, unknown>[]) : []
        rows.push({ kind: 'plan', key, steps: steps.map(s => ({ label: str(s.label || s.role), task: str(s.task) })) })

        return
      }

      case 'agent_start':
        rows.push({ kind: 'agent', key, label, model: str(p.model), state: 'running', summary: '' })

        return

      case 'agent_end': {
        const open = [...rows].reverse().find(r => r.kind === 'agent' && r.label === label && r.state === 'running')
        const state = p.success === false ? 'failed' : 'done'

        if (open?.kind === 'agent') {
          open.state = state
          open.summary = str(p.summary)
        } else {
          rows.push({ kind: 'agent', key, label, model: str(p.model), state, summary: str(p.summary) })
        }

        if (typeof p.total_tokens === 'number') {
          tokens += p.total_tokens
        }

        return
      }

      case 'tool_call':
        rows.push({ kind: 'tool', key, tool: str(p.tool), args: str(p.args), output: '', state: 'running' })

        return

      case 'tool_result': {
        const open = [...rows].reverse().find(r => r.kind === 'tool' && r.tool === str(p.tool) && r.state === 'running')

        if (open?.kind === 'tool') {
          open.output = str(p.output)
          open.state = p.success === false ? 'failed' : 'ok'
        } else {
          rows.push({
            kind: 'tool',
            key,
            tool: str(p.tool),
            args: '',
            output: str(p.output),
            state: p.success === false ? 'failed' : 'ok'
          })
        }

        return
      }

      case 'log':
        if (str(p.message).trim()) {
          rows.push({ kind: 'log', key, message: str(p.message) })
        }

        return

      case 'agent_message':
        rows.push({ kind: 'message', key, label, content: str(p.content) })

        return

      case 'approval_request':
        rows.push({
          kind: 'approval',
          key,
          actionId: str(p.action_id),
          tool: str(p.tool),
          reason: str(p.reason),
          risk: str(p.risk),
          args: str(p.args),
          resolved: ''
        })

        return

      case 'approval_resolved': {
        const row = rows.find(r => r.kind === 'approval' && r.actionId === str(p.action_id))

        if (row?.kind === 'approval') {
          row.resolved = p.approved ? 'approved' : 'denied'
        }

        return
      }

      case 'final_message':
        hasFinal = true
        rows.push({ kind: 'final', key, content: str(p.content) })

        return

      case 'propose_next': {
        const items = Array.isArray(p.suggestions) ? p.suggestions.map(str).filter(Boolean) : []

        if (items.length) {
          rows.push({ kind: 'suggestions', key, items })
        }

        return
      }

      case 'usage':
        if (typeof p.total_tokens === 'number') {
          tokens = Math.max(tokens, p.total_tokens)
        }

        return

      case 'error':
        finished = true
        success = false
        rows.push({ kind: 'error', key, message: str(p.message) || 'The run failed.', hint: str(p.fix_hint) })

        return

      case 'cancelled':
        finished = true
        success = false
        rows.push({ kind: 'log', key, message: str(p.message) || 'Cancelled.' })

        return

      case 'done':
        finished = true
        success = p.success !== false

        if (!hasFinal && str(p.analysis_md || p.summary).trim()) {
          hasFinal = true
          rows.push({ kind: 'final', key, content: str(p.analysis_md || p.summary) })
        }

        return

      default:
        return
    }
  })

  return { rows: hasFinal ? rows.filter(r => r.kind !== 'text') : rows, finished, success, tokens }
}
