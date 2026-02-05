"""
Hook for OpenClaw WebSocket connection

Manages real-time connection to OpenClaw task events.
"""

'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'

export function useOpenClawWebSocket(taskId: string | null) {
  const ws = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const { addEvent, updateTask, updateTaskStep, addScreenshot } = useOpenClawStore()

  const connect = useCallback(() => {
    if (!taskId || ws.current?.readyState === WebSocket.OPEN) return

    const wsUrl = `ws://localhost:8000/ws/openclaw/tasks/${taskId}`
    ws.current = new WebSocket(wsUrl)

    ws.current.onopen = () => {
      console.log(`[OpenClaw] Connected to task ${taskId}`)
      setIsConnected(true)
    }

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data)
      handleMessage(data)
    }

    ws.current.onclose = () => {
      console.log(`[OpenClaw] Disconnected from task ${taskId}`)
      setIsConnected(false)
    }

    ws.current.onerror = (error) => {
      console.error(`[OpenClaw] WebSocket error:`, error)
      setIsConnected(false)
    }
  }, [taskId])

  const disconnect = useCallback(() => {
    if (ws.current) {
      ws.current.close()
      ws.current = null
      setIsConnected(false)
    }
  }, [])

  const handleMessage = useCallback((data: any) => {
    if (data.type === 'event' && data.event) {
      const event = data.event

      // Add event to store
      addEvent({
        id: `${event.job_id}-${Date.now()}`,
        taskId: event.job_id,
        type: event.type,
        payload: event.payload,
        createdAt: event.timestamp,
      })

      // Handle specific event types
      switch (event.type) {
        case 'job_started':
          updateTask(event.job_id, {
            status: 'running',
            startedAt: event.payload.started_at,
          })
          break

        case 'job_completed':
          updateTask(event.job_id, {
            status: 'completed',
            result: event.payload.result,
            completedAt: new Date().toISOString(),
            progressPercentage: 100,
          })
          break

        case 'job_failed':
          updateTask(event.job_id, {
            status: 'failed',
            errorMessage: event.payload.error_message,
            completedAt: new Date().toISOString(),
          })
          break

        case 'job_cancelled':
          updateTask(event.job_id, {
            status: 'cancelled',
            completedAt: new Date().toISOString(),
          })
          break

        case 'task_step_started':
          updateTaskStep(event.job_id, event.payload.step_index, {
            status: 'running',
            startedAt: event.payload.started_at,
          })
          updateTask(event.job_id, { currentStep: event.payload.step_index })
          break

        case 'task_step_completed':
          updateTaskStep(event.job_id, event.payload.step_index, {
            status: 'completed',
            result: event.payload.result,
            completedAt: event.payload.completed_at,
            screenshots: event.payload.artifacts
              ?.filter((a: any) => a.type === 'screenshot')
              .map((a: any) => a.id) || [],
          })
          break

        case 'task_step_failed':
          updateTaskStep(event.job_id, event.payload.step_index, {
            status: 'failed',
            errorMessage: event.payload.error_message,
          })
          break

        case 'screenshot_captured':
          addScreenshot({
            id: event.payload.screenshot_id,
            taskId: event.job_id,
            stepIndex: event.payload.step_index,
            caption: event.payload.caption,
            url: `/api/assets/screenshots/${event.payload.screenshot_id}`,
            thumbnailUrl: event.payload.thumbnail_path
              ? `/api/assets/screenshots/${event.payload.screenshot_id}/thumbnail`
              : undefined,
            width: event.payload.width,
            height: event.payload.height,
            takenAt: event.payload.taken_at,
          })
          break

        case 'needs_approval':
          updateTask(event.job_id, { status: 'paused' })
          break

        case 'approval_granted':
          updateTask(event.job_id, { status: 'running' })
          break
      }
    } else if (data.type === 'initial_state') {
      // Handle initial state
      if (data.job) {
        // Update task with current state
      }
    }
  }, [addEvent, updateTask, updateTaskStep, addScreenshot])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  const sendMessage = useCallback((message: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message))
    }
  }, [])

  return {
    isConnected,
    sendMessage,
    connect,
    disconnect,
  }
}
