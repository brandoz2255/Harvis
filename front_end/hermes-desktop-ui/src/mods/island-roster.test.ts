import { describe, expect, it } from 'vitest'
import { IslandRoster } from './island-roster'

describe('island roster identity', () => {
  it('keeps same-named and unsafe profile identities distinct and resolves exact rows', () => {
    const roster = new IslandRoster()
    const a = { name: 'a/b', connectionId: 'one' }
    const b = { name: 'a_b', connectionId: 'two' }
    const rows = roster.update([a, b])
    expect(rows).toHaveLength(2)
    expect(rows[0].id).not.toBe(rows[1].id)
    expect(roster.resolve(rows[0].id)).toBe(a)
    expect(roster.resolve(rows[1].id)).toBe(b)
    roster.update([b])
    expect(roster.resolve(rows[0].id)).toBeUndefined()
  })

  it('maps each row to away, busy or idle', () => {
    const now = 1_000_000_000
    const roster = new IslandRoster()
    const ids = roster.update([
      { name: 'gone', sourceReachable: false },
      { name: 'ghost', ghost: true },
      { name: 'worker', last_session: { last_active: now / 1000 - 30 } },
      { name: 'resting' }
    ] as never[]).map(row => row.id)
    const p = roster.presence(now)
    expect(p[ids[0]]).toBe('away')
    expect(p[ids[1]]).toBe('away')
    expect(p[ids[2]]).toBe('busy')
    expect(p[ids[3]]).toBe('idle')
    expect(Object.keys(p)).toHaveLength(4)
  })
})
