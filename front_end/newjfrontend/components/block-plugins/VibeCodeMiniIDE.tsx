"use client"

import React, { useState, useCallback, useRef, useEffect } from "react"
import dynamic from "next/dynamic"
import {
  ArrowLeft, FolderTree, Code, Terminal as TerminalIcon,
  Bot, Play, Square, Loader2, GripVertical, GripHorizontal, Sparkles, RefreshCw,
  PanelLeftClose, PanelLeftOpen, MonitorPlay, Send, Trash2,
  CheckCircle, XCircle, Clock,
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

interface ExecutionRun {
  id: string
  file: string
  command: string
  stdout: string
  stderr: string
  exitCode: number
  executionTimeMs: number
  timestamp: Date
  status: "running" | "done" | "error"
  stdinProvided?: string
}

type BottomTab = "terminal" | "output" | "ai"

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
  const [selectedFile, setSelectedFile] = useState<ContainerFile | null>(null)
  const [sidebarWidth, setSidebarWidth] = useState(fullPage ? 220 : 180)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [bottomPercent, setBottomPercent] = useState(30)
  const [bottomTab, setBottomTab] = useState<BottomTab>("terminal")
  const containerRef = useRef<HTMLDivElement>(null)
  const isDraggingSidebar = useRef(false)
  const isDraggingBottom = useRef(false)

  // Execution / Output state
  const [execRuns, setExecRuns] = useState<ExecutionRun[]>([])
  const [isExecuting, setIsExecuting] = useState(false)
  const [stdinInput, setStdinInput] = useState("")
  const outputEndRef = useRef<HTMLDivElement>(null)

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

  // Auto-scroll output
  useEffect(() => {
    outputEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [execRuns])

  const handleFileSelect = useCallback((filePath: string, content: string) => {
    const name = filePath.split("/").pop() || filePath
    setSelectedFile({ name, type: "file", size: content.length, permissions: "", path: filePath })
  }, [])

  // ── Execute file via /api/vibecode/exec ──
  const executeFile = useCallback(async (filePath?: string) => {
    const rawFile = filePath || selectedFile?.path
    if (!rawFile || !sessionId || isExecuting) return

    // Strip /workspace/ prefix — backend validator rejects absolute paths
    // and _build_file_command re-adds the prefix automatically
    const file = rawFile.replace(/^\/workspace\//, "")

    setIsExecuting(true)
    setBottomTab("output")

    const runId = Date.now().toString()
    const pendingRun: ExecutionRun = {
      id: runId,
      file: rawFile,
      command: "",
      stdout: "",
      stderr: "",
      exitCode: -1,
      executionTimeMs: 0,
      timestamp: new Date(),
      status: "running",
      stdinProvided: stdinInput || undefined,
    }
    setExecRuns((prev) => [...prev, pendingRun])

    try {
      const body: Record<string, unknown> = {
        session_id: sessionId,
        file,
      }

      // If user provided stdin, pipe it via a shell command
      if (stdinInput.trim()) {
        const ext = rawFile.split(".").pop()?.toLowerCase() || ""
        const langMap: Record<string, string> = {
          py: "python3", js: "node", ts: "npx ts-node", sh: "bash",
          go: "go run", rs: "rustc", java: "java", c: "gcc", cpp: "g++",
        }
        const runner = langMap[ext] || "python3"
        const escapedInput = stdinInput.replace(/'/g, "'\\''")
        body.cmd = `printf '${escapedInput}\\n' | ${runner} '/workspace/${file}'`
        delete body.file
      }

      const res = await fetch("/api/vibecode/exec", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(errData.detail || `Execution failed (${res.status})`)
      }

      const data = await res.json()

      setExecRuns((prev) =>
        prev.map((r) =>
          r.id === runId
            ? {
                ...r,
                command: data.command || "",
                stdout: data.stdout || "",
                stderr: data.stderr || "",
                exitCode: data.exit_code ?? -1,
                executionTimeMs: data.execution_time_ms ?? 0,
                status: (data.exit_code ?? -1) === 0 ? "done" : "error",
              }
            : r
        )
      )
    } catch (err) {
      setExecRuns((prev) =>
        prev.map((r) =>
          r.id === runId
            ? {
                ...r,
                stderr: err instanceof Error ? err.message : String(err),
                exitCode: -1,
                status: "error",
              }
            : r
        )
      )
    } finally {
      setIsExecuting(false)
      setStdinInput("")
    }
  }, [sessionId, selectedFile, isExecuting, stdinInput])

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

  // Drag to resize sidebar (horizontal)
  const handleSidebarDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDraggingSidebar.current = true

    const handleMove = (me: MouseEvent) => {
      if (!isDraggingSidebar.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const newWidth = me.clientX - rect.left
      setSidebarWidth(Math.max(120, Math.min(400, newWidth)))
    }

    const handleUp = () => {
      isDraggingSidebar.current = false
      document.removeEventListener("mousemove", handleMove)
      document.removeEventListener("mouseup", handleUp)
    }

    document.addEventListener("mousemove", handleMove)
    document.addEventListener("mouseup", handleUp)
  }, [])

  // Drag to resize bottom pane (vertical)
  const handleBottomDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDraggingBottom.current = true

    const handleMove = (me: MouseEvent) => {
      if (!isDraggingBottom.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const headerHeight = 36
      const contentHeight = rect.height - headerHeight
      const fromTop = me.clientY - rect.top - headerHeight
      const bottomPct = ((contentHeight - fromTop) / contentHeight) * 100
      setBottomPercent(Math.max(15, Math.min(60, bottomPct)))
    }

    const handleUp = () => {
      isDraggingBottom.current = false
      document.removeEventListener("mousemove", handleMove)
      document.removeEventListener("mouseup", handleUp)
    }

    document.addEventListener("mousemove", handleMove)
    document.addEventListener("mouseup", handleUp)
  }, [])

  const bottomTabs: { id: BottomTab; icon: React.ReactNode; label: string; badge?: number }[] = [
    { id: "terminal", icon: <TerminalIcon className="w-3.5 h-3.5" />, label: "Terminal" },
    {
      id: "output",
      icon: <MonitorPlay className="w-3.5 h-3.5" />,
      label: "Output",
      badge: execRuns.filter((r) => r.status === "running").length || undefined,
    },
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
          onClick={() => setSidebarCollapsed((v) => !v)}
          title={sidebarCollapsed ? "Show files" : "Hide files"}
        >
          {sidebarCollapsed ? <PanelLeftOpen className="w-3.5 h-3.5" /> : <PanelLeftClose className="w-3.5 h-3.5" />}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={isContainerRunning ? onContainerStop : onContainerStart}
          title={isContainerRunning ? "Stop" : "Start"}
        >
          {isContainerRunning ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </Button>
      </div>

      {/* Main IDE body: sidebar + editor/terminal */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* ── File Tree Sidebar ── */}
        {!sidebarCollapsed && (
          <>
            <div
              className="shrink-0 flex flex-col min-h-0 border-r border-border bg-muted/20 overflow-hidden"
              style={{ width: sidebarWidth }}
            >
              <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border shrink-0 bg-muted/30">
                <FolderTree className="w-3.5 h-3.5 text-muted-foreground" />
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Explorer</span>
              </div>
              <div className="flex-1 overflow-y-auto overflow-x-hidden">
                <MonacoVibeFileTree
                  sessionId={sessionId}
                  isContainerRunning={isContainerRunning}
                  onFileSelect={handleFileSelect}
                  compact
                  className="h-full"
                />
              </div>
            </div>

            {/* Sidebar resize handle */}
            <div
              className="w-1 shrink-0 cursor-col-resize flex items-center justify-center hover:bg-primary/20 transition-colors group"
              onMouseDown={handleSidebarDragStart}
            >
              <GripVertical className="w-3 h-3 text-transparent group-hover:text-muted-foreground" />
            </div>
          </>
        )}

        {/* ── Right side: Editor (top) + Bottom pane ── */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">

          {/* Editor pane */}
          <div className="min-h-0 overflow-hidden" style={{ flexBasis: `${100 - bottomPercent}%`, flexGrow: 0, flexShrink: 0 }}>
            {selectedFile ? (
              <VibeContainerCodeEditor
                sessionId={sessionId}
                selectedFile={selectedFile}
                onExecute={(filePath) => executeFile(filePath)}
                compact
                className="h-full"
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
                <Code className="w-8 h-8 opacity-30" />
                <p className="text-xs">Select a file to start editing</p>
              </div>
            )}
          </div>

          {/* Bottom drag handle */}
          <div
            className="h-1.5 shrink-0 cursor-row-resize flex items-center justify-center bg-muted/50 hover:bg-primary/20 transition-colors group border-y border-border"
            onMouseDown={handleBottomDragStart}
          >
            <GripHorizontal className="w-4 h-4 text-transparent group-hover:text-muted-foreground" />
          </div>

          {/* Bottom pane */}
          <div className="min-h-0 overflow-hidden flex flex-col" style={{ flexBasis: `${bottomPercent}%`, flexGrow: 0, flexShrink: 0 }}>
            {/* Bottom Tab Bar */}
            <div className="flex items-center border-b border-border shrink-0 bg-muted/30">
              {bottomTabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setBottomTab(tab.id)}
                  className={`flex items-center gap-1.5 px-3 py-1 text-xs font-medium transition-colors border-b-2 ${
                    bottomTab === tab.id
                      ? "border-primary text-foreground bg-background"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                  {tab.badge && (
                    <span className="ml-1 px-1 py-0 text-[9px] rounded-full bg-yellow-500/20 text-yellow-400 font-bold">
                      {tab.badge}
                    </span>
                  )}
                </button>
              ))}

              {/* Right-side actions for Output tab */}
              {bottomTab === "output" && (
                <div className="ml-auto flex items-center gap-1 pr-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                    onClick={() => selectedFile && executeFile()}
                    disabled={!selectedFile || isExecuting || !isContainerRunning}
                    title="Re-run"
                  >
                    {isExecuting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    onClick={() => setExecRuns([])}
                    title="Clear output"
                  >
                    <Trash2 className="w-3 h-3" />
                  </Button>
                </div>
              )}
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
              ) : bottomTab === "output" ? (
                <OutputPanel
                  runs={execRuns}
                  isExecuting={isExecuting}
                  stdinInput={stdinInput}
                  onStdinChange={setStdinInput}
                  onSendStdin={() => selectedFile && executeFile()}
                  canRun={!!selectedFile && isContainerRunning && !isExecuting}
                  outputEndRef={outputEndRef}
                />
              ) : (
                <div className="flex flex-col h-full">
                  <div className="flex items-center gap-2 px-2 py-1 border-b border-border bg-muted/30 shrink-0">
                    <Sparkles className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                    <select
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      className="flex-1 bg-background border border-border text-foreground text-xs rounded px-2 py-0.5 focus:outline-none focus:border-purple-500 truncate"
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
      </div>
    </div>
  )
}


// ─── Output Panel ────────────────────────────────────────────────────────────

interface OutputPanelProps {
  runs: ExecutionRun[]
  isExecuting: boolean
  stdinInput: string
  onStdinChange: (v: string) => void
  onSendStdin: () => void
  canRun: boolean
  outputEndRef: React.RefObject<HTMLDivElement | null>
}

function OutputPanel({
  runs,
  isExecuting,
  stdinInput,
  onStdinChange,
  onSendStdin,
  canRun,
  outputEndRef,
}: OutputPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="flex flex-col h-full bg-[#0d1117]">
      {/* Output scroll area */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2 font-mono text-xs leading-relaxed">
        {runs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground/50 gap-1">
            <MonitorPlay className="w-6 h-6" />
            <p className="text-[11px]">Run a file to see output here</p>
            <p className="text-[10px] text-muted-foreground/30">Ctrl+Enter in the editor or press Run</p>
          </div>
        ) : (
          runs.map((run) => (
            <div key={run.id} className="mb-3 last:mb-0">
              {/* Run header */}
              <div className="flex items-center gap-2 mb-1 text-[10px] text-muted-foreground select-none">
                {run.status === "running" ? (
                  <Loader2 className="w-3 h-3 animate-spin text-yellow-400" />
                ) : run.exitCode === 0 ? (
                  <CheckCircle className="w-3 h-3 text-green-400" />
                ) : (
                  <XCircle className="w-3 h-3 text-red-400" />
                )}
                <span className="text-blue-400 truncate max-w-[60%]">{run.file.split("/").pop()}</span>
                {run.status !== "running" && (
                  <>
                    <span className={run.exitCode === 0 ? "text-green-400" : "text-red-400"}>
                      exit {run.exitCode}
                    </span>
                    <span className="flex items-center gap-0.5 text-muted-foreground/60">
                      <Clock className="w-2.5 h-2.5" />
                      {run.executionTimeMs}ms
                    </span>
                  </>
                )}
                {run.stdinProvided && (
                  <span className="text-purple-400">stdin</span>
                )}
                <span className="text-muted-foreground/40 ml-auto">
                  {run.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
              </div>

              {/* Command */}
              {run.command && (
                <div className="text-muted-foreground/50 mb-0.5 truncate">
                  <span className="text-green-500">$</span> {run.command}
                </div>
              )}

              {/* Stdout */}
              {run.stdout && (
                <pre className="whitespace-pre-wrap break-words text-[#d4d4d4]">{run.stdout}</pre>
              )}

              {/* Stderr */}
              {run.stderr && (
                <pre className="whitespace-pre-wrap break-words text-red-400">{run.stderr}</pre>
              )}

              {/* Running indicator */}
              {run.status === "running" && (
                <div className="flex items-center gap-1.5 text-yellow-400 mt-1">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>Running...</span>
                </div>
              )}
            </div>
          ))
        )}
        <div ref={outputEndRef} />
      </div>

      {/* Stdin input bar */}
      <div className="shrink-0 border-t border-border/50 bg-[#161b22] px-2 py-1.5 flex items-center gap-2">
        <span className="text-[10px] text-muted-foreground/50 shrink-0 select-none">stdin</span>
        <input
          ref={inputRef}
          type="text"
          value={stdinInput}
          onChange={(e) => onStdinChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canRun) {
              e.preventDefault()
              onSendStdin()
            }
          }}
          placeholder={isExecuting ? "Executing..." : "Type input for the program, then press Run..."}
          disabled={isExecuting}
          className="flex-1 bg-transparent text-xs text-[#d4d4d4] font-mono placeholder:text-muted-foreground/30 focus:outline-none disabled:opacity-50"
        />
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0 text-muted-foreground hover:text-primary shrink-0"
          onClick={onSendStdin}
          disabled={!canRun}
          title="Run with input"
        >
          {isExecuting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </Button>
      </div>
    </div>
  )
}
