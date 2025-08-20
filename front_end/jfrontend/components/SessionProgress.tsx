"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import { Loader2, X, RefreshCw, Clock, AlertCircle, CheckCircle2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { SessionStatusResponse } from "@/lib/api"

interface SessionProgressProps {
  sessionId: string
  onCancel?: () => void
  onRetry?: () => void
  onComplete?: (sessionId: string) => void
  className?: string
}

export default function SessionProgress({
  sessionId,
  onCancel,
  onRetry,
  onComplete,
  className = ""
}: SessionProgressProps) {
  const [status, setStatus] = useState<SessionStatusResponse | null>(null)
  const [elapsed, setElapsed] = useState<number>(0)
  const [error, setError] = useState<string | null>(null)
  const startTimeRef = useRef<number>(Date.now())
  const elapsedIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Update elapsed time every second
  useEffect(() => {
    elapsedIntervalRef.current = setInterval(() => {
      setElapsed(Date.now() - startTimeRef.current)
    }, 1000)

    return () => {
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
      }
    }
  }, [])

  // Handle status updates from parent component or polling
  useEffect(() => {
    if (status?.ready && onComplete) {
      onComplete(sessionId)
    }
  }, [status?.ready, sessionId, onComplete])

  const formatTime = (ms: number): string => {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
  }

  const getPhaseColor = (phase: string): string => {
    switch (phase) {
      case 'Starting': return 'text-blue-400'
      case 'PullingImage': return 'text-yellow-400'
      case 'CreatingVolume': return 'text-orange-400'
      case 'CreatingContainer': return 'text-purple-400'
      case 'StartingContainer': return 'text-green-400'
      case 'Ready': return 'text-green-400'
      case 'Error': return 'text-red-400'
      default: return 'text-gray-400'
    }
  }

  const getPhaseIcon = (phase: string) => {
    switch (phase) {
      case 'Ready': return <CheckCircle2 className="w-4 h-4" />
      case 'Error': return <AlertCircle className="w-4 h-4" />
      default: return <Loader2 className="w-4 h-4 animate-spin" />
    }
  }

  const getProgressBarColor = (phase: string): string => {
    switch (phase) {
      case 'Error': return 'bg-red-500'
      case 'Ready': return 'bg-green-500'
      default: return 'bg-blue-500'
    }
  }

  const handleCancel = () => {
    if (elapsedIntervalRef.current) {
      clearInterval(elapsedIntervalRef.current)
    }
    onCancel?.()
  }

  const handleRetry = () => {
    setError(null)
    startTimeRef.current = Date.now()
    setElapsed(0)
    onRetry?.()
  }

  // Allow parent to update status
  const updateStatus = (newStatus: SessionStatusResponse) => {
    setStatus(newStatus)
    if (newStatus.error) {
      setError(newStatus.error)
    }
  }

  // Expose updateStatus method to parent
  useEffect(() => {
    // Store the update function on the component instance
    (window as any).__sessionProgressUpdate = updateStatus
    return () => {
      delete (window as any).__sessionProgressUpdate
    }
  }, [])

  const progress = status?.progress
  const hasPercent = progress?.percent !== undefined
  const progressValue = hasPercent ? progress.percent : undefined
  const etaMs = progress?.eta_ms
  const phase = status?.phase || 'Starting'
  const isError = phase === 'Error' || error
  const isComplete = status?.ready || phase === 'Ready'

  return (
    <Card className={`bg-gray-900/95 backdrop-blur-sm border-purple-500/30 p-6 ${className}`}>
      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <motion.div
              animate={isError ? { scale: [1, 1.1, 1] } : isComplete ? {} : { rotate: 360 }}
              transition={isError ? { duration: 0.5, repeat: 3 } : isComplete ? {} : { duration: 2, repeat: Infinity, ease: "linear" }}
              className={getPhaseColor(phase)}
            >
              {getPhaseIcon(phase)}
            </motion.div>
            <div>
              <h3 className="text-lg font-semibold text-white">Creating Session</h3>
              <p className="text-sm text-gray-400">Session ID: {sessionId.slice(0, 8)}...</p>
            </div>
          </div>
          
          {onCancel && !isComplete && (
            <Button 
              onClick={handleCancel}
              size="sm" 
              variant="ghost" 
              className="text-gray-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>

        {/* Phase and Status */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Badge 
              variant="outline" 
              className={`${getPhaseColor(phase)} border-current`}
            >
              {phase}
            </Badge>
            <div className="flex items-center space-x-2 text-sm text-gray-400">
              <Clock className="w-3 h-3" />
              <span>Elapsed: {formatTime(elapsed)}</span>
            </div>
          </div>
          
          {status?.message && (
            <p className="text-sm text-gray-300">{status.message}</p>
          )}
        </div>

        {/* Progress Bar */}
        <div className="space-y-2">
          {hasPercent ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span>Progress</span>
                <span>{progressValue}%</span>
              </div>
              <div className="w-full bg-gray-700 rounded-full h-2">
                <motion.div 
                  className={`h-2 rounded-full ${getProgressBarColor(phase)}`}
                  initial={{ width: 0 }}
                  animate={{ width: `${progressValue}%` }}
                  transition={{ duration: 0.5, ease: "easeInOut" }}
                />
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              <div className="text-xs text-gray-400">Progress</div>
              <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                <motion.div 
                  className={`h-2 ${getProgressBarColor(phase)} bg-gradient-to-r from-transparent via-current to-transparent`}
                  animate={{ x: [-100, 300] }}
                  transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                  style={{ width: "100px" }}
                />
              </div>
            </div>
          )}
        </div>

        {/* ETA */}
        {etaMs && etaMs > 0 && !isComplete && !isError && (
          <div className="flex items-center space-x-2 text-sm text-gray-300">
            <Clock className="w-3 h-3" />
            <span>ETA: {formatTime(etaMs)}</span>
          </div>
        )}

        {/* Error State */}
        {isError && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3 bg-red-500/20 border border-red-500/30 rounded-lg"
          >
            <div className="flex items-center space-x-2 text-red-400 mb-2">
              <AlertCircle className="w-4 h-4" />
              <span className="font-medium">Session Creation Failed</span>
            </div>
            <p className="text-sm text-gray-300 mb-3">
              {error || status?.error || 'An unexpected error occurred'}
            </p>
            {onRetry && (
              <Button 
                onClick={handleRetry}
                size="sm" 
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                <RefreshCw className="w-3 h-3 mr-1" />
                Retry
              </Button>
            )}
          </motion.div>
        )}

        {/* Success State */}
        {isComplete && !isError && (
          <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3 bg-green-500/20 border border-green-500/30 rounded-lg"
          >
            <div className="flex items-center space-x-2 text-green-400">
              <CheckCircle2 className="w-4 h-4" />
              <span className="font-medium">Session Ready!</span>
            </div>
            <p className="text-sm text-gray-300 mt-1">
              Your development environment is ready to use.
            </p>
          </motion.div>
        )}
      </div>
    </Card>
  )
}

// Helper hook for parent components to control progress
export function useSessionProgress(sessionId: string) {
  const updateStatus = (status: SessionStatusResponse) => {
    if ((window as any).__sessionProgressUpdate) {
      (window as any).__sessionProgressUpdate(status)
    }
  }

  return { updateStatus }
}