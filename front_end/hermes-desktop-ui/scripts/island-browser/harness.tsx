// Browser harness for the island's adversarial tests. It mounts the REAL IslandHost
// (src/mods/island-host.tsx) with the REAL in-page island (src/island/mount.js) and the
// REAL per-account art store; only the account backend (session, bots) and app chrome
// (theme, icons, busy flag) are stubbed, via the esbuild plugin in build.mjs.
//
// window.__harness is the driver API used by run.mjs. Nothing here ships.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Sim } from '@/island/engine/sim.js'
import { $session } from '@/lib/harvis-session'
import { accountArtStore } from '@/mods/island-art'
import { IslandHost } from '@/mods/island-host'

// ---- instrumentation ------------------------------------------------------
// Outstanding rAF callbacks and window listeners, so a disposed island cannot leak a loop
// or a keybind into the next account.
let rafOutstanding = 0
const rafActive = new Map<number, boolean>()
const realRaf = window.requestAnimationFrame.bind(window)
const realCaf = window.cancelAnimationFrame.bind(window)
window.requestAnimationFrame = cb => {
  rafOutstanding++
  const id = realRaf(t => {
    if (rafActive.get(id)) {
      rafOutstanding--
      rafActive.delete(id)
      cb(t)
    }
  })
  rafActive.set(id, true)
  return id
}
window.cancelAnimationFrame = id => {
  if (rafActive.get(id)) {
    rafOutstanding--
    rafActive.delete(id)
  }
  realCaf(id)
}

const windowListeners = new Map<string, number>()
const realAdd = window.addEventListener.bind(window)
const realRemove = window.removeEventListener.bind(window)
window.addEventListener = (type: string, listener: EventListenerOrEventListenerObject, opts?: unknown) => {
  windowListeners.set(type, (windowListeners.get(type) ?? 0) + 1)
  return realAdd(type, listener, opts as AddEventListenerOptions)
}
window.removeEventListener = (type: string, listener: EventListenerOrEventListenerObject, opts?: unknown) => {
  windowListeners.set(type, Math.max(0, (windowListeners.get(type) ?? 0) - 1))
  return realRemove(type, listener, opts as EventListenerOptions)
}

// Count every sim tick (both renderers tick a Sim): a paused island stops this counter.
let ticks = 0
const origTick = Sim.prototype.tick
Sim.prototype.tick = function tick(...args: unknown[]) {
  ticks++
  return origTick.apply(this, args as never)
} as typeof origTick

// ---- the app --------------------------------------------------------------
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

function Harness() {
  return createElement(
    QueryClientProvider,
    { client },
    // A fake chrome: a sidebar strip and the chat area the island fades behind. The
    // sentinel button must never pick up the island's scoped styles.
    createElement('div', { style: { display: 'flex', width: '100vw', height: '100vh' } },
      createElement('div', { id: 'chrome', style: { width: '220px', flex: 'none' } },
        createElement('button', { id: 'sentinel', type: 'button' }, 'chrome button')),
      createElement('div', { id: 'chat', style: { position: 'relative', flex: 1, overflow: 'hidden' } },
        createElement(IslandHost))))
}

createRoot(document.getElementById('root') as HTMLElement).render(createElement(StrictMode, null, createElement(Harness)))

// ---- driver API -----------------------------------------------------------
const islandGlobals = () =>
  Object.getOwnPropertyNames(window).filter(k => /^__(island|hidden)/i.test(k))

const harness = {
  signIn(id: string) {
    $session.set({ status: 'signed-in', user: { email: '', id, name: '', role: 'user' } } as never)
  },
  signOut() {
    $session.set({ status: 'signed-out', expired: false } as never)
  },
  /** Save the given art files into this account's real IndexedDB store (as a pick would). */
  async seedArt(accountId: string, files: Record<string, ArrayBuffer>) {
    await accountArtStore(accountId).save(files)
  },
  async readArt(accountId: string) {
    const files = await accountArtStore(accountId).load()
    return files ? Object.keys(files).length : 0
  },
  state() {
    const root = document.querySelector('.hi-root')
    const residents = [...document.querySelectorAll('.hi-agent')].map(el => el.textContent?.trim() ?? '')
    const perf = document.querySelector('[data-el="perf"]')?.textContent ?? ''
    return {
      artCustom: !!root?.classList.contains('byo'),
      byoCanvas: !!document.querySelector('.hi-byo'),
      exploring: !!document.querySelector('.hi-root')?.closest('.fixed'),
      globals: islandGlobals(),
      iframes: document.querySelectorAll('iframe').length,
      islandRoots: document.querySelectorAll('.hi-root').length,
      keydownListeners: windowListeners.get('keydown') ?? 0,
      messageListeners: windowListeners.get('message') ?? 0,
      mounted: !!root,
      perf,
      rafOutstanding,
      residents,
      ticks
    }
  }
}

window.__harness = harness
