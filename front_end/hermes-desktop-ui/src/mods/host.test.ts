import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import type { ModsApi } from './api'
import { canLaunch, INIT_TIMEOUT_MS, ModHost } from './host'
import type { ModRow } from './types'

const HASH = 'a'.repeat(64)
const HTML = '<html><body>hi</body></html>'

const row = (patch: Partial<ModRow> = {}): ModRow =>
  ({
    approved_at: '2026-10-26T00:00:00Z',
    approved_hash: HASH,
    created_at: '',
    hash: HASH,
    id: 1,
    manifest: {
      harvis_mod_version: '1',
      name: 'clockface',
      ui: { csp: { connectDomains: ['https://api.example.com'] }, resource: 'ui.html', slot: 'clock' },
      version: '1.0.0'
    },
    name: 'clockface',
    source: 'user',
    status: 'on',
    status_reason: null,
    tiers: ['ui'],
    version: '1.0.0',
    ...patch
  }) as ModRow

let container: HTMLElement
let api: Pick<ModsApi, 'reportError' | 'resources'> & { reportError: Mock; resources: Mock }
let host: ModHost

const frame = () => container.querySelector('iframe')

/** Deliver a bridge message as if the mod frame's window sent it. */
const fromFrame = (data: unknown, source: unknown = frame()?.contentWindow) =>
  window.dispatchEvent(new MessageEvent('message', { data, origin: 'null', source: source as MessageEventSource }))

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  api = {
    reportError: vi.fn().mockResolvedValue({}),
    resources: vi.fn().mockResolvedValue({ 'ui.html': HTML })
  }
  host = new ModHost({ api })
})

afterEach(() => {
  host.stopAll()
  container.remove()
  vi.useRealTimers()
})

describe('the launch gate', () => {
  it('only an on mod approved at exactly its current hash may launch', () => {
    expect(canLaunch(row())).toBe(true)
    expect(canLaunch(row({ status: 'draft' }))).toBe(false)
    expect(canLaunch(row({ status: 'off' }))).toBe(false)
    expect(canLaunch(row({ status: 'broken' }))).toBe(false)
    expect(canLaunch(row({ approved_hash: null }))).toBe(false)
    expect(canLaunch(row({ approved_hash: 'b'.repeat(64) }))).toBe(false)
  })

  it('a mod without a UI has nothing to launch', () => {
    const noUi = row()
    delete noUi.manifest.ui
    expect(canLaunch(noUi)).toBe(false)
  })

  it.each([
    ['draft', { status: 'draft' }],
    ['off', { status: 'off' }],
    ['broken', { status: 'broken' }],
    ['approved for different bytes', { approved_hash: 'b'.repeat(64) }]
  ] as const)('does not fetch or mount a %s mod', async (_label, patch) => {
    expect(await host.launch(row(patch as Partial<ModRow>), container)).toBe(false)
    expect(api.resources).not.toHaveBeenCalled()
    expect(frame()).toBeNull()
  })

  it('mounts an on + approved mod in a script-only sandbox, fetching the resources of its approved hash', async () => {
    expect(await host.launch(row(), container)).toBe(true)

    expect(api.resources).toHaveBeenCalledWith('clockface', HASH)

    const iframe = frame()
    expect(iframe?.getAttribute('sandbox')).toBe('allow-scripts')
    expect(iframe?.getAttribute('allow')).toBeNull()
    expect(iframe?.getAttribute('src')).toBe('/mod-sandbox-proxy.html')
    expect(host.isRunning('clockface')).toBe(true)
  })
})

