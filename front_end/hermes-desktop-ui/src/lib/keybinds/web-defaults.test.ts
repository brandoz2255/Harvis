import { afterEach, describe, expect, it, vi } from 'vitest'

import { isWebReplacement, WEB_DEFAULTS, webSafeDefaults } from './web-defaults'

// Chords Chrome and Firefox keep for themselves (new/close/reopen tab or
// window, tab cycling). Off macOS `ctrl` folds to `mod`, so check both spellings.
const BROWSER_RESERVED = new Set([
  'mod+n',
  'mod+shift+n',
  'mod+t',
  'mod+shift+t',
  'mod+w',
  'mod+shift+w',
  'mod+tab',
  'mod+shift+tab',
  'mod+pageup',
  'mod+pagedown'
])

const folded = (combo: string) => combo.replace(/\bctrl\b/g, 'mod')

describe('web-safe keybind defaults', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('replaces new session, new tab and close tab with Alt chords', () => {
    expect(webSafeDefaults('session.new', ['mod+n'])).toEqual(['alt+n'])
    expect(webSafeDefaults('session.newTab', ['mod+t'])).toEqual(['alt+t'])
    expect(webSafeDefaults('view.closeTab', ['mod+w'])).toEqual(['alt+w'])
  })

  it('leaves chords a page can claim alone', () => {
    expect(webSafeDefaults('nav.commandPalette', ['mod+k', 'mod+p'])).toEqual(['mod+k', 'mod+p'])
  })

  it('lets the Alt replacements fire from the composer', () => {
    expect(isWebReplacement('session.new', 'alt+n')).toBe(true)
    expect(isWebReplacement('session.new', 'alt+x')).toBe(false)
  })

  it('ships no browser-reserved default in the web build', async () => {
    vi.stubGlobal('window', { ...window, hermesDesktop: { webShell: true } })
    const { KEYBIND_ACTIONS } = await import('./actions')

    const offenders = KEYBIND_ACTIONS.flatMap(action =>
      action.defaults.filter(combo => BROWSER_RESERVED.has(folded(combo))).map(combo => `${action.id}: ${combo}`)
    )

    expect(offenders).toEqual([])
    expect(KEYBIND_ACTIONS.find(action => action.id === 'session.new')?.defaults).toEqual(['alt+n'])
  })

  it('keeps the desktop chords when Electron supplies the bridge', async () => {
    const { KEYBIND_ACTIONS } = await import('./actions')

    expect(KEYBIND_ACTIONS.find(action => action.id === 'session.new')?.defaults).toEqual(['mod+n'])
  })

  it('covers every remapped id with an existing action', async () => {
    const { KEYBIND_ACTIONS } = await import('./actions')
    const ids = new Set(KEYBIND_ACTIONS.map(action => action.id))

    expect(Object.keys(WEB_DEFAULTS).filter(id => !ids.has(id))).toEqual([])
  })
})
