import { describe, expect, it, vi } from 'vitest'

import type { SubagentProgress } from '@/store/subagents'

import {
  type IslandAgent,
  IslandBridge,
  islandAgents,
  islandBots,
  sessionForIslandAgent
} from './island-bridge'

const sub = (patch: Partial<SubagentProgress>): SubagentProgress => ({
  filesRead: [],
  filesWritten: [],
  goal: 'dig through the logs',
  id: 'sa-1',
  parentId: null,
  startedAt: 0,
  status: 'running',
  stream: [],
  taskCount: 1,
  taskIndex: 0,
  updatedAt: 0,
  ...patch
})

const setup = () => {
  const calls: [string, unknown][] = []
  const app = {
    pause: vi.fn(() => calls.push(['pause', undefined])),
    resume: vi.fn(() => calls.push(['resume', undefined])),
    setLowFx: vi.fn((on: boolean) => calls.push(['lowfx', on])),
    setSession: vi.fn((agents: IslandAgent[]) => calls.push(['session', agents])),
    setTheme: vi.fn((theme: unknown) => calls.push(['theme', theme]))
  }
  const bridge = new IslandBridge(app)

  return { app, bridge, calls }
}

describe('islandAgents', () => {
  it('is the assistant plus the session subagents, with engine-safe ids', () => {
    const agents = islandAgents([sub({}), sub({ goal: '', id: 'bad id/with spaces' }), sub({ id: 'sa-1' })])

    expect(agents.map(a => a.id)).toEqual(['harvis', 'sa-1', 'bad_id_with_spaces'])
    expect(agents.every(a => /^[A-Za-z0-9_.:-]{1,64}$/.test(a.id))).toBe(true)
    expect(agents[1].name).toBe('dig through the logs')
  })

  it('maps a selected island agent back to its own session', () => {
    const subs = [sub({ id: 'sa-1', sessionId: 'stored-9' }), sub({ id: 'sa 2' })]

    expect(sessionForIslandAgent('sa-1', subs)).toBe('stored-9')
    expect(sessionForIslandAgent('sa_2', subs)).toBeUndefined()
    expect(sessionForIslandAgent('harvis', subs)).toBeUndefined()
  })
})

describe('islandBots', () => {
  it('is the assistant plus the account bots, engine-safe and capped', () => {
    const bots = Array.from({ length: 20 }, (_, i) => ({ id: `bot ${i}`, model: 'm', name: `Bot ${i}` }))
    const agents = islandBots([{ id: 'b-1', model: 'llama3', name: 'Researcher' }, ...bots])

    expect(agents[0]).toEqual({ id: 'harvis', name: 'Harvis', personality: 'Friendly, talkative assistant' })
    expect(agents[1]).toEqual({ id: 'b-1', model: 'llama3', name: 'Researcher' })
    expect(agents.length).toBe(16)
    expect(agents.every(a => /^[A-Za-z0-9_.:-]{1,64}$/.test(a.id))).toBe(true)
  })
})

describe('session (private, delivered by direct call)', () => {
  it('passes the account bots straight to the mounted island', () => {
    const { app, bridge } = setup()
    bridge.setSession([{ id: 'private-bot', name: 'Private' }])

    expect(app.setSession).toHaveBeenCalledWith([{ id: 'private-bot', name: 'Private' }])
  })

  it('does not rebuild the island for an unchanged roster, but does for a real change', () => {
    const { app, bridge } = setup()
    const bots = [{ id: 'resident-1', name: 'One' }, { id: 'resident-2', model: 'm', name: 'Two' }]

    bridge.setSession(bots)
    bridge.setSession(bots.map(bot => ({ ...bot })))
    expect(app.setSession).toHaveBeenCalledTimes(1)

    bridge.setSession([bots[0], { ...bots[1], name: 'Renamed' }])
    bridge.setSession([bots[0]])
    bridge.setSession([])
    expect(app.setSession).toHaveBeenCalledTimes(4)
  })

  it('a new bridge for a fresh mount receives the same roster again', () => {
    const first = setup()
    const second = setup()
    const bots = [{ id: 'resident-1', name: 'One' }]

    first.bridge.setSession(bots)
    second.bridge.setSession(bots)

    expect(first.app.setSession).toHaveBeenCalledTimes(1)
    expect(second.app.setSession).toHaveBeenCalledTimes(1)
  })
})

describe('run lifecycle', () => {
  it('a run starting turns lowfx on, a run ending turns it off, and repeats are not re-sent', () => {
    const { bridge, calls } = setup()

    bridge.setLowFx(false)
    expect(calls).toEqual([])

    bridge.setLowFx(true)
    bridge.setLowFx(true)
    bridge.setLowFx(false)

    expect(calls).toEqual([
      ['lowfx', true],
      ['lowfx', false]
    ])
  })
})

describe('visibility', () => {
  it('pauses when hidden and resumes when visible again', () => {
    const { bridge, calls } = setup()

    bridge.setReason('hidden', true)
    bridge.setReason('hidden', false)

    expect(calls.map(([name]) => name)).toEqual(['pause', 'resume'])
  })

  it('stays paused while any reason holds', () => {
    const { bridge, calls } = setup()

    bridge.setReason('hidden', true)
    bridge.setReason('offscreen', true) // already paused: no second pause
    bridge.setReason('hidden', false) // still off-screen: no resume yet
    expect(calls.map(([name]) => name)).toEqual(['pause'])

    bridge.setReason('offscreen', false)
    expect(calls.map(([name]) => name)).toEqual(['pause', 'resume'])
  })

  it('goes quiet on dispose: nothing is callable afterwards', () => {
    const { app, bridge } = setup()

    bridge.dispose()
    bridge.setLowFx(true)
    bridge.setReason('hidden', true)
    bridge.setSession([{ id: 'harvis', name: 'Harvis' }])
    bridge.setTheme({ colors: {} as never, mode: 'dark' })

    expect(app.pause).not.toHaveBeenCalled()
    expect(app.setLowFx).not.toHaveBeenCalled()
    expect(app.setSession).not.toHaveBeenCalled()
    expect(app.setTheme).not.toHaveBeenCalled()
  })
})

describe('theme', () => {
  const theme = {
    colors: { background: '#0d1117', border: '#30363d', foreground: '#e6edf3', mutedForeground: '#7d8590', popover: '#161b22', primary: '#4a84fe', primaryForeground: '#161616' },
    mode: 'dark' as const
  }

  it('sends the app theme once per change', () => {
    const { app, bridge } = setup()
    bridge.setTheme(theme)
    bridge.setTheme({ ...theme, colors: { ...theme.colors } })
    expect(app.setTheme).toHaveBeenCalledTimes(1)
    expect(app.setTheme).toHaveBeenCalledWith(theme)

    bridge.setTheme({ ...theme, mode: 'light' })
    expect(app.setTheme).toHaveBeenCalledTimes(2)
  })
})
