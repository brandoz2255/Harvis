// Installs a browser `window.hermesDesktop` so the Hermes renderer can run as a
// plain SPA served by Harvis' nginx instead of inside Electron.
//
// Import this FIRST in `src/main.tsx`: several modules read `hermesDesktop` at
// module-evaluation time, so the object has to exist before any of the app tree
// is imported, not merely before it renders.
//
// Nothing under `src/app/` is touched. That is deliberate — an unmodified
// upstream tree is what keeps the next re-sync from Nous a readable diff. When a
// surface misbehaves here, fix the stub, not the surface.

import { api, gatewayWsUrl, localStore, notify, openExternal, readClipboard, writeClipboard } from './api'
import { noopListener, stubs } from './stubs'
import { sandboxTerminal } from './terminal'
import { installZoom, zoom } from './zoom'

const projectDir = localStore('hermes.web.defaultProjectDir')

export function installDesktopShim(): void {
  if (typeof window === 'undefined') return
  // An Electron build already provides the real bridge; never shadow it.
  if ((window as any).hermesDesktop) return

  const shim = {
    ...stubs,
    // Read by lib/keybinds/web-defaults: this renderer runs in a browser tab.
    webShell: true,

    // ── Real implementations ─────────────────────────────────────────────
    api,
    notify,
    openExternal,
    readClipboard,
    writeClipboard,
    getGatewayWsUrl: async () => ({ ok: true, wsUrl: gatewayWsUrl() }),
    // The chat's sandbox container (right sidebar ▸ Terminal); see ./terminal.
    terminal: sandboxTerminal,
    zoom,

    settings: {
      getDefaultProjectDir: async () => {
        const dir = projectDir.read<string | null>(null)
        return { defaultLabel: 'Workspace', dir, resolvedCwd: dir ?? '' }
      },
      // No directory picker exists on the web; report a cancelled dialog rather
      // than pretending the user chose something.
      pickDefaultProjectDir: async () => ({ canceled: true, dir: null }),
      setDefaultProjectDir: async (dir: null | string) => {
        projectDir.write(dir)
        return { dir }
      }
    },

    themes: {
      // The VS Code Marketplace sends no CORS headers, so a browser cannot read
      // it directly. Empty results render as "nothing found" instead of an error.
      fetchMarketplace: async () => ({ themes: [] }),
      searchMarketplace: async () => []
    }
  }

  ;(window as any).hermesDesktop = shim
  installZoom()
}

// Install on import. A bare call in main.tsx would NOT work: ES imports are
// hoisted and fully evaluated before any top-level statement runs, so the only
// way to beat `./store/active-work` to the bridge is to be an earlier import.
installDesktopShim()

export { noopListener }
