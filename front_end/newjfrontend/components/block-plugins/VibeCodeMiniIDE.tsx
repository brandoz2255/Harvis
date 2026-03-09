"use client"

import React, { useState, useCallback, useRef, useEffect } from "react"
import dynamic from "next/dynamic"
import { useRouter } from "next/navigation"
import {
  ArrowLeft, Maximize2, FolderTree, Code, Terminal as TerminalIcon,
  Bot, Play, Square, Loader2, GripHorizontal, Sparkles, RefreshCw
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import MonacoVibeFileTree from "@/components/vibecode/MonacoVibeFileTree"
import AIAssistantPanel from "@/components/vibecode/AIAssistantPanel"

const VibeTerminal = dynamic(
  () => import("@/components/vibecode/VibeTerminal"),
  { ssr: false }
)

const VibeContainerCodeEditor = dynamic(
  () => import("@/components/vibecode/VibeContainerCodeEditor"),
  { ssr: false, loading: () => <div className="flex-1 flex items-center justify-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div> }
)

interface ContainerFile {
  name: string
  type: "file" | "directory"
  size: number
  permissions: string
  path: string
}

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  reasoning?: string
}

type TopTab = "files" | "editor"
type BottomTab = "terminal" | "ai"

interface VibeCodeMiniIDEProps {
  sessionId: string
  sessionName: string
  isContainerRunning: boolean
  onContainerStart: () => Promise<void>
  onContainerStop: () => Promise<void>
  onBack: () => void
  fullPage?: boolean
}

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (token) headers["Authorization"] = `Bearer ${token}`
  return headers
}

