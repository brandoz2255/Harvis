import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Cloud, ExternalLink, KeyRound, Loader2, Terminal } from '@/lib/icons'
import { cn } from '@/lib/utils'
import { notify, notifyError } from '@/store/notifications'

import {
  type CodingEngine,
  connectCredential,
  type CredentialStatus,
  disconnectCredential,
  fetchEngines,
  fetchFreeProviders,
  NO_KEY
} from './harvis-api'
import { EndpointEditor } from './endpoint-editor'
import { ModelSourcesSection, modelSourcesKey } from './harvis-model-sources'
import { ListRow, ListRowSkeleton, Pill, SettingsContent, SettingsSection } from './primitives'

const freeKey = ['harvis', 'settings', 'free-providers'] as const
const enginesKey = ['harvis', 'settings', 'engines'] as const

function CredentialPill({ auth }: { auth: CredentialStatus | null | undefined }) {
  if (auth?.verified) {
    return <Pill tone="primary">Connected</Pill>
  }

  if (auth?.saved) {
    return <Pill tone="warn">Saved, not verified</Pill>
  }

  return <Pill>Not connected</Pill>
}

/**
 * Paste a key and Harvis checks it with the vendor. The server stores it either
 * way (a failed one is kept with its error so it can be re-checked); the key
 * never comes back to the browser, the row only learns "connected".
 *
 * A key-optional provider (a server the user runs) connects with the field
 * empty: the stand-in NO_KEY is stored and the check is reachability only.
 */
