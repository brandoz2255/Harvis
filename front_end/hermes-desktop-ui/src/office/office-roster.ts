import { botAppearance } from '@/plugins/hermes-bots/avatar'
import { $botMeta, botActivitySession, botRosterKey } from '@/plugins/hermes-bots/data'
import { botRosterMeta } from '@/plugins/hermes-bots/routing'
import { activeBots } from '@/plugins/hermes-bots/row-helpers'
import type { BotMeta, RosterRow } from '@/plugins/hermes-bots/types'

import type { OfficeEntry, OfficeState } from './render/office'

/** What the roster can honestly say about a bot right now. */
export function officeState(row: RosterRow, active: boolean): OfficeState {
  if (row.ghost) return 'offline'
  // A missing or unreachable source means we cannot see this bot, not that it stopped.
  if (row.sourceMissing || row.sourceReachable === false) return 'unknown'

  return active ? 'busy' : 'idle'
}

/** The title of the session a working bot is in, only if the roster carries one. */
function taskTitle(row: RosterRow): null | string {
  const session = botActivitySession(row)

  if (!session || !('title' in session || 'root_title' in session)) return null
  const title = ('title' in session && session.title) || ('root_title' in session && session.root_title) || ''

  return title.trim() || null
}

export interface OfficeRosterContext {
  activeProfile?: string
  gatewayState?: string
  meta?: Record<string, BotMeta>
  now?: number
}

/** One office entry per roster row, in roster order, keyed by source-qualified identity. */
export function officeEntries(rows: readonly RosterRow[], ctx: OfficeRosterContext = {}): OfficeEntry[] {
  const now = ctx.now ?? Date.now()
  const active = new Set(activeBots([...rows], ctx.activeProfile ?? '', ctx.gatewayState ?? '', now).map(botRosterKey))
  const meta = ctx.meta ?? $botMeta.get()

  return rows.map(row => {
    const key = botRosterKey(row)
    const state = officeState(row, active.has(key))
    const last = botActivitySession(row)?.last_active

    return {
      key,
      profile: key,
      display_name: (row.display_name || row.name).slice(0, 24),
      color: botAppearance(row.name, botRosterMeta(row, meta)).color || null,
      state,
      idle_since: state === 'idle' && typeof last === 'number' && Number.isFinite(last) ? last : null,
      task: state === 'busy' ? taskTitle(row) : null
    }
  })
}

export interface OfficeCounts {
  busy: number
  idle: number
  offline: number
  unknown: number
}

export function officeCounts(entries: readonly OfficeEntry[]): OfficeCounts {
  const out: OfficeCounts = { busy: 0, idle: 0, offline: 0, unknown: 0 }

  for (const e of entries) out[e.state]++

  return out
}
