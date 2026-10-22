import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react'

import { AsciiField } from '@/components/chat/ascii-field'
import { HarvisWordmark } from '@/components/chat/harvis-wordmark'
import { Button } from '@/components/ui/button'
import { Field, FieldHint } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  type AuthConfig,
  AuthError,
  fetchAuthConfig,
  type HarvisUser,
  MIN_PASSWORD_LENGTH,
  NOTE_TO_HOST_MAX,
  probeSession,
  signIn,
  signOut,
  signUp
} from '@/lib/harvis-session'
import { AlertTriangle, ArrowRight, Clock, Eye, EyeOff, Loader2, LogOut, RefreshCw } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { asciiPlaces } from '@/store/ascii-places'

type Mode = 'signin' | 'signup' | 'claim'
type FieldName = NonNullable<AuthError['field']>

// The app-wide input border is a 4-7% tint, made for fields that sit in busy
// panels. Alone on this screen the empty fields vanished, so this screen raises it.
const SURFACE =
  'fixed inset-0 grid grid-cols-1 bg-(--ui-chat-surface-background) [--dt-input-border:28%] min-[900px]:grid-cols-[minmax(20rem,0.9fr)_minmax(0,1.1fr)]'

const CARD = 'w-full rounded-xl border border-(--stroke-nous) bg-(--ui-chat-bubble-background) shadow-nous'

const LOGO = `${import.meta.env.BASE_URL}harvis-logo.png`

/**
 * The full-screen frame both the sign-in and the "not answering" screens share:
 * on a wide screen a brand panel (logo, the cycling HARVIS, what it is) beside
 * the form; on a narrow one just the robot above it.
 */
function Frame({ children, overlay }: { children: ReactNode; overlay?: boolean }) {
  return (
    <div
      className={cn(
        SURFACE,
        overlay ? 'z-(--z-setup) bg-(--ui-chat-surface-background)/92 backdrop-blur-md' : 'z-(--z-setup)'
      )}
      data-glass-opaque=""
    >
      {asciiPlaces.has('signin-full') && <AsciiField className="absolute inset-0" />}
      <aside className="relative hidden min-w-0 flex-col justify-between gap-8 overflow-hidden border-r border-(--stroke-nous) bg-(--ui-chat-bubble-background) px-12 py-10 min-[900px]:flex">
        {asciiPlaces.has('signin') && <AsciiField className="absolute inset-0" />}
        <div className="relative flex items-center gap-2.5 text-[0.9375rem] font-semibold text-foreground">
          <img alt="" className="size-7" src={LOGO} />
          Harvis
        </div>
        <HarvisWordmark className="harvis-cycle-brand relative" />
        <p className="relative max-w-[20rem] text-[0.9375rem] leading-6 text-(--ui-text-tertiary)">
          Agents, models and memory that run on your own machine.
        </p>
      </aside>
      <div className="relative flex min-w-0 flex-col items-center justify-center-safe overflow-y-auto px-4 py-10">
        <div className="flex w-full max-w-[24rem] flex-col items-start gap-6">
          <img alt="Harvis" className="size-12 min-[900px]:hidden" src={LOGO} />
          {children}
        </div>
      </div>
    </div>
  )
}

const COPY: Record<Mode, { title: string; description: string; submit: string; busy: string }> = {
  signin: {
    title: 'Sign in to Harvis',
    description: 'Use the email and password you made for this Harvis.',
    submit: 'Sign in',
    busy: 'Signing in…'
  },
  signup: {
    title: 'Create your Harvis account',
    description: 'Your chats, files and settings stay on this Harvis.',
    submit: 'Create account',
    busy: 'Creating account…'
  },
  claim: {
    title: 'Set up this Harvis',
    description: 'No one has signed up yet. The account you make now is the admin.',
    submit: 'Create admin account',
    busy: 'Setting up…'
  }
}

// Sign-up on a server where the admin approves new accounts.
const APPROVAL_COPY = {
  description: 'The host lets new people in. Sign up, and Harvis opens as soon as they approve you.'
}

