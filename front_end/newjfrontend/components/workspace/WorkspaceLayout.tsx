/**
 * Workspace Layout Component
 * 
 * Manages the layout switching between normal chat and workspace mode.
 */

'use client'

import React from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { useDiscordWorkspaceFollow } from '@/hooks/useDiscordWorkspaceFollow'
import { cn } from '@/lib/utils'

interface WorkspaceLayoutProps {
  chatComponent: React.ReactNode
  workspaceComponent: React.ReactNode
  sidebarComponent?: React.ReactNode
  className?: string
}

export function WorkspaceLayout({
  chatComponent,
  workspaceComponent,
  sidebarComponent,
  className,
}: WorkspaceLayoutProps) {
  const { isWorkspaceActive, isChatMinimized, setChatMinimized } = useOpenClawStore()
  useDiscordWorkspaceFollow()

  if (!isWorkspaceActive) {
    // Normal chat mode — full width, no split
    return (
      <div className={cn('flex flex-1 h-full min-w-0', className)}>
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">{chatComponent}</div>
        {sidebarComponent && (
          <div className="w-80 border-l">{sidebarComponent}</div>
        )}
      </div>
    )
  }

  // Workspace mode: chat LEFT (minimized), workspace panel RIGHT (larger)
  return (
    <div className={cn('flex flex-1 h-full min-w-0', className)}>
      {/* Chat area LEFT — shrinks when workspace is active */}
      <div
        className={cn(
          'flex flex-col transition-all duration-500 ease-in-out overflow-hidden',
          isChatMinimized ? 'w-12' : 'flex-[4]'
        )}
      >
        {isChatMinimized ? (
          <MinimizedChatBar />
        ) : (
          <div className="h-full flex flex-col">{chatComponent}</div>
        )}
      </div>

      {/* Workspace panel RIGHT — compact activity log */}
      <div
        className={cn(
          'flex flex-col transition-all duration-500 ease-in-out border-l border-border',
          isChatMinimized ? 'flex-1' : 'flex-[3]'
        )}
      >
        {workspaceComponent}
      </div>

      {/* Sidebar (hidden in workspace mode to save space) */}
      {sidebarComponent && !isWorkspaceActive && (
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
