"""
Workspace Layout Component

Manages the layout switching between normal chat and workspace mode.
"""

'use client'

import React from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

interface WorkspaceLayoutProps {
  chatComponent: React.ReactNode
  workspaceComponent: React.ReactNode
  sidebarComponent?: React.ReactNode
}

export function WorkspaceLayout({
  chatComponent,
  workspaceComponent,
  sidebarComponent,
}: WorkspaceLayoutProps) {
  const { isWorkspaceActive, isChatMinimized } = useOpenClawStore()

  if (!isWorkspaceActive) {
    // Normal chat mode
    return (
      <div className="flex h-full">
        <div className="flex-1 flex flex-col">{chatComponent}</div>
        {sidebarComponent && (
          <div className="w-80 border-l">{sidebarComponent}</div>
        )}
      </div>
    )
  }

  // Workspace mode
  return (
    <div className="flex h-full">
      {/* Main workspace area */}
      <div
        className={cn(
          'flex flex-col transition-all duration-300',
          isChatMinimized ? 'flex-1' : 'flex-[2]'
        )}
      >
        {workspaceComponent}
      </div>

      {/* Chat area (collapsible) */}
      <div
        className={cn(
          'border-l transition-all duration-300 overflow-hidden',
          isChatMinimized ? 'w-12' : 'flex-1'
        )}
      >
        {isChatMinimized ? (
          <MinimizedChatBar />
        ) : (
          <div className="h-full flex flex-col">{chatComponent}</div>
        )}
      </div>

      {/* Sidebar */}
      {sidebarComponent && !isChatMinimized && (
        <div className="w-80 border-l">{sidebarComponent}</div>
      )}
    </div>
  )
}

function MinimizedChatBar() {
  const { setChatMinimized } = useOpenClawStore()

  return (
    <button
      onClick={() => setChatMinimized(false)}
      className="w-full h-full flex items-center justify-center hover:bg-muted transition-colors"
    >
      <div className="writing-vertical text-sm text-muted-foreground rotate-180">
        Chat
      </div>
    </button>
  )
}
