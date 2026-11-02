/** Wire shapes of the Harvis mods backend (python_back_end/plugins/mods). The
 *  server is the store and the hash authority; these only describe its answers. */

export const MOD_SLOTS = [
  'clock',
  'pet',
  'status-line',
  'side-panel',
  'slash-command',
  'pre-send',
  'chat-widget',
  'island'
] as const

export type ModSlotName = (typeof MOD_SLOTS)[number]

export type ModStatus = 'broken' | 'draft' | 'off' | 'on'
export type ModTier = 'looks' | 'rules' | 'ui'

export interface ModCsp {
  baseUriDomains?: string[]
  connectDomains?: string[]
  frameDomains?: string[]
  resourceDomains?: string[]
}

export interface ModUi {
  csp?: ModCsp
  permissions?: Record<string, unknown>
  resource: string
  slot: ModSlotName
  title?: string
}

export type LookValue = boolean | number | string

export interface ModManifest {
  author?: string
  description?: string
  harvis_mod_version: string
  looks?: Record<string, LookValue>
  name: string
  rules?: { hooks?: Record<string, unknown>[] }
  ui?: ModUi
  user_config?: Record<string, { type: 'boolean' | 'number' | 'string' }>
  version: string
}

export interface ModRow {
  approved_at: null | string
  approved_hash: null | string
  created_at: string
  hash: string
  id: number | string
  manifest: ModManifest
  name: string
  source: 'agent' | 'user'
  status: ModStatus
  status_reason: null | string
  tiers: ModTier[]
  version: string
}

export interface ModCard {
  author: string
  csp: Required<ModCsp> | null
  description: string
  hash: string
  hooks: Record<string, unknown>[]
  looks: Record<string, LookValue>
  name: string
  permissions: string[]
  slot: ModSlotName | null | undefined
  tiers: ModTier[]
  version: string
  warnings: string[]
}

export interface ModPackage {
  manifest: ModManifest
  resources: Record<string, string>
}
