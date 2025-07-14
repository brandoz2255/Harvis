"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
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
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import Link from "next/link"
import SettingsModal from "@/components/SettingsModal"
import Aurora from "@/components/Aurora"

interface CodeFile {
  id: string
  name: string
  content: string
  language: string
  isActive: boolean
  isModified: boolean
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  type?: "voice" | "text" | "code" | "command"
}

interface CodeStep {
  id: string
  description: string
  action: "create_file" | "modify_file" | "run_command" | "install_package"
  target: string
  content?: string
  command?: string
  completed: boolean
}

export default function VibeCodingPage() {
  const [files, setFiles] = useState<CodeFile[]>([
    {
      id: "1",
      name: "main.py",
      content: "# Welcome to Vibe Coding!\n# Start by saying what you want to build...\n\nprint('Hello, Vibe Coder!')",
      language: "python",
      isActive: true,
      isModified: false,
    },
  ])

  const [activeFileId, setActiveFileId] = useState("1")
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Welcome to Vibe Coding! 🚀 Tell me what you want to build and I'll help you code it step by step. You can speak or type your requests!",
      timestamp: new Date(),
      type: "text",
    },
  ])

  const [chatInput, setChatInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [terminalOutput, setTerminalOutput] = useState<string[]>([
    "Vibe Coding Terminal Ready 🎵",
    "Type commands or let AI execute them for you!",
  ])

  // Voice features
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessingVoice, setIsProcessingVoice] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  // AI Coding features
  const [isVibeCoding, setIsVibeCoding] = useState(false)
  const [currentSteps, setCurrentSteps] = useState<CodeStep[]>([])
  const [executingStep, setExecutingStep] = useState<string | null>(null)

  const [showSettings, setShowSettings] = useState(false)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  const scrollToBottom = (ref: React.RefObject<HTMLDivElement>) => {
    ref.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom(chatEndRef)
  }, [chatMessages])

  useEffect(() => {
    scrollToBottom(terminalEndRef)
  }, [terminalOutput])

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
      formData.append("model", "mistral")

      const response = await fetch("/api/voice-transcribe", {
        method: "POST",
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        if (data.transcription) {
          setChatInput(data.transcription)
          // Auto-send the transcribed command
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

  // Main vibe coding function
  const sendVibeCommand = async (command?: string, inputType: "text" | "voice" = "text") => {
    const message = command || chatInput
    if (!message.trim() || isLoading) return

    const userMessage: ChatMessage = {
      role: "user",
      content: message,
      timestamp: new Date(),
      type: inputType,
    }

    setChatMessages((prev) => [...prev, userMessage])
    if (inputType === "text") setChatInput("")
    setIsLoading(true)

    try {
      const response = await fetch("/api/vibe-coding", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          files: files.map((f) => ({ name: f.name, content: f.content, language: f.language })),
          terminalHistory: terminalOutput.slice(-10), // Last 10 terminal outputs
          model: "mistral",
        }),
      })

      if (response.ok) {
        const data = await response.json()

        // Add AI response to chat
        const aiMessage: ChatMessage = {
          role: "assistant",
          content: data.response || "I'll help you with that!",
          timestamp: new Date(),
          type: "code",
        }
        setChatMessages((prev) => [...prev, aiMessage])

        // Execute the coding steps
        if (data.steps && data.steps.length > 0) {
          setCurrentSteps(data.steps)
          setIsVibeCoding(true)
          executeSteps(data.steps)
        }

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
      console.error("Vibe coding error:", error)
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I encountered an error while processing your request.",
        timestamp: new Date(),
        type: "text",
      }
      setChatMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const executeSteps = async (steps: CodeStep[]) => {
    for (const step of steps) {
      setExecutingStep(step.id)
      await new Promise((resolve) => setTimeout(resolve, 1000)) // Simulate execution time

      switch (step.action) {
        case "create_file":
          createFile(step.target, step.content || "", getLanguageFromFilename(step.target))
          addTerminalOutput(`✅ Created file: ${step.target}`)
          break

        case "modify_file":
          modifyFile(step.target, step.content || "")
          addTerminalOutput(`✅ Modified file: ${step.target}`)
          break

        case "run_command":
          if (step.command) {
            await runCommand(step.command)
          }
          break

        case "install_package":
          if (step.command) {
            await runCommand(step.command)
          }
          break
      }

      // Mark step as completed
      setCurrentSteps((prev) => prev.map((s) => (s.id === step.id ? { ...s, completed: true } : s)))
    }

    setExecutingStep(null)
    setIsVibeCoding(false)
    addTerminalOutput("🎉 Vibe coding session completed!")
  }

  const createFile = (name: string, content: string, language: string) => {
    const newFile: CodeFile = {
      id: Date.now().toString(),
      name,
      content,
      language,
      isActive: false,
      isModified: false,
    }

    setFiles((prev) => [...prev, newFile])
    setActiveFileId(newFile.id)
  }

  const modifyFile = (name: string, content: string) => {
    setFiles((prev) => prev.map((file) => (file.name === name ? { ...file, content, isModified: true } : file)))
  }

  const runCommand = async (command: string) => {
    addTerminalOutput(`$ ${command}`)

    try {
      const response = await fetch("/api/run-command", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ command }),
      })

      if (response.ok) {
        const data = await response.json()
        addTerminalOutput(data.output || "Command executed successfully")
      } else {
        addTerminalOutput("❌ Command failed")
      }
    } catch (error) {
      addTerminalOutput("❌ Error executing command")
    }
  }

  const addTerminalOutput = (output: string) => {
    setTerminalOutput((prev) => [...prev, output])
  }

  const getLanguageFromFilename = (filename: string): string => {
    const ext = filename.split(".").pop()?.toLowerCase()
    const langMap: { [key: string]: string } = {
      py: "python",
      js: "javascript",
      ts: "typescript",
      jsx: "javascript",
      tsx: "typescript",
      html: "html",
      css: "css",
      json: "json",
      md: "markdown",
      yml: "yaml",
      yaml: "yaml",
      sh: "bash",
      sql: "sql",
    }
    return langMap[ext || ""] || "text"
  }

  const activeFile = files.find((f) => f.id === activeFileId)

  const updateFileContent = (content: string) => {
    setFiles((prev) => prev.map((file) => (file.id === activeFileId ? { ...file, content, isModified: true } : file)))
  }

  const saveFile = async (fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (!file) return

    try {
      const response = await fetch("/api/save-file", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          filename: file.name,
          content: file.content,
        }),
      })

      if (response.ok) {
        setFiles((prev) => prev.map((f) => (f.id === fileId ? { ...f, isModified: false } : f)))
        addTerminalOutput(`💾 Saved: ${file.name}`)
      }
    } catch (error) {
      addTerminalOutput(`❌ Failed to save: ${file.name}`)
    }
  }

  const closeFile = (fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== fileId))
    if (activeFileId === fileId && files.length > 1) {
      const remainingFiles = files.filter((f) => f.id !== fileId)
      setActiveFileId(remainingFiles[0]?.id || "")
    }
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
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-6">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between mb-6"
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
              AI-Powered IDE
            </Badge>
          </div>
          <div className="flex items-center space-x-2">
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

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-200px)]">
          {/* File Explorer & Chat */}
          <div className="lg:col-span-1 space-y-4">
            {/* File Explorer */}
            <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-1/2">
              <div className="p-4 border-b border-purple-500/30">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-purple-300">Files</h3>
                  <Button
                    onClick={() => createFile("new-file.py", "# New file\n", "python")}
                    size="sm"
                    className="bg-purple-600 hover:bg-purple-700 text-white"
                  >
                    <Plus className="w-3 h-3" />
                  </Button>
                </div>
              </div>
              <div className="p-4 overflow-y-auto">
                <div className="space-y-2">
                  {files.map((file) => (
                    <div
                      key={file.id}
                      className={`flex items-center justify-between p-2 rounded cursor-pointer transition-colors ${
                        file.id === activeFileId
                          ? "bg-purple-600/20 border border-purple-500/50"
                          : "bg-gray-800/50 hover:bg-gray-800/70"
                      }`}
                      onClick={() => setActiveFileId(file.id)}
                    >
                      <div className="flex items-center space-x-2 flex-1 min-w-0">
                        <FileText className="w-4 h-4 text-purple-400 flex-shrink-0" />
                        <span className="text-sm text-white truncate">{file.name}</span>
                        {file.isModified && <div className="w-2 h-2 bg-orange-400 rounded-full flex-shrink-0" />}
                      </div>
                      <div className="flex space-x-1">
                        <Button
                          onClick={(e) => {
                            e.stopPropagation()
                            saveFile(file.id)
                          }}
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0 text-gray-400 hover:text-white"
                        >
                          <Save className="w-3 h-3" />
                        </Button>
                        {files.length > 1 && (
                          <Button
                            onClick={(e) => {
                              e.stopPropagation()
                              closeFile(file.id)
                            }}
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0 text-gray-400 hover:text-red-400"
                          >
                            <X className="w-3 h-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            {/* AI Chat */}
            <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-1/2 flex flex-col">
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
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>

                {(isLoading || isProcessingVoice) && (
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
                    onKeyPress={(e) => e.key === "Enter" && !isLoading && sendVibeCommand()}
                    placeholder="Tell me what to code..."
                    className="flex-1 bg-gray-800 border-gray-600 text-white text-sm"
                    disabled={isLoading || isProcessingVoice}
                  />
                  <Button
                    onClick={() => sendVibeCommand()}
                    disabled={isLoading || !chatInput.trim() || isProcessingVoice}
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
          </div>

          {/* Code Editor */}
          <div className="lg:col-span-2">
            <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 h-full flex flex-col">
              <div className="p-4 border-b border-purple-500/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Code className="w-5 h-5 text-purple-400" />
                    <h3 className="text-lg font-semibold text-purple-300">{activeFile?.name || "No file selected"}</h3>
                    {activeFile?.isModified && (
                      <Badge variant="outline" className="border-orange-500 text-orange-400">
                        Modified
                      </Badge>
                    )}
                  </div>
                  <div className="flex space-x-2">
                    <Button
                      onClick={() => activeFile && saveFile(activeFile.id)}
                      disabled={!activeFile?.isModified}
                      size="sm"
                      className="bg-green-600 hover:bg-green-700 text-white"
                    >
                      <Save className="w-3 h-3 mr-1" />
                      Save
                    </Button>
                    <Button
                      onClick={() => activeFile && runCommand(`python ${activeFile.name}`)}
                      size="sm"
                      className="bg-blue-600 hover:bg-blue-700 text-white"
                    >
                      <Play className="w-3 h-3 mr-1" />
                      Run
                    </Button>
                  </div>
                </div>
              </div>

              <div className="flex-1 p-4">
                {activeFile ? (
                  <Textarea
                    value={activeFile.content}
                    onChange={(e) => updateFileContent(e.target.value)}
                    className="w-full h-full bg-gray-800 border-gray-600 text-white font-mono text-sm resize-none"
                    placeholder="Start coding..."
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-400">
                    <div className="text-center">
                      <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>No file selected</p>
                      <p className="text-sm">Create a new file or select an existing one</p>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* Terminal & Steps */}
          <div className="lg:col-span-1 space-y-4">
            {/* AI Steps */}
            {currentSteps.length > 0 && (
              <Card className="bg-gray-900/50 backdrop-blur-sm border-green-500/30 h-1/2">
                <div className="p-4 border-b border-green-500/30">
                  <h3 className="text-lg font-semibold text-green-300">AI Steps</h3>
                </div>
                <div className="p-4 overflow-y-auto">
                  <div className="space-y-2">
                    {currentSteps.map((step) => (
                      <div
                        key={step.id}
                        className={`p-2 rounded border ${
                          step.completed
                            ? "bg-green-900/20 border-green-500/50"
                            : executingStep === step.id
                              ? "bg-yellow-900/20 border-yellow-500/50"
                              : "bg-gray-800/50 border-gray-600"
                        }`}
                      >
                        <div className="flex items-center space-x-2">
                          {step.completed ? (
                            <div className="w-4 h-4 bg-green-500 rounded-full flex items-center justify-center">
                              <div className="w-2 h-2 bg-white rounded-full"></div>
                            </div>
                          ) : executingStep === step.id ? (
                            <div className="w-4 h-4 bg-yellow-500 rounded-full animate-pulse"></div>
                          ) : (
                            <div className="w-4 h-4 bg-gray-500 rounded-full"></div>
                          )}
                          <span className="text-sm text-white">{step.description}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            )}

            {/* Terminal */}
            <Card
              className={`bg-gray-900/50 backdrop-blur-sm border-blue-500/30 flex flex-col ${
                currentSteps.length > 0 ? "h-1/2" : "h-full"
              }`}
            >
              <div className="p-4 border-b border-blue-500/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Terminal className="w-5 h-5 text-blue-400" />
                    <h3 className="text-lg font-semibold text-blue-300">Terminal</h3>
                  </div>
                  <Button
                    onClick={() => setTerminalOutput(["Terminal cleared"])}
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
                  {terminalOutput.map((line, index) => (
                    <div key={index} className="text-green-400">
                      {line}
                    </div>
                  ))}
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
