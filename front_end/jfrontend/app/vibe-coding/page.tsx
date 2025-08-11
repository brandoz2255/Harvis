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
  Folder
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
import VibeCodeEditor from "@/components/VibeCodeEditor"
import VibeFileTree, { FileTreeNode } from "@/components/VibeFileTree"
import VibeModelSelector from "@/components/VibeModelSelector"
import { useCodeExecution } from "@/hooks/useCodeExecution"

interface VibeFile {
  id: string
  name: string
  content: string
  language: string
  isModified: boolean
  sessionId: string
  path: string
  type: 'file' | 'folder'
  parentId?: string
  size?: number
  createdAt: Date
  updatedAt: Date
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  type?: "voice" | "text" | "code" | "command"
  reasoning?: string
}

interface VibeSession {
  id: string
  name: string
  description?: string
  userId: string
  isActive: boolean
  createdAt: Date
  updatedAt: Date
  fileCount?: number
}

export default function VibeCodingPage() {
  const { user, isLoading: userLoading } = useUser()
  const router = useRouter()
  
  // Core state
  const [currentSession, setCurrentSession] = useState<VibeSession | null>(null)
  const [files, setFiles] = useState<FileTreeNode[]>([])
  const [selectedFile, setSelectedFile] = useState<VibeFile | null>(null)
  const [isLoadingSession, setIsLoadingSession] = useState(true)
  const [selectedModel, setSelectedModel] = useState<string>('mistral')
  const [selectedAgent, setSelectedAgent] = useState<'assistant' | 'vibe'>('vibe')

  // Chat and AI state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState("")
  const [isAIProcessing, setIsAIProcessing] = useState(false)
  const [terminalOutput, setTerminalOutput] = useState<string[]>([
    "Vibe Coding Terminal Ready 🎵",
    "Connected to execution environment",
  ])
  const [codeExecutionOutput, setCodeExecutionOutput] = useState<string[]>([
    "Code execution output will appear here...",
  ])
  const [terminalTab, setTerminalTab] = useState<'terminal' | 'execution'>('terminal')

  // Voice features
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessingVoice, setIsProcessingVoice] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  
  // Code execution
  const { 
    executeCode, 
    isExecuting, 
    output: executionOutput, 
    clearOutput,
    isConnected: executionConnected
  } = useCodeExecution({
    sessionId: currentSession?.id || 'temp',
    onOutput: (output) => {
      setTerminalOutput(prev => [...prev, output])
    },
    onError: (error) => {
      setTerminalOutput(prev => [...prev, `Error: ${error}`])
    }
  })

  // Refs
  const chatEndRef = useRef<HTMLDivElement>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  // Authentication guard
  useEffect(() => {
    if (!userLoading && !user) {
      router.push('/login')
      return
    }
  }, [user, userLoading, router])

  // Initialize session
  useEffect(() => {
    if (user && !currentSession) {
      initializeSession()
    }
  }, [user, currentSession])

  // Auto-scroll effects
  const scrollToBottom = (ref: React.RefObject<HTMLDivElement>) => {
    ref.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom(chatEndRef)
  }, [chatMessages])

  useEffect(() => {
    scrollToBottom(terminalEndRef)
  }, [terminalOutput])

  // Initialize or create default session
  const initializeSession = async () => {
    try {
      setIsLoadingSession(true)
      
      // Get auth token
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }
      
      // First try to get existing sessions
      const sessionsResponse = await fetch('/api/vibe/sessions', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (sessionsResponse.ok) {
        const { sessions } = await sessionsResponse.json()
        
        if (sessions.length > 0) {
          // Load the most recent session
          const latestSession = sessions[0]
          await loadSession(latestSession.id)
        } else {
          // Create a new default session
          await createNewSession()
        }
      } else {
        // Create new session if API fails
        await createNewSession()
      }
    } catch (error) {
      console.error('Failed to initialize session:', error)
      // Create offline session as fallback
      createOfflineSession()
    } finally {
      setIsLoadingSession(false)
    }
  }

  const createNewSession = async () => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      const response = await fetch('/api/vibe/sessions', {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json' 
        },
        body: JSON.stringify({
          name: `Vibe Session ${new Date().toLocaleDateString()}`,
          description: 'A new Vibe Coding session'
        })
      })

      if (response.ok) {
        const { session } = await response.json()
        await loadSession(session.id)
      } else {
        throw new Error('Failed to create session')
      }
    } catch (error) {
      console.error('Error creating session:', error)
      createOfflineSession()
    }
  }

  const createOfflineSession = () => {
    const offlineSession: VibeSession = {
      id: 'offline-' + Date.now(),
      name: 'Offline Session',
      description: 'Local session (backend unavailable)',
      userId: user?.id || 'offline',
      isActive: true,
      createdAt: new Date(),
      updatedAt: new Date()
    }

    const defaultFiles: FileTreeNode[] = [
      {
        id: '1',
        name: 'main.py',
        type: 'file',
        path: 'main.py',
        content: '# Welcome to Vibe Coding!\n# Start by describing what you want to build...\n\nprint("Hello, Vibe Coder!")',
        language: 'python',
        isModified: false,
        createdAt: new Date(),
        updatedAt: new Date()
      },
      {
        id: '2',
        name: 'README.md',
        type: 'file',
        path: 'README.md',
        content: '# Offline Vibe Session\n\nThis is a local session running in offline mode.\nBackend functionality may be limited.',
        language: 'markdown',
        isModified: false,
        createdAt: new Date(),
        updatedAt: new Date()
      }
    ]

    setCurrentSession(offlineSession)
    setFiles(defaultFiles)
    setSelectedFile(convertToVibeFile(defaultFiles[0], offlineSession.id))
    
    setChatMessages([{
      role: "assistant",
      content: "Welcome to Vibe Coding! 🚀 I'm running in offline mode. Tell me what you want to build and I'll help you code it step by step. You can speak or type your requests!",
      timestamp: new Date(),
      type: "text",
    }])
  }

  const loadSession = async (sessionId: string) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      const response = await fetch(`/api/vibe/sessions/${sessionId}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const { session, files: sessionFiles, chat } = await response.json()
        
        setCurrentSession(session)
        
        // Convert files to FileTreeNode format
        const fileNodes: FileTreeNode[] = sessionFiles.map((file: any) => ({
          id: file.id,
          name: file.name,
          type: file.type,
          path: file.path,
          content: file.content,
          language: file.language,
          parentId: file.parent_id,
          isModified: false,
          createdAt: new Date(file.created_at),
          updatedAt: new Date(file.updated_at)
        }))
        
        setFiles(fileNodes)
        
        // Select first file by default
        if (fileNodes.length > 0) {
          const firstFile = fileNodes.find(f => f.type === 'file')
          if (firstFile) {
            setSelectedFile(convertToVibeFile(firstFile, sessionId))
          }
        }
        
        // Load chat history
        if (chat && chat.length > 0) {
          const chatHistory: ChatMessage[] = chat.map((msg: any) => ({
            role: msg.role,
            content: msg.content,
            timestamp: new Date(msg.created_at),
            type: msg.type || 'text',
            reasoning: msg.reasoning
          }))
          setChatMessages(chatHistory)
        } else {
          // Add welcome message
          setChatMessages([{
            role: "assistant",
            content: `Welcome back to ${session.name}! 🚀 Ready to continue coding? Tell me what you want to work on!`,
            timestamp: new Date(),
            type: "text",
          }])
        }
      }
    } catch (error) {
      console.error('Failed to load session:', error)
      createOfflineSession()
    }
  }

  const convertToVibeFile = (node: FileTreeNode, sessionId: string): VibeFile => ({
    id: node.id,
    name: node.name,
    content: node.content || '',
    language: node.language || 'plaintext',
    isModified: node.isModified || false,
    sessionId,
    path: node.path,
    type: node.type,
    parentId: node.parentId,
    size: node.content?.length || 0,
    createdAt: node.createdAt,
    updatedAt: node.updatedAt
  })

  // File operations
  const handleFileSelect = (file: FileTreeNode) => {
    if (file.type === 'file' && currentSession) {
      setSelectedFile(convertToVibeFile(file, currentSession.id))
    }
  }

  const handleFileCreate = async (parentId: string | null, name: string, type: 'file' | 'folder') => {
    if (!currentSession) return

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      // Generate appropriate default content based on file extension
      const getDefaultContent = (filename: string): string => {
        const extension = filename.split('.').pop()?.toLowerCase()
        
        switch (extension) {
          case 'py':
            return '# New Python file\nprint("Hello, World!")\n'
          case 'js':
            return '// New JavaScript file\nconsole.log("Hello, World!");\n'
          case 'ts':
            return '// New TypeScript file\nconsole.log("Hello, World!");\n'
          case 'java':
            return '// New Java file\npublic class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}\n'
          case 'cpp':
          case 'cc':
            return '// New C++ file\n#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << "Hello, World!" << endl;\n    return 0;\n}\n'
          case 'c':
            return '// New C file\n#include <stdio.h>\n\nint main() {\n    printf("Hello, World!\\n");\n    return 0;\n}\n'
          case 'go':
            return '// New Go file\npackage main\n\nimport "fmt"\n\nfunc main() {\n    fmt.Println("Hello, World!")\n}\n'
          case 'rs':
            return '// New Rust file\nfn main() {\n    println!("Hello, World!");\n}\n'
          case 'rb':
            return '# New Ruby file\nputs "Hello, World!"\n'
          case 'php':
            return '<?php\n// New PHP file\necho "Hello, World!";\n?>\n'
          case 'sh':
            return '#!/bin/bash\n# New shell script\necho "Hello, World!"\n'
          case 'html':
            return '<!DOCTYPE html>\n<html>\n<head>\n    <title>New HTML File</title>\n</head>\n<body>\n    <h1>Hello, World!</h1>\n</body>\n</html>\n'
          case 'css':
            return '/* New CSS file */\nbody {\n    font-family: Arial, sans-serif;\n    margin: 0;\n    padding: 20px;\n}\n'
          case 'md':
            return '# New Markdown File\n\nHello, World!\n'
          case 'json':
            return '{\n  "message": "Hello, World!"\n}\n'
          case 'yaml':
          case 'yml':
            return '# New YAML file\nmessage: "Hello, World!"\n'
          case 'txt':
            return 'New text file\n'
          default:
            return '// New file\n'
        }
      }

      const response = await fetch('/api/vibe/files', {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json' 
        },
        body: JSON.stringify({
          sessionId: currentSession.id,
          parentId,
          name,
          type,
          content: type === 'file' ? getDefaultContent(name) : undefined
        })
      })

      if (response.ok) {
        const { file } = await response.json()
        
        // Refresh the entire file tree to show new file
        await refreshFiles()
        
        // If it's a file, select it
        if (type === 'file') {
          const newVibeFile = convertToVibeFile({
            id: file.id,
            name: file.name,
            type: file.type,
            path: file.path,
            content: file.content,
            language: file.language,
            parentId: file.parent_id,
            isModified: false,
            createdAt: new Date(file.created_at),
            updatedAt: new Date(file.updated_at)
          }, currentSession.id)
          
          setSelectedFile(newVibeFile)
        }
        
        addTerminalOutput(`✅ Created ${type}: ${name}`)
      }
    } catch (error) {
      console.error('Failed to create file:', error)
    }
  }

  const handleFileRename = async (fileId: string, newName: string) => {
    try {
      const response = await fetch(`/api/vibe/files/${fileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })

      if (response.ok) {
        await refreshFiles()
        addTerminalOutput(`📝 Renamed to: ${newName}`)
      }
    } catch (error) {
      console.error('Failed to rename file:', error)
    }
  }

  const handleFileDelete = async (fileId: string) => {
    try {
      const response = await fetch(`/api/vibe/files/${fileId}`, {
        method: 'DELETE'
      })

      if (response.ok) {
        await refreshFiles()
        
        if (selectedFile?.id === fileId) {
          setSelectedFile(null)
        }
        
        addTerminalOutput(`🗑️ Deleted file`)
      }
    } catch (error) {
      console.error('Failed to delete file:', error)
    }
  }

  const handleFileMove = async (fileId: string, newParentId: string | null) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        router.push('/login')
        return
      }

      console.log('Moving file:', fileId, 'to parent:', newParentId)
      
      const response = await fetch(`/api/vibe/files/${fileId}/move`, {
        method: 'PUT',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json' 
        },
        body: JSON.stringify({ 
          targetParentId: newParentId 
        })
      })

      if (response.ok) {
        const movedFile = await response.json()
        await refreshFiles()
        addTerminalOutput(`📁 Moved "${movedFile.name}" to ${newParentId ? 'folder' : 'root'}`)
        console.log('File moved successfully:', movedFile)
      } else {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }))
        console.error('Failed to move file:', response.status, errorData)
        addTerminalOutput(`❌ Failed to move file: ${errorData.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to move file:', error)
      addTerminalOutput(`❌ Failed to move file: ${error instanceof Error ? error.message : 'Unknown error'}`)
    }
  }

  const handleDownload = (fileId: string, isFolder: boolean) => {
    const downloadUrl = isFolder 
      ? `/api/vibe/download?fileId=${fileId}&type=folder`
      : `/api/vibe/download?fileId=${fileId}&type=file`
    
    window.open(downloadUrl, '_blank')
  }

  const handleToggleExpanded = (fileId: string) => {
    setFiles(prev => prev.map(file => 
      file.id === fileId ? { ...file, isExpanded: !file.isExpanded } : file
    ))
  }

  // File content changes
  const handleContentChange = (content: string) => {
    if (selectedFile) {
      setSelectedFile(prev => prev ? { ...prev, content, isModified: true } : null)
      
      // Update in files array
      setFiles(prev => prev.map(f => 
        f.id === selectedFile.id ? { ...f, content, isModified: true } : f
      ))
    }
  }

  const handleFileSave = async (fileId: string) => {
    if (!selectedFile || selectedFile.id !== fileId) return

    try {
      const response = await fetch(`/api/vibe/files/${fileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          content: selectedFile.content,
          language: selectedFile.language 
        })
      })

      if (response.ok) {
        setSelectedFile(prev => prev ? { ...prev, isModified: false } : null)
        setFiles(prev => prev.map(f => 
          f.id === fileId ? { ...f, isModified: false } : f
        ))
        
        addTerminalOutput(`💾 Saved: ${selectedFile.name}`)
      }
    } catch (error) {
      console.error('Failed to save file:', error)
      addTerminalOutput(`❌ Failed to save: ${selectedFile.name}`)
    }
  }

  const handleFileRun = async (fileId: string) => {
    if (!selectedFile || selectedFile.id !== fileId) return

    addTerminalOutput(`▶️ Running ${selectedFile.name}...`)
    
    if (executionConnected) {
      executeCode(selectedFile.content, selectedFile.language, selectedFile.name)
    } else {
      // Fallback to HTTP execution
      try {
        const token = localStorage.getItem('token')
        if (!token) {
          addTerminalOutput(`❌ Authentication required`)
          router.push('/login')
          return
        }

        const response = await fetch('/api/vibe/execute', {
          method: 'POST',
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json' 
          },
          body: JSON.stringify({
            session_id: currentSession?.id,
            code: selectedFile.content,
            language: selectedFile.language,
            filename: selectedFile.name
          })
        })

        if (response.ok) {
          const result = await response.json()
          addExecutionOutput(result.output || 'No output')
          if (result.exit_code !== 0) {
            addExecutionOutput(`❌ Exit code: ${result.exit_code}`)
            if (result.error) {
              addExecutionOutput(`Error: ${result.error}`)
            }
          } else {
            addExecutionOutput(`✅ Execution completed successfully`)
          }
          if (result.execution_time) {
            addExecutionOutput(`⏱️ Execution time: ${result.execution_time.toFixed(3)}s`)
          }
        } else {
          const errorData = await response.json().catch(() => ({ detail: 'Execution failed' }))
          addExecutionOutput(`❌ Execution failed: ${errorData.detail || 'Unknown error'}`)
        }
      } catch (error) {
        addTerminalOutput(`❌ Error: ${error}`)
      }
    }
  }

  const addTerminalOutput = (output: string) => {
    setTerminalOutput(prev => [...prev, output])
  }

  const addExecutionOutput = (output: string) => {
    setCodeExecutionOutput(prev => [...prev, output])
    // Also switch to execution tab when new output arrives
    setTerminalTab('execution')
  }

  // Refresh file tree
  const refreshFiles = async () => {
    if (!currentSession) return
    
    try {
      const token = localStorage.getItem('token')
      if (!token) return
      
      const response = await fetch(`/api/vibe/files?sessionId=${currentSession.id}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const { files: sessionFiles } = await response.json()
        
        // Convert files to FileTreeNode format
        const fileNodes: FileTreeNode[] = sessionFiles.map((file: any) => ({
          id: file.id,
          name: file.name,
          type: file.type,
          path: file.path,
          content: file.content,
          language: file.language,
          parentId: file.parent_id,
          isModified: false,
          createdAt: new Date(file.created_at),
          updatedAt: new Date(file.updated_at)
        }))
        
        setFiles(fileNodes)
      }
    } catch (error) {
      console.error('Failed to refresh files:', error)
    }
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
          history: chatMessages.slice(-10), // Last 10 messages for context
          model: selectedModel,
          context: {
            files: files.filter(f => f.type === 'file').map(f => ({ 
              name: f.name, 
              content: f.content, 
              language: f.language 
            })),
            currentFile: selectedFile ? {
              name: selectedFile.name,
              content: selectedFile.content,
              language: selectedFile.language
            } : null,
            session: currentSession?.name
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
        content: "Sorry, I encountered an error while processing your request. Please try again.",
        timestamp: new Date(),
        type: "text",
      }
      setChatMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsAIProcessing(false)
    }
  }

  // Early return for loading states
  if (userLoading || isLoadingSession) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-purple-400 mx-auto mb-4" />
          <p className="text-gray-400">
            {userLoading ? 'Checking authentication...' : 'Loading Vibe Coding environment...'}
          </p>
        </div>
      </div>
    )
  }

  if (!user) {
    return null // Will redirect to login
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#8B5CF6', '#F59E0B', '#EF4444']}
          blend={0.4}
          amplitude={1.0}
          speed={0.6}
        />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm flex flex-col">
        <div className="container mx-auto px-4 py-6 flex-1 flex flex-col">
          {/* Header - Fixed height */}
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
              <Badge variant="outline" className="border-purple-500 text-purple-400">
                {currentSession?.name || 'Loading...'}
              </Badge>
            </div>
            <div className="flex items-center space-x-4">
              {/* Compact Model Switcher */}
              <div className="hidden md:block">
                <VibeModelSelector
                  selectedModel={selectedModel}
                  selectedAgent={selectedAgent}
                  onModelChange={setSelectedModel}
                  onAgentChange={setSelectedAgent}
                  className="w-64"
                />
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  onClick={() => handleDownload(currentSession?.id || '', true)}
                  variant="outline"
                  size="sm"
                  className="bg-gray-800 border-gray-600 text-gray-300"
                  disabled={!currentSession}
                >
                  <Download className="w-4 h-4 mr-2" />
                  Export
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
            </div>
          </motion.div>

          {/* Main Content Area - Flexible height */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-6 flex-1 min-h-0 overflow-hidden">
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
              
              {/* Mobile Code Editor */}
              <div className="h-96">
                <VibeCodeEditor
                  file={selectedFile}
                  onContentChange={handleContentChange}
                  onSave={handleFileSave}
                  onRun={handleFileRun}
                  onDownload={(fileId) => handleDownload(fileId, false)}
                  isExecuting={isExecuting}
                  theme="vibe-dark"
                />
              </div>
              
              {/* Mobile File Tree */}
              <div className="h-64">
                <VibeFileTree
                  sessionId={currentSession?.id || ''}
                  files={files}
                  selectedFileId={selectedFile?.id}
                  onFileSelect={handleFileSelect}
                  onFileCreate={handleFileCreate}
                  onFileRename={handleFileRename}
                  onFileDelete={handleFileDelete}
                  onFileMove={handleFileMove}
                  onDownload={handleDownload}
                  onToggleExpanded={handleToggleExpanded}
                  isLoading={isLoadingSession}
                />
              </div>
              
              {/* Mobile Chat */}
              <div className="h-64">
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
                            <p>{message.content}</p>
                          </div>
                        </motion.div>
                      ))}
                    </AnimatePresence>
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
              
              {/* Mobile Terminal */}
              <div className="h-48">
                <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 h-full flex flex-col">
                  <div className="p-4 border-b border-blue-500/30">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <Terminal className="w-5 h-5 text-blue-400" />
                        <div className="flex space-x-1">
                          <button
                            onClick={() => setTerminalTab('terminal')}
                            className={`px-3 py-1 text-sm rounded ${
                              terminalTab === 'terminal' 
                                ? 'bg-blue-600 text-white' 
                                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                            }`}
                          >
                            Terminal
                          </button>
                          <button
                            onClick={() => setTerminalTab('execution')}
                            className={`px-3 py-1 text-sm rounded ${
                              terminalTab === 'execution' 
                                ? 'bg-purple-600 text-white' 
                                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                            }`}
                          >
                            Execution
                          </button>
                        </div>
                      </div>
                      <Button
                        onClick={() => {
                          if (terminalTab === 'terminal') {
                            setTerminalOutput(["Terminal cleared"])
                          } else {
                            setCodeExecutionOutput(["Execution output cleared"])
                          }
                        }}
                        size="sm"
                        variant="outline"
                        className="bg-gray-800 border-gray-600 text-gray-300"
                      >
                        Clear
                      </Button>
                    </div>
                  </div>
                  <div className="flex-1 p-4 overflow-y-auto bg-black rounded-b-lg">
                    <div className="font-mono text-sm space-y-1">
                      {terminalTab === 'terminal' ? (
                        terminalOutput.map((line, index) => (
                          <div key={index} className="text-green-400">
                            {line}
                          </div>
                        ))
                      ) : (
                        codeExecutionOutput.map((line, index) => (
                          <div key={index} className="text-cyan-400">
                            {line}
                          </div>
                        ))
                      )}
                      <div ref={terminalEndRef} />
                    </div>
                  </div>
                </Card>
              </div>
            </div>
            {/* Desktop Layout - Left Panel: File Tree */}
            <div className="hidden lg:flex lg:col-span-3 flex-col min-h-0 max-h-full">
              {/* File Tree */}
              <div className="flex-1 min-h-0 overflow-hidden">
                <VibeFileTree
                  sessionId={currentSession?.id || ''}
                  files={files}
                  selectedFileId={selectedFile?.id}
                  onFileSelect={handleFileSelect}
                  onFileCreate={handleFileCreate}
                  onFileRename={handleFileRename}
                  onFileDelete={handleFileDelete}
                  onFileMove={handleFileMove}
                  onDownload={handleDownload}
                  onToggleExpanded={handleToggleExpanded}
                  isLoading={isLoadingSession}
                />
              </div>
            </div>

            {/* Desktop Layout - Center Panel: Code Editor */}
            <div className="hidden lg:block lg:col-span-6 min-h-0 max-h-full overflow-hidden">
              <VibeCodeEditor
                file={selectedFile}
                onContentChange={handleContentChange}
                onSave={handleFileSave}
                onRun={handleFileRun}
                onDownload={(fileId) => handleDownload(fileId, false)}
                isExecuting={isExecuting}
                theme="vibe-dark"
              />
            </div>

            {/* Desktop Layout - Right Panel: Chat & Terminal */}
            <div className="hidden lg:flex lg:col-span-3 flex-col space-y-4 min-h-0 max-h-full">
              {/* AI Chat */}
              <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 flex-1 flex flex-col min-h-0">
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
                          <div
                            className="w-1 h-1 bg-purple-400 rounded-full animate-bounce"
                            style={{ animationDelay: "0.1s" }}
                          ></div>
                          <div
                            className="w-1 h-1 bg-purple-400 rounded-full animate-bounce"
                            style={{ animationDelay: "0.2s" }}
                          ></div>
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

              {/* Terminal */}
              <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 flex-1 flex flex-col min-h-0">
                <div className="p-4 border-b border-blue-500/30">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <Terminal className="w-5 h-5 text-blue-400" />
                      <div className="flex space-x-1">
                        <button
                          onClick={() => setTerminalTab('terminal')}
                          className={`px-3 py-1 text-sm rounded ${
                            terminalTab === 'terminal' 
                              ? 'bg-blue-600 text-white' 
                              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                          }`}
                        >
                          Terminal
                        </button>
                        <button
                          onClick={() => setTerminalTab('execution')}
                          className={`px-3 py-1 text-sm rounded ${
                            terminalTab === 'execution' 
                              ? 'bg-purple-600 text-white' 
                              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                          }`}
                        >
                          Execution
                        </button>
                      </div>
                      <Badge variant="outline" className={`text-xs ${
                        executionConnected ? 'border-green-500 text-green-400' : 'border-red-500 text-red-400'
                      }`}>
                        {executionConnected ? 'Connected' : 'Offline'}
                      </Badge>
                    </div>
                    <Button
                      onClick={() => {
                        if (terminalTab === 'terminal') {
                          setTerminalOutput(["Terminal cleared"])
                        } else {
                          setCodeExecutionOutput(["Execution output cleared"])
                        }
                      }}
                      size="sm"
                      variant="outline"
                      className="bg-gray-800 border-gray-600 text-gray-300"
                    >
                      Clear
                    </Button>
                  </div>
                </div>

                <div className="flex-1 p-4 overflow-y-auto bg-black rounded-b-lg">
                  <div className="font-mono text-sm space-y-1">
                    {terminalTab === 'terminal' ? (
                      terminalOutput.map((line, index) => (
                        <div key={index} className="text-green-400">
                          {line}
                        </div>
                      ))
                    ) : (
                      codeExecutionOutput.map((line, index) => (
                        <div key={index} className="text-cyan-400">
                          {line}
                        </div>
                      ))
                    )}
                    <div ref={terminalEndRef} />
                  </div>
                </div>
              </Card>
            </div>
          </div>
        </div>

        {/* Settings Modal */}
        <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} context="agent" />
      </div>
    </div>
  )
}