"use client"

import { useState, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  MessageSquare,
  Trash2,
  RefreshCw,
  Clock,
  Search,
  Plus,
  Loader2,
  X,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useOpenClawConnection } from "@/hooks/useOpenClawConnection"
import { useSessionsStore } from "@/stores/openclawSessionsStore"
import { useChatStore } from "@/stores/openclawChatStore"
import type { GatewaySessionRow } from "@/lib/openclaw/types"

interface OpenClawSessionsViewProps {
  className?: string
}

function formatTime(ts: number | null): string {
  if (!ts) return "Never"
  const date = new Date(ts)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return "Just now"
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

function getTokenCount(session: GatewaySessionRow): string {
  if (!session.totalTokens) return "—"
  if (session.totalTokens >= 1000000) return `${(session.totalTokens / 1000000).toFixed(1)}M`
  if (session.totalTokens >= 1000) return `${(session.totalTokens / 1000).toFixed(1)}K`
  return session.totalTokens.toString()
}

export function OpenClawSessionsView({ className }: OpenClawSessionsViewProps) {
  const { client, isConnected } = useOpenClawConnection()
  const { sessions, activeSessionKey, setActiveSession, setSessions, setLoading, setError, removeSession, clearSessions } = useSessionsStore()
  const clearMessages = useChatStore((s) => s.setMessages)

  const [searchQuery, setSearchQuery] = useState("")
  const [selectedSession, setSelectedSession] = useState<GatewaySessionRow | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null)
  const [loading, setLoadingState] = useState(false)

  // Load sessions on mount
  useEffect(() => {
    if (isConnected && client) {
      loadSessions()
    }
  }, [isConnected, client])

  const loadSessions = useCallback(async () => {
    if (!client || !client.connected) return
    setLoadingState(true)
    try {
      const result = await client.listSessions()
      if (result.type === "res" && result.ok) {
        const payload = result.payload as { sessions: GatewaySessionRow[] }
        if (payload?.sessions) {
          setSessions({
            ts: Date.now(),
            path: "",
            count: payload.sessions.length,
            defaults: { model: null, contextTokens: 0 },
            sessions: payload.sessions,
          })
        }
      }
    } catch (e) {
      console.error("[Sessions] Failed to load:", e)
      setError("Failed to load sessions")
    } finally {
      setLoadingState(false)
    }
  }, [client, isConnected])

  const handleReset = useCallback(async (sessionKey: string) => {
    if (!client || !client.connected) return
    try {
      await client.resetSession(sessionKey)
      // Reload sessions
      loadSessions()
    } catch (e) {
      console.error("[Sessions] Failed to reset:", e)
    }
  }, [client, loadSessions])

  const handleDelete = useCallback(async () => {
    if (!client || !client.connected || !sessionToDelete) return
    try {
      await client.deleteSession(sessionToDelete)
      removeSession(sessionToDelete)
      if (activeSessionKey === sessionToDelete) {
        setActiveSession("")
        clearMessages([])
      }
      setDeleteDialogOpen(false)
      setSessionToDelete(null)
    } catch (e) {
      console.error("[Sessions] Failed to delete:", e)
    }
  }, [client, sessionToDelete, activeSessionKey, removeSession, setActiveSession])

  const handleSelect = useCallback(
    (session: GatewaySessionRow) => {
      setSelectedSession(session)
      setActiveSession(session.key)
      if (isConnected && client) {
        client.switchSession(session.key)
      }
    },
    [isConnected, client, setActiveSession],
  )

  const filteredSessions = sessions.filter((s) => {
    const query = searchQuery.toLowerCase()
    if (!query) return true
    const displayName = s.displayName || s.key || ""
    return displayName.toLowerCase().includes(query)
  })

  return (
    <div className={cn("flex h-full", className)}>
      {/* Session list */}
      <div className="w-80 border-r flex flex-col">
        {/* Header */}
        <div className="p-3 border-b space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-medium flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-primary" />
              Sessions
            </h2>
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={loadSessions}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search sessions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 pl-8 text-sm"
            />
          </div>
        </div>

        {/* Session list */}
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {loading || !isConnected ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : filteredSessions.length === 0 ? (
              <div className="text-center text-sm text-muted-foreground py-8">
                {searchQuery ? "No matching sessions" : "No sessions yet"}
              </div>
            ) : (
              filteredSessions
                .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
                .map((session) => (
                  <button
                    key={session.key}
                    className={cn(
                      "w-full flex flex-col items-start gap-1 px-3 py-2 rounded-lg text-left transition-colors",
                      session.key === activeSessionKey
                        ? "bg-muted border"
                        : "hover:bg-muted/50 border border-transparent"
                    )}
                    onClick={() => handleSelect(session)}
                  >
                    <div className="flex items-center gap-2 w-full">
                      <span className="text-sm font-medium truncate flex-1">
                        {session.displayName || session.key.replace("agent:main:", "")}
                      </span>
                      {session.key === activeSessionKey && (
                        <Badge variant="secondary" className="text-xs shrink-0">
                          Active
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 w-full text-xs text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatTime(session.updatedAt)}</span>
                      {session.totalTokens && (
                        <>
                          <span>·</span>
                          <span>{getTokenCount(session)} tokens</span>
                        </>
                      )}
                    </div>
                  </button>
                ))
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Session detail */}
      <div className="flex-1 flex flex-col">
        {selectedSession ? (
          <div className="flex flex-col h-full">
            {/* Detail header */}
            <div className="p-4 border-b">
              <h3 className="font-medium mb-1">
                {selectedSession.displayName || selectedSession.key.replace("agent:main:", "")}
              </h3>
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span>Key: <code className="bg-muted px-1 rounded">{selectedSession.key}</code></span>
                {selectedSession.kind && selectedSession.kind !== "unknown" && (
                  <span>Kind: {selectedSession.kind}</span>
                )}
                {selectedSession.model && (
                  <span>Model: {selectedSession.model}</span>
                )}
              </div>
            </div>

            {/* Detail body */}
            <ScrollArea className="flex-1 p-4">
              <div className="space-y-4">
                <div>
                  <h4 className="text-sm font-medium mb-2">Statistics</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-muted/50 rounded-lg p-3">
                      <div className="text-xs text-muted-foreground">Input tokens</div>
                      <div className="text-lg font-medium">{selectedSession.inputTokens ?? "—"}</div>
                    </div>
                    <div className="bg-muted/50 rounded-lg p-3">
                      <div className="text-xs text-muted-foreground">Output tokens</div>
                      <div className="text-lg font-medium">{selectedSession.outputTokens ?? "—"}</div>
                    </div>
                    <div className="bg-muted/50 rounded-lg p-3">
                      <div className="text-xs text-muted-foreground">Total tokens</div>
                      <div className="text-lg font-medium">{getTokenCount(selectedSession)}</div>
                    </div>
                    <div className="bg-muted/50 rounded-lg p-3">
                      <div className="text-xs text-muted-foreground">Last updated</div>
                      <div className="text-lg font-medium">{formatTime(selectedSession.updatedAt)}</div>
                    </div>
                  </div>
                </div>

                {selectedSession.thinkingLevel && (
                  <div>
                    <h4 className="text-sm font-medium mb-2">Settings</h4>
                    <div className="bg-muted/50 rounded-lg p-3 space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Thinking level</span>
                        <span>{selectedSession.thinkingLevel}</span>
                      </div>
                      {selectedSession.reasoningLevel && (
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Reasoning level</span>
                          <span>{selectedSession.reasoningLevel}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </ScrollArea>

            {/* Actions */}
            <div className="p-4 border-t flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleReset(selectedSession.key)}
              >
                <RefreshCw className="h-3.5 w-3.5 mr-1" />
                Reset
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => {
                  setSessionToDelete(selectedSession.key)
                  setDeleteDialogOpen(true)
                }}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Delete
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <MessageSquare className="h-10 w-10 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-medium mb-1">Select a session</h3>
            <p className="text-sm text-muted-foreground">
              Choose a session from the list to view details
            </p>
          </div>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Session</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this session? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
