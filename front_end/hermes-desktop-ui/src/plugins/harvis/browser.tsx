/**
 * Browser — the watchable Firefox on the browser runner, over
 * `/api/agents/computer/*` (python_back_end/plugins/agents/computer.py).
 * Teammates browse in it during their runs; you can watch, take the wheel, or
 * drive it yourself. The screen is noVNC on the same origin (`/agents/vnc/`),
 * so the only thing the page ever learns about the runner is the session token.
 */

import { Button, cn, Codicon, EmptyState, Input, StatusDot, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { harvisApi } from './api'

interface Health {
  ok: boolean
  headedAvailable: boolean
  reason?: string
}

export interface Session {
  sessionId: string
  agentId: null | string
  vncPath: string
  takenOver: boolean
  url?: string
  title?: string
}

const BASE = '/api/agents/computer'
export const sessionsKey = ['harvis', 'computer', 'sessions'] as const

/** Live browser sessions. Shared by the page and the dock (same query key, so
 *  one poll serves both and they never disagree about what is open). */
export const fetchSessions = () => harvisApi<{ items: Session[] }>(`${BASE}/sessions`).then(r => r.items ?? [])

/** `path` is encoded because it carries its own `?token=`. */
const vncUrl = (vncPath: string) =>
  `/agents/vnc/vnc.html?autoconnect=true&resize=scale&reconnect=true&path=${encodeURIComponent(vncPath)}`

/** noVNC's own chrome (side toolbar, "Connected (unencrypted)" banner) sits
 *  over the page; the controls above the frame replace it. Same origin, so the
 *  frame's document is ours to style. */
const VNC_CHROME_CSS = '#noVNC_control_bar_anchor, #noVNC_status { display: none !important; }'

function hideVncChrome(frame: HTMLIFrameElement) {
  try {
    const doc = frame.contentDocument

    if (doc && !doc.getElementById('harvis-vnc-chrome')) {
      const style = doc.createElement('style')
      style.id = 'harvis-vnc-chrome'
      style.textContent = VNC_CHROME_CSS
      doc.head.append(style)
    }
  } catch {
    // Cross-origin in some deployment — leave noVNC as it is.
  }
}

function withScheme(raw: string) {
  const url = raw.trim()

  if (!url) {
    return ''
  }

  if (/^https?:\/\//i.test(url)) {
    return url
  }

  return url.includes('.') && !url.includes(' ')
    ? `https://${url}`
    : `https://duckduckgo.com/?q=${encodeURIComponent(url)}`
}

export function Screen({
  session,
  onClosed,
  compact = false
}: {
  session: Session
  onClosed: () => void
  /** The dock's smaller frame; the page gives the screen the full height. */
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const [address, setAddress] = useState('')
  const [error, setError] = useState('')

  const live = useQuery({
    queryFn: () => harvisApi<Session>(`${BASE}/sessions/${session.sessionId}`),
    queryKey: ['harvis', 'computer', session.sessionId],
    refetchInterval: 3000
  })

  const view = live.data ?? session
  const taken = view.takenOver

  useEffect(() => {
    if (view.url && document.activeElement?.getAttribute('aria-label') !== 'Address') {
      setAddress(view.url)
    }
  }, [view.url])

  const act = async (path: string, body?: unknown, method = 'POST') => {
    setError('')

    try {
      await harvisApi(`${BASE}/sessions/${session.sessionId}${path}`, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body)
      })
      await queryClient.invalidateQueries({ queryKey: ['harvis', 'computer'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <form
        className="flex items-center gap-1.5"
        onSubmit={event => {
          event.preventDefault()
          const url = withScheme(address)

          if (url) {
            void act('/navigate', { url })
          }
        }}
      >
        <StatusDot tone={taken ? 'warn' : 'good'} />
        <Input
          aria-label="Address"
          className="min-w-0 flex-1"
          onChange={e => setAddress(e.target.value)}
          placeholder="Type an address or a search"
          value={address}
        />
        <Button size="sm" type="submit" variant="outline">
          Go
        </Button>
        <Button
          onClick={() => void act('/takeover', { taken: !taken })}
          size="sm"
          variant={taken ? 'default' : 'outline'}
        >
          <Codicon name={taken ? 'debug-continue' : 'hand'} size="0.8rem" />
          {taken ? 'Hand back' : 'Take over'}
        </Button>
        <Button
          aria-label="Close browser"
          onClick={async () => {
            await act('', undefined, 'DELETE')
            onClosed()
          }}
          size="sm"
          variant="ghost"
        >
          <Codicon name="close" size="0.8rem" />
        </Button>
      </form>
      <p className="text-xs text-(--ui-text-tertiary)">
        {taken
          ? 'You have the wheel. Agents wait until you hand it back.'
          : view.agentId
            ? 'A teammate is using this browser. Watch it work, or take over to click and type yourself.'
            : 'Watching. Take over to click and type in the page.'}
        {view.title ? ` Now on: ${view.title}` : ''}
      </p>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div
        className={cn(
          'relative flex-1 overflow-hidden rounded-lg border bg-black',
          compact ? 'h-64 min-h-64' : 'min-h-[28rem]',
          taken && 'ring-2 ring-amber-500/60'
        )}
      >
        <iframe
          className={cn('absolute inset-0 size-full', !taken && 'pointer-events-none')}
          key={session.sessionId}
          onLoad={event => hideVncChrome(event.currentTarget)}
          src={vncUrl(view.vncPath)}
          title="Browser screen"
        />
      </div>
    </div>
  )
}

export function BrowserPage() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<null | string>(null)
  const [address, setAddress] = useState('')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  const health = useQuery({
    queryFn: () => harvisApi<Health>(`${BASE}/health`),
    queryKey: ['harvis', 'computer', 'health']
  })

  const sessions = useQuery({
    queryFn: fetchSessions,
    queryKey: sessionsKey,
    refetchInterval: 5000
  })

  const list = sessions.data ?? []
  const current = list.find(s => s.sessionId === selected) ?? list[0]

  const start = async () => {
    setStarting(true)
    setError('')

    try {
      const s = await harvisApi<Session>(`${BASE}/sessions`, {
        method: 'POST',
        body: JSON.stringify({ url: withScheme(address) || null })
      })

      setSelected(s.sessionId)
      await queryClient.invalidateQueries({ queryKey: sessionsKey })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStarting(false)
    }
  }

  if (health.data && !health.data.headedAvailable) {
    return (
      <EmptyState
        description={health.data.reason || 'This install’s browser runner has no watchable screen.'}
        title="No browser screen here"
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-lg font-semibold">Browser</h1>
        {list.map(s => (
          <button
            className={cn(
              'rounded-md border px-2 py-0.5 text-xs',
              s.sessionId === current?.sessionId ? 'border-primary/50 bg-primary/10' : 'hover:bg-accent/50'
            )}
            key={s.sessionId}
            onClick={() => setSelected(s.sessionId)}
            type="button"
          >
            {s.agentId ? 'Teammate' : 'Yours'}
            {s.title ? `: ${s.title.slice(0, 30)}` : ''}
          </button>
        ))}
      </div>
      {current ? (
        <Screen onClosed={() => setSelected(null)} session={current} />
      ) : (
        <div className="max-w-xl space-y-3">
          <p className="text-sm text-(--ui-text-tertiary)">
            A real Firefox running on the Harvis server. Agents use it when a task needs the web, and you can watch or
            take over at any time. Signing in, paying, sending, and deleting always stop and ask you first.
          </p>
          <form
            className="flex gap-1.5"
            onSubmit={event => {
              event.preventDefault()
              void start()
            }}
          >
            <Input
              className="min-w-0 flex-1"
              onChange={e => setAddress(e.target.value)}
              placeholder="Start at an address or a search (optional)"
              value={address}
            />
            <Button disabled={starting || health.isLoading} type="submit">
              <Codicon name="globe" size="0.9rem" />
              {starting ? 'Opening…' : 'Open browser'}
            </Button>
          </form>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      )}
    </div>
  )
}
