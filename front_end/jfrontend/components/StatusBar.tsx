/**
 * StatusBar Component
 * 
 * Displays session info, container status, file info, and quick actions at the bottom of the IDE.
 * Features:
 * - Session name and container status with color coding
 * - Selected file name and cursor position (line:col)
 * - Theme indicator and font size display
 * - Quick action buttons: command palette, theme toggle, settings
 * - Real-time container status updates
 */

import React, { useState, useEffect } from 'react'
import { 
  Circle, 
  FileText, 
  Sun, 
  Moon, 
  Type, 
  Command, 
  Settings,
  Loader2,
  Sidebar,
  PanelRightClose,
  PanelBottomClose
} from 'lucide-react'

interface StatusBarProps {
  // Session info
  sessionName?: string
  sessionId?: string
  containerStatus?: 'running' | 'stopped' | 'starting' | 'stopping'
  
  // File info
  selectedFileName?: string
  selectedFilePath?: string
  cursorPosition?: { line: number; column: number }
  
  // Editor state
  isDirty?: boolean
  language?: string
  
  // User preferences
  theme?: 'light' | 'dark'
  fontSize?: number
  
  // Panel visibility
  showLeftPanel?: boolean
  showRightPanel?: boolean
  showTerminal?: boolean
  
  // Actions
  onCommandPaletteClick?: () => void
  onThemeToggle?: () => void
  onSettingsClick?: () => void
  onToggleLeftPanel?: () => void
  onToggleRightPanel?: () => void
  onToggleTerminal?: () => void
  
  className?: string
}