const EXPIRED_COPY = {
  title: 'Your session ended',
  description: 'Sign in again to carry on. Nothing on this page was lost.'
}

function PasswordInput({
  autoComplete,
  id,
  invalid,
  onChange,
  value
}: {
  autoComplete: 'current-password' | 'new-password'
  id: string
  invalid: boolean
  onChange: (value: string) => void
  value: string
}) {
  const [shown, setShown] = useState(false)

  return (
    <Input
      aria-invalid={invalid || undefined}
      autoComplete={autoComplete}
      id={id}
      name={autoComplete === 'new-password' ? 'new-password' : 'password'}
      onChange={e => onChange(e.target.value)}
      required
      size="lg"
      suffix={
        <button
          aria-label={shown ? 'Hide password' : 'Show password'}
          className="pointer-events-auto -mr-1 grid size-6 cursor-pointer place-items-center rounded-[4px] text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          onClick={() => setShown(s => !s)}
          type="button"
        >
          {shown ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
        </button>
      }
      type={shown ? 'text' : 'password'}
      value={value}
    />
  )
}

export function SignInScreen({
  expired = false,
  previousUser
}: {
  expired?: boolean
  previousUser?: HarvisUser | null
}) {
  const ids = useId()
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [mode, setMode] = useState<Mode>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState(previousUser?.email ?? '')
  const [password, setPassword] = useState('')
  const [setupCode, setSetupCode] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; field?: FieldName } | null>(null)
  const firstField = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true

    fetchAuthConfig()
      .then(c => {
        if (!live) {
          return
        }

        setConfig(c)

        if (c.onboarding && !expired) {
          setMode('claim')
        }
      })
      .catch(() => {
        // Sign-in still works without the config; only sign-up is hidden.
        if (live) {
          setConfig({ onboarding: false, signupEnabled: false, setupCodeRequired: false, signupApproval: false })
        }
      })

    return () => {
      live = false
    }
  }, [expired])

  useEffect(() => {
    firstField.current?.focus()
  }, [mode, config])

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
    setPassword('')
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()

    if (busy) {
      return
    }

    setBusy(true)
    setError(null)

    try {
      // Success publishes the session; the gate takes it from there.
      if (mode === 'signin') {
        await signIn(email, password)
      } else {
        await signUp({
          name,
          email,
          password,
          setupCode: mode === 'claim' ? setupCode : undefined,
          noteToHost: mode === 'signup' ? note : undefined
        })
      }
    } catch (err) {
      if (err instanceof AuthError) {
        setError({ message: err.message, field: err.field })
      } else {
        setError({ message: err instanceof Error ? err.message : String(err) })
      }

      setBusy(false)
    }
  }

  const copy = COPY[mode]
  const title = expired && mode === 'signin' ? EXPIRED_COPY.title : copy.title
  const waits = mode === 'signup' && Boolean(config?.signupApproval)
  const description =
    expired && mode === 'signin' ? EXPIRED_COPY.description : waits ? APPROVAL_COPY.description : copy.description
  const needsName = mode !== 'signin'
  const needsCode = mode === 'claim' && Boolean(config?.setupCodeRequired)
  const canSignUp = Boolean(config?.signupEnabled) && !config?.onboarding
  const fieldError = (field: FieldName) => (error?.field === field ? error.message : null)

  const id = (field: string) => `${ids}-${field}`

  return (
    <Frame overlay={expired}>
      <div className="w-full">
        {/* Changing the key replays the glitch-in whenever the form switches. */}
        <form
          aria-describedby={`${id('description')}`}
          aria-labelledby={`${id('title')}`}
          className="harvis-glitch-in grid gap-5"
          key={mode}
          method="post"
          noValidate
          onSubmit={submit}
        >
          <header className="grid gap-1">
            <h1 className="text-[1.375rem] font-semibold tracking-tight text-foreground" id={id('title')}>
              {title}
            </h1>
            <p className="text-[0.875rem] leading-5 text-(--ui-text-tertiary)" id={id('description')}>
              {description}
            </p>
          </header>

          <div className="grid gap-4">
            {needsName && (
              <Field htmlFor={id('name')} label="Your name">
                <Input
                  aria-invalid={Boolean(fieldError('name')) || undefined}
                  autoCapitalize="words"
                  autoComplete="name"
                  id={id('name')}
                  name="name"
                  onChange={e => setName(e.target.value)}
                  ref={firstField}
                  required
                  size="lg"
                  value={name}
                />
                {fieldError('name') && <FieldHint error>{fieldError('name')}</FieldHint>}
              </Field>
            )}

            <Field htmlFor={id('email')} label="Email">
              <Input
                aria-invalid={Boolean(fieldError('email')) || undefined}
                autoComplete={mode === 'signin' ? 'username' : 'email'}
                id={id('email')}
                inputMode="email"
                name="email"
                onChange={e => setEmail(e.target.value)}
                ref={needsName ? undefined : firstField}
                required
                size="lg"
                type="email"
                value={email}
              />
              {fieldError('email') && <FieldHint error>{fieldError('email')}</FieldHint>}
            </Field>

            <Field htmlFor={id('password')} label="Password">
              <PasswordInput
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                id={id('password')}
                invalid={Boolean(fieldError('password'))}
                onChange={setPassword}
                value={password}
              />
              {fieldError('password') ? (
                <FieldHint error>{fieldError('password')}</FieldHint>
              ) : (
                mode !== 'signin' && <FieldHint>At least {MIN_PASSWORD_LENGTH} characters.</FieldHint>
              )}
            </Field>

            {waits && (
              <Field htmlFor={id('note')} label="Note to the host">
                <Input
                  id={id('note')}
                  maxLength={NOTE_TO_HOST_MAX}
                  name="note-to-host"
                  onChange={e => setNote(e.target.value)}
                  placeholder="Who you are, e.g. Jane from CSE 4800"
                  size="lg"
                  value={note}
                />
                <FieldHint>Optional. The host sees it beside your sign-up.</FieldHint>
              </Field>
            )}

            {needsCode && (
              <Field htmlFor={id('code')} label="Server code">
                <Input
                  aria-invalid={Boolean(fieldError('setupCode')) || undefined}
                  autoComplete="one-time-code"
                  id={id('code')}
                  inputMode="numeric"
                  name="setup-code"
                  onChange={e => setSetupCode(e.target.value)}
                  required
                  size="lg"
                  value={setupCode}
                />
                <FieldHint error={Boolean(fieldError('setupCode'))}>
                  {fieldError('setupCode') ??
                    'The 6-digit code shown on the server when Harvis was installed.'}
                </FieldHint>
              </Field>
            )}
          </div>

          {error && !error.field && (
            <div
              className="flex items-start gap-2 rounded-lg border border-destructive/35 bg-destructive/8 px-3 py-2 text-[0.8125rem] leading-5 text-foreground"
              role="alert"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
              <span>{error.message}</span>
            </div>
          )}

          <Button className="w-full justify-center" disabled={busy} size="lg" type="submit">
            {busy ? (
              <>
                <Loader2 className="animate-spin" />
                {copy.busy}
              </>
            ) : (
              <>
                {expired && mode === 'signin' ? 'Sign in again' : copy.submit}
                <ArrowRight />
              </>
            )}
          </Button>
        </form>
      </div>

      {mode === 'signin' && canSignUp && (
        <p className="self-center text-[0.8125rem] text-(--ui-text-tertiary)">
          New to this Harvis?{' '}
          <Button onClick={() => switchMode('signup')} size="inline" type="button" variant="textStrong">
            Create an account
          </Button>
        </p>
      )}
      {mode === 'signup' && (
        <p className="self-center text-[0.8125rem] text-(--ui-text-tertiary)">
          Already have an account?{' '}
          <Button onClick={() => switchMode('signin')} size="inline" type="button" variant="textStrong">
            Sign in
          </Button>
        </p>
      )}
    </Frame>
  )
}

