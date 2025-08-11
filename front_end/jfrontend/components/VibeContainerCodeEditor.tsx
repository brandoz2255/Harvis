"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import {
  Save,
  Play,
  Code,
  FileText,
  Loader2,
  CheckCircle,
  AlertCircle,
  Download,
  Copy,
  Maximize2,
  Minimize2
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface ContainerFile {
  name: string
  type: 'file' | 'directory'
  size: number
  permissions: string
  path: string
}

interface VibeContainerCodeEditorProps {
  sessionId: string | null
  selectedFile: ContainerFile | null
  onExecute?: (filePath: string) => void
  className?: string
}

export default function VibeContainerCodeEditor({
  sessionId,
  selectedFile,
  onExecute,
  className = ""
}: VibeContainerCodeEditorProps) {
  const [content, setContent] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [lastSaved, setLastSaved] = useState<Date | null>(null)
  const [isModified, setIsModified] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'error' | null>(null)
  
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load file content when selected file changes
  useEffect(() => {
    if (selectedFile && sessionId) {
      loadFileContent()
    } else {
      setContent('')
      setIsModified(false)
    }
  }, [selectedFile, sessionId])

  const loadFileContent = async () => {
    if (!selectedFile || !sessionId || selectedFile.type !== 'file') return

    try {
      setIsLoading(true)
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          action: 'read',
          file_path: selectedFile.path
        })
      })

      if (response.ok) {
        const data = await response.json()
        setContent(data.content || '')
        setIsModified(false)
        setLastSaved(new Date())
      } else {
        console.error('Failed to load file content')
        setContent('// Failed to load file content')
      }
    } catch (error) {
      console.error('Error loading file:', error)
      setContent('// Error loading file')
    } finally {
      setIsLoading(false)
    }
  }

  const saveFile = async () => {
    if (!selectedFile || !sessionId || !isModified) return

    try {
      setIsSaving(true)
      setSaveStatus('saving')
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/vibecoding/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          action: 'write',
          file_path: selectedFile.path,
          content
        })
      })

      if (response.ok) {
        setIsModified(false)
        setLastSaved(new Date())
        setSaveStatus('saved')
        
        // Clear save status after 2 seconds
        setTimeout(() => setSaveStatus(null), 2000)
      } else {
        setSaveStatus('error')
        setTimeout(() => setSaveStatus(null), 3000)
      }
    } catch (error) {
      console.error('Error saving file:', error)
      setSaveStatus('error')
      setTimeout(() => setSaveStatus(null), 3000)
    } finally {
      setIsSaving(false)
    }
  }

  const executeFile = async () => {
    if (!selectedFile || !sessionId) return

    try {
      setIsExecuting(true)
      
      // Save file first if modified
      if (isModified) {
        await saveFile()
      }

      if (onExecute) {
        onExecute(selectedFile.path)
      }

      // Alternative: execute via API
      const token = localStorage.getItem('token')
      if (token) {
        const response = await fetch('/api/vibecoding/files', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            session_id: sessionId,
            action: 'execute',
            command: getExecuteCommand(selectedFile.name, selectedFile.path)
          })
        })

        if (response.ok) {
          const data = await response.json()
          console.log('Execution result:', data)
        }
      }
    } catch (error) {
      console.error('Error executing file:', error)
    } finally {
      setIsExecuting(false)
    }
  }

  const getExecuteCommand = (fileName: string, filePath: string) => {
    const extension = fileName.split('.').pop()?.toLowerCase()
    
    switch (extension) {
      case 'py':
        return `python ${filePath}`
      case 'js':
        return `node ${filePath}`
      case 'ts':
        return `npx ts-node ${filePath}`
      case 'java':
        return `javac ${filePath} && java ${fileName.replace('.java', '')}`
      case 'cpp':
        return `g++ ${filePath} -o /tmp/output && /tmp/output`
      case 'c':
        return `gcc ${filePath} -o /tmp/output && /tmp/output`
      case 'go':
        return `go run ${filePath}`
      case 'rs':
        return `rustc ${filePath} -o /tmp/output && /tmp/output`
      case 'sh':
        return `bash ${filePath}`
      default:
        return `cat ${filePath}`
    }
  }

  const getLanguageFromFileName = (fileName: string) => {
    const extension = fileName.split('.').pop()?.toLowerCase()
    
    const languageMap: { [key: string]: string } = {
      'py': 'python',
      'js': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'jsx': 'javascript',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'go': 'go',
      'rs': 'rust',
      'php': 'php',
      'rb': 'ruby',
      'html': 'html',
      'css': 'css',
      'json': 'json',
      'md': 'markdown',
      'yaml': 'yaml',
      'yml': 'yaml',
      'sh': 'bash',
      'sql': 'sql'
    }
    
    return languageMap[extension || ''] || 'text'
  }

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value)
    setIsModified(true)
    setSaveStatus(null)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+S to save
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault()
      saveFile()
    }
    
    // Ctrl+Enter to execute
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault()
      executeFile()
    }
    
    // Tab handling
    if (e.key === 'Tab') {
      e.preventDefault()
      const start = e.currentTarget.selectionStart
      const end = e.currentTarget.selectionEnd
      
      const newContent = content.substring(0, start) + '  ' + content.substring(end)
      setContent(newContent)
      setIsModified(true)
      
      // Set cursor position after tab
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.selectionStart = textareaRef.current.selectionEnd = start + 2
        }
      }, 0)
    }
  }

  const copyContent = () => {
    navigator.clipboard.writeText(content)
  }

  const downloadFile = () => {
    if (!selectedFile) return
    
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = selectedFile.name
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const canExecute = selectedFile && ['py', 'js', 'ts', 'java', 'cpp', 'c', 'go', 'rs', 'sh'].includes(
    selectedFile.name.split('.').pop()?.toLowerCase() || ''
  )

  return (
    <Card className={`bg-gray-900/50 backdrop-blur-sm border-green-500/30 flex flex-col ${
      isFullscreen ? 'fixed inset-0 z-50' : className
    }`}>
      {/* Header */}
      <div className="p-4 border-b border-green-500/30 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Code className="w-5 h-5 text-green-400" />
            {selectedFile ? (
              <div className="flex items-center space-x-2">
                <h3 className="text-lg font-semibold text-green-300">
                  {selectedFile.name}
                </h3>
                <Badge variant="outline" className="border-green-500 text-green-400 text-xs">
                  {getLanguageFromFileName(selectedFile.name)}
                </Badge>
                {isModified && (
                  <Badge variant="outline" className="border-yellow-500 text-yellow-400 text-xs">
                    Modified
                  </Badge>
                )}
              </div>
            ) : (
              <h3 className="text-lg font-semibold text-gray-400">No file selected</h3>
            )}
          </div>
          
          <div className="flex items-center space-x-2">
            {saveStatus && (
              <div className="flex items-center space-x-1">
                {saveStatus === 'saving' && <Loader2 className="w-3 h-3 animate-spin text-blue-400" />}
                {saveStatus === 'saved' && <CheckCircle className="w-3 h-3 text-green-400" />}
                {saveStatus === 'error' && <AlertCircle className="w-3 h-3 text-red-400" />}
                <span className={`text-xs ${
                  saveStatus === 'saving' ? 'text-blue-400' :
                  saveStatus === 'saved' ? 'text-green-400' : 'text-red-400'
                }`}>
                  {saveStatus === 'saving' ? 'Saving...' :
                   saveStatus === 'saved' ? 'Saved' : 'Save failed'}
                </span>
              </div>
            )}
            
            {lastSaved && !isModified && (
              <span className="text-xs text-gray-500">
                Saved {lastSaved.toLocaleTimeString()}
              </span>
            )}
            
            <Button
              onClick={copyContent}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
              disabled={!selectedFile || isLoading}
            >
              <Copy className="w-3 h-3" />
            </Button>
            
            <Button
              onClick={downloadFile}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
              disabled={!selectedFile || isLoading}
            >
              <Download className="w-3 h-3" />
            </Button>
            
            <Button
              onClick={() => setIsFullscreen(!isFullscreen)}
              size="sm"
              variant="outline"
              className="bg-gray-800 border-gray-600 text-gray-300"
            >
              {isFullscreen ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
            </Button>
            
            <Button
              onClick={saveFile}
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white"
              disabled={!selectedFile || !isModified || isSaving}
            >
              {isSaving ? (
                <Loader2 className="w-3 h-3 animate-spin mr-1" />
              ) : (
                <Save className="w-3 h-3 mr-1" />
              )}
              Save
            </Button>
            
            {canExecute && (
              <Button
                onClick={executeFile}
                size="sm"
                className="bg-purple-600 hover:bg-purple-700 text-white"
                disabled={!selectedFile || isExecuting}
              >
                {isExecuting ? (
                  <Loader2 className="w-3 h-3 animate-spin mr-1" />
                ) : (
                  <Play className="w-3 h-3 mr-1" />
                )}
                Run
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col min-h-0">
        {!selectedFile ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <FileText className="w-16 h-16 text-gray-600 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-400 mb-2">No File Selected</h3>
              <p className="text-gray-500">Select a file from the explorer to start editing</p>
            </div>
          </div>
        ) : isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <Loader2 className="w-8 h-8 animate-spin text-green-400 mx-auto mb-4" />
              <p className="text-gray-400">Loading file content...</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={content}
              onChange={handleContentChange}
              onKeyDown={handleKeyDown}
              className="w-full h-full bg-gray-950 text-green-300 font-mono text-sm p-4 border-none outline-none resize-none"
              placeholder="Start typing your code..."
              spellCheck={false}
              style={{
                lineHeight: '1.6',
                tabSize: 2
              }}
            />
            
            {/* Line numbers overlay - simplified */}
            <div className="absolute left-0 top-0 p-4 pointer-events-none select-none">
              <div className="font-mono text-sm text-gray-600 leading-6">
                {content.split('\n').map((_, index) => (
                  <div key={index} className="text-right pr-3" style={{ minWidth: '2rem' }}>
                    {index + 1}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer with keyboard shortcuts */}
      {selectedFile && (
        <div className="px-4 py-2 border-t border-green-500/30 bg-gray-900/50 text-xs text-gray-500 flex justify-between items-center">
          <div className="flex space-x-4">
            <span>Ctrl+S: Save</span>
            {canExecute && <span>Ctrl+Enter: Run</span>}
            <span>Tab: Indent</span>
          </div>
          <div className="flex items-center space-x-2">
            <span>{content.split('\n').length} lines</span>
            <span>{content.length} characters</span>
          </div>
        </div>
      )}
    </Card>
  )
}