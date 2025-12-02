/**
 * IDE AI API Client
 * Provides typed interfaces for IDE AI features:
 * - Copilot inline suggestions
 * - AI Assistant chat
 * - Code change proposals and diff application
 */

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface CopilotSuggestion {
  suggestion: string
  range: {
    start: number
    end: number
  }
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ChatAttachment {
  path: string
  content?: string
}

export interface DiffProposal {
  draft_content: string | null
  diff: string | null
  stats: {
    lines_added: number
    lines_removed: number
    hunks: number
  }
  base_etag: string
}

export interface DiffApplyResult {
  saved: boolean
  bytes: number
  updated_at: string
  new_etag: string
}

export interface DiffConflict {
  conflict: true
  current_etag: string
  current_content: string
}

export interface ProviderInfo {
  id: string
  label: string
  type: 'ollama' | 'cloud'
  capabilities: string[]
}

export interface ProvidersResponse {
  providers: ProviderInfo[]
}

// ─── Utilities ─────────────────────────────────────────────────────────────────

function getAuthToken(): string {
  // Get JWT token from localStorage (only available client-side)
  if (typeof window === 'undefined') return ''
  try {
    return localStorage.getItem('access_token') || ''
  } catch {
    return ''
  }
}

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  // Include Authorization header if token exists (for backward compat)
  // But prefer cookies for same-origin requests
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

/**
 * Fetch Server-Sent Events (SSE) stream
 * Yields chunks as they arrive
 * Includes credentials to send cookies
 */
async function* fetchSSE(url: string, body: any): AsyncGenerator<string, void, unknown> {
  const response = await fetch(url, {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include', // Send cookies
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`HTTP ${response.status}: ${text}`)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('Response body is not readable')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim()
          if (data) {
            try {
              const parsed = JSON.parse(data)
              if (parsed.error) {
                throw new Error(parsed.error)
              }
              if (parsed.done) {
                return
              }
              if (parsed.token) {
                yield parsed.token
              }
            } catch (e) {
              console.error('Failed to parse SSE data:', data, e)
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ─── API Clients ───────────────────────────────────────────────────────────────

export const IDECopilotAPI = {
  /**
   * Request inline code suggestion
   * @returns Promise with suggestion text and range
   */
  async suggest(
    session_id: string,
    filepath: string,
    language: string,
    content: string,
    cursor_offset: number,
    neighbor_files?: Array<{ path: string; content: string }>,
    model?: string
  ): Promise<CopilotSuggestion> {
    const response = await fetch('/api/ide/copilot/suggest', {
      method: 'POST',
      headers: getAuthHeaders(),
      credentials: 'include', // Send cookies
      body: JSON.stringify({
        session_id,
        filepath,
        language,
        content,
        cursor_offset,
        neighbor_files,
        model,
      }),
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(`Copilot suggest failed: ${text}`)
    }

    return response.json()
  },
}

export const IDEChatAPI = {
  /**
   * Send message to IDE Assistant
   * @returns AsyncGenerator yielding response tokens as they stream
   */
  async *send(
    session_id: string,
    message: string,
    history: ChatMessage[],
    attachments?: ChatAttachment[],
    context?: any,
    model: string = 'mistral'
  ): AsyncGenerator<string, void, unknown> {
    yield* fetchSSE('/api/ide/chat/send', {
      session_id,
      message,
      history,
      attachments,
      context,
      model,
    })
  },

  /**
   * Request AI to propose code changes (uses new /api/ide/diff/propose endpoint)
   * @param mode - 'draft' returns full content, 'unified_diff' returns only diff
   * @returns Promise with draft content, diff, stats, and base_etag
   */
  async proposeDiff(
    session_id: string,
    filepath: string,
    instructions: string,
    base_content?: string,
    selection?: { start_line: number; end_line: number; text: string },
    mode: 'draft' | 'unified_diff' = 'draft'
  ): Promise<DiffProposal> {
    console.log('[IDEChatAPI] proposeDiff called', {
      session_id,
      filepath,
      instructions,
      baseContentLength: base_content?.length || 0,
      hasSelection: !!selection,
      mode
    })

    const body = {
      session_id,
      filepath,
      base_content,
      instructions,
      selection,
      mode,
    }
    console.log('[IDEChatAPI] Request body:', JSON.stringify(body).substring(0, 200))

    const headers = getAuthHeaders()
    console.log('[IDEChatAPI] Request headers:', headers)

    const response = await fetch('/api/ide/diff/propose', {
      method: 'POST',
      headers,
      credentials: 'include', // Send cookies
      body: JSON.stringify(body),
    })

    console.log('[IDEChatAPI] Response status:', response.status, response.statusText)

    if (!response.ok) {
      const text = await response.text()
      console.error('[IDEChatAPI] Request failed:', text)
      throw new Error(`Propose diff failed: ${text}`)
    }

    const result = await response.json()
    console.log('[IDEChatAPI] Response received:', {
      hasDraft: !!result.draft_content,
      hasDiff: !!result.diff,
      stats: result.stats
    })
    return result
  },
}

export const IDEDiffAPI = {
  /**
   * Apply proposed changes to file
   * @param base_etag - Optional ETag for optimistic concurrency (conflict detection)
   * @returns Promise with save result including new_etag
   * @throws Error with conflict details if 409 conflict detected
   */
  async apply(
    session_id: string,
    filepath: string,
    draft_content: string,
    base_etag?: string
  ): Promise<DiffApplyResult> {
    const response = await fetch('/api/ide/diff/apply', {
      method: 'POST',
      headers: getAuthHeaders(),
      credentials: 'include', // Send cookies
      body: JSON.stringify({
        session_id,
        filepath,
        draft_content,
        base_etag,
      }),
    })

    if (!response.ok) {
      // Handle 409 conflict specially
      if (response.status === 409) {
        try {
          const conflict: DiffConflict = await response.json()
          const error = new Error('Conflict: File changed since proposal') as any
          error.status = 409
          error.conflict = conflict
          throw error
        } catch (e) {
          // If parsing fails, throw generic error
          if (e instanceof Error && (e as any).conflict) throw e
          const text = await response.text()
          throw new Error(`Apply diff failed: ${text}`)
        }
      }
      const text = await response.text()
      throw new Error(`Apply diff failed: ${text}`)
    }

    return response.json()
  },
}

export const IDEProvidersAPI = {
  /**
   * Get list of available AI providers/models
   * @returns Promise with list of providers
   */
  async getProviders(): Promise<ProvidersResponse> {
    const response = await fetch('/api/ide/providers', {
      method: 'GET',
      headers: getAuthHeaders(),
      credentials: 'include', // Send cookies
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(`Get providers failed: ${text}`)
    }

    return response.json()
  },
}

