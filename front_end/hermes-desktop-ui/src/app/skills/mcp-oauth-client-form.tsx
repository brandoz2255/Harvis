import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import type { McpOAuthClient } from '@/hermes'

/** Where the vendor sends the person back to; shown so it can be allow-listed. */
export const mcpOAuthRedirectUrl = (): string =>
  typeof window === 'undefined' ? '' : `${window.location.origin}/hermes-api/api/mcp/oauth/callback`

/**
 * Asked for only when a service cannot register Harvis automatically (no dynamic
 * client registration). The id is not a secret; the optional secret is sent once
 * and the backend seals it at rest.
 */
export function McpOAuthClientForm({ busy, onSubmit }: { busy: boolean; onSubmit: (client: McpOAuthClient) => void }) {
  const { t } = useI18n()
  const m = t.settings.mcp
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')

  const submit = () => {
    const id = clientId.trim()

    if (!id) {
      return
    }

    const secret = clientSecret.trim()
    onSubmit(secret ? { client_id: id, client_secret: secret } : { client_id: id })
  }

  return (
    <form
      className="mt-3 grid gap-2 rounded-md border border-(--ui-stroke-quaternary) p-2"
      onSubmit={event => {
        event.preventDefault()
        submit()
      }}
    >
      <p className="text-[0.72rem] font-medium text-foreground/85">{m.clientIdTitle}</p>
      <p className="text-[0.66rem] text-muted-foreground/70">{m.clientIdHelp(mcpOAuthRedirectUrl())}</p>
      <label className="grid gap-1">
        <span className="text-[0.62rem] text-muted-foreground">{m.clientIdLabel}</span>
        <Input
          autoComplete="off"
          className="h-7 text-xs"
          onChange={event => setClientId(event.currentTarget.value)}
          value={clientId}
        />
      </label>
      <label className="grid gap-1">
        <span className="text-[0.62rem] text-muted-foreground">{m.clientSecretLabel}</span>
        <Input
          autoComplete="off"
          className="h-7 text-xs"
          onChange={event => setClientSecret(event.currentTarget.value)}
          type="password"
          value={clientSecret}
        />
      </label>
      <div className="flex justify-end">
        <Button disabled={busy || !clientId.trim()} size="xs" type="submit">
          {m.clientIdConnect}
        </Button>
      </div>
    </form>
  )
}
