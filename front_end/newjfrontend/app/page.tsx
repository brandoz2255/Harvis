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

export default function ChatPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading } = useUser()
  const [selectedModel, setSelectedModel] = useState("")
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
        session_id: sessionId || null
      }

      // Add research mode parameters
      if (isResearchMode) {
        requestBody.enableWebSearch = true
        requestBody.exaggeration = 0.5
        requestBody.temperature = 0.8
        requestBody.cfg_weight = 0.5
      }

      // Retry logic with exponential backoff
      let lastError: Error | null = null
      let response: Response | null = null
      const maxRetries = 6
      const timeoutMs = 600000 // 10 minutes for local hardware

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const controller = new AbortController()
          const timeoutId = setTimeout(() => {
            console.error(`⏱️ Request timeout after ${timeoutMs}ms (attempt ${attempt + 1}/${maxRetries + 1})`)
            controller.abort()
          }, timeoutMs)

          const startTime = Date.now()
          console.log(`📤 [Attempt ${attempt + 1}/${maxRetries + 1}] Sending to ${endpoint}`)

          response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(requestBody),
            credentials: 'include',
            signal: controller.signal
          })

          clearTimeout(timeoutId)
          const elapsed = Date.now() - startTime
          console.log(`📥 Response received in ${elapsed}ms with status ${response.status}`)

          if (!response.ok) {
            const errorText = await response.text()
            throw new Error(`Server error (${response.status}): ${errorText}`)
          }

          // Success - break retry loop
          break

        } catch (error) {
          // Log warning for intermediate failures, error only for final failure
          if (attempt < maxRetries) {
            console.warn(`⚠️ [Attempt ${attempt + 1}/${maxRetries + 1}] Request failed (retrying):`, error)
          } else {
            console.error(`❌ [Attempt ${attempt + 1}/${maxRetries + 1}] Request failed (final):`, error)
            lastError = error as Error
          }
          if (error instanceof Error && error.name === 'AbortError') {
            lastError = new Error(
              `Request timed out after ${timeoutMs / 1000} seconds. ` +
              `The backend may be processing your request. Please wait and try again.`
            )
          }

          // Don't retry if we're out of attempts
          if (attempt >= maxRetries) {
            throw lastError
          }

          // Exponential backoff
          const backoffDelay = Math.min(1000 * Math.pow(2, attempt), 5000)
          console.log(`🔄 Retrying in ${backoffDelay}ms...`)
          await new Promise(resolve => setTimeout(resolve, backoffDelay))
        }
      }

      if (!response || !response.ok) {
        throw lastError || new Error('Failed to get response from server')
      }

      const data = await response.json()

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
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex items-center gap-4 border-b border-border px-4 py-3">
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
            />
          </div>
        </header>

        {/* Chat Area */}
        <ScrollArea ref={scrollRef} className="flex-1">
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
        </ScrollArea>

        {/* Input Area */}
        <ChatInput
          onSend={handleSendMessage}
          isLoading={isLoading}
          isResearchMode={isResearchMode}
          selectedModel={selectedModel}
        />
      </div>
    </div>
  )
}
