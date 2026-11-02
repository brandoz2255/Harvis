import type { RosterRow } from '@/plugins/hermes-bots/types'
import type { IslandAgent } from './island-bridge'

/** Opaque, never-reused engine IDs preserve exact source-qualified roster identity. */
export class IslandRoster {
  private next = 0
  private ids = new Map<string, string>()
  private current = new Map<string, RosterRow>()

  update(rows: readonly RosterRow[]): IslandAgent[] {
    this.current.clear()
    return rows.slice(0, 16).map(row => {
      const key = JSON.stringify([row.connectionId ?? '', row.name])
      let id = this.ids.get(key)
      if (!id) {
        id = `resident-${++this.next}`
        this.ids.set(key, id)
      }
      this.current.set(id, row)
      return { id, name: (row.display_name || row.name).slice(0, 24) }
    })
  }

  resolve(id: string): RosterRow | undefined {
    return this.current.get(id)
  }
}
