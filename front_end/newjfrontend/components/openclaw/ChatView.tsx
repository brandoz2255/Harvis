"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { cn } from "@/lib/utils"
import {
  Users,
  Settings2,
  PanelRightOpen,
  PanelRightClose,
  Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import { ChatMessageList } from "./ChatMessageList"
import { ToolStreamSidebar } from "./ToolStreamSidebar"
import { OpenClawChatInput } from "./OpenClawChatInput"
import { useOpenClawConnection } from "@/hooks/useOpenClawConnection"
import { useOpenClawChat } from "@/hooks/useOpenClawChat"
import { useChatStore } from "@/stores/openclawChatStore"
import { useSessionsStore } from "@/stores/openclawSessionsStore"
import { useConnectionStore } from "@/stores/openclawConnectionStore"

interface OpenClawChatViewProps {
  className?: string
}

export function OpenClawChatView({ className }: OpenClawChatViewProps) {
  const { isConnected, client } = useOpenClawConnection()
  const {
    send,
    abort,
    loadHistory,
    switchSession,
    chatMessage,
    setChatMessage,
    messages,
    chatStream,
    chatRunId,
    aborting,
  } = useOpenClawChat()

  const {
    messages: chatMessages,
    chatStream: streamText,
    chatRunId: runId,
    chatThinkingLevel: thinkingLevel,
    toolStream,
    focusMode,
    showThinking,
    setFocusMode,
    setShowThinking,
    isThinking,
  } = useChatStore()

  const { sessions, activeSessionKey, setActiveSession, loading: sessionsLoading } = useSessionsStore()

  const [toolStreamOpen, setToolStreamOpen] = useState(true)
  const [splitRatio, setSplitRatio] = useState(0.3)
  const [showSessionPicker, setShowSessionPicker] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)

  // Load history on mount or session change
  useEffect(() => {
    if (isConnected && client) {
      loadHistory()
    }
  }, [isConnected, client, activeSessionKey])

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages.length, chatStream])

  const handleSend = useCallback(
    (text: string) => {
      send(text)
    },
    [send],
  )

  const handleAbort = useCallback(() => {
    abort()
  }, [abort])

  const handleSessionSelect = useCallback(
    (sessionKey: string) => {
      switchSession(sessionKey)
      setActiveSession(sessionKey)
      setShowSessionPicker(false)
    },
    [switchSession, setActiveSession],
  )

  return (
    <div className={cn("flex h-full", className)}>
      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b">
          <div className="flex items-center gap-2 ml-[10%]">
            {!isConnected && (
              <Badge variant="destructive" className="text-xs">
                Disconnected
              </Badge>
            )}
            {isConnected && (
              <Badge variant="secondary" className="text-xs">
                Connected
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Session selector */}
            <div className="relative">
              <Button
                variant="ghost"
                size="sm"
                className="gap-1 h-8 text-sm"
                onClick={() => setShowSessionPicker(!showSessionPicker)}
              >
                {sessionsLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <>
                    <Users className="h-3 w-3" />
                    <span className="truncate max-w-[120px]">
                      {activeSessionKey
                        ? activeSessionKey.replace("agent:main:", "")
                        : "Sessions"}
                    </span>
                  </>
                )}
              </Button>

              {showSessionPicker && (
                <div className="absolute right-0 top-full mt-1 w-72 bg-popover border rounded-lg shadow-lg z-50 max-h-80 overflow-hidden">
                  <ScrollArea className="max-h-80">
                    <div className="p-1">
                      {sessions.length === 0 ? (
                        <div className="px-3 py-4 text-sm text-muted-foreground text-center">
                          No sessions yet
                        </div>
                      ) : (
                        sessions
                          .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
                          .map((session) => (
                            <button
                              key={session.key}
                              className={cn(
                                "w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md text-left hover:bg-muted",
                                session.key === activeSessionKey && "bg-muted"
                              )}
                              onClick={() => handleSessionSelect(session.key)}
                            >
                              <span className="truncate flex-1">
                                {session.displayName || session.key.replace("agent:main:", "")}
                              </span>
                              {session.key === activeSessionKey && (
                                <Badge variant="secondary" className="text-xs shrink-0">
                                  Active
                                </Badge>
                              )}
                            </button>
                          ))
                      )}
                    </div>
                  </ScrollArea>
                </div>
              )}
            </div>

            {/* Focus mode toggle */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              onClick={() => setFocusMode(!focusMode)}
              title={focusMode ? "Exit focus mode" : "Focus mode"}
            >
              <Settings2 className="h-3.5 w-3.5" />
            </Button>

            {/* Tool stream toggle */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              onClick={() => setToolStreamOpen(!toolStreamOpen)}
              title="Toggle tool stream"
            >
              {toolStreamOpen ? (
                <PanelRightClose className="h-3.5 w-3.5" />
              ) : (
                <PanelRightOpen className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        </div>

        {/* Chat messages */}
        <div className="flex-1 flex min-h-0">
          <ChatMessageList
            messages={chatMessages}
            streamText={streamText}
            streamRunId={runId}
            thinkingLevel={thinkingLevel}
            isStreaming={!!streamText && !aborting}
            isThinking={isThinking}
            focusMode={focusMode}
            showThinking={showThinking}
            className="flex-1"
          />
        </div>

        {/* Input */}
        <OpenClawChatInput
          onSend={handleSend}
          onAbort={handleAbort}
          isLoading={aborting}
          isAborting={aborting}
          value={chatMessage}
          onChange={setChatMessage}
        />
      </div>

      {/* Tool stream sidebar */}
      {toolStreamOpen && (
        <ToolStreamSidebar
          entries={toolStream}
          isOpen={toolStreamOpen}
          onToggle={() => setToolStreamOpen(false)}
          splitRatio={splitRatio}
          onSplitChange={setSplitRatio}
        />
      )}
    </div>
  )
}
