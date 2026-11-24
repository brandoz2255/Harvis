import { describe, expect, it } from 'vitest'

import type { RosterRow } from '@/plugins/hermes-bots/types'

import { officeCounts, officeEntries, officeState } from './office-roster'
import { createOfficeLife, DOOR_X, hitTestFigures, officeLayout, type OfficeEntry, route } from './render/office.js'

const NOW = 1_800_000_000_000

function entry(key: string, state: OfficeEntry['state'], task: null | string = null): OfficeEntry {
  return { key, profile: key, display_name: key, color: null, state, idle_since: null, task }
}

describe('officeState', () => {
  it('reports what the roster can honestly say', () => {
    expect(officeState({ name: 'a', ghost: true }, true)).toBe('offline')
    expect(officeState({ name: 'a', sourceMissing: true }, true)).toBe('unknown')
    expect(officeState({ name: 'a', sourceReachable: false }, false)).toBe('unknown')
    expect(officeState({ name: 'a' }, true)).toBe('busy')
    expect(officeState({ name: 'a' }, false)).toBe('idle')
  })
})

describe('officeEntries', () => {
  const rows: RosterRow[] = [
    { name: 'coder', canonical_session: { last_active: NOW / 1000 - 10, title: 'Fix the login page' } },
    { name: 'writer', last_session: { last_active: NOW / 1000 - 4000, preview: 'hi' } },
    { name: 'ghosty', ghost: true },
    { name: 'far', connectionId: 'remote-1', sourceReachable: false }
  ]
  const list = officeEntries(rows, { activeProfile: 'default', gatewayState: 'open', meta: {}, now: NOW })

  it('keys by source-qualified identity, in roster order', () => {
    expect(list.map(e => e.key)).toEqual(['legacy::coder', 'legacy::writer', 'legacy::ghosty', 'remote-1::far'])
  })

  it('maps state, and only carries a real title while busy', () => {
    expect(list.map(e => e.state)).toEqual(['busy', 'idle', 'offline', 'unknown'])
    expect(list[0].task).toBe('Fix the login page')
    expect(list[1].task).toBeNull()
    expect(list[1].idle_since).toBe(NOW / 1000 - 4000)
    expect(list[0].idle_since).toBeNull()
  })

  it('never invents a task from a preview', () => {
    const [one] = officeEntries([{ name: 'x', last_session: { last_active: NOW / 1000 - 5, preview: 'secret text' } }], {
      gatewayState: 'open',
      meta: {},
      now: NOW
    })
    expect(one.state).toBe('busy')
    expect(one.task).toBeNull()
  })

  it('counts each state', () => {
    expect(officeCounts(list)).toEqual({ busy: 1, idle: 1, offline: 1, unknown: 1 })
  })
})

describe('office layout', () => {
  it('grows desks and lounge groups with the roster', () => {
    const small = officeLayout([entry('a', 'idle')])
    const big = officeLayout(Array.from({ length: 20 }, (_, i) => entry('b' + i, i < 13 ? 'idle' : 'busy')))
    expect(small.lounges).toHaveLength(1)
    expect(big.lounges).toHaveLength(3)
    expect(big.worldW).toBeGreaterThan(small.worldW)
    expect(big.workH).toBeGreaterThanOrEqual(small.workH)
  })
})

describe('office life', () => {
  it('places everyone where the data says on first paint, with no entrance walk', () => {
    const life = createOfficeLife()
    const list = [entry('a', 'busy'), entry('b', 'idle'), entry('c', 'offline')]
    const figs = life.update(list, officeLayout(list), 0)
    expect(figs.map(f => [f.key, f.mode])).toEqual([
      ['a', 'desk'],
      ['b', 'seat']
    ])
  })

  it('walks a bot to the lounge when it goes idle, and seats it on arrival', () => {
    const life = createOfficeLife()
    let list = [entry('a', 'busy')]
    life.update(list, officeLayout(list), 0)
    list = [entry('a', 'idle')]
    const L = officeLayout(list)
    const walking = life.update(list, L, 0.1)
    expect(walking[0].mode).toBe('walk')
    let figs = walking
    for (let t = 0.2; t < 40 && figs[0]?.mode === 'walk'; t += 0.2) figs = life.update(list, L, t)
    expect(figs[0].mode).toBe('seat')
  })

  it('walks an offline bot out the door and drops it', () => {
    const life = createOfficeLife()
    let list = [entry('a', 'busy')]
    life.update(list, officeLayout(list), 0)
    list = [entry('a', 'offline')]
    const L = officeLayout(list)
    let figs = life.update(list, L, 0.1)
    expect(figs[0].mode).toBe('walk')
    for (let t = 0.2; t < 60 && figs.length; t += 0.2) figs = life.update(list, L, t)
    expect(figs).toHaveLength(0)
  })

  it('only gives a busy bot a real bubble, and only with its real title', () => {
    const life = createOfficeLife()
    const list = [entry('a', 'busy', 'Fix the login page'), entry('b', 'busy')]
    const figs = life.update(list, officeLayout(list), 0)
    expect(figs[0].bubble).toMatchObject({ kind: 'real', text: 'Fix the login page' })
    expect(figs[1].bubble).toBeNull()
  })

  it('marks every idle line as simulated', () => {
    const life = createOfficeLife()
    const list = [entry('a', 'idle'), entry('b', 'idle'), entry('c', 'idle')]
    const L = officeLayout(list)
    const kinds = new Set<string>()
    for (let t = 0; t < 120; t += 0.25) for (const f of life.update(list, L, t)) if (f.bubble) kinds.add(f.bubble.kind)
    expect([...kinds]).toEqual(['sim'])
  })

  it('keeps walkers on the floor when the office shrinks mid-walk', () => {
    const life = createOfficeLife()
    const many = Array.from({ length: 24 }, (_, i) => entry('b' + i, i % 2 ? 'idle' : 'busy'))
    life.update(many, officeLayout(many), 0)
    const flipped = many.map(e => ({ ...e, state: e.state === 'busy' ? ('idle' as const) : ('busy' as const) }))
    life.update(flipped, officeLayout(flipped), 0.1)
    const few = flipped.slice(0, 4)
    const L = officeLayout(few)
    for (let t = 0.2; t < 30; t += 0.2) {
      for (const f of life.update(few, L, t)) {
        expect(f.x).toBeGreaterThanOrEqual(DOOR_X - 1e-6)
        expect(f.x).toBeLessThanOrEqual(L.worldW + 1e-6)
        expect(f.y).toBeLessThanOrEqual(L.worldH + 1e-6)
      }
    }
  })

  it('routes through the hallway and ends at the door', () => {
    const list = [entry('a', 'busy')]
    const L = officeLayout(list)
    const path = route({ kind: 'desk', index: 0 }, { kind: 'door' }, L)
    expect(path.at(-1)?.[0]).toBe(DOOR_X)
    expect(path.length).toBeGreaterThan(2)
  })
})

describe('hitTestFigures', () => {
  it('returns the front-most hit, else -1', () => {
    const frame = { hits: [{ index: 0, x: 10, y: 10, r: 8 }, { index: 3, x: 12, y: 10, r: 8 }] }
    expect(hitTestFigures(frame as never, 11, 10)).toBe(3)
    expect(hitTestFigures(frame as never, 100, 100)).toBe(-1)
  })
})
