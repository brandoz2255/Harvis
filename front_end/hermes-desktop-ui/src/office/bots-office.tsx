// The BOTS tab's office: the signed-in account's real roster drawn as the Office 3D
// office (MIT, see ./LICENSE). A working bot sits at its desk, an idle one is in the
// lounge, an offline one leaves its desk empty, and a bot we cannot see says so.
// Clicking a desk or a bot opens that bot's chat. The account id keys the view, so an
// account switch never shows the previous account's bots.
import { useStore } from '@nanostores/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { $session } from '@/lib/harvis-session'
import { leaveBotsForChats } from '@/plugins/hermes-bots/bots-home'
import { $botMeta, botRosterKey, useRoster } from '@/plugins/hermes-bots/data'
import { openRosterBot } from '@/plugins/hermes-bots/roster-actions'
import type { RosterRow } from '@/plugins/hermes-bots/types'
import { $activeGatewayProfile } from '@/store/profile'
import { $gatewayState } from '@/store/session'

import { OfficeCanvas } from './office-canvas'
import { officeCounts, officeEntries } from './office-roster'

function isSameAccount(accountId: string) {
  const current = $session.get()

  return current.status === 'signed-in' && current.user.id === accountId
}

export function BotsOffice() {
  const session = useStore($session)
  const accountId = session.status === 'signed-in' ? session.user.id : ''

  return accountId ? <AccountOffice accountId={accountId} key={accountId} /> : null
}

function AccountOffice({ accountId }: { accountId: string }) {
  const isCurrent = () => isSameAccount(accountId)
  const { data, isError, isLoading } = useRoster(accountId, isCurrent)
  const gatewayState = useStore($gatewayState)
  const activeProfile = (useStore($activeGatewayProfile) || 'default').trim() || 'default'
  const meta = useStore($botMeta)
  const [selectedKey, setSelectedKey] = useState('')
  const opening = useRef(false)

  // Busy fades after the activity window with no new roster data, so re-read on a clock.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const rows: RosterRow[] = data?.profiles ?? []
  const entries = useMemo(
    () => officeEntries(rows, { activeProfile, gatewayState, meta, now }),
    [rows, activeProfile, gatewayState, meta, now]
  )
  const counts = officeCounts(entries)
  const selectedIndex = entries.findIndex(e => e.key === selectedKey)

  const pick = (entry: null | { key: string }) => {
    if (!entry) {
      setSelectedKey('')
      return
    }
    setSelectedKey(entry.key)
    const row = isCurrent() ? rows.find(r => botRosterKey(r) === entry.key) : undefined
    if (!row || opening.current) return
    opening.current = true
    void openRosterBot(row, { isCurrent }).finally(() => {
      opening.current = false
    })
  }

  return (
    <div className="absolute inset-0 flex flex-col bg-(--ui-chat-surface-background)" data-slot="bots-office">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 pb-1 text-xs text-(--ui-text-secondary)">
        <button
          className="-ml-1.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-(--ui-text-secondary) hover:bg-[rgba(127,127,127,0.18)] hover:text-(--ui-text-primary)"
          onClick={leaveBotsForChats}
          title="Leave the Bots tab and go back to your chats"
          type="button"
        >
          <span aria-hidden>←</span> Chats
        </button>
        <span className="font-medium text-(--ui-text-primary)">Office</span>
        <span className="contents" role="status">
          <span>{counts.busy} working</span>
          <span>{counts.idle} idle</span>
          <span>{counts.offline} offline</span>
          {counts.unknown > 0 && <span>{counts.unknown} status unknown</span>}
        </span>
        <span className="ml-auto text-(--ui-text-tertiary)">Dashed ~ bubbles are made-up chatter, not real messages.</span>
      </div>
      <div className="relative min-h-0 flex-1">
        {entries.length > 0 ? (
          <OfficeCanvas entries={entries} onPick={pick} selectedIndex={selectedIndex} />
        ) : (
          <div className="grid h-full place-items-center text-sm text-(--ui-text-tertiary)">
            {isLoading ? 'Loading your bots…' : isError ? 'Could not load your bots.' : 'No bots yet. Add one in the Bots pane.'}
          </div>
        )}
      </div>
    </div>
  )
}
