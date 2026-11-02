import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Link, Loader2 } from '@/lib/icons'
import { notify } from '@/store/notifications'

import {
  disconnectLinkedAgent,
  fetchLinkedAgent,
  type LinkedAgentId,
  linkedAgentState,
  type LinkedAgentState,
  saveLinkedAgent,
  verifyLinkedAgent
} from './harvis-api'
import { ListRow, Pill, SettingsSection } from './primitives'

const AGENTS: readonly {
  badge: string
  badgeTone: 'muted' | 'primary'
  description: string
  id: LinkedAgentId
  label: string
  placeholder: string
  tokenLabel: string
}[] = [
  {
    badge: 'Recommended',
    badgeTone: 'primary',
    description: 'Chat with a Hermes Agent you already run. Paste its API server address and key.',
    id: 'hermes',
    label: 'Hermes (external)',
    placeholder: 'http://host:8642',
    tokenLabel: 'Hermes API key'
  },
  {
    badge: 'Optional, legacy',
    badgeTone: 'muted',
    description:
      'Your own OpenClaw gateway, the address you use for it (port 18789 by default). Turn on its OpenAI-compatible HTTP API first.',
    id: 'openclaw',
    label: 'OpenClaw (external)',
    placeholder: 'http://host:18789',
    tokenLabel: 'OpenClaw gateway token'
  }
]

const STATE_PILL: Record<LinkedAgentState, { label: string; tone: 'muted' | 'primary' | 'warn' }> = {
  error: { label: 'Verification failed', tone: 'warn' },
  linked: { label: 'Linked', tone: 'primary' },
  not_linked: { label: 'Not linked', tone: 'muted' },
  saved: { label: 'Saved, not verified', tone: 'warn' }
}

const linkedAgentKey = (id: LinkedAgentId) => ['harvis', 'settings', 'linked-agent', id] as const

/**
 * One agent link: address + token, Verify, Disconnect. The token field is write-only: it starts
 * empty every time, and a saved one shows only as the placeholder. Verify saves what is typed
 * first, so there is no separate Save step to forget.
 */
function LinkedAgentForm({ agent }: { agent: (typeof AGENTS)[number] }) {
  const queryClient = useQueryClient()
  const status = useQuery({ queryFn: () => fetchLinkedAgent(agent.id), queryKey: linkedAgentKey(agent.id) })
  const saved = status.data
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState<'' | 'disconnect' | 'verify'>('')
  const [error, setError] = useState('')

  useEffect(() => {
    setUrl(current => current || saved?.url || '')
  }, [saved?.url])

  const refresh = () => queryClient.invalidateQueries({ queryKey: linkedAgentKey(agent.id) })

  const verify = async () => {
    setBusy('verify')
    setError('')

    try {
      if (url.trim() !== (saved?.url ?? '') || token.trim()) {
        await saveLinkedAgent(agent.id, url.trim(), token)
        setToken('')
      }

      const result = await verifyLinkedAgent(agent.id)

      if (result.ok) {
        notify({ kind: 'success', message: 'It answered and the token checked out.', title: `${agent.label} linked` })
      } else {
        setError(result.error || 'Could not verify it.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
      void refresh()
    }
  }

  const disconnect = async () => {
    setBusy('disconnect')
    setError('')

    try {
      await disconnectLinkedAgent(agent.id)
      setUrl('')
      setToken('')
      notify({ kind: 'info', message: 'The saved address and token were removed.', title: `${agent.label} unlinked` })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
      void refresh()
    }
  }

  const state = linkedAgentState(saved)
  const pill = STATE_PILL[state]
  const lastError = error || (state === 'error' ? saved?.last_error : null)

  return (
    <ListRow
      action={
        <form
          className="grid gap-1.5"
          onSubmit={event => {
            event.preventDefault()

            if (url.trim()) {
              void verify()
            }
          }}
        >
          <Input
            aria-label={`${agent.label} address`}
            autoComplete="off"
            onChange={event => setUrl(event.target.value)}
            placeholder={agent.placeholder}
            value={url}
          />
          <Input
            aria-label={agent.tokenLabel}
            autoComplete="off"
            onChange={event => setToken(event.target.value)}
            placeholder={saved?.token_saved ? 'Token saved. Paste a new one to replace it' : 'Token'}
            type="password"
            value={token}
          />
          <div className="flex gap-1.5">
            <Button disabled={!url.trim() || busy !== ''} size="sm" type="submit">
              {busy === 'verify' && <Loader2 className="animate-spin" />}
              Verify
            </Button>
            {saved?.url && (
              <Button disabled={busy !== ''} onClick={() => void disconnect()} size="sm" type="button" variant="ghost">
                {busy === 'disconnect' && <Loader2 className="animate-spin" />}
                Disconnect
              </Button>
            )}
          </div>
          {lastError && <p className="text-xs text-destructive">{lastError}</p>}
        </form>
      }
      description={agent.description}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {agent.label}
          <Pill tone={agent.badgeTone}>{agent.badge}</Pill>
          {status.isLoading ? null : <Pill tone={pill.tone}>{pill.label}</Pill>}
        </span>
      }
    />
  )
}

/** Hermes and OpenClaw instances the person already runs, linked by address and token. */
export function LinkedAgentsSection() {
  return (
    <SettingsSection icon={Link} title="Linked agents">
      <p className="mb-1 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
        Hermes is the recommended agent. Link your own OpenClaw only if you already run one. Tokens are stored encrypted
        on the Harvis server and are never shown again.
      </p>
      <div className="divide-y">
        {AGENTS.map(agent => (
          <LinkedAgentForm agent={agent} key={agent.id} />
        ))}
      </div>
    </SettingsSection>
  )
}
