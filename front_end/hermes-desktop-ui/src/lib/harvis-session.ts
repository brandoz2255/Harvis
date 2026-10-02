import { atom } from 'nanostores'

/**
 * Who is signed in to this Harvis, as the backend sees it.
 *
 * Harvis authenticates the browser with an HttpOnly `access_token` cookie that
 * page code cannot read, so the only way to know the session is to ask the
 * server. These calls go to the backend's `/api/...` routes directly (nginx
 * fronts them on the same origin), not through the Hermes `/hermes-api` facade.
 */

export interface HarvisUser {
  id: string
  email: string
  name: string
  role: string
}

export type SessionState =
  | { status: 'checking' }
  | { status: 'signed-in'; user: HarvisUser }
  // `expired`: the app was in use and the server stopped accepting the cookie.
  | { status: 'signed-out'; expired: boolean }
  | { status: 'unreachable'; detail: string }

export interface AuthConfig {
  /** No account exists yet: the first sign-up claims this Harvis as its admin. */
  onboarding: boolean
  signupEnabled: boolean
  setupCodeRequired: boolean
}

export const $session = atom<SessionState>({ status: 'checking' })

const SESSION_PATH = '/api/v1/auths/'
const MIN_PASSWORD = 8

export const MIN_PASSWORD_LENGTH = MIN_PASSWORD

/** An error whose message is safe to show the person as-is. */
export class AuthError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly field?: 'email' | 'password' | 'name' | 'setupCode' | 'newPassword'
  ) {
    super(message)
  }
}

// Keep only the fields the UI shows from the session response.
function toUser(body: unknown): HarvisUser {
  const raw = (body ?? {}) as Record<string, unknown>

  return {
    id: String(raw.id ?? ''),
    email: typeof raw.email === 'string' ? raw.email : '',
    name: typeof raw.name === 'string' && raw.name ? raw.name : typeof raw.email === 'string' ? raw.email : '',
    role: typeof raw.role === 'string' ? raw.role : 'user'
  }
}

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => '')

  try {
    const body = JSON.parse(text) as { detail?: unknown }

    if (typeof body.detail === 'string') {
      return body.detail
    }

    // FastAPI validation errors: [{ msg, loc }, …]
    if (Array.isArray(body.detail) && body.detail.length) {
      const first = body.detail[0] as { msg?: unknown }

      if (typeof first.msg === 'string') {
        return first.msg
      }
    }
  } catch {
    // nginx answers rate limits and outages with HTML; fall through
  }

  if (res.status === 429) {
    return 'Too many attempts. Wait a minute, then try again.'
  }

  if (res.status >= 500) {
    return 'Harvis hit an error. Try again in a moment.'
  }

  return `${res.status} ${res.statusText}`.trim()
}

async function send(path: string, body: unknown, headers?: Record<string, string>): Promise<Response> {
  try {
    return await fetch(path, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
      body: JSON.stringify(body)
    })
  } catch {
    throw new AuthError('Harvis is not answering. Check that it is running, then try again.', 0)
  }
}

// Bumped by every write to `$session`, so a probe that started before a sign-in
// cannot land afterwards and overwrite the fresh answer.
let generation = 0

function publish(next: SessionState): void {
  generation += 1
  $session.set(next)
}

/** Asks the server who is signed in and publishes the answer on `$session`. */
export async function probeSession(): Promise<SessionState> {
  const started = generation
  let next: SessionState

  try {
    const res = await fetch(SESSION_PATH, { credentials: 'include', cache: 'no-store' })

    if (res.ok) {
      next = { status: 'signed-in', user: toUser(await res.json()) }
    } else if (res.status === 401 || res.status === 403) {
      const prev = $session.get()
      next = {
        status: 'signed-out',
        expired: prev.status === 'signed-in' || (prev.status === 'signed-out' && prev.expired)
      }
    } else {
      next = { status: 'unreachable', detail: `${res.status} ${res.statusText}`.trim() }
    }
  } catch (err) {
    next = { status: 'unreachable', detail: err instanceof Error ? err.message : String(err) }
  }

  if (started !== generation) {
    return $session.get()
  }

  // A server that is down or erroring has not signed anyone out. Covering an app
  // in use with "unreachable" would also strand it: nothing re-probes from there.
  const prev = $session.get()

  if (next.status === 'unreachable' && prev.status === 'signed-in') {
    return prev
  }

  publish(next)

  return next
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch('/api/config', { credentials: 'include', cache: 'no-store' })

  if (!res.ok) {
    throw new AuthError(await readDetail(res), res.status)
  }

  const body = (await res.json()) as {
    onboarding?: boolean
    features?: { enable_signup?: boolean; setup_code_required?: boolean }
  }

  return {
    onboarding: Boolean(body.onboarding),
    signupEnabled: body.features?.enable_signup !== false,
    setupCodeRequired: Boolean(body.features?.setup_code_required)
  }
}

export async function signIn(email: string, password: string): Promise<HarvisUser> {
  if (!email.trim()) {
    throw new AuthError('Enter your email.', 0, 'email')
  }

  const res = await send('/api/v1/auths/signin', { email: email.trim(), password })

  if (!res.ok) {
    throw new AuthError(
      res.status === 401 ? 'That email and password do not match an account.' : await readDetail(res),
      res.status,
      res.status === 401 ? 'password' : undefined
    )
  }

  const user = toUser(await res.json())
  publish({ status: 'signed-in', user })

  return user
}

