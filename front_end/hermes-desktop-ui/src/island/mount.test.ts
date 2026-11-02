import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type CanvasStubs, installCanvasStubs } from './canvas-stub'
import { tinyFiles } from './engine/test/fixtures.js'
import { mountIsland } from './mount.js'

// Town is the preset the island uses, so the synthetic map is named like it and sized to fit its places.
const islandFiles = () => tinyFiles('Town', 80, 92)
const agents = (...ids: string[]) => ids.map(id => ({ id, name: id.toUpperCase() }))

let stubs: CanvasStubs
let roots: HTMLElement[] = []

function mount(opts: Parameters<typeof mountIsland>[1] = {}) {
  const root = document.createElement('div')
  document.body.append(root)
  roots.push(root)

  return { app: mountIsland(root, opts), root }
}

beforeEach(() => {
  stubs = installCanvasStubs()
  roots = []
})

afterEach(() => {
  for (const root of roots) {
    root.remove()
  }

  stubs.restore()
})

describe('mountIsland scoping', () => {
  it('renders inside its container only and sets no window globals', () => {
    const { root } = mount({ agents: agents('a') })

    expect(root.classList.contains('hi-root')).toBe(true)
    expect(root.querySelector('[data-el="canvas"]')).not.toBeNull()
    expect(document.querySelector('body > .hi-root')).toBe(root) // the only island root is ours
    expect((window as unknown as Record<string, unknown>).__island).toBeUndefined()
    expect((window as unknown as Record<string, unknown>).__islandHiddenAt).toBeUndefined()
    expect((window as unknown as Record<string, unknown>).__hiddenAt).toBeUndefined()
  })

  it('wears the theme on the container, never on the document', () => {
    const { root } = mount()
    const before = document.documentElement.getAttribute('style') ?? ''
    const theme = {
      colors: { background: '#112233', border: '#30363d', foreground: '#e6edf3', mutedForeground: '#7d8590', popover: '#161b22', primary: '#4a84fe', primaryForeground: '#161616' },
      mode: 'light' as const
    }

    const { app } = { app: mountIsland(root, {}) }
    app.setTheme(theme)

    expect(root.style.getPropertyValue('--bg')).toBe('#112233')
    expect(root.dataset.mode).toBe('light')
    expect(document.documentElement.getAttribute('style') ?? '').toBe(before)
  })

  it('installs no message listener: spoofed island messages change nothing', async () => {
    const { app } = mount({ agents: agents('a') })

    window.dispatchEvent(new MessageEvent('message', { data: { session: { agents: agents('evil') }, type: 'island:session' }, origin: window.location.origin }))
    window.dispatchEvent(new MessageEvent('message', { data: { files: islandFiles(), type: 'island:stardew' }, origin: window.location.origin }))
    await new Promise(r => setTimeout(r, 20))

    expect(app.sim.agents.map(a => a.id)).toEqual(['a'])
    expect(app.custom).toBeNull()
    expect(stubs.blobUrls).toEqual([])
  })

  it('replaces the residents with the session it is handed', () => {
    const { app } = mount({ agents: agents('a') })

    app.setSession(agents('b', 'c'))
    expect(app.sim.agents.map(a => a.id)).toEqual(['b', 'c'])
  })
})

describe('mountIsland custom art', () => {
  it('a clear that lands while files are loading wins', async () => {
    const { app, root } = mount()
    const pending = app.useArt(islandFiles())
    app.clearArt()
    await pending

    expect(app.custom).toBeNull()
    expect(root.querySelector('.hi-byo')).toBeNull()
  })

  it('switches to the handed files and back to the built-in art', async () => {
    const { app, root } = mount({ agents: agents('a', 'b') })

    const status = await app.useArt(islandFiles())
    expect(status).toEqual({ custom: true, message: '', state: 'custom' })
    expect(app.custom).not.toBeNull()
    expect(root.classList.contains('byo')).toBe(true)
    expect(root.querySelector('.hi-byo')).not.toBeNull()
    expect(app.custom?.app.sim.agents.map((a: { id: string }) => a.id)).toEqual(['a', 'b'])

    // The session keeps flowing to whichever renderer is showing.
    app.setSession(agents('a', 'b', 'c'))
    expect(app.custom?.app.sim.agents.map((a: { id: string }) => a.id)).toEqual(['a', 'b', 'c'])

    expect(app.clearArt()).toEqual({ custom: false, message: '', state: 'builtin' })
    expect(app.custom).toBeNull()
    expect(root.classList.contains('byo')).toBe(false)
    expect(root.querySelector('.hi-byo')).toBeNull()
    expect(app.sim.agents.map(a => a.id)).toEqual(['a', 'b', 'c']) // the built-in island caught up
  })

  it('keeps working art when a later pick is unusable', async () => {
    const { app, root } = mount()
    await app.useArt(islandFiles())

    const bad = islandFiles()
    delete bad['Maps/Town.tbin']
    const status = await app.useArt(bad)

    expect(status.state).toBe('error')
    expect(status.custom).toBe(true)
    expect(app.custom).not.toBeNull()
    expect(root.classList.contains('byo')).toBe(true)
  })

  it('keeps pause state across the art switch', async () => {
    const { app } = mount({ agents: agents('a') })
    app.pause()
    await app.useArt(islandFiles())

    expect(app.custom?.app.paused).toBe(true)
    app.resume()
    expect(app.custom?.app.paused).toBe(false)
  })
})

describe('mountIsland disposal', () => {
  it('dispose stops the loop, removes listeners and empties the container', async () => {
    const { app, root } = mount({ agents: agents('a') })
    await app.useArt(islandFiles())

    let visibilityCalls = 0
    const probe = () => visibilityCalls++
    document.addEventListener('visibilitychange', probe)

    app.dispose()
    app.dispose() // safe to repeat

    expect(root.innerHTML).toBe('')
    expect(root.classList.contains('hi-root')).toBe(false)
    expect(app.custom).toBeNull()

    // The island's own visibility listener is gone (only our probe fires).
    document.dispatchEvent(new Event('visibilitychange'))
    expect(visibilityCalls).toBe(1)
    document.removeEventListener('visibilitychange', probe)

    // Calls after dispose do nothing and do not throw.
    app.setSession(agents('z'))
    app.setLowFx(true)
    app.resume()
    expect(app.sim.agents.map(a => a.id)).toEqual(['a'])
  })

  it('an in-flight art load is discarded when the island is disposed', async () => {
    const { app, root } = mount()
    const pending = app.useArt(islandFiles())
    app.dispose()
    const status = await pending

    expect(root.querySelector('.hi-byo')).toBeNull()
    expect(app.custom).toBeNull()
    expect(status.custom).toBe(false)
  })

  it('a second mount (account switch) is independent of the disposed first', async () => {
    const first = mount({ agents: agents('alice-bot') })
    await first.app.useArt(islandFiles())

    const second = mount({ agents: agents('bob-bot') })
    first.app.dispose()

    expect(second.root.querySelector('[data-el="canvas"]')).not.toBeNull()
    expect(second.app.sim.agents.map(a => a.id)).toEqual(['bob-bot'])
    expect(second.app.custom).toBeNull() // alice's art never leaks into bob's island

    second.app.setSession(agents('bob-bot', 'bob-helper'))
    expect(second.app.sim.agents.map(a => a.id)).toEqual(['bob-bot', 'bob-helper'])
    expect(first.app.sim.agents.map(a => a.id)).toEqual(['alice-bot'])

    second.app.dispose()
  })
})
