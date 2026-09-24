import { describe, expect, it } from 'vitest'

import type { WorkspaceEvent } from './api'
import { buildTimeline } from './timeline'

const ev = (type: string, payload: Record<string, unknown> = {}): WorkspaceEvent => ({ type, payload })

describe('buildTimeline', () => {
  it('folds consecutive token fragments into one text row per agent', () => {
    const { rows } = buildTimeline([
      ev('token', { content: 'Hel', agent_label: 'Coder' }),
      ev('token', { content: 'lo', agent_label: 'Coder' }),
      ev('token', { content: 'Hi', agent_label: 'Review' })
    ])

    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ kind: 'text', label: 'Coder', content: 'Hello' })
    expect(rows[1]).toMatchObject({ kind: 'text', label: 'Review', content: 'Hi' })
  })

  it('pairs a tool result with its open call', () => {
    const { rows } = buildTimeline([
      ev('tool_call', { tool: 'web_search', args: { q: 'x' } }),
      ev('tool_result', { tool: 'web_search', output: 'found', success: true })
    ])

    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ kind: 'tool', tool: 'web_search', output: 'found', state: 'ok' })
  })

  it('drops streamed text once a final message arrives and marks the run done', () => {
    const timeline = buildTimeline([
      ev('token', { content: 'draft' }),
      ev('final_message', { content: 'Final answer' }),
      ev('done', { success: true, summary: 'ignored' })
    ])

    expect(timeline.rows.map(r => r.kind)).toEqual(['final'])
    expect(timeline.finished).toBe(true)
    expect(timeline.success).toBe(true)
  })

  it('resolves an approval request from its matching resolution event', () => {
    const { rows } = buildTimeline([
      ev('approval_request', { action_id: 'a1', tool: 'shell', reason: 'rm', risk: 'high' }),
      ev('approval_resolved', { action_id: 'a1', approved: false })
    ])

    expect(rows[0]).toMatchObject({ kind: 'approval', actionId: 'a1', resolved: 'denied' })
  })

  it('reports an error with its fix hint', () => {
    const timeline = buildTimeline([ev('error', { message: 'Model offline', fix_hint: 'Start Ollama' })])

    expect(timeline.success).toBe(false)
    expect(timeline.rows[0]).toMatchObject({ kind: 'error', message: 'Model offline', hint: 'Start Ollama' })
  })
})
