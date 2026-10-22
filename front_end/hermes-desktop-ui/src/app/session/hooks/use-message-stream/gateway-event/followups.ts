import { parseFollowups, setSessionFollowups } from '@/store/followups'

import type { GatewayEventContext } from './types'

/** `harvis.followups` — the backend's suggested next steps for the turn that
 *  is ending. An empty or malformed list clears the session's cards. */
export function handleFollowupsEvent(ctx: GatewayEventContext): boolean {
  if (ctx.event.type !== 'harvis.followups') {
    return false
  }

  if (ctx.sessionId) {
    setSessionFollowups(ctx.sessionId, parseFollowups(ctx.payload?.items))
  }

  return true
}
