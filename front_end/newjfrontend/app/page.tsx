"use client"

import { useState, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  MessageSquare,
  Users,
  Cpu,
  Briefcase,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import ChatSidebar from "@/components/chat-sidebar"
import { OpenClawChatView } from "@/components/openclaw/ChatView"
import { OpenClawSessionsView } from "@/components/openclaw/OpenClawSessionsView"
import { OpenClawAgentsView } from "@/components/openclaw/OpenClawAgentsView"
import { WorkspaceLayout } from "@/components/workspace/WorkspaceLayout"
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel"
import { useOpenClawStore } from "@/stores/openclawStore"
import { useUser } from "@/lib/auth/UserProvider"
import { useConnectionStore } from "@/stores/openclawConnectionStore"

type Tab = "chat" | "sessions" | "agents" | "workspaces"

const TABS: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "sessions", label: "Sessions", icon: Users },
  { id: "agents", label: "Agents", icon: Cpu },
  { id: "workspaces", label: "Workspaces", icon: Briefcase },
]

export default function ChatPage() {
  const { user, isLoading: isAuthLoading } = useUser()
  const [activeTab, setActiveTab] = useState<Tab>("chat")
  const [sidebarOpen, setSidebarOpen] = useState(true)

  // Connect to OpenClaw gateway on mount
  const connect = useConnectionStore((s) => s.connect)

  if (isAuthLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="flex flex-col items-center gap-3">
          <Sparkles className="h-8 w-8 text-primary animate-pulse" />
          <span className="text-sm text-muted-foreground">Loading...</span>
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <h2 className="text-xl font-semibold mb-2">Authentication required</h2>
          <p className="text-sm text-muted-foreground">Please log in to continue</p>
        </div>
      </div>
    )
  }

  // Connect to OpenClaw on mount
  if (!useConnectionStore.getState().connected) {
    connect()
  }

  const renderContent = () => {
    switch (activeTab) {
      case "chat":
        return <OpenClawChatView />
      case "sessions":
        return <OpenClawSessionsView />
      case "agents":
        return <OpenClawAgentsView />
      case "workspaces":
        return <WorkspacePanel />
      default:
        return <OpenClawChatView />
    }
  }

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div
        className={cn(
          "flex flex-col border-r bg-sidebar transition-all duration-200",
          sidebarOpen ? "w-64" : "w-0 overflow-hidden"
        )}
      >
        <ChatSidebar
          chats={[]}
          activeChat={null}
          onSelectChat={() => {}}
          onNewChat={() => {}}
        />
      </div>

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Tab bar */}
        <div className="flex items-center gap-1 px-2 py-2 border-b bg-card">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeftOpen className="h-4 w-4" />
            )}
          </Button>

          <div className="flex items-center gap-1 ml-1">
            {TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <Button
                  key={tab.id}
                  variant={activeTab === tab.id ? "secondary" : "ghost"}
                  size="sm"
                  className={cn(
                    "h-8 text-sm gap-1.5 transition-colors",
                    activeTab === tab.id && "font-medium"
                  )}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">{tab.label}</span>
                </Button>
              )
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {renderContent()}
        </div>
      </div>
    </div>
  )
}
