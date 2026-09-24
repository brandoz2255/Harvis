import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Cpu, ExternalLink, Loader2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { EndpointEditor, modelSummary } from './endpoint-editor'
import { deleteUserApiKey, fetchHarvisProviders, type HarvisProviderRow, saveUserApiKey } from './harvis-api'
import { ListRow, ListRowSkeleton, Pill, SettingsSection } from './primitives'

export const modelSourcesKey = ['harvis', 'settings', 'model-sources'] as const

function statusTone(status: string): 'muted' | 'primary' | 'warn' {
  if (status === 'online') {
    return 'primary'
  }

  return status === 'offline' ? 'warn' : 'muted'
}

function statusLabel(status: string) {
  return (
    { online: 'Online', offline: 'Offline', no_key: 'No key', online_no_models: 'No models' }[status] ??
    status.replace(/_/g, ' ')
  )
}

/**
 * Local Ollama: the server's own address is shown read-only (it comes from
 * OLLAMA_URL); the editable one below is this user's copy, stored as the custom
 * endpoint `ollama` so chat can be pointed at it with "Use for chats".
 */
function LocalOllamaRow({ onChanged, row }: { onChanged: () => void; row: HarvisProviderRow }) {
  return (
    <ListRow
      action={<Pill tone={statusTone(row.status)}>{statusLabel(row.status)}</Pill>}
      below={
        <EndpointEditor
          endpointId={row.endpoint_id ?? 'local-ollama'}
          name="Local Ollama"
          onChanged={onChanged}
          placeholder="http://host.docker.internal:11434/v1"
          saved={row.endpoint}
        />
      }
      description={
        <span>
          {row.note} Server address: <span className="font-mono">{row.base_url}</span>.{' '}
          {row.status === 'online' ? modelSummary(row.models) : row.reason || 'Not reachable right now.'}
        </span>
      }
      title={row.label}
      wide
    />
  )
}

/** A key kept in the user's own key table (Kimi/Moonshot); saving verifies it with the vendor first. */
function UserApiKeyRow({ onChanged, row }: { onChanged: () => void; row: HarvisProviderRow }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState<'' | 'remove' | 'save'>('')
  const [error, setError] = useState('')
  const saved = Boolean(row.auth?.saved)

  const save = async () => {
    setBusy('save')
    setError('')

    try {
      await saveUserApiKey(row.provider_name ?? row.id, value.trim())
      setValue('')
      notify({ kind: 'success', message: 'The key checked out and is saved.', title: `${row.label} connected` })
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const remove = async () => {
    setBusy('remove')

    try {
      await deleteUserApiKey(row.provider_name ?? row.id)
      notify({ kind: 'info', message: 'The saved key was removed.', title: `${row.label} disconnected` })
      onChanged()
    } catch (err) {
      notifyError(err, `Could not disconnect ${row.label}`)
    } finally {
      setBusy('')
    }
  }

  return (
    <ListRow
      action={
        <div className="grid gap-1.5">
          <form
            className="flex gap-1.5"
            onSubmit={event => {
              event.preventDefault()

              if (value.trim()) {
                void save()
              }
            }}
          >
            <Input
              aria-label={`${row.label} key`}
              autoComplete="off"
              className="min-w-0 flex-1"
              onChange={event => setValue(event.target.value)}
              placeholder={saved ? 'Paste a new key to replace' : 'Paste key'}
              type="password"
              value={value}
            />
            <Button disabled={!value.trim() || busy !== ''} size="sm" type="submit">
              {busy === 'save' && <Loader2 className="animate-spin" />}
              Connect
            </Button>
            {saved && (
              <Button disabled={busy !== ''} onClick={() => void remove()} size="sm" type="button" variant="ghost">
                Disconnect
              </Button>
            )}
          </form>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      }
      description={
        <span className="flex flex-wrap items-center gap-x-2">
          <span>
            {row.note} {row.status === 'online' ? modelSummary(row.models) : row.reason}
          </span>
          {row.console_url && (
            <a
              className="inline-flex items-center gap-0.5 text-primary hover:underline"
              href={row.console_url}
              rel="noreferrer"
              target="_blank"
            >
              Get a key <ExternalLink className="size-3" />
            </a>
          )}
        </span>
      }
      title={
        <span className="flex items-center gap-2">
          {row.label}
          <Pill tone={saved ? 'primary' : 'muted'}>{saved ? 'Connected' : 'Not connected'}</Pill>
        </span>
      }
    />
  )
}

/** Where Harvis gets its models, each with a way to connect it; nothing here is read-only. */
export function ModelSourcesSection() {
  const queryClient = useQueryClient()
  const sources = useQuery({ queryFn: fetchHarvisProviders, queryKey: modelSourcesKey })
  const onChanged = () => void queryClient.invalidateQueries({ queryKey: modelSourcesKey })

  return (
    <SettingsSection
      aside={
        <Button onClick={() => void sources.refetch()} size="sm" variant="ghost">
          {sources.isFetching ? <Loader2 className="animate-spin" /> : null}
          Check again
        </Button>
      }
      icon={Cpu}
      title="Model providers"
    >
      {sources.isLoading ? (
        <ListRowSkeleton />
      ) : sources.error ? (
        <p className="py-3 text-sm text-destructive">Could not load providers: {String(sources.error)}</p>
      ) : (
        <div className="divide-y">
          {(sources.data ?? []).map(row =>
            row.kind === 'local' ? (
              <LocalOllamaRow key={row.id} onChanged={onChanged} row={row} />
            ) : (
              <UserApiKeyRow key={row.id} onChanged={onChanged} row={row} />
            )
          )}
        </div>
      )}
    </SettingsSection>
  )
}
