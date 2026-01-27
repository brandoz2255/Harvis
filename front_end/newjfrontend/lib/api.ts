// Use relative paths to go through the nginx proxy
const API_BASE_URL = ''

export const getAuthHeaders = (): Record<string, string> => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}

// Retry utility with exponential backoff
async function fetchWithRetry(
  url: string,
  options: RequestInit,
  maxRetries: number = 2,
  timeoutMs: number = 3600000 // 1 hour for local hardware
): Promise<Response> {
  let lastError: Error | null = null

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const startTime = Date.now()
    try {
      // Create abort controller for timeout
      const controller = new AbortController()
      const timeoutId = setTimeout(() => {
        console.error(`⏱️ Request timeout after ${timeoutMs}ms (attempt ${attempt + 1}/${maxRetries + 1})`)
        controller.abort()
      }, timeoutMs)
      console.log(`📤 [Attempt ${attempt + 1}/${maxRetries + 1}] Fetching ${url}`)

      const response = await fetch(url, {
        ...options,
        headers: {
          ...options.headers,
          'Connection': 'keep-alive',
          'Keep-Alive': 'timeout=3600'
        },
        signal: controller.signal,
      })

      clearTimeout(timeoutId)
      const elapsed = Date.now() - startTime
      console.log(`📥 Response received in ${elapsed}ms with status ${response.status}`)

      // Return successful response
      return response

    } catch (error) {
      const elapsed = Date.now() - startTime
      lastError = error as Error

      console.error(`❌ [Attempt ${attempt + 1}/${maxRetries + 1}] Request failed after ${elapsed}ms:`, error)

      // Don't retry on abort (user cancelled)
      if (error instanceof Error && error.name === 'AbortError') {
        if (elapsed >= timeoutMs) {
          throw new Error(`Request timed out after ${timeoutMs}ms. The backend may be processing your request. Please try again or check your connection.`)
        }
        throw error
      }

      // Retry on network errors
      if (attempt < maxRetries) {
        const backoffDelay = Math.min(1000 * Math.pow(2, attempt), 5000)
        console.log(`🔄 Retrying in ${backoffDelay}ms...`)
        await new Promise(resolve => setTimeout(resolve, backoffDelay))
        continue
      }
    }
  }

  // All retries exhausted
  throw new Error(
    `Network error after ${maxRetries + 1} attempts. ` +
    `Please check: (1) You're accessing via localhost:9000 (not :3000), ` +
    `(2) Backend is running, (3) Your internet connection. ` +
    `Original error: ${lastError?.message || 'Unknown error'}`
  )
}

export const apiClient = {
  // Chat endpoints
  async sendMessage(payload: {
    message: string
    history?: any[]
    model?: string
    session_id?: string | null
    tempId?: string
  }) {
    try {
      const response = await fetchWithRetry(
        `${API_BASE_URL}/api/chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
          },
          body: JSON.stringify(payload),
          credentials: 'include',
        },
        2, // max 2 retries
        3600000 // 1 hour timeout
      )

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`Server error (${response.status}): ${errorText}`)
      }

      return response.json()
    } catch (error) {
      console.error('❌ sendMessage error:', error)
      throw error
    }
  },

  async sendResearchMessage(payload: {
    message: string
    history?: any[]
    model?: string
    session_id?: string | null
    tempId?: string
    enableWebSearch?: boolean
    exaggeration?: number
    temperature?: number
    cfg_weight?: number
  }) {
    try {
      const response = await fetchWithRetry(
        `${API_BASE_URL}/api/research-chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
          },
          body: JSON.stringify(payload),
          credentials: 'include',
        },
        2, // max 2 retries
        3600000 // 1 hour timeout for research
      )

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`Server error (${response.status}): ${errorText}`)
      }

      return response.json()
    } catch (error) {
      console.error('❌ sendResearchMessage error:', error)
      throw error
    }
  },

  // Model endpoints
  async getAvailableModels() {
    const response = await fetch(`${API_BASE_URL}/api/ollama-models`, {
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
    })

    if (!response.ok) {
      throw new Error('Failed to fetch models')
    }

    const models = await response.json()
    // Backend returns array of model names, transform to expected format
    return {
      models: Array.isArray(models) ? models.map((name: string) => ({
        name,
        displayName: name,
        status: 'available'
      })) : []
    }
  },

  // Web search endpoint
  async performWebSearch(query: string, model?: string, maxResults: number = 5) {
    const response = await fetch(`${API_BASE_URL}/api/web-search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
      },
      body: JSON.stringify({
        query,
        model: model || 'mistral',
        maxResults,
      }),
      credentials: 'include',
    })

    if (!response.ok) {
      throw new Error('Web search failed')
    }

    return response.json()
  },

  // Chat history endpoints
  async getSessions() {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions`, {
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
    })

    if (!response.ok) {
      throw new Error('Failed to fetch sessions')
    }

    return response.json()
  },

  async createSession(title: string, modelUsed?: string) {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        title,
        model_used: modelUsed,
      }),
    })

    if (!response.ok) {
      throw new Error('Failed to create session')
    }

    return response.json()
  },

  async getSessionMessages(sessionId: string) {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}`, {
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
    })

    if (!response.ok) {
      throw new Error('Failed to fetch session messages')
    }

    return response.json()
  },

  async deleteSession(sessionId: string) {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
    })

    if (!response.ok) {
      throw new Error('Failed to delete session')
    }

    return response.json()
  },

  async updateSessionTitle(sessionId: string, title: string) {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/sessions/${sessionId}/title`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({ title }),
    })

    if (!response.ok) {
      throw new Error('Failed to update session title')
    }

    return response.json()
  },

  async persistMessage(payload: {
    session_id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    reasoning?: string
    model_used?: string
    input_type?: 'text' | 'voice' | 'screen'
    metadata?: Record<string, any>
  }) {
    const response = await fetch(`${API_BASE_URL}/api/chat-history/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Connection': 'keep-alive',
        'Keep-Alive': 'timeout=3600',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(payload),
      credentials: 'include',
    })

    if (!response.ok) {
      throw new Error('Failed to persist message')
    }

    return response.json()
  },
}
