// @vitest-environment node

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// @ts-expect-error -- plain .mjs build script, no type declarations
import { islandBundle } from '../../scripts/bundle-island.mjs'

const PUBLIC = join(__dirname, '..', '..', 'public')
const ISLAND = join(PUBLIC, 'island')
const SOURCE = join(__dirname, '..', 'island')

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap(name => {
    const path = join(dir, name)

    return statSync(path).isDirectory() ? walk(path) : [path]
  })

describe('island', () => {
  const served = walk(ISLAND).map(path => path.slice(ISLAND.length + 1))
  const source = walk(SOURCE).map(path => path.slice(SOURCE.length + 1))

  it('serves only the page and its bundle, and ships no game file anywhere', () => {
    expect(served.sort()).toEqual(['index.html', 'island.js'])
    expect([...served, ...source].filter(f => /\.(png|xnb|tbin|wav|ogg)$/i.test(f))).toEqual([])
  })

  it('has the generic engine, the bring-your-own-art layer and its tests', () => {
    expect(source.filter(f => !f.startsWith('engine/test/')).sort()).toEqual([
      'byo.test.ts',
      'canvas-stub.ts',
      'engine/agents.js',
      'engine/ambient.js',
      'engine/appearance.js',
      'engine/events.js',
      'engine/island-life.js',
      'engine/pathfinding.js',
      'engine/render.js',
      'engine/sim.js',
      'engine/social.js',
      'engine/stardew/art-files.d.ts',
      'engine/stardew/art-files.js',
      'engine/stardew/byo.d.ts',
      'engine/stardew/byo.js',
      'engine/stardew/hud.js',
      'engine/stardew/maps/island-s.js',
      'engine/stardew/maps/town.js',
      'engine/stardew/stardew-app.js',
      'engine/stardew/stardew-map.js',
      'engine/stardew/stardew-ui.js',
      'engine/stardew/stardew-world.js',
      'engine/stardew/tbin.js',
      'engine/town-art.js',
      'engine/world.js',
      'examples/demo-session.js',
      'main.js',
      'main.test.ts',
      'mount.d.ts',
      'mount.js',
      'mount.test.ts'
    ])
  })

  it('never fetches game files: the art arrives from the host as messages', () => {
    const stardew = source.filter(f => f.startsWith('engine/stardew/') && f.endsWith('.js'))

    for (const file of stardew) {
      expect(readFileSync(join(SOURCE, file), 'utf8'), file).not.toMatch(/\bfetch\(|ASSET_ROOT|XMLHttpRequest/)
    }
  })

  it('loads one classic script, since a sandboxed frame cannot import modules without CORS', () => {
    const page = readFileSync(join(ISLAND, 'index.html'), 'utf8')

    expect(page).toContain('<script src="./island.js"></script>')
    expect(page).not.toContain('type="module"')
    expect(readFileSync(join(ISLAND, 'island.js'), 'utf8')).toBe(islandBundle())
  })

  it('the page answers pause, resume and lowfx, and only from the ?host= origin', () => {
    const html = readFileSync(join(SOURCE, 'main.js'), 'utf8')

    expect(html).toContain('params.get("host")')
    expect(html).toMatch(/e\.origin !== HOST_ORIGIN/)
    expect(html).toContain('"island:pause"')
    expect(html).toContain('"island:resume"')
    expect(html).toContain('"island:lowfx"')
    expect(html).toContain('"island:session"')

    // Every handler, game files included, sits behind the origin check, not before it.
    const gate = html.indexOf('e.origin !== HOST_ORIGIN')

    for (const type of ['island:pause', 'island:stardew', 'island:stardew-clear']) {
      expect(gate, type).toBeLessThan(html.indexOf(`e.data.type === "${type}"`))
    }
  })

  it('the renderer has a lowFx switch for the host to flip', () => {
    expect(readFileSync(join(SOURCE, 'engine', 'render.js'), 'utf8')).toContain('this.lowFx')
  })
})

describe('mod-sandbox-proxy.html', () => {
  const proxy = readFileSync(join(PUBLIC, 'mod-sandbox-proxy.html'), 'utf8')

  it('nests the mod in a script-only sandbox and never grants same-origin', () => {
    expect(existsSync(join(PUBLIC, 'mod-sandbox-proxy.html'))).toBe(true)
    expect(proxy).toContain("setAttribute('sandbox', 'allow-scripts')")
    expect(proxy).not.toContain('allow-same-origin')
  })

  it('tears the mod frame down on any load after the first, since CSP cannot stop self-navigation', () => {
    expect(proxy).toContain("frame.addEventListener('load'")
    expect(proxy).toMatch(/loads > 1/)
    expect(proxy).toContain('mod frame navigated away')
  })

  it('locks frame-src on the proxy page itself so a mod cannot navigate its frame out (teardown on load fires after the request left)', () => {
    expect(proxy).toContain("meta.httpEquiv = 'Content-Security-Policy'")
    expect(proxy).toContain("meta.content = 'frame-src ' + frameSrc")
    expect(proxy).toContain('document.head.appendChild(meta)')
    // The lock goes in before the mod frame is attached to the document.
    expect(proxy.indexOf('lockFrameSrc(csp)')).toBeLessThan(proxy.indexOf('document.body.appendChild(view)'))
    // Missing or odd frame-src falls back to none, never to "allow".
    expect(proxy).toContain(`: "'none'"`)
  })

  it('removes WebRTC from the mod window before the mod code runs, since CSP does not govern ICE/STUN', () => {
    const boot = proxy.slice(proxy.indexOf('const BOOT'), proxy.indexOf('function dropView'))

    expect(boot).toContain('RTCPeerConnection')
    expect(boot).toContain('webkitRTCPeerConnection')
    expect(boot.indexOf('RTCPeerConnection')).toBeLessThan(boot.indexOf("window.addEventListener('error'"))
  })

  it('puts the manifest CSP meta ahead of the mod html and routes by window, not origin', () => {
    expect(proxy).toContain('Content-Security-Policy')
    expect(proxy.indexOf('meta + BOOT + html')).toBeGreaterThan(-1)
    expect(proxy).toContain('e.source === parent')
    expect(proxy).toContain('e.source === view.contentWindow')
    expect(proxy).not.toMatch(/e\.origin/)
  })
})
