import { Button, Codicon, host, useQuery, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { fetchSessions, Screen, type Session, sessionsKey } from './browser'

/**
 * The Browser appears when it is needed, not as a tab you keep open: while a
 * browser session is live (an agent needs the web, or you opened one) it docks
 * above the composer with the live screen, and it is gone the moment nothing is
 * browsing. "Open full view" goes to the /browser page for the big screen.
 */
export function BrowserDock() {
  const busy = useValue(host.state.busy)
  const [collapsed, setCollapsed] = useState(false)
  // Hiding is per session: a new session (the agent visiting somewhere else)
  // pops back up, the way it would in Grok, instead of staying hidden forever.
  const [hidden, setHidden] = useState<null | string>(null)

  const { data } = useQuery({
    queryFn: fetchSessions,
    queryKey: sessionsKey,
    // Watch closely while a turn runs or a browser is open; idle, just check in.
    refetchInterval: query => {
      const list = query.state.data as Session[] | undefined

      return busy || (list?.length ?? 0) > 0 ? 4000 : 20_000
    }
  })

  // An agent's session is the "it needs the web" case, so it wins the dock.
  const session = (data ?? []).find(s => s.agentId) ?? data?.[0]

  if (!session || session.sessionId === hidden) {
    return null
  }

  const heading = session.agentId ? 'Browsing for you' : 'Browser'

  return (
    <div className="mb-1.5 overflow-hidden rounded-lg border bg-(--ui-surface-raised,var(--background))">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5">
        <Codicon className="text-(--ui-text-tertiary)" name="globe" size="0.85rem" />
        <span className="shrink-0 text-xs font-medium">{heading}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-(--ui-text-tertiary)">
          {session.title || session.url || ''}
        </span>
        <Button
          aria-label={collapsed ? 'Show browser' : 'Collapse browser'}
          onClick={() => setCollapsed(!collapsed)}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name={collapsed ? 'chevron-down' : 'chevron-up'} size="0.8rem" />
        </Button>
        <Button aria-label="Open full browser" onClick={() => host.navigate('/browser')} size="icon-xs" variant="ghost">
          <Codicon name="screen-full" size="0.8rem" />
        </Button>
        <Button
          aria-label="Hide browser"
          onClick={() => setHidden(session.sessionId)}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name="close" size="0.8rem" />
        </Button>
      </div>
      {collapsed ? null : (
        <div className="flex px-2.5 pb-2.5">
          <Screen compact onClosed={() => setHidden(session.sessionId)} session={session} />
        </div>
      )}
    </div>
  )
}
