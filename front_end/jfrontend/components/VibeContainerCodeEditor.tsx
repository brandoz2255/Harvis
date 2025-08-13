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
  Minimize2,
  Settings,
  Palette
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import Editor from "@monaco-editor/react"
import { configureMonacoLanguages, setupLSPFeatures } from '@/lib/monaco-config'

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
  const [editorTheme, setEditorTheme] = useState<'vibe-dark' | 'vibe-light' | 'github-dark' | 'github-light' | 'vs-dark' | 'light' | 'monokai' | 'dracula'>('vibe-dark')
  const [fontSize, setFontSize] = useState(14)
  const [wordWrap, setWordWrap] = useState<'on' | 'off'>('off')
  
  const editorRef = useRef<any>(null)
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

  // Update Monaco editor options when settings change
  useEffect(() => {
    if (editorRef.current) {
      editorRef.current.updateOptions({
        fontSize: fontSize,
        wordWrap: wordWrap,
        minimap: { enabled: fontSize >= 14, scale: fontSize >= 16 ? 0.7 : 0.5 }
      })
    }
  }, [fontSize, wordWrap])

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

  // Enhanced Monaco editor theme definitions (same as VibeCodeEditor)
  const defineCustomThemes = (monaco: any) => {
    // Vibe Dark Theme (Enhanced)
    monaco.editor.defineTheme('vibe-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '6A737D', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'F97583' },
        { token: 'string', foreground: '9ECBFF' },
        { token: 'number', foreground: 'B392F0' },
        { token: 'type', foreground: 'FFD700' },
        { token: 'function', foreground: 'E1E4E8' },
        { token: 'variable', foreground: 'F0F6FC' },
        { token: 'operator', foreground: 'F97583' },
        { token: 'delimiter', foreground: 'E1E4E8' },
        { token: 'class', foreground: 'FFAB70' },
        { token: 'interface', foreground: 'FFB86C' },
        { token: 'namespace', foreground: 'FF79C6' }
      ],
      colors: {
        'editor.background': '#0D1117',
        'editor.foreground': '#F0F6FC',
        'editorLineNumber.foreground': '#6E7681',
        'editorCursor.foreground': '#7C3AED',
        'editor.selectionBackground': '#7C3AED33',
        'editor.inactiveSelectionBackground': '#7C3AED22',
        'editorLineNumber.activeForeground': '#B392F0',
        'editor.lineHighlightBackground': '#21262D',
        'editorGutter.background': '#0D1117',
        'editorWhitespace.foreground': '#6E768166',
        'editorIndentGuide.background': '#21262D',
        'editorIndentGuide.activeBackground': '#7C3AED',
        'editor.findMatchBackground': '#FFD70033',
        'editor.findMatchHighlightBackground': '#FFD70022',
        'editorBracketMatch.background': '#7C3AED33',
        'editorBracketMatch.border': '#7C3AED',
        'editorSuggestWidget.background': '#161B22',
        'editorSuggestWidget.border': '#30363D',
        'editorSuggestWidget.foreground': '#F0F6FC',
        'editorSuggestWidget.selectedBackground': '#7C3AED33',
        'editorHoverWidget.background': '#161B22',
        'editorHoverWidget.border': '#30363D'
      }
    })

    // Vibe Light Theme
    monaco.editor.defineTheme('vibe-light', {
      base: 'vs',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '6A737D', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'D73A49' },
        { token: 'string', foreground: '032F62' },
        { token: 'number', foreground: '005CC5' },
        { token: 'type', foreground: 'B31D28' },
        { token: 'function', foreground: '6F42C1' },
        { token: 'variable', foreground: '24292E' },
        { token: 'operator', foreground: 'D73A49' },
        { token: 'delimiter', foreground: '24292E' }
      ],
      colors: {
        'editor.background': '#FFFFFF',
        'editor.foreground': '#24292E',
        'editorLineNumber.foreground': '#959DA5',
        'editorCursor.foreground': '#7C3AED',
        'editor.selectionBackground': '#7C3AED33',
        'editor.lineHighlightBackground': '#F6F8FA',
        'editorGutter.background': '#FFFFFF'
      }
    })

    // GitHub Dark Theme
    monaco.editor.defineTheme('github-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '8B949E', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'FF7B72' },
        { token: 'string', foreground: 'A5D6FF' },
        { token: 'number', foreground: '79C0FF' },
        { token: 'type', foreground: 'FFA657' },
        { token: 'function', foreground: 'D2A8FF' },
        { token: 'variable', foreground: 'FFA657' }
      ],
      colors: {
        'editor.background': '#0D1117',
        'editor.foreground': '#F0F6FC',
        'editorLineNumber.foreground': '#7D8590',
        'editor.lineHighlightBackground': '#161B22'
      }
    })

    // Dracula Theme
    monaco.editor.defineTheme('dracula', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '6272A4', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'FF79C6' },
        { token: 'string', foreground: 'F1FA8C' },
        { token: 'number', foreground: 'BD93F9' },
        { token: 'type', foreground: '8BE9FD' },
        { token: 'function', foreground: '50FA7B' },
        { token: 'variable', foreground: 'F8F8F2' }
      ],
      colors: {
        'editor.background': '#282A36',
        'editor.foreground': '#F8F8F2',
        'editorLineNumber.foreground': '#6272A4',
        'editor.lineHighlightBackground': '#44475A'
      }
    })

    // Monokai Theme
    monaco.editor.defineTheme('monokai', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'comment', foreground: '75715E', fontStyle: 'italic' },
        { token: 'keyword', foreground: 'F92672' },
        { token: 'string', foreground: 'E6DB74' },
        { token: 'number', foreground: 'AE81FF' },
        { token: 'type', foreground: '66D9EF' },
        { token: 'function', foreground: 'A6E22E' },
        { token: 'variable', foreground: 'F8F8F2' }
      ],
      colors: {
        'editor.background': '#272822',
        'editor.foreground': '#F8F8F2',
        'editorLineNumber.foreground': '#90908A',
        'editor.lineHighlightBackground': '#3E3D32'
      }
    })
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
      'sql': 'sql',
      'dockerfile': 'dockerfile',
      'Dockerfile': 'dockerfile',
      'vue': 'vue',
      'svelte': 'svelte'
    }
    
    return languageMap[extension || ''] || 'plaintext'
  }

  const handleEditorDidMount = (editor: any, monaco: any) => {
    editorRef.current = editor
    
    // Define custom themes (same as VibeCodeEditor)
    defineCustomThemes(monaco)
    
    // Configure language features
    configureMonacoLanguages(monaco)
    
    // Setup LSP features for current language
    if (selectedFile) {
      const language = getLanguageFromFileName(selectedFile.name)
      setupLSPFeatures(monaco, language)
    }
    
    // Configure editor
    editor.updateOptions({
      fontSize: fontSize,
      wordWrap: wordWrap,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      automaticLayout: true,
      tabSize: 2,
      insertSpaces: true,
      renderWhitespace: 'selection',
      lineNumbers: 'on',
      cursorStyle: 'line',
      smoothScrolling: true,
      contextmenu: true,
      mouseWheelZoom: true
    })

    // Add keyboard shortcuts
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      saveFile()
    })

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      executeFile()
    })

    // Auto-save on focus loss
    editor.onDidBlurEditorText(() => {
      if (isModified) {
        saveFile()
      }
    })
  }

  const handleEditorChange = (value: string | undefined) => {
    if (value !== undefined) {
      setContent(value)
      setIsModified(true)
      setSaveStatus(null)
    }
  }

  // Legacy textarea handlers - removed in favor of Monaco Editor

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
            
            {/* Theme Controls */}
            <div className="flex items-center space-x-1 border-l border-gray-600 pl-2">
              <Button
                onClick={() => {
                  const themes: typeof editorTheme[] = ['vibe-dark', 'vibe-light', 'github-dark', 'dracula', 'monokai', 'vs-dark', 'light']
                  const currentIndex = themes.indexOf(editorTheme)
                  const nextTheme = themes[(currentIndex + 1) % themes.length]
                  setEditorTheme(nextTheme)
                }}
                size="sm"
                variant="ghost"
                className="h-8 px-2 text-gray-400 hover:text-white"
                title={`Current: ${editorTheme} (click to cycle)`}
              >
                <Palette className="w-3 h-3" />
              </Button>
              
              <Button
                onClick={() => setFontSize(fontSize === 14 ? 16 : fontSize === 16 ? 12 : 14)}
                size="sm"
                variant="ghost"
                className="h-8 px-2 text-gray-400 hover:text-white text-xs"
                title="Font Size"
              >
                {fontSize}px
              </Button>
            </div>
            
            <div className="flex items-center space-x-1 border-l border-gray-600 pl-2">
              <Button
                onClick={copyContent}
                size="sm"
                variant="outline"
                className="bg-gray-800 border-gray-600 text-gray-300"
                disabled={!selectedFile || isLoading}
                title="Copy Content"
              >
                <Copy className="w-3 h-3" />
              </Button>
              
              <Button
                onClick={downloadFile}
                size="sm"
                variant="outline"
                className="bg-gray-800 border-gray-600 text-gray-300"
                disabled={!selectedFile || isLoading}
                title="Download File"
              >
                <Download className="w-3 h-3" />
              </Button>
              
              <Button
                onClick={() => setIsFullscreen(!isFullscreen)}
                size="sm"
                variant="outline"
                className="bg-gray-800 border-gray-600 text-gray-300"
                title="Toggle Fullscreen"
              >
                {isFullscreen ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
              </Button>
            </div>
            
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
          <div className="flex-1 bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
            <Editor
              height="100%"
              language={getLanguageFromFileName(selectedFile.name)}
              value={content}
              onChange={handleEditorChange}
              onMount={handleEditorDidMount}
              theme={editorTheme}
              options={{
                fontSize: fontSize,
                wordWrap: wordWrap,
                minimap: { enabled: true, scale: 0.5 },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                insertSpaces: true,
                renderWhitespace: 'selection',
                lineNumbers: 'on',
                cursorStyle: 'line',
                smoothScrolling: true,
                contextmenu: true,
                mouseWheelZoom: true,
                bracketPairColorization: { enabled: true },
                autoIndent: 'full',
                formatOnPaste: true,
                formatOnType: true,
                suggestOnTriggerCharacters: true,
                acceptSuggestionOnCommitCharacter: true,
                acceptSuggestionOnEnter: 'on',
                quickSuggestions: {
                  other: true,
                  comments: true,
                  strings: true
                },
                parameterHints: { 
                  enabled: true,
                  cycle: true 
                },
                codeLens: true,
                folding: true,
                foldingStrategy: 'auto',
                showFoldingControls: 'mouseover',
                unfoldOnClickAfterEndOfLine: true,
                disableLayerHinting: false,
                renderLineHighlight: 'all',
                suggest: {
                  showKeywords: true,
                  showSnippets: true,
                  showFunctions: true,
                  showVariables: true,
                  showClasses: true,
                  showStructs: true,
                  showInterfaces: true,
                  showModules: true,
                  showProperties: true,
                  showEvents: true,
                  showOperators: true,
                  showUnits: true,
                  showValues: true,
                  showConstants: true,
                  showEnums: true,
                  showEnumMembers: true,
                  showColors: true,
                  showFiles: true,
                  showReferences: true,
                  showFolders: true,
                  showTypeParameters: true,
                  filterGraceful: true,
                  snippetsPreventQuickSuggestions: false
                },
                autoClosingBrackets: 'always',
                autoClosingQuotes: 'always'
              }}
              loading={
                <div className="flex items-center justify-center h-full bg-gray-950">
                  <div className="text-center">
                    <Loader2 className="w-8 h-8 animate-spin text-blue-400 mx-auto mb-4" />
                    <p className="text-gray-400">Loading Monaco Editor...</p>
                  </div>
                </div>
              }
            />
          </div>
        )}
      </div>

      {/* Footer with keyboard shortcuts and file info */}
      {selectedFile && (
        <div className="px-4 py-2 border-t border-gray-700 bg-gray-900 text-xs text-gray-400 flex justify-between items-center">
          <div className="flex space-x-4">
            <span>Ctrl+S: Save</span>
            {canExecute && <span>Ctrl+Enter: Run</span>}
            <span>Ctrl+/: Comment</span>
            <span>Alt+Shift+F: Format</span>
            <span>Ctrl+D: Multi-cursor</span>
          </div>
          <div className="flex items-center space-x-4">
            <span className="flex items-center space-x-2">
              <Badge variant="outline" className="border-gray-600 text-gray-400 text-xs">
                {getLanguageFromFileName(selectedFile.name)}
              </Badge>
              <span>{content.split('\n').length} lines</span>
              <span>{content.length} chars</span>
            </span>
            <span className="text-blue-400">
              {editorTheme === 'vs-dark' ? 'Dark' : editorTheme === 'light' ? 'Light' : 'High Contrast'} • {fontSize}px
            </span>
          </div>
        </div>
      )}
    </Card>
  )
}