"use client"

import type React from "react"

import { useState, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import {
  ArrowLeft,
  Play,
  Square,
  Settings,
  Monitor,
  MessageSquare,
  Terminal,
  Eye,
  MonitorOff,
  Send,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import Link from "next/link"
import Aurora from "@/components/Aurora"

interface LogEntry {
  id: string
  timestamp: string
  type: "system" | "red-team" | "blue-team" | "info"
  message: string
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: string
}

interface EmulationState {
  isRunning: boolean
  redModel: string
  blueModel: string
  scenario: string
  sessionId: string | null
}

interface AgentScreenState {
  isSharing: boolean
  commentaryEnabled: boolean
  commentary: string
  isAnalyzing: boolean
}

export default function VersusModePage() {
  const [redActiveTab, setRedActiveTab] = useState<"screen" | "chat" | "commands">("screen")
  const [blueActiveTab, setBlueActiveTab] = useState<"screen" | "chat" | "commands">("screen")

  const [emulationState, setEmulationState] = useState<EmulationState>({
    isRunning: false,
    redModel: "gpt-4o",
    blueModel: "claude-3",
    scenario: "network-intrusion",
    sessionId: null,
  })

  const [redScreenState, setRedScreenState] = useState<AgentScreenState>({
    isSharing: false,
    commentaryEnabled: false,
    commentary: "",
    isAnalyzing: false,
  })

  const [blueScreenState, setBlueScreenState] = useState<AgentScreenState>({
    isSharing: false,
    commentaryEnabled: false,
    commentary: "",
    isAnalyzing: false,
  })

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [redChatMessages, setRedChatMessages] = useState<ChatMessage[]>([])
  const [blueChatMessages, setBlueChatMessages] = useState<ChatMessage[]>([])
  const [redChatInput, setRedChatInput] = useState("")
  const [blueChatInput, setBlueChatInput] = useState("")
  const [redChatLoading, setRedChatLoading] = useState(false)
  const [blueChatLoading, setBlueChatLoading] = useState(false)

  const redVideoRef = useRef<HTMLVideoElement>(null)
  const blueVideoRef = useRef<HTMLVideoElement>(null)
  const redStreamRef = useRef<MediaStream | null>(null)
  const blueStreamRef = useRef<MediaStream | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const redChatEndRef = useRef<HTMLDivElement>(null)
  const blueChatEndRef = useRef<HTMLDivElement>(null)

  const availableModels = [
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "claude-3", label: "Claude 3" },
    { value: "mistral", label: "Mistral" },
    { value: "llama3", label: "Llama 3" },
  ]

  const availableScenarios = [
    { value: "network-intrusion", label: "Network Intrusion" },
    { value: "privilege-escalation", label: "Privilege Escalation" },
    { value: "data-exfiltration", label: "Data Exfiltration" },
    { value: "lateral-movement", label: "Lateral Movement" },
    { value: "persistence", label: "Persistence" },
  ]

  const scrollToBottom = (ref: React.RefObject<HTMLDivElement>) => {
    ref.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom(logsEndRef)
  }, [logs])

  useEffect(() => {
    scrollToBottom(redChatEndRef)
  }, [redChatMessages])

  useEffect(() => {
    scrollToBottom(blueChatEndRef)
  }, [blueChatMessages])

  // Screen sharing functions for Red Team
  const startRedScreenShare = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      })

      if (redVideoRef.current) {
        redVideoRef.current.srcObject = stream
        redStreamRef.current = stream
        setRedScreenState((prev) => ({ ...prev, isSharing: true }))

        stream.getVideoTracks()[0].addEventListener("ended", stopRedScreenShare)
      }
    } catch (error) {
      console.error("Error starting red screen share:", error)
      alert("Failed to start screen sharing. Please check permissions.")
    }
  }

  const stopRedScreenShare = () => {
    if (redStreamRef.current) {
      redStreamRef.current.getTracks().forEach((track) => track.stop())
      redStreamRef.current = null
    }

    if (redVideoRef.current) {
      redVideoRef.current.srcObject = null
    }

    setRedScreenState({
      isSharing: false,
      commentaryEnabled: false,
      commentary: "",
      isAnalyzing: false,
    })
  }

  // Screen sharing functions for Blue Team
  const startBlueScreenShare = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      })

      if (blueVideoRef.current) {
        blueVideoRef.current.srcObject = stream
        blueStreamRef.current = stream
        setBlueScreenState((prev) => ({ ...prev, isSharing: true }))

        stream.getVideoTracks()[0].addEventListener("ended", stopBlueScreenShare)
      }
    } catch (error) {
      console.error("Error starting blue screen share:", error)
      alert("Failed to start screen sharing. Please check permissions.")
    }
  }

  const stopBlueScreenShare = () => {
    if (blueStreamRef.current) {
      blueStreamRef.current.getTracks().forEach((track) => track.stop())
      blueStreamRef.current = null
    }

    if (blueVideoRef.current) {
      blueVideoRef.current.srcObject = null
    }

    setBlueScreenState({
      isSharing: false,
      commentaryEnabled: false,
      commentary: "",
      isAnalyzing: false,
    })
  }

  // Analyze screen functions
  const analyzeRedScreen = async () => {
    if (!redVideoRef.current || !redStreamRef.current || redScreenState.isAnalyzing) return

    setRedScreenState((prev) => ({ ...prev, isAnalyzing: true }))

    try {
      const canvas = document.createElement("canvas")
      canvas.width = redVideoRef.current.videoWidth
      canvas.height = redVideoRef.current.videoHeight

      const ctx = canvas.getContext("2d")
      if (ctx) {
        ctx.drawImage(redVideoRef.current, 0, 0)
        const imageData = canvas.toDataURL("image/jpeg", 0.8)

        const response = await fetch("/api/analyze-screen", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ image: imageData }),
        })

        if (response.ok) {
          const data = await response.json()
          if (data.commentary) {
            setRedScreenState((prev) => ({ ...prev, commentary: data.commentary }))
          }
        }
      }
    } catch (error) {
      console.error("Red screen analysis failed:", error)
    } finally {
      setRedScreenState((prev) => ({ ...prev, isAnalyzing: false }))
    }
  }

  const analyzeBlueScreen = async () => {
    if (!blueVideoRef.current || !blueStreamRef.current || blueScreenState.isAnalyzing) return

    setBlueScreenState((prev) => ({ ...prev, isAnalyzing: true }))

    try {
      const canvas = document.createElement("canvas")
      canvas.width = blueVideoRef.current.videoWidth
      canvas.height = blueVideoRef.current.videoHeight

      const ctx = canvas.getContext("2d")
      if (ctx) {
        ctx.drawImage(blueVideoRef.current, 0, 0)
        const imageData = canvas.toDataURL("image/jpeg", 0.8)

        const response = await fetch("/api/analyze-screen", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ image: imageData }),
        })

        if (response.ok) {
          const data = await response.json()
          if (data.commentary) {
            setBlueScreenState((prev) => ({ ...prev, commentary: data.commentary }))
          }
        }
      }
    } catch (error) {
      console.error("Blue screen analysis failed:", error)
    } finally {
      setBlueScreenState((prev) => ({ ...prev, isAnalyzing: false }))
    }
  }

  // Chat functions
  const sendRedChatMessage = async () => {
    if (!redChatInput.trim() || redChatLoading) return

    const userMessage: ChatMessage = {
      role: "user",
      content: redChatInput,
      timestamp: new Date().toLocaleTimeString(),
    }

    setRedChatMessages((prev) => [...prev, userMessage])
    setRedChatInput("")
    setRedChatLoading(true)

    try {
      const response = await fetch("/api/versus-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: redChatInput,
          team: "red",
          model: emulationState.redModel,
          scenario: emulationState.scenario,
          sessionId: emulationState.sessionId,
          history: redChatMessages,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const aiResponse: ChatMessage = {
          role: "assistant",
          content: data.response || "Red team operations acknowledged.",
          timestamp: new Date().toLocaleTimeString(),
        }
        setRedChatMessages((prev) => [...prev, aiResponse])
      }
    } catch (error) {
      console.error("Red chat error:", error)
      const errorResponse: ChatMessage = {
        role: "assistant",
        content: "Error processing red team command.",
        timestamp: new Date().toLocaleTimeString(),
      }
      setRedChatMessages((prev) => [...prev, errorResponse])
    } finally {
      setRedChatLoading(false)
    }
  }

  const sendBlueChatMessage = async () => {
    if (!blueChatInput.trim() || blueChatLoading) return

    const userMessage: ChatMessage = {
      role: "user",
      content: blueChatInput,
      timestamp: new Date().toLocaleTimeString(),
    }

    setBlueChatMessages((prev) => [...prev, userMessage])
    setBlueChatInput("")
    setBlueChatLoading(true)

    try {
      const response = await fetch("/api/versus-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: blueChatInput,
          team: "blue",
          model: emulationState.blueModel,
          scenario: emulationState.scenario,
          sessionId: emulationState.sessionId,
          history: blueChatMessages,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const aiResponse: ChatMessage = {
          role: "assistant",
          content: data.response || "Blue team defenses activated.",
          timestamp: new Date().toLocaleTimeString(),
        }
        setBlueChatMessages((prev) => [...prev, aiResponse])
      }
    } catch (error) {
      console.error("Blue chat error:", error)
      const errorResponse: ChatMessage = {
        role: "assistant",
        content: "Error processing blue team command.",
        timestamp: new Date().toLocaleTimeString(),
      }
      setBlueChatMessages((prev) => [...prev, errorResponse])
    } finally {
      setBlueChatLoading(false)
    }
  }

  // Simulate real-time log updates
  useEffect(() => {
    if (!emulationState.isRunning) return

    const interval = setInterval(() => {
      const sampleLogs = [
        { type: "system" as const, message: "Simulation environment initialized" },
        { type: "red-team" as const, message: "Scanning network for vulnerabilities..." },
        { type: "blue-team" as const, message: "Monitoring network traffic for anomalies" },
        { type: "red-team" as const, message: "Found open SSH port on target system" },
        { type: "blue-team" as const, message: "Detected port scan from external IP" },
        { type: "red-team" as const, message: "Attempting credential brute force" },
        { type: "blue-team" as const, message: "Blocking suspicious login attempts" },
        { type: "system" as const, message: "Security alert: Multiple failed login attempts" },
      ]

      const randomLog = sampleLogs[Math.floor(Math.random() * sampleLogs.length)]
      const newLog: LogEntry = {
        id: Date.now().toString(),
        timestamp: new Date().toLocaleTimeString(),
        type: randomLog.type,
        message: randomLog.message,
      }

      setLogs((prev) => [...prev.slice(-19), newLog]) // Keep last 20 logs
    }, 3000)

    return () => clearInterval(interval)
  }, [emulationState.isRunning])

  const startEmulation = async () => {
    try {
      const response = await fetch("/api/start-versus-emulation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          redModel: emulationState.redModel,
          blueModel: emulationState.blueModel,
          scenario: emulationState.scenario,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        setEmulationState((prev) => ({
          ...prev,
          isRunning: true,
          sessionId: data.sessionId,
        }))

        const initialLog: LogEntry = {
          id: Date.now().toString(),
          timestamp: new Date().toLocaleTimeString(),
          type: "system",
          message: `Versus mode started: ${emulationState.redModel} vs ${emulationState.blueModel} - ${emulationState.scenario}`,
        }
        setLogs([initialLog])

        // Initialize chat with welcome messages
        const redWelcome: ChatMessage = {
          role: "assistant",
          content: `Red team agent initialized with ${emulationState.redModel}. Ready for ${emulationState.scenario} operations.`,
          timestamp: new Date().toLocaleTimeString(),
        }
        const blueWelcome: ChatMessage = {
          role: "assistant",
          content: `Blue team agent initialized with ${emulationState.blueModel}. Defensive systems active for ${emulationState.scenario} scenario.`,
          timestamp: new Date().toLocaleTimeString(),
        }
        setRedChatMessages([redWelcome])
        setBlueChatMessages([blueWelcome])
      }
    } catch (error) {
      console.error("Failed to start emulation:", error)
    }
  }

  const stopEmulation = () => {
    setEmulationState((prev) => ({
      ...prev,
      isRunning: false,
      sessionId: null,
    }))

    const stopLog: LogEntry = {
      id: Date.now().toString(),
      timestamp: new Date().toLocaleTimeString(),
      type: "system",
      message: "Versus mode simulation stopped",
    }
    setLogs((prev) => [...prev, stopLog])

    // Clear chat messages
    setRedChatMessages([])
    setBlueChatMessages([])
  }

  const getLogTypeColor = (type: LogEntry["type"]) => {
    switch (type) {
      case "system":
        return "text-blue-400"
      case "red-team":
        return "text-red-400"
      case "blue-team":
        return "text-cyan-400"
      case "info":
        return "text-gray-400"
      default:
        return "text-gray-400"
    }
  }

  const getLogTypePrefix = (type: LogEntry["type"]) => {
    switch (type) {
      case "system":
        return "[System]"
      case "red-team":
        return "[Red Team]"
      case "blue-team":
        return "[Blue Team]"
      case "info":
        return "[Info]"
      default:
        return "[Log]"
    }
  }

  const renderAgentInterface = (
    team: "red" | "blue",
    activeTab: string,
    setActiveTab: (tab: "screen" | "chat" | "commands") => void,
    chatMessages: ChatMessage[],
    chatInput: string,
    setChatInput: (input: string) => void,
    sendMessage: () => void,
    chatLoading: boolean,
    screenState: AgentScreenState,
    videoRef: React.RefObject<HTMLVideoElement>,
    startScreenShare: () => void,
    stopScreenShare: () => void,
    analyzeScreen: () => void,
    chatEndRef: React.RefObject<HTMLDivElement>,
  ) => {
    const teamColor = team === "red" ? "red" : "cyan"
    const teamColorClass = team === "red" ? "border-red-500/30" : "border-cyan-500/30"
    const teamTextClass = team === "red" ? "text-red-300" : "text-cyan-300"
    const teamBgClass = team === "red" ? "bg-red-600" : "bg-cyan-600"
    const teamHoverClass = team === "red" ? "hover:bg-red-700" : "hover:bg-cyan-700"

    return (
      <Card className={`bg-gray-900/50 backdrop-blur-sm ${teamColorClass}`}>
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className={`text-lg font-semibold ${teamTextClass}`}>{team === "red" ? "Red Team" : "Blue Team"}</h3>
            <Badge
              variant="outline"
              className={`${teamColor === "red" ? "border-red-500 text-red-400" : "border-cyan-500 text-cyan-400"}`}
            >
              {team === "red" ? emulationState.redModel : emulationState.blueModel}
            </Badge>
          </div>

          {/* Tab Navigation */}
          <div className="flex space-x-1 mb-4">
            {[
              { id: "screen", label: "Screen", icon: Monitor },
              { id: "chat", label: "Chat", icon: MessageSquare },
              { id: "commands", label: "Commands", icon: Terminal },
            ].map((tab) => (
              <Button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                variant={activeTab === tab.id ? "default" : "outline"}
                size="sm"
                className={`${
                  activeTab === tab.id
                    ? `${teamBgClass} text-white`
                    : "bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
                }`}
              >
                <tab.icon className="w-4 h-4 mr-1" />
                {tab.label}
              </Button>
            ))}
          </div>
        </div>

        <div className="p-4">
          {/* Tab Content */}
          <div className="bg-gray-800 rounded-lg p-3 h-80">
            {activeTab === "screen" && (
              <div className="h-full">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-gray-400">Screen Feed</span>
                  <div className="flex space-x-1">
                    <Button
                      onClick={screenState.isSharing ? stopScreenShare : startScreenShare}
                      size="sm"
                      className={`${screenState.isSharing ? "bg-red-600 hover:bg-red-700" : `${teamBgClass} ${teamHoverClass}`} text-white`}
                    >
                      {screenState.isSharing ? <MonitorOff className="w-3 h-3" /> : <Monitor className="w-3 h-3" />}
                    </Button>
                    <Button
                      onClick={analyzeScreen}
                      disabled={!screenState.isSharing || screenState.isAnalyzing}
                      size="sm"
                      variant="outline"
                      className="bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600"
                    >
                      <Eye className="w-3 h-3" />
                    </Button>
                  </div>
                </div>

                <div className="relative h-64">
                  <video
                    ref={videoRef}
                    autoPlay
                    muted
                    className={`w-full h-full rounded border border-gray-600 object-cover ${screenState.isSharing ? "block" : "hidden"}`}
                  />

                  {!screenState.isSharing && (
                    <div className="w-full h-full bg-gray-700 rounded border border-gray-600 flex items-center justify-center">
                      <div className="text-center text-gray-400">
                        <Monitor className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-xs">Click to start screen sharing</p>
                      </div>
                    </div>
                  )}
                </div>

                {screenState.commentary && (
                  <div className="mt-2 bg-gray-700 rounded p-2">
                    <p className="text-xs text-gray-300">{screenState.commentary}</p>
                  </div>
                )}
              </div>
            )}

            {activeTab === "chat" && (
              <div className="h-full flex flex-col">
                <div className="flex-1 overflow-y-auto mb-3 space-y-2">
                  {chatMessages.map((message, index) => (
                    <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-[80%] p-2 rounded text-xs ${
                          message.role === "user" ? `${teamBgClass} text-white` : "bg-gray-700 text-gray-100"
                        }`}
                      >
                        <p>{message.content}</p>
                        <span className="text-xs opacity-70 mt-1 block">{message.timestamp}</span>
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="flex justify-start">
                      <div className="bg-gray-700 p-2 rounded">
                        <div className="flex space-x-1">
                          <div className="w-1 h-1 bg-blue-400 rounded-full animate-bounce"></div>
                          <div
                            className="w-1 h-1 bg-blue-400 rounded-full animate-bounce"
                            style={{ animationDelay: "0.1s" }}
                          ></div>
                          <div
                            className="w-1 h-1 bg-blue-400 rounded-full animate-bounce"
                            style={{ animationDelay: "0.2s" }}
                          ></div>
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
                <div className="flex space-x-2">
                  <Input
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyPress={(e) => e.key === "Enter" && !chatLoading && sendMessage()}
                    placeholder={`Message ${team} team...`}
                    className="flex-1 bg-gray-700 border-gray-600 text-white text-sm"
                    disabled={!emulationState.isRunning || chatLoading}
                  />
                  <Button
                    onClick={sendMessage}
                    disabled={!emulationState.isRunning || !chatInput.trim() || chatLoading}
                    size="sm"
                    className={`${teamBgClass} ${teamHoverClass} text-white`}
                  >
                    <Send className="w-3 h-3" />
                  </Button>
                </div>
              </div>
            )}

            {activeTab === "commands" && (
              <div className="h-full">
                <div className="bg-black rounded p-2 h-full overflow-y-auto font-mono text-xs">
                  <div className={`${teamColor === "red" ? "text-red-400" : "text-cyan-400"} mb-2`}>
                    $ {team.toUpperCase()} TEAM COMMAND INTERFACE
                  </div>
                  <div className="text-gray-400 mb-3">Real-time command execution log:</div>
                  {logs
                    .filter((log) => log.type === `${team}-team` || log.type === "system")
                    .map((log) => (
                      <div key={log.id} className="mb-1">
                        <span className="text-gray-500">[{log.timestamp}]</span>{" "}
                        <span className={getLogTypeColor(log.type)}>{log.message}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </Card>
    )
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#DC2626', '#3B82F6', '#7C3AED']}
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
            <h1 className="text-3xl font-bold text-white">Versus Mode</h1>
            <Badge variant="outline" className="border-purple-500 text-purple-400">
              Red Team vs Blue Team
            </Badge>
          </div>
          <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300">
            <Settings className="w-4 h-4 mr-2" />
            Settings
          </Button>
        </motion.div>

        {/* Simulation Configuration */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 mb-6">
            <div className="p-6">
              <h2 className="text-xl font-semibold text-purple-300 mb-4">Simulation Configuration</h2>
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4 items-end">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Red Team Model</label>
                  <select
                    value={emulationState.redModel}
                    onChange={(e) => setEmulationState((prev) => ({ ...prev, redModel: e.target.value }))}
                    disabled={emulationState.isRunning}
                    className="w-full bg-gray-800 border border-gray-600 text-white rounded px-3 py-2 focus:border-red-500 focus:outline-none disabled:opacity-50"
                  >
                    {availableModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Blue Team Model</label>
                  <select
                    value={emulationState.blueModel}
                    onChange={(e) => setEmulationState((prev) => ({ ...prev, blueModel: e.target.value }))}
                    disabled={emulationState.isRunning}
                    className="w-full bg-gray-800 border border-gray-600 text-white rounded px-3 py-2 focus:border-cyan-500 focus:outline-none disabled:opacity-50"
                  >
                    {availableModels.map((model) => (
                      <option key={model.value} value={model.value}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Scenario</label>
                  <select
                    value={emulationState.scenario}
                    onChange={(e) => setEmulationState((prev) => ({ ...prev, scenario: e.target.value }))}
                    disabled={emulationState.isRunning}
                    className="w-full bg-gray-800 border border-gray-600 text-white rounded px-3 py-2 focus:border-purple-500 focus:outline-none disabled:opacity-50"
                  >
                    {availableScenarios.map((scenario) => (
                      <option key={scenario.value} value={scenario.value}>
                        {scenario.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">Status</label>
                  <Badge
                    variant="outline"
                    className={`${
                      emulationState.isRunning ? "border-green-500 text-green-400" : "border-gray-500 text-gray-400"
                    }`}
                  >
                    {emulationState.isRunning ? "Running" : "Stopped"}
                  </Badge>
                </div>

                <div>
                  <Button
                    onClick={emulationState.isRunning ? stopEmulation : startEmulation}
                    className={`w-full ${
                      emulationState.isRunning ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"
                    } text-white`}
                  >
                    {emulationState.isRunning ? (
                      <>
                        <Square className="w-4 h-4 mr-2" />
                        Stop Simulation
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4 mr-2" />
                        Start Simulation
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Agent Interfaces */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Red Team Interface */}
            {renderAgentInterface(
              "red",
              redActiveTab,
              setRedActiveTab,
              redChatMessages,
              redChatInput,
              setRedChatInput,
              sendRedChatMessage,
              redChatLoading,
              redScreenState,
              redVideoRef,
              startRedScreenShare,
              stopRedScreenShare,
              analyzeRedScreen,
              redChatEndRef,
            )}

            {/* Blue Team Interface */}
            {renderAgentInterface(
              "blue",
              blueActiveTab,
              setBlueActiveTab,
              blueChatMessages,
              blueChatInput,
              setBlueChatInput,
              sendBlueChatMessage,
              blueChatLoading,
              blueScreenState,
              blueVideoRef,
              startBlueScreenShare,
              stopBlueScreenShare,
              analyzeBlueScreen,
              blueChatEndRef,
            )}
          </div>
        </motion.div>

        {/* Simulation Log */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30">
            <div className="p-6">
              <h2 className="text-xl font-semibold text-purple-300 mb-4">Simulation Log</h2>
              <div className="bg-black rounded-lg p-4 h-64 overflow-y-auto font-mono text-sm">
                {logs.length === 0 ? (
                  <div className="text-gray-500">Waiting for simulation to start...</div>
                ) : (
                  logs.map((log) => (
                    <div key={log.id} className="mb-1">
                      <span className="text-gray-500">[{log.timestamp}]</span>{" "}
                      <span className={getLogTypeColor(log.type)}>{getLogTypePrefix(log.type)}</span>{" "}
                      <span className="text-gray-300">{log.message}</span>
                    </div>
                  ))
                )}
                <div ref={logsEndRef} />
              </div>
            </div>
          </Card>
        </motion.div>
        </div>
      </div>
    </div>
  )
}
