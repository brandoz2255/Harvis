import { beforeEach, describe, expect, it, vi } from 'vitest'

const hermes = vi.hoisted(() => ({
  addMcpServer: vi.fn().mockResolvedValue({}),
  authMcpServer: vi.fn(),
  cancelMcpOAuthFlow: vi.fn(),
  getMcpCatalog: vi.fn().mockResolvedValue({ entries: [] }),
  getMcpOAuthFlow: vi.fn(),
  listMcpServers: vi.fn().mockResolvedValue({ servers: [] }),
  removeMcpServer: vi.fn().mockResolvedValue({ ok: true })
}))

vi.mock('@/hermes', () => hermes)

import { connect } from './mcp'

const approved = { authorization_url: null, error: null, flow_id: 'f', server_name: 'linear', status: 'approved' }

describe('connecting a suggested MCP server', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = {
      openExternal: vi.fn().mockResolvedValue(undefined),
      webShell: false
    }
  })

  it('adds the URL as streamable HTTP with OAuth, so the server does not have to guess', async () => {
    hermes.authMcpServer.mockResolvedValue({
      ...approved,
      authorization_url: 'https://idp.example/a',
      status: 'authorization_required'
    })
    hermes.getMcpOAuthFlow.mockResolvedValue(approved)

    await connect({ hosts: [], keywords: [], server: 'linear', url: 'https://mcp.linear.app/mcp' }, null, () => false)

    expect(hermes.addMcpServer).toHaveBeenCalledWith({
      auth: 'oauth',
      name: 'linear',
      transport: 'streamable-http',
      url: 'https://mcp.linear.app/mcp'
    })
  })

  it('removes the half-added server when the sign-in fails', async () => {
    hermes.authMcpServer.mockResolvedValue({ ...approved, error: 'denied', status: 'error' })

    await expect(
      connect({ hosts: [], keywords: [], server: 'linear', url: 'https://mcp.linear.app/mcp' }, null, () => false)
    ).rejects.toThrow()

    expect(hermes.removeMcpServer).toHaveBeenCalledWith('linear')
  })
})