export default function StatusBar({
  sessionName,
  sessionId,
  containerStatus = 'stopped',
  selectedFileName,
  selectedFilePath,
  cursorPosition,
  isDirty = false,
  language,
  theme = 'dark',
  fontSize = 14,
  showLeftPanel = true,
  showRightPanel = true,
  showTerminal = true,
  onCommandPaletteClick,
  onThemeToggle,
  onSettingsClick,
  onToggleLeftPanel,
  onToggleRightPanel,
  onToggleTerminal,
  className = ''
}: StatusBarProps) {
  const [currentContainerStatus, setCurrentContainerStatus] = useState(containerStatus)
  const [isPolling, setIsPolling] = useState(false)

  // Update local status when prop changes
  useEffect(() => {
    setCurrentContainerStatus(containerStatus)
  }, [containerStatus])

  // Poll container status in real-time
  useEffect(() => {
    if (!sessionId) return

    let pollInterval: NodeJS.Timeout | null = null

    const pollStatus = async () => {
      try {
        setIsPolling(true)
        const token = localStorage.getItem('token')
        if (!token) return

        const response = await fetch(`/api/vibecode/container/${sessionId}/status`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })

        if (response.ok) {
          const data = await response.json()
          // Handle new status values
          const status = data.status || 'stopped'
          setCurrentContainerStatus(status)
        } else {
          // Handle API errors gracefully
          console.warn('Container status check failed:', response.status)
          setCurrentContainerStatus('error')
        }
      } catch (error) {
        console.error('Failed to poll container status:', error)
        setCurrentContainerStatus('error')
      } finally {
        setIsPolling(false)
      }
    }

    // Poll every 5 seconds
    pollInterval = setInterval(pollStatus, 5000)

    // Initial poll
    pollStatus()

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval)
      }
    }
  }, [sessionId])

  // Get container status color and label
  const getContainerStatusInfo = () => {
    switch (currentContainerStatus) {
      case 'running':
        return {
          color: 'text-green-400',
          bgColor: 'bg-green-500/20',
          label: 'Running',
          icon: <Circle className="w-2 h-2 fill-current" />
        }
      case 'stopped':
        return {
          color: 'text-red-400',
          bgColor: 'bg-red-500/20',
          label: 'Stopped',
          icon: <Circle className="w-2 h-2 fill-current" />
        }
      case 'starting':
        return {
          color: 'text-yellow-400',
          bgColor: 'bg-yellow-500/20',
          label: 'Starting',
          icon: <Loader2 className="w-2 h-2 animate-spin" />
        }
      case 'stopping':
        return {
          color: 'text-orange-400',
          bgColor: 'bg-orange-500/20',
          label: 'Stopping',
          icon: <Loader2 className="w-2 h-2 animate-spin" />
        }
      case 'not_created':
        return {
          color: 'text-gray-400',
          bgColor: 'bg-gray-500/20',
          label: 'Not Created',
          icon: <Circle className="w-2 h-2 fill-current" />
        }
      case 'error':
        return {
          color: 'text-red-400',
          bgColor: 'bg-red-500/20',
          label: 'Error',
          icon: <Circle className="w-2 h-2 fill-current" />
        }
      default:
        return {
          color: 'text-gray-400',
          bgColor: 'bg-gray-500/20',
          label: 'Unknown',
          icon: <Circle className="w-2 h-2 fill-current" />
        }
    }
  }

  const statusInfo = getContainerStatusInfo()

  return (
    <div 
      className={`
        h-6 bg-gray-800 border-t border-gray-700 
        flex items-center justify-between px-3 
        text-xs text-gray-400 
        flex-shrink-0
        ${className}
      `}
    >
      {/* Left section - Session and file info */}
      <div className="flex items-center gap-3">
        {/* Session name */}
        {sessionName ? (
          <div className="flex items-center gap-1.5">
            <span className="text-gray-500">Session:</span>
            <span className="text-gray-300 font-medium">{sessionName}</span>
          </div>
        ) : (
          <span className="text-gray-500">No session</span>
        )}

        {/* Container status */}
        {sessionId && (
          <>
            <span className="text-gray-600">|</span>
            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Container:</span>
              <div className={`
                flex items-center gap-1.5 px-2 py-0.5 rounded
                ${statusInfo.bgColor} ${statusInfo.color}
              `}>
                {statusInfo.icon}
                <span className="font-medium">{statusInfo.label}</span>
              </div>
            </div>
          </>
        )}

        {/* Selected file */}
        {selectedFileName && (
          <>
            <span className="text-gray-600">|</span>
            <div className="flex items-center gap-1.5">
              <FileText className="w-3 h-3 text-gray-500" />
              <span className="text-gray-300">{selectedFileName}</span>
              {isDirty && (
                <span className="text-yellow-400 ml-1">●</span>
              )}
            </div>
          </>
        )}

        {/* Language */}
        {language && (
          <>
            <span className="text-gray-600">|</span>
            <span className="text-gray-400 capitalize">{language}</span>
          </>
        )}

        {/* Cursor position */}
        {cursorPosition && (
          <>
            <span className="text-gray-600">|</span>
            <span className="text-gray-400 font-mono">
              Ln {cursorPosition.line}, Col {cursorPosition.column}
            </span>
          </>
        )}
      </div>

      {/* Right section - Theme, font size, and actions */}
      <div className="flex items-center gap-3">
        {/* Theme indicator */}
        <div className="flex items-center gap-1.5">
          {theme === 'dark' ? (
            <Moon className="w-3 h-3 text-gray-400" />
          ) : (
            <Sun className="w-3 h-3 text-gray-400" />
          )}
          <span className="text-gray-400 capitalize">{theme}</span>
        </div>

        <span className="text-gray-600">|</span>

        {/* Font size */}
        <div className="flex items-center gap-1.5">
          <Type className="w-3 h-3 text-gray-400" />
          <span className="text-gray-400">{fontSize}px</span>
        </div>

        <span className="text-gray-600">|</span>

        {/* Quick actions */}
        <div className="flex items-center gap-1">
          {/* Panel Toggles */}
          {onToggleLeftPanel && (
            <button
              onClick={onToggleLeftPanel}
              className={`
                p-1 rounded hover:bg-gray-700 
                transition-colors
                ${showLeftPanel ? 'text-blue-400 hover:text-blue-300' : 'text-gray-400 hover:text-gray-200'}
              `}
              title={`${showLeftPanel ? 'Hide' : 'Show'} Explorer (Ctrl+B)`}
            >
              <Sidebar className="w-3.5 h-3.5" />
            </button>
          )}

          {onToggleRightPanel && (
            <button
              onClick={onToggleRightPanel}
              className={`
                p-1 rounded hover:bg-gray-700 
                transition-colors
                ${showRightPanel ? 'text-blue-400 hover:text-blue-300' : 'text-gray-400 hover:text-gray-200'}
              `}
              title={`${showRightPanel ? 'Hide' : 'Show'} Right Panel`}
            >
              <PanelRightClose className="w-3.5 h-3.5" />
            </button>
          )}

          {onToggleTerminal && (
            <button
              onClick={onToggleTerminal}
              className={`
                p-1 rounded hover:bg-gray-700 
                transition-colors
                ${showTerminal ? 'text-blue-400 hover:text-blue-300' : 'text-gray-400 hover:text-gray-200'}
              `}
              title={`${showTerminal ? 'Hide' : 'Show'} Terminal (Ctrl+J)`}
            >
              <PanelBottomClose className="w-3.5 h-3.5" />
            </button>
          )}

          <span className="text-gray-600">|</span>

          {/* Command Palette */}
          {onCommandPaletteClick && (
            <button
              onClick={onCommandPaletteClick}
              className="
                p-1 rounded hover:bg-gray-700 
                transition-colors
                text-gray-400 hover:text-gray-200
              "
              title="Command Palette (Ctrl+Shift+P)"
            >
              <Command className="w-3.5 h-3.5" />
            </button>
          )}

          {/* Theme Toggle */}
          {onThemeToggle && (
            <button
              onClick={onThemeToggle}
              className="
                p-1 rounded hover:bg-gray-700 
                transition-colors
                text-gray-400 hover:text-gray-200
              "
              title="Toggle Theme"
            >
              {theme === 'dark' ? (
                <Sun className="w-3.5 h-3.5" />
              ) : (
                <Moon className="w-3.5 h-3.5" />
              )}
            </button>
          )}

          {/* Settings */}
          {onSettingsClick && (
            <button
              onClick={onSettingsClick}
              className="
                p-1 rounded hover:bg-gray-700 
                transition-colors
                text-gray-400 hover:text-gray-200
              "
              title="Settings"
            >
              <Settings className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
