import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $followupsBySession,
  clearSessionFollowups,
  MAX_FOLLOWUPS,
  parseFollowups,
  setFollowupStarter,
  setSessionFollowups,
  startFollowup
} from './followups'

const card = (n: number) => ({ prompt: `prompt ${n}`, title: `title ${n}` })

describe('parseFollowups', () => {
  it('keeps well-formed rows, trimmed', () => {
    expect(parseFollowups([{ prompt: '  do it ', title: ' Do it  ' }])).toEqual([{ prompt: 'do it', title: 'Do it' }])
  })

  it('drops rows missing a title or prompt and non-objects', () => {
    expect(
      parseFollowups([
        { title: 'only title' },
        { prompt: 'only prompt' },
        { prompt: ' ', title: 'x' },
        null,
        'str',
        7,
        card(1)
      ])
    ).toEqual([card(1)])
  })

  it('caps the list at the backend maximum', () => {
    expect(parseFollowups([1, 2, 3, 4, 5].map(card))).toHaveLength(MAX_FOLLOWUPS)
  })

  it.each([undefined, null, {}, 'x', 5])('treats %s as no cards', raw => {
    expect(parseFollowups(raw)).toEqual([])
  })
})

describe('session followups store', () => {
  beforeEach(() => {
    $followupsBySession.set({})
    setFollowupStarter(null)
  })

  it('stores cards per session and clears one without touching others', () => {
    setSessionFollowups('a', [card(1)])
    setSessionFollowups('b', [card(2)])

    clearSessionFollowups('a')

    expect($followupsBySession.get()).toEqual({ b: [card(2)] })
  })

  it('keeps the reference when the same cards arrive again', () => {
    setSessionFollowups('a', [card(1)])
    const before = $followupsBySession.get()

    setSessionFollowups('a', [card(1)])

    expect($followupsBySession.get()).toBe(before)
  })

  it('removes the entry when an empty list arrives', () => {
    setSessionFollowups('a', [card(1)])

    setSessionFollowups('a', [])

    expect($followupsBySession.get()).toEqual({})
  })

  it('ignores a missing session id', () => {
    setSessionFollowups('', [card(1)])

    expect($followupsBySession.get()).toEqual({})
  })
})

describe('startFollowup', () => {
  beforeEach(() => {
    $followupsBySession.set({})
    setFollowupStarter(null)
  })

  it('starts the prompt and retires that session cards', () => {
    const starter = vi.fn()
    setFollowupStarter(starter)
    setSessionFollowups('a', [card(1), card(2)])
    setSessionFollowups('b', [card(3)])

    expect(startFollowup('a', card(1))).toBe(true)

    expect(starter).toHaveBeenCalledWith('prompt 1')
    expect($followupsBySession.get()).toEqual({ b: [card(3)] })
  })

  it('keeps the cards when nothing can start the chat', () => {
    setSessionFollowups('a', [card(1)])

    expect(startFollowup('a', card(1))).toBe(false)

    expect($followupsBySession.get()).toEqual({ a: [card(1)] })
  })

  it('does not surface a starter rejection as unhandled', async () => {
    setFollowupStarter(() => Promise.reject(new Error('boom')))

    expect(startFollowup('a', card(1))).toBe(true)
    await Promise.resolve()
  })
})
