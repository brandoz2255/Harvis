"use client"

import { useState, useCallback, useRef } from 'react'

interface AsyncTTSState {
  jobId: string | null
  status: 'idle' | 'queued' | 'active' | 'completed' | 'failed'
  audioUrl: string | null
  error: string | null
  progress: number
}

export function useAsyncTTS() {
  const [state, setState] = useState<AsyncTTSState>({
    jobId: null,
    status: 'idle',
    audioUrl: null,
    error: null,
    progress: 0
  })
  
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const submitTTS = useCallback(async (
    text: string, 
    options: {
      voiceId?: string
      ttsEngine?: string
      onComplete?: (audioUrl: string) => void
      onError?: (error: string) => void
    } = {}
  ) => {
    const { voiceId, ttsEngine = 'qwen', onComplete, onError } = options
    
    // Cancel any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    try {
      setState(prev => ({ ...prev, status: 'queued', progress: 10, error: null }))

      // Submit TTS job
      const response = await fetch('/api/jobs/tts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token') || ''}`
        },
        body: JSON.stringify({
          text,
          voice_id: voiceId,
          tts_engine: ttsEngine
        }),
        signal: abortControllerRef.current.signal
      })

      if (!response.ok) {
        throw new Error(`Failed to submit TTS job: ${response.statusText}`)
      }

      const data = await response.json()
      const jobId = data.job_id

      setState(prev => ({ ...prev, jobId, status: 'queued', progress: 20 }))

      // Start polling for job completion
      pollIntervalRef.current = setInterval(async () => {
        try {
          const statusResponse = await fetch(`/api/jobs/${jobId}`, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('token') || ''}`
            }
          })

          if (!statusResponse.ok) {
            throw new Error('Failed to check job status')
          }

          const jobStatus = await statusResponse.json()
          
          switch (jobStatus.state) {
            case 'created':
              setState(prev => ({ ...prev, status: 'queued', progress: 30 }))
              break
            case 'active':
              setState(prev => ({ ...prev, status: 'active', progress: 50 }))
              break
            case 'completed':
              // Job completed - check for audio_path in data
              const audioPath = jobStatus.data?.audio_path
              if (audioPath) {
                setState({
                  jobId,
                  status: 'completed',
                  audioUrl: audioPath,
                  error: null,
                  progress: 100
                })
                onComplete?.(audioPath)
              } else {
                setState(prev => ({ 
                  ...prev, 
                  status: 'failed', 
                  error: 'No audio generated',
                  progress: 0
                }))
                onError?.('No audio generated')
              }
              // Stop polling
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current)
                pollIntervalRef.current = null
              }
              break
            case 'failed':
              const errorMsg = jobStatus.data?.error || 'TTS job failed'
              setState(prev => ({ 
                ...prev, 
                status: 'failed', 
                error: errorMsg,
                progress: 0
              }))
              onError?.(errorMsg)
              // Stop polling
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current)
                pollIntervalRef.current = null
              }
              break
          }
        } catch (error) {
          console.error('Error polling TTS job:', error)
          // Don't stop polling on network errors, will retry
        }
      }, 2000) // Poll every 2 seconds

      return jobId
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to submit TTS'
      setState(prev => ({ ...prev, status: 'failed', error: errorMsg, progress: 0 }))
      onError?.(errorMsg)
      throw error
    }
  }, [])

  const cancelTTS = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setState({
      jobId: null,
      status: 'idle',
      audioUrl: null,
      error: null,
      progress: 0
    })
  }, [])

  return {
    ...state,
    submitTTS,
    cancelTTS
  }
}
