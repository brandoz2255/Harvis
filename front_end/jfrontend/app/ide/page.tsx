"use client"

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { useRouter } from "next/navigation"
import { useUser } from "@/lib/auth/UserProvider"
import { useUserPreferences } from "@/lib/useUserPreferences"
import { X } from "lucide-react"
import { ToastProvider } from "./components/Toast"
import VibeSessionManager from "@/components/VibeSessionManager"
import SessionCreator from "./components/SessionCreator"
import ExplorerNewFile from "./components/ExplorerNewFile"
import RunButton from "./components/RunButton"
import FileActions from "./components/FileActions"
import LeftSidebar from "@/components/LeftSidebar"
import ResizablePanel from "@/components/ResizablePanel"
import VibeContainerCodeEditor from "@/components/VibeContainerCodeEditor"
import EditorTabBar, { EditorTab } from "@/components/EditorTabBar"
import SessionTabs from "@/components/SessionTabs"
import TerminalTabBar, { TerminalTab } from "@/components/TerminalTabBar"
import OptimizedVibeTerminal from "@/components/OptimizedVibeTerminal"
import StatusBar from "@/components/StatusBar"
import CommandPalette, { useIDECommands } from "@/components/CommandPalette"
import { Loader2, ChevronLeft, ChevronRight, FileText, Save, CheckCircle, AlertCircle, Terminal } from "lucide-react"
import { toWorkspaceRelativePath } from '@/lib/strings'
import { toRel } from './lib/paths'

interface Session {
  id: string
  session_id: string
  name: string
  description?: string
  container_status: 'running' | 'stopped' | 'starting' | 'stopping'
  created_at: string
  updated_at: string
  last_activity: string
  file_count: number
  activity_status: 'active' | 'recent' | 'inactive'
}

