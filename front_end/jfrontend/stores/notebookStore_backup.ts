import { create } from 'zustand'

// Types
export interface Notebook {
  id: string
  user_id: number
  title: string
  description?: string
  is_active: boolean
  created_at: string
  updated_at: string
  source_count: number
  note_count: number
}

export interface NotebookSource {
  id: string
  notebook_id: string
  type: 'pdf' | 'text' | 'url' | 'markdown' | 'doc' | 'transcript' | 'audio'
  title?: string
  storage_path?: string
  original_filename?: string
  metadata: Record<string, any>
  status: 'pending' | 'processing' | 'ready' | 'error'
  error_message?: string
  created_at: string
  updated_at: string
  chunk_count: number
}

export interface NotebookNote {
  id: string
  notebook_id: string
  user_id: number
  type: 'user_note' | 'ai_note' | 'summary' | 'highlight'
  title?: string
  content: string
  source_meta: Record<string, any>
  is_pinned: boolean
  created_at: string
  updated_at: string
}

export interface Citation {
  source_id: string
  source_title?: string
  chunk_id?: string
  page?: number
  section?: string
  quote?: string
}

export interface ChatMessage {
  id: string
  notebook_id: string
  user_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  reasoning?: string
  citations: Citation[]
  model_used?: string
  created_at: string
}

interface NotebookState {
  // Notebooks
  notebooks: Notebook[]
  currentNotebook: Notebook | null
  isLoadingNotebooks: boolean

  // Sources
  sources: NotebookSource[]
  isLoadingSources: boolean

  // Notes
  notes: NotebookNote[]
  isLoadingNotes: boolean

  // Chat
  messages: ChatMessage[]
  isLoadingMessages: boolean
  isChatting: boolean

  // Error
  error: string | null

  // Actions - Notebooks
  fetchNotebooks: () => Promise<void>
  createNotebook: (title: string, description?: string) => Promise<Notebook | null>
  selectNotebook: (notebookId: string) => Promise<void>
  updateNotebook: (notebookId: string, title?: string, description?: string) => Promise<void>
  deleteNotebook: (notebookId: string) => Promise<void>

  // Actions - Sources
  fetchSources: (notebookId: string) => Promise<void>
  uploadSource: (notebookId: string, file: File, title?: string) => Promise<NotebookSource | null>
  addUrlSource: (notebookId: string, url: string, title?: string) => Promise<NotebookSource | null>
  addTextSource: (notebookId: string, title: string, content: string) => Promise<NotebookSource | null>
  deleteSource: (notebookId: string, sourceId: string) => Promise<void>
  refreshSourceStatus: (notebookId: string, sourceId: string) => Promise<void>

  // Actions - Notes
  fetchNotes: (notebookId: string) => Promise<void>
  createNote: (notebookId: string, content: string, type?: string, title?: string) => Promise<NotebookNote | null>
  updateNote: (notebookId: string, noteId: string, content?: string, title?: string, isPinned?: boolean) => Promise<void>
  deleteNote: (notebookId: string, noteId: string) => Promise<void>

  // Actions - Chat
  fetchChatHistory: (notebookId: string) => Promise<void>
  sendMessage: (notebookId: string, message: string, model?: string) => Promise<void>
  clearChatHistory: (notebookId: string) => Promise<void>

  // UI State
  setError: (error: string | null) => void
  clearCurrentNotebook: () => void
}

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

