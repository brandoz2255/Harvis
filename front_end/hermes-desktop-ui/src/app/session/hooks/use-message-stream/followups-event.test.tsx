import { act, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $followupsBySession, setSessionFollowups } from '@/store/followups'
import type { RpcEvent } from '@/types/hermes'

import { type MessageStreamHarness, renderMessageStream } from './test-harness'

const SID = 'session-1'
const OTHER_SID = 'session-2'
let stream: MessageStreamHarness

function emit(type: RpcEvent['type'], payload: RpcEvent['payload'] = {}, sessionId = SID) {
  act(() => stream.handleEvent({ payload, session_id: sessionId, type }))
}

describe('useMessageStream harvis.followups', () => {
  beforeEach(() => {
    $followupsBySession.set({})
    stream = renderMessageStream(SID)
  })

  afterEach(() => {
    cleanup()
    $followupsBySession.set({})
  })

  it('stores the cards for the session that emitted them', () => {
    emit('harvis.followups', { items: [{ prompt: 'Run the tests', title: 'Run tests' }] })

    expect($followupsBySession.get()).toEqual({ [SID]: [{ prompt: 'Run the tests', title: 'Run tests' }] })
  })

  it('files a background session cards under its own id', () => {
    emit('harvis.followups', { items: [{ prompt: 'p', title: 't' }] }, OTHER_SID)

    expect(Object.keys($followupsBySession.get())).toEqual([OTHER_SID])
  })

  it('caps at three and drops malformed rows', () => {
    emit('harvis.followups', {
      items: [{ title: 'no prompt' }, ...[1, 2, 3, 4].map(n => ({ prompt: `p${n}`, title: `t${n}` }))]
    })

    expect($followupsBySession.get()[SID]?.map(item => item.title)).toEqual(['t1', 't2', 't3'])
  })

  it('clears the cards when the payload carries none', () => {
    setSessionFollowups(SID, [{ prompt: 'p', title: 't' }])

    emit('harvis.followups', { items: [] })

    expect($followupsBySession.get()).toEqual({})
  })

  it('clears only that session cards when its next turn starts', () => {
    setSessionFollowups(SID, [{ prompt: 'p', title: 't' }])
    setSessionFollowups(OTHER_SID, [{ prompt: 'q', title: 'u' }])

    emit('message.start', {})

    expect(Object.keys($followupsBySession.get())).toEqual([OTHER_SID])
  })

  it('keeps the cards through message.complete', () => {
    emit('message.start', {})
    emit('harvis.followups', { items: [{ prompt: 'p', title: 't' }] })
    emit('message.complete', { text: 'done' })

    expect($followupsBySession.get()[SID]).toHaveLength(1)
  })

  it('still ignores unknown event types', () => {
    expect(() => emit('harvis.something-else', { items: [{ prompt: 'p', title: 't' }] })).not.toThrow()
    expect($followupsBySession.get()).toEqual({})
  })
})
