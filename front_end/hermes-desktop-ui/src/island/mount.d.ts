// Types for mount.js — the scoped in-page island used by the Harvis React host.
import type { IslandAgent, IslandArtFiles, IslandArtStatus, IslandTheme } from '../mods/island-bridge'

export interface MountOptions {
  agents?: IslandAgent[]
  interactive?: boolean
  lowFx?: boolean
  onSelect?: (agentId: string) => void
  paused?: boolean
  theme?: IslandTheme | null
  weather?: string
  zoom?: number
}

export interface IslandApp {
  /** The tile-art island app while custom art is on, else null. */
  readonly custom: {
    app: {
      readonly paused: boolean
      pause(): void
      resume(): void
      setInteractive(on: boolean): void
      setLowFx(on: boolean): void
      r: { lastSig: string; setTheme(t: unknown): void }
      sim: { agents: readonly { id: string }[] }
    }
  } | null
  /** Test/introspection handle to the built-in renderer. */
  readonly r: { draw(force?: boolean): boolean; lowFx: boolean; selected: null | string }
  /** Test/introspection handle to the built-in sim. */
  readonly sim: { agents: readonly { id: string }[] }
  applyEvent(ev: unknown): void
  /** Back to the built-in art. */
  clearArt(): IslandArtStatus
  dispose(): void
  pause(): void
  resume(): void
  setInteractive(on: boolean): void
  setLowFx(on: boolean): void
  setSession(agents: IslandAgent[]): void
  setTheme(theme: IslandTheme): void
  /** Switch to the user's own game files; resolves to what the island shows now. */
  useArt(files: IslandArtFiles): Promise<IslandArtStatus>
}

export function mountIsland(root: Element, opts?: MountOptions): IslandApp
