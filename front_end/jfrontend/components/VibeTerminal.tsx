"use client"

import React, { useState, useRef, useEffect, useCallback } from "react"
import { Terminal, Send, RefreshCw, Power, PowerOff, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface VibeTerminalProps {
  sessionId: string | null
  isContainerRunning?: boolean
  onContainerStart?: () => Promise<void>
  onContainerStop?: () => Promise<void>
  className?: string
}

interface TerminalLine {
  id: string
  content: string
  timestamp: Date
  type: 'output' | 'input' | 'error' | 'system'
}

export default function VibeTerminal({
  sessionId,
  isContainerRunning = false,
  onContainerStart,
  onContainerStop,
  className = ""
}: VibeTerminalProps) {
  const [lines, setLines] = useState<TerminalLine[]>([
    {
      id: '1',
      content: 'Vibe Terminal - Connecting to development environment...',
      timestamp: new Date(),
      type: 'system'
    }
  ])
  const [currentCommand, setCurrentCommand] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isExecutingCommand, setIsExecutingCommand] = useState(false)
  
  const websocketRef = useRef<WebSocket | null>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const commandHistoryRef = useRef<string[]>([])
  const historyIndexRef = useRef(-1)

  const addLine = useCallback((content: string, type: TerminalLine['type'] = 'output') => {
    const newLine: TerminalLine = {
      id: Date.now().toString() + Math.random(),
      content,
      timestamp: new Date(),
      type
    }
    
    setLines(prev => [...prev, newLine])
  }, [])

  const scrollToBottom = useCallback(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [lines, scrollToBottom])

  const connectWebSocket = useCallback(async () => {
    if (!sessionId || websocketRef.current) return

    setIsConnecting(true)
    addLine('Establishing terminal connection...', 'system')

    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/api/vibecoding/container/${sessionId}/terminal`
      
      const ws = new WebSocket(wsUrl)
      websocketRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        setIsConnecting(false)
        addLine('✅ Terminal connected - Ready for commands!', 'system')
        addLine('Type commands and press Enter to execute in your development container.', 'system')
        
        // Focus input after connection
        setTimeout(() => {
          inputRef.current?.focus()
        }, 100)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'error') {
            addLine(`❌ Error: ${data.message}`, 'error')
          } else {
            addLine(event.data, 'output')
          }
        } catch {
          // Raw terminal output
          addLine(event.data, 'output')
        }
      }

      ws.onerror = (error) => {
        console.error('Terminal WebSocket error:', error)
        addLine('❌ Terminal connection error', 'error')
        setIsConnected(false)
        setIsConnecting(false)
      }

      ws.onclose = () => {
        setIsConnected(false)
        setIsConnecting(false)
        addLine('🔌 Terminal connection closed', 'system')
        websocketRef.current = null
      }

    } catch (error) {
      console.error('Failed to connect terminal:', error)
      addLine('❌ Failed to establish terminal connection', 'error')
      setIsConnecting(false)
    }
  }, [sessionId, addLine])

  const disconnectWebSocket = useCallback(() => {
    if (websocketRef.current) {
      websocketRef.current.close()
      websocketRef.current = null
    }
    setIsConnected(false)
  }, [])

  const executeCommand = useCallback(async (command: string) => {
    if (!command.trim() || !websocketRef.current || !isConnected) return

    setIsExecutingCommand(true)
    addLine(`$ ${command}`, 'input')
    
    // Add to command history
    commandHistoryRef.current.unshift(command)
    if (commandHistoryRef.current.length > 50) {
      commandHistoryRef.current = commandHistoryRef.current.slice(0, 50)
    }
    historyIndexRef.current = -1

    try {
      // Send command through WebSocket
      websocketRef.current.send(command + '\n')
      setCurrentCommand('')
    } catch (error) {
      console.error('Error sending command:', error)
      addLine('❌ Failed to send command', 'error')
    } finally {
      setIsExecutingCommand(false)
    }
  }, [isConnected, addLine])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      executeCommand(currentCommand)
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
      // TODO: Implement tab completion
    }
  }, [currentCommand, executeCommand])

  const clearTerminal = useCallback(() => {
    setLines([{
      id: Date.now().toString(),
      content: 'Terminal cleared',
      timestamp: new Date(),
      type: 'system'
    }])
  }, [])

  const reconnectTerminal = useCallback(() => {
    disconnectWebSocket()
    setTimeout(() => {
      connectWebSocket()
    }, 1000)
  }, [disconnectWebSocket, connectWebSocket])

  // Auto-connect when sessionId changes and container is running
  useEffect(() => {
    if (sessionId && isContainerRunning && !websocketRef.current) {
      connectWebSocket()
    }
    
    return () => {
      disconnectWebSocket()
    }
  }, [sessionId, isContainerRunning, connectWebSocket, disconnectWebSocket])

  const handleContainerStart = async () => {
    if (onContainerStart) {
      await onContainerStart()
      // Wait a moment for container to be ready, then connect
      setTimeout(() => {
        connectWebSocket()
      }, 2000)
    }
  }

  const handleContainerStop = async () => {
    disconnectWebSocket()
    if (onContainerStop) {
      await onContainerStop()
    }
  }

  return (
    <Card className={`bg-gray-900/95 backdrop-blur-sm border-green-500/30 flex flex-col ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-green-500/30 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Terminal className="w-5 h-5 text-green-400" />
            <h3 className="text-lg font-semibold text-green-300">Development Terminal</h3>
            <Badge 
              variant="outline" 
              className={`text-xs ${
                isConnected 
                  ? 'border-green-500 text-green-400' 
                  : isConnecting 
                    ? 'border-yellow-500 text-yellow-400' 
                    : 'border-red-500 text-red-400'
              }`}
            >
              {isConnected ? 'Connected' : isConnecting ? 'Connecting...' : 'Disconnected'}
            </Badge>
          </div>
          
          <div className="flex items-center space-x-2">
            {/* Container Controls */}
            {!isContainerRunning ? (
              <Button
                onClick={handleContainerStart}
                size="sm"
                className="bg-green-600 hover:bg-green-700 text-white"
                disabled={!sessionId}
              >
                <Power className="w-3 h-3 mr-1" />
                Start Container
              </Button>
            ) : (
              <Button
                onClick={handleContainerStop}
                size="sm"
                variant="outline"
                className="border-red-500 text-red-400 hover:bg-red-500/20"
              >
                <PowerOff className="w-3 h-3 mr-1" />
                Stop Container
              </Button>
            )}
            
            <Button
              onClick={reconnectTerminal}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
              disabled={isConnecting || !sessionId}
            >
              {isConnecting ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
            </Button>
            
            <Button
              onClick={clearTerminal}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
            >
              Clear
            </Button>
          </div>
        </div>
      </div>

      {/* Terminal Output */}
      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        <div className="flex-1 overflow-y-auto bg-black p-4 font-mono text-sm">
          <div className="space-y-1">
            {lines.map((line) => (
              <div
                key={line.id}
                className={`whitespace-pre-wrap break-words ${
                  line.type === 'input'
                    ? 'text-cyan-300 font-semibold'
                    : line.type === 'error'
                      ? 'text-red-400'
                      : line.type === 'system'
                        ? 'text-yellow-400'
                        : 'text-green-300'
                }`}
              >
                {line.content}
              </div>
            ))}
            
            {isExecutingCommand && (
              <div className="text-yellow-400 flex items-center space-x-2">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>Executing command...</span>
              </div>
            )}
            
            <div ref={terminalEndRef} />
          </div>
        </div>

        {/* Command Input */}
        <div className="flex-shrink-0 p-4 border-t border-green-500/30 bg-gray-900/50">
          <div className="flex items-center space-x-2">
            <span className="text-green-400 font-mono text-sm select-none">$</span>
            <Input
              ref={inputRef}
              value={currentCommand}
              onChange={(e) => setCurrentCommand(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isConnected 
                  ? "Enter command..." 
                  : sessionId 
                    ? "Terminal not connected" 
                    : "No session selected"
              }
              className="flex-1 bg-black border-gray-600 text-green-300 font-mono text-sm focus:border-green-500"
              disabled={!isConnected || isExecutingCommand}
            />
            <Button
              onClick={() => executeCommand(currentCommand)}
              disabled={!isConnected || !currentCommand.trim() || isExecutingCommand}
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              {isExecutingCommand ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Send className="w-3 h-3" />
              )}
            </Button>
          </div>
          
          {!sessionId && (
            <p className="text-xs text-gray-400 mt-2">
              Select or create a session to access the terminal
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}