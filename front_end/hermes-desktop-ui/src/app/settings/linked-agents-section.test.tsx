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
  statuses = { hermes: { ...empty } }
  verifyReply = { error: null, ok: true }

  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      const id = 'hermes'
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
  it('shows the Hermes link with plain copy and nothing else', async () => {
    renderSection()

    expect(await screen.findByText('Hermes (external)')).toBeTruthy()
    expect(screen.getByText('Recommended')).toBeTruthy()
    expect(screen.getByText(/Link a Hermes Agent you already run/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/openclaw/i)
    await waitFor(() => expect(screen.getAllByText('Not linked')).toHaveLength(1))
  })

  it('saves what was typed, then verifies, for the Hermes row', async () => {
    renderSection()
    await screen.findByText('Hermes (external)')

    fireEvent.change(screen.getByLabelText('Hermes (external) address'), {
      target: { value: 'http://hermes.lan:8642' }
    })
    fireEvent.change(screen.getByLabelText('Hermes API key'), { target: { value: 'secret-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))

    await waitFor(() => expect(screen.getByText('Linked')).toBeTruthy())

    const writes = calls.filter(c => c.method === 'POST')

    expect(writes.map(c => c.path)).toEqual([
      '/api/owui/integrations/hermes-external',
      '/api/owui/integrations/hermes-external/verify'
    ])
    expect(writes[0]!.body).toEqual({ token: 'secret-token', url: 'http://hermes.lan:8642' })
  })

  it('never shows a saved token back, and clears the typed one after saving', async () => {
    statuses.hermes = { ...empty, token_saved: true, url: 'http://hermes.lan:8642' }
    renderSection()

    const token = (await screen.findByLabelText('Hermes API key')) as HTMLInputElement

    expect(token.value).toBe('')
    expect(token.type).toBe('password')
    await waitFor(() => expect(token.placeholder).toMatch(/Token saved/))
    await waitFor(() =>
      expect((screen.getByLabelText('Hermes (external) address') as HTMLInputElement).value).toBe(
        'http://hermes.lan:8642'
      )
    )

    fireEvent.change(token, { target: { value: 'new-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(token.value).toBe(''))
    expect(document.body.textContent).not.toContain('new-token')
  })

  it('does not re-save an unchanged address on Verify, so a saved token is kept', async () => {
    statuses.hermes = { ...empty, token_saved: true, url: 'http://hermes.lan:8642' }
    renderSection()
    await waitFor(() =>
      expect((screen.getByLabelText('Hermes (external) address') as HTMLInputElement).value).toBe(
        'http://hermes.lan:8642'
      )
    )

    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/verify'))).toBe(true))

    expect(calls.filter(c => c.method === 'POST').map(c => c.path)).toEqual([
      '/api/owui/integrations/hermes-external/verify'
    ])
  })

  it('shows the gateway error when verification fails', async () => {
    verifyReply = { error: 'Authentication failed — check the API key.', ok: false }
    renderSection()
    await screen.findByText('Hermes (external)')

    fireEvent.change(screen.getByLabelText('Hermes (external) address'), {
      target: { value: 'http://hermes.lan:8642' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))

    expect(await screen.findByText('Authentication failed — check the API key.')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Verification failed')).toBeTruthy())
  })

  it('disconnects a saved link', async () => {
    statuses.hermes = { ...empty, connected: true, token_saved: true, url: 'http://hermes.lan:8642', verified_at: 1 }
    renderSection()

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))

    await waitFor(() =>
      expect(calls.some(c => c.path === '/api/owui/integrations/hermes-external/disconnect')).toBe(true)
    )
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Disconnect' })).toBeNull())
    expect(screen.getAllByText('Not linked')).toHaveLength(1)
  })
})
