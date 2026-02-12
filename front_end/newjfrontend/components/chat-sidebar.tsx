"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"
import {
  Search,
  Plus,
  MessageSquare,
  Code2,
  Star,
  Clock,
  ChevronDown,
  Sparkles,
  User,
  Cpu,
  Trash2,
  Loader2,
  Database,
  PanelLeftClose,
  PanelLeftOpen,
  FileText,
  FileSpreadsheet,
  FileType,
  Presentation,
  Globe,
  Box,
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

interface Chat {
  id: string
  title: string
  timestamp: string
  starred?: boolean
}

interface Artifact {
  id: string
  artifact_type: string
  title: string
  description?: string
  status: string
  file_size?: number
  created_at: string
  updated_at: string
}

interface ChatSidebarProps {
  chats: Chat[]
  activeChat: string | null
  onSelectChat: (id: string) => void
  onNewChat: () => void
  onProfileClick?: () => void
  className?: string
}

// Artifact type icons mapping
const ARTIFACT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  spreadsheet: FileSpreadsheet,
  document: FileText,
  pdf: FileType,
  presentation: Presentation,
  website: Globe,
  app: Globe,
  code: Code2,
}

// Type colors for badges
const TYPE_COLORS: Record<string, string> = {
  spreadsheet: "bg-green-500/10 text-green-500",
  document: "bg-blue-500/10 text-blue-500",
  pdf: "bg-red-500/10 text-red-500",
  presentation: "bg-orange-500/10 text-orange-500",
  website: "bg-purple-500/10 text-purple-500",
  app: "bg-purple-500/10 text-purple-500",
  code: "bg-cyan-500/10 text-cyan-500",
}

