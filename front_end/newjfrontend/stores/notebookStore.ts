import { create } from 'zustand'
import OpenNotebookAPI, {
  type Notebook as ApiNotebook,
  type Source as ApiSource,
  type Note as ApiNote,
  type ChatMessage as ApiChatMessage,
  type Podcast,
} from '@/lib/openNotebookApi'

// ============================================================================
// Types
// ============================================================================

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
  type: 'pdf' | 'text' | 'url' | 'markdown' | 'doc' | 'transcript' | 'audio' | 'youtube' | 'image'
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
  notebooks: Notebook[]
  currentNotebook: Notebook | null
  isLoadingNotebooks: boolean

  sources: NotebookSource[]
  isLoadingSources: boolean

  notes: NotebookNote[]
  isLoadingNotes: boolean

  messages: ChatMessage[]
  isLoadingMessages: boolean
  isChatting: boolean
  selectedModel: string

  podcasts: Podcast[]
  isLoadingPodcasts: boolean

  isOpenNotebookAvailable: boolean
  error: string | null

  fetchNotebooks: () => Promise<void>
  createNotebook: (title: string, description?: string) => Promise<Notebook | null>
  selectNotebook: (notebookId: string) => Promise<void>
  updateNotebook: (notebookId: string, title?: string, description?: string) => Promise<void>
  deleteNotebook: (notebookId: string) => Promise<void>

  fetchSources: (notebookId?: string) => Promise<void>
  uploadSource: (notebookId: string, file: File, title?: string) => Promise<NotebookSource | null>
  addUrlSource: (notebookId: string, url: string, title?: string) => Promise<NotebookSource | null>
  addTextSource: (notebookId: string, title: string, content: string) => Promise<NotebookSource | null>
  addYouTubeSource: (notebookId: string, url: string) => Promise<NotebookSource | null>
  deleteSource: (notebookId: string, sourceId: string) => Promise<void>
  refreshSourceStatus: (notebookId: string, sourceId: string) => Promise<void>

  fetchNotes: (notebookId: string) => Promise<void>
  createNote: (notebookId: string, content: string, type?: string, title?: string) => Promise<NotebookNote | null>
  updateNote: (notebookId: string, noteId: string, content?: string, title?: string, isPinned?: boolean) => Promise<void>
  deleteNote: (notebookId: string, noteId: string) => Promise<void>

  fetchChatHistory: (notebookId: string) => Promise<void>
  sendMessage: (notebookId: string, message: string, model?: string) => Promise<void>
  clearChatHistory: (notebookId: string) => Promise<void>
  setSelectedModel: (model: string) => void

  fetchPodcasts: (notebookId: string) => Promise<void>
  deletePodcast: (podcastId: string) => Promise<void>

  setError: (error: string | null) => void
  clearCurrentNotebook: () => void
  checkServiceHealth: () => Promise<void>
}

// ============================================================================
// Mappers
// ============================================================================

function mapApiNotebook(n: ApiNotebook): Notebook {
  return {
    id: n.id,
    user_id: 0,
    title: n.title,
    description: n.description,
    is_active: n.is_active !== false,
    created_at: n.created_at,
    updated_at: n.updated_at,
    source_count: n.source_count || 0,
    note_count: n.note_count || 0,
  }
}

const SOURCE_TYPE_MAP: Record<string, NotebookSource['type']> = {
  pdf: 'pdf', text: 'text', url: 'url', markdown: 'markdown',
  doc: 'doc', youtube: 'youtube', audio: 'audio', image: 'image',
  transcript: 'transcript', link: 'url', upload: 'doc', file: 'doc',
}

const SOURCE_STATUS_MAP: Record<string, NotebookSource['status']> = {
  pending: 'pending', processing: 'processing', ready: 'ready',
  completed: 'ready', error: 'error', failed: 'error',
}

function mapApiSource(s: ApiSource, notebookId: string): NotebookSource {
  return {
    id: s.id,
    notebook_id: s.notebook_id || notebookId,
    type: SOURCE_TYPE_MAP[s.source_type || ''] || 'doc',
    title: s.title || s.original_filename,
    storage_path: s.storage_path,
    original_filename: s.original_filename,
    metadata: s.metadata || {},
    status: SOURCE_STATUS_MAP[s.status || ''] || 'pending',
    error_message: s.error_message,
    created_at: s.created_at,
    updated_at: s.updated_at,
    chunk_count: s.chunk_count || 0,
  }
}

