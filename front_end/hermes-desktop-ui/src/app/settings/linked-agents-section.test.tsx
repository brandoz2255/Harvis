import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LinkedAgentsSection } from './linked-agents-section'

const empty = { connected: false, last_error: null, token_saved: false, url: null, verified_at: null }

const calls: { body: unknown; method: string; path: string }[] = []
let statuses: Record<string, Record<string, unknown>> = {}
let verifyReply: Record<string, unknown> = {}

beforeEach(() => {
  calls.length = 0
  statuses = { hermes: { ...empty }, openclaw: { ...empty } }
  verifyReply = { error: null, ok: true }

  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      const id = path.includes('openclaw') ? 'openclaw' : 'hermes'
      calls.push({ body, method, path })

      if (method === 'POST' && path.endsWith('/verify')) {
        statuses[id] = { ...statuses[id], connected: Boolean(verifyReply.ok), last_error: verifyReply.error ?? null }

        return Response.json({ ...statuses[id], ...verifyReply })
      }

      if (method === 'POST' && path.endsWith('/disconnect')) {
        statuses[id] = { ...empty }

        return Response.json({ connected: false })
      }

      if (method === 'POST') {
        statuses[id] = { ...statuses[id], connected: false, token_saved: Boolean(body.token), url: body.url }

        return Response.json(statuses[id])
      }

      return Response.json(statuses[id])
    })
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <LinkedAgentsSection />
    </QueryClientProvider>
  )
}

describe('LinkedAgentsSection', () => {
  it('shows Hermes as recommended and OpenClaw as optional, with plain copy', async () => {
    renderSection()

    expect(await screen.findByText('Hermes (external)')).toBeTruthy()
    expect(screen.getByText('OpenClaw (external)')).toBeTruthy()
    expect(screen.getByText('Recommended')).toBeTruthy()
    expect(screen.getByText('Optional, legacy')).toBeTruthy()
    expect(
      screen.getByText(/Hermes is the recommended agent\. Link your own OpenClaw only if you already run one/)
    ).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('Not linked')).toHaveLength(2))
  })

  it('saves what was typed, then verifies, for the OpenClaw row only', async () => {
    renderSection()
    await screen.findByText('OpenClaw (external)')

    fireEvent.change(screen.getByLabelText('OpenClaw (external) address'), {
      target: { value: 'http://claw.lan:18789' }
    })
    fireEvent.change(screen.getByLabelText('OpenClaw gateway token'), { target: { value: 'secret-token' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Verify' })[1]!)

    await waitFor(() => expect(screen.getByText('Linked')).toBeTruthy())

    const writes = calls.filter(c => c.method === 'POST')

    expect(writes.map(c => c.path)).toEqual([
      '/api/owui/integrations/openclaw-external',
      '/api/owui/integrations/openclaw-external/verify'
    ])
    expect(writes[0]!.body).toEqual({ token: 'secret-token', url: 'http://claw.lan:18789' })
  })

  it('never shows a saved token back, and clears the typed one after saving', async () => {
    statuses.openclaw = { ...empty, token_saved: true, url: 'http://claw.lan:18789' }
    renderSection()

    const token = (await screen.findByLabelText('OpenClaw gateway token')) as HTMLInputElement

    expect(token.value).toBe('')
    expect(token.type).toBe('password')
    await waitFor(() => expect(token.placeholder).toMatch(/Token saved/))
    await waitFor(() =>
      expect((screen.getByLabelText('OpenClaw (external) address') as HTMLInputElement).value).toBe(
        'http://claw.lan:18789'
      )
    )

    fireEvent.change(token, { target: { value: 'new-token' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Verify' })[1]!)
    await waitFor(() => expect(token.value).toBe(''))
    expect(document.body.textContent).not.toContain('new-token')
  })

  it('does not re-save an unchanged address on Verify, so a saved token is kept', async () => {
    statuses.openclaw = { ...empty, token_saved: true, url: 'http://claw.lan:18789' }
    renderSection()
    await waitFor(() =>
      expect((screen.getByLabelText('OpenClaw (external) address') as HTMLInputElement).value).toBe(
        'http://claw.lan:18789'
      )
    )

    fireEvent.click(screen.getAllByRole('button', { name: 'Verify' })[1]!)
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/verify'))).toBe(true))

    expect(calls.filter(c => c.method === 'POST').map(c => c.path)).toEqual([
      '/api/owui/integrations/openclaw-external/verify'
    ])
  })

  it('shows the gateway error when verification fails', async () => {
    verifyReply = { error: 'Authentication failed — check the gateway token.', ok: false }
    renderSection()
    await screen.findByText('OpenClaw (external)')

    fireEvent.change(screen.getByLabelText('OpenClaw (external) address'), {
      target: { value: 'http://claw.lan:18789' }
    })
    fireEvent.click(screen.getAllByRole('button', { name: 'Verify' })[1]!)

    expect(await screen.findByText('Authentication failed — check the gateway token.')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Verification failed')).toBeTruthy())
  })

  it('disconnects a saved link', async () => {
    statuses.openclaw = { ...empty, connected: true, token_saved: true, url: 'http://claw.lan:18789', verified_at: 1 }
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))

    await waitFor(() =>
      expect(calls.some(c => c.path === '/api/owui/integrations/openclaw-external/disconnect')).toBe(true)
    )
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Disconnect' })).toBeNull())
    expect(screen.getAllByText('Not linked')).toHaveLength(2)
  })
})
