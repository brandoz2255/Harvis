import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $selectedStoredSessionId, setSelectedStoredSessionId } from '@/store/session'
import { $sessionTiles, closeSessionTile } from '@/store/session-states'

import { type BtwDeps, openBtwSession, parseBtwResult } from './btw'

const RESULT = {
  message: 'what does this flag do?',
  output: 'Side question opened',
  parent_session_id: 'parent-stored',
  session_id: 'rt-btw',
  stored_session_id: 'stored-btw',
  title: 'btw: flag',
  type: 'btw'
}

function deps(overrides: Partial<BtwDeps> = {}): BtwDeps {
  return {
    refreshSessions: vi.fn(async () => undefined),
    resumeStoredSession: vi.fn(),
    submitPromptText: vi.fn(async () => true),
    updateSessionState: vi.fn() as never,
    ...overrides
  }
}

describe('parseBtwResult', () => {
  it('reads the backend shape', () => {
    expect(parseBtwResult(RESULT)).toEqual({
      message: 'what does this flag do?',
      output: 'Side question opened',
      parentSessionId: 'parent-stored',
      sessionId: 'rt-btw',
      storedSessionId: 'stored-btw',
      title: 'btw: flag'
    })
  })

  it('routes by the runtime id when no durable id comes back', () => {
    expect(parseBtwResult({ ...RESULT, stored_session_id: undefined })?.storedSessionId).toBe('rt-btw')
  })

  it.each([
    ['another result type', { ...RESULT, type: 'send' }],
    ['no session', { ...RESULT, session_id: '' }],
    ['plain exec output', { output: 'hello' }],
    ['null', null]
  ])('rejects %s', (_label, raw) => {
    expect(parseBtwResult(raw)).toBeNull()
  })
})

describe('openBtwSession', () => {
  beforeEach(() => {
    closeSessionTile('stored-btw')
  })

  it('opens a tab bound to the minted runtime and asks the question in it', async () => {
    const d = deps()
    const btw = parseBtwResult(RESULT)!

    await expect(openBtwSession(btw, d)).resolves.toBe('tile')

    const tile = $sessionTiles.get().find(t => t.storedSessionId === 'stored-btw')
    expect(tile?.runtimeId).toBe('rt-btw')
    expect(d.resumeStoredSession).not.toHaveBeenCalled()
    expect(d.submitPromptText).toHaveBeenCalledWith('what does this flag do?', {
      sessionId: 'rt-btw',
      storedSessionId: 'stored-btw'
    })
    // Listed once on open and again after the question persists a row.
    expect(d.refreshSessions).toHaveBeenCalledTimes(2)
    expect(d.updateSessionState).toHaveBeenCalledWith('rt-btw', expect.any(Function), 'stored-btw')
  })

  it('falls back to selecting the session when no tab opens, and still asks', async () => {
    const d = deps()
    // A session that is already the main thread never tiles.
    const before = $selectedStoredSessionId.get()
    setSelectedStoredSessionId('stored-btw')

    try {
      await expect(openBtwSession(parseBtwResult(RESULT)!, d)).resolves.toBe('selected')
    } finally {
      setSelectedStoredSessionId(before)
    }

    expect(d.resumeStoredSession).toHaveBeenCalledWith('stored-btw')
    expect(d.submitPromptText).toHaveBeenCalledTimes(1)
  })

  it('still asks when the fallback select fails too', async () => {
    const d = deps({
      resumeStoredSession: vi.fn(async () => {
        throw new Error('no such session')
      })
    })

    const before = $selectedStoredSessionId.get()
    setSelectedStoredSessionId('stored-btw')

    try {
      await expect(openBtwSession(parseBtwResult(RESULT)!, d)).resolves.toBe('selected')
    } finally {
      setSelectedStoredSessionId(before)
    }

    expect(d.submitPromptText).toHaveBeenCalledTimes(1)
  })

  it('opens the tab without sending when the backend returned no message', async () => {
    const d = deps()

    await openBtwSession(parseBtwResult({ ...RESULT, message: '' })!, d)

    expect(d.submitPromptText).not.toHaveBeenCalled()
    expect($sessionTiles.get().some(t => t.storedSessionId === 'stored-btw')).toBe(true)
  })
})