function mapApiNote(n: ApiNote): NotebookNote {
  return {
    id: n.id,
    notebook_id: n.notebook_id || '',
    user_id: 0,
    type: (n.type as NotebookNote['type']) || 'user_note',
    title: n.title,
    content: n.content,
    source_meta: n.source_meta || {},
    is_pinned: n.is_pinned || false,
    created_at: n.created_at,
    updated_at: n.updated_at,
  }
}

function mapApiChatMessage(msg: ApiChatMessage, notebookId: string): ChatMessage {
  return {
    id: msg.id,
    notebook_id: notebookId,
    user_id: 0,
    role: msg.role === 'human' ? 'user' : msg.role === 'ai' ? 'assistant' : (msg.role as ChatMessage['role']),
    content: msg.content,
    citations: [],
    created_at: msg.created_at || new Date().toISOString(),
  }
}

// ============================================================================
// Store
// ============================================================================

export const useNotebookStore = create<NotebookState>((set, get) => ({
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
  selectedModel: 'mistral',
  podcasts: [],
  isLoadingPodcasts: false,
  isOpenNotebookAvailable: false,
  error: null,

  checkServiceHealth: async () => {
    const isAvailable = await OpenNotebookAPI.checkHealth()
    set({ isOpenNotebookAvailable: isAvailable })
  },

  // ─── Notebook Actions ─────────────────────────────────────────────────────────

  fetchNotebooks: async () => {
    set({ isLoadingNotebooks: true, error: null })
    try {
      const apiNotebooks = await OpenNotebookAPI.notebooks.list()
      set({
        notebooks: apiNotebooks.map(mapApiNotebook),
        isLoadingNotebooks: false,
        isOpenNotebookAvailable: true,
      })
    } catch (error) {
      console.error('Error fetching notebooks:', error)
      let errorMessage = 'Failed to load notebooks'
      if (error instanceof Error) {
        if (error.message.includes('401')) errorMessage = 'Session expired. Please login again.'
        else if (error.message.includes('fetch')) errorMessage = 'Cannot connect to notebook service.'
      }
      set({ error: errorMessage, isLoadingNotebooks: false, isOpenNotebookAvailable: false })
    }
  },

  createNotebook: async (title, description) => {
    set({ error: null })
    try {
      const apiNotebook = await OpenNotebookAPI.notebooks.create({ title, description })
      const notebook = mapApiNotebook(apiNotebook)
      set(state => ({ notebooks: [notebook, ...state.notebooks] }))
      return notebook
    } catch (error) {
      console.error('Error creating notebook:', error)
      set({ error: 'Failed to create notebook' })
      return null
    }
  },

  selectNotebook: async (notebookId) => {
    set({ isLoadingNotebooks: true, error: null })
    try {
      const apiNotebook = await OpenNotebookAPI.notebooks.get(notebookId)
      const notebook = mapApiNotebook(apiNotebook)
      set({
        currentNotebook: notebook,
        isLoadingNotebooks: false,
        sources: [], notes: [], messages: [],
      })
      await Promise.all([
        get().fetchSources(notebookId),
        get().fetchNotes(notebookId),
        get().fetchChatHistory(notebookId),
      ])
    } catch (error) {
      console.error('Error selecting notebook:', error)
      set({ error: 'Notebook not found', isLoadingNotebooks: false })
    }
  },

  updateNotebook: async (notebookId, title, description) => {
    try {
      const apiNotebook = await OpenNotebookAPI.notebooks.update(notebookId, { title, description })
      const updated = mapApiNotebook(apiNotebook)
      set(state => ({
        notebooks: state.notebooks.map(n => n.id === notebookId ? updated : n),
        currentNotebook: state.currentNotebook?.id === notebookId ? updated : state.currentNotebook,
      }))
    } catch (error) {
      console.error('Error updating notebook:', error)
    }
  },

  deleteNotebook: async (notebookId) => {
    try {
      await OpenNotebookAPI.notebooks.delete(notebookId)
      set(state => ({
        notebooks: state.notebooks.filter(n => n.id !== notebookId),
        currentNotebook: state.currentNotebook?.id === notebookId ? null : state.currentNotebook,
      }))
    } catch (error) {
      console.error('Error deleting notebook:', error)
    }
  },

  // ─── Source Actions ───────────────────────────────────────────────────────────

  fetchSources: async (notebookId) => {
    if (!notebookId) return
    set({ isLoadingSources: true })
    try {
      const sources = await OpenNotebookAPI.sources.list(notebookId)
      set({ sources: sources.map(s => mapApiSource(s, notebookId)), isLoadingSources: false })
    } catch (error) {
      console.error('Error fetching sources:', error)
      set({ isLoadingSources: false })
    }
  },

  uploadSource: async (notebookId, file, title) => {
    try {
      const resp = await OpenNotebookAPI.sources.uploadFile({ file, title, notebook_id: notebookId })
      const mapped = mapApiSource(resp.source, notebookId)
      set(state => ({ sources: [mapped, ...state.sources] }))
      return mapped
    } catch (error) {
      console.error('Error uploading source:', error)
      set({ error: 'Failed to upload file' })
      return null
    }
  },

  addUrlSource: async (notebookId, url, title) => {
    try {
      const resp = await OpenNotebookAPI.sources.createFromUrl({ url, title, notebook_id: notebookId })
      const mapped = mapApiSource(resp.source, notebookId)
      set(state => ({ sources: [mapped, ...state.sources] }))
      return mapped
    } catch (error) {
      console.error('Error adding URL source:', error)
      set({ error: 'Failed to add URL' })
      return null
    }
  },

  addTextSource: async (notebookId, title, content) => {
    try {
      const resp = await OpenNotebookAPI.sources.createFromText({ content, title, notebook_id: notebookId })
      const mapped = mapApiSource(resp.source, notebookId)
      set(state => ({ sources: [mapped, ...state.sources] }))
      return mapped
    } catch (error) {
      console.error('Error adding text source:', error)
      set({ error: 'Failed to add text' })
      return null
    }
  },

  addYouTubeSource: async (notebookId, url) => {
    try {
      const resp = await OpenNotebookAPI.sources.createFromYouTube({ url, notebook_id: notebookId })
      const mapped = mapApiSource(resp.source, notebookId)
      set(state => ({ sources: [mapped, ...state.sources] }))
      return mapped
    } catch (error) {
      console.error('Error adding YouTube source:', error)
      set({ error: 'Failed to add YouTube source' })
      return null
    }
  },

  deleteSource: async (notebookId, sourceId) => {
    try {
      await OpenNotebookAPI.sources.delete(notebookId, sourceId)
      set(state => ({ sources: state.sources.filter(s => s.id !== sourceId) }))
    } catch (error) {
      console.error('Error deleting source:', error)
    }
  },

  refreshSourceStatus: async (notebookId, sourceId) => {
    try {
      const status = await OpenNotebookAPI.sources.getStatus(notebookId, sourceId)
      const mappedStatus = SOURCE_STATUS_MAP[status.status] || 'pending'
      set(state => ({
        sources: state.sources.map(s =>
          s.id === sourceId
            ? { ...s, status: mappedStatus, error_message: status.error_message, chunk_count: status.chunk_count ?? s.chunk_count }
            : s
        ),
      }))
    } catch (error) {
      console.error('Error refreshing source status:', error)
    }
  },

  // ─── Note Actions ─────────────────────────────────────────────────────────────

  fetchNotes: async (notebookId) => {
    set({ isLoadingNotes: true })
    try {
      const notes = await OpenNotebookAPI.notes.list(notebookId)
      set({ notes: notes.map(mapApiNote), isLoadingNotes: false })
    } catch (error) {
      console.error('Error fetching notes:', error)
      set({ isLoadingNotes: false })
    }
  },

  createNote: async (notebookId, content, type = 'user_note', title) => {
    try {
      const note = await OpenNotebookAPI.notes.create(notebookId, {
        title: title || 'Untitled Note',
        content,
        type,
      })
      const mapped = mapApiNote(note)
      set(state => ({ notes: [mapped, ...state.notes] }))
      return mapped
    } catch (error) {
      console.error('Error creating note:', error)
      set({ error: 'Failed to create note' })
      return null
    }
  },

  updateNote: async (notebookId, noteId, content, title, isPinned) => {
    try {
      const note = await OpenNotebookAPI.notes.update(notebookId, noteId, {
        content,
        title,
        is_pinned: isPinned,
      })
      const mapped = mapApiNote(note)
      set(state => ({ notes: state.notes.map(n => n.id === noteId ? mapped : n) }))
    } catch (error) {
      console.error('Error updating note:', error)
    }
  },

  deleteNote: async (notebookId, noteId) => {
    try {
      await OpenNotebookAPI.notes.delete(notebookId, noteId)
      set(state => ({ notes: state.notes.filter(n => n.id !== noteId) }))
    } catch (error) {
      console.error('Error deleting note:', error)
    }
  },

  // ─── Chat Actions ─────────────────────────────────────────────────────────────

  fetchChatHistory: async (notebookId) => {
    set({ isLoadingMessages: true })
    try {
      const history = await OpenNotebookAPI.chat.getHistory(notebookId)
      const messages = history.map(msg => mapApiChatMessage(msg, notebookId))
      set({ messages, isLoadingMessages: false })
    } catch (error) {
      console.error('Error fetching chat history:', error)
      set({ isLoadingMessages: false })
    }
  },

  sendMessage: async (notebookId, message, model) => {
    set({ isChatting: true, error: null })

    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      notebook_id: notebookId,
      user_id: 0,
      role: 'user',
      content: message,
      citations: [],
      created_at: new Date().toISOString(),
    }
    set(state => ({ messages: [...state.messages, tempUserMsg] }))

    try {
      const response = await OpenNotebookAPI.chat.sendMessage(notebookId, {
        message,
        model: model || undefined,
      })

      const assistantMsg: ChatMessage = {
        id: response.message_id || `resp-${Date.now()}`,
        notebook_id: notebookId,
        user_id: 0,
        role: 'assistant',
        content: response.answer,
        reasoning: response.reasoning,
        citations: (response.citations || []).map(c => ({
          source_id: c.source_id || '',
          source_title: c.source_title,
          chunk_id: c.chunk_id,
          quote: c.quote,
        })),
        model_used: response.model_used,
        created_at: new Date().toISOString(),
      }

      set(state => ({ messages: [...state.messages, assistantMsg], isChatting: false }))
    } catch (error) {
      console.error('Error sending message:', error)
      set(state => ({
        messages: state.messages.filter(m => m.id !== tempUserMsg.id),
        error: 'Failed to send message',
        isChatting: false,
      }))
    }
  },

  clearChatHistory: async (notebookId) => {
    try {
      await OpenNotebookAPI.chat.clearHistory(notebookId)
      set({ messages: [] })
    } catch (error) {
      console.error('Error clearing chat history:', error)
    }
  },

  setSelectedModel: (model) => set({ selectedModel: model }),

  // ─── Podcast Actions ────────────────────────────────────────────────────────

  fetchPodcasts: async (notebookId) => {
    set({ isLoadingPodcasts: true })
    try {
      const podcasts = await OpenNotebookAPI.podcasts.listByNotebook(notebookId)
      set({ podcasts, isLoadingPodcasts: false })
    } catch (error) {
      console.error('Error fetching podcasts:', error)
      set({ isLoadingPodcasts: false })
    }
  },

  deletePodcast: async (podcastId) => {
    try {
      await OpenNotebookAPI.podcasts.delete(podcastId)
      set(state => ({ podcasts: state.podcasts.filter(p => p.id !== podcastId) }))
    } catch (error) {
      console.error('Error deleting podcast:', error)
    }
  },

  // ─── UI State ─────────────────────────────────────────────────────────────────

  setError: (error) => set({ error }),

  clearCurrentNotebook: () => set({
    currentNotebook: null,
    sources: [],
    notes: [],
    messages: [],
    podcasts: [],
  }),
}))
