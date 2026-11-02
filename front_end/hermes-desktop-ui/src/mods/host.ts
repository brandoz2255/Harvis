// Host runtime for mod UIs: mounts an approved mod into the double-iframe
// sandbox, speaks the MCP Apps `ui/*` JSON-RPC bridge, and switches a mod off
// (server side, as broken) when it errors or never starts.
//
//   host page  ->  <iframe sandbox="allow-scripts" src=/mod-sandbox-proxy.html>
//                    (opaque origin; mounts the mod HTML in an inner iframe
//                     under a CSP <meta> built from the approved manifest)
//
// Messages are accepted by WINDOW identity (`event.source`), never by origin:
// a sandboxed frame has no allow-same-origin, so its origin is the string "null".
import type { ModsApi } from './api'
import { auditEntry, buildCsp } from './csp'
import type { ModRow } from './types'

export const INIT_TIMEOUT_MS = 5000
export const MOD_PROXY_URL = '/mod-sandbox-proxy.html'
const PROTOCOL_VERSION = '2026-01-26'
const MAX_REASON = 200

export type ModHostEvent =
  | { at: string; csp: string; hash: string; mod: string; what: 'audit' }
  | { at: string; content?: unknown; mod: string; what: 'mod-context' }
  | { at: string; error: string; mod: string; what: 'mod-error' }
  | { at: string; mod: string; text?: unknown; what: 'mod-message' }
  | { at: string; mod: string; what: 'mod-started' | 'mod-stopped' }

export interface ModHostOptions {
  api: Pick<ModsApi, 'reportError' | 'resources'>
  initTimeoutMs?: number
  onEvent?: (event: ModHostEvent) => void
  proxyUrl?: string
  theme?: () => 'dark' | 'light'
}

interface Running {
  cleanup: (() => void)[]
  crashed: boolean
  hash: string
  iframe: HTMLIFrameElement | null
  initialized: boolean
  name: string
  stopped: boolean
}

/** The gate: a mod mounts only when it is on AND approved at exactly the bytes it holds now. */
export function canLaunch(row: ModRow): boolean {
  return row.status === 'on' && Boolean(row.approved_hash) && row.approved_hash === row.hash && Boolean(row.manifest?.ui)
}

const now = () => new Date().toISOString()

export class ModHost {
  private readonly running = new Map<string, Running>()

  constructor(private readonly opts: ModHostOptions) {}

  isRunning(name: string): boolean {
    return this.running.has(name)
  }

  /** Mount the mod's UI into `container`. Resolves true once the sandbox frame is mounted. */
  async launch(row: ModRow, container: HTMLElement, { toolInput = {} }: { toolInput?: Record<string, unknown> } = {}) {
    if (!canLaunch(row)) {
      return false
    }

    this.stop(row.name)

    const ui = row.manifest.ui!
    const state: Running = { cleanup: [], crashed: false, hash: row.hash, iframe: null, initialized: false, name: row.name, stopped: false }
    this.running.set(row.name, state)

    let html: unknown

    try {
      html = (await this.opts.api.resources(row.name, row.hash))[ui.resource]
    } catch {
      // A failed request says nothing about the mod itself: leave it on, just don't mount it now.
      this.release(state)

      return false
    }

    if (state.stopped) {
      return false
    }

    if (typeof html !== 'string' || !html) {
      void this.crash(state, `resource ${ui.resource} is missing`)

      return false
    }

    const csp = buildCsp(ui.csp)
    this.opts.onEvent?.({ ...auditEntry(row.name, row.hash, csp), what: 'audit' })

    const iframe = document.createElement('iframe')
    iframe.setAttribute('sandbox', 'allow-scripts') // never allow-same-origin: the frame must stay opaque
    iframe.title = ui.title || row.name
    iframe.style.cssText = 'border:0;width:100%;height:100%;background:transparent;color-scheme:normal'
    iframe.src = this.opts.proxyUrl ?? MOD_PROXY_URL
    state.iframe = iframe

    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframe.contentWindow) {
        return
      }

      const data = event.data as { jsonrpc?: string } | null

      if (!data || data.jsonrpc !== '2.0') {
        return
      }

