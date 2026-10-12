import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $session } from '@/lib/harvis-session'

import { AddComputerForm } from './add-computer'
import type { ModelRequest } from './harvis-api'
import { RequestModelForm } from './model-requests'
import { ModelsSettings } from './models-page'

const SPAM_LIMIT = 'You can ask for 5 models a day. Try again tomorrow.'

const mine: ModelRequest[] = [
  {
    id: 1,
    model: 'gemma3:4b',
    note: null,
    status: 'open',
    votes: 2,
    requested_by: { id: 7, username: 'pat' },
    created_at: '2026-10-09T00:00:00Z',
    decided_at: null,
    reason: null
  },
  {
    id: 2,
    model: 'llama3.3:70b',
    note: null,
    status: 'denied',
    votes: 1,
    requested_by: { id: 7, username: 'pat' },
    created_at: '2026-10-08T00:00:00Z',
    decided_at: '2026-10-08T01:00:00Z',
    reason: 'Too big for this server'
  },
  {
    id: 3,
    model: 'qwen3:8b',
    note: null,
    status: 'approved',
    votes: 1,
    requested_by: { id: 7, username: 'pat' },
    created_at: '2026-10-07T00:00:00Z',
    decided_at: '2026-10-07T01:00:00Z',
    reason: null
  }
]

let post: { status: number; body: unknown } = { status: 201, body: {} }
let calls: { path: string; method: string; body: unknown }[] = []

const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
  const method = init?.method ?? 'GET'
  calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  if (method === 'POST') {
    return json(post.body, post.status)
  }

  if (path.startsWith('/api/cookbook/nodes')) {
    return json({ nodes: [{ name: 'main-host', role: 'main' }] })
  }

  if (path.startsWith('/api/cookbook/installed')) {
    return json({
      models: [
        { name: 'qwen3:8b', size: 4_800_000_000, details: { family: 'qwen3', parameter_size: '8B' } },
        { name: 'tiny:latest', size: 0 },
        { name: 'kimi-k2.6:cloud', size: 0 },
        { name: 'qwen3-coder:480b-cloud', size: 0 },
        { name: 'hosted:latest', size: 0, remote_host: 'https://ollama.com:443' }
      ]
    })
  }

  if (path.startsWith('/api/cookbook/recommend')) {
    return json({ models: [] })
  }

  if (path.startsWith('/api/model-requests/mine')) {
    return json({ requests: mine })
  }

  if (path.startsWith('/api/model-requests')) {
    return json({ requests: [] })
  }

  if (path.startsWith('/api/inference-nodes')) {
    return json({ nodes: [] })
  }

  return json({}, 404)
})

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const user = (role: string) => ({ status: 'signed-in' as const, user: { email: 'a@b.test', id: '1', name: 'A', role } })

beforeEach(() => {
  calls = []
  post = { status: 201, body: {} }
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  fetchMock.mockClear()
  vi.unstubAllGlobals()
  $session.set({ status: 'checking' })
})

