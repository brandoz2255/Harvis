"use client"

import { useState } from "react"
import { CheckCircle2, AlertCircle, FileJson, FileCode } from "lucide-react"
import { extOf } from "../lib/run-capabilities"

interface FileActionsProps {
  filePath: string
  sessionId: string | null
  className?: string
}

export default function FileActions({ 
  filePath, 
  sessionId,
  className = "" 
}: FileActionsProps) {
  const [status, setStatus] = useState<{ type: 'success' | 'error', message: string } | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const ext = extOf(filePath)

  const fetchFileContent = async (): Promise<string> => {
    if (!sessionId || !filePath) {
      throw new Error("Session or file path not available")
    }
    
    const relativePath = filePath.replace(/^\/workspace\//, "")
    const response = await fetch(`/api/vibecode/files/read?session_id=${sessionId}&path=${encodeURIComponent(relativePath)}`, {
      headers: { 
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    })
    
    if (!response.ok) {
      throw new Error(`Failed to read file: ${response.status}`)
    }
    
    const data = await response.json()
    return data.content || ""
  }

  const saveFileContent = async (content: string): Promise<void> => {
    if (!sessionId || !filePath) {
      throw new Error("Session or file path not available")
    }
    
    const relativePath = filePath.replace(/^\/workspace\//, "")
    const response = await fetch(`/api/vibecode/files/save`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify({
        session_id: sessionId,
        path: relativePath,
        content: content
      })
    })
    
    if (!response.ok) {
      throw new Error(`Failed to save file: ${response.status}`)
    }
  }

  const handleFormatJSON = async () => {
    setIsLoading(true)
    try {
      const content = await fetchFileContent()
      const parsed = JSON.parse(content)
      const formatted = JSON.stringify(parsed, null, 2)
      await saveFileContent(formatted)
      setStatus({ type: 'success', message: 'JSON formatted successfully' })
      setTimeout(() => setStatus(null), 3000)
      
      // Trigger a reload of the file in the editor
      window.dispatchEvent(new CustomEvent('file-updated', { detail: { path: filePath } }))
    } catch (error: any) {
      setStatus({ type: 'error', message: `Format failed: ${error.message}` })
      setTimeout(() => setStatus(null), 5000)
    } finally {
      setIsLoading(false)
    }
  }

  const handleValidateJSON = async () => {
    setIsLoading(true)
    try {
      const content = await fetchFileContent()
      JSON.parse(content)
      setStatus({ type: 'success', message: 'JSON is valid ✓' })
      setTimeout(() => setStatus(null), 3000)
    } catch (error: any) {
      setStatus({ type: 'error', message: `Invalid JSON: ${error.message}` })
      setTimeout(() => setStatus(null), 5000)
    } finally {
      setIsLoading(false)
    }
  }

  const handleFormatYAML = async () => {
    setStatus({ type: 'success', message: 'YAML formatting not yet implemented' })
    setTimeout(() => setStatus(null), 3000)
  }

  const handleValidateYAML = async () => {
    setStatus({ type: 'success', message: 'YAML validation not yet implemented' })
    setTimeout(() => setStatus(null), 3000)
  }

  const handleCopyPath = () => {
    navigator.clipboard.writeText(filePath)
    setStatus({ type: 'success', message: 'Path copied to clipboard' })
    setTimeout(() => setStatus(null), 2000)
  }

  if (ext === 'json') {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <button
          onClick={handleValidateJSON}
          disabled={isLoading}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded transition-colors"
        >
          <CheckCircle2 size={14} />
          {isLoading ? 'Validating...' : 'Validate'}
        </button>
        
        <button
          onClick={handleFormatJSON}
          disabled={isLoading}
          className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded transition-colors"
        >
          <FileJson size={14} />
          {isLoading ? 'Formatting...' : 'Format'}
        </button>

        {status && (
          <div className={`text-xs px-2 py-1 rounded ${
            status.type === 'success' 
              ? 'bg-green-600 text-white' 
              : 'bg-red-600 text-white'
          }`}>
            {status.message}
          </div>
        )}
      </div>
    )
  }

  if (ext === 'yaml' || ext === 'yml') {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <button
          onClick={handleValidateYAML}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
        >
          <CheckCircle2 size={14} />
          Validate
        </button>
        
        <button
          onClick={handleFormatYAML}
          className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded transition-colors"
        >
          <FileCode size={14} />
          Format
        </button>

        {status && (
          <div className={`text-xs px-2 py-1 rounded ${
            status.type === 'success' 
              ? 'bg-green-600 text-white' 
              : 'bg-red-600 text-white'
          }`}>
            {status.message}
          </div>
        )}
      </div>
    )
  }

  // For other non-runnable files, just show copy path
  const nonRunnable = ["toml", "ini", "md", "txt", "csv", "tsv", 
                        "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", 
                        "mp3", "mp4", "pdf", "zip", "exe", "dll", "so", "ipynb"]
  
  if (nonRunnable.includes(ext)) {
    return (
      <div className={`flex items-center gap-2 text-sm text-gray-400 ${className}`}>
        <AlertCircle size={14} />
        <span>Non-executable file type</span>
        <button
          onClick={handleCopyPath}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
        >
          Copy path
        </button>
        {status && (
          <div className="text-xs px-2 py-1 rounded bg-green-600 text-white">
            {status.message}
          </div>
        )}
      </div>
    )
  }

  return null
}
