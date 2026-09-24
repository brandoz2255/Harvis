import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2 } from '@/lib/icons'
import { notify, notifyError } from '@/store/notifications'

import { checkEndpoint, deleteEndpoint, type EndpointCheck, type EndpointSummary, saveEndpoint } from './harvis-api'

export function modelSummary(models: string[]) {
  if (models.length === 0) {
    return ''
  }

  return `${models.length} model${models.length === 1 ? '' : 's'}: ${models.slice(0, 6).join(', ')}${models.length > 6 ? ', …' : ''}`
}

interface EndpointEditorProps {
  /** Custom-endpoint id this server is saved under (e.g. `local-ollama`, `omniroute`). */
  endpointId: string
  name: string
  saved: EndpointSummary | null | undefined
  placeholder: string
  /** Offer an optional key field (servers that may or may not ask for one). */
  optionalKey?: boolean
  onChanged: () => void
}

/**
 * An address this user points Harvis at: test it (lists its models), save it,
 * make it the model chats use, or remove it. Saved as the user's own custom
 * endpoint, so its models show up in every model picker under `name`.
 */
export function EndpointEditor({ endpointId, name, saved, placeholder, optionalKey, onChanged }: EndpointEditorProps) {
  const [url, setUrl] = useState(saved?.base_url ?? '')
  const [key, setKey] = useState('')
  const [check, setCheck] = useState<EndpointCheck | null>(null)
  const [busy, setBusy] = useState<'' | 'check' | 'remove' | 'save'>('')

  const probe = () => checkEndpoint(name, url.trim(), key.trim() || undefined, saved ? endpointId : undefined)

  const test = async () => {
    setBusy('check')

    try {
      setCheck(await probe())
    } catch (err) {
      setCheck({ ok: false, reachable: false, models: [], message: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy('')
    }
  }

  const save = async (makeDefault: boolean) => {
    setBusy('save')

    try {
      const result = check?.ok && check.models.length > 0 ? check : await probe()

      if (!result.ok || result.models.length === 0) {
        setCheck(
          result.ok ? { ...result, ok: false, message: 'It answered, but lists no models to chat with.' } : result
        )

        return
      }

      await saveEndpoint({
        id: endpointId,
        name,
        base_url: url.trim(),
        model: saved?.model && result.models.includes(saved.model) ? saved.model : result.models[0],
        models: result.models,
        ...(key.trim() ? { api_key: key.trim() } : {}),
        make_default: makeDefault
      })
      setKey('')
      notify({
        kind: 'success',
        message: makeDefault ? `Your chats now use ${name}.` : `Its models are in the model picker under ${name}.`,
        title: `${name} saved`
      })
      onChanged()
    } catch (err) {
      notifyError(err, `Could not save ${name}`)
    } finally {
      setBusy('')
    }
  }

  const remove = async () => {
    setBusy('remove')

    try {
      await deleteEndpoint(endpointId)
      setUrl('')
      setKey('')
      setCheck(null)
      notify({ kind: 'info', message: 'Its models left the model picker.', title: `${name} removed` })
      onChanged()
    } catch (err) {
      notifyError(err, `Could not remove ${name}`)
    } finally {
      setBusy('')
    }
  }

  const idle = busy === ''

  return (
    <div className="grid gap-1.5">
      <form
        className="flex flex-wrap gap-1.5"
        onSubmit={event => {
          event.preventDefault()
          void test()
        }}
      >
        <Input
          aria-label={`${name} address`}
          autoComplete="off"
          className="min-w-0 flex-1"
          onChange={event => {
            setUrl(event.target.value)
            setCheck(null)
          }}
          placeholder={placeholder}
          value={url}
        />
        {optionalKey && (
          <Input
            aria-label={`${name} key (optional)`}
            autoComplete="off"
            className="w-44"
            onChange={event => {
              setKey(event.target.value)
              setCheck(null)
            }}
            placeholder={saved?.has_api_key ? 'Key saved; paste to replace' : 'Key (optional)'}
            type="password"
            value={key}
          />
        )}
        <Button disabled={!url.trim() || !idle} size="sm" type="submit" variant="outline">
          {busy === 'check' && <Loader2 className="animate-spin" />}
          Test connection
        </Button>
        <Button disabled={!url.trim() || !idle} onClick={() => void save(false)} size="sm" type="button">
          {busy === 'save' && <Loader2 className="animate-spin" />}
          Save
        </Button>
        <Button
          disabled={!url.trim() || !idle}
          onClick={() => void save(true)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Use for chats
        </Button>
        {saved && (
          <Button disabled={!idle} onClick={() => void remove()} size="sm" type="button" variant="ghost">
            Remove
          </Button>
        )}
      </form>
      {check && (
        <p className={check.ok ? 'text-xs text-(--ui-text-tertiary)' : 'text-xs text-destructive'}>
          {check.message}
          {check.ok && check.models.length > 0 ? ` ${modelSummary(check.models)}` : ''}
        </p>
      )}
      {saved && (
        <p className="text-xs text-(--ui-text-tertiary)">
          Saved: {saved.base_url}
          {saved.has_api_key ? ' · key saved' : ''}
          {saved.is_current ? ' · in use for your chats' : ''}
          {saved.models.length > 0 ? ` · ${modelSummary(saved.models)}` : ''}
        </p>
      )}
    </div>
  )
}
