"use client"

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { 
  Terminal, 
  Power, 
  RefreshCw, 
  Maximize2, 
  Minimize2, 
  Copy, 
  Loader2,
  Container,
  AlertTriangle,
  CheckCircle,
  Clock
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useSessionStatus } from '@/hooks/useSessionStatus'

// Dynamic imports for browser-only libraries
let XTerm: any = null
let FitAddon: any = null 
let WebLinksAddon: any = null

interface TerminalClientProps {
  sessionId: string
  isContainerRunning?: boolean
  onContainerStart?: () => Promise<void>
  onContainerStop?: () => Promise<void>
  onReady?: () => void
  className?: string
}

type ContainerStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'error'

export default function TerminalClient({ 
  sessionId, 
  isContainerRunning = false,
  onContainerStart,
  onContainerStop,
  onReady,
  className = "" 
}: TerminalClientProps) {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isMaximized, setIsMaximized] = useState(false)
  const [containerStatus, setContainerStatus] = useState<ContainerStatus>(isContainerRunning ? 'running' : 'stopped')
  const [connectionError, setConnectionError] = useState<string | null>(null)
  
  // Use session status hook for robust status checking
  const {
    sessionStatus,
    isLoading: isStatusLoading,
    error: statusError,
    isReady,
    isStarting,
    isStopped,
    hasError,
    startSession,
    stopSession
  } = useSessionStatus({ sessionId, pollWhenNotRunning: true, pollInterval: 2000 })
  
  const terminalRef = useRef<HTMLDivElement>(null)
  const xtermRef = useRef<any>(null)
  const websocketRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)

  // Initialize terminal
  const initializeTerminal = useCallback(async () => {
    if (!terminalRef.current || xtermRef.current) return

    // Dynamic imports for browser-only libraries
    if (!XTerm) {
      try {
        const [xtermModule, fitAddonModule, webLinksModule] = await Promise.all([
          import('@xterm/xterm').then(m => m.Terminal),
          import('@xterm/addon-fit').then(m => m.FitAddon),
          import('@xterm/addon-web-links').then(m => m.WebLinksAddon)
        ])
        XTerm = xtermModule
        FitAddon = fitAddonModule
        WebLinksAddon = webLinksModule
        
        // Import CSS dynamically
        await import('@xterm/xterm/css/xterm.css')
      } catch (error) {
        console.error('Failed to load xterm dependencies:', error)
        return
      }
    }

    const xterm = new XTerm({
      theme: {
        background: '#0D1117',
        foreground: '#F0F6FC',
        cursor: '#7C3AED',
        cursorAccent: '#7C3AED',
        selection: '#7C3AED33',
        black: '#21262D',
        red: '#F85149',
        green: '#56D364',
        yellow: '#E3B341',
        blue: '#79C0FF',
        magenta: '#D2A8FF',
        cyan: '#39D0D8',
        white: '#B1BAC4',
        brightBlack: '#6E7681',
        brightRed: '#F85149',
        brightGreen: '#56D364',
        brightYellow: '#E3B341',
        brightBlue: '#79C0FF',
        brightMagenta: '#D2A8FF',
        brightCyan: '#39D0D8',
        brightWhite: '#F0F6FC'
      },
      fontFamily: '"JetBrains Mono", "Consolas", "Courier New", monospace',
      fontSize: 14,
      fontWeight: 400,
      lineHeight: 1.2,
      cursorBlink: true,
      cursorStyle: 'bar',
      allowTransparency: false,
      convertEol: true,
      scrollback: 1000,
      tabStopWidth: 4
    })

    const fitAddon = new FitAddon()
    const webLinksAddon = new WebLinksAddon()

    xterm.loadAddon(fitAddon)
    xterm.loadAddon(webLinksAddon)

    xterm.open(terminalRef.current)
    fitAddon.fit()

    xtermRef.current = xterm
    fitAddonRef.current = fitAddon

    // Welcome message
    xterm.writeln('\x1b[1;32m╭─────────────────────────────────────────────────────────╮\x1b[0m')
    xterm.writeln('\x1b[1;32m│\x1b[0m                  \x1b[1;35mHarvis Terminal\x1b[0m                     \x1b[1;32m│\x1b[0m')
    xterm.writeln('\x1b[1;32m│\x1b[0m           Interactive Development Environment          \x1b[1;32m│\x1b[0m')
    xterm.writeln('\x1b[1;32m╰─────────────────────────────────────────────────────────╯\x1b[0m')
    xterm.writeln('')

    if (containerStatus !== 'running') {
      xterm.writeln('\x1b[1;33m⚠ Container is not running. Start container to begin.\x1b[0m')
      xterm.writeln('')
    }

    // Handle terminal input
    xterm.onData((data: string) => {
      if (websocketRef.current && websocketRef.current.readyState === WebSocket.OPEN) {
        // Send as JSON for better control
        websocketRef.current.send(JSON.stringify({
          type: 'stdin',
          data: data
        }))
      }
    })

    // Handle window resize
    const handleResize = () => {
      if (fitAddonRef.current && xtermRef.current) {
        setTimeout(() => {
          fitAddonRef.current?.fit()
          
          // Send resize info to backend
          if (websocketRef.current && websocketRef.current.readyState === WebSocket.OPEN) {
            websocketRef.current.send(JSON.stringify({
              type: 'resize',
              cols: xtermRef.current?.cols || 80,
              rows: xtermRef.current?.rows || 24
            }))
          }
        }, 100)
      }
    }

    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [containerStatus])

  // Connect to WebSocket - only when session is ready
  const connectWebSocket = useCallback(() => {
    if (websocketRef.current || !sessionId) return
    
    // SESSION GUARD: Only connect if session is ready
    if (!isReady) {
      console.log(`🚫 TerminalClient: Session ${sessionId} not ready, current state: ${sessionStatus?.state}`)
      if (xtermRef.current) {
        xtermRef.current.writeln(`\x1b[1;33m⏳ Session is ${sessionStatus?.state || 'unknown'}. Waiting for ready state...\x1b[0m`)
      }
      return
    }

    setIsConnecting(true)
    setConnectionError(null)

    const wsUrl = `/ws/terminal/${sessionId}`
    console.log(`🔌 TerminalClient: Connecting to terminal WebSocket: ${wsUrl}`)
    const ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${wsUrl}`)
    
    ws.onopen = () => {
      setIsConnected(true)
      setIsConnecting(false)
      setConnectionError(null)
      
      if (xtermRef.current) {
        xtermRef.current.writeln('\x1b[1;32m✓ Connected to terminal session\x1b[0m')
        
        // Send initial resize
        setTimeout(() => {
          if (websocketRef.current && websocketRef.current.readyState === WebSocket.OPEN) {
            websocketRef.current.send(JSON.stringify({
              type: 'resize',
              cols: xtermRef.current?.cols || 80,
              rows: xtermRef.current?.rows || 24
            }))
          }
        }, 100)
      }

      onReady?.()
    }

    ws.onmessage = (event) => {
      try {
        // Try to parse as JSON first
        const data = JSON.parse(event.data)
        
        if (data.type === 'output' || data.type === 'stdout') {
          xtermRef.current?.write(data.data)
        } else if (data.type === 'error') {
          xtermRef.current?.writeln(`\x1b[1;31mError: ${data.message}\x1b[0m`)
        } else if (data.type === 'container_status') {
          setContainerStatus(data.status)
          if (data.status === 'running') {
            xtermRef.current?.writeln('\x1b[1;32m✓ Container is now running\x1b[0m')
          } else if (data.status === 'stopped') {
            xtermRef.current?.writeln('\x1b[1;31m✗ Container stopped\x1b[0m')
          }
        }
      } catch {
        // Fallback: treat as raw terminal output
        xtermRef.current?.write(event.data)
      }
    }

    ws.onerror = () => {
      setConnectionError('WebSocket connection failed')
      setIsConnecting(false)
    }

    ws.onclose = () => {
      setIsConnected(false)
      setIsConnecting(false)
      
      if (xtermRef.current) {
        xtermRef.current.writeln('\x1b[1;31m✗ Terminal connection closed\x1b[0m')
      }

      // Auto-reconnect after 2 seconds
      setTimeout(() => {
        if (sessionId && !websocketRef.current) {
          connectWebSocket()
        }
      }, 2000)
    }

    websocketRef.current = ws
  }, [sessionId, onReady])

  // Disconnect WebSocket
  const disconnectWebSocket = useCallback(() => {
    if (websocketRef.current) {
      websocketRef.current.close()
      websocketRef.current = null
    }
    setIsConnected(false)
    setIsConnecting(false)
  }, [])

  // Container actions with session lifecycle
  const handleContainerStart = async () => {
    console.log(`🚀 TerminalClient: Starting session ${sessionId}`)
    xtermRef.current?.writeln('\x1b[1;33m🚀 Starting session...\x1b[0m')
    
    try {
      const result = await startSession()
      if (result.success) {
        xtermRef.current?.writeln(`\x1b[1;32m✅ ${result.message || 'Session start initiated'}\x1b[0m`)
        if (result.jobId) {
          xtermRef.current?.writeln(`\x1b[1;34mJob ID: ${result.jobId}\x1b[0m`)
        }
      } else {
        xtermRef.current?.writeln(`\x1b[1;31m❌ ${result.message || 'Failed to start session'}\x1b[0m`)
      }
      
      // Also call legacy handler if provided
      await onContainerStart?.()
    } catch (error) {
      xtermRef.current?.writeln(`\x1b[1;31m❌ Start error: ${error}\x1b[0m`)
    }
  }

  const handleContainerStop = async () => {
    console.log(`🛑 TerminalClient: Stopping session ${sessionId}`)
    xtermRef.current?.writeln('\x1b[1;33m🛑 Stopping session...\x1b[0m')
    
    // Disconnect WebSocket first
    disconnectWebSocket()
    
    try {
      const result = await stopSession()
      if (result.success) {
        xtermRef.current?.writeln(`\x1b[1;32m✅ ${result.message || 'Session stopped'}\x1b[0m`)
      } else {
        xtermRef.current?.writeln(`\x1b[1;31m❌ ${result.message || 'Failed to stop session'}\x1b[0m`)
      }
      
      // Also call legacy handler if provided  
      await onContainerStop?.()
    } catch (error) {
      xtermRef.current?.writeln(`\x1b[1;31m❌ Stop error: ${error}\x1b[0m`)
    }
  }

  const handleRefresh = () => {
    disconnectWebSocket()
    setTimeout(() => {
      connectWebSocket()
    }, 500)
  }

  const handleCopy = async () => {
    if (xtermRef.current) {
      const selection = xtermRef.current.getSelection()
      if (selection) {
        try {
          await navigator.clipboard.writeText(selection)
          xtermRef.current.writeln('\x1b[1;32m✓ Copied to clipboard\x1b[0m')
        } catch (error) {
          xtermRef.current.writeln('\x1b[1;31m✗ Failed to copy to clipboard\x1b[0m')
        }
      }
    }
  }

  // Initialize terminal on mount
  useEffect(() => {
    const init = async () => {
      await initializeTerminal()
    }
    
    init()

    return () => {
      disconnectWebSocket()
      if (xtermRef.current) {
        xtermRef.current.dispose()
        xtermRef.current = null
      }
    }
  }, [sessionId, initializeTerminal, disconnectWebSocket])

  // Connect WebSocket when session becomes ready
  useEffect(() => {
    if (isReady && xtermRef.current && !isConnected && !isConnecting) {
      console.log(`✅ TerminalClient: Session ${sessionId} is ready, connecting WebSocket`)
      connectWebSocket()
    }
  }, [isReady, sessionId, isConnected, isConnecting, connectWebSocket])

  // Update terminal messages based on session status
  useEffect(() => {
    if (!xtermRef.current || !sessionStatus) return
    
    // Update container status from session status
    if (sessionStatus.state !== containerStatus) {
      setContainerStatus(sessionStatus.state as ContainerStatus)
      
      // Show status messages in terminal
      if (sessionStatus.state === 'starting') {
        xtermRef.current.writeln('\x1b[1;33m🚀 Container is starting...\x1b[0m')
      } else if (sessionStatus.state === 'running' && !isConnected) {
        xtermRef.current.writeln('\x1b[1;32m✅ Session is ready! Connecting to terminal...\x1b[0m')
      } else if (sessionStatus.state === 'stopped') {
        xtermRef.current.writeln('\x1b[1;31m🛑 Session stopped\x1b[0m')
      } else if (sessionStatus.state === 'error') {
        xtermRef.current.writeln(`\x1b[1;31m❌ Session error: ${sessionStatus.error_message || 'Unknown error'}\x1b[0m`)
      }
    }
  }, [sessionStatus, containerStatus, isConnected])

  // Handle session status errors
  useEffect(() => {
    if (statusError && xtermRef.current) {
      xtermRef.current.writeln(`\x1b[1;31m❌ Status check failed: ${statusError}\x1b[0m`)
    }
  }, [statusError])

  // Update container status (legacy support)
  useEffect(() => {
    if (isContainerRunning && !isReady) {
      // Legacy prop suggests container is running, but session status says otherwise
      console.warn('TerminalClient: isContainerRunning prop conflicts with session status')
    }
  }, [isContainerRunning, isReady])

  const getStatusIcon = () => {
    switch (containerStatus) {
      case 'starting':
        return <Loader2 className="w-3 h-3 animate-spin text-yellow-400" />
      case 'running':
        return <CheckCircle className="w-3 h-3 text-green-400" />
      case 'stopping':
        return <Loader2 className="w-3 h-3 animate-spin text-orange-400" />
      case 'error':
        return <AlertTriangle className="w-3 h-3 text-red-400" />
      default:
        return <Clock className="w-3 h-3 text-gray-400" />
    }
  }

  const getStatusColor = () => {
    switch (containerStatus) {
      case 'starting':
        return 'border-yellow-500 text-yellow-400'
      case 'running':
        return 'border-green-500 text-green-400'
      case 'stopping':
        return 'border-orange-500 text-orange-400'
      case 'error':
        return 'border-red-500 text-red-400'
      default:
        return 'border-gray-500 text-gray-400'
    }
  }

  return (
    <Card className={`bg-gray-900/50 backdrop-blur-sm border-green-500/30 flex flex-col ${
      isMaximized ? 'fixed inset-4 z-50' : className
    }`}>
      {/* Header */}
      <div className="p-3 border-b border-green-500/30 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Terminal className="w-4 h-4 text-green-400" />
            <h3 className="text-sm font-semibold text-green-300">Terminal</h3>
            
            {/* Connection Status */}
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
              {isConnecting ? (
                <>
                  <Loader2 className="w-2 h-2 mr-1 animate-spin" />
                  Connecting
                </>
              ) : isConnected ? (
                'Connected'
              ) : (
                'Disconnected'
              )}
            </Badge>

            {/* Container Status */}
            <Badge 
              variant="outline" 
              className={`text-xs ${getStatusColor()}`}
            >
              {getStatusIcon()}
              <span className="ml-1 capitalize">{containerStatus}</span>
            </Badge>
          </div>
          
          <div className="flex items-center space-x-1">
            {/* Container Controls */}
            {containerStatus === 'stopped' || containerStatus === 'error' ? (
              <Button
                onClick={handleContainerStart}
                size="sm"
                className="bg-green-600 hover:bg-green-700 text-white text-xs px-2 py-1"
                disabled={containerStatus === 'starting'}
              >
                {containerStatus === 'starting' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Power className="w-3 h-3" />
                )}
              </Button>
            ) : (
              <Button
                onClick={handleContainerStop}
                size="sm"
                variant="outline"
                className="border-red-600 text-red-400 hover:bg-red-600 hover:text-white text-xs px-2 py-1"
                disabled={containerStatus === 'stopping'}
              >
                {containerStatus === 'stopping' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Power className="w-3 h-3" />
                )}
              </Button>
            )}

            <Button
              onClick={handleRefresh}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300 text-xs px-2 py-1"
              disabled={isConnecting}
            >
              <RefreshCw className={`w-3 h-3 ${isConnecting ? 'animate-spin' : ''}`} />
            </Button>
            
            <Button
              onClick={handleCopy}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300 text-xs px-2 py-1"
            >
              <Copy className="w-3 h-3" />
            </Button>
            
            <Button
              onClick={() => setIsMaximized(!isMaximized)}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300 text-xs px-2 py-1"
            >
              {isMaximized ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
            </Button>
          </div>
        </div>

        {/* Container Building Indicator */}
        {containerStatus === 'starting' && (
          <div className="mt-2 flex items-center space-x-2 text-sm text-yellow-400">
            <Container className="w-4 h-4" />
            <span>Building development container...</span>
            <div className="flex space-x-1">
              <div className="w-1 h-1 bg-yellow-400 rounded-full animate-bounce"></div>
              <div className="w-1 h-1 bg-yellow-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
              <div className="w-1 h-1 bg-yellow-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
            </div>
          </div>
        )}

        {connectionError && (
          <div className="mt-2 text-sm text-red-400 flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4" />
            <span>{connectionError}</span>
          </div>
        )}
      </div>

      {/* Terminal */}
      <div className="flex-1 bg-gray-950 border border-gray-800 rounded-b-lg overflow-hidden">
        <div ref={terminalRef} className="h-full w-full p-2" />
      </div>
    </Card>
  )
}