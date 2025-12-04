"use client"

import React, { useState, useEffect, useRef, useCallback } from "react"
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
  Sun,
  Moon,
  Palette
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import Editor from "@monaco-editor/react"
import { toWorkspaceRelativePath } from '@/lib/strings'
import { configureMonacoLanguages, setupLSPFeatures } from '@/lib/monaco-config'

const COMMENT_PREFIXES = ['#', '//', '/*', '--', '<!--']
const KEYWORD_TRIGGER_REGEX = /\b(def|class|if|for|while|try|except|with|function|return|const|let|var|async|await|switch|case|struct|impl)\b[^\n]*$/i
const TRIGGER_CHARS = ['.', ':', '=', '(', '{', '[']

interface ContainerFile {
  name: string
  type: 'file' | 'directory'
  size: number
  permissions: string
  path: string
}

interface NeighborFileSnippet {
  path: string
  content: string
}

interface VibeContainerCodeEditorProps {
  sessionId: string | null
  selectedFile: ContainerFile | null
  onExecute?: (filePath: string) => void
  onCursorPositionChange?: (position: { line: number; column: number }) => void
  className?: string
  // Expose Monaco editor instance to parent (for copilot/insert-at-cursor)
  onEditorMount?: (editor: any) => void
  neighborFiles?: NeighborFileSnippet[]
  copilotEnabled?: boolean
}

