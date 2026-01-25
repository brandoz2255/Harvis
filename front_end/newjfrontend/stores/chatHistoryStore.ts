import { create } from 'zustand'

// Use the backend URL from environment, which goes through nginx proxy
const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:9000')
  : ''

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

  // Robustness State
  lastFetchTime: number
  requestInFlight: Set<string>
  retryCount: number
  circuitBreakerOpen: boolean
  circuitBreakerResetTime: number

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
  if (typeof window === 'undefined') return {}
  const token = localStorage.getItem('token')
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

// Request deduplication and robustness helpers
const MIN_REQUEST_INTERVAL = 500 // Minimum 0.5 seconds between requests
const CIRCUIT_BREAKER_THRESHOLD = 3 // Open circuit after 3 failures
const CIRCUIT_BREAKER_TIMEOUT = 10000 // 10 seconds
const MAX_RETRIES = 2 // Maximum retry attempts

export const useChatHistoryStore = create<ChatHistoryState>((set, get) => ({
  // Initial state
  sessions: [],
  currentSession: null,
  isLoadingSessions: false,
  messages: [],
  isLoadingMessages: false,
  isHistoryVisible: false,
  error: null,

  // Robustness state
  lastFetchTime: 0,
  requestInFlight: new Set(),
  retryCount: 0,
  circuitBreakerOpen: false,
  circuitBreakerResetTime: 0,

  // Session actions
  fetchSessions: async () => {
    const state = get()
    const now = Date.now()
    const requestKey = 'fetchSessions'

    // Circuit breaker check
    if (state.circuitBreakerOpen) {
      if (now < state.circuitBreakerResetTime) {
        console.log('🚫 Circuit breaker open - blocking request')
        return
      } else {
        // Reset circuit breaker
        set({ circuitBreakerOpen: false, retryCount: 0 })
      }
    }

    // Prevent concurrent fetches and rapid requests
    if (state.isLoadingSessions || state.requestInFlight.has(requestKey)) {
      console.log('⏳ Request already in progress, skipping')
      return
    }

    // Rate limiting - only for rapid successive calls
    if (now - state.lastFetchTime < MIN_REQUEST_INTERVAL && state.sessions.length > 0) {
      console.log('⏰ Rate limited - too soon since last request')
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

    // Mark request as in flight
    set({
      isLoadingSessions: true,
      error: null,
      lastFetchTime: now,
      requestInFlight: new Set(Array.from(state.requestInFlight).concat(requestKey))
    })

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions`, {
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
          ...getAuthHeaders(),
        },
        signal: AbortSignal.timeout(10000), // 10 second timeout
      })

      if (response.ok) {
        const sessions = await response.json()
        const currentState = get()
        const newRequestInFlight = new Set(Array.from(currentState.requestInFlight).filter(key => key !== requestKey))

        set({
          sessions: Array.isArray(sessions) ? sessions : [],
          isLoadingSessions: false,
          error: null,
          retryCount: 0, // Reset on success
          requestInFlight: newRequestInFlight
        })
      } else {
        const errorText = await response.text()
        console.error('Failed to fetch sessions:', response.statusText, errorText)

        const currentState = get()
        const newRequestInFlight = new Set(Array.from(currentState.requestInFlight).filter(key => key !== requestKey))
        const newRetryCount = currentState.retryCount + 1

        // Handle auth errors specifically
        if (response.status === 401) {
          localStorage.removeItem('token') // Clear invalid token
          set({
            isLoadingSessions: false,
            error: 'Session expired. Please login again.',
            requestInFlight: newRequestInFlight
          })
        } else {
          // Open circuit breaker if too many failures
          const shouldOpenCircuit = newRetryCount >= CIRCUIT_BREAKER_THRESHOLD

          set({
            isLoadingSessions: false,
            error: shouldOpenCircuit ? 'Service temporarily unavailable' : 'Could not load chat history',
            retryCount: newRetryCount,
            circuitBreakerOpen: shouldOpenCircuit,
            circuitBreakerResetTime: shouldOpenCircuit ? Date.now() + CIRCUIT_BREAKER_TIMEOUT : 0,
            requestInFlight: newRequestInFlight
          })
        }
      }
    } catch (error) {
      console.error('Error fetching sessions:', error)
      const currentState = get()
      const newRequestInFlight = new Set(Array.from(currentState.requestInFlight).filter(key => key !== requestKey))
      const newRetryCount = currentState.retryCount + 1
      const shouldOpenCircuit = newRetryCount >= CIRCUIT_BREAKER_THRESHOLD

      set({
        isLoadingSessions: false,
        error: shouldOpenCircuit
          ? 'Service temporarily unavailable'
          : error instanceof Error && error.name === 'AbortError'
            ? 'Request timed out'
            : 'Could not load chat history',
        retryCount: newRetryCount,
        circuitBreakerOpen: shouldOpenCircuit,
        circuitBreakerResetTime: shouldOpenCircuit ? Date.now() + CIRCUIT_BREAKER_TIMEOUT : 0,
        requestInFlight: newRequestInFlight
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

      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
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
      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
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
      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
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
      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}/title`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
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
    const now = Date.now()
    const requestKey = `fetchMessages-${sessionId}`

    console.log(`🔄 Starting to fetch messages for session: ${sessionId}`)
    console.log(`🔄 Current loading state:`, currentState.isLoadingMessages)
    console.log(`🔄 Current session:`, currentState.currentSession?.id)

    // Circuit breaker check
    if (currentState.circuitBreakerOpen) {
      if (now < currentState.circuitBreakerResetTime) {
        console.log('🚫 Circuit breaker open - blocking message request')
        return
      }
    }

    // Prevent concurrent requests for the same session
    if (currentState.requestInFlight.has(requestKey)) {
      console.log(`⏳ Message request already in progress for session ${sessionId}, skipping`)
      return
    }

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

    // Mark request as in flight and set loading state
    set({
      isLoadingMessages: true,
      error: null,
      requestInFlight: new Set(Array.from(currentState.requestInFlight).concat(requestKey))
    })

    try {
      const authHeaders = getAuthHeaders()
      console.log(`🔐 Auth headers for session fetch:`, authHeaders.Authorization ? 'Present' : 'Missing')

      const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}`, {
        headers: {
          'Content-Type': 'application/json',
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=300',
          ...(authHeaders.Authorization ? { 'Authorization': authHeaders.Authorization } : {}),
        },
        signal: AbortSignal.timeout(10000), // 10 second timeout
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
        const newRequestInFlight = new Set(Array.from(state.requestInFlight).filter(key => key !== requestKey))

        // Update session info if provided and matches current session
        const sessionUpdate = data.session && state.currentSession?.id === data.session.id
          ? { currentSession: data.session }
          : {}

        set({
          messages,
          isLoadingMessages: false,
          error: null,
          retryCount: 0, // Reset on success
          requestInFlight: newRequestInFlight,
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

        const state = get()
        const newRequestInFlight = new Set(Array.from(state.requestInFlight).filter(key => key !== requestKey))
        const newRetryCount = state.retryCount + 1

        // Handle auth errors specifically
        if (response.status === 401) {
          localStorage.removeItem('token') // Clear invalid token
          set({
            error: 'Session expired. Please login again.',
            messages: [],
            isLoadingMessages: false,
            requestInFlight: newRequestInFlight
          })
        } else {
          // Open circuit breaker if too many failures
          const shouldOpenCircuit = newRetryCount >= CIRCUIT_BREAKER_THRESHOLD

          set({
            error: shouldOpenCircuit
              ? 'Service temporarily unavailable'
              : response.status === 404
                ? 'Chat session not found'
                : 'Could not load chat history',
            messages: [],
            isLoadingMessages: false,
            retryCount: newRetryCount,
            circuitBreakerOpen: shouldOpenCircuit,
            circuitBreakerResetTime: shouldOpenCircuit ? Date.now() + CIRCUIT_BREAKER_TIMEOUT : 0,
            requestInFlight: newRequestInFlight
          })
        }
      }
    } catch (error) {
      const isTimeout = error instanceof Error && error.name === 'AbortError'
      console.error(`❌ Fetch error for session ${sessionId}:`, error)

      const state = get()
      const newRequestInFlight = new Set(Array.from(state.requestInFlight).filter(key => key !== requestKey))
      const newRetryCount = state.retryCount + 1
      const shouldOpenCircuit = newRetryCount >= CIRCUIT_BREAKER_THRESHOLD

      set({
        error: shouldOpenCircuit
          ? 'Service temporarily unavailable'
          : isTimeout
            ? 'Request timed out'
            : 'Could not load chat history',
        messages: [],
        isLoadingMessages: false,
        retryCount: newRetryCount,
        circuitBreakerOpen: shouldOpenCircuit,
        circuitBreakerResetTime: shouldOpenCircuit ? Date.now() + CIRCUIT_BREAKER_TIMEOUT : 0,
        requestInFlight: newRequestInFlight
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

  // Retry mechanism with exponential backoff
  retryWithExponentialBackoff: async (operation: () => Promise<void>, maxRetries: number = MAX_RETRIES) => {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        await operation()
        return // Success, exit retry loop
      } catch (error) {
        console.error(`Attempt ${attempt + 1} failed:`, error)

        if (attempt === maxRetries - 1) {
          // Final attempt failed
          throw error
        }

        // Exponential backoff: 1s, 2s, 4s, 8s...
        const delay = Math.min(1000 * Math.pow(2, attempt), 10000) // Max 10 seconds
        console.log(`Retrying in ${delay}ms...`)
        await new Promise(resolve => setTimeout(resolve, delay))
      }
    }
  },
}))