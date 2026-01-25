"use client"

import { useState, useRef, useEffect } from "react"
import { useRouter } from "next/navigation"
import { v4 as uuidv4 } from 'uuid'
import { ChatSidebar } from "@/components/chat-sidebar"
import { ChatMessage } from "@/components/chat-message"
import { ChatInput } from "@/components/chat-input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Menu, Sparkles } from "lucide-react"
import ModelSelector from "@/components/ModelSelector"
import SearchToggle from "@/components/SearchToggle"
import { useChatHistoryStore } from "@/stores/chatHistoryStore"
import { apiClient } from "@/lib/api"
import { useUser } from "@/lib/auth/UserProvider"
import type { Message, MessageObject } from "@/types/message"

import { useApiWithRetry } from "@/hooks/useApiWithRetry"

export default function ChatPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading } = useUser()
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [lowVram, setLowVram] = useState(false)
  const [textOnly, setTextOnly] = useState(false)
  const [isResearchMode, setIsResearchMode] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auth protection
  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.push("/login")
    }
  }, [user, isAuthLoading, router])

  // Chat history store integration
  const {
    sessions,
    currentSession,
    fetchSessions,
    createNewChat,
    selectSession,
    messages: storeMessages,
    isLoadingMessages,
  } = useChatHistoryStore()

  // Fetch sessions on mount (only if user exists)
  useEffect(() => {
    if (user) {
      fetchSessions()
    }
  }, [fetchSessions, user])

  // Sync messages from store
  useEffect(() => {
    if (currentSession && storeMessages) {
      const formattedMessages: Message[] = storeMessages.map((msg: any) => ({
        id: msg.id?.toString(),
        role: msg.role,
        content: msg.content,
        timestamp: new Date(msg.created_at || Date.now()),
        model: msg.model_used,
        status: "sent",
        searchResults: msg.metadata?.searchResults,
        searchQuery: msg.metadata?.searchQuery,
        audioUrl: msg.metadata?.audio_path,
      }))
      setMessages(formattedMessages)
    } else if (!currentSession) {
      // Clear messages when no session is selected
      setMessages([])
    }
  }, [currentSession, storeMessages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleNewChat = async () => {
    const newSession = await createNewChat()
    if (newSession) {
      setMessages([])
    }
  }

  const handleSelectChat = async (id: string) => {
    await selectSession(id)
    setSidebarOpen(false)
  }

  const isDuplicateMessage = (newMessage: Message, existingMessages: Message[]): boolean => {
    const recentMessages = existingMessages.slice(-3)
    return recentMessages.some(msg =>
      msg.role === newMessage.role &&
      msg.content === newMessage.content &&
      Math.abs(msg.timestamp.getTime() - newMessage.timestamp.getTime()) < 2000
    )
  }

  const { fetchWithRetry } = useApiWithRetry()

  const handleSendMessage = async (input: string | MessageObject) => {
    // Handle voice message objects
    if (typeof input !== 'string') {
      if (!isDuplicateMessage(input as Message, messages)) {
        setMessages((prev) => [...prev, input as Message])
      }
      return
    }

    // Handle text input
    if (!input.trim() || isLoading) return

    const tempId = uuidv4()

    // Create optimistic user message
    const userMessage: Message = {
      tempId,
      role: "user",
      content: input,
      timestamp: new Date(),
      model: selectedModel,
      status: "pending",
    }

    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)

    // Create session if none exists
    let sessionId = currentSession?.id
    if (!sessionId) {
      const newSession = await createNewChat()
      sessionId = newSession?.id
    }

    try {
      // Get auth token
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('Authentication required. Please log in again.')
      }

      // Determine endpoint based on research mode
      const endpoint = isResearchMode ? '/api/research-chat' : '/api/chat'

      // Build request payload
      const requestBody: any = {
        message: input,
        history: messages.map(m => ({
          role: m.role,
          content: m.content
        })),
        model: selectedModel || 'mistral',
        session_id: sessionId || null,
        low_vram: lowVram,
        text_only: textOnly
      }

      // Add research mode parameters
      if (isResearchMode) {
        requestBody.enableWebSearch = true
        requestBody.exaggeration = 0.5
        requestBody.temperature = 0.8
        requestBody.cfg_weight = 0.5
      }

      // Use fetchWithRetry for all modes (it handles both JSON and SSE)
      const data = await fetchWithRetry(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(requestBody),
        credentials: 'include'
      }, {
        lowVram,
        timeout: lowVram ? 3600000 : 300000,
        maxRetries: 0
      })

      // Update user message to sent
      setMessages((prev) =>
        prev.map((msg) =>
          msg.tempId === tempId ? { ...msg, status: "sent" } : msg
        )
      )

      // Create assistant message with all response data
      const assistantContent = data.final_answer ||
        data.response ||
        (data.history && data.history.length > 0
          ? data.history[data.history.length - 1]?.content
          : '')

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: assistantContent,
        timestamp: new Date(),
        model: selectedModel,
        status: "sent",
        audioUrl: data.audio_path,
        reasoning: data.reasoning,
        searchResults: data.search_results,
        searchQuery: data.searchQuery,
      }

      if (!isDuplicateMessage(assistantMessage, messages)) {
        setMessages((prev) => [...prev, assistantMessage])
      }
    } catch (error) {
      console.error("Chat error:", error)
      // Mark message as failed
      setMessages((prev) =>
        prev.map((msg) =>
          msg.tempId === tempId ? { ...msg, status: "failed" } : msg
        )
      )
    } finally {
      setIsLoading(false)
    }
  }

  if (isAuthLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Sparkles className="h-10 w-10 animate-pulse text-primary" />
      </div>
    )
  }

  if (!user) {
    return null // Will redirect in useEffect
  }

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div
        className={`${sidebarOpen ? "translate-x-0" : "-translate-x-full"
          } fixed inset-y-0 left-0 z-30 transition-transform duration-300 lg:relative lg:translate-x-0`}
      >
        <ChatSidebar
          chats={sessions.map((s) => ({
            id: s.id,
            title: s.title,
            timestamp: new Date(s.updated_at).toLocaleDateString(),
            starred: false,
          }))}
          codeBlocks={[]}
          activeChat={currentSession?.id || ""}
          onSelectChat={handleSelectChat}
          onNewChat={handleNewChat}
          onProfileClick={() => router.push("/profile")}
        />
      </div>

      {/* Overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setSidebarOpen(false)}
        />
      )}

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header - Sticky at top */}
        <header className="sticky top-0 z-10 shrink-0 flex items-center gap-4 border-b border-border bg-background px-4 py-3">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/20">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h1 className="text-sm font-medium text-foreground">
                {currentSession?.title || "New Chat"}
              </h1>
              <p className="text-xs text-muted-foreground">HARVIS Assistant</p>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <SearchToggle
              isResearchMode={isResearchMode}
              onToggle={setIsResearchMode}
            />
            <ModelSelector
              selectedModel={selectedModel}
              onModelChange={setSelectedModel}
              lowVram={lowVram}
              onLowVramChange={setLowVram}
              textOnly={textOnly}
              onTextOnlyChange={setTextOnly}
            />
          </div>
        </header>

        {/* Chat Area - Scrollable middle section */}
        <div className="flex-1 overflow-y-auto" ref={scrollRef}>
          <div className="mx-auto max-w-4xl px-4 py-6">
            {messages.length === 0 ? (
              <div className="flex h-[60vh] flex-col items-center justify-center text-center">
                <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/20">
                  <Sparkles className="h-10 w-10 text-primary" />
                </div>
                <h2 className="mb-2 text-2xl font-semibold text-foreground">
                  How can I help you today?
                </h2>
                <p className="max-w-md text-muted-foreground">
                  I'm HARVIS, your AI assistant. Ask me anything about coding,
                  design, or any topic you'd like to explore.
                </p>
                <div className="mt-8 grid gap-3 sm:grid-cols-2">
                  {[
                    "Help me write a React component",
                    "Explain TypeScript generics",
                    "Design a database schema",
                    "Debug my code",
                  ].map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => handleSendMessage(prompt)}
                      className="rounded-xl border border-border bg-card px-4 py-3 text-left text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message, index) => (
                <ChatMessage
                  key={message.id || message.tempId || index}
                  role={message.role}
                  content={message.content}
                  timestamp={message.timestamp.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  codeBlocks={message.codeBlocks}
                  searchResults={message.searchResults}
                  searchQuery={message.searchQuery}
                  audioUrl={message.audioUrl}
                  reasoning={message.reasoning}
                />
              ))
            )}
            {isLoading && (
              <div className="flex items-center gap-4 py-6">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/20">
                  <Sparkles className="h-4 w-4 animate-pulse text-primary" />
                </div>
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                  <div className="h-2 w-2 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                  <div className="h-2 w-2 animate-bounce rounded-full bg-primary" />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Input Area - Sticky at bottom */}
        <div className="sticky bottom-0 z-10 shrink-0 border-t border-border bg-background">
          <ChatInput
            onSend={handleSendMessage}
            isLoading={isLoading}
            isResearchMode={isResearchMode}
            selectedModel={selectedModel}
          />
        </div>
      </div>
    </div>
  )
}
