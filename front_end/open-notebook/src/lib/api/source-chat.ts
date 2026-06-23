import apiClient from './client'
import { getApiUrl } from '@/lib/config'
import {
  SourceChatSession,
  SourceChatSessionWithMessages,
  CreateSourceChatSessionRequest,
  UpdateSourceChatSessionRequest,
  SendMessageRequest
} from '@/lib/types/api'

export const sourceChatApi = {
  // Session management
  createSession: async (sourceId: string, data: Omit<CreateSourceChatSessionRequest, 'source_id'>) => {
    // Extract clean ID without "source:" prefix for the request body
    const cleanId = sourceId.startsWith('source:') ? sourceId.slice(7) : sourceId
    const response = await apiClient.post<SourceChatSession>(
      `/sources/${sourceId}/chat/sessions`,
      { ...data, source_id: cleanId }  // Include source_id in the request body
    )
    return response.data
  },

  listSessions: async (sourceId: string) => {
    const response = await apiClient.get<SourceChatSession[]>(
      `/sources/${sourceId}/chat/sessions`
    )
    return response.data
  },

  getSession: async (sourceId: string, sessionId: string) => {
    const response = await apiClient.get<SourceChatSessionWithMessages>(
      `/sources/${sourceId}/chat/sessions/${sessionId}`
    )
    return response.data
  },

  updateSession: async (sourceId: string, sessionId: string, data: UpdateSourceChatSessionRequest) => {
    const response = await apiClient.put<SourceChatSession>(
      `/sources/${sourceId}/chat/sessions/${sessionId}`,
      data
    )
    return response.data
  },

  deleteSession: async (sourceId: string, sessionId: string) => {
    await apiClient.delete(`/sources/${sourceId}/chat/sessions/${sessionId}`)
  },

  // Messaging with streaming
  sendMessage: async (sourceId: string, sessionId: string, data: SendMessageRequest) => {
    // Auth token: prefer Harvis's shared OWUI JWT (localStorage.token) when
    // embedded under /onb, fall back to open-notebook's own auth-storage.
    let token = null
    if (typeof window !== 'undefined') {
      try {
        token = localStorage.getItem('token')
      } catch {
        token = null
      }
      if (!token) {
        const authStorage = localStorage.getItem('auth-storage')
        if (authStorage) {
          try {
            const { state } = JSON.parse(authStorage)
            if (state?.token) {
              token = state.token
            }
          } catch (error) {
            console.error('Error parsing auth storage:', error)
          }
        }
      }
    }

    // Build off the runtime API base (→ /onb/api/... under Harvis) so the SSE
    // fetch hits the onb_compat facade instead of skipping the basePath and 404ing.
    const url = `${await getApiUrl()}/api/sources/${sourceId}/chat/sessions/${sessionId}/messages`

    // Use fetch with ReadableStream for SSE
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { 'Authorization': `Bearer ${token}` })
      },
      body: JSON.stringify(data)
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      return response.body
    })
  }
}
