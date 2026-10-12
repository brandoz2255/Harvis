import { useStore } from '@nanostores/react'
import { atom } from 'nanostores'

/**
 * What this backend can do for the signed-in person, as reported by
 * `/api/status` (`capabilities`). A control whose flag is false is not rendered
 * and its endpoint is not called, so nobody meets a 404 or a 403 from a button
 * that was never going to work.
 *
 * Before the first status answer arrives every flag reads false (nothing flashes
 * in and then disappears). A backend that does not send `capabilities` at all
 * (a stock Hermes gateway) is treated as capable of everything.
 */
export type ServerCapability =
  | 'backup'
  | 'browser_control'
  | 'computer_use_grant'
  | 'curator'
  | 'debug_share'
  | 'doctor'
  | 'gateway_restart'
  | 'git'
  | 'git_remote'
  | 'git_worktrees'
  | 'hermes_update'
  | 'kanban'
  | 'logs'
  | 'memory_provider_config'
  | 'memory_reset'
  | 'pets'
  | 'projects'
  | 'provider_oauth'
  | 'provider_validate'
  | 'sandbox'
  | 'security_audit'
  | 'session_search'
  | 'skills_hub'
  | 'toolset_setup'
  | 'wake_word'

export interface ServerCapabilitiesState {
  /** True once a status answer has been read. */
  loaded: boolean
  /** Undefined when the backend did not send flags (treat as everything on). */
  flags: Partial<Record<ServerCapability, boolean>> | undefined
}

export const $serverCapabilities = atom<ServerCapabilitiesState>({ flags: undefined, loaded: false })

/** Reads the `capabilities` object off a `/api/status` body. Anything else clears the flags. */
export function setServerCapabilities(status: unknown): void {
  const raw = (status as null | { capabilities?: unknown })?.capabilities

  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    $serverCapabilities.set({ flags: undefined, loaded: true })

    return
  }

  const flags: Partial<Record<ServerCapability, boolean>> = {}

  for (const [key, value] of Object.entries(raw)) {
    flags[key as ServerCapability] = value === true
  }

  $serverCapabilities.set({ flags, loaded: true })
}

/** Back to "unknown" (a different backend or a sign-out). */
export function resetServerCapabilities(): void {
  $serverCapabilities.set({ flags: undefined, loaded: false })
}

export function hasCapability(
  name: ServerCapability,
  state: ServerCapabilitiesState = $serverCapabilities.get()
): boolean {
  if (!state.loaded) {
    return false
  }

  // A flag the backend does not mention is one it does not know about: off.
  return state.flags ? state.flags[name] === true : true
}

export function useCapability(name: ServerCapability): boolean {
  return hasCapability(name, useStore($serverCapabilities))
}
