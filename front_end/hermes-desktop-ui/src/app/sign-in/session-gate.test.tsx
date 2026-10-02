import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $session } from '@/lib/harvis-session'

import { SessionGate } from './session-gate'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const USER = { id: '1', email: 'a@example.test', name: 'Ada', role: 'admin' }

function route(session: () => Response, config = { onboarding: false, features: { enable_signup: true } }) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)

    if (url === '/api/v1/auths/') {
      return session()
    }

    if (url === '/api/config') {
      return json(200, config)
    }

    return json(404, {})
  })
}

describe('SessionGate', () => {
  beforeEach(() => {
    $session.set({ status: 'checking' })
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ addEventListener: vi.fn(), matches: true, removeEventListener: vi.fn() }))
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows sign-in and does not mount the app when signed out', async () => {
    vi.stubGlobal(
      'fetch',
      route(() => json(401, {}))
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    expect(await screen.findByRole('heading', { name: 'Sign in to Harvis' })).toBeTruthy()
    expect(screen.queryByText('the app')).toBeNull()
    expect(await screen.findByRole('button', { name: 'Create an account' })).toBeTruthy()
  })

  it('offers the admin claim on a fresh install', async () => {
    vi.stubGlobal(
      'fetch',
      route(() => json(401, {}), { onboarding: true, features: { enable_signup: true } })
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    expect(await screen.findByRole('heading', { name: 'Set up this Harvis' })).toBeTruthy()
  })

  it('mounts the app when signed in, and covers it without unmounting when the session ends', async () => {
    vi.stubGlobal(
      'fetch',
      route(() => json(200, USER))
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    expect(await screen.findByText('the app')).toBeTruthy()

    act(() => $session.set({ status: 'signed-out', expired: true }))

    expect(await screen.findByRole('heading', { name: 'Your session ended' })).toBeTruthy()
    expect(screen.getByText('the app')).toBeTruthy()
    expect(screen.getByText('the app').closest('[inert]')).not.toBeNull()
  })

  it('says so when the server does not answer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      })
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    expect(await screen.findByRole('heading', { name: "Harvis isn't answering yet" })).toBeTruthy()
  })

  it('keeps the card up while a different person signing in restarts the app', async () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    vi.stubGlobal(
      'fetch',
      route(() => json(200, USER))
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    expect(await screen.findByText('the app')).toBeTruthy()

    act(() => $session.set({ status: 'signed-in', user: { ...USER, id: '2', email: 'b@example.test' } }))

    expect(reload).toHaveBeenCalled()
    expect(screen.getByText('the app').closest('[inert]')).not.toBeNull()
  })

  it('says what is missing when sign-up is sent with a blank name', async () => {
    vi.stubGlobal(
      'fetch',
      route(() => json(401, {}))
    )

    render(
      <SessionGate>
        <p>the app</p>
      </SessionGate>
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Create an account' }))
    fireEvent.click(await screen.findByRole('button', { name: /Create account/ }))

    expect(await screen.findByText('Enter your name.')).toBeTruthy()
  })
})
