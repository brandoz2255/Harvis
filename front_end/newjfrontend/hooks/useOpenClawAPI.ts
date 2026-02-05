"""
Hook for OpenClaw API calls

Provides methods for interacting with OpenClaw backend.
"""

'use client'

import { useCallback } from 'react'

interface CreateTaskRequest {
  task_prompt: string
  session_id?: string
  instance_id?: string
  policy_profile?: string
  max_runtime_minutes?: number
}

interface CreateInstanceRequest {
  name: string
  vm_type?: 'virtualbox' | 'docker' | 'cloud'
  vm_config?: Record<string, any>
}

export function useOpenClawAPI() {
  const createTask = useCallback(async (request: CreateTaskRequest) => {
    const response = await fetch('/api/openclaw/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      throw new Error('Failed to create task')
    }

    return response.json()
  }, [])

  const cancelTask = useCallback(async (taskId: string, reason?: string) => {
    const response = await fetch(`/api/openclaw/tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    })

    if (!response.ok) {
      throw new Error('Failed to cancel task')
    }

    return response.json()
  }, [])

  const submitApproval = useCallback(
    async (taskId: string, requestId: string, approved: boolean, reason?: string) => {
      const response = await fetch(`/api/openclaw/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: requestId,
          approved,
          reason,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to submit approval')
      }

      return response.json()
    },
    []
  )

  const submitContext = useCallback(
    async (taskId: string, requestId: string, response: string, attachments?: any[]) => {
      const res = await fetch(`/api/openclaw/tasks/${taskId}/context`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: requestId,
          response,
          attachments,
        }),
      })

      if (!res.ok) {
        throw new Error('Failed to submit context')
      }

      return res.json()
    },
    []
  )

  const fetchTasks = useCallback(async () => {
    const response = await fetch('/api/openclaw/tasks')

    if (!response.ok) {
      throw new Error('Failed to fetch tasks')
    }

    return response.json()
  }, [])

  const fetchTask = useCallback(async (taskId: string) => {
    const response = await fetch(`/api/openclaw/tasks/${taskId}`)

    if (!response.ok) {
      throw new Error('Failed to fetch task')
    }

    return response.json()
  }, [])

  const createInstance = useCallback(async (request: CreateInstanceRequest) => {
    const response = await fetch('/api/openclaw/instances', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      throw new Error('Failed to create instance')
    }

    return response.json()
  }, [])

  const fetchInstances = useCallback(async () => {
    const response = await fetch('/api/openclaw/instances')

    if (!response.ok) {
      throw new Error('Failed to fetch instances')
    }

    return response.json()
  }, [])

  return {
    createTask,
    cancelTask,
    submitApproval,
    submitContext,
    fetchTasks,
    fetchTask,
    createInstance,
    fetchInstances,
  }
}
