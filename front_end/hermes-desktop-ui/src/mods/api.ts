// Typed wrappers over the mods backend (python_back_end/plugins/mods/routes.py),
// reached through the desktop plugin REST door. The server stores mods, computes
// their content hash and decides what is approved; nothing here hashes anything.
import { pluginRest } from '@/api/plugins'

import type { ModCard, ModPackage, ModRow } from './types'

const NS = 'mods'
const enc = encodeURIComponent

export interface ModsApi {
  approve: (name: string, hash: string) => Promise<ModRow>
  card: (name: string, hash: string) => Promise<{ approval: ModCard; mod: ModRow }>
  disable: (name: string) => Promise<ModRow>
  install: (pkg: ModPackage) => Promise<{ approval: ModCard; mod: ModRow }>
  list: () => Promise<ModRow[]>
  remove: (name: string) => Promise<boolean>
  reportError: (name: string, reason: string) => Promise<ModRow>
  resources: (name: string, hash: string) => Promise<Record<string, string>>
  rollback: (name: string) => Promise<ModRow>
}

export const modsApi: ModsApi = {
  approve: async (name, hash) => (await pluginRest<{ mod: ModRow }>(NS, `/${enc(name)}/approve`, { body: { hash }, method: 'POST' })).mod,

  card: (name, hash) => pluginRest<{ approval: ModCard; mod: ModRow }>(NS, `/${enc(name)}/${enc(hash)}/card`),

  disable: async name => (await pluginRest<{ mod: ModRow }>(NS, `/${enc(name)}/disable`, { method: 'POST', body: {} })).mod,

  install: pkg => pluginRest<{ approval: ModCard; mod: ModRow }>(NS, '', { body: pkg, method: 'POST' }),

  list: async () => (await pluginRest<{ mods: ModRow[] }>(NS, '')).mods ?? [],

  remove: async name => Boolean((await pluginRest<{ removed: unknown }>(NS, `/${enc(name)}`, { method: 'DELETE' })).removed),

  reportError: async (name, reason) =>
    (await pluginRest<{ mod: ModRow }>(NS, `/${enc(name)}/error`, { body: { reason }, method: 'POST' })).mod,

  resources: async (name, hash) =>
    (await pluginRest<{ resources: Record<string, string> }>(NS, `/${enc(name)}/${enc(hash)}/resources`)).resources ?? {},

  rollback: async name => (await pluginRest<{ mod: ModRow }>(NS, `/${enc(name)}/rollback`, { method: 'POST', body: {} })).mod
}
