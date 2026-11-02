// Client cache of the person's mod rows. The server owns them; this atom only
// holds the last list it sent and the helpers that refresh it after a change.
import { atom, computed } from 'nanostores'

import { $session } from '@/lib/harvis-session'
import { readKey, writeKey } from '@/lib/storage'

import { modsApi } from './api'
import type { ModRow, ModSlotName } from './types'

export const $mods = atom<ModRow[]>([])

// The island is a built-in surface of the `island` slot. It was always on before this setting
// was read, so a signed-in account with nothing stored sees it until they turn it off (Settings > Mods).
export const $islandVisible = atom(false)
// The full-screen map. The titlebar opens it from any chat, so it is not tied to the idle Bots tab.
export const $islandExplore = atom(false)
let account: string | null = null
let accountGeneration = 0
let inflight: null | Promise<void> = null
const visibilityKey = (id: string) => `hermes.desktop.islandVisible.user.${encodeURIComponent(id)}`
let loadingAccount = false

$session.subscribe(session => {
  const next = session.status === 'signed-in' && session.user.id ? session.user.id : null
  if (next === account) return
  account = next
  accountGeneration += 1
  $mods.set([])
  $islandExplore.set(false)
  inflight = null
  loadingAccount = true
  $islandVisible.set(next !== null && readKey(visibilityKey(next)) !== 'false')
  loadingAccount = false
})

$islandVisible.subscribe(visible => {
  if (!loadingAccount && account) writeKey(visibilityKey(account), String(visible))
  if (!visible) $islandExplore.set(false)
})

/** A mod may run only when it is switched on AND approved at exactly the bytes it holds now. */
export function isRunnable(row: ModRow): boolean {
  return row.status === 'on' && Boolean(row.approved_hash) && row.approved_hash === row.hash
}

/** On, approved, and with a UI — the rows a slot may mount. */
export function runnableUiMods(rows: readonly ModRow[], slot?: ModSlotName): ModRow[] {
  return rows.filter(row => isRunnable(row) && row.manifest?.ui && (!slot || row.manifest.ui.slot === slot))
}

export const $runnableUiMods = computed($mods, rows => runnableUiMods(rows))

/** Re-read the list from the server. Failures keep the last list: a flaky request must not unmount working mods. */
export function refreshMods(): Promise<void> {
  if (!account) return Promise.resolve()
  const generation = accountGeneration
  inflight ??= modsApi
    .list()
    .then(rows => {
      if (generation === accountGeneration) $mods.set(rows)
    })
    .catch(() => undefined)
    .finally(() => {
      if (generation === accountGeneration) inflight = null
    })

  return inflight
}

export function clearMods(): void {
  $mods.set([])
}

export interface ModGroup {
  /** What the person sees as "the mod": the version that is on, else the newest. */
  head: ModRow
  name: string
  /** Newer versions waiting for a decision (drafts). */
  pending: ModRow[]
}

/** Rows grouped by mod name, in list order (newest first within a name). */
export function groupByName(rows: readonly ModRow[]): ModGroup[] {
  const byName = new Map<string, ModRow[]>()

  for (const row of rows) {
    byName.set(row.name, [...(byName.get(row.name) ?? []), row])
  }

  return [...byName.entries()].map(([name, versions]) => {
    const head = versions.find(isRunnable) ?? versions.find(v => v.status === 'on') ?? versions[0]
    const pending = versions.filter(v => v !== head && v.status === 'draft' && versions.indexOf(v) < versions.indexOf(head))

    return { head, name, pending }
  })
}