const RETRY_SECONDS = 5

/** Shown on a cold load when the backend does not answer at all. */
export function UnreachableScreen({ detail, onRetry }: { detail: string; onRetry: () => Promise<unknown> }) {
  const [left, setLeft] = useState(RETRY_SECONDS)
  const [trying, setTrying] = useState(false)

  useEffect(() => {
    if (trying) {
      return
    }

    if (left <= 0) {
      setTrying(true)
      void onRetry().finally(() => {
        setTrying(false)
        setLeft(RETRY_SECONDS)
      })

      return
    }

    const t = window.setTimeout(() => setLeft(s => s - 1), 1000)

    return () => window.clearTimeout(t)
  }, [left, trying, onRetry])

  return (
    <Frame>
      <div className={cn(CARD, 'harvis-glitch-in grid gap-4 p-6')} role="status">
        <header className="grid gap-1">
          <h1 className="text-[1.0625rem] font-semibold tracking-tight text-foreground">
            Harvis isn&apos;t answering yet
          </h1>
          <p className="text-[0.8125rem] leading-5 text-(--ui-text-tertiary)">
            The page loaded, but the Harvis server behind it did not reply. It may still be starting.
          </p>
        </header>
        <p className="font-mono text-[0.75rem] break-all text-(--ui-text-tertiary)">{detail}</p>
        <div className="flex items-center justify-between gap-3">
          <span className="text-[0.8125rem] text-(--ui-text-tertiary)" aria-live="polite">
            {trying ? 'Checking…' : `Trying again in ${left}s`}
          </span>
          <Button disabled={trying} onClick={() => setLeft(0)} size="sm" type="button" variant="secondary">
            <RefreshCw className={cn(trying && 'animate-spin')} />
            Retry now
          </Button>
        </div>
        <p className="border-t border-(--ui-stroke-tertiary) pt-3 text-[0.75rem] leading-5 text-(--ui-text-tertiary)">
          If this lasts more than a minute, on the machine running Harvis run{' '}
          <code className="rounded bg-(--ui-bg-quinary) px-1 py-0.5 font-mono text-foreground">
            docker compose logs backend pgsql
          </code>
        </p>
      </div>
    </Frame>
  )
}

