// Host side of the in-page island (src/island/mount.js). The island renders in the app's
// own React tree and origin, so there is no frame and no postMessage: the bridge calls the
// mounted app's methods directly. It stays pure decision logic — WHICH call WHEN — so the
// lifecycle rules (lowfx while a run is busy; paused while hidden or off-screen) are
// testable without a DOM. The component supplies the app handle.
import type { SubagentProgress } from '@/store/subagents'

/** Same id rule as the engine (src/island/engine/agents.js): anything else is dropped there. */
const ID_RE = /^[A-Za-z0-9_.:-]{1,64}$/
const MAX_AGENTS = 16

export interface IslandAgent {
  id: string
  model?: string
  name: string
  personality?: string
}

/** The user's own imported game files, by relative path (see engine/stardew/art-files.js for the rules). */
export type IslandArtFiles = Record<string, ArrayBuffer>

/** What the island reports about the user's own art. `error` leaves the previous art in place. */
export interface IslandArtStatus {
  custom: boolean
  message: string
  state: 'builtin' | 'custom' | 'error' | 'loading'
}

/** The app's look, so the island's HUD wears the same colours. The island accepts #rrggbb only. */
export interface IslandTheme {
  colors: {
    background: string
    border: string
    foreground: string
    mutedForeground: string
    popover: string
    primary: string
    primaryForeground: string
  }
  mode: 'dark' | 'light'
}

export type PauseReason = 'hidden' | 'offscreen'

export const ASSISTANT_AGENT_ID = 'harvis'

const safeId = (raw: string) => raw.replace(/[^A-Za-z0-9_.:-]/g, '_').slice(0, 64)

/** The residents for one session: the assistant itself plus the subagents it has spawned. */
export function islandAgents(subagents: readonly SubagentProgress[]): IslandAgent[] {
  const agents: IslandAgent[] = [
    { id: ASSISTANT_AGENT_ID, name: 'Harvis', personality: 'Friendly, talkative assistant' }
  ]

  for (const sub of subagents) {
    const id = safeId(sub.id)

    if (ID_RE.test(id) && !agents.some(a => a.id === id)) {
      agents.push({ id, model: sub.model, name: (sub.goal || id).slice(0, 24) })
    }
  }

  return agents.slice(0, MAX_AGENTS)
}

/** A new-chat island shows saved account bots, not ephemeral session runs. */
export function islandBots(bots: readonly { id: string; name: string; model: string }[]): IslandAgent[] {
  const agents: IslandAgent[] = [{ id: ASSISTANT_AGENT_ID, name: 'Harvis', personality: 'Friendly, talkative assistant' }]
  for (const bot of bots) {
    const id = safeId(bot.id)
    if (ID_RE.test(id) && !agents.some(agent => agent.id === id)) {
      agents.push({ id, model: bot.model, name: (bot.name || id).slice(0, 24) })
    }
  }
  return agents.slice(0, MAX_AGENTS)
}

/** island:select carries the engine's agent id; map it back to the subagent's own session, if it has one. */
export function sessionForIslandAgent(agentId: string, subagents: readonly SubagentProgress[]): string | undefined {
  return subagents.find(sub => safeId(sub.id) === agentId)?.sessionId
}

/** The slice of the mounted island (src/island/mount.js) the bridge drives. */
export interface IslandAppHandle {
  pause(): void
  resume(): void
  setLowFx(on: boolean): void
  setSession(agents: IslandAgent[]): void
  setTheme(theme: IslandTheme): void
}

/**
 * Lifecycle for one mounted island. Because `app` is same-process and trusted, the bridge
 * DOES pass the account's session through — the old iframe channel could not. dispose()
 * stops everything; nothing is callable afterwards.
 */
export class IslandBridge {
  private lowfx = false
  private paused = false
  private readonly reasons = new Set<PauseReason>()
  private themeKey = ''
  private sessionKey = ''
  private disposed = false

  constructor(private readonly app: IslandAppHandle) {}

  /** The island rebuilds every resident from its start tile, so an unchanged roster must not reach it. */
  setSession(agents: IslandAgent[]) {
    const key = JSON.stringify(agents)

    if (key === this.sessionKey || this.disposed) {
      return
    }

    this.sessionKey = key
    this.app.setSession(agents)
  }

  setTheme(theme: IslandTheme) {
    const key = JSON.stringify(theme)

    if (key === this.themeKey || this.disposed) {
      return
    }

    this.themeKey = key
    this.app.setTheme(theme)
  }

  /** A run starting turns low effects on; it ending turns them off. */
  setLowFx(on: boolean) {
    if (on === this.lowfx || this.disposed) {
      return
    }

    this.lowfx = on
    this.app.setLowFx(on)
  }

  /** Paused while ANY reason holds; resumes when the last one clears. */
  setReason(reason: PauseReason, active: boolean) {
    if (this.disposed) {
      return
    }

    if (active) {
      this.reasons.add(reason)
    } else {
      this.reasons.delete(reason)
    }

    const paused = this.reasons.size > 0

    if (paused !== this.paused) {
      this.paused = paused

      if (paused) {
        this.app.pause()
      } else {
        this.app.resume()
      }
    }
  }

  /** Unmounting goes quiet; the component then disposes the app itself. */
  dispose() {
    this.disposed = true
    this.reasons.clear()
  }
}
