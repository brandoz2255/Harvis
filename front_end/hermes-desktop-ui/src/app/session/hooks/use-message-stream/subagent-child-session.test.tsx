import { act, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $subagentsBySession } from '@/store/subagents'
import type { RpcEvent } from '@/types/hermes'

import { renderMessageStream } from './test-harness'

const SID = 'session-1'

describe('subagent child session refresh', () => {
  const refreshSessions = vi.fn<() => Promise<void>>(async () => undefined)

  function emit(stream: ReturnType<typeof renderMessageStream>, type: RpcEvent['type'], payload: RpcEvent['payload']) {
    act(() => stream.handleEvent({ payload, session_id: SID, type }))
  }

  beforeEach(() => {
    vi.useFakeTimers()
    refreshSessions.mockClear()
    $subagentsBySession.set({})
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    $subagentsBySession.set({})
  })

  it('refreshes the sidebar when a step completes with a stored child session', () => {
    const stream = renderMessageStream(SID, { refreshSessions })

    emit(stream, 'subagent.start', { goal: 'step', subagent_id: 'a' })
    emit(stream, 'subagent.complete', {
      child_session_id: 'child-1',
      goal: 'step',
      status: 'completed',
      subagent_id: 'a'
    })

    expect(refreshSessions).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(400)
    })

    expect(refreshSessions).toHaveBeenCalledTimes(1)
    expect($subagentsBySession.get()[SID]?.[0]?.sessionId).toBe('child-1')
  })

  it('does not refresh for completions without a child session or for other subagent events', () => {
    const stream = renderMessageStream(SID, { refreshSessions })

    emit(stream, 'subagent.complete', { goal: 'step', status: 'completed', subagent_id: 'a' })
    emit(stream, 'subagent.start', { child_session_id: 'child-2', goal: 'step', subagent_id: 'b' })

    act(() => {
      vi.advanceTimersByTime(400)
    })

    expect(refreshSessions).not.toHaveBeenCalled()
  })
})