describe('RequestModelForm', () => {
  const ask = (model: string) => {
    fireEvent.change(screen.getByPlaceholderText('gemma3:4b'), { target: { value: model } })
    fireEvent.click(screen.getByRole('button', { name: 'Request model' }))
  }

  it('shows the spam limit sentence exactly as the server sent it', async () => {
    post = { status: 429, body: { detail: SPAM_LIMIT } }
    renderWithQuery(<RequestModelForm />)

    ask('gemma3:4b')

    expect((await screen.findByRole('alert')).textContent).toBe(SPAM_LIMIT)
    // The model stays in the box so the person can see what was refused.
    expect((screen.getByPlaceholderText('gemma3:4b') as HTMLInputElement).value).toBe('gemma3:4b')
  })

  it('shows a 409 reason as-is', async () => {
    const detail = '"gemma3:4b" was denied in the last 30 days: too big. Try again after 30 days.'
    post = { status: 409, body: { detail } }
    renderWithQuery(<RequestModelForm />)

    ask('gemma3:4b')

    expect((await screen.findByRole('alert')).textContent).toBe(detail)
  })

  it('sends the model and the note, and trims the note away when blank', async () => {
    post = { status: 201, body: { request: mine[0] } }
    renderWithQuery(<RequestModelForm />)

    ask('  gemma3:4b ')

    await screen.findByText('Request sent. The admin will see it.')
    expect(calls.find(c => c.method === 'POST')).toMatchObject({
      body: { model: 'gemma3:4b' },
      path: '/api/model-requests'
    })
    expect(calls.find(c => c.method === 'POST')?.body).not.toHaveProperty('note')
  })

  it('says so when it joined a request someone else made', async () => {
    post = { status: 200, body: { request: mine[0], joined: true } }
    renderWithQuery(<RequestModelForm />)

    ask('gemma3:4b')

    await screen.findByText('Someone already asked for that one. Your vote is added.')
  })

  it('keeps the button off until a model is typed', () => {
    renderWithQuery(<RequestModelForm />)

    expect((screen.getByRole('button', { name: 'Request model' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('AddComputerForm', () => {
  it('takes only a 6-digit numeric PIN and shows the server sentence on failure', async () => {
    post = { status: 403, body: { detail: 'That PIN is not right.' } }
    renderWithQuery(<AddComputerForm />)

    const pin = screen.getByPlaceholderText('123456') as HTMLInputElement
    expect(pin.getAttribute('inputmode')).toBe('numeric')
    expect(pin.maxLength).toBe(6)

    fireEvent.change(pin, { target: { value: '12ab34567' } })
    expect(pin.value).toBe('123456')

    fireEvent.change(screen.getByPlaceholderText('192.168.1.50'), { target: { value: '192.168.1.50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add computer' }))

    expect((await screen.findByRole('alert')).textContent).toBe('That PIN is not right.')
    expect(calls.find(c => c.method === 'POST')).toMatchObject({
      body: { address: '192.168.1.50', pin: '123456' },
      path: '/api/inference-nodes/pair'
    })
  })

  it('explains how to get a PIN', () => {
    renderWithQuery(<AddComputerForm />)

    screen.getByText('On the other computer, run harvis_node.py. It shows a 6-digit PIN.')
  })
})

describe('ModelsSettings', () => {
  it('shows a member the installed list and their requests, and nothing admin-only', async () => {
    $session.set(user('user'))
    renderWithQuery(<ModelsSettings />)

    expect(await screen.findByText('4.8 GB')).toBeTruthy()
    expect(screen.getByText('qwen3 · 8B')).toBeTruthy()
    // Every installed model is listed, even one with no size.
    expect(screen.getByText('tiny:latest')).toBeTruthy()
    // Ollama cloud models run on ollama.com, not here, so they are not listed.
    expect(screen.queryByText('kimi-k2.6:cloud')).toBeNull()
    expect(screen.queryByText('qwen3-coder:480b-cloud')).toBeNull()
    expect(screen.queryByText('hosted:latest')).toBeNull()

    expect(await screen.findByText('Waiting')).toBeTruthy()
    expect(screen.getByText('Denied')).toBeTruthy()
    expect(screen.getByText('Reason: Too big for this server')).toBeTruthy()
    expect(screen.getByText('Request a model')).toBeTruthy()

    expect(screen.queryByText('Get a model')).toBeNull()
    expect(screen.queryByText('Other computers')).toBeNull()
    await waitFor(() => expect(calls.some(c => c.path.startsWith('/api/inference-nodes'))).toBe(false))
    expect(calls.some(c => c.path.startsWith('/api/model-requests?status=open'))).toBe(false)
  })

  it('shows an admin the download, requests and computers sections instead', async () => {
    $session.set(user('admin'))
    renderWithQuery(<ModelsSettings />)

    expect(await screen.findByText('Get a model')).toBeTruthy()
    expect(await screen.findByText('Other computers')).toBeTruthy()
    expect(screen.getByText('Requests')).toBeTruthy()
    expect(screen.queryByText('Request a model')).toBeNull()
    expect(screen.queryByText('My requests')).toBeNull()
  })
})
