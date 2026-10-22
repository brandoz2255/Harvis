import { atom } from 'nanostores'

import { persistBoolean, storedBoolean } from '@/lib/storage'

const TAKEOVER_KEY = 'hermes.desktop.terminalTakeover'

export const $terminalTakeover = atom(storedBoolean(TAKEOVER_KEY, false))

$terminalTakeover.subscribe(active => persistBoolean(TAKEOVER_KEY, active))

export const setTerminalTakeover = (active: boolean) => $terminalTakeover.set(active)

/** A command queued to run in the embedded terminal. The terminal pane flushes
 *  (and clears) it once its session is live, so a value set before the pane
 *  mounts still runs. Cleared after flush so a later remount can't replay it. */
export const $terminalInjection = atom<null | string>(null)

/** Open the terminal pane and run a command in it. Used to disconnect external
 *  (CLI-managed) providers, which Hermes can't clear via the API — the user
 *  sees exactly what runs instead of Hermes silently deleting their creds. */
export const runInTerminal = (command: string) => {
  const trimmed = command.trim()

  if (!trimmed) {
    return
  }

  setTerminalTakeover(true)
  $terminalInjection.set(trimmed)
}

const SESSION_PANEL_COLLAPSED_KEY = 'hermes.desktop.rightSidebar.sessionPanelCollapsed'

/** Whether this viewer folded the "This session" panel. Stored per browser. */
export const $sessionPanelCollapsed = atom(storedBoolean(SESSION_PANEL_COLLAPSED_KEY, false))

$sessionPanelCollapsed.subscribe(collapsed => persistBoolean(SESSION_PANEL_COLLAPSED_KEY, collapsed))

export const setSessionPanelCollapsed = (collapsed: boolean) => $sessionPanelCollapsed.set(collapsed)
