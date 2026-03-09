"use client"

import { useState, useCallback, useEffect } from 'react'

interface JobStatus {
  id: string
  name: string
  state: 'created' | 'active' | 'completed' | 'failed' | 'cancelled' | 'retry'
  data?: {
    audio_path?: string
    text?: string
    error?: string
    [key: string]: any
  }
  retry_count: number
  retry_limit: number
  created_at?: string
  started_at?: string
  completed_at?: string
}

interface UseAsyncJobOptions {
  onComplete?: (result: any) => void
  onError?: (error: string) => void
  pollInterval?: number
}

export function useAsyncJob(options: UseAsyncJobOptions = {}) {
  const { onComplete, onError, pollInterval = 2000 } = options
  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submitTTSJob = useCallback(async (text: string, voiceId?: string, ttsEngine: string = 'qwen') => {
    setIsLoading(true)
    setError(null)
    
    try {
      const response = await fetch('/api/jobs/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice_id: voiceId, tts_engine: ttsEngine })
      })
      
      if (!response.ok) {
        throw new Error(`Failed to submit TTS job: ${response.statusText}`)
      }
      
      const data = await response.json()
      setJobId(data.job_id)
      return data.job_id
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      onError?.(message)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [onError])

  const submitWhisperJob = useCallback(async (audioPath: string) => {
    setIsLoading(true)
    setError(null)
    
    try {
      const response = await fetch('/api/jobs/whisper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audio_path: audioPath })
      })
      
      if (!response.ok) {
        throw new Error(`Failed to submit Whisper job: ${response.statusText}`)
      }
      
      const data = await response.json()
      setJobId(data.job_id)
      return data.job_id
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      onError?.(message)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [onError])

  const checkJobStatus = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/jobs/${id}`)
      
      if (!response.ok) {
        throw new Error(`Failed to check job status: ${response.statusText}`)
      }
      
      const jobStatus: JobStatus = await response.json()
      setStatus(jobStatus)
      
      if (jobStatus.state === 'completed') {
        onComplete?.(jobStatus.data)
        return true
      } else if (jobStatus.state === 'failed') {
        const errorMsg = jobStatus.data?.error || 'Job failed'
        setError(errorMsg)
        onError?.(errorMsg)
        return true
      }
      
      return false
    } catch (err) {
      console.error('Error checking job status:', err)
      return false
    }
  }, [onComplete, onError])

  // Auto-poll when jobId is set
  useEffect(() => {
    if (!jobId) return

    let isActive = true
    let timeoutId: NodeJS.Timeout

    const poll = async () => {
      if (!isActive) return
      
      const isDone = await checkJobStatus(jobId)
      
      if (!isDone && isActive) {
        timeoutId = setTimeout(poll, pollInterval)
      }
    }

    poll()

    return () => {
      isActive = false
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [jobId, pollInterval, checkJobStatus])

  const reset = useCallback(() => {
    setJobId(null)
    setStatus(null)
    setIsLoading(false)
    setError(null)
  }, [])

  return {
    jobId,
    status,
    isLoading,
    error,
    submitTTSJob,
    submitWhisperJob,
    checkJobStatus,
    reset
  }
}