const WAIT_POLL_MS = 10_000

/**
 * Signed up on a server where the admin approves new accounts, and not approved
 * yet. The server refuses everything else this account asks for, so the app
 * stays unmounted; this asks again every few seconds and the gate opens the app
 * as soon as the session comes back with an approved role.
 */
export function WaitingRoom({ user }: { user: HarvisUser }) {
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    const t = window.setInterval(() => void probeSession(), WAIT_POLL_MS)
    const onFocus = () => void probeSession()
    window.addEventListener('focus', onFocus)

    return () => {
      window.clearInterval(t)
      window.removeEventListener('focus', onFocus)
    }
  }, [])

  const leave = async () => {
    setLeaving(true)

    try {
      await signOut()
    } finally {
      setLeaving(false)
    }
  }

  return (
    <Frame>
      <div className={cn(CARD, 'harvis-glitch-in grid gap-4 p-6')} role="status">
        <header className="grid gap-1">
          <h1 className="flex items-center gap-2 text-[1.0625rem] font-semibold tracking-tight text-foreground">
            <Clock className="size-4 text-(--ui-text-tertiary)" />
            You&apos;re on the list
          </h1>
          <p className="text-[0.8125rem] leading-5 text-(--ui-text-tertiary)">
            The host lets new people into this Harvis. Once they approve you, it opens here by itself; you can also
            close this page and sign in later.
          </p>
        </header>
        <p className="text-[0.8125rem] text-(--ui-text-tertiary)">
          Signed up as <span className="text-foreground">{user.email || user.name}</span>
        </p>
        <div className="flex items-center justify-between gap-3 border-t border-(--ui-stroke-tertiary) pt-3">
          <span className="text-[0.75rem] text-(--ui-text-tertiary)" aria-live="polite">
            Checking every {WAIT_POLL_MS / 1000}s
          </span>
          <Button disabled={leaving} onClick={() => void leave()} size="sm" type="button" variant="secondary">
            {leaving ? <Loader2 className="animate-spin" /> : <LogOut />}
            Sign out
          </Button>
        </div>
      </div>
    </Frame>
  )
}
