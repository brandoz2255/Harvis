import { afterEach, describe, expect, it, vi } from 'vitest'

import { McpOAuthNeedsClientId } from './mcp-dashboard-oauth'
import { connectMcpWithPopup, prepareOAuthWindow } from './mcp-oauth-popup'

const flow = (over: Record<string, unknown> = {}) => ({
  authorization_url: 'https://idp.example/authorize',
  error: null,
  flow_id: 'f1',
  server_name: 'srv',
  status: 'authorization_required',
  ...over
})

function installDesktop(webShell: boolean) {
  const openExternal = vi.fn().mockResolvedValue(undefined)
  ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { openExternal, webShell }

  return openExternal
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('prepareOAuthWindow', () => {
  it('opens a blank popup synchronously in a browser tab and points it at the URL later', async () => {
    const openExternal = installDesktop(true)
    const popup = { closed: false, close: vi.fn(), location: { href: '' }, opener: {} as unknown }
    const open = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)

    const win = prepareOAuthWindow()
    expect(open).toHaveBeenCalledWith('about:blank', 'harvis-mcp-oauth', expect.stringContaining('popup'))
    expect(popup.opener).toBeNull()

    await win.open('https://idp.example/authorize')
    expect(popup.location.href).toBe('https://idp.example/authorize')
    expect(openExternal).not.toHaveBeenCalled()

    win.close()
    expect(popup.close).toHaveBeenCalled()
  })

  it('falls back to the system browser when the popup is blocked', async () => {
    const openExternal = installDesktop(true)
    vi.spyOn(window, 'open').mockReturnValue(null)

    await prepareOAuthWindow().open('https://idp.example/authorize')
    expect(openExternal).toHaveBeenCalledWith('https://idp.example/authorize')
  })

  it('never opens a popup in the desktop app', async () => {
    const openExternal = installDesktop(false)
    const open = vi.spyOn(window, 'open')

    await prepareOAuthWindow().open('https://idp.example/authorize')
    expect(open).not.toHaveBeenCalled()
    expect(openExternal).toHaveBeenCalledOnce()
  })
})

describe('connectMcpWithPopup', () => {
  it('closes the popup after a successful flow', async () => {
    installDesktop(true)
    const popup = { closed: false, close: vi.fn(), location: { href: '' }, opener: null }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)

    const result = await connectMcpWithPopup({
      serverName: 'srv',
      sleep: async () => {},
      start: async () => flow(),
      status: async () => flow({ status: 'approved', tools: [{ description: '', name: 't' }] })
    } as never)

    expect(result.status).toBe('approved')
    expect(popup.location.href).toBe('https://idp.example/authorize')
    expect(popup.close).toHaveBeenCalled()
  })

  it('closes the popup and raises a typed error when a client id is needed', async () => {
    installDesktop(true)
    const popup = { closed: false, close: vi.fn(), location: { href: '' }, opener: null }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)

    await expect(
      connectMcpWithPopup({
        serverName: 'srv',
        start: async () =>
          flow({ authorization_url: null, error: 'no registration', needs_client_id: true, status: 'error' }),
        status: async () => flow()
      } as never)
    ).rejects.toBeInstanceOf(McpOAuthNeedsClientId)

    expect(popup.close).toHaveBeenCalled()
  })
})
