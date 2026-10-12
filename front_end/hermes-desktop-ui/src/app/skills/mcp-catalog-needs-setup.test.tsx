import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { McpCatalogEntry } from '@/hermes'

import { McpCatalog } from './mcp-tab'

const base: McpCatalogEntry = {
  args: [],
  auth_type: 'none',
  bootstrap: [],
  command: null,
  default_enabled: null,
  description: 'A product with no hosted MCP address.',
  enabled: false,
  install_ref: 'salesforce',
  install_url: 'https://docs.example/salesforce',
  installed: false,
  name: 'salesforce',
  needs_install: false,
  post_install: '',
  required_env: [],
  source: 'vendor',
  transport: 'http',
  url: null
}

afterEach(cleanup)

describe('catalog rows that cannot be installed in one click', () => {
  it('says what to do and links the vendor instead of offering Install', () => {
    const open = vi.fn().mockResolvedValue(undefined)
    ;(window as unknown as { hermesDesktop: unknown }).hermesDesktop = { openExternal: open }

    render(
      <McpCatalog
        entries={[
          { ...base, needs_setup: true, setup_note: 'Find its MCP server URL in its docs, then paste it with Import.' }
        ]}
        loading={false}
        onInstalled={() => {}}
      />
    )

    expect(screen.getByText('Needs setup')).toBeTruthy()
    expect(screen.getByText(/paste it with Import/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()

    screen.getByRole('button', { name: 'Open site' }).click()
    expect(open).toHaveBeenCalledWith('https://docs.example/salesforce')
  })

  it('keeps Install for entries that can be installed', () => {
    render(
      <McpCatalog
        entries={[{ ...base, needs_setup: false, url: 'https://mcp.example/mcp' }]}
        loading={false}
        onInstalled={() => {}}
      />
    )

    expect(screen.getByRole('button', { name: 'Install' })).toBeTruthy()
    expect(screen.queryByText('Needs setup')).toBeNull()
  })
})