export function ChatSidebar({
  chats,
  activeChat,
  onSelectChat,
  onNewChat,
  onProfileClick,
  className,
}: ChatSidebarProps) {
  const router = useRouter()
  const [searchQuery, setSearchQuery] = useState("")
  const [expandedSections, setExpandedSections] = useState({
    starred: true,
    recents: true,
    artifacts: true,
  })
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false)
  const [isClearing, setIsClearing] = useState(false)
  const [memoryStats, setMemoryStats] = useState<{
    usage_percent?: number
    free_gb?: number
    allocated_gb?: number
  } | null>(null)
  const [clearMessage, setClearMessage] = useState<string | null>(null)
  const isFetchingStats = useRef(false)
  
  // Minimized state with localStorage persistence
  const [isMinimized, setIsMinimized] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('sidebar-minimized')
      return saved === 'true'
    }
    return false
  })
  
  // Persist minimized state to localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('sidebar-minimized', isMinimized.toString())
    }
  }, [isMinimized])
  
  const toggleMinimize = () => {
    setIsMinimized(!isMinimized)
  }

  // Fetch artifacts
  const fetchArtifacts = async () => {
    try {
      setIsLoadingArtifacts(true)
      const token = localStorage.getItem('token')
      const res = await fetch('/api/artifacts/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      
      if (res.ok) {
        const data = await res.json()
        setArtifacts(data.artifacts || [])
      }
    } catch (error) {
      console.error('Failed to fetch artifacts:', error)
    } finally {
      setIsLoadingArtifacts(false)
    }
  }

  useEffect(() => {
    fetchArtifacts()
    // Refresh artifacts every 30 seconds
    const interval = setInterval(fetchArtifacts, 30000)
    return () => clearInterval(interval)
  }, [])

  const fetchMemoryStats = async () => {
    if (isFetchingStats.current) {
      console.log('[MemoryStats] Skipping fetch: Request already in progress')
      return
    }
    isFetchingStats.current = true
    const startTime = Date.now()
    console.log('[MemoryStats] Starting fetch...')

    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => {
        console.log('[MemoryStats] Aborting request due to timeout (5000ms)')
        controller.abort('timeout')
      }, 5000)

      const res = await fetch('/api/models/memory-pressure', {
        signal: controller.signal
      })
      
      clearTimeout(timeoutId)
      
      if (res.ok) {
        const data = await res.json()
        const duration = Date.now() - startTime
        console.log(`[MemoryStats] Success (${duration}ms):`, data)
        setMemoryStats(data)
      } else {
        console.warn(`[MemoryStats] Failed with status ${res.status}: ${res.statusText}`)
      }
    } catch (error) {
      const duration = Date.now() - startTime
      const err = error as Error
      
      if (err.name === 'AbortError') {
         console.warn(`[MemoryStats] Request aborted after ${duration}ms (Timeout)`)
      } else {
         console.error(`[MemoryStats] Error after ${duration}ms:`, err)
      }
    } finally {
      isFetchingStats.current = false
    }
  }

  const handleClearRAM = async () => {
    setIsClearing(true)
    setClearMessage(null)
    try {
      const res = await fetch('/api/models/unload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_type: 'all' }),
      })

      if (res.ok) {
        const data = await res.json()
        setClearMessage(`Cleared: ${data.unloaded_models?.join(', ') || 'All models'}`)
        await fetchMemoryStats()
      } else {
        setClearMessage('Failed to clear RAM')
      }
    } catch (error) {
      console.error('Failed to clear RAM:', error)
      setClearMessage('Error clearing RAM')
    } finally {
      setIsClearing(false)
      setTimeout(() => setClearMessage(null), 3000)
    }
  }

  useEffect(() => {
    fetchMemoryStats()
    const interval = setInterval(fetchMemoryStats, 30000)
    return () => clearInterval(interval)
  }, [])

  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }))
  }

  const filteredChats = chats.filter((chat) =>
    chat.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const starredChats = filteredChats.filter((chat) => chat.starred)
  const recentChats = filteredChats.filter((chat) => !chat.starred)

  // Get recent chats for minimized view (last 5)
  const recentChatsMinimized = recentChats.slice(0, 5)

  const handleArtifactClick = (artifact: Artifact) => {
    // Navigate to the artifact's chat session or show it
    // For now, we can just log it or navigate
    console.log('Clicked artifact:', artifact)
    // TODO: Implement navigation to artifact's chat or preview
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <>
      {/* Floating Toggle Button - Always visible at the edge */}
      <button
        type="button"
        onClick={toggleMinimize}
        className={cn(
          "fixed z-50 flex h-8 w-8 items-center justify-center rounded-full border border-border bg-background shadow-md transition-all duration-300 ease-in-out hover:bg-accent hover:shadow-lg",
          isMinimized ? "left-[3.375rem] top-4" : "left-[14.625rem] top-4"
        )}
        title={isMinimized ? "Expand sidebar" : "Minimize sidebar"}
      >
        {isMinimized ? (
          <PanelLeftOpen className="h-4 w-4 text-muted-foreground" />
        ) : (
          <PanelLeftClose className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {/* Main Sidebar Container with smooth width transition */}
      <div
        className={cn(
          "flex h-full flex-col border-r border-border bg-sidebar transition-all duration-300 ease-in-out",
          isMinimized ? "w-16" : "w-72",
          className
        )}
      >
        {/* Header */}
        <div className={cn(
          "flex items-center gap-2 border-b border-border p-4",
          isMinimized && "justify-center px-2"
        )}>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            {!isMinimized && (
              <span className="text-lg font-semibold text-foreground">Harvis</span>
            )}
          </div>
        </div>

        {/* New Chat Button */}
        <div className={cn("p-3", isMinimized && "px-2")}>
          <Button
            onClick={onNewChat}
            className={cn(
              "justify-center gap-2 bg-primary/10 text-primary hover:bg-primary/20 transition-all duration-300",
              isMinimized ? "w-full px-2" : "w-full justify-start"
            )}
            variant="ghost"
            title="New Chat"
          >
            <Plus className="h-4 w-4 shrink-0" />
            {!isMinimized && <span>New Chat</span>}
          </Button>
        </div>

        {/* Search - Hidden when minimized */}
        {!isMinimized && (
          <div className="px-3 pb-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search chats..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 bg-input border-border text-foreground placeholder:text-muted-foreground"
              />
            </div>
          </div>
        )}

        {/* Chat List Content */}
        <div className="flex-1 overflow-y-auto px-2">
          {isMinimized ? (
            // Minimized view - Show only icons for recent chats
            <div className="space-y-1 py-2">
              {recentChatsMinimized.map((chat) => (
                <button
                  key={chat.id}
                  type="button"
                  onClick={() => onSelectChat(chat.id)}
                  className={cn(
                    "flex w-full items-center justify-center rounded-lg p-2 transition-colors",
                    activeChat === chat.id
                      ? "bg-sidebar-accent text-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
                  )}
                  title={chat.title}
                >
                  <MessageSquare className="h-4 w-4 shrink-0" />
                  {chat.starred && (
                    <Star className="h-2 w-2 fill-primary text-primary absolute top-1 right-1" />
                  )}
                </button>
              ))}
              
              {/* Show count if more chats exist */}
              {recentChats.length > 5 && (
                <div className="text-center py-1">
                  <span className="text-[10px] text-muted-foreground">+{recentChats.length - 5}</span>
                </div>
              )}
            </div>
          ) : (
            // Full view - Show all sections
            <>
              {/* Starred Section */}
              {starredChats.length > 0 && (
                <div className="mb-2">
                  <button
                    type="button"
                    onClick={() => toggleSection("starred")}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                  >
                    <ChevronDown
                      className={cn(
                        "h-3 w-3 transition-transform",
                        !expandedSections.starred && "-rotate-90"
                      )}
                    />
                    <Star className="h-3 w-3" />
                    Starred
                  </button>
                  {expandedSections.starred && (
                    <div className="space-y-0.5">
                      {starredChats.map((chat) => (
                        <ChatItem
                          key={chat.id}
                          chat={chat}
                          isActive={activeChat === chat.id}
                          onSelect={() => onSelectChat(chat.id)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Recents Section */}
              <div className="mb-2">
                <button
                  type="button"
                  onClick={() => toggleSection("recents")}
                  className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                >
                  <ChevronDown
                    className={cn(
                      "h-3 w-3 transition-transform",
                      !expandedSections.recents && "-rotate-90"
                    )}
                  />
                  <Clock className="h-3 w-3" />
                  Recents
                </button>
                {expandedSections.recents && (
                  <div className="space-y-0.5">
                    {recentChats.map((chat) => (
                      <ChatItem
                        key={chat.id}
                        chat={chat}
                        isActive={activeChat === chat.id}
                        onSelect={() => onSelectChat(chat.id)}
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* Artifacts Section */}
              <div className="mb-2">
                <button
                  type="button"
                  onClick={() => toggleSection("artifacts")}
                  className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                >
                  <ChevronDown
                    className={cn(
                      "h-3 w-3 transition-transform",
                      !expandedSections.artifacts && "-rotate-90"
                    )}
                  />
                  <Box className="h-3 w-3" />
                  Artifacts
                  {artifacts.length > 0 && (
                    <span className="ml-auto text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full">
                      {artifacts.length}
                    </span>
                  )}
                </button>
                {expandedSections.artifacts && (
                  <div className="space-y-0.5">
                    {isLoadingArtifacts ? (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    ) : artifacts.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-muted-foreground">
                        No artifacts yet
                      </div>
                    ) : (
                      artifacts.map((artifact) => (
                        <ArtifactItem
                          key={artifact.id}
                          artifact={artifact}
                          onClick={() => handleArtifactClick(artifact)}
                        />
                      ))
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className={cn("border-t border-border space-y-1", isMinimized ? "p-2" : "p-3")}>
          {/* RAM Clear Button */}
          <button
            type="button"
            onClick={handleClearRAM}
            disabled={isClearing}
            className={cn(
              "flex w-full items-center rounded-lg transition-colors",
              isClearing
                ? "text-muted-foreground cursor-not-allowed"
                : "text-muted-foreground hover:bg-red-500/10 hover:text-red-400",
              isMinimized ? "justify-center p-2" : "gap-3 px-3 py-2 text-sm"
            )}
            title="Clear AI RAM"
          >
            {isClearing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            {!isMinimized && (
              <div className="flex flex-col items-start flex-1">
                <span className="flex items-center gap-2">
                  Clear AI RAM
                  <Cpu className="h-3 w-3" />
                </span>
                {memoryStats && (
                  <span className="text-xs text-muted-foreground">
                    {memoryStats.usage_percent?.toFixed(0)}% used ({memoryStats.free_gb?.toFixed(1)}GB free)
                  </span>
                )}
                {clearMessage && (
                  <span className="text-xs text-green-400">{clearMessage}</span>
                )}
              </div>
            )}
          </button>

          {/* RAG Corpus Button */}
          <button
            type="button"
            onClick={() => router.push("/settings")}
            className={cn(
              "flex w-full items-center rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors",
              isMinimized ? "justify-center p-2" : "gap-3 px-3 py-2 text-sm"
            )}
            title="RAG corpus"
          >
            <Database className="h-4 w-4" />
            {!isMinimized && <span>RAG corpus</span>}
          </button>
          
          {/* Profile Button */}
          <button
            type="button"
            onClick={onProfileClick}
            className={cn(
              "flex w-full items-center rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors",
              isMinimized ? "justify-center p-2" : "gap-3 px-3 py-2 text-sm"
            )}
            title="User Profile"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 ring-2 ring-primary/40">
              <User className="h-4 w-4 text-primary" />
            </div>
            {!isMinimized && (
              <div className="flex flex-col items-start">
                <span className="text-foreground font-medium">User Profile</span>
                <span className="text-xs text-muted-foreground">Pro Plan</span>
              </div>
            )}
          </button>
        </div>
      </div>
    </>
  )
}

function ChatItem({
  chat,
  isActive,
  onSelect,
}: {
  chat: Chat
  isActive: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-sidebar-accent text-foreground"
          : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
      )}
    >
      <MessageSquare className="h-4 w-4 shrink-0" />
      <span className="truncate flex-1 text-left">{chat.title}</span>
      {chat.starred && (
        <Star className="h-3 w-3 fill-primary text-primary shrink-0" />
      )}
    </button>
  )
}

function ArtifactItem({
  artifact,
  onClick,
}: {
  artifact: Artifact
  onClick: () => void
}) {
  const Icon = ARTIFACT_ICONS[artifact.artifact_type] || Box
  const typeColor = TYPE_COLORS[artifact.artifact_type] || "bg-slate-500/10 text-slate-500"

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent hover:text-foreground cursor-pointer transition-colors"
    >
      <div className={cn("flex h-6 w-6 items-center justify-center rounded", typeColor)}>
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="flex-1 min-w-0 text-left">
        <div className="truncate">{artifact.title}</div>
        <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
          <span className="uppercase">{artifact.artifact_type}</span>
          {artifact.file_size && (
            <>
              <span>•</span>
              <span>{formatFileSize(artifact.file_size)}</span>
            </>
          )}
        </div>
      </div>
    </button>
  )
}

export default ChatSidebar