describe('the bridge', () => {
  it('hands the mod html and the manifest CSP to the proxy once it is ready', async () => {
    await host.launch(row(), container)

    const post = vi.spyOn(frame()!.contentWindow!, 'postMessage')
    fromFrame({ jsonrpc: '2.0', method: 'ui/notifications/sandbox-proxy-ready' })

    expect(post).toHaveBeenCalledTimes(1)

    const sent = post.mock.calls[0][0] as { method: string; params: { csp: string; html: string } }
    expect(sent.method).toBe('ui/notifications/sandbox-resource-ready')
    expect(sent.params.html).toBe(HTML)
    expect(sent.params.csp).toContain("default-src 'none'")
    expect(sent.params.csp).toContain('connect-src https://api.example.com')
  })

  it('answers ui/initialize and then does not time out', async () => {
    vi.useFakeTimers()
    await host.launch(row(), container)

    const post = vi.spyOn(frame()!.contentWindow!, 'postMessage')
    fromFrame({ id: 7, jsonrpc: '2.0', method: 'ui/initialize', params: {} })

    expect(post.mock.calls[0][0]).toMatchObject({ id: 7, result: { protocolVersion: expect.any(String) } })

    await vi.advanceTimersByTimeAsync(INIT_TIMEOUT_MS * 2)
    expect(api.reportError).not.toHaveBeenCalled()
    expect(frame()).not.toBeNull()
  })

  it('refuses methods outside the ui/* surface', async () => {
    await host.launch(row(), container)

    const post = vi.spyOn(frame()!.contentWindow!, 'postMessage')
    fromFrame({ id: 3, jsonrpc: '2.0', method: 'fs/readFile', params: {} })

    expect(post.mock.calls[0][0]).toMatchObject({ error: { code: -32601 }, id: 3 })
  })

  it('accepts messages by window identity, not by origin', async () => {
    await host.launch(row(), container)

    // Right origin string ("null" is what a sandboxed frame reports), wrong window: ignored.
    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'spoofed' } }, window)
    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'spoofed' } }, null)
    await Promise.resolve()

    expect(api.reportError).not.toHaveBeenCalled()
    expect(frame()).not.toBeNull()

    // The mod's own window is accepted even though its origin is "null".
    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'real' } })
    await Promise.resolve()

    expect(api.reportError).toHaveBeenCalledTimes(1)
  })
})

describe('a failing mod is switched off', () => {
  it('a mod error calls POST /error with the reason and unmounts it', async () => {
    const onEvent = vi.fn()
    host = new ModHost({ api, onEvent })
    await host.launch(row(), container)

    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'boom' } })
    await vi.waitFor(() => expect(api.reportError).toHaveBeenCalledWith('clockface', 'boom'))

    expect(frame()).toBeNull()
    expect(host.isRunning('clockface')).toBe(false)
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ error: 'boom', mod: 'clockface', what: 'mod-error' }))
  })

  it('reports once even when the mod keeps erroring', async () => {
    await host.launch(row(), container)

    const win = frame()!.contentWindow
    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'one' } }, win)
    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'two' } }, win)
    await Promise.resolve()

    expect(api.reportError).toHaveBeenCalledTimes(1)
  })

  it('no ui/initialize within the timeout calls POST /error and unmounts it', async () => {
    vi.useFakeTimers()
    await host.launch(row(), container)

    await vi.advanceTimersByTimeAsync(INIT_TIMEOUT_MS - 1)
    expect(api.reportError).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    expect(api.reportError).toHaveBeenCalledWith('clockface', expect.stringContaining('ui/initialize'))
    expect(frame()).toBeNull()
  })

  it('a mod with no resource html is reported, not mounted', async () => {
    api.resources.mockResolvedValue({})

    expect(await host.launch(row(), container)).toBe(false)
    expect(api.reportError).toHaveBeenCalledWith('clockface', expect.stringContaining('ui.html'))
    expect(frame()).toBeNull()
  })

  it('a failed resource request leaves the mod alone (it is not the mod that failed)', async () => {
    api.resources.mockRejectedValue(new Error('network'))

    expect(await host.launch(row(), container)).toBe(false)
    expect(api.reportError).not.toHaveBeenCalled()
    expect(host.isRunning('clockface')).toBe(false)
  })

  it('stopping a mod removes its frame and stops listening', async () => {
    await host.launch(row(), container)
    const win = frame()!.contentWindow

    host.stop('clockface')
    expect(frame()).toBeNull()

    fromFrame({ jsonrpc: '2.0', method: 'ui/error', params: { message: 'late' } }, win)
    await Promise.resolve()
    expect(api.reportError).not.toHaveBeenCalled()
  })
})
