"use client"

import React, { useState, useRef, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ArrowLeft,
  Play,
  Pause,
  Code,
  Plus,
  X,
  Settings,
  Sparkles,
  Loader2,
  Folder,
  Container,
  Monitor,
  Activity,
  Moon,
  Sun
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useUser } from "@/lib/auth/UserProvider"
import SettingsModal from "@/components/SettingsModal"
import Aurora from "@/components/Aurora"
import dynamic from "next/dynamic"
import VibeModelSelector from "@/components/VibeModelSelector"
import VibeSessionManager from "@/components/VibeSessionManager"
import MonacoVibeFileTree from "@/components/MonacoVibeFileTree"
import VibeContainerCodeEditor from "@/components/VibeContainerCodeEditor"
import CodeExecutionPanel from "@/components/CodeExecutionPanel"
import AIAssistantPanel from "@/components/AIAssistantPanel"
import ResizablePanel from "@/components/ResizablePanel"
import RightTabsPanel from "@/components/RightTabsPanel"
import { useUserPreferences, getPreferencesWithDefaults } from "@/lib/useUserPreferences"

// Import VibeTerminal dynamically to avoid SSR issues with xterm.js
const VibeTerminal = dynamic(() => import("@/components/VibeTerminal"), {
  ssr: false,
  loading: () => (
    <div className="h-full bg-gray-900 border border-gray-700 rounded-lg flex items-center justify-center">
      <div className="text-gray-400">Loading terminal...</div>
    </div>
  )
})

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  type?: "voice" | "text" | "code" | "command"
  reasoning?: string
}

interface Session {
  id: string
  session_id: string
  project_name: string
  description?: string
  container_status: 'running' | 'stopped' | 'starting' | 'stopping'
  created_at: string
  updated_at: string
  last_activity: string
  file_count: number
  activity_status: 'active' | 'recent' | 'inactive'
}

interface ContainerFile {
  name: string
  type: 'file' | 'directory'
  size: number
  permissions: string
  path: string
}

interface ExecutionResult {
  stdout: string
  stderr: string
  exit_code: number
  started_at: number
  finished_at: number
  command: string
}