function CredentialForm({
  auth,
  engine,
  keyOptional = false,
  label,
  onChanged,
  oauth = false
}: {
  auth: CredentialStatus | null | undefined
  engine: string
  keyOptional?: boolean
  label: string
  onChanged: () => void
  oauth?: boolean
}) {
  const [value, setValue] = useState('')
  const [mode, setMode] = useState(auth?.auth_mode === 'oauth_token' ? 'oauth_token' : 'api_key')
  const [busy, setBusy] = useState<'' | 'connect' | 'disconnect'>('')
  const [error, setError] = useState('')

  const connect = async () => {
    setBusy('connect')
    setError('')

    try {
      const credential = value.trim() || (keyOptional ? NO_KEY : '')
      const result = await connectCredential(engine, credential, mode)

      if (!result.ok) {
        setError(result.error || (credential === NO_KEY ? 'Could not reach it.' : 'The key did not work.'))
        onChanged()

        return
      }

      setValue('')
      notify({
        kind: 'success',
        message: credential === NO_KEY ? 'Reachable; connected without a key.' : 'The key checked out and is saved.',
        title: `${label} connected`
      })
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const disconnect = async () => {
    setBusy('disconnect')

    try {
      await disconnectCredential(engine)
      notify({ kind: 'info', message: 'The saved key was removed.', title: `${label} disconnected` })
      onChanged()
    } catch (err) {
      notifyError(err, `Could not disconnect ${label}`)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="grid gap-1.5">
      {oauth && (
        <div className="flex gap-1 text-xs">
          {(['api_key', 'oauth_token'] as const).map(m => (
            <button
              className={cn(
                'rounded px-2 py-0.5',
                mode === m ? 'bg-(--ui-bg-tertiary) text-foreground' : 'text-(--ui-text-tertiary) hover:text-foreground'
              )}
              key={m}
              onClick={() => setMode(m)}
              type="button"
            >
              {m === 'api_key' ? 'API key' : 'Subscription token'}
            </button>
          ))}
        </div>
      )}
      <form
        className="flex gap-1.5"
        onSubmit={event => {
          event.preventDefault()

          if (value.trim() || keyOptional) {
            void connect()
          }
        }}
      >
        <Input
          aria-label={`${label} key`}
          autoComplete="off"
          className="min-w-0 flex-1"
          onChange={event => setValue(event.target.value)}
          placeholder={auth?.saved ? 'Paste a new key to replace' : keyOptional ? 'Key (optional)' : 'Paste key'}
          type="password"
          value={value}
        />
        <Button disabled={(!value.trim() && !keyOptional) || busy !== ''} size="sm" type="submit">
          {busy === 'connect' && <Loader2 className="animate-spin" />}
          Connect
        </Button>
        {auth?.saved && (
          <Button disabled={busy !== ''} onClick={() => void disconnect()} size="sm" type="button" variant="ghost">
            Disconnect
          </Button>
        )}
      </form>
      {(error || auth?.last_error) && (
        <p className="text-xs text-destructive">{error || `Last check failed: ${auth?.last_error}`}</p>
      )}
    </div>
  )
}

/** Where Harvis gets its models: the local Ollama, cloud keys set on the server, and free hosted tiers. */
export function HarvisProvidersSettings() {
  const queryClient = useQueryClient()
  const free = useQuery({ queryFn: fetchFreeProviders, queryKey: freeKey })

  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: freeKey })
    void queryClient.invalidateQueries({ queryKey: modelSourcesKey })
  }

  return (
    <SettingsContent>
      <ModelSourcesSection />

      <SettingsSection icon={Cloud} meta="Your own key" title="Free hosted models">
        <p className="mb-1 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          Each of these has a free tier. Get a key from the provider, paste it here, and Harvis checks it with the
          provider and stores it encrypted.
        </p>
        {free.isLoading ? (
          <ListRowSkeleton />
        ) : free.error ? (
          <p className="py-3 text-sm text-destructive">Could not load free providers: {String(free.error)}</p>
        ) : (
          <div className="divide-y">
            {(free.data ?? []).map(p =>
              p.key_optional ? (
                <ListRow
                  below={
                    <EndpointEditor
                      endpointId={p.endpoint_id ?? p.id}
                      name={p.label}
                      onChanged={changed}
                      optionalKey
                      placeholder={p.base_url || 'http://host:port/v1'}
                      saved={p.endpoint}
                    />
                  }
                  description={
                    <span className="flex flex-wrap items-center gap-x-2">
                      <span>{p.note}</span>
                      <a
                        className="inline-flex items-center gap-0.5 text-primary hover:underline"
                        href={p.console_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open its dashboard <ExternalLink className="size-3" />
                      </a>
                      <span className="text-(--ui-text-tertiary)">
                        Enter the address Harvis can reach it at (suggested: {p.base_url}), then Test connection.
                      </span>
                    </span>
                  }
                  key={p.id}
                  title={
                    <span className="flex items-center gap-2">
                      {p.label} {p.endpoint ? <Pill tone="primary">Saved</Pill> : <Pill>Not connected</Pill>}
                    </span>
                  }
                  wide
                />
              ) : (
                <ListRow
                  action={<CredentialForm auth={p.auth} engine={p.id} label={p.label} onChanged={changed} />}
                  description={
                    <span className="flex flex-wrap items-center gap-x-2">
                      <span>{p.note}</span>
                      <a
                        className="inline-flex items-center gap-0.5 text-primary hover:underline"
                        href={p.console_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Get a key <ExternalLink className="size-3" />
                      </a>
                      {p.base_url && <span className="font-mono text-(--ui-text-tertiary)">{p.base_url}</span>}
                    </span>
                  }
                  key={p.id}
                  title={
                    <span className="flex items-center gap-2">
                      {p.label} <CredentialPill auth={p.auth} />
                    </span>
                  }
                />
              )
            )}
          </div>
        )}
      </SettingsSection>
    </SettingsContent>
  )
}

function engineState(engine: CodingEngine): { label: string; tone: 'muted' | 'primary' | 'warn' } {
  if (engine.state === 'running') {
    return { label: 'Running', tone: 'primary' }
  }

  if (engine.state === 'missing') {
    return { label: 'Not installed', tone: 'muted' }
  }

  return { label: engine.state === 'unknown' ? 'Unknown' : 'Stopped', tone: 'warn' }
}

/** The coding agents a workspace run can hand work to, and the keys they need. */
export function CodingEnginesSettings() {
  const queryClient = useQueryClient()
  const engines = useQuery({ queryFn: fetchEngines, queryKey: enginesKey })

  return (
    <SettingsContent>
      <SettingsSection
        aside={
          <Button onClick={() => void engines.refetch()} size="sm" variant="ghost">
            {engines.isFetching ? <Loader2 className="animate-spin" /> : null}
            Check again
          </Button>
        }
        icon={Terminal}
        title="Coding engines"
      >
        <p className="mb-1 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
          In Agent or Team mode, Harvis can hand coding steps to one of these. Each runs in its own container inside the
          workspace sandbox.
        </p>
        {engines.isLoading ? (
          <ListRowSkeleton />
        ) : engines.error ? (
          <p className="py-3 text-sm text-destructive">Could not load engines: {String(engines.error)}</p>
        ) : (
          <div className="divide-y">
            {(engines.data ?? []).map(engine => {
              const state = engineState(engine)

              return (
                <ListRow
                  action={
                    engine.needs_key ? (
                      <CredentialForm
                        auth={engine.auth}
                        engine={engine.id}
                        label={engine.label}
                        oauth={engine.supports_oauth}
                        onChanged={() => void queryClient.invalidateQueries({ queryKey: enginesKey })}
                      />
                    ) : (
                      <span className="text-xs text-(--ui-text-tertiary)">No key needed</span>
                    )
                  }
                  description={engine.description}
                  hint={engine.hint ?? undefined}
                  key={engine.id}
                  title={
                    <span className="flex flex-wrap items-center gap-2">
                      {engine.label}
                      <Pill tone={state.tone}>{state.label}</Pill>
                      {engine.needs_key && <CredentialPill auth={engine.auth} />}
                    </span>
                  }
                />
              )
            })}
          </div>
        )}
      </SettingsSection>
      <p className="flex items-center gap-1.5 text-xs text-(--ui-text-tertiary)">
        <KeyRound className="size-3.5" /> Keys are stored encrypted on the Harvis server and are never shown again.
      </p>
    </SettingsContent>
  )
}
