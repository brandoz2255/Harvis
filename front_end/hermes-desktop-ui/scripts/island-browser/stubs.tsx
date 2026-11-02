// Stub modules for the island browser harness. build.mjs redirects these imports here:
//   @/lib/harvis-session                   -> session atom only (no backend probing)
//   @/store/session                        -> $busy atom only
//   @/plugins/hermes-bots/data             -> useRoster: per-account rosters driven by window.__bots
//   @/plugins/hermes-bots/roster-actions   -> openRosterBot: records the opened bot in window.__botChats
//   @/themes/context                       -> a fixed theme
//   @/components/ui/codicon                -> a plain span
//   @/api/plugins                          -> never callable in the harness
import { useQuery } from '@tanstack/react-query'
import { atom } from 'nanostores'
import { createElement } from 'react'

import type { RosterRow } from '@/plugins/hermes-bots/types'

export interface SessionState {
  status: 'signed-in' | 'signed-out'
  user?: { email: string; id: string; name: string; role: string }
}

export const $session = atom<SessionState>({ status: 'signed-out' })
export const $busy = atom(false)

declare global {
  interface Window {
    __bots: Record<string, RosterRow[]>
    __botChats: string[]
  }
}

// Same contract as the real useRoster(accountId, isCurrent): the query key carries the account
// id, so a switch never shows the previous account's cached rows, and the fetch throws if the
// account changed while it was in flight. The real one asks the gateway; this one reads the
// account's rows from window.__bots, after a real macrotask so switch races are exercised.
export function useRoster(accountId?: string, isCurrent: () => boolean = () => true) {
  return useQuery({
    queryFn: async () => {
      if (!isCurrent()) throw new Error('Account changed')

      await new Promise(resolve => setTimeout(resolve, 20))

      if (!isCurrent()) throw new Error('Account changed')

      return { fetchedAt: Date.now(), profiles: (accountId && window.__bots[accountId]) || [] }
    },
    queryKey: ['island-roster', accountId, 'harness']
  })
}

// Same refusal as the real openRosterBot: a stale click (the account changed) opens nothing.
export const openRosterBot = async (bot: RosterRow, { isCurrent = (): boolean => true } = {}) => {
  if (!isCurrent()) {
    return false
  }

  window.__botChats.push(bot.name)

  return true
}

const colors = {
  background: '#0d1117',
  border: '#30363d',
  foreground: '#e6edf3',
  mutedForeground: '#7d8590',
  popover: '#161b22',
  primary: '#4a84fe',
  primaryForeground: '#161616'
}

export const useTheme = () => ({ renderedMode: 'dark' as const, theme: { colors } })

export const Codicon = ({ name }: { name: string }) => createElement('span', null, name)

export const pluginRest = async (): Promise<never> => {
  throw new Error('pluginRest must not be called in the island harness')
}
