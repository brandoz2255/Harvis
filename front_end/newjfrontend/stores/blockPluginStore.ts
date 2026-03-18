import { create } from 'zustand'

export type BlockPluginId = 'open-notebook' | 'vibe-code'
export type PluginViewMode = 'compact' | 'full'

export interface BlockPluginDef {
  id: BlockPluginId
  label: string
  iconName: string
  supportsFullPage?: boolean
}

export const BLOCK_PLUGINS: BlockPluginDef[] = [
  { id: 'open-notebook', label: 'Notebook',   iconName: 'BookOpen', supportsFullPage: true },
  { id: 'vibe-code',     label: 'Vibe Code',  iconName: 'Code',     supportsFullPage: true },
]

interface BlockPluginState {
  activePluginId: BlockPluginId | null
  panelWidth: number
  viewModes: Partial<Record<BlockPluginId, PluginViewMode>>

  toggle: (id: BlockPluginId) => void
  open: (id: BlockPluginId) => void
  close: () => void
  setPanelWidth: (width: number) => void
  getViewMode: (id: BlockPluginId) => PluginViewMode
  setViewMode: (id: BlockPluginId, mode: PluginViewMode) => void
  toggleViewMode: (id: BlockPluginId) => void
}

const STORAGE_KEY = 'block-plugin-panel-width'

function loadWidth(): number {
  if (typeof window === 'undefined') return 420
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v ? Math.max(320, Math.min(800, Number(v))) : 420
  } catch {
    return 420
  }
}

export const useBlockPluginStore = create<BlockPluginState>()((set, get) => ({
  activePluginId: null,
  panelWidth: loadWidth(),
  viewModes: {},

  toggle: (id) => set((s) => ({
    activePluginId: s.activePluginId === id ? null : id,
  })),
  open: (id) => set({ activePluginId: id }),
  close: () => set({ activePluginId: null }),
  setPanelWidth: (width) => {
    const clamped = Math.max(320, Math.min(800, width))
    try { localStorage.setItem(STORAGE_KEY, String(clamped)) } catch {}
    return set({ panelWidth: clamped })
  },
  getViewMode: (id) => get().viewModes[id] || 'compact',
  setViewMode: (id, mode) => set((s) => ({
    viewModes: { ...s.viewModes, [id]: mode },
  })),
  toggleViewMode: (id) => set((s) => ({
    viewModes: {
      ...s.viewModes,
      [id]: (s.viewModes[id] || 'compact') === 'compact' ? 'full' : 'compact',
    },
  })),
}))
