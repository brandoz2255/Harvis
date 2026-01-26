import { create } from 'zustand'
import OpenNotebookAPI, {
  Notebook as OpenNotebook,
  Source,
  Note,
  ChatSession,
  ChatMessage as OpenChatMessage,
  ChatSessionWithMessages,
} from '@/lib/openNotebookApi'

// ============================================================================
// Types - Mapped from Open Notebook API types
// ============================================================================

export interface Notebook {
  id: string
  user_id: number  // Not used by Open Notebook but kept for compatibility
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
  currentSession: ChatSession | null
  messages: ChatMessage[]
  isLoadingMessages: boolean
  isChatting: boolean

  // Service status
  isOpenNotebookAvailable: boolean

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
  checkServiceHealth: () => Promise<void>
}

// ============================================================================
// Mappers - Convert between Open Notebook API types and our internal types
// ============================================================================

function mapOpenNotebookToNotebook(on: OpenNotebook): Notebook {
  return {
    id: on.id,
    user_id: 0, // Open Notebook doesn't have user_id
    title: on.name,
    description: on.description,
    is_active: !on.archived,
    created_at: on.created,
    updated_at: on.updated,
    source_count: on.source_count,
    note_count: on.note_count,
  }
}

function mapSourceToNotebookSource(source: Source, notebookId: string): NotebookSource {
  // Map source_type to our type
  const typeMap: Record<string, NotebookSource['type']> = {
    file: 'doc',
    url: 'url',
    text: 'text',
    youtube: 'youtube',
    pdf: 'pdf',
    audio: 'audio',
    video: 'transcript',
  }

  // Map processing_status to our status
  const statusMap: Record<string, NotebookSource['status']> = {
    pending: 'pending',
    processing: 'processing',
    completed: 'ready',
    failed: 'error',
  }

  return {
    id: source.id,
    notebook_id: notebookId,
    type: typeMap[source.source_type] || 'doc',
    title: source.title,
    storage_path: source.file_path,
    original_filename: source.title,
    metadata: {},
    status: statusMap[source.processing_status] || 'pending',
    error_message: source.error_message,
    created_at: source.created,
    updated_at: source.updated,
    chunk_count: source.asset_count || 0,
  }
}

function mapNoteToNotebookNote(note: Note): NotebookNote {
  return {
    id: note.id,
    notebook_id: note.notebook_id || '',
    user_id: 0,
    type: (note.note_type as NotebookNote['type']) || 'user_note',
    title: note.title,
    content: note.content,
    source_meta: { source_ids: note.source_ids },
    is_pinned: note.pinned,
    created_at: note.created,
    updated_at: note.updated,
  }
}

function mapOpenChatMessageToChatMessage(
  msg: OpenChatMessage,
  notebookId: string
): ChatMessage {
  return {
    id: msg.id,
    notebook_id: notebookId,
    user_id: 0,
    role: msg.type === 'human' ? 'user' : 'assistant',
    content: msg.content,
    citations: [],
    created_at: msg.timestamp || new Date().toISOString(),
  }
}

// ============================================================================
// Store
// ============================================================================

