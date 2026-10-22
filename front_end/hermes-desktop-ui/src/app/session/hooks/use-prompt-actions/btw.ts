import { revealTreePane } from '@/components/pane-shell/tree/store'
import { $sessionTiles, openSessionTile, patchSessionTile } from '@/store/session-states'

import type { ClientSessionState } from '../../../types'

import type { SubmitTextOptions } from './utils'

/** The `/btw <question>` result: the backend has already forked a side session
 *  from the current chat and wants `message` asked in it. */
export interface BtwResult {
  message: string
  output: string
  parentSessionId: null | string
  /** Runtime id of the forked session. */
  sessionId: string
  /** Durable id — what the sidebar and tiles key on. */
  storedSessionId: string
  title: string
}

const str = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')

export function parseBtwResult(raw: unknown): BtwResult | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const row = raw as Record<string, unknown>

  if (row.type !== 'btw') {
    return null
  }

  const sessionId = str(row.session_id)

  if (!sessionId) {
    return null
  }

  return {
    message: str(row.message),
    output: str(row.output),
    parentSessionId: str(row.parent_session_id) || null,
    sessionId,
    // Same fallback session.create consumers use: a gateway that doesn't mint a
    // separate durable id routes by the runtime id.
    storedSessionId: str(row.stored_session_id) || sessionId,
    title: str(row.title)
  }
}

export interface BtwDeps {
  refreshSessions: () => Promise<void>
  resumeStoredSession: (storedSessionId: string) => Promise<void> | void
  submitPromptText: (rawText: string, options?: SubmitTextOptions) => Promise<boolean>
  updateSessionState: (
    sessionId: string,
    updater: (state: ClientSessionState) => ClientSessionState,
    storedSessionId?: string | null
  ) => ClientSessionState
}

/**
 * Open the side session beside the current chat and ask it the question.
 *
 * It opens as a tab, never in main: the point of /btw is to ask without
 * leaving the conversation (or interrupting its running turn). The tile is
 * bound to the runtime the backend already minted so it doesn't resume a second
 * copy. If no tile materialises, fall back to selecting the session normally —
 * the question is sent either way, so the answer is waiting wherever the user
 * opens it.
 */
export async function openBtwSession(result: BtwResult, deps: BtwDeps): Promise<'selected' | 'tile'> {
  const { message, sessionId, storedSessionId } = result
  const { refreshSessions, resumeStoredSession, submitPromptText, updateSessionState } = deps

  // Bind runtime ↔ stored id in the cache before anything mounts against it.
  updateSessionState(sessionId, state => state, storedSessionId)

  let opened: 'selected' | 'tile' = 'tile'

  try {
    openSessionTile(storedSessionId, 'center')
    patchSessionTile(storedSessionId, { runtimeId: sessionId })
    revealTreePane(`session-tile:${storedSessionId}`)

    if (!$sessionTiles.get().some(tile => tile.storedSessionId === storedSessionId)) {
      throw new Error('session tile did not open')
    }
  } catch {
    opened = 'selected'

    try {
      await resumeStoredSession(storedSessionId)
    } catch {
      // Not selectable yet (a brand-new session has no persisted row until its
      // first turn). The question still goes out below.
    }
  }

  // List the new session now and again once the question has persisted a row —
  // an unused session is hidden from the list until its first turn lands.
  void refreshSessions().catch(() => undefined)

  if (message) {
    await submitPromptText(message, { sessionId, storedSessionId })
    void refreshSessions().catch(() => undefined)
  }

  return opened
}
