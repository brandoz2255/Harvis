import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  $session,
  AuthError,
  probeSession,
  reportUnauthorized,
  signIn,
  signUp,
  startSessionWatch
} from './harvis-session'

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const flush = () => new Promise(resolve => setTimeout(resolve, 0))

describe('harvis session', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    $session.set({ status: 'checking' })
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('keeps only display fields from the session, never the token', async () => {
    fetchMock.mockResolvedValueOnce(
      json(200, { id: 7, email: 'a@example.test', name: 'Ada', role: 'admin', token: 'secret-jwt' })
    )

    const state = await probeSession()

    expect(state).toEqual({
      status: 'signed-in',
      user: { id: '7', email: 'a@example.test', name: 'Ada', role: 'admin' }
    })
    expect(JSON.stringify($session.get())).not.toContain('secret-jwt')
  })

  it('treats 401 as signed out and anything else as unreachable', async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'Not authenticated' }))
    expect(await probeSession()).toEqual({ status: 'signed-out', expired: false })

    fetchMock.mockResolvedValueOnce(new Response('bad gateway', { status: 502, statusText: 'Bad Gateway' }))
    expect((await probeSession()).status).toBe('unreachable')

    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    expect(await probeSession()).toEqual({ status: 'unreachable', detail: 'Failed to fetch' })
  })

  it('marks the sign-out as expired when someone was signed in', async () => {
    $session.set({ status: 'signed-in', user: { id: '1', email: 'a@x.test', name: 'A', role: 'user' } })
    fetchMock.mockResolvedValueOnce(json(401, {}))

    expect(await probeSession()).toEqual({ status: 'signed-out', expired: true })
  })

  it('signs out on a reported 401 only if the session check agrees', async () => {
    const user = { id: '1', email: 'a@x.test', name: 'A', role: 'user' }

    $session.set({ status: 'signed-in', user })
    fetchMock.mockResolvedValueOnce(json(200, user))
    reportUnauthorized()
    await flush()
    expect($session.get().status).toBe('signed-in')

    fetchMock.mockResolvedValueOnce(json(401, {}))
    reportUnauthorized()
    reportUnauthorized() // a burst of 401s re-checks once
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect($session.get()).toEqual({ status: 'signed-out', expired: true })
  })

  it('gives a plain message for a wrong password', async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'Incorrect email or password' }))

    await expect(signIn('a@x.test', 'nope')).rejects.toMatchObject({
      field: 'password',
      message: 'That email and password do not match an account.'
    })
  })

  it('sends the setup code as a header and maps a bad one to its field', async () => {
    fetchMock.mockResolvedValueOnce(
      json(403, { detail: 'First signup requires a valid setup code (X-Setup-Code header)' })
    )

    const err = await signUp({ name: 'A', email: 'a@x.test', password: 'longenough', setupCode: ' abc ' }).catch(e => e)

    expect(err).toBeInstanceOf(AuthError)
    expect(err.field).toBe('setupCode')
    expect(fetchMock.mock.calls[0][1].headers['X-Setup-Code']).toBe('abc')
  })

  it('refuses a short password before calling the server', async () => {
    await expect(signUp({ name: 'A', email: 'a@x.test', password: 'short' })).rejects.toMatchObject({
      field: 'password'
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('explains a rate limit from nginx, which answers in HTML', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>429</html>', { status: 429, statusText: 'Too Many Requests' }))

    await expect(signIn('a@x.test', 'pw')).rejects.toMatchObject({
      message: 'Too many attempts. Wait a minute, then try again.'
    })
  })

  it('keeps a signed-in app when the session check fails for a reason other than 401', async () => {
    const user = { id: '1', email: 'a@x.test', name: 'A', role: 'user' }

    $session.set({ status: 'signed-in', user })
    fetchMock.mockResolvedValueOnce(new Response('down', { status: 503, statusText: 'Service Unavailable' }))

    expect(await probeSession()).toEqual({ status: 'signed-in', user })
    expect($session.get()).toEqual({ status: 'signed-in', user })
  })

  it('does not let a probe that started before a sign-in overwrite it', async () => {
    let answerProbe: (res: Response) => void = () => undefined

    fetchMock.mockImplementationOnce(() => new Promise<Response>(resolve => (answerProbe = resolve)))
    const probe = probeSession()

    fetchMock.mockResolvedValueOnce(json(200, { id: 2, email: 'b@x.test', name: 'B' }))
    await signIn('b@x.test', 'longenough')

    answerProbe(json(401, {}))
    await probe

    expect($session.get()).toMatchObject({ status: 'signed-in', user: { id: '2' } })
  })

  it('publishes a different user signed in from another tab', async () => {
    $session.set({ status: 'signed-in', user: { id: '1', email: 'a@x.test', name: 'A', role: 'user' } })
    fetchMock.mockResolvedValueOnce(json(200, { id: 2, email: 'b@x.test', name: 'B' }))

    const stop = startSessionWatch()
    window.dispatchEvent(new Event('focus'))
    await flush()
    await flush()
    stop()

    expect($session.get()).toMatchObject({ status: 'signed-in', user: { id: '2' } })
  })

  it('refuses a blank name or a malformed email before calling the server', async () => {
    await expect(signUp({ name: ' ', email: 'a@x.test', password: 'longenough' })).rejects.toMatchObject({
      field: 'name'
    })
    await expect(signUp({ name: 'A', email: 'not-an-email', password: 'longenough' })).rejects.toMatchObject({
      field: 'email'
    })
    await expect(signIn('  ', 'longenough')).rejects.toMatchObject({ field: 'email' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('does not blame the email when the server says the email or name is taken', async () => {
    fetchMock.mockResolvedValueOnce(json(409, { detail: 'User with this email or username already exists' }))

    const err = await signUp({ name: 'A', email: 'a@x.test', password: 'longenough' }).catch(e => e)

    expect(err.field).toBeUndefined()
    expect(err.message).toMatch(/email or name is already in use/)
  })
})
