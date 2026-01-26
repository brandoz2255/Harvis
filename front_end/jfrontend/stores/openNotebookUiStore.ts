import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// ============================================================================
// Types
// ============================================================================

export type ContextMode = 'off' | 'insights' | 'full'

interface SidebarState {
  isCollapsed: boolean
  toggleCollapse: () => void
  setCollapsed: (collapsed: boolean) => void
}

interface NotebookColumnsState {
  sourcesCollapsed: boolean
  notesCollapsed: boolean
  toggleSources: () => void
  toggleNotes: () => void
  setSourcesCollapsed: (collapsed: boolean) => void
  setNotesCollapsed: (collapsed: boolean) => void
}

interface ContextSelection {
  sources: Record<string, ContextMode>
  notes: Record<string, ContextMode>
}

interface ContextSelectionsState {
  // Map of notebookId -> { sources: {sourceId: mode}, notes: {noteId: mode} }
  selections: Record<string, ContextSelection>
  getSourceMode: (notebookId: string, sourceId: string) => ContextMode
  getNoteMode: (notebookId: string, noteId: string) => ContextMode
  setSourceMode: (notebookId: string, sourceId: string, mode: ContextMode) => void
  setNoteMode: (notebookId: string, noteId: string, mode: ContextMode) => void
  clearNotebookSelections: (notebookId: string) => void
}

// ============================================================================
// Sidebar Store
// ============================================================================

export const useOpenNotebookSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      isCollapsed: false,
      toggleCollapse: () => set((state) => ({ isCollapsed: !state.isCollapsed })),
      setCollapsed: (collapsed: boolean) => set({ isCollapsed: collapsed }),
    }),
    {
      name: 'open-notebook-sidebar-storage',
    }
  )
)

// ============================================================================
// Notebook Columns Store
// ============================================================================

export const useNotebookColumnsStore = create<NotebookColumnsState>()(
  persist(
    (set) => ({
      sourcesCollapsed: false,
      notesCollapsed: false,
      toggleSources: () => set((state) => ({ sourcesCollapsed: !state.sourcesCollapsed })),
      toggleNotes: () => set((state) => ({ notesCollapsed: !state.notesCollapsed })),
      setSourcesCollapsed: (collapsed: boolean) => set({ sourcesCollapsed: collapsed }),
      setNotesCollapsed: (collapsed: boolean) => set({ notesCollapsed: collapsed }),
    }),
    {
      name: 'notebook-columns-storage',
    }
  )
)

// ============================================================================
// Context Selections Store
// ============================================================================

export const useContextSelectionsStore = create<ContextSelectionsState>()(
  persist(
    (set, get) => ({
      selections: {},

      getSourceMode: (notebookId: string, sourceId: string): ContextMode => {
        const notebookSelections = get().selections[notebookId]
        if (!notebookSelections) return 'full' // Default to full content
        return notebookSelections.sources[sourceId] ?? 'full'
      },

      getNoteMode: (notebookId: string, noteId: string): ContextMode => {
        const notebookSelections = get().selections[notebookId]
        if (!notebookSelections) return 'full' // Default to full content
        return notebookSelections.notes[noteId] ?? 'full'
      },

      setSourceMode: (notebookId: string, sourceId: string, mode: ContextMode) => {
        set((state) => {
          const notebookSelections = state.selections[notebookId] || { sources: {}, notes: {} }
          return {
            selections: {
              ...state.selections,
              [notebookId]: {
                ...notebookSelections,
                sources: {
                  ...notebookSelections.sources,
                  [sourceId]: mode,
                },
              },
            },
          }
        })
      },

      setNoteMode: (notebookId: string, noteId: string, mode: ContextMode) => {
        set((state) => {
          const notebookSelections = state.selections[notebookId] || { sources: {}, notes: {} }
          return {
            selections: {
              ...state.selections,
              [notebookId]: {
                ...notebookSelections,
                notes: {
                  ...notebookSelections.notes,
                  [noteId]: mode,
                },
              },
            },
          }
        })
      },

      clearNotebookSelections: (notebookId: string) => {
        set((state) => {
          const { [notebookId]: _, ...rest } = state.selections
          return { selections: rest }
        })
      },
    }),
    {
      name: 'context-selections-storage',
    }
  )
)

// ============================================================================
// Create Dialogs State
// ============================================================================

interface CreateDialogsState {
  sourceDialogOpen: boolean
  notebookDialogOpen: boolean
  podcastDialogOpen: boolean
  openSourceDialog: () => void
  openNotebookDialog: () => void
  openPodcastDialog: () => void
  closeSourceDialog: () => void
  closeNotebookDialog: () => void
  closePodcastDialog: () => void
}

export const useCreateDialogsStore = create<CreateDialogsState>((set) => ({
  sourceDialogOpen: false,
  notebookDialogOpen: false,
  podcastDialogOpen: false,
  openSourceDialog: () => set({ sourceDialogOpen: true }),
  openNotebookDialog: () => set({ notebookDialogOpen: true }),
  openPodcastDialog: () => set({ podcastDialogOpen: true }),
  closeSourceDialog: () => set({ sourceDialogOpen: false }),
  closeNotebookDialog: () => set({ notebookDialogOpen: false }),
  closePodcastDialog: () => set({ podcastDialogOpen: false }),
}))

// ============================================================================
// Mobile View State
// ============================================================================

type MobileTab = 'sources' | 'notes' | 'chat'

interface MobileViewState {
  activeTab: MobileTab
  setActiveTab: (tab: MobileTab) => void
}

export const useMobileViewStore = create<MobileViewState>((set) => ({
  activeTab: 'chat',
  setActiveTab: (tab: MobileTab) => set({ activeTab: tab }),
}))
