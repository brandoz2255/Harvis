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
  refreshSessionMessages: (sessionId?: string) => Promise<void>
  
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
    const state = get()
    
    // Prevent concurrent fetches
    if (state.isLoadingSessions) {
      return
    }

    // Check if user is logged in
    const token = localStorage.getItem('token')
    if (!token) {
      console.log('❌ No auth token found, user needs to login')
      set({ 
        isLoadingSessions: false,
        error: 'Please login to view chat history'
      })
      return
    }
    
    set({ isLoadingSessions: true, error: null })
    try {
      const response = await fetch('/api/chat-history/sessions', {
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        signal: AbortSignal.timeout(10000), // 10 second timeout
      })
      
      if (response.ok) {
        const sessions = await response.json()
        set({ 
          sessions: Array.isArray(sessions) ? sessions : [],
          isLoadingSessions: false,
          error: null 
        })
      } else {
        const errorText = await response.text()
        console.error('Failed to fetch sessions:', response.statusText, errorText)
        
        // Handle auth errors specifically
        if (response.status === 401) {
          localStorage.removeItem('token') // Clear invalid token
          set({ 
            isLoadingSessions: false,
            error: 'Session expired. Please login again.'
          })
        } else {
          set({ 
            isLoadingSessions: false,
            error: 'Could not load chat history'
          })
        }
      }
    } catch (error) {
      console.error('Error fetching sessions:', error)
      set({ 
        isLoadingSessions: false,
        error: error instanceof Error && error.name === 'AbortError' 
          ? 'Request timed out' 
          : 'Could not load chat history'
      })
    }
  },
  
  createNewChat: async () => {
    const state = get()
    
    // Prevent concurrent new chat creation
    if (state.isLoadingSessions) {
      return null
    }
    
    try {
      set({ error: null, isLoadingSessions: true })
      
      // Generate unique title with timestamp
      const now = new Date()
      const title = `New Chat ${now.toLocaleString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        hour: '2-digit', 
        minute: '2-digit' 
      })}`
      
      const response = await fetch('/api/chat-history/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          title,
        }),
        signal: AbortSignal.timeout(10000), // 10 second timeout
      })
      
      if (response.ok) {
        const newSession = await response.json()
        set(state => ({
          sessions: [newSession, ...state.sessions],
          currentSession: newSession,
          messages: [], // Completely clear messages for new chat
          isLoadingSessions: false,
          isLoadingMessages: false, // Reset message loading state
          error: null,
        }))
        
        console.log(`🆕 Created new chat session: ${newSession.id} with title: "${title}"`)
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
      const isTimeout = error instanceof Error && error.name === 'AbortError'
      set({ 
        error: isTimeout ? 'New chat creation timed out' : 'Could not start new chat', 
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
    const state = get()
    const session = state.sessions.find(s => s.id === sessionId)
    
    console.log(`🔄 Switching to session ${sessionId}`)
    console.log(`📋 Session found:`, session ? 'Yes' : 'No')
    console.log(`🔄 Current session:`, state.currentSession?.id)
    console.log(`⏳ Already loading:`, state.isLoadingMessages)
    
    // Prevent reselecting the same session or selecting invalid sessions
    if (!session) {
      console.warn(`❌ Session ${sessionId} not found in sessions list`)
      return
    }
    
    if (session.id === state.currentSession?.id && state.messages.length > 0 && !state.isLoadingMessages) {
      console.log(`⏭️ Already on session ${sessionId} with messages loaded, skipping`)
      return
    }
    
    // Don't prevent concurrent switches, but ensure proper cleanup
    try {
      console.log(`✅ Setting current session to: ${session.title} (${sessionId})`)
      
      // Set session first, then load messages
      set({ 
        currentSession: session, 
        error: null,
        messages: [], // Clear messages immediately when switching
        isLoadingMessages: true
      })
      
      // Fetch messages for this session
      console.log(`📞 Calling fetchSessionMessages for: ${sessionId}`)
      
      // Set a timeout to reset loading state if fetch gets stuck
      const loadingTimeout = setTimeout(() => {
        const currentState = get()
        if (currentState.isLoadingMessages && currentState.currentSession?.id === sessionId) {
          console.log(`⏰ Loading timeout for session ${sessionId}, resetting state`)
          set({ 
            isLoadingMessages: false,
            error: 'Loading timed out, please try again'
          })
        }
      }, 20000) // 20 second timeout
      
      try {
        await get().fetchSessionMessages(sessionId)
        clearTimeout(loadingTimeout)
      } catch (error) {
        clearTimeout(loadingTimeout)
        throw error
      }
      
    } catch (error) {
      console.error(`❌ Error selecting session ${sessionId}:`, error)
      set({ 
        error: 'Could not load chat history',
        messages: [],
        isLoadingMessages: false
      })
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
    
    console.log(`🔄 Starting to fetch messages for session: ${sessionId}`)
    console.log(`🔄 Current loading state:`, currentState.isLoadingMessages)
    console.log(`🔄 Current session:`, currentState.currentSession?.id)

    // Check authentication first
    const token = localStorage.getItem('token')
    if (!token) {
      console.log('❌ No auth token found, cannot fetch messages')
      set({ 
        error: 'Please login to view chat messages',
        messages: [],
        isLoadingMessages: false 
      })
      return
    }
    
    // Only skip if we're loading AND already have messages for this session
    if (currentState.isLoadingMessages && currentState.currentSession?.id === sessionId && currentState.messages.length > 0) {
      console.log(`⏳ Already loading messages for session ${sessionId} and have messages, skipping duplicate request`)
      return
    }
    
    // Always set loading state to ensure UI updates
    set({ isLoadingMessages: true, error: null })
    
    try {
      const authHeaders = getAuthHeaders()
      console.log(`🔐 Auth headers for session fetch:`, authHeaders.Authorization ? 'Present' : 'Missing')
      
      const response = await fetch(`/api/chat-history/sessions/${sessionId}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders.Authorization ? { 'Authorization': authHeaders.Authorization } : {}),
        },
        signal: AbortSignal.timeout(15000), // Increased timeout to 15 seconds
      })
      
      console.log(`🌐 API response status: ${response.status} ${response.statusText}`)
      
      if (response.ok) {
        const data: MessageHistoryResponse = await response.json()
        console.log(`📊 Raw API response:`, { 
          messagesCount: data.messages?.length, 
          sessionTitle: data.session?.title,
          totalCount: data.total_count 
        })
        
        // Always update if we got a successful response
        const state = get()
        const messages = Array.isArray(data.messages) ? data.messages : []
        
        // Update session info if provided and matches current session
        const sessionUpdate = data.session && state.currentSession?.id === data.session.id 
          ? { currentSession: data.session } 
          : {}
        
        set({ 
          messages,
          isLoadingMessages: false,
          error: null,
          ...sessionUpdate
        })
        
        console.log(`📨 Successfully loaded ${messages.length} messages for session ${sessionId}`)
        
        // If we loaded messages but they're not showing, force a state update
        if (messages.length > 0) {
          // Small delay to ensure state propagation
          setTimeout(() => {
            const currentState = get()
            if (currentState.currentSession?.id === sessionId && currentState.messages.length !== messages.length) {
              console.log(`🔄 Force updating messages state for session ${sessionId}`)
              set({ messages })
            }
          }, 100)
        }
      } else {
        const errorText = await response.text()
        console.error(`❌ API Error ${response.status}:`, errorText)
        
        // Handle auth errors specifically
        if (response.status === 401) {
          localStorage.removeItem('token') // Clear invalid token
          set({ 
            error: 'Session expired. Please login again.',
            messages: [],
            isLoadingMessages: false 
          })
        } else {
          set({ 
            error: response.status === 404 ? 'Chat session not found' : 'Could not load chat history',
            messages: [],
            isLoadingMessages: false 
          })
        }
      }
    } catch (error) {
      const isTimeout = error instanceof Error && error.name === 'AbortError'
      console.error(`❌ Fetch error for session ${sessionId}:`, error)
      set({ 
        error: isTimeout ? 'Request timed out' : 'Could not load chat history',
        messages: [],
        isLoadingMessages: false 
      })
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
      isLoadingMessages: false, // Reset loading state
      isLoadingSessions: false, // Reset session loading state
    })
    console.log('🧹 Cleared current chat - complete context reset')
  },
  
  // Add a method to force refresh session messages
  refreshSessionMessages: async (sessionId?: string) => {
    const state = get()
    const targetSessionId = sessionId || state.currentSession?.id
    
    if (!targetSessionId) {
      console.log('🔄 No session to refresh')
      return
    }
    
    console.log(`🔄 Force refreshing messages for session: ${targetSessionId}`)
    
    // Force clear messages first
    set({ 
      messages: [],
      isLoadingMessages: true,
      error: null
    })
    
    // Small delay to ensure UI updates
    await new Promise(resolve => setTimeout(resolve, 50))
    
    // Fetch messages
    await get().fetchSessionMessages(targetSessionId)
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