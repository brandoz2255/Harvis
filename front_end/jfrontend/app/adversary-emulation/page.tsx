"use client"

import type React from "react"

import { useState, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import { ArrowLeft, Play, Square, Settings, Monitor, MessageSquare, Terminal, ScanEye } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import Link from "next/link"
import Image from "next/image"
import Aurora from "@/components/Aurora"

interface LogEntry {
  id: string
  timestamp: string
  type: "system" | "red-team" | "blue-team" | "info"
  message: string
}

interface EmulationState {
  isRunning: boolean
  model: string
  scenario: string
  sessionId: string | null
}

export default function AdversaryEmulationPage() {
  const [activeTab, setActiveTab] = useState<"screen" | "chat" | "commands">("screen")
  const [emulationState, setEmulationState] = useState<EmulationState>({
    isRunning: false,
    model: "gpt-4o",
    scenario: "network-intrusion",
    sessionId: null,
  })

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [chatMessages, setChatMessages] = useState<
    Array<{ role: "user" | "assistant"; content: string; timestamp: string }>
  >([])
  const [chatInput, setChatInput] = useState("")
  const [screenFeed, setScreenFeed] = useState<string>("/placeholder.svg?height=400&width=600")

  const logsEndRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)

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
    scrollToBottom(chatEndRef)
  }, [chatMessages])

  // Simulate real-time log updates
  useEffect(() => {
    if (!emulationState.isRunning) return

    const interval = setInterval(() => {
      const sampleLogs = [
        { type: "system" as const, message: "Scanning network for open ports..." },
        { type: "red-team" as const, message: "Found open SSH port on 192.168.1.100" },
        { type: "red-team" as const, message: "Attempting brute force attack..." },
        { type: "system" as const, message: "Login attempt detected from external IP" },
        { type: "red-team" as const, message: "Successfully gained access to target system" },
        { type: "blue-team" as const, message: "Anomalous login detected, investigating..." },
        { type: "red-team" as const, message: "Escalating privileges using CVE-2023-1234" },
        { type: "system" as const, message: "Privilege escalation attempt blocked" },
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
      const response = await fetch("/api/start-emulation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: emulationState.model,
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

        // Add initial log entry
        const initialLog: LogEntry = {
          id: Date.now().toString(),
          timestamp: new Date().toLocaleTimeString(),
          type: "system",
          message: `Adversary emulation started with ${emulationState.model} model using ${emulationState.scenario} scenario`,
        }
        setLogs([initialLog])
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
      message: "Adversary emulation stopped",
    }
    setLogs((prev) => [...prev, stopLog])
  }

  const sendChatMessage = async () => {
    if (!chatInput.trim() || !emulationState.isRunning) return

    const userMessage = {
      role: "user" as const,
      content: chatInput,
      timestamp: new Date().toLocaleTimeString(),
    }

    setChatMessages((prev) => [...prev, userMessage])
    setChatInput("")

    try {
      const response = await fetch("/api/send-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: emulationState.sessionId,
          message: chatInput,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const assistantMessage = {
          role: "assistant" as const,
          content: data.response,
          timestamp: new Date().toLocaleTimeString(),
        }
        setChatMessages((prev) => [...prev, assistantMessage])
      }
    } catch (error) {
      console.error("Failed to send message:", error)
    }
  }

  const handleAnalyzeAndRespond = async () => {
    if (!screenFeed) return;

    try {
      const response = await fetch("/api/analyze-and-respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: screenFeed }),
      });

      if (response.ok) {
        const data = await response.json();
        console.log("Analysis response:", data);
        // Add the response to the chat
        const assistantMessage = {
          role: "assistant" as const,
          content: data.llm_response || data.commentary,
          timestamp: new Date().toLocaleTimeString(),
        };
        setChatMessages((prev) => [...prev, assistantMessage]);
      }
    } catch (error) {
      console.error("Failed to analyze and respond:", error);
    }
  };

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

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#DC2626', '#B91C1C', '#7F1D1D']}
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
          className="flex items-center justify-between mb-8"
        >
          <div className="flex items-center space-x-4">
            <Link href="/">
              <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Dashboard
              </Button>
            </Link>
            <h1 className="text-3xl font-bold text-white">Adversary Emulation Mode</h1>
          </div>
          <div className="flex items-center space-x-2">
            <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300" onClick={handleAnalyzeAndRespond}>
              <ScanEye className="w-4 h-4 mr-2" />
              Analyze and Respond
            </Button>
            <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300">
              <Settings className="w-4 h-4 mr-2" />
              Settings
            </Button>
          </div>
        </motion.div>

        {/* Simulation Configuration */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card className="bg-gray-900/50 backdrop-blur-sm border-red-500/30 mb-6">
            <div className="p-6">
              <h2 className="text-xl font-semibold text-red-300 mb-4">Simulation Configuration</h2>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">AI Model</label>
                  <select
                    value={emulationState.model}
                    onChange={(e) => setEmulationState((prev) => ({ ...prev, model: e.target.value }))}
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
                  <label className="block text-sm font-medium text-gray-300 mb-2">Scenario</label>
                  <select
                    value={emulationState.scenario}
                    onChange={(e) => setEmulationState((prev) => ({ ...prev, scenario: e.target.value }))}
                    disabled={emulationState.isRunning}
                    className="w-full bg-gray-800 border border-gray-600 text-white rounded px-3 py-2 focus:border-red-500 focus:outline-none disabled:opacity-50"
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

        {/* Main Interface */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <Card className="bg-gray-900/50 backdrop-blur-sm border-red-500/30 mb-6">
            <div className="p-6">
              <h2 className="text-xl font-semibold text-red-300 mb-4">Agent Interface</h2>

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
                        ? "bg-red-600 text-white"
                        : "bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <tab.icon className="w-4 h-4 mr-2" />
                    {tab.label}
                  </Button>
                ))}
              </div>

              {/* Tab Content */}
              <div className="bg-gray-800 rounded-lg p-4 h-96">
                {activeTab === "screen" && (
                  <div className="h-full flex items-center justify-center">
                    <Image
                      src={screenFeed || "/placeholder.svg"}
                      alt="Agent Screen Feed"
                      className="max-w-full max-h-full rounded border border-gray-600"
                      width={800}
                      height={600}
                      style={{ objectFit: "contain" }}
                    />
                  </div>
                )}

                {activeTab === "chat" && (
                  <div className="h-full flex flex-col">
                    <div className="flex-1 overflow-y-auto mb-4 space-y-2">
                      {chatMessages.map((message, index) => (
                        <div
                          key={index}
                          className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                        >
                          <div
                            className={`max-w-[80%] p-2 rounded text-sm ${
                              message.role === "user" ? "bg-red-600 text-white" : "bg-gray-700 text-gray-100"
                            }`}
                          >
                            <p>{message.content}</p>
                            <span className="text-xs opacity-70">{message.timestamp}</span>
                          </div>
                        </div>
                      ))}
                      <div ref={chatEndRef} />
                    </div>
                    <div className="flex space-x-2">
                      <Input
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyPress={(e) => e.key === "Enter" && sendChatMessage()}
                        placeholder="Send message to AI agent..."
                        className="flex-1 bg-gray-700 border-gray-600 text-white"
                        disabled={!emulationState.isRunning}
                      />
                      <Button
                        onClick={sendChatMessage}
                        disabled={!emulationState.isRunning || !chatInput.trim()}
                        className="bg-red-600 hover:bg-red-700 text-white"
                      >
                        Send
                      </Button>
                    </div>
                  </div>
                )}

                {activeTab === "commands" && (
                  <div className="h-full">
                    <div className="bg-black rounded p-3 h-full overflow-y-auto font-mono text-sm">
                      <div className="text-green-400 mb-2">$ Agent Command Interface</div>
                      <div className="text-gray-400 mb-4">Real-time command execution log:</div>
                      {logs
                        .filter((log) => log.type === "red-team" || log.type === "system")
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
        </motion.div>

        {/* Simulation Log */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <Card className="bg-gray-900/50 backdrop-blur-sm border-red-500/30">
            <div className="p-6">
              <h2 className="text-xl font-semibold text-red-300 mb-4">Simulation Log</h2>
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