export default function VibeCodePage() {
  const { user, isLoading: userLoading } = useUser()
  const router = useRouter()

  // Core state
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [isContainerRunning, setIsContainerRunning] = useState(false)
  const [selectedFile, setSelectedFile] = useState<ContainerFile | null>(null)
  const [isLoadingSession, setIsLoadingSession] = useState(true)
  const [selectedModel, setSelectedModel] = useState<string>('mistral')
  const [selectedAgent, setSelectedAgent] = useState<'assistant' | 'vibe'>('vibe')
  const [showSessionPicker, setShowSessionPicker] = useState(false)

  // Chat and AI state (AI Assistant tab only)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [isAIProcessing, setIsAIProcessing] = useState(false)
  const [availableModels, setAvailableModels] = useState<Array<{ name: string; provider: string; type: string }>>([])

  // Code Execution state (separate from chat)
  const [executionHistory, setExecutionHistory] = useState<ExecutionResult[]>([])
  const [isExecuting, setIsExecuting] = useState(false)

  // UI state
  const [showSettings, setShowSettings] = useState(false)

  // User preferences hook
  const { preferences, isLoading: prefsLoading, updatePreferences } = useUserPreferences()
  const prefs = getPreferencesWithDefaults(preferences)

  // UI state - Panel sizes (initialized from preferences)
  const [activeRightTab, setActiveRightTab] = useState<'assistant' | 'execution'>('assistant')
  const [leftPanelWidth, setLeftPanelWidth] = useState(prefs.left_panel_width)
  const [rightPanelWidth, setRightPanelWidth] = useState(prefs.right_panel_width)
  const [terminalHeight, setTerminalHeight] = useState(prefs.terminal_height)
  const [currentTheme, setCurrentTheme] = useState<'light' | 'dark'>(prefs.theme)

  // Authentication guard
  useEffect(() => {
    if (!userLoading && !user) {
      router.push('/login')
      return
    }
    if (user) {
      setIsLoadingSession(false)
      // Show session picker on entry (as per masterprompt spec)
      setShowSessionPicker(true)
      // Fetch available AI models
      fetchAvailableModels()
    }
  }, [user, userLoading, router])

  // Apply preferences when loaded (Task 16.1)
  useEffect(() => {
    if (!prefsLoading && preferences) {
      // Apply panel sizes
      setLeftPanelWidth(preferences.left_panel_width)
      setRightPanelWidth(preferences.right_panel_width)
      setTerminalHeight(preferences.terminal_height)
      
      // Apply default model
      setSelectedModel(preferences.default_model)
      
      // Apply theme
      setCurrentTheme(preferences.theme)
      if (preferences.theme === 'light') {
        document.documentElement.classList.remove('dark')
      } else {
        document.documentElement.classList.add('dark')
      }
      
      // Apply font size to editor and terminal (via CSS variable)
      document.documentElement.style.setProperty('--vibe-font-size', `${preferences.font_size}px`)
    }
  }, [preferences, prefsLoading])

  // Handler for panel resize with preference saving (Task 16.2)
  const handleLeftPanelResize = useCallback((width: number) => {
    setLeftPanelWidth(width)
    updatePreferences({ left_panel_width: width })
  }, [updatePreferences])

  const handleRightPanelResize = useCallback((width: number) => {
    setRightPanelWidth(width)
    updatePreferences({ right_panel_width: width })
  }, [updatePreferences])

  const handleTerminalResize = useCallback((height: number) => {
    setTerminalHeight(height)
    updatePreferences({ terminal_height: height })
  }, [updatePreferences])

  // Handler for model change with preference saving (Task 16.2)
  const handleModelChange = useCallback((model: string) => {
    setSelectedModel(model)
    updatePreferences({ default_model: model })
  }, [updatePreferences])

  // Handler for theme toggle with preference saving (Task 16.2)
  const handleThemeToggle = useCallback(() => {
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark'
    setCurrentTheme(newTheme)
    
    if (newTheme === 'light') {
      document.documentElement.classList.remove('dark')
    } else {
      document.documentElement.classList.add('dark')
    }
    
    updatePreferences({ theme: newTheme })
  }, [currentTheme, updatePreferences])

  // Fetch available AI models
  const fetchAvailableModels = async () => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/vibecode/ai/models', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (response.ok) {
        const data = await response.json()
        setAvailableModels(data.models || [])
      }
    } catch (error) {
      console.error('Failed to fetch AI models:', error)
      // Set default model if fetch fails
      setAvailableModels([{ name: 'mistral', provider: 'ollama', type: 'local' }])
    }
  }

  // Periodic container status check (real-time updates)
  useEffect(() => {
    if (!currentSession) return

    // Check status immediately
    checkContainerStatus(currentSession.session_id)

    // Then check every 5 seconds
    const interval = setInterval(() => {
      checkContainerStatus(currentSession.session_id)
    }, 5000)

    return () => clearInterval(interval)
  }, [currentSession?.session_id])

  // Session Management
  const handleSessionSelect = async (session: Session) => {
    setCurrentSession(session)
    setIsContainerRunning(session.container_status === 'running')
    setSelectedFile(null)
    setShowSessionPicker(false)

    // Load welcome message for this session (AI Assistant only)
    setChatMessages([{
      role: "assistant",
      content: `Welcome to ${session.project_name}! 🚀 Your development container is ${session.container_status}. Ready to code together?`,
      timestamp: new Date(),
      type: "text",
    }])

    // Check container status
    await checkContainerStatus(session.session_id)
  }

  const handleSessionCreate = async (projectName: string, description?: string): Promise<Session> => {
    try {
      const token = localStorage.getItem('token')
      if (!token) throw new Error('No authentication token')

      // Use new /api/vibecode endpoint structure
      const response = await fetch('/api/vibecode/sessions/create', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: projectName,
          template: 'base',
          description: description || ''
        })
      })

      if (!response.ok) {
        const errorText = await response.text()
        console.error('Session creation failed:', response.status, errorText)
        throw new Error(`Failed to create session: ${response.status} ${errorText}`)
      }

      const data = await response.json()
      console.log('Session creation response:', data)

      const session: Session = {
        id: data.session_id,
        session_id: data.session_id,
        project_name: projectName,
        description: description,
        container_status: 'running',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        last_activity: new Date().toISOString(),
        file_count: 0,
        activity_status: 'active'
      }

      return session
    } catch (error) {
      console.error('Failed to create session:', error)
      throw error
    }
  }

  const handleSessionDelete = async (sessionId: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      await fetch('/api/vibecode/sessions/delete', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          force: false // Soft delete by default
        })
      })

      if (currentSession?.session_id === sessionId) {
        setCurrentSession(null)
        setIsContainerRunning(false)
        setSelectedFile(null)
        setChatMessages([])
        setExecutionHistory([])
        setShowSessionPicker(true)
      }
    } catch (error) {
      console.error('Failed to delete session:', error)
    }
  }

  // Container Management
  const checkContainerStatus = async (sessionId: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch(`/api/vibecode/container/${sessionId}/status`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (response.ok) {
        const data = await response.json()
        setIsContainerRunning(data.status === 'running')

        if (currentSession) {
          setCurrentSession(prev => prev ? {
            ...prev,
            container_status: data.status
          } : null)
        }
      }
    } catch (error) {
      console.error('Failed to check container status:', error)
    }
  }

  const handleContainerStart = async () => {
    if (!currentSession) return

    try {
      const token = localStorage.getItem('token')
      if (!token) return

      setCurrentSession(prev => prev ? { ...prev, container_status: 'starting' } : null)

      const response = await fetch('/api/vibecode/sessions/open', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id
        })
      })

      if (response.ok) {
        setIsContainerRunning(true)
        setCurrentSession(prev => prev ? { ...prev, container_status: 'running' } : null)

        // Add system message
        setChatMessages(prev => [...prev, {
          role: "assistant",
          content: "🎉 Development container is now running! You can start coding and using the terminal.",
          timestamp: new Date(),
          type: "text",
        }])
      } else {
        setCurrentSession(prev => prev ? { ...prev, container_status: 'stopped' } : null)
      }
    } catch (error) {
      console.error('Failed to start container:', error)
      setCurrentSession(prev => prev ? { ...prev, container_status: 'stopped' } : null)
    }
  }

  const handleContainerStop = async () => {
    if (!currentSession) return

    try {
      const token = localStorage.getItem('token')
      if (!token) return

      setCurrentSession(prev => prev ? { ...prev, container_status: 'stopping' } : null)

      const response = await fetch('/api/vibecode/sessions/suspend', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id
        })
      })

      if (response.ok) {
        setIsContainerRunning(false)
        setCurrentSession(prev => prev ? { ...prev, container_status: 'stopped' } : null)

        // Add system message
        setChatMessages(prev => [...prev, {
          role: "assistant",
          content: "Container has been stopped. Files are saved in persistent storage.",
          timestamp: new Date(),
          type: "text",
        }])
      }
    } catch (error) {
      console.error('Failed to stop container:', error)
    }
  }

  // File Management
  const handleFileSelect = (filePath: string, content: string) => {
    setSelectedFile({
      name: filePath.split('/').pop() || '',
      type: 'file',
      size: content.length,
      permissions: '',
      path: filePath
    })
  }

  const handleFileContentChange = (filePath: string, content: string) => {
    console.log('📄 File content changed:', filePath)
  }

  const handleFileExecute = async (filePath: string) => {
    if (!currentSession || !isContainerRunning) return

    setIsExecuting(true)
    // Switch to Execution tab when running file (Task 13.3 requirement)
    setActiveRightTab('execution')

    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const fileExt = filePath.split('.').pop()?.toLowerCase()
      let lang = 'bash'

      if (fileExt === 'py') lang = 'python'
      else if (fileExt === 'js') lang = 'node'

      const response = await fetch('/api/vibecode/exec', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          file: filePath.replace('/workspace/', ''),
          lang: lang
        })
      })

      if (response.ok) {
        const result = await response.json()
        setExecutionHistory(prev => [...prev, result])
      }
    } catch (error) {
      console.error('Execution failed:', error)
    } finally {
      setIsExecuting(false)
    }
  }

  // Code Execution (separate from AI chat)
  const handleExecuteCommand = async (command: string) => {
    if (!command.trim() || !currentSession || !isContainerRunning || isExecuting) return

    setIsExecuting(true)

    try {
      const token = localStorage.getItem('token')
      if (!token) return

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

      if (response.ok) {
        const result = await response.json()
        setExecutionHistory(prev => [...prev, result])
      }
    } catch (error) {
      console.error('Command execution failed:', error)
    } finally {
      setIsExecuting(false)
    }
  }



  // AI Chat (AI Assistant tab only) - Updated to use /api/vibecode/ai/chat
  const sendVibeCommand = async (message: string) => {
    if (!message.trim() || isAIProcessing || !currentSession) return

    const userMessage: ChatMessage = {
      role: "user",
      content: message,
      timestamp: new Date(),
      type: "text",
    }

    setChatMessages((prev) => [...prev, userMessage])
    setIsAIProcessing(true)

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      const response = await fetch("/api/vibecode/ai/chat", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          session_id: currentSession.session_id,
          model: selectedModel,
          history: chatMessages.slice(-10),
          context: {
            container_status: currentSession.container_status,
            selected_file: selectedFile?.name || null
          }
        }),
      })

      if (response.ok) {
        const data = await response.json()

        const aiMessage: ChatMessage = {
          role: "assistant",
          content: data.content || "I'm here to help you with coding!",
          timestamp: new Date(),
          type: "text",
          reasoning: data.reasoning
        }
        setChatMessages((prev) => [...prev, aiMessage])
      } else {
        throw new Error(`AI request failed: ${response.status}`)
      }
    } catch (error) {
      console.error("AI chat error:", error)
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again.",
        timestamp: new Date(),
        type: "text",
      }
      setChatMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsAIProcessing(false)
    }
  }

  // Loading state
  if (userLoading || isLoadingSession) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-purple-400 mx-auto mb-4" />
          <p className="text-gray-400">Loading VibeCode environment...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return null
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#8B5CF6', '#10B981', '#3B82F6']}
          blend={0.3}
          amplitude={0.8}
          speed={0.4}
        />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Session Picker Modal (as per masterprompt spec) */}
      <AnimatePresence>
        {showSessionPicker && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-4xl max-h-[80vh] overflow-hidden"
            >
              <VibeSessionManager
                currentSessionId={currentSession?.session_id || null}
                onSessionSelect={handleSessionSelect}
                onSessionCreate={handleSessionCreate}
                onSessionDelete={handleSessionDelete}
                userId={Number(user.id)}
                className="h-full"
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm flex flex-col">
        <div className="container mx-auto px-4 py-6 flex-1 flex flex-col">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center justify-between mb-6 flex-shrink-0"
          >
            <div className="flex items-center space-x-4">
              <Link href="/">
                <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Dashboard
                </Button>
              </Link>
              <div className="flex items-center space-x-2">
                <Code className="w-6 h-6 text-purple-400" />
                <h1 className="text-3xl font-bold text-white">VibeCode</h1>
              </div>

              {/* Session Info */}
              <div className="flex items-center space-x-2">
                <Button
                  onClick={() => setShowSessionPicker(true)}
                  variant="outline"
                  className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
                >
                  <Container className="w-4 h-4 mr-2" />
                  {currentSession ? currentSession.project_name : 'Select Session'}
                </Button>

                {currentSession && (
                  <>
                    <Badge
                      variant="outline"
                      className={`${
                        currentSession.container_status === 'running'
                          ? 'border-green-500 text-green-400'
                          : currentSession.container_status === 'starting'
                          ? 'border-yellow-500 text-yellow-400'
                          : currentSession.container_status === 'stopping'
                          ? 'border-orange-500 text-orange-400'
                          : 'border-red-500 text-red-400'
                      }`}
                    >
                      <Monitor className="w-3 h-3 mr-1" />
                      {currentSession.container_status}
                    </Badge>

                    {/* Container Control Buttons */}
                    {currentSession.container_status === 'stopped' ? (
                      <Button
                        onClick={handleContainerStart}
                        size="sm"
                        className="bg-green-600 hover:bg-green-700 text-white"
                      >
                        <Play className="w-3 h-3 mr-1" />
                        Start
                      </Button>
                    ) : currentSession.container_status === 'running' ? (
                      <Button
                        onClick={handleContainerStop}
                        size="sm"
                        variant="outline"
                        className="border-orange-500 text-orange-400 hover:bg-orange-500/20"
                      >
                        <Pause className="w-3 h-3 mr-1" />
                        Stop
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        disabled
                        variant="outline"
                        className="border-gray-600 text-gray-500"
                      >
                        <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        {currentSession.container_status}
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>

            <div className="flex items-center space-x-4">
              {/* Model Selector */}
              <div className="hidden md:block">
                <VibeModelSelector
                  selectedModel={selectedModel}
                  selectedAgent={selectedAgent}
                  onModelChange={handleModelChange}
                  onAgentChange={setSelectedAgent}
                  className="w-64"
                />
              </div>

              {/* Theme Toggle */}
              <Button
                onClick={handleThemeToggle}
                variant="outline"
                size="sm"
                className="bg-gray-800 border-gray-600 text-gray-300"
                title={`Switch to ${currentTheme === 'dark' ? 'light' : 'dark'} mode`}
              >
                {currentTheme === 'dark' ? (
                  <Sun className="w-4 h-4" />
                ) : (
                  <Moon className="w-4 h-4" />
                )}
              </Button>

              <Button
                onClick={() => setShowSettings(true)}
                variant="outline"
                size="sm"
                className="bg-gray-800 border-gray-600 text-gray-300"
              >
                <Settings className="w-4 h-4 mr-2" />
                Settings
              </Button>
            </div>
          </motion.div>

          {/* Main Content */}
          {!currentSession ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center max-w-md">
                <Container className="w-16 h-16 text-gray-600 mx-auto mb-6" />
                <h3 className="text-2xl font-semibold text-white mb-4">Welcome to VibeCode</h3>
                <p className="text-gray-400 mb-6">
                  AI-powered development environment with isolated containers for each project.
                </p>

                {/* Quick Start Actions */}
                <div className="space-y-3 mb-8">
                  <Button
                    onClick={() => setShowSessionPicker(true)}
                    className="w-full bg-purple-600 hover:bg-purple-700 text-white py-3"
                  >
                    <Plus className="w-5 h-5 mr-2" />
                    Create New Session
                  </Button>
                  <Button
                    onClick={() => setShowSessionPicker(true)}
                    variant="outline"
                    className="w-full bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700 py-3"
                  >
                    <Folder className="w-5 h-5 mr-2" />
                    Open Existing Session
                  </Button>
                </div>

                {/* Features Overview */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                  <div className="bg-gray-800/50 p-4 rounded-lg">
                    <Terminal className="w-6 h-6 text-green-400 mx-auto mb-2" />
                    <p className="text-gray-300 font-medium">Interactive Terminal</p>
                    <p className="text-gray-500">Full shell access</p>
                  </div>
                  <div className="bg-gray-800/50 p-4 rounded-lg">
                    <Code className="w-6 h-6 text-blue-400 mx-auto mb-2" />
                    <p className="text-gray-300 font-medium">Code Editor</p>
                    <p className="text-gray-500">Syntax highlighting</p>
                  </div>
                  <div className="bg-gray-800/50 p-4 rounded-lg">
                    <Sparkles className="w-6 h-6 text-purple-400 mx-auto mb-2" />
                    <p className="text-gray-300 font-medium">AI Assistant</p>
                    <p className="text-gray-500">Code with AI help</p>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // VSCode-like 3-Column Layout with Resizable Panels
            <div className="flex flex-1 min-h-0 gap-4">
              {/* Left Panel: File Explorer (Resizable 200-500px) */}
              <ResizablePanel
                width={leftPanelWidth}
                onResize={handleLeftPanelResize}
                minWidth={200}
                maxWidth={500}
                direction="horizontal"
                handlePosition="right"
              >
                <MonacoVibeFileTree
                  sessionId={currentSession.session_id}
                  onFileSelect={handleFileSelect}
                  onFileContentChange={handleFileContentChange}
                  className="h-full"
                />
              </ResizablePanel>

              {/* Center Panel: Code Editor + Terminal */}
              <div className="flex-1 min-w-0 flex flex-col gap-4">
                {/* Code Editor (takes remaining space) */}
                <div className="flex-1 min-h-0">
                  <VibeContainerCodeEditor
                    sessionId={currentSession.session_id}
                    selectedFile={selectedFile}
                    onExecute={handleFileExecute}
                    className="h-full"
                  />
                </div>
                
                {/* Terminal (Resizable 100-600px height) */}
                <ResizablePanel
                  height={terminalHeight}
                  onResize={handleTerminalResize}
                  minHeight={100}
                  maxHeight={600}
                  direction="vertical"
                  handlePosition="top"
                  className="flex-shrink-0"
                >
                  <VibeTerminal
                    sessionId={currentSession.session_id}
                    isContainerRunning={isContainerRunning}
                    onContainerStart={handleContainerStart}
                    className="h-full"
                  />
                </ResizablePanel>
              </div>

              {/* Right Panel: Tabs (AI Assistant + Code Execution) (Resizable 300-600px) */}
              <ResizablePanel
                width={rightPanelWidth}
                onResize={handleRightPanelResize}
                minWidth={300}
                maxWidth={600}
                direction="horizontal"
                handlePosition="left"
              >
                <RightTabsPanel
                  activeTab={activeRightTab}
                  onTabChange={setActiveRightTab}
                  sessionId={currentSession?.session_id || null}
                  containerStatus={currentSession?.container_status}
                  selectedFile={selectedFile?.name || null}
                  isContainerRunning={isContainerRunning}
                  chatMessages={chatMessages}
                  isAIProcessing={isAIProcessing}
                  selectedModel={selectedModel}
                  availableModels={availableModels}
                  onSendMessage={sendVibeCommand}
                  onModelChange={handleModelChange}
                  executionHistory={executionHistory}
                  isExecuting={isExecuting}
                  onExecute={handleExecuteCommand}
                  className="h-full"
                />
              </ResizablePanel>
            </div>
          )}
        </div>

        {/* Settings Modal */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
              >
                <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

// Terminal icon component for welcome screen
const Terminal = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
  </svg>
)