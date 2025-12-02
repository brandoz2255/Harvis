'use client'

// NOTE: MonacoCopilot is currently a no-op. Inline suggestions are handled
// entirely inside VibeContainerCodeEditor via a custom ghost-text overlay.

import React from 'react'

interface MonacoCopilotProps {
  editor: any
  sessionId: string | null
  filepath: string
  language: string
  enabled?: boolean
  debounceMs?: number
  model?: string
}

export function MonacoCopilot(_props: MonacoCopilotProps) {
  return null
}