export default function IDEPage() {
  const router = useRouter()
  const { user, isLoading: userLoading } = useUser()
  const { preferences, updatePreferences, isLoading: prefsLoading } = useUserPreferences()
  
  // Core state
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [openSessions, setOpenSessions] = useState<Session[]>([])
  const [showSessionManager, setShowSessionManager] = useState(false)
  const [sessionCapabilities, setSessionCapabilities] = useState<Record<string, boolean>>({})
  
  // Cursor position state for status bar
  const [cursorPosition, setCursorPosition] = useState<{ line: number; column: number }>({ line: 1, column: 1 })
  
  // Editor tabs state
  const [editorTabs, setEditorTabs] = useState<EditorTab[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  
  // Panel state - initialized from preferences
  const [leftPanelWidth, setLeftPanelWidth] = useState(280)
  const [showLeftPanel, setShowLeftPanel] = useState(true)
  const [terminalHeight, setTerminalHeight] = useState(200)
  const [showTerminal, setShowTerminal] = useState(true)
  const [activeOutputTab, setActiveOutputTab] = useState<'terminal' | 'output'>('terminal')
  const [codeOutput, setCodeOutput] = useState<string>('')
  
  // Command palette state
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  
  // Session creation loading and error states
  const [isCreatingSession, setIsCreatingSession] = useState(false)
  const [sessionCreationError, setSessionCreationError] = useState<string | null>(null)
  const [sessionCreationSuccess, setSessionCreationSuccess] = useState<string | null>(null)
  
  // Terminal tabs state
  const [terminalTabs, setTerminalTabs] = useState<TerminalTab[]>([])
  const [activeTerminalId, setActiveTerminalId] = useState<string | null>(null)
  
  // AI Assistant state
  const [chatMessages, setChatMessages] = useState<Array<{
    role: 'user' | 'assistant'
    content: string
    timestamp: Date
    reasoning?: string
  }>>([])
  const [isAIProcessing, setIsAIProcessing] = useState(false)
  const [selectedModel, setSelectedModel] = useState('mistral')
  const [availableModels, setAvailableModels] = useState<Array<{
    name: string
    provider: string
    type: string
  }>>([])
  
  // Code Execution state
  const [executionHistory, setExecutionHistory] = useState<Array<{
    command: string
    stdout: string
    stderr: string
    exit_code: number
    started_at: number
    finished_at: number
    execution_time_ms: number
  }>>([])
  const [isExecuting, setIsExecuting] = useState(false)
  
  // Refs for debouncing and terminal focus
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const terminalContainerRef = useRef<HTMLDivElement | null>(null)

  // Memoize active tab to prevent recreation on every render
  const activeTab = useMemo(() => {
    if (!activeTabId) return null
    return editorTabs.find(t => t.id === activeTabId) || null
  }, [activeTabId, editorTabs])

  // Memoize selectedFile to prevent recreation on every render
  const selectedFile = useMemo(() => {
    if (!activeTab) return null

    return {
      name: activeTab.name,
      path: activeTab.path,
      type: 'file' as const,
      size: 0,
      permissions: ''
    }
  }, [activeTab])

  // Authentication guard
  useEffect(() => {
    if (!userLoading && !user) {
      router.push('/login')
    }
  }, [user, userLoading, router])

  // Load and apply user preferences
  useEffect(() => {
    if (preferences && !prefsLoading) {
      // Apply panel sizes from preferences
      setLeftPanelWidth(preferences.left_panel_width || 280)
      setTerminalHeight(preferences.terminal_height || 200)
      
      // Apply theme (this would typically be handled by a theme provider)
      // For now, we'll just log it
      console.log('Applied theme from preferences:', preferences.theme)
      
      // Apply font size to editor and terminal
      if (preferences.font_size) {
        document.documentElement.style.setProperty('--editor-font-size', `${preferences.font_size}px`)
      }
      
      // Apply default model
      if (preferences.default_model) {
        setSelectedModel(preferences.default_model)
      }
    }
  }, [preferences, prefsLoading])

  // Show session manager on mount if no session
  useEffect(() => {
    if (!userLoading && user && !currentSession) {
      setShowSessionManager(true)
    }
  }, [user, userLoading, currentSession])

  // Handle session selection
  const handleSessionSelect = async (session: Session) => {
    try {
      console.log('🔄 Opening session:', session.session_id)
      
      // Call /sessions/open to auto-start container
      const token = localStorage.getItem('token')
      const response = await fetch('/api/vibecode/sessions/open', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ session_id: session.session_id })
      })
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('❌ Failed to open session:', response.status, errorText)
        throw new Error(`Failed to open session: ${response.status}`)
      }
      
      const data = await response.json()
      console.log('✅ Session opened successfully:', data)
      
      // Update session with container info
      const updatedSession = {
        ...session,
        container_status: 'running' as const,
        container_id: data.container?.id
      }
      
      setCurrentSession(updatedSession)
      
      // Add to open sessions if not already there
      setOpenSessions(prev => {
        const exists = prev.some(s => s.session_id === session.session_id)
        if (!exists) {
          return [...prev, updatedSession]
        }
        return prev.map(s => s.session_id === session.session_id ? updatedSession : s)
      })
      
      // Fetch session capabilities
      try {
        const statusResponse = await fetch(`/api/vibecoding/status/${session.session_id}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        })
        if (statusResponse.ok) {
          const statusData = await statusResponse.json()
          setSessionCapabilities(statusData.capabilities || {})
        }
      } catch (error) {
        console.warn('Failed to fetch capabilities:', error)
        setSessionCapabilities({})
      }
      
      setShowSessionManager(false)
      
      // Create initial terminal tab when session is selected
      if (terminalTabs.length === 0) {
        createTerminal()
      }
    } catch (error) {
      console.error('❌ Failed to open session:', error)
      // Still set the session but show error
      setCurrentSession(session)
      setShowSessionManager(false)
    }
  }

  // Handle session close
  const handleSessionClose = (sessionId: string) => {
    setOpenSessions(prev => prev.filter(s => s.session_id !== sessionId))
    
    // If closing current session, switch to another or clear
    if (currentSession?.session_id === sessionId) {
      const remainingSessions = openSessions.filter(s => s.session_id !== sessionId)
      if (remainingSessions.length > 0) {
        setCurrentSession(remainingSessions[0])
      } else {
        setCurrentSession(null)
      }
    }
  }

  // Handle new session
  const handleNewSession = () => {
    setShowSessionManager(true)
  }
  
  // Create new terminal tab
  const createTerminal = useCallback(() => {
    const terminalNumber = terminalTabs.length + 1
    const newTerminal: TerminalTab = {
      id: `terminal-${Date.now()}-${Math.random()}`,
      name: `Terminal ${terminalNumber}`,
      instanceId: `instance-${Date.now()}-${Math.random()}`
    }
    
    setTerminalTabs(prev => [...prev, newTerminal])
    setActiveTerminalId(newTerminal.id)
  }, [terminalTabs.length])
  
  // Close terminal tab
  const closeTerminal = useCallback((tabId: string) => {
    // If closing the active terminal, show confirmation
    if (activeTerminalId === tabId && terminalTabs.length > 1) {
      const confirmed = window.confirm('Close this terminal? Any running processes will be terminated.')
      if (!confirmed) return
    }
    
    setTerminalTabs(prev => {
      const newTabs = prev.filter(tab => tab.id !== tabId)
      
      // If closing active terminal, switch to another tab
      if (activeTerminalId === tabId) {
        if (newTabs.length > 0) {
          // Switch to the tab to the right, or the last tab if closing the rightmost
          const closedIndex = prev.findIndex(tab => tab.id === tabId)
          const nextTab = newTabs[Math.min(closedIndex, newTabs.length - 1)]
          setActiveTerminalId(nextTab.id)
        } else {
          setActiveTerminalId(null)
        }
      }
      
      return newTabs
    })
  }, [activeTerminalId, terminalTabs.length])
  
  // Handle terminal tab click
  const handleTerminalTabClick = (tabId: string) => {
    setActiveTerminalId(tabId)
  }

  // Handle session creation
  const handleSessionCreate = async (projectName: string, description?: string): Promise<Session> => {
    setIsCreatingSession(true)
    setSessionCreationError(null)
    setSessionCreationSuccess(null)
    
    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')

      const response = await fetch('/api/vibecode/sessions/create', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: projectName, description })
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Failed to create session (${response.status})`)
      }
      
      const data = await response.json()
      
      // Show success message
      setSessionCreationSuccess(`Session "${projectName}" created successfully! Loading...`)
      
      // Clear success message after 3 seconds
      setTimeout(() => {
        setSessionCreationSuccess(null)
      }, 3000)
      
      return data.session
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to create session'
      setSessionCreationError(errorMessage)
      
      // Clear error message after 5 seconds
      setTimeout(() => {
        setSessionCreationError(null)
      }, 5000)
      
      throw error
    } finally {
      setIsCreatingSession(false)
    }
  }

  // Handle session deletion
  const handleSessionDelete = async (sessionId: string): Promise<void> => {
    const token = localStorage.getItem('token')
    if (!token) throw new Error('Not authenticated')

    const response = await fetch('/api/vibecode/sessions/delete', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ session_id: sessionId })
    })

    if (!response.ok) throw new Error('Failed to delete session')
  }

  // Get language from file extension
  const getLanguageFromPath = (path: string): string => {
    const ext = path.split('.').pop()?.toLowerCase()
    const languageMap: Record<string, string> = {
      'js': 'javascript',
      'jsx': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'py': 'python',
      'java': 'java',
      'cpp': 'cpp',
      'c': 'c',
      'cs': 'csharp',
      'php': 'php',
      'rb': 'ruby',
      'go': 'go',
      'rs': 'rust',
      'html': 'html',
      'css': 'css',
      'scss': 'scss',
      'json': 'json',
      'xml': 'xml',
      'yaml': 'yaml',
      'yml': 'yaml',
      'md': 'markdown',
      'sql': 'sql',
      'sh': 'shell',
      'bash': 'shell'
    }
    return languageMap[ext || ''] || 'plaintext'
  }

  // Handle file selection from file tree
  const handleFileSelect = (filePath: string, content: string) => {
    // Check if tab already exists
    const existingTab = editorTabs.find(tab => tab.path === filePath)
    
    if (existingTab) {
      // Just switch to existing tab
      setActiveTabId(existingTab.id)
    } else {
      // Create new tab
      const fileName = filePath.split('/').pop() || 'untitled'
      const newTab: EditorTab = {
        id: filePath, // Use path as unique ID
        name: fileName,
        path: filePath,
        content: content,
        isDirty: false,
        language: getLanguageFromPath(filePath)
      }
      
      setEditorTabs(prev => [...prev, newTab])
      setActiveTabId(newTab.id)
    }
  }

  // Handle code execution from editor
  const handleCodeExecution = async (filePath: string) => {
    if (!currentSession) return

    console.log('🚀 Executing code for file:', filePath)
    
    try {
      setIsExecuting(true)
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')

      // Get file extension to determine execution command
      const fileName = filePath.split('/').pop() || ''
      const extension = fileName.split('.').pop()?.toLowerCase() || ''
      
      let command = ''
      switch (extension) {
        case 'py':
          command = `python ${toWorkspaceRelativePath(filePath)}`
          break
        case 'js':
          command = `node ${toWorkspaceRelativePath(filePath)}`
          break
        case 'ts':
          command = `npx ts-node ${toWorkspaceRelativePath(filePath)}`
          break
        case 'sh':
          command = `bash ${toWorkspaceRelativePath(filePath)}`
          break
        default:
          command = `cat ${toWorkspaceRelativePath(filePath)}`
      }

      const response = await fetch('/api/vibecode/exec', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          cmd: command
        })
      })

      if (!response.ok) throw new Error('Execution failed')

      const result = await response.json()

      // Show clean output (just the actual output, no labels)
      const out = (result.stdout && result.stdout.trim()) || ''
      const err = (result.stderr && result.stderr.trim()) || ''
      
      // Show stdout if available, otherwise stderr, otherwise "No output"
      const cleanOutput = out || err || 'No output'
      
      console.log('📤 Setting output:', cleanOutput)
      setCodeOutput(cleanOutput)
      setActiveOutputTab('output')

      setExecutionHistory(prev => [...prev, result])
    } catch (error) {
      console.error('Execution error:', error)
      
      // Show error in output area
      setCodeOutput(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setActiveOutputTab('output')
      
      // Add error result to history
      setExecutionHistory(prev => [...prev, {
        command: filePath,
        stdout: '',
        stderr: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        exit_code: 1,
        started_at: Date.now(),
        finished_at: Date.now(),
        execution_time_ms: 0
      }])
    } finally {
      setIsExecuting(false)
    }
  }

  // Handle tab click
  const handleTabClick = (tabId: string) => {
    setActiveTabId(tabId)
  }

  // Handle tab close
  const handleTabClose = (tabId: string) => {
    setEditorTabs(prev => {
      const newTabs = prev.filter(tab => tab.id !== tabId)
      
      // If closing active tab, switch to another tab
      if (activeTabId === tabId) {
        if (newTabs.length > 0) {
          // Switch to the tab to the right, or the last tab if closing the rightmost
          const closedIndex = prev.findIndex(tab => tab.id === tabId)
          const nextTab = newTabs[Math.min(closedIndex, newTabs.length - 1)]
          setActiveTabId(nextTab.id)
        } else {
          setActiveTabId(null)
        }
      }
      
      return newTabs
    })
  }

  // Save file to backend
  const saveFile = useCallback(async (tabId: string) => {
    const tab = editorTabs.find(t => t.id === tabId)
    if (!tab || !currentSession) return

    try {
      setSaveStatus('saving')
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')

      const response = await fetch('/api/vibecode/files/save', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          path: toWorkspaceRelativePath(tab.path),
          content: tab.content
        })
      })

      if (!response.ok) throw new Error('Failed to save file')

      // Clear isDirty flag
      setEditorTabs(prev => prev.map(t => 
        t.id === tabId ? { ...t, isDirty: false } : t
      ))

      setSaveStatus('saved')
      
      // Reset status after 2 seconds
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch (error) {
      console.error('Save failed:', error)
      setSaveStatus('error')
      setTimeout(() => setSaveStatus('idle'), 3000)
    }
  }, [editorTabs, currentSession])

  // Debounced auto-save
  const debouncedSave = useCallback((tabId: string) => {
    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
    }

    // Set new timeout for 500ms
    saveTimeoutRef.current = setTimeout(() => {
      saveFile(tabId)
    }, 500)
  }, [saveFile])

  // Handle editor content change
  const handleEditorChange = (value: string | undefined) => {
    if (!activeTabId || value === undefined) return
    
    setEditorTabs(prev => prev.map(tab => 
      tab.id === activeTabId 
        ? { ...tab, content: value, isDirty: true }
        : tab
    ))

    // Trigger debounced auto-save
    debouncedSave(activeTabId)
  }

  // Manual save (for keyboard shortcut)
  const handleManualSave = useCallback(() => {
    if (activeTabId) {
      // Cancel any pending auto-save
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
        saveTimeoutRef.current = null
      }
      // Save immediately
      saveFile(activeTabId)
    }
  }, [activeTabId, saveFile])

  // Panel resize handlers with preference persistence
  const handleLeftPanelResize = useCallback((width: number) => {
    setLeftPanelWidth(width)
    updatePreferences({ left_panel_width: width })
  }, [updatePreferences])
  
  const handleTerminalResize = useCallback((height: number) => {
    setTerminalHeight(height)
    updatePreferences({ terminal_height: height })
  }, [updatePreferences])

  // Toggle panels
  const toggleLeftPanel = useCallback(() => {
    setShowLeftPanel(prev => !prev)
  }, [])
  
  const toggleTerminal = useCallback(() => {
    setShowTerminal(prev => !prev)
  }, [])
  
  // Status bar action handlers
  const handleCommandPaletteClick = () => {
    setShowCommandPalette(true)
  }
  
  const handleThemeToggle = useCallback(() => {
    const newTheme = preferences?.theme === 'dark' ? 'light' : 'dark'
    updatePreferences({ theme: newTheme })
    
    // Apply theme immediately (in a real app, this would be handled by a theme provider)
    console.log('Theme toggled to:', newTheme)
  }, [preferences, updatePreferences])
  
  const handleSettingsClick = () => {
    // TODO: Implement settings modal
    console.log('Settings clicked')
  }
  
  // Container control handlers
  const handleStartContainer = useCallback(async () => {
    if (!currentSession) return
    
    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')
      
      const response = await fetch('/api/vibecode/sessions/open', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ session_id: currentSession.session_id })
      })
      
      if (!response.ok) throw new Error('Failed to start container')
      
      // Update session status
      setCurrentSession(prev => prev ? { ...prev, container_status: 'starting' } : null)
      
      // Poll for status update
      setTimeout(() => {
        setCurrentSession(prev => prev ? { ...prev, container_status: 'running' } : null)
      }, 2000)
    } catch (error) {
      console.error('Failed to start container:', error)
    }
  }, [currentSession])
  
  const handleStopContainer = useCallback(async () => {
    if (!currentSession) return
    
    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')
      
      const response = await fetch('/api/vibecode/sessions/suspend', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ session_id: currentSession.session_id })
      })
      
      if (!response.ok) throw new Error('Failed to stop container')
      
      // Update session status
      setCurrentSession(prev => prev ? { ...prev, container_status: 'stopping' } : null)
      
      // Poll for status update
      setTimeout(() => {
        setCurrentSession(prev => prev ? { ...prev, container_status: 'stopped' } : null)
      }, 2000)
    } catch (error) {
      console.error('Failed to stop container:', error)
    }
  }, [currentSession])
  
  // New file handler
  const handleNewFile = useCallback(() => {
    // TODO: Implement new file creation dialog
    console.log('New file creation not yet implemented')
  }, [])

  // Fetch available AI models
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const token = localStorage.getItem('token')
        if (!token) return

        const response = await fetch('/api/vibecode/ai/models', {
          headers: { 'Authorization': `Bearer ${token}` }
        })

        if (response.ok) {
          const data = await response.json()
          setAvailableModels(data.models || [])
        }
      } catch (error) {
        console.error('Failed to fetch AI models:', error)
      }
    }

    if (currentSession) {
      fetchModels()
    }
  }, [currentSession])

  // Handle AI message sending
  const handleSendAIMessage = async (message: string) => {
    if (!currentSession) return

    const userMessage = {
      role: 'user' as const,
      content: message,
      timestamp: new Date()
    }

    setChatMessages(prev => [...prev, userMessage])
    setIsAIProcessing(true)

    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')

      const response = await fetch('/api/vibecode/ai/chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message,
          session_id: currentSession.session_id,
          model: selectedModel,
          history: chatMessages.slice(-10),
          context: {
            container_status: currentSession.container_status,
            selected_file: activeTabId ? editorTabs.find(t => t.id === activeTabId)?.path : null
          }
        })
      })

      if (!response.ok) throw new Error('AI request failed')

      const data = await response.json()

      const aiMessage = {
        role: 'assistant' as const,
        content: data.content || data.response || 'No response',
        timestamp: new Date(),
        reasoning: data.reasoning
      }

      setChatMessages(prev => [...prev, aiMessage])
    } catch (error) {
      console.error('AI chat error:', error)
      
      const errorMessage = {
        role: 'assistant' as const,
        content: 'Sorry, I encountered an error processing your request.',
        timestamp: new Date()
      }
      
      setChatMessages(prev => [...prev, errorMessage])
    } finally {
      setIsAIProcessing(false)
    }
  }

  // Handle code execution
  const handleExecuteCode = async (command: string) => {
    if (!currentSession) return

    setIsExecuting(true)

    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('Not authenticated')

      const response = await fetch('/api/vibecode/exec', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          cmd: command
        })
      })

      if (!response.ok) throw new Error('Execution failed')

      const result = await response.json()

      // Show stdout/stderr with exit code in the output area
      const out = (result.stdout && result.stdout.trim()) || ''
      const err = (result.stderr && result.stderr.trim()) || ''
      const exit = typeof result.exit_code === 'number' ? result.exit_code : null
      const composed = [
        exit !== null ? `exit_code: ${exit}` : null,
        out ? `stdout:\n${out}` : null,
        err ? `stderr:\n${err}` : null
      ].filter(Boolean).join('\n\n') || 'No output'
      setCodeOutput(composed)
      setActiveOutputTab('output')

      setExecutionHistory(prev => [...prev, result])
    } catch (error) {
      console.error('Execution error:', error)
      
      // Show error in output area with exit code style
      setCodeOutput(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setActiveOutputTab('output')
      
      // Add error result to history
      setExecutionHistory(prev => [...prev, {
        command,
        stdout: '',
        stderr: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        exit_code: 1,
        started_at: Date.now(),
        finished_at: Date.now(),
        execution_time_ms: 0
      }])
    } finally {
      setIsExecuting(false)
    }
  }

  // Load and restore tabs from localStorage on mount
  useEffect(() => {
    if (currentSession) {
      const savedTabs = localStorage.getItem(`ide-tabs-${currentSession.session_id}`)
      if (savedTabs) {
        try {
          const parsed = JSON.parse(savedTabs)
          setEditorTabs(parsed.tabs || [])
          setActiveTabId(parsed.activeTabId || null)
        } catch (e) {
          console.warn('Failed to restore tabs from localStorage')
        }
      }
      
      // Restore terminal tabs
      const savedTerminalTabs = localStorage.getItem(`ide-terminal-tabs-${currentSession.session_id}`)
      if (savedTerminalTabs) {
        try {
          const parsed = JSON.parse(savedTerminalTabs)
          setTerminalTabs(parsed.tabs || [])
          setActiveTerminalId(parsed.activeTabId || null)
        } catch (e) {
          console.warn('Failed to restore terminal tabs from localStorage')
        }
      }
    }
  }, [currentSession])

  // Save tabs to localStorage when they change
  useEffect(() => {
    if (currentSession && editorTabs.length > 0) {
      localStorage.setItem(
        `ide-tabs-${currentSession.session_id}`,
        JSON.stringify({ tabs: editorTabs, activeTabId })
      )
    }
  }, [editorTabs, activeTabId, currentSession])
  
  // Save terminal tabs to localStorage when they change
  useEffect(() => {
    if (currentSession && terminalTabs.length > 0) {
      localStorage.setItem(
        `ide-terminal-tabs-${currentSession.session_id}`,
        JSON.stringify({ tabs: terminalTabs, activeTabId: activeTerminalId })
      )
    }
  }, [terminalTabs, activeTerminalId, currentSession])

  // Save panel visibility to localStorage
  useEffect(() => {
    localStorage.setItem('ide-panel-visibility', JSON.stringify({
      showLeftPanel,
      showTerminal
    }))
  }, [showLeftPanel, showTerminal])

  // Restore panel visibility from localStorage on mount
  useEffect(() => {
    const savedVisibility = localStorage.getItem('ide-panel-visibility')
    if (savedVisibility) {
      try {
        const parsed = JSON.parse(savedVisibility)
        setShowLeftPanel(parsed.showLeftPanel ?? true)
        setShowTerminal(parsed.showTerminal ?? true)
      } catch (e) {
        console.warn('Failed to restore panel visibility from localStorage')
      }
    }
  }, [])

  // Create command palette commands
  const commands = useIDECommands({
    onSaveFile: handleManualSave,
    onNewFile: handleNewFile,
    onNewTerminal: createTerminal,
    onStartContainer: handleStartContainer,
    onStopContainer: handleStopContainer,
    onToggleTheme: handleThemeToggle,
    onToggleLeftPanel: toggleLeftPanel,
    onToggleTerminal: toggleTerminal,
    canSave: !!activeTabId,
    canStartContainer: currentSession?.container_status === 'stopped',
    canStopContainer: currentSession?.container_status === 'running',
    theme: preferences?.theme || 'dark'
  })

  // Focus terminal helper
  const focusTerminal = useCallback(() => {
    // Show terminal if hidden
    setShowTerminal(true)
    
    // Focus the terminal input after a short delay to ensure it's rendered
    setTimeout(() => {
      const terminalInput = terminalContainerRef.current?.querySelector('input[type="text"]') as HTMLInputElement
      if (terminalInput) {
        terminalInput.focus()
      }
    }, 100)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+P or Cmd+Shift+P - Command Palette
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'P') {
        e.preventDefault()
        setShowCommandPalette(true)
        return
      }
      
      // Ctrl+K or Cmd+K - AI Chat (Cursor-style)
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        // Focus AI chat in left sidebar
        setShowLeftPanel(true)
        // TODO: Focus AI chat input
        return
      }
      
      // Ctrl+Shift+E or Cmd+Shift+E - File Explorer
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'E') {
        e.preventDefault()
        setShowLeftPanel(true)
        // TODO: Focus file explorer
        return
      }
      
      // Ctrl+Shift+F or Cmd+Shift+F - Search
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'F') {
        e.preventDefault()
        setShowLeftPanel(true)
        // TODO: Focus search
        return
      }
      
      // Ctrl+S or Cmd+S - Save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleManualSave()
        return
      }
      
      // Ctrl+B or Cmd+B - Toggle left panel
      if ((e.ctrlKey || e.metaKey) && e.key === 'b' && !e.altKey) {
        e.preventDefault()
        toggleLeftPanel()
        return
      }
      
      // Ctrl+J or Cmd+J - Toggle terminal
      if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
        e.preventDefault()
        toggleTerminal()
        return
      }
      
      // Ctrl+` or Cmd+` - Focus terminal
      if ((e.ctrlKey || e.metaKey) && e.key === '`') {
        e.preventDefault()
        focusTerminal()
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleManualSave, toggleLeftPanel, toggleTerminal, focusTerminal])

  // Loading state
  if (userLoading) {
    return (
      <div className="h-screen bg-gray-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          <p className="text-gray-400">Loading IDE...</p>
        </div>
      </div>
    )
  }

  // Not authenticated
  if (!user) {
    return null
  }

  return (
    <ToastProvider>
      <div className="h-screen bg-gray-900 text-white flex flex-col overflow-hidden">
      {/* Header with Session Tabs */}
      <header className="h-12 bg-gray-800 border-b border-gray-700 flex items-center justify-between px-4 flex-shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">VibeCode IDE</h1>
          <SessionTabs
            sessions={openSessions}
            activeSessionId={currentSession?.session_id || null}
            onSessionSelect={handleSessionSelect}
            onSessionClose={handleSessionClose}
            onNewSession={() => {}} // Disabled - using SessionCreator instead
            className="flex-1"
          />
          <SessionCreator
            onReady={(sessionId) => {
              // Load the session details
              const token = localStorage.getItem('token')
              fetch('/api/vibecoding/sessions', {
                headers: { 'Authorization': `Bearer ${token}` }
              })
                .then(r => r.json())
                .then((sessions: any[]) => {
                  const session = sessions.find(s => s.session_id === sessionId || s.id === sessionId)
                  if (session) {
                    setCurrentSession(session as Session)
                    setShowSessionManager(false)
                    setOpenSessions(prev => {
                      const exists = prev.some(s => s.session_id === sessionId)
                      return exists ? prev : [...prev, session as Session]
                    })
                  }
                })
                .catch(console.error)
            }}
          />
        </div>
        <div className="flex items-center gap-2">
          {currentSession && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">Container:</span>
              <span className={`text-xs px-2 py-1 rounded ${
                currentSession.container_status === 'running' 
                  ? 'bg-green-500/20 text-green-400' 
                  : 'bg-red-500/20 text-red-400'
              }`}>
                {currentSession.container_status}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* Main Grid Layout */}
      <div className="flex-1 overflow-hidden flex">
        {/* Left Sidebar - Cursor Style */}
        {showLeftPanel && (
          <ResizablePanel
            width={leftPanelWidth}
            onResize={handleLeftPanelResize}
            minWidth={200}
            maxWidth={500}
            direction="horizontal"
            handlePosition="right"
          >
            <LeftSidebar
              sessionId={currentSession?.session_id || null}
              isContainerRunning={currentSession?.container_status === 'running'}
              onFileSelect={handleFileSelect}
              chatMessages={chatMessages}
              isAIProcessing={isAIProcessing}
              selectedModel={selectedModel}
              availableModels={availableModels}
              onSendMessage={handleSendAIMessage}
              onModelChange={setSelectedModel}
              newFileButton={
                <ExplorerNewFile
                  sessionId={currentSession?.session_id || null}
                  currentDir=""
                  refreshTree={async () => {
                    // Trigger file tree refresh
                    console.log('Refreshing file tree...')
                  }}
                  onOpenFile={(filePath) => {
                    handleFileSelect(filePath, '')
                  }}
                />
              }
              className="h-full"
            />
          </ResizablePanel>
        )}
        
        {/* Toggle button when panel is hidden */}
        {!showLeftPanel && (
          <button
            onClick={toggleLeftPanel}
            className="w-8 bg-gray-800 border-r border-gray-700 flex items-center justify-center hover:bg-gray-700 transition-colors"
            title="Show Sidebar"
          >
            <ChevronRight className="w-4 h-4 text-gray-400" />
          </button>
        )}
        
        {/* Center - Editor and Terminal */}
        <div className="flex-1 flex flex-col overflow-hidden">
            {/* Center - Editor */}
            <div className="flex-1 bg-gray-900 overflow-hidden flex flex-col">
            {/* Editor Tab Bar with Save Button */}
            <div className="flex items-center bg-gray-800 border-b border-gray-700">
              <EditorTabBar
                tabs={editorTabs}
                activeTabId={activeTabId}
                onTabClick={handleTabClick}
                onTabClose={handleTabClose}
                className="flex-1"
              />
              
              {/* Save Button and Run Button */}
              {activeTabId && (
                <div className="flex items-center gap-2 px-3 border-l border-gray-700">
                  <button
                    onClick={handleManualSave}
                    disabled={saveStatus === 'saving'}
                    className={`
                      flex items-center gap-2 px-3 py-1.5 rounded text-sm transition-colors
                      ${saveStatus === 'saving' 
                        ? 'bg-gray-700 text-gray-400 cursor-wait' 
                        : saveStatus === 'saved'
                        ? 'bg-green-600 text-white'
                        : saveStatus === 'error'
                        ? 'bg-red-600 text-white'
                        : 'bg-blue-600 hover:bg-blue-700 text-white'
                      }
                    `}
                    title="Save (Ctrl+S)"
                  >
                    {saveStatus === 'saving' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Saving...</span>
                      </>
                    ) : saveStatus === 'saved' ? (
                      <>
                        <CheckCircle className="w-4 h-4" />
                        <span>Saved</span>
                      </>
                    ) : saveStatus === 'error' ? (
                      <>
                        <AlertCircle className="w-4 h-4" />
                        <span>Error</span>
                      </>
                    ) : (
                      <>
                        <Save className="w-4 h-4" />
                        <span>Save</span>
                      </>
                    )}
                  </button>
                  
                  {/* Run Button */}
                  <RunButton
                    filePath={activeTab?.filePath || ''}
                    sessionId={currentSession?.session_id || null}
                    capabilities={sessionCapabilities}
                    onRun={(result) => {
                      console.log('Code execution result:', result)
                      // You can add logic here to show the result in the output area
                    }}
                  />
                  
                  {/* File Actions (Format/Validate for JSON, etc.) */}
                  <FileActions
                    filePath={activeTab?.filePath || ''}
                    sessionId={currentSession?.session_id || null}
                  />
                </div>
              )}
            </div>
            
            {/* Monaco Editor */}
            <div className="flex-1 overflow-hidden">
              {selectedFile && currentSession ? (
                <VibeContainerCodeEditor
                  sessionId={currentSession.session_id}
                  selectedFile={selectedFile}
                  onExecute={handleCodeExecution}
                  onCursorPositionChange={setCursorPosition}
                  className="h-full"
                />
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-gray-400">
                  <FileText className="w-16 h-16 mb-4 opacity-50" />
                  <p className="text-lg">No file open</p>
                  <p className="text-sm mt-2">Select a file from the explorer to start editing</p>
                </div>
              )}
            </div>
          </div>

          {/* Bottom - Terminal with Tabs */}
          {showTerminal && (
            <ResizablePanel
              height={terminalHeight}
              onResize={handleTerminalResize}
              minHeight={100}
              maxHeight={600}
              direction="vertical"
              handlePosition="top"
            >
              <div className="h-full bg-gray-800 border-t border-gray-700 overflow-hidden flex flex-col">
                {/* Output and Terminal Tabs */}
                <div className="flex border-b border-gray-700">
                  <button
                    className={`px-4 py-2 text-sm font-medium transition-colors ${
                      activeOutputTab === 'terminal' 
                        ? 'bg-gray-700 text-white border-b-2 border-blue-500' 
                        : 'text-gray-400 hover:text-white hover:bg-gray-700'
                    }`}
                    onClick={() => setActiveOutputTab('terminal')}
                  >
                    Terminal
                  </button>
                  <button
                    className={`px-4 py-2 text-sm font-medium transition-colors ${
                      activeOutputTab === 'output' 
                        ? 'bg-gray-700 text-white border-b-2 border-blue-500' 
                        : 'text-gray-400 hover:text-white hover:bg-gray-700'
                    }`}
                    onClick={() => setActiveOutputTab('output')}
                  >
                    Output
                  </button>
                </div>
                
                {/* Output/Terminal Content */}
                {activeOutputTab === 'terminal' ? (
                  <>
                    {/* Terminal Tab Bar */}
                    <TerminalTabBar
                      tabs={terminalTabs}
                      activeTabId={activeTerminalId}
                      onTabClick={handleTerminalTabClick}
                  onTabClose={closeTerminal}
                  onNewTab={createTerminal}
                />
                
                {/* Terminal Content */}
                <div ref={terminalContainerRef} className="flex-1 overflow-hidden relative">
                  {terminalTabs.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-gray-400">
                      <Terminal className="w-12 h-12 mb-3 opacity-50" />
                      <p className="text-sm">No terminal open</p>
                      <button
                        onClick={createTerminal}
                        className="mt-3 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
                      >
                        Open Terminal
                      </button>
                    </div>
                  ) : (
                    <>
                      {terminalTabs.map((tab) => (
                        <div
                          key={tab.id}
                          className={`absolute inset-0 ${
                            activeTerminalId === tab.id ? 'block' : 'hidden'
                          }`}
                        >
                          {currentSession && (
                            <OptimizedVibeTerminal
                              sessionId={currentSession.session_id}
                              instanceId={tab.instanceId}
                              isContainerRunning={currentSession.container_status === 'running'}
                              autoConnect={true}
                              className="h-full"
                            />
                          )}
                        </div>
                      ))}
                    </>
                  )}
                </div>
                  </>
                ) : (
                  /* Code Output Area */
                  <div className="flex-1 bg-gray-900 p-4 overflow-auto">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-medium text-gray-300">Code Output</h3>
                      <button
                        onClick={() => setCodeOutput('')}
                        className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700"
                      >
                        Clear
                      </button>
                    </div>
                    <div className="bg-black rounded p-3 font-mono text-sm text-green-400 min-h-[200px] whitespace-pre-wrap">
                      {codeOutput || 'No output yet. Run some code to see results here.'}
                      {console.log('🔍 Current codeOutput:', codeOutput)}
                    </div>
                  </div>
                )}
              </div>
            </ResizablePanel>
          )}
        </div>
      </div>
      {/* End of main flex container */}

      {/* Status Bar */}
      <StatusBar
        sessionName={currentSession?.name}
        sessionId={currentSession?.session_id}
        containerStatus={currentSession?.container_status}
        selectedFileName={activeTabId ? editorTabs.find(t => t.id === activeTabId)?.name : undefined}
        selectedFilePath={activeTabId ? editorTabs.find(t => t.id === activeTabId)?.path : undefined}
        cursorPosition={cursorPosition}
        isDirty={activeTabId ? editorTabs.find(t => t.id === activeTabId)?.isDirty : false}
        language={activeTabId ? editorTabs.find(t => t.id === activeTabId)?.language : undefined}
        theme={preferences?.theme || 'dark'}
        fontSize={preferences?.font_size || 14}
        showLeftPanel={showLeftPanel}
        showTerminal={showTerminal}
        onCommandPaletteClick={handleCommandPaletteClick}
        onThemeToggle={handleThemeToggle}
        onSettingsClick={handleSettingsClick}
        onToggleLeftPanel={toggleLeftPanel}
        onToggleTerminal={toggleTerminal}
      />

      {/* Command Palette */}
      <CommandPalette
        isOpen={showCommandPalette}
        onClose={() => setShowCommandPalette(false)}
        commands={commands}
      />

      {/* Session Creation Loading Overlay */}
      {isCreatingSession && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <div className="flex items-center justify-center mb-4">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
            <h3 className="text-lg font-semibold text-white text-center mb-2">
              Creating Session...
            </h3>
            <p className="text-gray-300 text-center text-sm">
              Please wait while we set up your development environment
            </p>
          </div>
        </div>
      )}

      {/* Session Creation Success/Error Messages */}
      {(sessionCreationSuccess || sessionCreationError) && (
        <div className="fixed top-4 right-4 z-50 max-w-md">
          {sessionCreationSuccess && (
            <div className="bg-green-900/20 border border-green-500/30 rounded-md p-4 mb-2">
              <div className="flex items-center">
                <div className="w-4 h-4 bg-green-400 rounded-full mr-3 animate-pulse" />
                <span className="text-green-300 text-sm">{sessionCreationSuccess}</span>
              </div>
            </div>
          )}
          {sessionCreationError && (
            <div className="bg-red-900/20 border border-red-500/30 rounded-md p-4">
              <div className="flex items-center">
                <X className="w-4 h-4 text-red-400 mr-3" />
                <span className="text-red-300 text-sm">{sessionCreationError}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Session Manager Modal */}
      {showSessionManager && user && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] overflow-hidden">
            <VibeSessionManager
              currentSessionId={currentSession?.session_id || null}
              onSessionSelect={handleSessionSelect}
              onSessionCreate={handleSessionCreate}
              onSessionDelete={handleSessionDelete}
              userId={Number(user.id)}
              isCreatingSession={isCreatingSession}
              sessionCreationError={sessionCreationError}
              sessionCreationSuccess={sessionCreationSuccess}
              className="h-full"
            />
          </div>
        </div>
      )}
      </div>
    </ToastProvider>
  )
}
