"use client"

import React, { useState, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ArrowLeft,
  Play,
  Save,
  FileText,
  Terminal,
  Mic,
  MicOff,
  Code,
  Zap,
  Volume2,
  VolumeX,
  Plus,
  X,
  Settings,
  Sparkles,
  Loader2,
  Download,
  Folder,
  Container,
  Monitor,
  RefreshCw
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
import VibeModelSelector from "@/components/VibeModelSelector"
import VibeSessionManager from "@/components/VibeSessionManager"
import MonacoVibeFileTree from "@/components/MonacoVibeFileTree"
import OptimizedVibeTerminal from "@/components/OptimizedVibeTerminal"
import VibeContainerCodeEditor from "@/components/VibeContainerCodeEditor"

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

export default function VibeCodingPage() {
  const { user, isLoading: userLoading } = useUser()
  const router = useRouter()
  
  // Core state
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [isContainerRunning, setIsContainerRunning] = useState(false)
  const [selectedFile, setSelectedFile] = useState<ContainerFile | null>(null)
  const [isLoadingSession, setIsLoadingSession] = useState(true)
  const [selectedModel, setSelectedModel] = useState<string>('mistral')
  const [selectedAgent, setSelectedAgent] = useState<'assistant' | 'vibe'>('vibe')
  const [showSessionManager, setShowSessionManager] = useState(false)

  // Chat and AI state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [isAIProcessing, setIsAIProcessing] = useState(false)

  // Voice features
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessingVoice, setIsProcessingVoice] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  // UI state
  const [activeTab, setActiveTab] = useState<'files' | 'chat'>('files')
  const [terminalHeight, setTerminalHeight] = useState(200) // Terminal height in pixels
  
  // Refs
  const chatEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  // Authentication guard
  useEffect(() => {
    if (!userLoading && !user) {
      router.push('/login')
      return
    }
    if (user) {
      setIsLoadingSession(false)
    }
  }, [user, userLoading, router])

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatMessages])

  // Session Management
  const handleSessionSelect = async (session: Session) => {
    setCurrentSession(session)
    setIsContainerRunning(session.container_status === 'running')
    setSelectedFile(null)
    setShowSessionManager(false)
    
    // Load welcome message for this session
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

      const response = await fetch('/api/vibecoding/sessions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          project_name: projectName,
          description: description || ''
        })
      })

      if (!response.ok) throw new Error('Failed to create session')

      const data = await response.json()
      
      const session: Session = {
        id: data.id,
        session_id: data.session_id,
        project_name: projectName,
        description: description,
        container_status: 'stopped',
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

      // Stop container first
      await fetch('/api/vibecoding/container', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          action: 'stop'
        })
      })

      if (currentSession?.session_id === sessionId) {
        setCurrentSession(null)
        setIsContainerRunning(false)
        setSelectedFile(null)
        setChatMessages([])
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

      const response = await fetch('/api/vibecoding/container', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: sessionId,
          action: 'status'
        })
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

      const response = await fetch('/api/vibecoding/container', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          action: 'create'
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

      const response = await fetch('/api/vibecoding/container', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          session_id: currentSession.session_id,
          action: 'stop'
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
    setActiveTab('files')
  }

  const handleFileContentChange = (filePath: string, content: string) => {
    // Handle real-time file changes from the file system watcher
    console.log('📄 File content changed:', filePath)
  }

  const handleFileExecute = (filePath: string) => {
    setChatMessages(prev => [...prev, {
      role: "assistant",
      content: `Executing ${filePath}... Check the terminal for output! 🚀`,
      timestamp: new Date(),
      type: "code",
    }])
  }

  // Voice recording functions
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" })
        await processVoiceCommand(audioBlob)
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
    } catch (error) {
      console.error("Error accessing microphone:", error)
      alert("Unable to access microphone. Please check permissions.")
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      setIsProcessingVoice(true)
    }
  }

  const processVoiceCommand = async (audioBlob: Blob) => {
    try {
      const formData = new FormData()
      formData.append("file", audioBlob, "vibe-command.wav")
      formData.append("model", selectedModel)

      const response = await fetch("/api/voice-transcribe", {
        method: "POST",
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        if (data.transcription) {
          setChatInput(data.transcription)
          setTimeout(() => {
            sendVibeCommand(data.transcription, "voice")
          }, 500)
        }
      }
    } catch (error) {
      console.error("Voice processing failed:", error)
    } finally {
      setIsProcessingVoice(false)
    }
  }

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const toggleAudio = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
      } else {
        audioRef.current.play()
      }
    }
  }

  // AI Chat
  const sendVibeCommand = async (command?: string, inputType: "text" | "voice" = "text") => {
    const message = command || chatInput
    if (!message.trim() || isAIProcessing) return

    const userMessage: ChatMessage = {
      role: "user",
      content: message,
      timestamp: new Date(),
      type: inputType,
    }

    setChatMessages((prev) => [...prev, userMessage])
    if (inputType === "text") setChatInput("")
    setIsAIProcessing(true)

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          history: chatMessages.slice(-10),
          model: selectedModel,
          context: {
            session: currentSession?.project_name || 'Vibe Coding Session',
            container_running: isContainerRunning,
            selected_file: selectedFile?.name || null
          }
        }),
      })

      if (response.ok) {
        const data = await response.json()

        const aiMessage: ChatMessage = {
          role: "assistant",
          content: data.final_answer || data.response || "I'm here to help you with coding!",
          timestamp: new Date(),
          type: "code",
          reasoning: data.reasoning
        }
        setChatMessages((prev) => [...prev, aiMessage])

        // Play voice response if available
        if (data.audio_path) {
          setAudioUrl(data.audio_path)
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.play().catch(console.warn)
            }
          }, 1000)
        }
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
          <p className="text-gray-400">Loading Vibe Coding environment...</p>
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

      {/* Session Manager Modal */}
      <AnimatePresence>
        {showSessionManager && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={(e) => e.target === e.currentTarget && setShowSessionManager(false)}
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
                <Sparkles className="w-6 h-6 text-purple-400" />
                <h1 className="text-3xl font-bold text-white">Vibe Coding</h1>
              </div>
              
              {/* Session Info */}
              <div className="flex items-center space-x-2">
                <Button
                  onClick={() => setShowSessionManager(true)}
                  variant="outline"
                  className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
                >
                  <Container className="w-4 h-4 mr-2" />
                  {currentSession ? currentSession.project_name : 'Select Session'}
                </Button>
                
                {currentSession && (
                  <Badge 
                    variant="outline" 
                    className={`${
                      isContainerRunning 
                        ? 'border-green-500 text-green-400' 
                        : 'border-red-500 text-red-400'
                    }`}
                  >
                    <Monitor className="w-3 h-3 mr-1" />
                    {currentSession.container_status}
                  </Badge>
                )}
              </div>
            </div>
            
            <div className="flex items-center space-x-4">
              {/* Model Selector */}
              <div className="hidden md:block">
                <VibeModelSelector
                  selectedModel={selectedModel}
                  selectedAgent={selectedAgent}
                  onModelChange={setSelectedModel}
                  onAgentChange={setSelectedAgent}
                  className="w-64"
                />
              </div>
              
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
                <h3 className="text-2xl font-semibold text-white mb-4">Welcome to Vibe Coding</h3>
                <p className="text-gray-400 mb-6">
                  AI-powered development environment with isolated containers for each project.
                </p>
                
                {/* Quick Start Actions */}
                <div className="space-y-3 mb-8">
                  <Button
                    onClick={() => setShowSessionManager(true)}
                    className="w-full bg-purple-600 hover:bg-purple-700 text-white py-3"
                  >
                    <Plus className="w-5 h-5 mr-2" />
                    Create New Project
                  </Button>
                  <Button
                    onClick={() => setShowSessionManager(true)}
                    variant="outline"
                    className="w-full bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700 py-3"
                  >
                    <Folder className="w-5 h-5 mr-2" />
                    Open Existing Project
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
            <div className="flex flex-col flex-1 min-h-0">
              {/* Mobile: Show stacked layout */}
              <div className="lg:hidden space-y-4 overflow-y-auto">
                {/* Mobile Model Selector */}
                <VibeModelSelector
                  selectedModel={selectedModel}
                  selectedAgent={selectedAgent}
                  onModelChange={setSelectedModel}
                  onAgentChange={setSelectedAgent}
                  className="h-auto"
                />

                {/* Mobile Navigation */}
                <div className="flex space-x-2 mb-4">
                  <Button
                    onClick={() => setActiveTab('files')}
                    size="sm"
                    className={`flex-1 ${activeTab === 'files' 
                      ? 'bg-blue-600 text-white shadow-lg' 
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-600'
                    }`}
                  >
                    <Code className="w-4 h-4 mr-2" />
                    Code Editor
                  </Button>
                  <Button
                    onClick={() => setActiveTab('chat')}
                    size="sm"
                    className={`flex-1 ${activeTab === 'chat' 
                      ? 'bg-purple-600 text-white shadow-lg' 
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-600'
                    }`}
                  >
                    <Sparkles className="w-4 h-4 mr-2" />
                    AI Assistant
                  </Button>
                </div>

                {activeTab === 'files' ? (
                  <div className="space-y-4">
                    {/* File Explorer */}
                    <div className="h-64">
                      <MonacoVibeFileTree
                        sessionId={currentSession.session_id}
                        onFileSelect={handleFileSelect}
                        onFileContentChange={handleFileContentChange}
                        className="h-full"
                      />
                    </div>
                    
                    {/* Code Editor */}
                    <div className="h-96">
                      <VibeContainerCodeEditor
                        sessionId={currentSession.session_id}
                        selectedFile={selectedFile}
                        onExecute={handleFileExecute}
                        className="h-full"
                      />
                    </div>
                    
                    {/* Terminal */}
                    <div className="h-64">
                      <OptimizedVibeTerminal
                        sessionId={currentSession.session_id}
                        isContainerRunning={isContainerRunning}
                        onContainerStart={handleContainerStart}
                        onContainerStop={handleContainerStop}
                        className="h-full"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="h-96">
                    <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-full flex flex-col">
                      <div className="p-4 border-b border-purple-500/30">
                        <div className="flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-purple-300">AI Assistant</h3>
                          <div className="flex items-center space-x-2">
                            <Button
                              onClick={toggleRecording}
                              disabled={isProcessingVoice}
                              size="sm"
                              className={`${
                                isRecording ? "bg-red-600 hover:bg-red-700 animate-pulse" : "bg-purple-600 hover:bg-purple-700"
                              } text-white`}
                            >
                              {isRecording ? <MicOff className="w-3 h-3" /> : <Mic className="w-3 h-3" />}
                            </Button>
                            {audioUrl && (
                              <Button
                                onClick={toggleAudio}
                                size="sm"
                                variant="outline"
                                className="bg-gray-800 border-gray-600 text-gray-300"
                              >
                                {isPlaying ? <VolumeX className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                      
                      <div className="flex-1 overflow-y-auto p-4 space-y-3">
                        <AnimatePresence>
                          {chatMessages.map((message, index) => (
                            <motion.div
                              key={index}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                            >
                              <div
                                className={`max-w-[90%] p-2 rounded text-sm ${
                                  message.role === "user" ? "bg-purple-600 text-white" : "bg-gray-700 text-gray-100"
                                }`}
                              >
                                <div className="flex items-center space-x-2 mb-1">
                                  {message.type === "voice" && <Mic className="w-3 h-3 text-purple-400" />}
                                  {message.type === "code" && <Code className="w-3 h-3 text-green-400" />}
                                  <span className="text-xs opacity-70">{message.timestamp.toLocaleTimeString()}</span>
                                </div>
                                <p>{message.content}</p>
                                {message.reasoning && (
                                  <details className="mt-2 text-xs opacity-75">
                                    <summary className="cursor-pointer">Reasoning</summary>
                                    <p className="mt-1 pl-2 border-l border-purple-400/30">{message.reasoning}</p>
                                  </details>
                                )}
                              </div>
                            </motion.div>
                          ))}
                        </AnimatePresence>
                        
                        {(isAIProcessing || isProcessingVoice) && (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                            <div className="bg-gray-700 p-2 rounded">
                              <div className="flex space-x-1">
                                <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce"></div>
                                <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "0.1s" }}></div>
                                <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                              </div>
                            </div>
                          </motion.div>
                        )}
                        <div ref={chatEndRef} />
                      </div>
                      
                      <div className="p-4 border-t border-purple-500/30">
                        <div className="flex space-x-2">
                          <Input
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            onKeyPress={(e) => e.key === "Enter" && !isAIProcessing && sendVibeCommand()}
                            placeholder="Tell me what to code..."
                            className="flex-1 bg-gray-800 border-gray-600 text-white text-sm"
                            disabled={isAIProcessing || isProcessingVoice}
                          />
                          <Button
                            onClick={() => sendVibeCommand()}
                            disabled={isAIProcessing || !chatInput.trim() || isProcessingVoice}
                            size="sm"
                            className="bg-purple-600 hover:bg-purple-700 text-white"
                          >
                            <Zap className="w-3 h-3" />
                          </Button>
                        </div>
                      </div>
                    </Card>
                  </div>
                )}
              </div>

              {/* Desktop Layout */}
              <div className="hidden lg:flex flex-col flex-1 min-h-0">
                {/* Top Section: Sidebar + Main Content + AI Chat */}
                <div className="flex flex-1 min-h-0 gap-4">
                  {/* Left Sidebar: File Explorer */}
                  <div className="w-80 flex-shrink-0">
                    <MonacoVibeFileTree
                      sessionId={currentSession.session_id}
                      onFileSelect={handleFileSelect}
                      onFileContentChange={handleFileContentChange}
                      className="h-full"
                    />
                  </div>

                  {/* Main Content: Code Editor */}
                  <div className="flex-1 min-w-0">
                    <VibeContainerCodeEditor
                      sessionId={currentSession.session_id}
                      selectedFile={selectedFile}
                      onExecute={handleFileExecute}
                      className="h-full"
                    />
                  </div>

                  {/* Right Sidebar: AI Assistant */}
                  <div className="w-96 flex-shrink-0">
                    <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-full flex flex-col">
                      <div className="p-4 border-b border-purple-500/30 flex-shrink-0">
                        <div className="flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-purple-300">AI Assistant</h3>
                          <div className="flex items-center space-x-2">
                            <Button
                              onClick={toggleRecording}
                              disabled={isProcessingVoice}
                              size="sm"
                              className={`${
                                isRecording ? "bg-red-600 hover:bg-red-700 animate-pulse" : "bg-purple-600 hover:bg-purple-700"
                              } text-white`}
                            >
                              {isRecording ? <MicOff className="w-3 h-3" /> : <Mic className="w-3 h-3" />}
                            </Button>
                            {audioUrl && (
                              <Button
                                onClick={toggleAudio}
                                size="sm"
                                variant="outline"
                                className="bg-gray-800 border-gray-600 text-gray-300"
                              >
                                {isPlaying ? <VolumeX className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
                        <AnimatePresence>
                          {chatMessages.map((message, index) => (
                            <motion.div
                              key={index}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                            >
                              <div
                                className={`max-w-[90%] p-3 rounded-lg text-sm ${
                                  message.role === "user" ? "bg-purple-600 text-white" : "bg-gray-700 text-gray-100"
                                }`}
                              >
                                <div className="flex items-center space-x-2 mb-1">
                                  {message.type === "voice" && <Mic className="w-3 h-3 text-purple-400" />}
                                  {message.type === "code" && <Code className="w-3 h-3 text-green-400" />}
                                  <span className="text-xs opacity-70">{message.timestamp.toLocaleTimeString()}</span>
                                </div>
                                <p className="leading-relaxed">{message.content}</p>
                                {message.reasoning && (
                                  <details className="mt-2 text-xs opacity-75">
                                    <summary className="cursor-pointer hover:text-purple-300">💭 View Reasoning</summary>
                                    <p className="mt-2 pl-3 border-l-2 border-purple-400/30 text-gray-300">{message.reasoning}</p>
                                  </details>
                                )}
                              </div>
                            </motion.div>
                          ))}
                        </AnimatePresence>

                        {(isAIProcessing || isProcessingVoice) && (
                          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                            <div className="bg-gray-700 p-3 rounded-lg">
                              <div className="flex items-center space-x-2 text-gray-400">
                                <div className="flex space-x-1">
                                  <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce"></div>
                                  <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "0.1s" }}></div>
                                  <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                                </div>
                                <span className="text-sm">AI is thinking...</span>
                              </div>
                            </div>
                          </motion.div>
                        )}
                        <div ref={chatEndRef} />
                      </div>

                      <div className="p-4 border-t border-purple-500/30 flex-shrink-0">
                        <div className="flex space-x-2">
                          <Input
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            onKeyPress={(e) => e.key === "Enter" && !isAIProcessing && sendVibeCommand()}
                            placeholder="Ask AI to help with your code..."
                            className="flex-1 bg-gray-800 border-gray-600 text-white"
                            disabled={isAIProcessing || isProcessingVoice}
                          />
                          <Button
                            onClick={() => sendVibeCommand()}
                            disabled={isAIProcessing || !chatInput.trim() || isProcessingVoice}
                            size="sm"
                            className="bg-purple-600 hover:bg-purple-700 text-white px-3"
                          >
                            <Zap className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>

                      {audioUrl && (
                        <audio
                          ref={audioRef}
                          src={audioUrl}
                          onPlay={() => setIsPlaying(true)}
                          onPause={() => setIsPlaying(false)}
                          onEnded={() => setIsPlaying(false)}
                          className="hidden"
                        />
                      )}
                    </Card>
                  </div>
                </div>

                {/* Bottom Section: Development Terminal */}
                <div 
                  className="mt-4 border-t border-gray-700 pt-4"
                  style={{ height: `${terminalHeight}px`, minHeight: '150px', maxHeight: '400px' }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <Terminal className="w-4 h-4 text-green-400" />
                      <h3 className="text-sm font-semibold text-green-300">Development Terminal</h3>
                      <Badge 
                        variant="outline" 
                        className={`text-xs ${
                          isContainerRunning 
                            ? 'border-green-500 text-green-400' 
                            : 'border-red-500 text-red-400'
                        }`}
                      >
                        {isContainerRunning ? 'Running' : 'Stopped'}
                      </Badge>
                    </div>
                    
                    <div className="flex items-center space-x-2">
                      {!isContainerRunning ? (
                        <Button
                          onClick={handleContainerStart}
                          size="sm"
                          className="bg-green-600 hover:bg-green-700 text-white"
                          disabled={currentSession?.container_status === 'starting'}
                        >
                          <Play className="w-3 h-3 mr-1" />
                          {currentSession?.container_status === 'starting' ? 'Starting...' : 'Start Container'}
                        </Button>
                      ) : (
                        <Button
                          onClick={handleContainerStop}
                          size="sm"
                          variant="outline"
                          className="border-red-600 text-red-400 hover:bg-red-600 hover:text-white"
                          disabled={currentSession?.container_status === 'stopping'}
                        >
                          <X className="w-3 h-3 mr-1" />
                          {currentSession?.container_status === 'stopping' ? 'Stopping...' : 'Stop'}
                        </Button>
                      )}
                    </div>
                  </div>
                  
                  <OptimizedVibeTerminal
                    sessionId={currentSession.session_id}
                    isContainerRunning={isContainerRunning}
                    onContainerStart={handleContainerStart}
                    onContainerStop={handleContainerStop}
                    className="h-full"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Settings Modal */}
        <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} context="global" />
      </div>
    </div>
  )
}