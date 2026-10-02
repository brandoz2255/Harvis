import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { Loader2, MessageCircle, Power, Users } from '@/lib/icons'
import { confirm } from '@/store/confirm'
import { notify, notifyError } from '@/store/notifications'

import {
  fetchInstanceConfig,
  fetchPeople,
  fetchServerModels,
  type Person,
  saveInstanceConfig,
  unpairContact,
  updatePerson
} from './harvis-api'
import { draftFor, lastSeen, modelChoices, patchFrom, toggleModel, usageLabel } from './people-helpers'
import { EmptyState, ListRow, ListRowSkeleton, Pill, SettingsContent, SettingsSection, ToggleRow } from './primitives'

const peopleKey = ['harvis', 'settings', 'people'] as const
const configKey = ['harvis', 'settings', 'instance-config'] as const
const modelsKey = ['harvis', 'settings', 'people-models'] as const

function Limits({ person, serverModels }: { person: Person; serverModels: string[] }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(() => draftFor(person))
  const [saving, setSaving] = useState(false)
  const { patch, error } = patchFrom(person, draft)
  const dirty = Object.keys(patch).length > 0
  const choices = modelChoices(serverModels, draft.models)

  const save = async () => {
    setSaving(true)

    try {
      await updatePerson(person.id, patch)
      await queryClient.invalidateQueries({ queryKey: peopleKey })
      notify({ kind: 'success', title: 'Limits saved', message: person.name })
    } catch (err) {
      notifyError(err, 'Could not save the limits')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3 grid max-w-[40rem] gap-4 rounded-md bg-(--ui-bg-tertiary)/50 p-3">
      <label className="grid gap-1.5">
        <span className="text-[0.8125rem] font-medium">Messages per day</span>
        <Input
          aria-invalid={Boolean(error && draft.limit.trim() && !/^\d+$/.test(draft.limit.trim())) || undefined}
          className="w-40"
          inputMode="numeric"
          onChange={e => setDraft(d => ({ ...d, limit: e.target.value }))}
          placeholder="No limit"
          value={draft.limit}
        />
        <span className="text-[0.75rem] text-(--ui-text-tertiary)">
          Blank means no limit. 0 turns chat off but keeps them signed in. Resets at midnight UTC. In a group room, each
          bot&apos;s reply counts as one message.
        </span>
      </label>

      <fieldset className="grid gap-2">
        <legend className="mb-1.5 text-[0.8125rem] font-medium">Models they can use</legend>
        <div className="flex gap-2">
          <Button
            onClick={() => setDraft(d => ({ ...d, models: null }))}
            size="sm"
            variant={draft.models === null ? 'default' : 'outline'}
          >
            Any model
          </Button>
          <Button
            onClick={() => setDraft(d => ({ ...d, models: d.models ?? [] }))}
            size="sm"
            variant={draft.models === null ? 'outline' : 'default'}
          >
            Only these
          </Button>
        </div>
        {draft.models !== null && (
          <div className="flex flex-wrap gap-1.5">
            {choices.length === 0 && (
              <span className="text-[0.75rem] text-(--ui-text-tertiary)">This server lists no models right now.</span>
            )}
            {choices.map(id => {
              const on = draft.models?.includes(id) ?? false

              return (
                <button
                  aria-pressed={on}
                  className={cn(
                    'rounded-full px-2.5 py-0.5 font-mono text-[0.72rem] transition-colors',
                    on
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-(--ui-bg-quaternary) text-(--ui-text-secondary) hover:text-foreground'
                  )}
                  key={id}
                  onClick={() => setDraft(d => ({ ...d, models: toggleModel(d.models ?? [], id) }))}
                  type="button"
                >
                  {id}
                </button>
              )
            })}
          </div>
        )}
        <span className="text-[0.75rem] text-(--ui-text-tertiary)">
          The first one picked is their default. Anything not picked is refused in chat, notebooks, workspace runs,
          scheduled jobs, mixture of agents, and fallbacks: other models on this server, cloud models from Integrations,
          teammates, and endpoints on this network. Workspace runs that would use a cloud agent run locally on a picked
          model instead. A custom endpoint on a public address with their own key is theirs to use. Paired contacts
          count toward the daily limit but use the server&apos;s own model.
        </span>
      </fieldset>

      {error && (
        <p className="text-[0.8125rem] text-destructive" role="alert">
          {error}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button disabled={!dirty || Boolean(error) || saving} onClick={() => void save()} size="sm">
          {saving && <Loader2 className="animate-spin" />}
          Save limits
        </Button>
        {dirty && (
          <Button onClick={() => setDraft(draftFor(person))} size="sm" variant="text">
            Undo changes
          </Button>
        )}
      </div>
    </div>
  )
}

function PersonRow({ person, serverModels }: { person: Person; serverModels: string[] }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: peopleKey })

  const setBlocked = async (blocked: boolean) => {
    if (blocked) {
      const ok = await confirm({
        title: `Turn off ${person.name}?`,
        description:
          'Harvis refuses their sign-in and chats right away, until you turn them back on. ' +
          'A window they already have open can still show what it loaded until it reconnects, and a ' +
          'workspace run or research already under way finishes. ' +
          'If new sign-ups are on, they could make a new account, so turn sign-ups off too. ' +
          'Their chats and files stay. Contacts paired to them stop getting answers.',
        confirmLabel: 'Turn off',
        destructive: true
      })

      if (!ok) {
        return
      }
    }

    setBusy(true)

    try {
      await updatePerson(person.id, { blocked })
      await refresh()
    } catch (err) {
      notifyError(err, blocked ? 'Could not turn them off' : 'Could not turn them back on')
    } finally {
      setBusy(false)
    }
  }

  const unpair = async (contactId: number, label: string) => {
    const ok = await confirm({
      title: `Unpair ${label}?`,
      description: `${label} stops talking to Harvis as ${person.name}. They can ask to pair again.`,
      confirmLabel: 'Unpair',
      destructive: true
    })

    if (!ok) {
      return
    }

    try {
      await unpairContact(contactId)
      await refresh()
    } catch (err) {
      notifyError(err, 'Could not unpair that contact')
    }
  }

  const limited = person.daily_message_limit !== null || person.allowed_models !== null

  return (
    <ListRow
      action={
        person.is_admin ? undefined : (
          <div className="flex flex-wrap items-center gap-2 @2xl:justify-end">
            <Button onClick={() => setOpen(o => !o)} size="sm" variant="outline">
              {open ? 'Close limits' : 'Limits'}
            </Button>
            <Button
              disabled={busy}
              onClick={() => void setBlocked(!person.blocked)}
              size="sm"
              variant={person.blocked ? 'default' : 'outline'}
            >
              {busy ? <Loader2 className="animate-spin" /> : <Power />}
              {person.blocked ? 'Turn on' : 'Turn off'}
            </Button>
          </div>
        )
      }
      below={
        <>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[0.75rem] text-(--ui-text-secondary) tabular-nums">
            <span>{usageLabel(person)}</span>
            <span>{person.messages_week} this week</span>
            <span>
              {person.chats} chat{person.chats === 1 ? '' : 's'}
            </span>
            <span>{lastSeen(person.last_active)}</span>
          </div>
          {person.paired.length > 0 && (
            <ul className="mt-2 grid gap-1">
              {person.paired.map(c => {
                const label = c.name || c.identifier

                return (
                  <li className="flex items-center gap-2 text-[0.75rem]" key={c.id}>
                    <MessageCircle className="size-3.5 text-muted-foreground" />
                    <span className="capitalize">{c.platform}</span>
                    <span className="truncate text-(--ui-text-secondary)">{label}</span>
                    {!c.enabled && <Pill>Paused</Pill>}
                    <Button onClick={() => void unpair(c.id, label)} size="inline" variant="text">
                      Unpair
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
          {open && !person.is_admin && <Limits person={person} serverModels={serverModels} />}
        </>
      }
      description={person.email}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {person.name}
          {person.is_admin && <Pill tone="primary">Admin</Pill>}
          {person.blocked && <Pill tone="warn">Turned off</Pill>}
          {!person.blocked && limited && <Pill>Limited</Pill>}
        </span>
      }
    />
  )
}

/**
 * Admin only: everyone with an account on this Harvis, what they used today,
 * the messaging contacts paired to them, and the limits the admin sets.
 */
export function PeopleSettings() {
  const queryClient = useQueryClient()
  const people = useQuery({ queryFn: fetchPeople, queryKey: peopleKey })
  const config = useQuery({ queryFn: fetchInstanceConfig, queryKey: configKey })
  const models = useQuery({ queryFn: fetchServerModels, queryKey: modelsKey, staleTime: 60_000 })
  const serverModels = (models.data?.models ?? []).map(m => m.id)
  const users = people.data?.users ?? []

  const setSignup = async (on: boolean) => {
    try {
      const next = await saveInstanceConfig({ ENABLE_SIGNUP: on })
      queryClient.setQueryData(configKey, next)
    } catch (err) {
      notifyError(err, 'Could not change sign-ups')
    }
  }

  return (
    <SettingsContent>
      <SettingsSection icon={Users} title="Joining">
        {config.isPending ? (
          <ListRowSkeleton />
        ) : (
          <ToggleRow
            checked={config.data?.ENABLE_SIGNUP ?? false}
            description="When off, only people who already have an account can sign in."
            disabled={!config.data}
            label="Allow new sign-ups"
            onChange={on => void setSignup(on)}
          />
        )}
      </SettingsSection>

      <SettingsSection icon={Users} meta={people.data ? String(users.length) : undefined} title="People">
        {people.isPending ? (
          <div className="grid gap-1">
            <ListRowSkeleton />
            <ListRowSkeleton />
          </div>
        ) : people.isError ? (
          <p className="py-3 text-[0.8125rem] text-destructive" role="alert">
            {people.error instanceof Error ? people.error.message : 'Could not load people.'}
          </p>
        ) : users.length === 0 ? (
          <EmptyState title="No accounts yet" />
        ) : (
          <div className="divide-y">
            {users.map(p => (
              <PersonRow key={p.id} person={p} serverModels={serverModels} />
            ))}
          </div>
        )}
        {models.data?.error && <p className="pt-2 text-[0.75rem] text-(--ui-text-tertiary)">{models.data.error}</p>}
      </SettingsSection>
    </SettingsContent>
  )
}