      this.onBridge(state, row, csp, html as string, data as BridgeMessage, toolInput)
    }

    window.addEventListener('message', onMessage)
    state.cleanup.push(() => window.removeEventListener('message', onMessage))

    // Dead on arrival: no ui/initialize in time switches the mod off.
    const timeoutMs = this.opts.initTimeoutMs ?? INIT_TIMEOUT_MS
    const timer = setTimeout(() => {
      if (!state.initialized) {
        void this.crash(state, `no ui/initialize within ${timeoutMs}ms`)
      }
    }, timeoutMs)
    state.cleanup.push(() => clearTimeout(timer))

    container.replaceChildren(iframe)

    return true
  }

  private onBridge(state: Running, row: ModRow, csp: string, html: string, d: BridgeMessage, toolInput: Record<string, unknown>) {
    const post = (message: unknown) => state.iframe?.contentWindow?.postMessage(message, '*')
    const reply = (result: unknown) => d.id !== undefined && post({ id: d.id, jsonrpc: '2.0', result })

    switch (d.method) {
      case 'ui/notifications/sandbox-proxy-ready':
        post({ jsonrpc: '2.0', method: 'ui/notifications/sandbox-resource-ready', params: { csp, html } })

        return

      case 'ui/initialize':
        state.initialized = true
        reply({
          hostCapabilities: { displayMode: {}, message: {}, updateModelContext: {} },
          hostContext: {
            displayMode: 'inline',
            theme: this.opts.theme?.() ?? 'dark',
            userConfig: row.manifest.user_config ?? {}
          },
          hostInfo: { name: 'harvis', version: '0.1' },
          protocolVersion: PROTOCOL_VERSION
        })
        post({ jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: { arguments: toolInput } })
        this.opts.onEvent?.({ at: now(), mod: state.name, what: 'mod-started' })

        return

      case 'ui/message': // the mod wants to say something in chat: surfaced as an event, never written into the chat
        this.opts.onEvent?.({ at: now(), mod: state.name, text: d.params?.text, what: 'mod-message' })

        return

      case 'ui/update-model-context':
        this.opts.onEvent?.({ at: now(), content: d.params?.content, mod: state.name, what: 'mod-context' })

        return

      case 'ui/request-display-mode':
        reply({ mode: 'inline' })

        return

      case 'ui/error':
        void this.crash(state, String(d.params?.message ?? 'mod error'))

        return

      default:
        if (d.method?.startsWith('ui/notifications/sandbox-')) {
          return // host-internal
        }

        if (d.id !== undefined) {
          post({ error: { code: -32601, message: 'method not allowed' }, id: d.id, jsonrpc: '2.0' })
        }
    }
  }

  /** Unmount at once, then tell the server the mod is broken (so it stays off on reload). */
  private async crash(state: Running, why: string) {
    if (state.crashed) {
      return
    }

    state.crashed = true
    this.stop(state.name)

    const reason = why.slice(0, MAX_REASON)

    try {
      await this.opts.api.reportError(state.name, reason)
    } catch {
      // The mod is already unmounted; a failed report only means it may try again next load.
    }

    this.opts.onEvent?.({ at: now(), error: reason, mod: state.name, what: 'mod-error' })
  }

  private release(state: Running) {
    state.stopped = true
    state.cleanup.forEach(fn => fn())
    state.cleanup = []

    if (this.running.get(state.name) === state) {
      this.running.delete(state.name)
    }
  }

  stop(name: string) {
    const state = this.running.get(name)

    if (!state) {
      return
    }

    try {
      state.iframe?.contentWindow?.postMessage({ jsonrpc: '2.0', method: 'ui/resource-teardown', params: {} }, '*')
    } catch {
      // frame already gone
    }

    state.iframe?.remove()
    this.release(state)
    this.opts.onEvent?.({ at: now(), mod: name, what: 'mod-stopped' })
  }

  stopAll() {
    for (const name of [...this.running.keys()]) {
      this.stop(name)
    }
  }
}

interface BridgeMessage {
  id?: number | string
  method?: string
  params?: { content?: unknown; message?: unknown; text?: unknown }
}