export async function signUp(input: {
  name: string
  email: string
  password: string
  setupCode?: string
}): Promise<HarvisUser> {
  // The form turns off browser validation to show its own messages, and the
  // server accepts empty strings, so blank fields have to stop here.
  if (!input.name.trim()) {
    throw new AuthError('Enter your name.', 0, 'name')
  }

  if (!/^[^\s@]+@[^\s@]+$/.test(input.email.trim())) {
    throw new AuthError('Enter an email address, like name@example.com.', 0, 'email')
  }

  if (input.password.length < MIN_PASSWORD) {
    throw new AuthError(`Use at least ${MIN_PASSWORD} characters.`, 0, 'password')
  }

  const code = input.setupCode?.trim()

  const res = await send(
    '/api/v1/auths/signup',
    { name: input.name.trim(), email: input.email.trim(), password: input.password },
    code ? { 'X-Setup-Code': code } : undefined
  )

  if (!res.ok) {
    const detail = await readDetail(res)

    // The server answers 409 for a taken email OR a taken name (the name is the
    // unique username) and does not say which.
    if (res.status === 409 || /already/i.test(detail)) {
      throw new AuthError(
        'That email or name is already in use. Sign in instead, or choose a different name.',
        res.status
      )
    }

    if (/setup code/i.test(detail)) {
      throw new AuthError('That setup code is not right.', res.status, 'setupCode')
    }

    if (/disabled/i.test(detail)) {
      throw new AuthError('This Harvis is not taking new accounts. Ask its admin to add you.', res.status)
    }

    throw new AuthError(detail, res.status)
  }

  const user = toUser(await res.json())
  publish({ status: 'signed-in', user })

  return user
}

export async function changePassword(current: string, next: string): Promise<void> {
  if (next.length < MIN_PASSWORD) {
    throw new AuthError(`Use at least ${MIN_PASSWORD} characters.`, 0, 'newPassword')
  }

  const res = await send('/api/v1/auths/update/password', { password: current, new_password: next })

  if (res.status === 401) {
    reportUnauthorized()
    throw new AuthError('Your session ended. Sign in again, then change your password.', 401)
  }

  if (!res.ok) {
    const detail = await readDetail(res)

    throw new AuthError(
      /incorrect|current|wrong/i.test(detail) ? 'Your current password is not right.' : detail,
      res.status,
      /incorrect|current|wrong/i.test(detail) ? 'password' : undefined
    )
  }
}

/** Ends the session on the server, then reloads into the sign-in screen. */
export async function signOut(): Promise<void> {
  try {
    await fetch('/api/v1/auths/signout', { method: 'POST', credentials: 'include', cache: 'no-store' })
  } catch {
    // Even if the server is unreachable, leave the app; the reload re-probes.
  }

  // The retired OWUI frontend kept a copy of the token here.
  try {
    window.localStorage.removeItem('token')
  } catch {
    // storage blocked: nothing to clear
  }

  // The shell's own address (/harvis/), dropping the #route of the old session.
  window.location.replace(import.meta.env.BASE_URL)
}

let recheck: null | Promise<SessionState> = null

/**
 * Any API call that got a 401 reports it here. One 401 is not proof the session
 * is gone (a route can answer 401 for its own reasons), so this re-asks the
 * session endpoint and only the answer from there signs the person out.
 */
export function reportUnauthorized(): void {
  if ($session.get().status !== 'signed-in' || recheck) {
    return
  }

  recheck = probeSession().finally(() => {
    recheck = null
  })
}

const WATCH_INTERVAL_MS = 5 * 60_000

/**
 * Re-checks the session when the tab comes back into view and every few minutes
 * while signed in, so an expired cookie shows the sign-in card before the next
 * action fails. A failed check while signed in leaves the app alone: the server
 * being briefly down is not a reason to cover the page.
 */
export function startSessionWatch(): () => void {
  const check = () => {
    if ($session.get().status !== 'signed-in' || document.visibilityState === 'hidden') {
      return
    }

    void fetch(SESSION_PATH, { credentials: 'include', cache: 'no-store' })
      .then(async res => {
        if (res.status === 401 || res.status === 403) {
          publish({ status: 'signed-out', expired: true })

          return
        }

        // Someone else signed in from another tab: the cookie is theirs now.
        // Publishing them lets SessionGate restart the app instead of leaving
        // this tab showing the previous person's chats.
        const current = $session.get()

        if (res.ok && current.status === 'signed-in') {
          const user = toUser(await res.json())

          if (user.id && user.id !== current.user.id) {
            publish({ status: 'signed-in', user })
          }
        }
      })
      .catch(() => undefined)
  }

  const timer = window.setInterval(check, WATCH_INTERVAL_MS)
  window.addEventListener('focus', check)
  document.addEventListener('visibilitychange', check)

  return () => {
    window.clearInterval(timer)
    window.removeEventListener('focus', check)
    document.removeEventListener('visibilitychange', check)
  }
}
