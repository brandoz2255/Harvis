"use client"

import React, { useRef, useEffect, useState } from 'react'
import Editor, { OnMount, OnChange } from '@monaco-editor/react'
import { editor } from 'monaco-editor'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  Save, 
  Play, 
  Download, 
  Copy, 
  Maximize, 
  Settings, 
  Code,
  Sparkles,
  FileText,
  Type
} from 'lucide-react'

interface VibeFile {
  id: string
  name: string
  content: string
  language: string
  isModified: boolean
}

interface VibeCodeEditorProps {
  file: VibeFile | null
  onContentChange: (content: string) => void
  onSave?: (fileId: string) => void
  onRun?: (fileId: string) => void
  onDownload?: (fileId: string) => void
  isExecuting?: boolean
  theme?: 'vibe-dark' | 'vs-dark' | 'light'
  readOnly?: boolean
}

export default function VibeCodeEditor({
  file,
  onContentChange,
  onSave,
  onRun,
  onDownload,
  isExecuting = false,
  theme = 'vibe-dark',
  readOnly = false
}: VibeCodeEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [wordWrap, setWordWrap] = useState<'on' | 'off'>('off')
  const [fontSize, setFontSize] = useState(14)

  // Language mapping for file extensions
  const getLanguageFromExtension = (filename: string): string => {
    const ext = filename.split('.').pop()?.toLowerCase()
    const langMap: { [key: string]: string } = {
      'py': 'python',
      'js': 'javascript',
      'jsx': 'javascriptreact',
      'ts': 'typescript',
      'tsx': 'typescriptreact',
      'html': 'html',
      'css': 'css',
      'scss': 'scss',
      'json': 'json',
      'md': 'markdown',
      'sql': 'sql',
      'yml': 'yaml',
      'yaml': 'yaml',
      'sh': 'shell',
      'bash': 'shell',
      'xml': 'xml',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'cs': 'csharp',
      'php': 'php',
      'rb': 'ruby',
      'go': 'go',
      'rs': 'rust',
      'swift': 'swift',
      'kt': 'kotlin',
      'r': 'r',
      'scala': 'scala',
      'dart': 'dart'
    }
    return langMap[ext || ''] || 'plaintext'
  }

  // Monaco editor theme definition
  const defineVibeTheme = (monaco: any) => {
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
        { token: 'delimiter', foreground: 'E1E4E8' }
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
        'editorBracketMatch.border': '#7C3AED'
      }
    })
  }

  // Register AI completion provider (disabled for now)
  const registerCompletionProvider = (monaco: any, language: string) => {
    return monaco.languages.registerCompletionItemProvider(language, {
      provideCompletionItems: async (model: any, position: any) => {
        // AI completion temporarily disabled - return empty suggestions
        return { suggestions: [] }
      },
      triggerCharacters: ['.', '(', ' ', '\n']
    })
  }

  const handleEditorDidMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    
    // Define custom theme
    defineVibeTheme(monaco)
    
    // Set theme
    monaco.editor.setTheme(theme)
    
    // Register completion provider for current language
    if (file) {
      const language = file.language || getLanguageFromExtension(file.name)
      registerCompletionProvider(monaco, language)
    }

    // Configure editor options
    editor.updateOptions({
      fontFamily: '"Fira Code", "JetBrains Mono", "SF Mono", Consolas, monospace',
      fontLigatures: true,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      automaticLayout: true,
      tabSize: 2,
      insertSpaces: true,
      wordWrap: wordWrap,
      lineNumbers: 'on',
      rulers: [80, 120],
      bracketPairColorization: { enabled: true },
      guides: {
        indentation: true,
        bracketPairs: true
      },
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
      quickSuggestions: {
        other: true,
        comments: true,
        strings: true
      },
      parameterHints: {
        enabled: true,
        cycle: true
      },
      autoClosingBrackets: 'always',
      autoClosingQuotes: 'always',
      autoIndent: 'full',
      formatOnType: true,
      formatOnPaste: true
    })

    // Add keyboard shortcuts
    editor.addAction({
      id: 'save-file',
      label: 'Save File',
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
      run: () => {
        if (file && onSave) {
          onSave(file.id)
        }
      }
    })

    editor.addAction({
      id: 'run-file',
      label: 'Run File',
      keybindings: [monaco.KeyCode.F5],
      run: () => {
        if (file && onRun) {
          onRun(file.id)
        }
      }
    })
  }

  const handleEditorChange: OnChange = (value) => {
    if (value !== undefined) {
      onContentChange(value)
    }
  }

  const copyToClipboard = () => {
    if (file && file.content) {
      navigator.clipboard.writeText(file.content)
    }
  }

  const formatCode = () => {
    if (editorRef.current) {
      editorRef.current.getAction('editor.action.formatDocument')?.run()
    }
  }

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen)
  }

  if (!file) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-900/50 rounded-lg border border-purple-500/30">
        <div className="text-center text-gray-400">
          <FileText className="w-16 h-16 mx-auto mb-4 opacity-50" />
          <h3 className="text-lg font-medium mb-2">No File Selected</h3>
          <p className="text-sm">Select a file from the tree or create a new one to start coding</p>
        </div>
      </div>
    )
  }

  const currentLanguage = file.language || getLanguageFromExtension(file.name)

  return (
    <div className={`flex flex-col h-full bg-gray-900/50 rounded-lg border border-purple-500/30 ${isFullscreen ? 'fixed inset-0 z-50 bg-gray-900' : ''}`}>
      {/* Action Bar */}
      <div className="flex items-center justify-between p-3 border-b border-purple-500/30 bg-gray-800/50">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2">
            <Code className="w-5 h-5 text-purple-400" />
            <span className="font-medium text-white">{file.name}</span>
            {file.isModified && (
              <Badge variant="outline" className="border-orange-500 text-orange-400 text-xs">
                Modified
              </Badge>
            )}
          </div>
          <Badge variant="outline" className="border-blue-500 text-blue-400 text-xs">
            {currentLanguage}
          </Badge>
        </div>

        <div className="flex items-center space-x-2">
          {/* Theme Selector */}
          <Button
            onClick={() => {
              // This would cycle through themes, but since theme is a prop, 
              // the parent component would need to handle theme changes
              console.log(`Current theme: ${theme}`)
            }}
            variant="outline"
            size="sm"
            className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
            title={`Theme: ${theme}`}
          >
            <Settings className="w-4 h-4" />
          </Button>

          <Button
            onClick={() => setWordWrap(wordWrap === 'on' ? 'off' : 'on')}
            variant="outline"
            size="sm"
            className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
            title="Toggle Word Wrap"
          >
            <Type className="w-4 h-4" />
          </Button>

          <Button
            onClick={formatCode}
            variant="outline"
            size="sm"
            className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
            title="Format Code"
          >
            <Sparkles className="w-4 h-4" />
          </Button>

          <Button
            onClick={copyToClipboard}
            variant="outline"
            size="sm"
            className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
            title="Copy to Clipboard"
          >
            <Copy className="w-4 h-4" />
          </Button>

          {onDownload && (
            <Button
              onClick={() => onDownload(file.id)}
              variant="outline"
              size="sm"
              className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
              title="Download File"
            >
              <Download className="w-4 h-4" />
            </Button>
          )}

          {onSave && (
            <Button
              onClick={() => onSave(file.id)}
              disabled={!file.isModified}
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white disabled:bg-gray-600"
              title="Save (Ctrl+S)"
            >
              <Save className="w-4 h-4" />
            </Button>
          )}

          {onRun && (
            <Button
              onClick={() => onRun(file.id)}
              disabled={isExecuting}
              size="sm"
              className="bg-blue-600 hover:bg-blue-700 text-white disabled:bg-gray-600"
              title="Run (F5)"
            >
              <Play className="w-4 h-4" />
            </Button>
          )}

          <Button
            onClick={toggleFullscreen}
            variant="outline"
            size="sm"
            className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
            title="Fullscreen"
          >
            <Maximize className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Monaco Editor */}
      <div className="flex-1">
        <Editor
          height="100%"
          language={currentLanguage}
          value={file.content}
          theme={theme}
          onChange={handleEditorChange}
          onMount={handleEditorDidMount}
          options={{
            readOnly,
            fontSize,
            automaticLayout: true,
            scrollBeyondLastLine: false,
            minimap: { enabled: !isFullscreen },
            wordWrap: wordWrap,
            lineNumbers: 'on',
            renderWhitespace: 'boundary',
            smoothScrolling: true,
            cursorBlinking: 'smooth',
            cursorSmoothCaretAnimation: "on"
          }}
        />
      </div>

      {/* Status Bar */}
      <div className="flex items-center justify-between px-3 py-2 border-t border-purple-500/30 bg-gray-800/30 text-xs text-gray-400">
        <div className="flex items-center space-x-4">
          <span>Lines: {file.content.split('\n').length}</span>
          <span>Size: {new Blob([file.content]).size} bytes</span>
          <span>Language: {currentLanguage}</span>
        </div>
        <div className="flex items-center space-x-2">
          {isExecuting && (
            <Badge variant="outline" className="border-blue-500 text-blue-400">
              Executing...
            </Badge>
          )}
          <span>UTF-8</span>
        </div>
      </div>
    </div>
  )
}