export const useNotebookStore = create<NotebookState>((set, get) => ({
  // Initial state
  notebooks: [],
  currentNotebook: null,
  isLoadingNotebooks: false,
  sources: [],
  isLoadingSources: false,
  notes: [],
  isLoadingNotes: false,
  currentSession: null,
  messages: [],
  isLoadingMessages: false,
  isChatting: false,
  isOpenNotebookAvailable: false,
  error: null,

  // ─── Service Health ──────────────────────────────────────────────────────────

  checkServiceHealth: async () => {
    const isAvailable = await OpenNotebookAPI.checkHealth()
    set({ isOpenNotebookAvailable: isAvailable })
  },

  // ─── Notebook Actions ─────────────────────────────────────────────────────────

  fetchNotebooks: async () => {
    set({ isLoadingNotebooks: true, error: null })

    try {
      const openNotebooks = await OpenNotebookAPI.notebooks.list(false)
      const notebooks = openNotebooks.map(mapOpenNotebookToNotebook)
      
      // Also fetch archived notebooks
      const archivedNotebooks = await OpenNotebookAPI.notebooks.list(true)
      const allNotebooks = [
        ...notebooks,
        ...archivedNotebooks.map(mapOpenNotebookToNotebook),
      ]

      set({
        notebooks: allNotebooks,
        isLoadingNotebooks: false,
        isOpenNotebookAvailable: true,
      })
    } catch (error) {
      console.error('Error fetching notebooks:', error)
      let errorMessage = 'Failed to load notebooks'
      
      if (error instanceof Error) {
        if (error.message.includes('fetch')) {
          errorMessage = 'Cannot connect to Open Notebook service. Make sure it is running.'
        } else if (error.message.includes('401')) {
          errorMessage = 'Session expired. Please login again.'
        } else if (error.message.includes('5')) {
          errorMessage = 'Server error. Please try again later.'
        }
      }
      
      set({ 
        error: errorMessage, 
        isLoadingNotebooks: false,
        isOpenNotebookAvailable: false,
      })
    }
  },

  createNotebook: async (title: string, description?: string) => {
    set({ error: null })

    try {
      const openNotebook = await OpenNotebookAPI.notebooks.create({
        name: title,
        description,
      })
      
      const notebook = mapOpenNotebookToNotebook(openNotebook)
      
      set(state => ({
        notebooks: [notebook, ...state.notebooks],
      }))
      
      return notebook
    } catch (error) {
      console.error('Error creating notebook:', error)
      set({ error: 'Failed to create notebook' })
      return null
    }
  },

  selectNotebook: async (notebookId: string) => {
    set({ isLoadingNotebooks: true, error: null })

    try {
      const openNotebook = await OpenNotebookAPI.notebooks.get(notebookId)
      const notebook = mapOpenNotebookToNotebook(openNotebook)
      
      set({
        currentNotebook: notebook,
        isLoadingNotebooks: false,
        sources: [],
        notes: [],
        messages: [],
        currentSession: null,
      })

      // Fetch related data in parallel
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

  updateNotebook: async (notebookId: string, title?: string, description?: string) => {
    try {
      const openNotebook = await OpenNotebookAPI.notebooks.update(notebookId, {
        name: title,
        description,
      })
      
      const updated = mapOpenNotebookToNotebook(openNotebook)
      
      set(state => ({
        notebooks: state.notebooks.map(n => n.id === notebookId ? updated : n),
        currentNotebook: state.currentNotebook?.id === notebookId ? updated : state.currentNotebook,
      }))
    } catch (error) {
      console.error('Error updating notebook:', error)
    }
  },

  deleteNotebook: async (notebookId: string) => {
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

  fetchSources: async (notebookId: string) => {
    set({ isLoadingSources: true })

    try {
      const sources = await OpenNotebookAPI.sources.list(notebookId)
      const mappedSources = sources.map(s => mapSourceToNotebookSource(s, notebookId))
      
      set({ sources: mappedSources, isLoadingSources: false })
    } catch (error) {
      console.error('Error fetching sources:', error)
      set({ isLoadingSources: false })
    }
  },

  uploadSource: async (notebookId: string, file: File, title?: string) => {
    try {
      const source = await OpenNotebookAPI.sources.uploadFile({
        file,
        title,
        notebook_id: notebookId,
        embed: true,
        async_processing: true,
      })
      
      const mappedSource = mapSourceToNotebookSource(source, notebookId)
      
      set(state => ({
        sources: [mappedSource, ...state.sources],
      }))
      
      return mappedSource
    } catch (error) {
      console.error('Error uploading source:', error)
      set({ error: 'Failed to upload file' })
      return null
    }
  },

  addUrlSource: async (notebookId: string, url: string, title?: string) => {
    try {
      const source = await OpenNotebookAPI.sources.createFromUrl({
        url,
        title,
        notebook_id: notebookId,
        embed: true,
        async_processing: true,
      })
      
      const mappedSource = mapSourceToNotebookSource(source, notebookId)
      
      set(state => ({
        sources: [mappedSource, ...state.sources],
      }))
      
      return mappedSource
    } catch (error) {
      console.error('Error adding URL source:', error)
      set({ error: 'Failed to add URL' })
      return null
    }
  },

  addTextSource: async (notebookId: string, title: string, content: string) => {
    try {
      const source = await OpenNotebookAPI.sources.createFromText({
        content,
        title,
        notebook_id: notebookId,
        embed: true,
      })
      
      const mappedSource = mapSourceToNotebookSource(source, notebookId)
      
      set(state => ({
        sources: [mappedSource, ...state.sources],
      }))
      
      return mappedSource
    } catch (error) {
      console.error('Error adding text source:', error)
      set({ error: 'Failed to add text' })
      return null
    }
  },

  deleteSource: async (notebookId: string, sourceId: string) => {
    try {
      // First remove from notebook, then delete the source
      await OpenNotebookAPI.notebooks.removeSource(notebookId, sourceId)
      await OpenNotebookAPI.sources.delete(sourceId)
      
      set(state => ({
        sources: state.sources.filter(s => s.id !== sourceId),
      }))
    } catch (error) {
      console.error('Error deleting source:', error)
    }
  },

  refreshSourceStatus: async (notebookId: string, sourceId: string) => {
    try {
      const status = await OpenNotebookAPI.sources.getStatus(sourceId)
      
      const statusMap: Record<string, NotebookSource['status']> = {
        pending: 'pending',
        processing: 'processing',
        completed: 'ready',
        failed: 'error',
      }
      
      set(state => ({
        sources: state.sources.map(s =>
          s.id === sourceId
            ? { ...s, status: statusMap[status.status] || s.status, error_message: status.error }
            : s
        ),
      }))
    } catch (error) {
      console.error('Error refreshing source status:', error)
    }
  },

  // ─── Note Actions ─────────────────────────────────────────────────────────────

  fetchNotes: async (notebookId: string) => {
    set({ isLoadingNotes: true })

    try {
      const notes = await OpenNotebookAPI.notes.list(notebookId)
      const mappedNotes = notes.map(mapNoteToNotebookNote)
      
      set({ notes: mappedNotes, isLoadingNotes: false })
    } catch (error) {
      console.error('Error fetching notes:', error)
      set({ isLoadingNotes: false })
    }
  },

  createNote: async (notebookId: string, content: string, type: string = 'user_note', title?: string) => {
    try {
      const note = await OpenNotebookAPI.notes.create({
        title: title || 'Untitled Note',
        content,
        notebook_id: notebookId,
        note_type: type,
      })
      
      const mappedNote = mapNoteToNotebookNote(note)
      
      set(state => ({
        notes: [mappedNote, ...state.notes],
      }))
      
      return mappedNote
    } catch (error) {
      console.error('Error creating note:', error)
      set({ error: 'Failed to create note' })
      return null
    }
  },

  updateNote: async (notebookId: string, noteId: string, content?: string, title?: string, isPinned?: boolean) => {
    try {
      const note = await OpenNotebookAPI.notes.update(noteId, {
        content,
        title,
        pinned: isPinned,
      })
      
      const mappedNote = mapNoteToNotebookNote(note)
      
      set(state => ({
        notes: state.notes.map(n => n.id === noteId ? mappedNote : n),
      }))
    } catch (error) {
      console.error('Error updating note:', error)
    }
  },

  deleteNote: async (notebookId: string, noteId: string) => {
    try {
      await OpenNotebookAPI.notes.delete(noteId)
      
      set(state => ({
        notes: state.notes.filter(n => n.id !== noteId),
      }))
    } catch (error) {
      console.error('Error deleting note:', error)
    }
  },

  // ─── Chat Actions ─────────────────────────────────────────────────────────────

  fetchChatHistory: async (notebookId: string) => {
    set({ isLoadingMessages: true })

    try {
      // Get or create a chat session for this notebook
      const sessions = await OpenNotebookAPI.chat.getSessions(notebookId)
      
      let session: ChatSession
      if (sessions.length > 0) {
        // Use the most recent session
        session = sessions[0]
      } else {
        // Create a new session
        session = await OpenNotebookAPI.chat.createSession({
          notebook_id: notebookId,
          title: 'Chat',
        })
      }
      
      // Fetch messages for this session
      const sessionWithMessages = await OpenNotebookAPI.chat.getSession(session.id)
      const messages = sessionWithMessages.messages.map(msg =>
        mapOpenChatMessageToChatMessage(msg, notebookId)
      )
      
      set({
        currentSession: session,
        messages,
        isLoadingMessages: false,
      })
    } catch (error) {
      console.error('Error fetching chat history:', error)
      set({ isLoadingMessages: false })
    }
  },

  sendMessage: async (notebookId: string, message: string, model?: string) => {
    const { currentSession, sources, notes } = get()
    
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
      // Ensure we have a session
      let sessionId = currentSession?.id
      if (!sessionId) {
        const session = await OpenNotebookAPI.chat.createSession({
          notebook_id: notebookId,
          title: 'Chat',
        })
        sessionId = session.id
        set({ currentSession: session })
      }

      // Build context from current sources and notes
      const context = {
        sources: sources.map(s => s.id),
        notes: notes.map(n => n.id),
        use_rag: true,
        include_all_sources: true,
        include_all_notes: true,
      }

      // Send message
      const response = await OpenNotebookAPI.chat.sendMessage({
        session_id: sessionId,
        message,
        context,
        model_override: model,
      })

      // Update messages with response
      const newMessages = response.messages.map(msg =>
        mapOpenChatMessageToChatMessage(msg, notebookId)
      )

      set({
        messages: newMessages,
        isChatting: false,
      })
    } catch (error) {
      console.error('Error sending message:', error)
      set(state => ({
        messages: state.messages.filter(m => m.id !== tempUserMsg.id),
        error: 'Failed to send message',
        isChatting: false,
      }))
    }
  },

  clearChatHistory: async (notebookId: string) => {
    const { currentSession } = get()
    
    try {
      if (currentSession) {
        await OpenNotebookAPI.chat.deleteSession(currentSession.id)
      }
      
      // Create a new session
      const session = await OpenNotebookAPI.chat.createSession({
        notebook_id: notebookId,
        title: 'Chat',
      })
      
      set({
        currentSession: session,
        messages: [],
      })
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
    currentSession: null,
  }),
}))
