import apiClient from './client'
import { getApiUrl } from '@/lib/config'
import { SearchRequest, SearchResponse, AskRequest } from '@/lib/types/search'

export const searchApi = {
  // Standard search (non-streaming)
  search: async (params: SearchRequest) => {
    const response = await apiClient.post<SearchResponse>('/search', params)
    return response.data
  },

  // Ask with streaming (uses relative URL for Docker compatibility)
  askKnowledgeBase: async (params: AskRequest) => {
    // Get auth token using the same logic as the apiClient interceptor:
    // prefer Harvis's shared OWUI JWT (localStorage.token) when embedded under
    // /onb, fall back to open-notebook's own auth-storage when standalone.
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

    // Build the URL off the runtime-configured API base (same as apiClient's
    // baseURL = `${apiUrl}/api`). Under Harvis this resolves to /onb/api/... which
    // nginx rewrites to the onb_compat facade; a bare /api/... would skip the
    // basePath and 404. SSE streaming still uses a raw fetch (axios can't stream).
    const url = `${await getApiUrl()}/api/search/ask`

    // Use fetch with ReadableStream for SSE
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` })
      },
      body: JSON.stringify(params)
    })

    if (!response.ok) {
      // Try to extract error message from response
      let errorMessage = `HTTP error! status: ${response.status}`
      try {
        const errorData = await response.json()
        errorMessage = errorData.detail || errorData.message || errorMessage
      } catch {
        // If response isn't JSON, use status text
        errorMessage = response.statusText || errorMessage
      }
      throw new Error(errorMessage)
    }

    if (!response.body) {
      throw new Error('No response body received')
    }

    return response.body
  }
}