export default function VibeContainerCodeEditor({
  sessionId,
  selectedFile,
  onExecute,
  onCursorPositionChange,
  className = "",
  onEditorMount,
  neighborFiles = [],
  copilotEnabled = true
}: VibeContainerCodeEditorProps) {
  const [content, setContent] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [lastSaved, setLastSaved] = useState<Date | null>(null)
  const [isModified, setIsModified] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isLoadingFile, setIsLoadingFile] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'error' | null>(null)
  const [editorTheme, setEditorTheme] = useState<'vibe-dark' | 'vibe-light' | 'github-dark' | 'github-light' | 'vs-dark' | 'light' | 'monokai' | 'dracula'>('vibe-dark')
  const [wordWrap, setWordWrap] = useState<'on' | 'off'>('off')

  // Get font size from CSS variable (set by user preferences)
  const [fontSize, setFontSize] = useState(() => {
    if (typeof window !== 'undefined') {
      const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--vibe-font-size')
      return cssVar ? parseInt(cssVar) : 14
    }
    return 14
  })

  const editorRef = useRef<any>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Use ref to track last call time to prevent debounce issues
  const lastCallRef = useRef<number>(0)
  const sessionIdRef = useRef(sessionId)
  const selectedFileRef = useRef<ContainerFile | null>(selectedFile)
  const neighborFilesRef = useRef<NeighborFileSnippet[]>([])
  const copilotEnabledRef = useRef<boolean>(copilotEnabled)
  const inlineAbortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    selectedFileRef.current = selectedFile
  }, [selectedFile])

  useEffect(() => {
    neighborFilesRef.current = (neighborFiles || [])
      .slice(0, 3)
      .map((file) => ({
        path: file.path,
        content: (file.content || '').slice(0, 4000)
      }))
  }, [neighborFiles])

  useEffect(() => {
    copilotEnabledRef.current = copilotEnabled
    if (editorRef.current) {
      editorRef.current.updateOptions({
        inlineSuggest: { enabled: copilotEnabled }
      })
    }
  }, [copilotEnabled])

  const shouldTriggerInline = useCallback((content: string, offset: number, languageId: string) => {
    if (!copilotEnabledRef.current) return false
    if (!content || !content.trim()) return false
    if (offset < 0 || offset > content.length) return false

    const prefix = content.slice(0, offset)
    const lineStart = prefix.lastIndexOf('\n') + 1
    const currentLine = prefix.slice(lineStart)
    const trimmedLine = currentLine.trim()

    if (!trimmedLine) {
      return true
    }

    const lowerLine = trimmedLine.toLowerCase()
    if (COMMENT_PREFIXES.some((token) => lowerLine.startsWith(token))) {
      return false
    }
    if (trimmedLine.startsWith('"""') || trimmedLine.startsWith("'''")) {
      return false
    }
    const quoteChar = trimmedLine[0]
    if ((quoteChar === '"' || quoteChar === "'" || quoteChar === '`') && trimmedLine.endsWith(quoteChar)) {
      return false
    }

    const lastChar = prefix.slice(-1)
    const prevTwo = prefix.slice(-2)

    if (TRIGGER_CHARS.includes(lastChar)) {
      return true
    }
    if (prevTwo === '::' || prevTwo === '->') {
      return true
    }
    if (trimmedLine.endsWith('.') || trimmedLine.endsWith(':') || trimmedLine.endsWith('=') || trimmedLine.endsWith('->')) {
      return true
    }
    if (/\(\s*$/.test(trimmedLine) || trimmedLine.endsWith(',')) {
      return true
    }
    if (KEYWORD_TRIGGER_REGEX.test(trimmedLine)) {
      return true
    }
    if (/=\s*$/.test(trimmedLine)) {
      return true
    }

    if (languageId === 'python' && trimmedLine.endsWith('\\')) {
      return true
    }

    return false
  }, [])

  // Define loadFileContent before using it in useEffect
  const loadFileContent = useCallback(async () => {
    if (!selectedFile || !sessionId || selectedFile.type !== 'file') return

    // Debounce file loading to prevent flickering
    const now = Date.now()
    if (lastCallRef.current && now - lastCallRef.current < 500) {
      console.log('⏳ Debouncing file load (too frequent)')
      return
    }
    lastCallRef.current = now

    // Don't load if already loading
    if (isLoading || isLoadingFile) {
      console.log('⏳ File already loading, skipping...')
      return
    }

    try {
      setIsLoading(true)
      setIsLoadingFile(true)
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('❌ No authentication token found')
        setContent('// Authentication required - please log in')
        return
      }

      const response = await fetch('/api/vibecode/files/read', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: selectedFile.path
        })
      })

      if (response.ok) {
        const data = await response.json()
        console.log(`📄 Loaded file ${selectedFile.path}: ${data.content?.length || 0} bytes`)
        setContent(data.content || '')
        setIsModified(false)
        setLastSaved(new Date())
      } else {
        const errorText = await response.text()
        console.error(`❌ Failed to load file content (${response.status}):`, errorText)

        if (response.status === 401) {
          console.error('❌ Authentication failed - token may be expired')
          setContent('// Authentication failed - please refresh the page')
          // Optionally redirect to login or refresh token
        } else {
          setContent('// Failed to load file content')
        }
      }
    } catch (error) {
      console.error('Error loading file:', error)
      setContent('// Error loading file')
    } finally {
      setIsLoading(false)
      setIsLoadingFile(false)
    }
  }, [selectedFile?.path, sessionId, isLoading, isLoadingFile])

  // Load file content when selected file changes
  useEffect(() => {
    if (selectedFile && sessionId) {
      loadFileContent()
    } else {
      setContent('')
      setIsModified(false)
    }
  }, [selectedFile?.path, sessionId, loadFileContent])

  // Watch for font size changes from CSS variable (user preferences)
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const cssVar = getComputedStyle(document.documentElement).getPropertyValue('--vibe-font-size')
      if (cssVar) {
        const newSize = parseInt(cssVar)
        if (newSize !== fontSize) {
          setFontSize(newSize)
        }
      }
    })

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style']
    })

    return () => observer.disconnect()
  }, [fontSize])

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

  const saveFile = useCallback(async () => {
    if (!selectedFile || !sessionId || !isModified) return

    // Throttle auto-save to prevent spam
    const now = Date.now()
    if (saveFile.lastCall && now - saveFile.lastCall < 2000) {
      console.log('⏳ Throttling auto-save (too frequent)')
      return
    }
    saveFile.lastCall = now

    try {
      setIsSaving(true)
      setSaveStatus('saving')
      const token = localStorage.getItem('token')
      if (!token) {
        console.error('❌ No authentication token found')
        return
      }

      const response = await fetch('/api/vibecode/files/save', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          path: toWorkspaceRelativePath(selectedFile.path),
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
        const errorText = await response.text()
        console.error(`❌ Save failed (${response.status}):`, errorText)

        if (response.status === 401) {
          console.error('❌ Authentication failed - token may be expired')
        } else if (response.status === 422) {
          console.error('❌ Validation error - check request format')
        }

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
  }, [selectedFile?.path, sessionId, isModified, content])

  // Debounced auto-save (500ms delay) - Task 11.2 requirement
  useEffect(() => {
    if (!isModified || !selectedFile || !sessionId || isSaving) return

    const timeoutId = setTimeout(() => {
      saveFile()
    }, 500)

    return () => clearTimeout(timeoutId)
  }, [isModified, selectedFile?.path, sessionId, isSaving, saveFile])

  const executeFile = useCallback(async () => {
    if (!selectedFile || !sessionId) return

    setIsExecuting(true)
    console.log('🚀 Executing file:', selectedFile.path)

    try {
      const command = getExecuteCommand(selectedFile.name, toWorkspaceRelativePath(selectedFile.path))
      console.log('📝 Execute command:', command)

      onExecute?.(selectedFile.path)
    } catch (error) {
      console.error('Error executing file:', error)
    } finally {
      setIsExecuting(false)
    }
  }, [selectedFile, sessionId, onExecute])

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
        'editorHoverWidget.border': '#30363D',
        'editorGhostText.foreground': '#8a8f98',
        'editorGhostText.border': '#00000000'
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
        'editorGutter.background': '#FFFFFF',
        'editorGhostText.foreground': '#8a8f98',
        'editorGhostText.border': '#00000000'
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
        'editor.lineHighlightBackground': '#161B22',
        'editorGhostText.foreground': '#8a8f98',
        'editorGhostText.border': '#00000000'
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
        'editor.lineHighlightBackground': '#44475A',
        'editorGhostText.foreground': '#8a8f98',
        'editorGhostText.border': '#00000000'
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
        'editor.lineHighlightBackground': '#3E3D32',
        'editorGhostText.foreground': '#8a8f98',
        'editorGhostText.border': '#00000000'
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
    monaco.editor?.setTabFocusMode?.(false)

    if (typeof window !== 'undefined') {
      import(
        'monaco-editor/esm/vs/editor/contrib/inlineCompletions/browser/inlineCompletions.contribution'
      ).catch(() => { })
    }

    // Notify parent about the editor instance
    try {
      onEditorMount && onEditorMount(editor)
    } catch { }

    // Define custom themes
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
      mouseWheelZoom: true,
      inlineSuggest: { enabled: true },
      tabCompletion: 'off'
    })

    // Track cursor position changes
    if (onCursorPositionChange) {
      editor.onDidChangeCursorPosition((e: any) => {
        onCursorPositionChange({
          line: e.position.lineNumber,
          column: e.position.column
        })
      })

      // Set initial position
      const position = editor.getPosition()
      if (position) {
        onCursorPositionChange({
          line: position.lineNumber,
          column: position.column
        })
      }
    }

    // Add keyboard shortcuts
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      saveFile()
    })

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      executeFile()
    })

    const providerDisposables: monaco.IDisposable[] = []
    const supportedLanguages = [
      'python',
      'javascript',
      'typescript',
      'tsx',
      'jsx',
      'java',
      'cpp',
      'c',
      'csharp',
      'go',
      'rust',
      'ruby',
      'php',
      'html',
      'css',
      'json',
      'yaml',
      'markdown',
      'sql',
      'shell',
      'plaintext'
    ]

    const registerInlineProvider = () => {
      const emptyResult = { items: [], dispose() { } }
      const provideInlineCompletions = async (
        model: any,
        position: any,
        context?: { triggerKind?: number },
        token?: monaco.CancellationToken
      ) => {
        const currentSessionId = sessionIdRef.current
        const currentFile = selectedFileRef.current
        if (!currentSessionId || !currentFile || !copilotEnabledRef.current) {
          return emptyResult
        }

        if (token?.isCancellationRequested) {
          return emptyResult
        }

        const content = model.getValue()
        const offset = model.getOffsetAt(position)
        const languageId = model.getLanguageId()
        const inlineTriggerKind = monaco.languages?.InlineCompletionTriggerKind
        const isExplicitTrigger = context?.triggerKind === inlineTriggerKind?.Explicit

        if (!isExplicitTrigger && !shouldTriggerInline(content, offset, languageId)) {
          return emptyResult
        }

        const normalizedPath = currentFile.path
          .replace(/^\/workspace\//, '')
          .replace(/^workspace\//, '')

        const prefixSlice = content.slice(Math.max(0, offset - 2000), offset)
        const suffixSlice = content.slice(offset, Math.min(content.length, offset + 400))
        const neighborPayload = neighborFilesRef.current

        if (inlineAbortControllerRef.current) {
          inlineAbortControllerRef.current.abort()
        }
        const controller = new AbortController()
        inlineAbortControllerRef.current = controller

        try {
          const res = await fetch('/api/ide/copilot/suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            signal: controller.signal,
            body: JSON.stringify({
              session_id: currentSessionId,
              filepath: normalizedPath,
              language: languageId,
              content,
              cursor_offset: offset,
              prefix: prefixSlice,
              suffix: suffixSlice,
              neighbor_files: neighborPayload
            })
          })

          if (!res.ok) {
            return emptyResult
          }

          const data = await res.json().catch(() => null)
          const suggestion: string = (data?.suggestion || '').trim()
          if (!suggestion || token?.isCancellationRequested) {
            return emptyResult
          }

          const pos = position
          return {
            items: [
              {
                insertText: suggestion,
                range: new monaco.Range(pos.lineNumber, pos.column, pos.lineNumber, pos.column)
              }
            ],
            dispose() { }
          }
        } catch (error: any) {
          if (error?.name !== 'AbortError') {
            console.warn('⚠️ Inline completion fetch failed', error)
          }
          return emptyResult
        } finally {
          if (inlineAbortControllerRef.current === controller) {
            inlineAbortControllerRef.current = null
          }
        }
      }

      supportedLanguages.forEach((lang) => {
        try {
          providerDisposables.push(
            monaco.languages.registerInlineCompletionsProvider(lang, {
              provideInlineCompletions,
              freeInlineCompletions: () => { }
            })
          )
        } catch (e) {
          console.warn('⚠️ Failed to register inline provider for', lang, e)
        }
      })
    }

    registerInlineProvider()

    const enableTestProvider =
      typeof window !== 'undefined' && (window as any).__ENABLE_INLINE_TEST_PROVIDER === true

    if (enableTestProvider) {
      const testDisposable = monaco.languages.registerInlineCompletionsProvider('python', {
        provideInlineCompletions: (_model: any, position: any) => {
          const pos = position
          return {
            items: [
              {
                insertText: 'return a + b',
                range: new monaco.Range(pos.lineNumber, pos.column, pos.lineNumber, pos.column)
              }
            ],
            dispose() { }
          }
        },
        freeInlineCompletions: () => { }
      })
      providerDisposables.push(testDisposable)
      console.log('🧪 Inline test provider enabled (set window.__ENABLE_INLINE_TEST_PROVIDER = true)')
    }

    let idleTimer: ReturnType<typeof setTimeout> | null = null
    editor.onDidChangeModelContent(() => {
      if (idleTimer) {
        clearTimeout(idleTimer)
      }

      idleTimer = setTimeout(() => {
        if (!copilotEnabledRef.current) {
          return
        }
        const model = editor.getModel()
        const position = editor.getPosition()
        if (!model || !position) {
          return
        }
        const offset = model.getOffsetAt(position)
        if (!shouldTriggerInline(model.getValue(), offset, model.getLanguageId())) {
          return
        }
        if (!editor.hasTextFocus?.()) {
          editor.focus()
        }
        editor.getAction('editor.action.inlineSuggest.trigger')?.run()
      }, 650)
    })

    // Auto-save on focus loss
    editor.onDidBlurEditorText(() => {
      if (isModified) {
        saveFile()
      }
    })

    // Cleanup on dispose
    editor.onDidDispose(() => {
      if (idleTimer) {
        clearTimeout(idleTimer)
      }
      providerDisposables.forEach((disposable) => {
        try {
          disposable.dispose()
        } catch (e) {
          console.warn('⚠️ Failed to dispose inline provider', e)
        }
      })
      if (inlineAbortControllerRef.current) {
        inlineAbortControllerRef.current.abort()
        inlineAbortControllerRef.current = null
      }
    })
  }

  const handleEditorChange = (value: string | undefined) => {
    if (value !== undefined) {
      setContent(value)
      setIsModified(true)
    }
  }

  const downloadFile = () => {
    if (!selectedFile || !content) return

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

  const copyContent = () => {
    if (!content) return
    navigator.clipboard.writeText(content)
  }

  return (
    <div className={`flex flex-col h-full bg-gray-900 ${className}`}>
      {/* Editor Controls */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <Code className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-medium text-gray-200">
            {selectedFile ? selectedFile.name : 'No file selected'}
          </span>
          {isModified && <Badge variant="outline" className="text-xs">Modified</Badge>}
        </div>

        <div className="flex items-center gap-2">
          {/* Save Status */}
          {saveStatus === 'saving' && (
            <div className="flex items-center gap-1 text-xs text-blue-400">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Saving...</span>
            </div>
          )}
          {saveStatus === 'saved' && (
            <div className="flex items-center gap-1 text-xs text-green-400">
              <CheckCircle className="w-3 h-3" />
              <span>Saved</span>
            </div>
          )}
          {saveStatus === 'error' && (
            <div className="flex items-center gap-1 text-xs text-red-400">
              <AlertCircle className="w-3 h-3" />
              <span>Error</span>
            </div>
          )}

          {/* Action Buttons */}
          <Button
            size="sm"
            variant="ghost"
            onClick={saveFile}
            disabled={!selectedFile || !isModified || isSaving}
            className="h-7"
          >
            <Save className="w-3 h-3 mr-1" />
            Save
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={executeFile}
            disabled={!selectedFile || isExecuting}
            className="h-7"
          >
            {isExecuting ? (
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
            ) : (
              <Play className="w-3 h-3 mr-1" />
            )}
            Run
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={downloadFile}
            disabled={!selectedFile}
            className="h-7"
          >
            <Download className="w-3 h-3" />
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={copyContent}
            disabled={!content}
            className="h-7"
          >
            <Copy className="w-3 h-3" />
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="h-7"
          >
            {isFullscreen ? (
              <Minimize2 className="w-3 h-3" />
            ) : (
              <Maximize2 className="w-3 h-3" />
            )}
          </Button>
        </div>
      </div>

      {/* Monaco Editor */}
      <div className="flex-1 relative">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <Loader2 className="w-8 h-8 text-purple-500 animate-spin" />
          </div>
        ) : selectedFile ? (
          <Editor
            height="100%"
            language={getLanguageFromFileName(selectedFile.name)}
            value={content}
            onChange={handleEditorChange}
            onMount={handleEditorDidMount}
            theme={editorTheme}
            options={{
              minimap: { enabled: false },
              fontSize: fontSize,
              wordWrap: wordWrap,
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
              insertSpaces: true,
              renderWhitespace: 'selection',
              lineNumbers: 'on',
              glyphMargin: true,
              folding: true,
              lineDecorationsWidth: 10,
              lineNumbersMinChars: 3,
              cursorStyle: 'line',
              cursorBlinking: 'blink',
              smoothScrolling: true,
              contextmenu: true,
              mouseWheelZoom: true,
              quickSuggestions: {
                other: 'inline',
                comments: 'off',
                strings: 'off',
              },
              inlineSuggest: {
                enabled: true,
              },
              tabCompletion: 'off',
            }}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500">
            <FileText className="w-16 h-16 mb-4 opacity-50" />
            <p className="text-lg">No file selected</p>
            <p className="text-sm mt-2">Select a file from the explorer to start editing</p>
          </div>
        )}
      </div>
    </div>
  )
}
