import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type PluginTab = 'notebooks' | 'sources' | 'chat' | 'search' | 'podcasts' | 'voices' | 'settings'
export type NotebookViewMode = 'compact' | 'full'

interface NotebookPluginState {
  isOpen: boolean
  activeTab: PluginTab
  panelWidth: number
  selectedNotebookId: string | null
  viewMode: NotebookViewMode

  toggle: () => void
  open: () => void
  close: () => void
  setActiveTab: (tab: PluginTab) => void
  setPanelWidth: (width: number) => void
  selectNotebook: (id: string | null) => void
  setViewMode: (mode: NotebookViewMode) => void
  toggleViewMode: () => void
}

export const useNotebookPluginStore = create<NotebookPluginState>()(
  persist(
    (set) => ({
      isOpen: false,
      activeTab: 'notebooks',
      panelWidth: 420,
      selectedNotebookId: null,
      viewMode: 'compact' as NotebookViewMode,

      toggle: () => set((s) => ({ isOpen: !s.isOpen })),
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),
      setActiveTab: (tab) => set({ activeTab: tab }),
      setPanelWidth: (width) => set({ panelWidth: Math.max(320, Math.min(700, width)) }),
      selectNotebook: (id) => set({ selectedNotebookId: id }),
      setViewMode: (mode) => set({ viewMode: mode }),
      toggleViewMode: () => set((s) => ({
        viewMode: s.viewMode === 'compact' ? 'full' : 'compact',
      })),
    }),
    {
      name: 'notebook-plugin-storage',
      partialize: (state) => ({
        panelWidth: state.panelWidth,
        activeTab: state.activeTab,
      }),
    }
  )
)
