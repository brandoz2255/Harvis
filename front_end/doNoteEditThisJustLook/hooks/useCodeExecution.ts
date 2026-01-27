"use client"

import { useState, useEffect, useRef, useCallback } from 'react'

export interface ExecutionResult {
  id: string
  command: string
  output: string
  exitCode: number
  executionTime: number
  language: string
  timestamp: Date
}

export interface ExecutionStatus {
  isConnected: boolean
  isExecuting: boolean
  currentCommand?: string
  error?: string
}

interface UseCodeExecutionProps {
  sessionId: string
  onOutput?: (output: string) => void
  onError?: (error: string) => void
  onResult?: (result: ExecutionResult) => void
}

export function useCodeExecution({ 
  sessionId, 
  onOutput, 
  onError, 
  onResult 
}: UseCodeExecutionProps) {
  const [socket, setSocket] = useState<WebSocket | null>(null)
  const [status, setStatus] = useState<ExecutionStatus>({
    isConnected: false,
    isExecuting: false
  })
  const [outputBuffer, setOutputBuffer] = useState<string[]>([])
  const [executionHistory, setExecutionHistory] = useState<ExecutionResult[]>([])
  
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const reconnectAttemptsRef = useRef(0)
  const maxReconnectAttempts = 5

  const connect = useCallback(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      return // Already connected
    }

    try {
      // Determine WebSocket URL
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const wsUrl = `${protocol}//${host}/ws/execution/${sessionId}`
      
      const newSocket = new WebSocket(wsUrl)
      
      newSocket.onopen = () => {
        console.log('WebSocket connected for execution')
        setStatus(prev => ({ ...prev, isConnected: true, error: undefined }))
        setSocket(newSocket)
        reconnectAttemptsRef.current = 0
      }

      newSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          switch (data.type) {
            case 'output':
              setOutputBuffer(prev => [...prev, data.content])
              onOutput?.(data.content)
              break
              
            case 'error':
              const errorMsg = data.content || 'Execution error'
              setStatus(prev => ({ ...prev, error: errorMsg }))
              onError?.(errorMsg)
              break
              
            case 'result':
              const result: ExecutionResult = {
                id: data.id || Date.now().toString(),
                command: data.command,
                output: data.output,
                exitCode: data.exit_code || 0,
                executionTime: data.execution_time || 0,
                language: data.language || 'unknown',
                timestamp: new Date()
              }
              setExecutionHistory(prev => [result, ...prev.slice(0, 19)]) // Keep last 20
              setStatus(prev => ({ ...prev, isExecuting: false, currentCommand: undefined }))
              onResult?.(result)
              break
              
            case 'status':
              setStatus(prev => ({ 
                ...prev, 
                isExecuting: data.executing || false,
                currentCommand: data.command 
              }))
              break
              
            default:
              console.log('Unknown WebSocket message type:', data.type)
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error)
        }
      }

      newSocket.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason)
        setSocket(null)
        setStatus(prev => ({ 
          ...prev, 
          isConnected: false, 
          isExecuting: false 
        }))
        
        // Attempt reconnection if not a normal closure
        if (event.code !== 1000 && reconnectAttemptsRef.current < maxReconnectAttempts) {
          const delay = Math.pow(2, reconnectAttemptsRef.current) * 1000 // Exponential backoff
          reconnectAttemptsRef.current++
          
          console.log(`Attempting reconnect ${reconnectAttemptsRef.current}/${maxReconnectAttempts} in ${delay}ms`)
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setStatus(prev => ({ 
            ...prev, 
            error: 'Failed to connect after multiple attempts' 
          }))
        }
      }

      newSocket.onerror = (error) => {
        console.error('WebSocket error:', error)
        setStatus(prev => ({ 
          ...prev, 
          error: 'WebSocket connection error' 
        }))
      }

    } catch (error) {
      console.error('Failed to create WebSocket connection:', error)
      setStatus(prev => ({ 
        ...prev, 
        error: 'Failed to establish connection' 
      }))
    }
  }, [sessionId, onOutput, onError, onResult])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    
    if (socket) {
      socket.close(1000, 'User disconnect')
      setSocket(null)
    }
    
    setStatus({
      isConnected: false,
      isExecuting: false
    })
  }, [socket])

  const executeCode = useCallback((code: string, language: string = 'python', filename?: string) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      onError?.('Not connected to execution server')
      return false
    }

    if (status.isExecuting) {
      onError?.('Another execution is in progress')
      return false
    }

    try {
      const message = {
        action: 'execute',
        code,
        language,
        filename: filename || `temp.${getFileExtension(language)}`,
        options: {
          timeout: 30000, // 30 second timeout
          capture_output: true
        }
      }

      socket.send(JSON.stringify(message))
      setStatus(prev => ({ 
        ...prev, 
        isExecuting: true, 
        currentCommand: `Running ${language} code...`,
        error: undefined
      }))
      setOutputBuffer([]) // Clear previous output
      
      return true
    } catch (error) {
      console.error('Failed to send execution message:', error)
      onError?.('Failed to send execution request')
      return false
    }
  }, [socket, status.isExecuting, onError])

  const cancelExecution = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: 'cancel' }))
    }
  }, [socket])

  const clearOutput = useCallback(() => {
    setOutputBuffer([])
  }, [])

  const getFileExtension = (language: string): string => {
    const extMap: { [key: string]: string } = {
      'python': 'py',
      'javascript': 'js',
      'typescript': 'ts',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'rust': 'rs',
      'go': 'go',
      'shell': 'sh',
      'bash': 'sh'
    }
    return extMap[language] || 'txt'
  }

  // Connect on mount and when sessionId changes
  useEffect(() => {
    connect()
    
    return () => {
      disconnect()
    }
  }, [sessionId]) // Only depend on sessionId to avoid infinite re-connections

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      disconnect()
    }
  }, [])

  return {
    // Connection status
    isConnected: status.isConnected,
    isExecuting: status.isExecuting,
    error: status.error,
    currentCommand: status.currentCommand,
    
    // Execution methods
    executeCode,
    cancelExecution,
    
    // Output management
    output: outputBuffer,
    clearOutput,
    executionHistory,
    
    // Connection management
    connect,
    disconnect,
    
    // Raw socket for advanced usage
    socket
  }
}