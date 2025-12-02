"use client"

import React, { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { Terminal as TerminalIcon, Power, RefreshCw, Maximize2, Minimize2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

interface VibeTerminalProps {
  sessionId: string
  isContainerRunning?: boolean
  onContainerStart?: () => Promise<void>
  className?: string
}

export default function VibeTerminal({
  sessionId,
  isContainerRunning = false,
  onContainerStart,
  className = ""
}: VibeTerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null)
  const xtermRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isMaximized, setIsMaximized] = useState(false)
  
  // Get font size from CSS variable (set by user preferences)
  const [fontSize, setFontSize] = useState(() => {
    if (typeof window !== 'undefined') {
      const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--vibe-font-size')
      return cssVar ? parseInt(cssVar) : 14
    }
    return 14
  })

  // Initialize xterm.js terminal
  useEffect(() => {
    if (!terminalRef.current) return

    // Create terminal instance with dark theme
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: fontSize,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: '#000000',
        foreground: '#d4d4d4',
        cursor: '#d4d4d4',
        black: '#000000',
        red: '#cd3131',
        green: '#0dbc79',
        yellow: '#e5e510',
        blue: '#2472c8',
        magenta: '#bc3fbc',
        cyan: '#11a8cd',
        white: '#e5e5e5',
        brightBlack: '#666666',
        brightRed: '#f14c4c',
        brightGreen: '#23d18b',
        brightYellow: '#f5f543',
        brightBlue: '#3b8eea',
        brightMagenta: '#d670d6',
        brightCyan: '#29b8db',
        brightWhite: '#e5e5e5'
      },
      scrollback: 1000,
      convertEol: true
    })

    // Add fit addon for responsive sizing
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)

    // Open terminal in DOM
    terminal.open(terminalRef.current)
    fitAddon.fit()

    // Store refs
    xtermRef.current = terminal
    fitAddonRef.current = fitAddon

    // Welcome message
    terminal.writeln('\x1b[1;32m╔═══════════════════════════════════════════════════════════╗\x1b[0m')
    terminal.writeln('\x1b[1;32m║\x1b[0m          \x1b[1;36mVibeCode Interactive Terminal\x1b[0m                  \x1b[1;32m║\x1b[0m')
    terminal.writeln('\x1b[1;32m╚═══════════════════════════════════════════════════════════╝\x1b[0m')
    terminal.writeln('')

    // Handle window resize
    const handleResize = () => {
      fitAddon.fit()
    }
    window.addEventListener('resize', handleResize)

    // Cleanup
    return () => {
      window.removeEventListener('resize', handleResize)
      terminal.dispose()
      xtermRef.current = null
      fitAddonRef.current = null
    }
  }, [fontSize])

  // Watch for font size changes from CSS variable (user preferences)
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--vibe-font-size')
      if (cssVar) {
        const newSize = parseInt(cssVar)
        if (newSize !== fontSize && xtermRef.current) {
          setFontSize(newSize)
          xtermRef.current.options.fontSize = newSize
          fitAddonRef.current?.fit()
        }
      }
    })
    
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style']
    })
    
    return () => observer.disconnect()
  }, [fontSize])

  // Connect WebSocket to backend terminal
  const connectWebSocket = React.useCallback(() => {
    if (!sessionId || !xtermRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    
    // CRITICAL: Don't connect if container isn't running
    if (!isContainerRunning) {
      const terminal = xtermRef.current
      console.warn('⚠️ Cannot connect terminal: container not running')
      terminal.writeln('\x1b[33m⚠️ Container is not running. Click "Start Container" first.\x1b[0m')
      return
    }

    setIsConnecting(true)
    const terminal = xtermRef.current

    terminal.writeln('\x1b[33m🔌 Connecting to container terminal...\x1b[0m')

    try {
      // Get token from localStorage
      const token = localStorage.getItem('token')
      if (!token) {
        terminal.writeln('\x1b[31m❌ Authentication token not found\x1b[0m')
        setIsConnecting(false)
        return
      }

      // Construct WebSocket URL
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/ws/vibecoding/terminal?session_id=${sessionId}&token=${token}`
      
      console.log(`🔌 Connecting terminal WebSocket for session ${sessionId}`)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      // Connection timeout
      const connectionTimeout = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close()
          terminal.writeln('\x1b[31m❌ Connection timeout\x1b[0m')
          setIsConnecting(false)
        }
      }, 10000)

      ws.onopen = () => {
        clearTimeout(connectionTimeout)
        setIsConnected(true)
        setIsConnecting(false)
        terminal.writeln('\x1b[32m✅ Connected to container terminal\x1b[0m')
        terminal.writeln('')

        // Send terminal input to WebSocket
        terminal.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(data)
          }
        })
      }

      ws.onmessage = (event) => {
        // Handle binary data (Blob/ArrayBuffer)
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then(buffer => {
            const uint8Array = new Uint8Array(buffer)
            terminal.write(uint8Array)
          })
        } else if (event.data instanceof ArrayBuffer) {
          const uint8Array = new Uint8Array(event.data)
          terminal.write(uint8Array)
        } else {
          // Handle text data
          terminal.write(event.data)
        }
      }

      ws.onerror = (error) => {
        console.error('Terminal WebSocket error:', error)
        terminal.writeln('\x1b[31m❌ Connection error\x1b[0m')
        setIsConnected(false)
        setIsConnecting(false)
      }

      ws.onclose = (event) => {
        setIsConnected(false)
        setIsConnecting(false)

        if (event.wasClean) {
          terminal.writeln('\x1b[33m🔌 Connection closed\x1b[0m')
        } else {
          terminal.writeln('\x1b[31m🔌 Connection lost - reconnecting in 3s...\x1b[0m')

          // Auto-reconnect
          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current)
          }

          reconnectTimeoutRef.current = setTimeout(() => {
            if (sessionId && isContainerRunning) {
              connectWebSocket()
            }
          }, 3000)
        }

        wsRef.current = null
      }

    } catch (error) {
      console.error('Failed to connect terminal:', error)
      terminal.writeln('\x1b[31m❌ Failed to establish connection\x1b[0m')
      setIsConnecting(false)
    }
  }, [sessionId, isContainerRunning])

  // Disconnect WebSocket
  const disconnectWebSocket = React.useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setIsConnected(false)

    if (xtermRef.current) {
      xtermRef.current.writeln('\x1b[33m🔌 Disconnected from terminal\x1b[0m')
    }
  }, [])

  // Auto-connect when container is running
  useEffect(() => {
    if (sessionId && isContainerRunning && !wsRef.current) {
      // Small delay to ensure container is ready
      const timer = setTimeout(() => {
        connectWebSocket()
      }, 500)
      return () => clearTimeout(timer)
    }

    if (!isContainerRunning && wsRef.current) {
      disconnectWebSocket()
    }
  }, [sessionId, isContainerRunning, connectWebSocket, disconnectWebSocket])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnectWebSocket()
    }
  }, [disconnectWebSocket])

  // Handle maximize/minimize
  useEffect(() => {
    if (fitAddonRef.current) {
      // Refit terminal when maximized state changes
      setTimeout(() => {
        fitAddonRef.current?.fit()
      }, 100)
    }
  }, [isMaximized])

  const handleReconnect = () => {
    disconnectWebSocket()
    setTimeout(() => {
      connectWebSocket()
    }, 500)
  }

  const handleClear = () => {
    if (xtermRef.current) {
      xtermRef.current.clear()
    }
  }

  const handleContainerStart = async () => {
    if (onContainerStart) {
      if (xtermRef.current) {
        xtermRef.current.writeln('\x1b[33m🚀 Starting container...\x1b[0m')
      }
      await onContainerStart()
    }
  }

  return (
    <div
      className={`bg-gray-900 border border-gray-700 rounded-lg overflow-hidden flex flex-col shadow-2xl ${
        isMaximized ? 'fixed inset-4 z-50' : ''
      } ${className}`}
    >
      {/* Terminal Title Bar */}
      <div className="bg-gray-800 px-4 py-2 flex items-center justify-between border-b border-gray-700">
        <div className="flex items-center space-x-2">
          {/* macOS-style traffic lights */}
          <div className="flex space-x-2">
            <div className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 cursor-pointer" onClick={disconnectWebSocket}></div>
            <div className="w-3 h-3 rounded-full bg-yellow-500 hover:bg-yellow-400 cursor-pointer" onClick={() => setIsMaximized(!isMaximized)}></div>
            <div className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-400 cursor-pointer" onClick={() => xtermRef.current?.focus()}></div>
          </div>

          <TerminalIcon className="w-4 h-4 text-green-400" />
          <span className="text-gray-300 text-sm font-medium">Terminal</span>

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
            onClick={handleClear}
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
              className="h-6 w-6 p-0 text-green-400 hover:text-green-300"
              onClick={handleContainerStart}
              title="Start container"
            >
              <Power className="w-3 h-3" />
            </Button>
          )}

          {isContainerRunning && !isConnected && !isConnecting && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 w-6 p-0 text-blue-400 hover:text-blue-300"
              onClick={handleReconnect}
              title="Reconnect"
            >
              <RefreshCw className="w-3 h-3" />
            </Button>
          )}
        </div>
      </div>

      {/* Terminal Content */}
      <div className="flex-1 overflow-hidden bg-black">
        <div ref={terminalRef} className="h-full w-full" />
      </div>

      {/* Status Bar */}
      {!isContainerRunning && (
        <div className="bg-gray-800 px-3 py-2 text-xs text-yellow-400 border-t border-gray-700 flex items-center justify-center">
          <span>⚠️ Container is not running. Start the container to use the terminal.</span>
        </div>
      )}
    </div>
  )
}