export default function VibeCodeMiniIDE({
  sessionId,
  sessionName,
  isContainerRunning,
  onContainerStart,
  onContainerStop,
  onBack,
  fullPage = false,
}: VibeCodeMiniIDEProps) {
  const router = useRouter()
  const [topTab, setTopTab] = useState<TopTab>("files")
  const [bottomTab, setBottomTab] = useState<BottomTab>("terminal")
  const [selectedFile, setSelectedFile] = useState<ContainerFile | null>(null)
  const [splitPercent, setSplitPercent] = useState(50)
  const containerRef = useRef<HTMLDivElement>(null)
  const isDragging = useRef(false)

  // AI chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [isAIProcessing, setIsAIProcessing] = useState(false)
  const [selectedModel, setSelectedModel] = useState("llama3.2:3b")
  const [availableModels, setAvailableModels] = useState<Array<{ name: string; provider: string; type: string }>>([])

  // Load models
  useEffect(() => {
    const loadModels = async () => {
      try {
        const res = await fetch("/api/vibecode/ai/models", { headers: getAuthHeaders() })
        if (res.ok) {
          const data = await res.json()
          setAvailableModels(data.models || [])
          if (data.models?.length > 0) setSelectedModel(data.models[0].name)
        }
      } catch {}
    }
    loadModels()
  }, [])

  const handleFileSelect = useCallback((filePath: string, content: string) => {
    const name = filePath.split("/").pop() || filePath
    setSelectedFile({ name, type: "file", size: content.length, permissions: "", path: filePath })
    setTopTab("editor")
  }, [])

  const handleSendAIMessage = useCallback(async (message: string) => {
    const userMsg: ChatMessage = { role: "user", content: message, timestamp: new Date() }
    setChatMessages((prev) => [...prev, userMsg])
    setIsAIProcessing(true)

    try {
      const res = await fetch("/api/vibecode/ai/chat", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          session_id: sessionId,
          message,
          model: selectedModel,
          context: { current_file: selectedFile?.path },
        }),
      })

      if (res.ok) {
        const data = await res.json()
        setChatMessages((prev) => [
          ...prev,
          { role: "assistant", content: data.response || data.message || "No response", timestamp: new Date(), reasoning: data.reasoning },
        ])
      }
    } catch {
      setChatMessages((prev) => [...prev, { role: "assistant", content: "Failed to get AI response", timestamp: new Date() }])
    } finally {
      setIsAIProcessing(false)
    }
  }, [sessionId, selectedModel, selectedFile])

  // Drag to resize split
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true

    const handleMove = (me: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const percent = ((me.clientY - rect.top) / rect.height) * 100
      setSplitPercent(Math.max(20, Math.min(80, percent)))
    }

    const handleUp = () => {
      isDragging.current = false
      document.removeEventListener("mousemove", handleMove)
      document.removeEventListener("mouseup", handleUp)
    }

    document.addEventListener("mousemove", handleMove)
    document.addEventListener("mouseup", handleUp)
  }, [])

  const topTabs: { id: TopTab; icon: React.ReactNode; label: string }[] = [
    { id: "files", icon: <FolderTree className="w-3.5 h-3.5" />, label: "Files" },
    { id: "editor", icon: <Code className="w-3.5 h-3.5" />, label: "Editor" },
  ]

  const bottomTabs: { id: BottomTab; icon: React.ReactNode; label: string }[] = [
    { id: "terminal", icon: <TerminalIcon className="w-3.5 h-3.5" />, label: "Terminal" },
    { id: "ai", icon: <Bot className="w-3.5 h-3.5" />, label: "AI" },
  ]

  return (
    <div ref={containerRef} className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border shrink-0">
        <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={onBack} title="Back to sessions">
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <span className="text-sm font-medium truncate flex-1">{sessionName}</span>
        <Badge
          variant="outline"
          className={`text-[10px] px-1.5 py-0 ${
            isContainerRunning ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-muted text-muted-foreground border-border"
          }`}
        >
          {isContainerRunning ? "running" : "stopped"}
        </Badge>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={isContainerRunning ? onContainerStop : onContainerStart}
          title={isContainerRunning ? "Stop" : "Start"}
        >
          {isContainerRunning ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={() => router.push(`/vibecode?session=${sessionId}`)}
          title="Open full IDE"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </Button>
      </div>

      {/* Top Pane */}
      <div style={{ height: `${splitPercent}%` }} className="flex flex-col min-h-0">
        {/* Top Tab Bar */}
        <div className="flex items-center border-b border-border shrink-0 bg-muted/30">
          {topTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setTopTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors border-b-2 ${
                topTab === tab.id
                  ? "border-primary text-foreground bg-background"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Top Content */}
        <div className="flex-1 overflow-hidden">
          {topTab === "files" ? (
            <MonacoVibeFileTree
              sessionId={sessionId}
              isContainerRunning={isContainerRunning}
              onFileSelect={handleFileSelect}
              compact
              className="h-full"
            />
          ) : (
            <VibeContainerCodeEditor
              sessionId={sessionId}
              selectedFile={selectedFile}
              compact
              className="h-full"
            />
          )}
        </div>
      </div>

      {/* Drag Handle */}
      <div
        className="h-2 shrink-0 cursor-row-resize flex items-center justify-center bg-muted/50 hover:bg-primary/20 transition-colors group border-y border-border"
        onMouseDown={handleDragStart}
      >
        <GripHorizontal className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
      </div>

      {/* Bottom Pane */}
      <div style={{ height: `${100 - splitPercent}%` }} className="flex flex-col min-h-0">
        {/* Bottom Tab Bar */}
        <div className="flex items-center border-b border-border shrink-0 bg-muted/30">
          {bottomTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setBottomTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors border-b-2 ${
                bottomTab === tab.id
                  ? "border-primary text-foreground bg-background"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Bottom Content */}
        <div className="flex-1 overflow-hidden">
          {bottomTab === "terminal" ? (
            <VibeTerminal
              sessionId={sessionId}
              isContainerRunning={isContainerRunning}
              onContainerStart={onContainerStart}
              compact
              className="h-full rounded-none border-0"
            />
          ) : (
            <div className="flex flex-col h-full">
              {/* AI Model Selector Bar */}
              <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border bg-muted/30 shrink-0">
                <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="flex-1 bg-background border border-border text-foreground text-xs rounded px-2 py-1 focus:outline-none focus:border-purple-500 truncate"
                >
                  {availableModels.length > 0 ? (
                    availableModels.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name} ({m.provider})
                      </option>
                    ))
                  ) : (
                    <option value={selectedModel}>{selectedModel}</option>
                  )}
                </select>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0 shrink-0"
                  onClick={async () => {
                    try {
                      const res = await fetch("/api/vibecode/ai/models", { headers: getAuthHeaders() })
                      if (res.ok) {
                        const data = await res.json()
                        setAvailableModels(data.models || [])
                      }
                    } catch {}
                  }}
                  title="Refresh models"
                >
                  <RefreshCw className="w-3 h-3" />
                </Button>
              </div>
              <AIAssistantPanel
                sessionId={sessionId}
                containerStatus={isContainerRunning ? "running" : "stopped"}
                selectedFile={selectedFile?.path || null}
                onSendMessage={handleSendAIMessage}
                messages={chatMessages}
                isProcessing={isAIProcessing}
                selectedModel={selectedModel}
                availableModels={availableModels}
                onModelChange={setSelectedModel}
                compact
                className="flex-1 min-h-0"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
