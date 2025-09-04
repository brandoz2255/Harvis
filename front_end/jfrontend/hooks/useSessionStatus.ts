/**
 * Custom hook for session status management
 * Provides real-time session status checking and polling
 */

import { useState, useCallback, useEffect, useRef } from 'react'

export interface SessionStatus {
  state: 'starting' | 'running' | 'stopping' | 'stopped' | 'error'
  container_exists: boolean
  volume_exists: boolean
  last_ready_at?: string
  created_at?: string
  error_message?: string
  session_id: string
  container_id?: string
  volume_name?: string
}

interface UseSessionStatusOptions {
  sessionId: string
  pollInterval?: number // milliseconds, default 2000
  pollWhenNotRunning?: boolean // default true
}

export function useSessionStatus({ 
  sessionId, 
  pollInterval = 2000, 
  pollWhenNotRunning = true 
}: UseSessionStatusOptions) {
  const [sessionStatus, setSessionStatus] = useState<SessionStatus | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const pollTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const mountedRef = useRef(true)

  const fetchSessionStatus = useCallback(async (silent = false) => {
    if (!sessionId) return null

    if (!silent) setIsLoading(true)
    setError(null)

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('No authentication token')
      }

      const response = await fetch(`/api/vibe-sessions/${sessionId}/status`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Authentication failed')
        } else if (response.status === 404) {
          throw new Error('Session not found')
        } else {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }
      }

      const status = await response.json() as SessionStatus
      
      if (mountedRef.current) {
        setSessionStatus(status)
        setError(null)
      }
      
      return status
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch session status'
      
      if (mountedRef.current) {
        setError(errorMessage)
        console.error('Session status fetch error:', err)
      }
      
      return null
    } finally {
      if (!silent && mountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [sessionId])

  const startPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current)
    }

    const poll = async () => {
      if (!mountedRef.current) return

      const status = await fetchSessionStatus(true) // silent fetch during polling
      
      if (!mountedRef.current) return

      // Continue polling if session is not running and polling is enabled
      const shouldContinuePolling = pollWhenNotRunning && 
        status && 
        status.state !== 'running'

      if (shouldContinuePolling) {
        pollTimeoutRef.current = setTimeout(poll, pollInterval)
      }
    }

    // Start first poll after a short delay
    pollTimeoutRef.current = setTimeout(poll, 100)
  }, [fetchSessionStatus, pollInterval, pollWhenNotRunning])

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current)
      pollTimeoutRef.current = null
    }
  }, [])

  const startSession = useCallback(async (): Promise<{ success: boolean; jobId?: string; message?: string }> => {
    if (!sessionId) return { success: false, message: 'No session ID' }

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('No authentication token')
      }

      const response = await fetch(`/api/vibe-sessions/${sessionId}/start`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const result = await response.json()
      
      // Start polling to monitor the start process
      startPolling()
      
      return { 
        success: true, 
        jobId: result.job_id,
        message: result.message 
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to start session'
      console.error('Session start error:', err)
      return { success: false, message: errorMessage }
    }
  }, [sessionId, startPolling])

  const stopSession = useCallback(async (): Promise<{ success: boolean; message?: string }> => {
    if (!sessionId) return { success: false, message: 'No session ID' }

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('No authentication token')
      }

      const response = await fetch(`/api/vibe-sessions/${sessionId}/stop`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const result = await response.json()
      
      // Refresh status immediately after stop
      setTimeout(() => fetchSessionStatus(true), 100)
      
      return { success: true, message: result.message }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to stop session'
      console.error('Session stop error:', err)
      return { success: false, message: errorMessage }
    }
  }, [sessionId, fetchSessionStatus])

  // Initial fetch and setup polling when session changes
  useEffect(() => {
    if (!sessionId) return

    // Fetch initial status
    fetchSessionStatus()
    
    // Start polling if needed
    if (pollWhenNotRunning) {
      startPolling()
    }

    return () => {
      stopPolling()
    }
  }, [sessionId, fetchSessionStatus, startPolling, stopPolling, pollWhenNotRunning])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false
      stopPolling()
    }
  }, [stopPolling])

  const isReady = sessionStatus?.state === 'running'
  const isStarting = sessionStatus?.state === 'starting'
  const isStopped = sessionStatus?.state === 'stopped'
  const hasError = sessionStatus?.state === 'error' || !!error

  return {
    sessionStatus,
    isLoading,
    error,
    isReady,
    isStarting,
    isStopped,
    hasError,
    fetchSessionStatus,
    startSession,
    stopSession,
    startPolling,
    stopPolling
  }
}