"use client"

import { useState, useEffect } from "react"
import { cn } from "@/lib/utils"
import {
  Search,
  Plus,
  MessageSquare,
  Code2,
  Star,
  Clock,
  ChevronDown,
  Settings,
  Sparkles,
  User,
  Cpu,
  Trash2,
  Loader2,
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"

interface Chat {
  id: string
  title: string
  timestamp: string
  starred?: boolean
}

interface CodeBlock {
  id: string
  title: string
  language: string
  timestamp: string
}

interface ChatSidebarProps {
  chats: Chat[]
  codeBlocks: CodeBlock[]
  activeChat: string | null
  onSelectChat: (id: string) => void
  onNewChat: () => void
  onProfileClick?: () => void
  className?: string
}

export function ChatSidebar({
  chats,
  codeBlocks,
  activeChat,
  onSelectChat,
  onNewChat,
  onProfileClick,
  className,
}: ChatSidebarProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [expandedSections, setExpandedSections] = useState({
    starred: true,
    recents: true,
    codeBlocks: true,
  })
  const [isClearing, setIsClearing] = useState(false)
  const [memoryStats, setMemoryStats] = useState<{
    usage_percent?: number
    free_gb?: number
    allocated_gb?: number
  } | null>(null)
  const [clearMessage, setClearMessage] = useState<string | null>(null)

  const fetchMemoryStats = async () => {
    try {
      const res = await fetch('/api/models/memory-pressure')
      if (res.ok) {
        const data = await res.json()
        setMemoryStats(data)
      }
    } catch (error) {
      console.error('Failed to fetch memory stats:', error)
    }
  }

  const handleClearRAM = async () => {
    setIsClearing(true)
    setClearMessage(null)
    try {
      // Unload all models
      const res = await fetch('/api/models/unload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_type: 'all' }),
      })

      if (res.ok) {
        const data = await res.json()
        setClearMessage(`Cleared: ${data.unloaded_models?.join(', ') || 'All models'}`)
        // Refresh memory stats
        await fetchMemoryStats()
      } else {
        setClearMessage('Failed to clear RAM')
      }
    } catch (error) {
      console.error('Failed to clear RAM:', error)
      setClearMessage('Error clearing RAM')
    } finally {
      setIsClearing(false)
      // Clear message after 3 seconds
      setTimeout(() => setClearMessage(null), 3000)
    }
  }

  // Fetch memory stats on mount and periodically
  useEffect(() => {
    fetchMemoryStats()
    const interval = setInterval(fetchMemoryStats, 30000) // Every 30 seconds
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

  return (
    <div
      className={cn(
        "flex h-full w-72 flex-col border-r border-border bg-sidebar",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border p-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Sparkles className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-semibold text-foreground">Harvis</span>
        </div>
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <Button
          onClick={onNewChat}
          className="w-full justify-start gap-2 bg-primary/10 text-primary hover:bg-primary/20"
          variant="ghost"
        >
          <Plus className="h-4 w-4" />
          New Chat
        </Button>
      </div>

      {/* Search */}
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

      {/* Chat List */}
      <ScrollArea className="flex-1 px-2">
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

        {/* Code Blocks Section */}
        <div className="mb-2">
          <button
            type="button"
            onClick={() => toggleSection("codeBlocks")}
            className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            <ChevronDown
              className={cn(
                "h-3 w-3 transition-transform",
                !expandedSections.codeBlocks && "-rotate-90"
              )}
            />
            <Code2 className="h-3 w-3" />
            Code Blocks
          </button>
          {expandedSections.codeBlocks && (
            <div className="space-y-0.5">
              {codeBlocks.map((block) => (
                <div
                  key={block.id}
                  className="group flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent hover:text-foreground cursor-pointer"
                >
                  <div className="flex h-6 w-6 items-center justify-center rounded bg-primary/10 text-[10px] font-mono text-primary">
                    {block.language.slice(0, 2).toUpperCase()}
                  </div>
                  <span className="truncate flex-1">{block.title}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="border-t border-border p-3 space-y-1">
        {/* RAM Clear Button */}
        <button
          type="button"
          onClick={handleClearRAM}
          disabled={isClearing}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
            isClearing
              ? "text-muted-foreground cursor-not-allowed"
              : "text-muted-foreground hover:bg-red-500/10 hover:text-red-400"
          )}
        >
          {isClearing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
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
        </button>

        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
        >
          <Settings className="h-4 w-4" />
          Settings
        </button>
        <button
          type="button"
          onClick={onProfileClick}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 ring-2 ring-primary/40">
            <User className="h-4 w-4 text-primary" />
          </div>
          <div className="flex flex-col items-start">
            <span className="text-foreground font-medium">User Profile</span>
            <span className="text-xs text-muted-foreground">Pro Plan</span>
          </div>
        </button>
      </div>
    </div>
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
