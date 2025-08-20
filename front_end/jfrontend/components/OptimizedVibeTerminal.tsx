"use client"

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Terminal, Power, RefreshCw, Maximize2, Minimize2, Copy, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { apiRequest } from '@/lib/api'

interface OptimizedVibeTerminalProps {
  sessionId: string
  isContainerRunning?: boolean
  onContainerStart?: () => Promise<void>
  onContainerStop?: () => Promise<void>
  onReady?: () => void
  className?: string
}

interface TerminalLine {
  id: string
  content: string
  timestamp: Date
  type: 'output' | 'input' | 'error' | 'system'
}

export default function OptimizedVibeTerminal({ 
  sessionId, 
  isContainerRunning = false,
  onContainerStart,
  onContainerStop,
  onReady,
  className = "" 
}: OptimizedVibeTerminalProps) {
  const [lines, setLines] = useState<TerminalLine[]>([
    {
      id: '1',
      content: 'Optimized Vibe Terminal - Ready to connect...',
      timestamp: new Date(),
      type: 'system'
    }
  ])
  const [currentCommand, setCurrentCommand] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isExecutingCommand, setIsExecutingCommand] = useState(false)
  const [isMaximized, setIsMaximized] = useState(false)
  const [sessionReady, setSessionReady] = useState(false)
  const [readinessChecking, setReadinessChecking] = useState(false)
  
  const websocketRef = useRef<WebSocket | null>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const commandHistoryRef = useRef<string[]>([])
  const historyIndexRef = useRef(-1)
  const readinessIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const addLine = useCallback((content: string, type: TerminalLine['type'] = 'output') => {
    const newLine: TerminalLine = {
      id: Date.now().toString() + Math.random(),
      content,
      timestamp: new Date(),
      type
    }
    
    setLines(prev => {
      // Limit terminal history to prevent memory issues
      const newLines = [...prev, newLine]
      if (newLines.length > 1000) {
        return newLines.slice(-1000)
      }
      return newLines
    })
  }, [])

  const scrollToBottom = useCallback(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "auto" })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [lines, scrollToBottom])

  // Check session readiness before allowing terminal connection
  const checkSessionReadiness = useCallback(async () => {
    if (!sessionId || readinessChecking) return false
    
    setReadinessChecking(true)
    try {
      const result = await apiRequest(`/api/vibecoding/sessions/${sessionId}/status`)
      
      if (result.ok && result.data?.ready) {
        setSessionReady(true)
        if (readinessIntervalRef.current) {
          clearInterval(readinessIntervalRef.current)
          readinessIntervalRef.current = null
        }
        return true
      } else {
        addLine(`Session starting: ${result.data?.message || 'Preparing container...'}`, 'system')
        return false
      }
    } catch (error) {
      console.error('Error checking session readiness:', error)
      addLine(`Error checking session status: ${error}`, 'error')
      return false
    } finally {
      setReadinessChecking(false)
    }
  }, [sessionId, readinessChecking, addLine])

  const connectWebSocket = useCallback(async () => {
    if (!sessionId || websocketRef.current?.readyState === WebSocket.OPEN) return

    // Check readiness first
    const ready = await checkSessionReadiness()
    if (!ready) {
      addLine('⏳ Waiting for session to be ready...', 'system')
      // Set up periodic readiness checking
      if (!readinessIntervalRef.current) {
        readinessIntervalRef.current = setInterval(async () => {
          const isReady = await checkSessionReadiness()
          if (isReady) {
            connectWebSocket()
          }
        }, 2000)
      }
      return
    }

    setIsConnecting(true)
    addLine('🔌 Establishing optimized terminal connection...', 'system')

    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vibecoding/container/${sessionId}/terminal`
      
      const ws = new WebSocket(wsUrl)
      // Configure for binary support and better performance
      ws.binaryType = 'arraybuffer'
      websocketRef.current = ws

      let connectionTimeout = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close()
          addLine('❌ Connection timeout - trying alternative method...', 'error')
          setIsConnecting(false)
        }
      }, 10000)

      ws.onopen = () => {
        clearTimeout(connectionTimeout)
        setIsConnected(true)
        setIsConnecting(false)
        addLine('✅ Terminal connected - Enhanced performance mode active!', 'system')
        addLine('💡 Features: Command history (↑/↓), auto-completion, optimized I/O', 'system')
        addLine('', 'system')
        
        onReady?.()
        
        // Focus input after connection
        setTimeout(() => {
          inputRef.current?.focus()
        }, 100)
      }

      ws.onmessage = (event) => {
        try {
          // Handle binary messages for optimized terminal I/O
          if (event.data instanceof ArrayBuffer) {
            const decoder = new TextDecoder('utf-8', { fatal: false })
            const content = decoder.decode(event.data)
            if (content.trim()) {
              addLine(content, 'output')
            }
            return
          }
          
          // Handle text messages
          if (typeof event.data === 'string') {
            try {
              // Try to parse as JSON first (for structured messages)
              const data = JSON.parse(event.data)
              if (data.type === 'error') {
                addLine(`❌ Error: ${data.message}`, 'error')
              } else if (data.type === 'system') {
                addLine(data.message, 'system')
              } else if (data.type === 'ready') {
                addLine('🚀 Terminal ready for input', 'system')
              } else {
                addLine(data.content || event.data, 'output')
              }
            } catch {
              // Raw terminal output - handle ANSI escape codes if needed
              const content = event.data
              if (content.trim()) {
                addLine(content, 'output')
              }
            }
          }
        } catch (error) {
          console.error('Error processing terminal message:', error)
          addLine('Error processing terminal output', 'error')
        }
      }

      ws.onerror = (error) => {
        console.error('Terminal WebSocket error:', error)
        addLine('❌ Terminal connection error - attempting reconnection...', 'error')
        setIsConnected(false)
        setIsConnecting(false)
      }

      ws.onclose = (event) => {
        setIsConnected(false)
        setIsConnecting(false)
        
        if (event.wasClean) {
          addLine('🔌 Terminal connection closed cleanly', 'system')
        } else {
          addLine('🔌 Terminal connection lost - auto-reconnecting in 3s...', 'system')
          
          // Auto-reconnect with exponential backoff
          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current)
          }
          
          reconnectTimeoutRef.current = setTimeout(() => {
            if (sessionId && isContainerRunning) {
              connectWebSocket()
            }
          }, 3000)
        }
        
        websocketRef.current = null
      }

    } catch (error) {
      console.error('Failed to connect terminal:', error)
      addLine('❌ Failed to establish terminal connection', 'error')
      setIsConnecting(false)
    }
  }, [sessionId, isContainerRunning, addLine, onReady])

  const disconnectWebSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    
    if (websocketRef.current) {
      websocketRef.current.close()
      websocketRef.current = null
    }
    setIsConnected(false)
  }, [])

  const executeCommandDirect = useCallback(async (command: string) => {
    if (!command.trim() || !sessionId) return

    setIsExecutingCommand(true)
    addLine(`$ ${command}`, 'input')
    
    // Add to command history
    if (command.trim() !== commandHistoryRef.current[0]) {
      commandHistoryRef.current.unshift(command.trim())
      if (commandHistoryRef.current.length > 100) {
        commandHistoryRef.current = commandHistoryRef.current.slice(0, 100)
      }
    }
    historyIndexRef.current = -1

    try {
      // Try WebSocket first (faster)
      if (websocketRef.current?.readyState === WebSocket.OPEN) {
        // Send as binary for better performance
        const encoder = new TextEncoder()
        const data = encoder.encode(command + '\n')
        websocketRef.current.send(data)
      } else {
        // Fallback to HTTP API
        const token = localStorage.getItem('token')
        const result = await apiRequest('/api/vibecoding/files', {
          method: 'POST',
          headers: {
            ...(token && { 'Authorization': `Bearer ${token}` })
          },
          body: JSON.stringify({
            action: 'execute',
            session_id: sessionId,
            command: command
          })
        })

        if (result.ok) {
          addLine(result.data?.output || '', result.data?.success ? 'output' : 'error')
        } else {
          addLine('❌ Command execution failed', 'error')
        }
      }
      
      setCurrentCommand('')
    } catch (error) {
      console.error('Error executing command:', error)
      addLine('❌ Failed to execute command', 'error')
    } finally {
      setIsExecutingCommand(false)
    }
  }, [sessionId, addLine])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      executeCommandDirect(currentCommand)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const history = commandHistoryRef.current
      if (history.length > 0) {
        historyIndexRef.current = Math.min(historyIndexRef.current + 1, history.length - 1)
        setCurrentCommand(history[historyIndexRef.current] || '')
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (historyIndexRef.current > 0) {
        historyIndexRef.current = Math.max(historyIndexRef.current - 1, -1)
        setCurrentCommand(historyIndexRef.current >= 0 ? commandHistoryRef.current[historyIndexRef.current] : '')
      } else {
        historyIndexRef.current = -1
        setCurrentCommand('')
      }
    } else if (e.key === 'Tab') {
      e.preventDefault()
      // Basic tab completion for common commands
      const commonCommands = ['ls', 'cd', 'pwd', 'cat', 'echo', 'mkdir', 'rm', 'cp', 'mv', 'grep', 'find']
      const matches = commonCommands.filter(cmd => cmd.startsWith(currentCommand.toLowerCase()))
      if (matches.length === 1) {
        setCurrentCommand(matches[0] + ' ')
      }
    } else if (e.ctrlKey && e.key === 'c') {
      e.preventDefault()
      // Send interrupt signal
      if (websocketRef.current?.readyState === WebSocket.OPEN) {
        // Send Ctrl+C as binary
        const encoder = new TextEncoder()
        const data = encoder.encode('\x03')
        websocketRef.current.send(data)
      }
      addLine('^C', 'input')
    }
  }, [currentCommand, executeCommandDirect, addLine])

  const clearTerminal = useCallback(() => {
    setLines([{
      id: Date.now().toString(),
      content: 'Terminal cleared - Optimized Vibe Terminal ready',
      timestamp: new Date(),
      type: 'system'
    }])
  }, [])

  const copyTerminalContent = useCallback(() => {
    const content = lines.map(line => line.content).join('\n')
    navigator.clipboard.writeText(content).then(() => {
      addLine('📋 Terminal content copied to clipboard', 'system')
    }).catch(() => {
      addLine('❌ Failed to copy terminal content', 'error')
    })
  }, [lines, addLine])

  // Auto-connect when sessionId changes and container is running with readiness check
  useEffect(() => {
    if (sessionId && isContainerRunning && !websocketRef.current) {
      // Start with readiness check, then connect
      connectWebSocket()
    }
    
    return () => {
      disconnectWebSocket()
      // Clean up readiness checking
      if (readinessIntervalRef.current) {
        clearInterval(readinessIntervalRef.current)
        readinessIntervalRef.current = null
      }
    }
  }, [sessionId, isContainerRunning, connectWebSocket, disconnectWebSocket, checkSessionReadiness])

  const handleContainerStart = async () => {
    if (onContainerStart) {
      addLine('🚀 Starting container...', 'system')
      await onContainerStart()
      // Wait for container to be ready, then connect
      setTimeout(() => {
        connectWebSocket()
      }, 2000)
    }
  }

  const handleContainerStop = async () => {
    disconnectWebSocket()
    if (onContainerStop) {
      addLine('🛑 Stopping container...', 'system')
      await onContainerStop()
    }
  }

  return (
    <div className={`bg-gray-900 border border-gray-700 rounded-lg overflow-hidden flex flex-col shadow-2xl ${
      isMaximized ? 'fixed inset-4 z-50' : ''
    } ${className}`}>
      {/* Enhanced Terminal Title Bar */}
      <div className="bg-gray-800 px-4 py-2 flex items-center justify-between border-b border-gray-700">
        <div className="flex items-center space-x-2">
          {/* macOS-style traffic lights */}
          <div className="flex space-x-2">
            <div className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 cursor-pointer" onClick={handleContainerStop}></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500 hover:bg-yellow-400 cursor-pointer" onClick={() => setIsMaximized(!isMaximized)}></div>
            <div className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-400 cursor-pointer" onClick={() => inputRef.current?.focus()}></div>
          </div>
          
          <Terminal className="w-4 h-4 text-green-400" />
          <span className="text-gray-300 text-sm font-medium">Optimized Terminal</span>
          
          <Badge 
            variant="outline" 
            className={`text-xs border-0 ${
              isConnected 
                ? 'bg-green-900/50 text-green-400' 
                : isConnecting 
                ? 'bg-yellow-900/50 text-yellow-400'
                : 'bg-red-900/50 text-red-400'
            }`}
          >
            {isConnected ? 'Connected' : isConnecting ? 'Connecting...' : 'Disconnected'}
          </Badge>
        </div>

        <div className="flex items-center space-x-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-gray-400 hover:text-gray-300"
            onClick={copyTerminalContent}
            title="Copy terminal content"
          >
            <Copy className="w-3 h-3" />
          </Button>
          
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-gray-400 hover:text-gray-300"
            onClick={clearTerminal}
            title="Clear terminal"
          >
            <RefreshCw className="w-3 h-3" />
          </Button>
          
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-gray-400 hover:text-gray-300"
            onClick={() => setIsMaximized(!isMaximized)}
            title={isMaximized ? "Minimize" : "Maximize"}
          >
            {isMaximized ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </Button>
          
          {!isContainerRunning && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0 text-red-400 hover:text-red-300"
              onClick={handleContainerStart}
              title="Start container"
            >
              <Power className="w-3 h-3" />
            </Button>
          )}
        </div>
      </div>

      {/* Terminal Content */}
      <div className="flex-1 overflow-y-auto bg-black p-3 font-mono text-sm">
        {lines.map((line) => (
          <div 
            key={line.id} 
            className={`mb-1 ${
              line.type === 'input' ? 'text-green-300' : 
              line.type === 'error' ? 'text-red-400' : 
              line.type === 'system' ? 'text-blue-400' : 'text-gray-200'
            }`}
          >
            <span className="whitespace-pre-wrap break-words">{line.content}</span>
          </div>
        ))}
        
        {/* Command Input Line */}
        {isConnected && (
          <div className="flex items-center text-green-300">
            <span className="mr-2">$</span>
            <input
              ref={inputRef}
              type="text"
              value={currentCommand}
              onChange={(e) => setCurrentCommand(e.target.value)}
              onKeyDown={handleKeyDown}
              className="flex-1 bg-transparent outline-none text-gray-200"
              placeholder="Enter command..."
              disabled={isExecutingCommand}
              autoFocus
            />
            {isExecutingCommand && (
              <Loader2 className="w-4 h-4 animate-spin text-yellow-400 ml-2" />
            )}
          </div>
        )}
        
        <div ref={terminalEndRef} />
      </div>

      {/* Status/Help Bar */}
      <div className="bg-gray-800 px-3 py-1 text-xs text-gray-500 border-t border-gray-700">
        <div className="flex justify-between items-center">
          <span>
            {isConnected ? `Session: ${sessionId}` : 'Not connected'}
          </span>
          <span>
            History: {commandHistoryRef.current.length} | ↑/↓: Navigate | Tab: Complete | Ctrl+C: Interrupt
          </span>
        </div>
      </div>
    </div>
  )
}