export const useNotebookStore = create<NotebookState>((set, get) => ({
  // Initial state
  notebooks: [],
  currentNotebook: null,
  isLoadingNotebooks: false,
  sources: [],
  isLoadingSources: false,
  notes: [],
  isLoadingNotes: false,
  messages: [],
  isLoadingMessages: false,
  isChatting: false,
  error: null,

  // ─── Notebook Actions ─────────────────────────────────────────────────────────

  fetchNotebooks: async () => {
    const token = localStorage.getItem('token')
    if (!token) {
      set({ error: 'Please login to view notebooks' })
      return
    }

    set({ isLoadingNotebooks: true, error: null })

    try {
      const response = await fetch('/api/notebooks', {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const data = await response.json()
        set({
          notebooks: data.notebooks || [],
          isLoadingNotebooks: false
        })
      } else {
        const error = await response.text()
        set({ error: 'Failed to load notebooks', isLoadingNotebooks: false })
        console.error('Failed to fetch notebooks:', error)
      }
    } catch (error) {
      set({ error: 'Failed to load notebooks', isLoadingNotebooks: false })
      console.error('Error fetching notebooks:', error)
    }
  },

  createNotebook: async (title: string, description?: string) => {
    set({ error: null })

    try {
      const response = await fetch('/api/notebooks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ title, description }),
      })

      if (response.ok) {
        const notebook = await response.json()
        set(state => ({
          notebooks: [notebook, ...state.notebooks],
        }))
        return notebook
      } else {
        const error = await response.text()
        set({ error: 'Failed to create notebook' })
        console.error('Failed to create notebook:', error)
        return null
      }
    } catch (error) {
      set({ error: 'Failed to create notebook' })
      console.error('Error creating notebook:', error)
      return null
    }
  },

  selectNotebook: async (notebookId: string) => {
    set({ isLoadingNotebooks: true, error: null })

    try {
      const response = await fetch(`/api/notebooks/${notebookId}`, {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const notebook = await response.json()
        set({
          currentNotebook: notebook,
          isLoadingNotebooks: false,
          sources: [],
          notes: [],
          messages: [],
        })

        // Fetch related data
        await Promise.all([
          get().fetchSources(notebookId),
          get().fetchNotes(notebookId),
          get().fetchChatHistory(notebookId),
        ])
      } else {
        set({ error: 'Notebook not found', isLoadingNotebooks: false })
      }
    } catch (error) {
      set({ error: 'Failed to load notebook', isLoadingNotebooks: false })
      console.error('Error selecting notebook:', error)
    }
  },

  updateNotebook: async (notebookId: string, title?: string, description?: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ title, description }),
      })

      if (response.ok) {
        const updated = await response.json()
        set(state => ({
          notebooks: state.notebooks.map(n => n.id === notebookId ? updated : n),
          currentNotebook: state.currentNotebook?.id === notebookId ? updated : state.currentNotebook,
        }))
      }
    } catch (error) {
      console.error('Error updating notebook:', error)
    }
  },

  deleteNotebook: async (notebookId: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })

      if (response.ok) {
        set(state => ({
          notebooks: state.notebooks.filter(n => n.id !== notebookId),
          currentNotebook: state.currentNotebook?.id === notebookId ? null : state.currentNotebook,
        }))
      }
    } catch (error) {
      console.error('Error deleting notebook:', error)
    }
  },

  // ─── Source Actions ───────────────────────────────────────────────────────────

  fetchSources: async (notebookId: string) => {
    set({ isLoadingSources: true })

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources`, {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const sources = await response.json()
        set({ sources, isLoadingSources: false })
      } else {
        set({ isLoadingSources: false })
      }
    } catch (error) {
      set({ isLoadingSources: false })
      console.error('Error fetching sources:', error)
    }
  },

  uploadSource: async (notebookId: string, file: File, title?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (title) formData.append('title', title)

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/upload`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        set(state => ({
          sources: [data.source, ...state.sources],
        }))
        return data.source
      } else {
        const error = await response.text()
        set({ error: 'Failed to upload file' })
        console.error('Failed to upload source:', error)
        return null
      }
    } catch (error) {
      set({ error: 'Failed to upload file' })
      console.error('Error uploading source:', error)
      return null
    }
  },

  addUrlSource: async (notebookId: string, url: string, title?: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ url, title }),
      })

      if (response.ok) {
        const data = await response.json()
        set(state => ({
          sources: [data.source, ...state.sources],
        }))
        return data.source
      } else {
        set({ error: 'Failed to add URL' })
        return null
      }
    } catch (error) {
      set({ error: 'Failed to add URL' })
      console.error('Error adding URL source:', error)
      return null
    }
  },

  addTextSource: async (notebookId: string, title: string, content: string) => {
    const formData = new FormData()
    formData.append('title', title)
    formData.append('content', content)

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/text`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        set(state => ({
          sources: [data.source, ...state.sources],
        }))
        return data.source
      } else {
        set({ error: 'Failed to add text' })
        return null
      }
    } catch (error) {
      set({ error: 'Failed to add text' })
      console.error('Error adding text source:', error)
      return null
    }
  },

  deleteSource: async (notebookId: string, sourceId: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/${sourceId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })

      if (response.ok) {
        set(state => ({
          sources: state.sources.filter(s => s.id !== sourceId),
        }))
      }
    } catch (error) {
      console.error('Error deleting source:', error)
    }
  },

  refreshSourceStatus: async (notebookId: string, sourceId: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/${sourceId}/status`, {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const status = await response.json()
        set(state => ({
          sources: state.sources.map(s =>
            s.id === sourceId
              ? { ...s, status: status.status, chunk_count: status.chunk_count || s.chunk_count, error_message: status.error_message }
              : s
          ),
        }))
      }
    } catch (error) {
      console.error('Error refreshing source status:', error)
    }
  },

  // ─── Note Actions ─────────────────────────────────────────────────────────────

  fetchNotes: async (notebookId: string) => {
    set({ isLoadingNotes: true })

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/notes`, {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const data = await response.json()
        set({ notes: data.notes || [], isLoadingNotes: false })
      } else {
        set({ isLoadingNotes: false })
      }
    } catch (error) {
      set({ isLoadingNotes: false })
      console.error('Error fetching notes:', error)
    }
  },

  createNote: async (notebookId: string, content: string, type: string = 'user_note', title?: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ content, type, title }),
      })

      if (response.ok) {
        const note = await response.json()
        set(state => ({
          notes: [note, ...state.notes],
        }))
        return note
      } else {
        set({ error: 'Failed to create note' })
        return null
      }
    } catch (error) {
      set({ error: 'Failed to create note' })
      console.error('Error creating note:', error)
      return null
    }
  },

  updateNote: async (notebookId: string, noteId: string, content?: string, title?: string, isPinned?: boolean) => {
    try {
      const body: any = {}
      if (content !== undefined) body.content = content
      if (title !== undefined) body.title = title
      if (isPinned !== undefined) body.is_pinned = isPinned

      const response = await fetch(`/api/notebooks/${notebookId}/notes/${noteId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify(body),
      })

      if (response.ok) {
        const updated = await response.json()
        set(state => ({
          notes: state.notes.map(n => n.id === noteId ? updated : n),
        }))
      }
    } catch (error) {
      console.error('Error updating note:', error)
    }
  },

  deleteNote: async (notebookId: string, noteId: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/notes/${noteId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })

      if (response.ok) {
        set(state => ({
          notes: state.notes.filter(n => n.id !== noteId),
        }))
      }
    } catch (error) {
      console.error('Error deleting note:', error)
    }
  },

  // ─── Chat Actions ─────────────────────────────────────────────────────────────

  fetchChatHistory: async (notebookId: string) => {
    set({ isLoadingMessages: true })

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/chat/history`, {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })

      if (response.ok) {
        const data = await response.json()
        set({ messages: data.messages || [], isLoadingMessages: false })
      } else {
        set({ isLoadingMessages: false })
      }
    } catch (error) {
      set({ isLoadingMessages: false })
      console.error('Error fetching chat history:', error)
    }
  },

  sendMessage: async (notebookId: string, message: string, model: string = 'mistral') => {
    set({ isChatting: true, error: null })

    // Add user message optimistically
    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      notebook_id: notebookId,
      user_id: 0,
      role: 'user',
      content: message,
      citations: [],
      created_at: new Date().toISOString(),
    }

    set(state => ({
      messages: [...state.messages, tempUserMsg],
    }))

    try {
      const response = await fetch(`/api/notebooks/${notebookId}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ message, model, top_k: 5 }),
      })

      if (response.ok) {
        const data = await response.json()

        // Replace temp message with actual and add assistant response
        set(state => ({
          messages: [
            ...state.messages.filter(m => m.id !== tempUserMsg.id),
            { ...tempUserMsg, id: `user-${Date.now()}` },
            {
              id: data.message_id,
              notebook_id: notebookId,
              user_id: 0,
              role: 'assistant',
              content: data.answer,
              reasoning: data.reasoning,
              citations: data.citations || [],
              model_used: data.model_used,
              created_at: new Date().toISOString(),
            },
          ],
          isChatting: false,
        }))
      } else {
        const error = await response.text()
        set(state => ({
          messages: state.messages.filter(m => m.id !== tempUserMsg.id),
          error: 'Failed to send message',
          isChatting: false,
        }))
        console.error('Failed to send message:', error)
      }
    } catch (error) {
      set(state => ({
        messages: state.messages.filter(m => m.id !== tempUserMsg.id),
        error: 'Failed to send message',
        isChatting: false,
      }))
      console.error('Error sending message:', error)
    }
  },

  clearChatHistory: async (notebookId: string) => {
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/chat/history`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })

      if (response.ok) {
        set({ messages: [] })
      }
    } catch (error) {
      console.error('Error clearing chat history:', error)
    }
  },

  // ─── UI State ─────────────────────────────────────────────────────────────────

  setError: (error: string | null) => set({ error }),

  clearCurrentNotebook: () => set({
    currentNotebook: null,
    sources: [],
    notes: [],
    messages: [],
  }),
}))
