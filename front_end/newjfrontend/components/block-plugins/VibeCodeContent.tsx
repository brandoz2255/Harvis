"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import {
  Plus, ExternalLink, Loader2, Container,
  Play, Square, Trash2, AlertCircle,
  RefreshCw, Code,
} from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import VibeCodeMiniIDE from "./VibeCodeMiniIDE"

interface Session {
  session_id: string
  name: string
  description: string | null
  status: string
  container_id: string | null
  container_status: string | null
  volume_name: string | null
  created_at: string
  updated_at: string
  last_activity: string
}

const STATUS_COLORS: Record<string, string> = {
  running:  "bg-green-500/20 text-green-400 border-green-500/30",
  stopped:  "bg-muted text-muted-foreground border-border",
  starting: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  stopping: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  not_created: "bg-muted text-muted-foreground border-border",
  error:    "bg-red-500/20 text-red-400 border-red-500/30",
}

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (token) headers["Authorization"] = `Bearer ${token}`
  return headers
}

interface VibeCodeContentProps {
  fullPage?: boolean
}

export default function VibeCodeContent({ fullPage = false }: VibeCodeContentProps) {
  const router = useRouter()
  const [sessions, setSessions] = useState<Session[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [newProjectName, setNewProjectName] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [containerStatuses, setContainerStatuses] = useState<Record<string, string>>({})
  const [activeSession, setActiveSession] = useState<Session | null>(null)

  useEffect(() => {
    loadSessions()
  }, [])

  const loadSessions = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/vibecode/sessions", {
        headers: getAuthHeaders(),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Failed to load sessions (${res.status})`)
      }
      const data = await res.json()
      const sessionList: Session[] = data.sessions || []
      setSessions(sessionList)

      for (const s of sessionList) {
        fetchContainerStatus(s.session_id)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load sessions"
      setError(msg)
      setSessions([])
    } finally {
      setIsLoading(false)
    }
  }

  const fetchContainerStatus = async (sessionId: string) => {
    try {
      const res = await fetch(`/api/vibecode/container/${sessionId}/status`, {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        setContainerStatuses((prev) => ({ ...prev, [sessionId]: data.status || "unknown" }))
      }
    } catch {
      // silently fail
    }
  }

  const createSession = async () => {
    if (!newProjectName.trim()) return
    setIsCreating(true)
    setError(null)
    try {
      const res = await fetch("/api/vibecode/sessions/create", {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ name: newProjectName.trim() }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || "Failed to create session")
      }
      setNewProjectName("")
      await loadSessions()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create session"
      setError(msg)
    } finally {
      setIsCreating(false)
    }
  }

  const toggleContainer = async (session: Session, e?: React.MouseEvent) => {
    e?.stopPropagation()
    const currentStatus = containerStatuses[session.session_id] || session.status
    const action = currentStatus === "running" ? "stop" : "start"

    setContainerStatuses((prev) => ({
      ...prev,
      [session.session_id]: action === "start" ? "starting" : "stopping",
    }))

    try {
      let res: Response

      if (action === "start" && (currentStatus === "not_created" || currentStatus === "stopped" || currentStatus === "unknown")) {
        res = await fetch("/api/vibecode/sessions/open", {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({ session_id: session.session_id }),
        })
      } else {
        res = await fetch(`/api/vibecode/container/${session.session_id}/${action}`, {
          method: "POST",
          headers: getAuthHeaders(),
        })
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Failed to ${action} container`)
      }

      await fetchContainerStatus(session.session_id)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : `Failed to ${action}`
      setError(msg)
      await fetchContainerStatus(session.session_id)
    }
  }

  const deleteSession = async (sessionId: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    try {
      const res = await fetch(`/api/vibecode/sessions/delete?session_id=${encodeURIComponent(sessionId)}`, {
        method: "POST",
        headers: getAuthHeaders(),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || "Failed to delete session")
      }
      if (activeSession?.session_id === sessionId) {
        setActiveSession(null)
      }
      await loadSessions()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to delete"
      setError(msg)
    }
  }

  const getDisplayStatus = (session: Session): string => {
    return containerStatuses[session.session_id] || session.status || "stopped"
  }

  const isRunning = (session: Session): boolean => {
    return getDisplayStatus(session) === "running"
  }

  const isActiveRunning = activeSession ? (containerStatuses[activeSession.session_id] === "running") : false

  const handleContainerStart = useCallback(async () => {
    if (!activeSession) return
    await toggleContainer(activeSession)
  }, [activeSession, containerStatuses])

  const handleContainerStop = useCallback(async () => {
    if (!activeSession) return
    await toggleContainer(activeSession)
  }, [activeSession, containerStatuses])

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    } catch {
      return ""
    }
  }

  // If a session is active, show the mini IDE
  if (activeSession) {
    return (
      <VibeCodeMiniIDE
        sessionId={activeSession.session_id}
        sessionName={activeSession.name}
        isContainerRunning={isActiveRunning}
        onContainerStart={handleContainerStart}
        onContainerStop={handleContainerStop}
        onBack={() => setActiveSession(null)}
        fullPage={fullPage}
      />
    )
  }

  // Otherwise show the session list
  return (
    <div className={`flex flex-col h-full p-4 gap-4 ${fullPage ? "max-w-4xl mx-auto" : ""}`}>
      {/* Open IDE Button */}
      <Link href="/vibecode">
        <Button size="sm" className="w-full bg-purple-600 hover:bg-purple-700 text-white">
          <Code className="w-4 h-4 mr-2" />
          Open VibeCode IDE
          <ExternalLink className="w-3 h-3 ml-2" />
        </Button>
      </Link>

      {/* Header actions */}
      <div className="flex gap-2">
        <Input
          value={newProjectName}
          onChange={(e) => setNewProjectName(e.target.value)}
          placeholder="New project name..."
          className="flex-1 text-sm"
          onKeyDown={(e) => e.key === "Enter" && createSession()}
        />
        <Button
          size="sm"
          onClick={createSession}
          disabled={isCreating || !newProjectName.trim()}
          className="shrink-0"
        >
          {isCreating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={loadSessions}
          className="shrink-0"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
            &times;
          </button>
        </div>
      )}

      <div className="flex-1 space-y-2 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-12">
            <Container className="w-8 h-8 mx-auto mb-3 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">No sessions yet</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Create a project to get started</p>
          </div>
        ) : (
          sessions.map((session) => {
            const status = getDisplayStatus(session)
            return (
              <div
                key={session.session_id}
                className={`group rounded-lg border bg-background/50 p-3 transition-colors cursor-pointer ${
                  fullPage ? "p-4" : "p-3"
                } ${
                  isRunning(session)
                    ? "border-green-500/30 hover:border-green-500/50"
                    : "border-border hover:border-primary/30"
                }`}
                onClick={() => setActiveSession(session)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className={`font-medium text-foreground truncate ${fullPage ? "text-base" : "text-sm"}`}>
                      {session.name}
                    </p>
                    {session.description && (
                      <p className="text-xs text-muted-foreground/70 truncate mt-0.5">
                        {session.description}
                      </p>
                    )}
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <Badge
                        variant="outline"
                        className={`text-[10px] px-1.5 py-0 ${STATUS_COLORS[status] || STATUS_COLORS.stopped}`}
                      >
                        {status}
                      </Badge>
                      {fullPage && (
                        <span className="text-[10px] text-muted-foreground">
                          Last active: {formatDate(session.last_activity || session.updated_at)}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={(e) => toggleContainer(session, e)}
                      disabled={status === "starting" || status === "stopping"}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
                      title={isRunning(session) ? "Stop" : "Start"}
                    >
                      {status === "starting" || status === "stopping" ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : isRunning(session) ? (
                        <Square className="w-3.5 h-3.5" />
                      ) : (
                        <Play className="w-3.5 h-3.5" />
                      )}
                    </button>
                    <button
                      onClick={(e) => deleteSession(session.session_id, e)}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                      title="Delete"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
