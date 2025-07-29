import { create } from 'zustand'

export interface ChatSession {
  id: string
  user_id: number
  title: string
  created_at: string
  updated_at: string
  last_message_at: string
  message_count: number
  model_used?: string
  is_active: boolean
}

export interface ChatMessage {
  id?: number
  session_id: string
  user_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  reasoning?: string
  model_used?: string
  input_type: 'text' | 'voice' | 'screen'
  metadata: Record<string, any>
  created_at?: string
}

export interface MessageHistoryResponse {
  messages: ChatMessage[]
  session: ChatSession
  total_count: number
}

interface ChatHistoryState {
  // Sessions
  sessions: ChatSession[]
  currentSession: ChatSession | null
  isLoadingSessions: boolean
  
  // Messages
  messages: ChatMessage[]
  isLoadingMessages: boolean
  
  // UI State
  isHistoryVisible: boolean
  
  // Error State
  error: string | null
  
  // Actions
  fetchSessions: () => Promise<void>
  createNewChat: () => Promise<ChatSession | null>
  createSession: (title?: string, modelUsed?: string) => Promise<ChatSession | null>
  selectSession: (sessionId: string) => Promise<void>
  deleteSession: (sessionId: string) => Promise<void>
  updateSessionTitle: (sessionId: string, title: string) => Promise<void>
  
  fetchSessionMessages: (sessionId: string) => Promise<void>
  clearMessages: () => void
  clearCurrentChat: () => void
  
  toggleHistoryVisibility: () => void
  setCurrentSession: (session: ChatSession | null) => void
  setError: (error: string | null) => void
}

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

export const useChatHistoryStore = create<ChatHistoryState>((set, get) => ({
  // Initial state
  sessions: [],
  currentSession: null,
  isLoadingSessions: false,
  messages: [],
  isLoadingMessages: false,
  isHistoryVisible: false,
  error: null,
  
  // Session actions
  fetchSessions: async () => {
    set({ isLoadingSessions: true })
    try {
      const response = await fetch('/api/chat-history/sessions', {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })
      
      if (response.ok) {
        const sessions = await response.json()
        set({ sessions, isLoadingSessions: false })
      } else {
        console.error('Failed to fetch sessions:', response.statusText)
        set({ isLoadingSessions: false })
      }
    } catch (error) {
      console.error('Error fetching sessions:', error)
      set({ isLoadingSessions: false })
    }
  },
  
  createNewChat: async () => {
    try {
      set({ error: null, isLoadingSessions: true })
      
      const response = await fetch('/api/chat-history/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          title: 'New Chat',
        }),
      })
      
      if (response.ok) {
        const newSession = await response.json()
        set(state => ({
          sessions: [newSession, ...state.sessions],
          currentSession: newSession,
          messages: [], // Clear messages for new chat
          isLoadingSessions: false,
          error: null,
        }))
        
        console.log(`🆕 Created new chat session: ${newSession.id}`)
        return newSession
      } else {
        const errorText = await response.text()
        set({ 
          error: 'Could not start new chat', 
          isLoadingSessions: false 
        })
        console.error('Failed to create new chat:', errorText)
        return null
      }
    } catch (error) {
      set({ 
        error: 'Could not start new chat', 
        isLoadingSessions: false 
      })
      console.error('Error creating new chat:', error)
      return null
    }
  },

  createSession: async (title = 'New Chat', modelUsed) => {
    try {
      const response = await fetch('/api/chat-history/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          title,
          model_used: modelUsed,
        }),
      })
      
      if (response.ok) {
        const newSession = await response.json()
        set(state => ({
          sessions: [newSession, ...state.sessions],
          currentSession: newSession,
        }))
        return newSession
      } else {
        console.error('Failed to create session:', response.statusText)
        return null
      }
    } catch (error) {
      console.error('Error creating session:', error)
      return null
    }
  },
  
  selectSession: async (sessionId: string) => {
    const session = get().sessions.find(s => s.id === sessionId)
    const currentSession = get().currentSession
    
    // Prevent reselecting the same session
    if (session && session.id !== currentSession?.id) {
      try {
        set({ 
          currentSession: session, 
          error: null,
          messages: [] // Clear messages immediately when switching
        })
        
        console.log(`🔄 Switching to chat session: ${sessionId}`)
        
        // Fetch messages for this session
        await get().fetchSessionMessages(sessionId)
        
      } catch (error) {
        set({ 
          error: 'Could not load chat history',
          messages: [] 
        })
        console.error('Error selecting session:', error)
      }
    }
  },
  
  deleteSession: async (sessionId: string) => {
    try {
      const response = await fetch(`/api/chat-history/sessions/${sessionId}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
      })
      
      if (response.ok) {
        set(state => ({
          sessions: state.sessions.filter(s => s.id !== sessionId),
          currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
          messages: state.currentSession?.id === sessionId ? [] : state.messages,
        }))
      } else {
        console.error('Failed to delete session:', response.statusText)
      }
    } catch (error) {
      console.error('Error deleting session:', error)
    }
  },
  
  updateSessionTitle: async (sessionId: string, title: string) => {
    try {
      const response = await fetch(`/api/chat-history/sessions/${sessionId}/title`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({ title }),
      })
      
      if (response.ok) {
        set(state => ({
          sessions: state.sessions.map(s => 
            s.id === sessionId ? { ...s, title } : s
          ),
          currentSession: state.currentSession?.id === sessionId 
            ? { ...state.currentSession, title } 
            : state.currentSession,
        }))
      } else {
        console.error('Failed to update session title:', response.statusText)
      }
    } catch (error) {
      console.error('Error updating session title:', error)
    }
  },
  
  // Message actions
  fetchSessionMessages: async (sessionId: string) => {
    const currentState = get()
    
    // Prevent fetching if already loading for the same session
    if (currentState.isLoadingMessages && currentState.currentSession?.id === sessionId) {
      return
    }
    
    set({ isLoadingMessages: true, error: null })
    try {
      const authHeaders = getAuthHeaders()
      const response = await fetch(`/api/chat-history/sessions/${sessionId}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders.Authorization ? { 'Authorization': authHeaders.Authorization } : {}),
        },
      })
      
      if (response.ok) {
        const data: MessageHistoryResponse = await response.json()
        
        // Only update messages if this is still the current session
        const state = get()
        if (state.currentSession?.id === sessionId) {
          set({ 
            messages: data.messages || [],
            isLoadingMessages: false,
            error: null,
          })
          
          console.log(`📨 Loaded ${data.messages?.length || 0} messages for session ${sessionId}`)
        }
      } else {
        const errorText = await response.text()
        set({ 
          error: 'Could not load chat history',
          messages: [],
          isLoadingMessages: false 
        })
        console.error('Failed to fetch messages:', errorText)
      }
    } catch (error) {
      set({ 
        error: 'Could not load chat history',
        messages: [],
        isLoadingMessages: false 
      })
      console.error('Error fetching messages:', error)
    }
  },
  
  clearMessages: () => {
    set({ messages: [] })
  },
  
  clearCurrentChat: () => {
    set({ 
      messages: [],
      currentSession: null,
      error: null,
    })
    console.log('🧹 Cleared current chat')
  },
  
  // UI actions
  toggleHistoryVisibility: () => {
    set(state => ({ isHistoryVisible: !state.isHistoryVisible }))
  },
  
  setCurrentSession: (session: ChatSession | null) => {
    set({ currentSession: session })
  },
  
  setError: (error: string | null) => {
    set({ error })
  },
}))