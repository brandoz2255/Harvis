import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type CanvasStubs, installCanvasStubs } from './canvas-stub'
import { LIMITS } from './engine/stardew/art-files.js'
import { tinyFiles } from './engine/test/fixtures.js'

const HOST = 'https://harvis.example'
const PAGE = readFileSync(join(__dirname, '..', '..', 'public', 'island', 'index.html'), 'utf8')

interface Island {
  art: { custom: boolean; message: string; state: string }
  custom: { app: { paused: boolean; sim: { agents: { id: string }[] } } } | null
  sim: { agents: { id: string }[] }
}

const island = () => (window as unknown as { __island: Island }).__island

/** Load the island page's script fresh, as the sandboxed frame would, with ?host= set (or not). */
async function boot(host: string | null = HOST) {
  vi.resetModules()
  document.documentElement.innerHTML = PAGE
  history.replaceState({}, '', `/island/index.html${host ? `?host=${encodeURIComponent(host)}` : ''}`)
  // @ts-expect-error -- plain script with no exports, so no declaration file
  await import('./main.js')
}

const send = (data: unknown, origin = HOST) => window.dispatchEvent(new MessageEvent('message', { data, origin }))

// Town is the preset the island uses, so the synthetic map is named like it and sized to fit its places.
const islandFiles = () => tinyFiles('Town', 80, 92)
const agents = (...ids: string[]) => ({ agents: ids.map(id => ({ id, name: id.toUpperCase() })) })
const settle = (state: string) => vi.waitFor(() => expect(island().art.state).toBe(state))

let stubs: CanvasStubs
let listeners: [string, EventListenerOrEventListenerObject][] = []

beforeEach(() => {
  stubs = installCanvasStubs()
  listeners = []

  // Each boot() re-runs main.js in the same window; drop its listeners afterwards so tests do not hear each other's islands.
  const add = window.addEventListener.bind(window)

  vi.spyOn(window, 'addEventListener').mockImplementation(((type: string, fn: EventListenerOrEventListenerObject, opts?: unknown) => {
    listeners.push([type, fn])
    add(type, fn, opts as AddEventListenerOptions)
  }) as typeof window.addEventListener)
})

afterEach(async () => {
  send({ type: 'island:stardew-clear' }) // stops the custom frame loop between tests
  vi.restoreAllMocks()

  for (const [type, fn] of listeners) {
    window.removeEventListener(type, fn)
  }

  stubs.restore()
})

