import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Person } from './harvis-api'
import { PeopleSettings } from './people-settings'

const confirmMock = vi.fn<(req: unknown) => Promise<boolean>>()
vi.mock('@/store/confirm', () => ({ confirm: (req: unknown) => confirmMock(req) }))

const admin: Person = {
  id: 1,
  name: 'David',
  email: 'admin@example.test',
  joined: '2026-09-01T00:00:00Z',
  is_admin: true,
  pending: false,
  note_to_host: null,
  blocked: false,
  daily_message_limit: null,
  allowed_models: null,
  messages_today: 12,
  messages_week: 40,
  last_active: null,
  chats: 9,
  paired: []
}

const member: Person = {
  ...admin,
  id: 7,
  name: 'Pat',
  email: 'pat@example.test',
  is_admin: false,
  daily_message_limit: 20,
  messages_today: 3,
  messages_week: 5,
  chats: 1,
  paired: [{ id: 44, platform: 'discord', identifier: '1234', name: 'pat#0001', enabled: true, since: null }]
}

const off: Person = { ...member, id: 8, name: 'Sam', email: 'sam@example.test', blocked: true, paired: [] }

const waiting: Person = {
  ...member,
  id: 9,
  name: 'Jane',
  email: 'jane@example.test',
  pending: true,
  note_to_host: 'Jane from CSE 4800',
  daily_message_limit: null,
  paired: []
}

type Call = { path: string; method: string; body: unknown }
let calls: Call[] = []
let extraUsers: Person[] = []

const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
  const method = init?.method ?? 'GET'
  calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })

  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

  if (path.endsWith('/admin/users') && method === 'GET') {
    return json({ users: [admin, member, off, ...extraUsers] })
  }

  if (path.endsWith('/admin/models')) {
    return json({
      models: [
        { id: 'gemma4:e2b', provider: 'ollama' },
        { id: 'qwen3:35b', provider: 'ollama' }
      ]
    })
  }

  if (path === '/api/v1/auths/admin/config') {
    return json({ ENABLE_SIGNUP: true, DEV_MODE: false, ...((calls.at(-1)?.body as object) ?? {}) })
  }

  return json({ ok: true })
})

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <PeopleSettings />
    </QueryClientProvider>
  )
}

const writes = () => calls.filter(c => c.method !== 'GET')

beforeEach(() => {
  calls = []
  extraUsers = []
  fetchMock.mockClear()
  confirmMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('PeopleSettings', () => {
  it('lists everyone with today’s use, their state, and paired contacts', async () => {
    renderPage()

    expect(await screen.findByText('Pat')).toBeTruthy()
    expect(screen.getByText('Admin')).toBeTruthy()
    expect(screen.getByText('Turned off')).toBeTruthy()
    expect(screen.getByText('12 today')).toBeTruthy()
    expect(screen.getAllByText('3 / 20 today')).toHaveLength(2)
    expect(screen.getByText('pat#0001')).toBeTruthy()
    // The admin has no limits, so no controls on their row.
    expect(screen.getAllByRole('button', { name: /Turn off|Turn on/ })).toHaveLength(2)
  })

  it('shows the waiting list only when someone is waiting, apart from everyone else', async () => {
    renderPage()
    await screen.findByText('Pat')
    expect(screen.queryByText('Waiting for you')).toBeNull()

    cleanup()
    extraUsers = [waiting]
    renderPage()
    expect(await screen.findByText('Waiting for you')).toBeTruthy()
    expect(screen.getByText('“Jane from CSE 4800”')).toBeTruthy()
    expect(screen.getByText('Waiting')).toBeTruthy()
    // Waiting people get Let in / Turn away, not the member controls.
    expect(screen.getAllByRole('button', { name: /Turn off|Turn on/ })).toHaveLength(2)
  })

  it('lets a waiting person in with one click', async () => {
    extraUsers = [waiting]
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Let in' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ path: '/hermes-api/api/harvis/admin/users/9/approve', method: 'POST' })
    expect(confirmMock).not.toHaveBeenCalled()
  })

  it('turns a waiting person away only after the admin confirms', async () => {
    extraUsers = [waiting]
    renderPage()
    const away = await screen.findByRole('button', { name: 'Turn away' })

    confirmMock.mockResolvedValueOnce(false)
    fireEvent.click(away)
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1))
    expect(writes()).toHaveLength(0)

    confirmMock.mockResolvedValueOnce(true)
    fireEvent.click(away)
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ path: '/hermes-api/api/harvis/admin/users/9/reject', method: 'POST' })
  })

  it('turns a person off only after the admin confirms', async () => {
    renderPage()
    await screen.findByText('Pat')

    confirmMock.mockResolvedValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1))
    expect(writes()).toHaveLength(0)

    confirmMock.mockResolvedValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toEqual({
      path: '/hermes-api/api/harvis/admin/users/7',
      method: 'PUT',
      body: { blocked: true }
    })
  })

  it('turns a person back on without asking', async () => {
    renderPage()
    await screen.findByText('Sam')

    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(confirmMock).not.toHaveBeenCalled()
    expect(writes()[0].body).toEqual({ blocked: false })
  })

  it('saves only the limits the admin changed', async () => {
    renderPage()
    await screen.findByText('Pat')

    fireEvent.click(screen.getAllByRole('button', { name: 'Limits' })[0])
    fireEvent.change(screen.getByPlaceholderText('No limit'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Only these' }))

    const save = screen.getByRole('button', { name: 'Save limits' }) as HTMLButtonElement
    expect(screen.getByText(/Pick at least one model/)).toBeTruthy()
    expect(save.disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'gemma4:e2b' }))
    expect(save.disabled).toBe(false)
    fireEvent.click(save)

    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toEqual({
      path: '/hermes-api/api/harvis/admin/users/7',
      method: 'PUT',
      body: { daily_message_limit: 5, allowed_models: ['gemma4:e2b'] }
    })
  })

  it('unpairs a contact after confirming', async () => {
    renderPage()
    await screen.findByText('pat#0001')

    confirmMock.mockResolvedValueOnce(true)
    fireEvent.click(screen.getByRole('button', { name: 'Unpair' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ path: '/hermes-api/api/harvis/admin/senders/44', method: 'DELETE' })
  })

  it('switches new sign-ups off', async () => {
    renderPage()
    const toggle = await screen.findByRole('switch', { name: 'Allow new sign-ups' })

    fireEvent.click(toggle)
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toEqual({ path: '/api/v1/auths/admin/config', method: 'POST', body: { ENABLE_SIGNUP: false } })
  })
})
