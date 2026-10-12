import { act, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $approvalRequest, clearApprovalRequest, setApprovalRequest } from '@/store/prompts'
import { $activeSessionId } from '@/store/session'

import { type MessageStreamHarness, renderMessageStream } from './test-harness'

const SID = 'session-approval'
let stream: MessageStreamHarness

describe('approval.resolved', () => {
  beforeEach(() => {
    $activeSessionId.set(SID)
    stream = renderMessageStream(SID)
  })

  afterEach(() => {
    cleanup()
    clearApprovalRequest(SID)
  })

  it('dismisses the prompt when the backend finishes the request elsewhere or times out', () => {
    setApprovalRequest({ command: 'rm -rf x', description: 'd', requestId: 'r1', sessionId: SID })
    expect($approvalRequest.get()?.requestId).toBe('r1')

    act(() =>
      stream.handleEvent({
        payload: { approved: false, request_id: 'r1', timed_out: true },
        session_id: SID,
        type: 'approval.resolved'
      })
    )

    expect($approvalRequest.get()).toBeNull()
  })

  it('leaves a newer prompt alone when a stale request id resolves', () => {
    setApprovalRequest({ command: 'ls', description: 'd', requestId: 'r2', sessionId: SID })

    act(() =>
      stream.handleEvent({
        payload: { approved: true, request_id: 'r1', timed_out: false },
        session_id: SID,
        type: 'approval.resolved'
      })
    )

    expect($approvalRequest.get()?.requestId).toBe('r2')
  })
})