describe('island game art', () => {
  it('starts on the built-in renderer', async () => {
    await boot()

    expect(island().custom).toBeNull()
    expect(island().art.state).toBe('builtin')
    expect(document.getElementById('sc')).toBeNull()
    expect(document.body.classList.contains('byo')).toBe(false)
  })

  it('refuses game files from any origin but the host', async () => {
    await boot()

    send({ files: islandFiles(), type: 'island:stardew' }, 'https://evil.example')
    send({ files: islandFiles(), type: 'island:stardew' }, 'null')
    await new Promise(r => setTimeout(r, 20))

    expect(island().art.state).toBe('builtin')
    expect(island().custom).toBeNull()
    expect(stubs.blobUrls).toEqual([])
  })

  it('accepts no messages at all without a ?host= origin', async () => {
    await boot(null)

    send({ files: islandFiles(), type: 'island:stardew' })
    await new Promise(r => setTimeout(r, 20))

    expect(island().art.state).toBe('builtin')
    expect(island().custom).toBeNull()
  })

  it('wears the host theme, from the host only, and drops colours that are not hex', async () => {
    await boot()
    const root = document.documentElement

    send({ colors: { primary: '#123456' }, mode: 'light', type: 'island:theme' }, 'https://evil.example')
    expect(root.style.getPropertyValue('--accent')).not.toBe('#123456')

    send({ colors: { background: 'url(x)', primary: '#123456' }, mode: 'light', type: 'island:theme' })
    expect(root.style.getPropertyValue('--accent')).toBe('#123456')
    expect(root.style.getPropertyValue('--bg')).toBe('#ffffff')
    expect(root.dataset.mode).toBe('light')
  })

  it('refuses an oversized payload and stays on the built-in renderer', async () => {
    await boot()

    send({ files: { ...islandFiles(), 'Maps/huge.png': { size: LIMITS.maxFileBytes + 1, [Symbol.toStringTag]: 'Blob' } }, type: 'island:stardew' })
    await settle('error')

    expect(island().art.message).toMatch(/too large/)
    expect(island().custom).toBeNull()
    expect(document.body.classList.contains('byo')).toBe(false)
    expect(stubs.blobUrls).toEqual([])
  })

  it('falls back to the built-in renderer, with a plain message, when a required file is missing', async () => {
    await boot()

    const files = islandFiles()

    delete files['Maps/MenuTiles.png']
    send({ files, type: 'island:stardew' })
    await settle('error')

    expect(island().art.message).toBe('Missing from the folder you picked: Maps/MenuTiles.png. Run the importer again.')
    expect(island().custom).toBeNull()
    expect(document.getElementById('sc')).toBeNull()
    expect(document.body.classList.contains('byo')).toBe(false)
    expect(document.getElementById('log')?.textContent).toContain('Maps/MenuTiles.png')
  })

  it('switches to the posted game files and back to the built-in art', async () => {
    await boot()
    send({ session: agents('a', 'b'), type: 'island:session' })

    send({ files: islandFiles(), type: 'island:stardew' })
    await settle('custom')

    expect(island().custom).not.toBeNull()
    expect(island().art.custom).toBe(true)
    expect(document.getElementById('sc')).not.toBeNull()
    expect(document.body.classList.contains('byo')).toBe(true)
    expect(island().custom?.app.sim.agents.map(a => a.id)).toEqual(['a', 'b'])
    expect(stubs.blobUrls.length).toBeGreaterThan(0)

    // The session keeps flowing to whichever renderer is showing.
    send({ session: agents('a', 'b', 'c'), type: 'island:session' })
    expect(island().custom?.app.sim.agents.map(a => a.id)).toEqual(['a', 'b', 'c'])

    send({ type: 'island:stardew-clear' })

    expect(island().custom).toBeNull()
    expect(island().art.state).toBe('builtin')
    expect(document.getElementById('sc')).toBeNull()
    expect(document.body.classList.contains('byo')).toBe(false)
    expect(island().sim.agents.map(a => a.id)).toEqual(['a', 'b', 'c']) // the built-in island caught up
  })

  it('keeps pause and resume working on the custom renderer', async () => {
    await boot()
    send({ files: islandFiles(), type: 'island:stardew' })
    await settle('custom')

    send({ type: 'island:pause' })
    expect(island().custom?.app.paused).toBe(true)

    send({ type: 'island:resume' })
    expect(island().custom?.app.paused).toBe(false)
  })

  it('starts the custom renderer paused when the host had paused it', async () => {
    await boot()
    send({ type: 'island:pause' })
    send({ files: islandFiles(), type: 'island:stardew' })
    await settle('custom')

    expect(island().custom?.app.paused).toBe(true)
  })

  it('keeps working art when a later pick is unusable', async () => {
    await boot()
    send({ files: islandFiles(), type: 'island:stardew' })
    await settle('custom')

    const bad = islandFiles()

    delete bad['Maps/Town.tbin']
    send({ files: bad, type: 'island:stardew' })
    await settle('error')

    expect(island().art.custom).toBe(true)
    expect(island().custom).not.toBeNull()
    expect(document.body.classList.contains('byo')).toBe(true)
  })

  it('a clear that arrives while files are loading wins', async () => {
    await boot()
    send({ files: islandFiles(), type: 'island:stardew' })
    send({ type: 'island:stardew-clear' })
    await new Promise(r => setTimeout(r, 50))

    expect(island().art.state).toBe('builtin')
    expect(island().custom).toBeNull()
    expect(document.getElementById('sc')).toBeNull()
  })

  it('reports status and selections to the host origin only', async () => {
    const post = vi.fn()

    const original = Object.getOwnPropertyDescriptor(window, 'parent')

    Object.defineProperty(window, 'parent', { configurable: true, value: { postMessage: post } })

    try {
      await boot()
      send({ files: { ...islandFiles(), 'Maps/Town.tbin': new ArrayBuffer(8) }, type: 'island:stardew' })
      await settle('error')
      send({ files: islandFiles(), type: 'island:stardew' })
      await settle('custom')

      const states = post.mock.calls.map(c => (c[0] as { state?: string }).state)

      expect(states).toEqual(['loading', 'error', 'loading', 'custom'])
      expect(post.mock.calls.every(c => c[1] === HOST)).toBe(true)
      expect(post.mock.calls[3][0]).toEqual({ custom: true, message: '', state: 'custom', type: 'island:stardew-status' })
    } finally {
      if (original) {
        Object.defineProperty(window, 'parent', original)
      } else {
        Reflect.deleteProperty(window, 'parent')
      }
    }
  })
})
