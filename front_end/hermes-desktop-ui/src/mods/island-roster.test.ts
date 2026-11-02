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
})
