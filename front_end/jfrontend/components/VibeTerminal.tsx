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
    <div className={`bg-black border border-gray-700 rounded-lg overflow-hidden flex flex-col shadow-2xl ${className}`}>
      {/* Terminal Title Bar - macOS style */}
      <div className="bg-gray-800 px-4 py-2 flex items-center justify-between border-b border-gray-700">
        {/* Traffic Light Buttons */}
        <div className="flex items-center space-x-2">
          <div className="flex space-x-2">
            <div className="w-3 h-3 rounded-full bg-red-500"></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
            <div className="w-3 h-3 rounded-full bg-green-500"></div>
          </div>
          <span className="ml-4 text-gray-300 text-sm font-medium">Terminal</span>
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
            {isConnected ? '●' : isConnecting ? '○' : '○'}
          </Badge>
        </div>
        
        {/* Terminal Controls */}
        <div className="flex items-center space-x-1">
          {!isContainerRunning ? (
            <Button
              onClick={handleContainerStart}
              size="sm"
              className="h-6 px-2 bg-green-600 hover:bg-green-700 text-white text-xs"
              disabled={!sessionId}
            >
              <Power className="w-3 h-3 mr-1" />
              Start
            </Button>
          ) : (
            <Button
              onClick={handleContainerStop}
              size="sm"
              className="h-6 px-2 bg-red-600 hover:bg-red-700 text-white text-xs"
            >
              <PowerOff className="w-3 h-3 mr-1" />
              Stop
            </Button>
          )}
          
          <Button
            onClick={reconnectTerminal}
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-gray-400 hover:text-white hover:bg-gray-700"
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
            variant="ghost"
            className="h-6 px-2 text-gray-400 hover:text-white hover:bg-gray-700 text-xs"
          >
            Clear
          </Button>
        </div>
      </div>

      {/* Terminal Content */}
      <div className="flex-1 min-h-0 bg-black text-green-400 font-mono text-sm overflow-hidden flex flex-col">
        {/* Terminal Output */}
        <div className="flex-1 overflow-y-auto p-4 scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-900">
          <div className="space-y-0">
            {lines.map((line) => (
              <div
                key={line.id}
                className={`leading-relaxed ${
                  line.type === 'input'
                    ? 'text-white'
                    : line.type === 'error'
                      ? 'text-red-400'
                      : line.type === 'system'
                        ? 'text-blue-400'
                        : 'text-green-400'
                }`}
              >
                <span className="whitespace-pre-wrap break-words">{line.content}</span>
              </div>
            ))}
            
            {isExecutingCommand && (
              <div className="text-yellow-400 flex items-center space-x-2 my-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>Executing...</span>
              </div>
            )}
          </div>
          <div ref={terminalEndRef} />
        </div>

        {/* Current Command Line */}
        <div className="border-t border-gray-800 bg-black px-4 py-2">
          <div className="flex items-center">
            <span className="text-green-400 mr-2 select-none">
              user@container:~$
            </span>
            <input
              ref={inputRef}
              value={currentCommand}
              onChange={(e) => setCurrentCommand(e.target.value)}
              onKeyDown={handleKeyDown}
              className="flex-1 bg-transparent text-white outline-none font-mono text-sm caret-green-400"
              placeholder={
                !isConnected 
                  ? (sessionId ? "Terminal not connected" : "No session selected")
                  : ""
              }
              disabled={!isConnected || isExecutingCommand}
              style={{ caretColor: '#4ade80' }}
            />
            {isExecutingCommand && (
              <Loader2 className="w-4 h-4 text-green-400 animate-spin ml-2" />
            )}
          </div>
          
          {!sessionId && (
            <div className="text-xs text-gray-500 mt-2 ml-[120px]">
              Select or create a session to access the terminal
            </div>
          )}
        </div>
      </div>
    </div>
  )
}