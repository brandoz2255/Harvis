"use client"

import { useState } from "react"
import { Play, Loader2, AlertCircle } from "lucide-react"
import { runnableReason, extOf } from "../lib/run-capabilities"

interface RunButtonProps {
  filePath: string
  sessionId: string | null
  capabilities: Record<string, boolean>
  onRun?: (result: any) => void
  className?: string
}

export default function RunButton({ 
  filePath, 
  sessionId, 
  capabilities, 
  onRun,
  className = "" 
}: RunButtonProps) {
  const [isRunning, setIsRunning] = useState(false)
  const [lastResult, setLastResult] = useState<any>(null)

  const { runnable, reason } = runnableReason(filePath, capabilities)
  
  if (!runnable) {
    // Don't show anything for non-runnable files (FileActions will handle them)
    // Only show message for files that need a runtime
    if (reason === "Requires Node runtime") {
      return (
        <div 
          className={`flex items-center gap-2 text-sm text-gray-400 ${className}`}
          title="Install Node.js in the runner container to execute JavaScript files"
        >
          <AlertCircle size={14} />
          <span>{reason}</span>
        </div>
      )
    }
    return null
  }

  async function handleRun() {
    if (!sessionId || isRunning) return
    
    setIsRunning(true)
    try {
      const response = await fetch("/api/vibecode/exec", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          file: filePath.replace(/^\/workspace\//, ""), // Convert to relative path
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const result = await response.json()
      setLastResult(result)
      onRun?.(result)
    } catch (error) {
      console.error("Run failed:", error)
      setLastResult({
        stdout: "",
        stderr: `Run failed: ${error}`,
        exit_code: 1
      })
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <button
        onClick={handleRun}
        disabled={isRunning || !sessionId}
        className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:opacity-50 text-white text-sm rounded transition-colors"
      >
        {isRunning ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Play size={14} />
        )}
        {isRunning ? "Running..." : "Run"}
      </button>
      
      {lastResult && (
        <div className="text-xs text-gray-400">
          Exit: {lastResult.exit_code}
        </div>
      )}
    </div>
  )
}
