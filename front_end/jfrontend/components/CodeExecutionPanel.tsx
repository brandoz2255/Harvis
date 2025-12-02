"use client"

import React, { useRef, useEffect } from "react"
import { motion } from "framer-motion"
import { Play, Loader2, Terminal, CheckCircle, XCircle, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface ExecutionResult {
  command: string
  stdout: string
  stderr: string
  exit_code: number
  started_at: number
  finished_at: number
  execution_time_ms: number
}

interface CodeExecutionPanelProps {
  sessionId: string | null
  isContainerRunning: boolean
  executionHistory: ExecutionResult[]
  onExecute: (command: string) => Promise<void>
  isExecuting: boolean
  className?: string
}

const CodeExecutionPanel: React.FC<CodeExecutionPanelProps> = ({
  sessionId,
  isContainerRunning,
  executionHistory,
  onExecute,
  isExecuting,
  className = ""
}) => {
  const [input, setInput] = React.useState("")
  const executionEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new execution results arrive
  useEffect(() => {
    executionEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [executionHistory])

  const handleExecute = async () => {
    if (!input.trim() || !sessionId || !isContainerRunning || isExecuting) return
    
    await onExecute(input)
    setInput("") // Clear input after successful execution
  }

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !isExecuting) {
      handleExecute()
    }
  }

  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString()
  }

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(2)}s`
  }

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Execution History */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {executionHistory.length === 0 ? (
          <div className="h-full flex items-center justify-center text-center">
            <div>
              <Terminal className="w-12 h-12 text-gray-600 mx-auto mb-4" />
              <p className="text-gray-400 text-sm">No executions yet</p>
              <p className="text-gray-500 text-xs mt-2">
                Enter a command below to execute code
              </p>
            </div>
          </div>
        ) : (
          <>
            {executionHistory.map((result, idx) => (
              <ExecutionResultCard key={idx} result={result} />
            ))}
            <div ref={executionEndRef} />
          </>
        )}
      </div>

      {/* Command Input Area */}
      <div className="p-4 border-t border-gray-700 flex-shrink-0">
        {!sessionId || !isContainerRunning ? (
          <div className="text-center py-4">
            <p className="text-gray-500 text-sm">
              {!sessionId 
                ? "Select a session to execute commands" 
                : "Start the container to execute commands"}
            </p>
          </div>
        ) : (
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Enter command to execute (e.g., python script.py)..."
              disabled={isExecuting}
              className="flex-1 bg-gray-800 border-gray-600 text-gray-200 placeholder:text-gray-500 focus:border-purple-500"
            />
            <Button
              onClick={handleExecute}
              disabled={!input.trim() || isExecuting}
              className="bg-purple-600 hover:bg-purple-700 text-white"
            >
              {isExecuting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Running
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-2" />
                  Execute
                </>
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

// Execution Result Card Component
const ExecutionResultCard: React.FC<{ result: ExecutionResult }> = ({ result }) => {
  const hasOutput = result.stdout || result.stderr
  const isSuccess = result.exit_code === 0

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
    >
      <Card className="bg-gray-800/50 border-gray-700 p-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            {isSuccess ? (
              <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            )}
            <code className="text-sm text-gray-300 font-mono truncate">
              {result.command}
            </code>
          </div>
          <Badge
            variant="outline"
            className={`ml-2 flex-shrink-0 ${
              isSuccess
                ? 'border-green-500 text-green-400'
                : 'border-red-500 text-red-400'
            }`}
          >
            Exit {result.exit_code}
          </Badge>
        </div>

        {/* Metadata */}
        <div className="flex items-center gap-4 text-xs text-gray-500 mb-3">
          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {formatTimestamp(result.started_at)}
          </div>
          <div>
            Duration: {formatDuration(result.execution_time_ms)}
          </div>
        </div>

        {/* Output */}
        {hasOutput ? (
          <div className="space-y-2">
            {result.stdout && (
              <div>
                <div className="text-xs text-gray-500 mb-1">STDOUT:</div>
                <pre className="bg-gray-900 border border-gray-700 rounded p-3 text-sm text-green-400 font-mono overflow-x-auto whitespace-pre-wrap break-words">
                  {result.stdout}
                </pre>
              </div>
            )}
            {result.stderr && (
              <div>
                <div className="text-xs text-gray-500 mb-1">STDERR:</div>
                <pre className="bg-gray-900 border border-red-900/50 rounded p-3 text-sm text-red-400 font-mono overflow-x-auto whitespace-pre-wrap break-words">
                  {result.stderr}
                </pre>
              </div>
            )}
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-700 rounded p-3">
            <p className="text-sm text-gray-500 italic">(no output)</p>
          </div>
        )}
      </Card>
    </motion.div>
  )
}

// Helper function to format timestamp
function formatTimestamp(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString()
}

// Helper function to format duration
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export default CodeExecutionPanel
