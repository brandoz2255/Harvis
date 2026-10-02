import { describe, expect, it } from 'vitest'

import { draftFor, lastSeen, modelChoices, parseLimit, patchFrom, toggleModel, usageLabel } from './people-helpers'

describe('usageLabel', () => {
  it('shows the limit when there is one', () => {
    expect(usageLabel({ daily_message_limit: 20, messages_today: 3 })).toBe('3 / 20 today')
    expect(usageLabel({ daily_message_limit: null, messages_today: 3 })).toBe('3 today')
    expect(usageLabel({ daily_message_limit: 0, messages_today: 0 })).toBe('Chat off')
  })
})

describe('parseLimit', () => {
  it('reads blank as no limit and whole numbers as a limit', () => {
    expect(parseLimit('  ')).toEqual({ ok: true, value: null })
    expect(parseLimit('0')).toEqual({ ok: true, value: 0 })
    expect(parseLimit(' 25 ')).toEqual({ ok: true, value: 25 })
  })

  it('refuses anything else', () => {
    expect(parseLimit('-1').ok).toBe(false)
    expect(parseLimit('2.5').ok).toBe(false)
    expect(parseLimit('ten').ok).toBe(false)
    expect(parseLimit('100001').ok).toBe(false)
  })
})

describe('patchFrom', () => {
  const person = { daily_message_limit: 10, allowed_models: null }

  it('sends nothing when nothing changed', () => {
    expect(patchFrom(person, draftFor(person))).toEqual({ patch: {}, error: null })
  })

  it('sends only the changed fields', () => {
    expect(patchFrom(person, { limit: '', models: null }).patch).toEqual({ daily_message_limit: null })
    expect(patchFrom(person, { limit: '10', models: ['a'] }).patch).toEqual({ allowed_models: ['a'] })
  })

  it('refuses "only these models" with none picked, and a bad number', () => {
    expect(patchFrom(person, { limit: '10', models: [] }).error).toMatch(/at least one model/)
    expect(patchFrom(person, { limit: 'x', models: null }).error).toMatch(/whole number/)
  })

  it('treats a reordered model list as a change but the same list as none', () => {
    const limited = { daily_message_limit: null, allowed_models: ['a', 'b'] }
    expect(patchFrom(limited, { limit: '', models: ['a', 'b'] }).patch).toEqual({})
    expect(patchFrom(limited, { limit: '', models: ['b', 'a'] }).patch).toEqual({ allowed_models: ['b', 'a'] })
  })
})

describe('model choices', () => {
  it('toggles a model in and out', () => {
    expect(toggleModel(['a'], 'b')).toEqual(['a', 'b'])
    expect(toggleModel(['a', 'b'], 'a')).toEqual(['b'])
  })

  it('keeps allowed models the server no longer lists, so they can be removed', () => {
    expect(modelChoices(['a', 'b'], ['c', 'a'])).toEqual(['a', 'b', 'c'])
    expect(modelChoices(['a'], null)).toEqual(['a'])
  })
})

describe('lastSeen', () => {
  const now = Date.parse('2026-10-01T12:00:00Z')

  it('says how long ago in plain words', () => {
    expect(lastSeen(null, now)).toBe('No messages this week')
    expect(lastSeen('2026-10-01T11:59:30Z', now)).toBe('Active just now')
    expect(lastSeen('2026-10-01T11:30:00Z', now)).toBe('Active 30 min ago')
    expect(lastSeen('2026-10-01T07:00:00Z', now)).toBe('Active 5 h ago')
    expect(lastSeen('2026-09-30T12:00:00Z', now)).toBe('Active 1 day ago')
  })
})
