import { useStore } from '@nanostores/react'
import { type FormEvent, useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Field, FieldHint } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { $session, AuthError, changePassword, MIN_PASSWORD_LENGTH, signOut } from '@/lib/harvis-session'
import { CheckCircle2, Loader2, Lock, LogOut, User } from '@/lib/icons'
import { confirm } from '@/store/confirm'

import { ListRow, Pill, SettingsContent, SettingsSection } from './primitives'

function PasswordForm({ email }: { email: string }) {
  const ids = useId()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<{ message: string; field?: string } | null>(null)

  const mismatch = again.length > 0 && again !== next

  const submit = async (e: FormEvent) => {
    e.preventDefault()

    if (busy) {
      return
    }

    if (next !== again) {
      setError({ message: 'The new passwords do not match.', field: 'again' })

      return
    }

    setBusy(true)
    setError(null)
    setDone(false)

    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setAgain('')
      setDone(true)
    } catch (err) {
      setError(
        err instanceof AuthError
          ? { message: err.message, field: err.field }
          : { message: err instanceof Error ? err.message : String(err) }
      )
    } finally {
      setBusy(false)
    }
  }

  const fieldError = (field: string) => (error?.field === field ? error.message : null)

  return (
    <form className="grid max-w-[26rem] gap-4 py-3" method="post" noValidate onSubmit={submit}>
      {/* Lets password managers file the new password under the right account. */}
      <input autoComplete="username" className="hidden" name="username" readOnly type="email" value={email} />
      <Field htmlFor={`${ids}-current`} label="Current password">
        <Input
          aria-invalid={Boolean(fieldError('password')) || undefined}
          autoComplete="current-password"
          id={`${ids}-current`}
          onChange={e => setCurrent(e.target.value)}
          required
          type="password"
          value={current}
        />
        {fieldError('password') && <FieldHint error>{fieldError('password')}</FieldHint>}
      </Field>
      <Field htmlFor={`${ids}-new`} label="New password">
        <Input
          aria-invalid={Boolean(fieldError('newPassword')) || undefined}
          autoComplete="new-password"
          id={`${ids}-new`}
          onChange={e => setNext(e.target.value)}
          required
          type="password"
          value={next}
        />
        <FieldHint error={Boolean(fieldError('newPassword'))}>
          {fieldError('newPassword') ?? `At least ${MIN_PASSWORD_LENGTH} characters.`}
        </FieldHint>
      </Field>
      <Field htmlFor={`${ids}-again`} label="New password, again">
        <Input
          aria-invalid={mismatch || Boolean(fieldError('again')) || undefined}
          autoComplete="new-password"
          id={`${ids}-again`}
          onChange={e => setAgain(e.target.value)}
          required
          type="password"
          value={again}
        />
        {(mismatch || fieldError('again')) && <FieldHint error>The new passwords do not match.</FieldHint>}
      </Field>

      {error && !error.field && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {error.message}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button disabled={busy || !current || !next || !again || mismatch} type="submit">
          {busy ? (
            <>
              <Loader2 className="animate-spin" />
              Changing…
            </>
          ) : (
            'Change password'
          )}
        </Button>
        {done && (
          <span className="flex items-center gap-1.5 text-[0.8125rem] text-(--ui-text-tertiary)" role="status">
            <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" />
            Password changed
          </span>
        )}
      </div>
    </form>
  )
}

export function AccountSettings() {
  const session = useStore($session)
  const [leaving, setLeaving] = useState(false)

  const user = session.status === 'signed-in' ? session.user : null

  const onSignOut = async () => {
    const ok = await confirm({
      title: 'Sign out of Harvis?',
      description: 'You will go back to the sign-in screen. Running jobs keep going on the server.',
      confirmLabel: 'Sign out'
    })

    if (!ok) {
      return
    }

    setLeaving(true)
    await signOut()
  }

  return (
    <SettingsContent>
      <SettingsSection icon={User} title="Signed in as">
        <div className="divide-y">
          <ListRow
            description={user?.email}
            title={
              <span className="flex items-center gap-2">
                {user?.name || 'Unknown'}
                {user?.role === 'admin' ? <Pill tone="primary">Admin</Pill> : <Pill>Member</Pill>}
              </span>
            }
          />
          <ListRow
            action={
              <Button disabled={leaving} onClick={() => void onSignOut()} variant="outline">
                <LogOut />
                {leaving ? 'Signing out…' : 'Sign out'}
              </Button>
            }
            description="Ends this browser's session. Other devices stay signed in until their session runs out."
            title="Sign out"
          />
        </div>
      </SettingsSection>

      <SettingsSection icon={Lock} title="Password">
        <PasswordForm email={user?.email ?? ''} />
      </SettingsSection>
    </SettingsContent>
  )
}
