"use client"

import { useState, useRef, useEffect, useMemo, useCallback } from "react"
import { flushSync } from "react-dom"
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
import type { Message, MessageObject, Attachment } from "@/types/message"
import { isVisionModel } from "@/types/message"
import { useChat } from "@ai-sdk/react"
// @ts-ignore
import { Message as AiMessage } from "ai"

import { useApiWithRetry } from "@/hooks/useApiWithRetry"

export default function ChatPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading } = useUser()
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [lowVram, setLowVram] = useState(false)
  const [textOnly, setTextOnly] = useState(false)
  const [isResearchMode, setIsResearchMode] = useState(false)
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const [sidebarOpen, setSidebarOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Use a ref to track if we should skip the next scroll (to prevent scroll jank during streaming)
  const skipNextScrollRef = useRef(false)

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
    setCurrentSession,
    messages: storeMessages,
    isLoadingMessages,
  } = useChatHistoryStore()

  // Vercel AI SDK integration
  const {
    messages: aiMessages,
    append,
    setMessages: setAiMessages,
    isLoading: isAiLoading,
    data: aiData
  } = useChat({
    api: '/api/ai-chat',
    // Add auth headers dynamically via credentials - simpler than custom fetch
    credentials: 'include',
    body: {
      model: selectedModel,
      sessionId: currentSession?.id || null,
      textOnly: textOnly,
      lowVram: lowVram,
    },
    onError: (e: any) => {
      console.error("AI SDK Error:", e)
      console.error("AI SDK Error details:", {
        message: e?.message,
        cause: e?.cause,
        name: e?.name,
        stack: e?.stack?.slice(0, 500)
      })
      // Check if this is a non-stream response error (backend down, etc.)
      if (e?.message?.includes('input stream') || e?.name === 'TypeError') {
        console.error("AI SDK: Received non-stream response. Backend may be down or returned invalid data.")
      }
      setIsLoading(false)
    },
    onFinish: (message: any) => {
      setIsLoading(false)
      fetchSessions()
    }
  })

  // Track data in refs to avoid re-renders during streaming
  const audioUrlMapRef = useRef<Map<string, string>>(new Map())
  const searchResultsMapRef = useRef<Map<string, any[]>>(new Map())
  const videosMapRef = useRef<Map<string, any[]>>(new Map())
  const reasoningMapRef = useRef<Map<string, string>>(new Map())
  const researchChainMapRef = useRef<Map<string, any>>(new Map())
  const processedDataLengthRef = useRef(0)

  // Track previous aiData length to detect new data
  const prevAiDataLengthRef = useRef(0)

  // Buffer for research events that arrive before assistant message exists
  const pendingResearchEventsRef = useRef<any[]>([])

  // State trigger to force re-render when research chain updates
  const [researchChainUpdateTrigger, setResearchChainUpdateTrigger] = useState(0)

  // Helper function to process a single research event and update the chain
  // Uses immutable updates to ensure React detects changes
  const processResearchEvent = useCallback((data: any, assistantId: string) => {
    // Case 1: Pre-formed chain object
    if (data?.research_chain) {
      researchChainMapRef.current.set(assistantId, data.research_chain)
      return true
    }
    // Case 2: Structured research events from auto-research streaming
    else if (data?.status === 'researching' && data?.eventType) {
      const currentChain = researchChainMapRef.current.get(assistantId) || {
        summary: "Researching...",
        steps: [],
        isLoading: true
      }

      const eventType = data.eventType

      if (eventType === 'search_query') {
        const query = data.query || data.detail
        if (query) {
          const newSteps = [...currentChain.steps, {
            type: 'search',
            query: query,
            resultCount: 0,
            results: []
          }]
          researchChainMapRef.current.set(assistantId, { ...currentChain, steps: newSteps })
          return true
        }
      }
      else if (eventType === 'search_result') {
        const title = data.title || 'Unknown'
        const url = data.url || ''
        const domain = data.domain || ''

        // Create new steps array with updated search step (immutable)
        const newSteps = currentChain.steps.map((step: any, i: number) => {
          const isLastSearch = step.type === 'search' &&
            !currentChain.steps.slice(i + 1).some((s: any) => s.type === 'search')

          if (isLastSearch && !step.results.some((r: any) => r.url === url)) {
            return {
              ...step,
              results: [...step.results, { title, url, domain }],
              resultCount: step.results.length + 1
            }
          }
          return step
        })
        researchChainMapRef.current.set(assistantId, { ...currentChain, steps: newSteps })
        return true
      }
      else if (eventType === 'reading') {
        const domain = data.domain || data.detail
        if (domain) {
          const newSteps = [...currentChain.steps, {
            type: 'read',
            domain: domain,
            summary: 'Reading content...'
          }]
          researchChainMapRef.current.set(assistantId, { ...currentChain, steps: newSteps })
          return true
        }
      }
    }
    // Case 3: Legacy log parsing for backward compatibility
    else if (data?.status === 'progress' || data?.status === 'researching' || data?.type === 'log') {
      const logMessage = data.message || data.detail || data.content
      if (logMessage && typeof logMessage === 'string') {
        const currentChain = researchChainMapRef.current.get(assistantId) || {
          summary: "Researching...",
          steps: [],
          isLoading: true
        }

        const lastStep = currentChain.steps[currentChain.steps.length - 1] as any
        if (!lastStep || (lastStep.content !== logMessage && lastStep.query !== logMessage && lastStep.domain !== logMessage)) {
          const lowerLog = logMessage.toLowerCase()
          let newStep: any = null

          if (lowerLog.includes('search') || lowerLog.includes('googl')) {
            newStep = {
              type: 'search',
              query: logMessage.replace(/searching for|search/gi, '').trim() || logMessage,
              resultCount: 0,
              results: []
            }
          } else if (lowerLog.includes('read') || lowerLog.includes('brow') || lowerLog.includes('access')) {
            newStep = {
              type: 'read',
              domain: logMessage,
              summary: 'Reading content...'
            }
          } else {
            newStep = {
              type: 'thinking',
              content: logMessage
            }
          }

          if (newStep) {
            const newSteps = [...currentChain.steps, newStep]
            researchChainMapRef.current.set(assistantId, { ...currentChain, steps: newSteps })
            return true
          }
        }
      }
    }
    return false
  }, [])

  // Process aiData updates in a separate effect (doesn't trigger re-renders of messages)
  useEffect(() => {
    if (!aiData || aiData.length === 0) {
      processedDataLengthRef.current = 0
      prevAiDataLengthRef.current = 0
      pendingResearchEventsRef.current = []
      return
    }

    const assistantMsgIds = aiMessages
      .filter((m: any) => m.role === 'assistant')
      .map((m: any) => m.id)
    const lastAssistantId = assistantMsgIds[assistantMsgIds.length - 1]

    // Process any pending research events now that we have an assistant message
    if (lastAssistantId && pendingResearchEventsRef.current.length > 0) {
      console.log(`[AI-Chat] Processing ${pendingResearchEventsRef.current.length} buffered research events for ${lastAssistantId}`)
      let updated = false
      pendingResearchEventsRef.current.forEach(event => {
        if (processResearchEvent(event, lastAssistantId)) {
          updated = true
        }
      })
      pendingResearchEventsRef.current = []
      if (updated) {
        setResearchChainUpdateTrigger(prev => prev + 1)
      }
    }

    // Only process new data items
    if (aiData.length > prevAiDataLengthRef.current) {
      const newItems = aiData.slice(prevAiDataLengthRef.current)
      prevAiDataLengthRef.current = aiData.length

      const mappedAudioUrls = new Set(audioUrlMapRef.current.values())
      let chainUpdated = false

      newItems.forEach((rawData: any) => {
        // AI SDK wraps data in arrays when sent via 2:[...], so unwrap if needed
        const dataItems = Array.isArray(rawData) ? rawData : [rawData]

        dataItems.forEach((data: any) => {
          // Audio URLs
          if (data?.audioPath && !mappedAudioUrls.has(data.audioPath) && lastAssistantId) {
            audioUrlMapRef.current.set(lastAssistantId, data.audioPath)
            mappedAudioUrls.add(data.audioPath)
          }

          // Search results
          const results = data?.searchResults || data?.results || data?.sources
          if (results && lastAssistantId && !searchResultsMapRef.current.has(lastAssistantId)) {
            searchResultsMapRef.current.set(lastAssistantId, results)
          }

          // Videos
          if (data?.videos && lastAssistantId && !videosMapRef.current.has(lastAssistantId)) {
            videosMapRef.current.set(lastAssistantId, data.videos)
          }

          // Research Chain - Handle with buffering if no assistant message yet
          const isResearchEvent = data?.research_chain ||
            (data?.status === 'researching') ||
            (data?.status === 'progress') ||
            (data?.type === 'log')

          if (isResearchEvent) {
            console.log('[AI-Chat] Research event received:', {
              status: data?.status,
              eventType: data?.eventType,
              lastAssistantId,
              aiMessagesCount: aiMessages.length,
              isAutoResearch: data?.isAutoResearch
            })

            // FIX: Initialize research chain for auto-research mode (same UI as forced research)
            // This ensures the "Researching..." UI appears even when user didn't toggle research mode
            if (data?.isAutoResearch && lastAssistantId && !researchChainMapRef.current.has(lastAssistantId)) {
              console.log('[AI-Chat] Auto-research detected, initializing research chain for', lastAssistantId)
              researchChainMapRef.current.set(lastAssistantId, {
                summary: "Researching...",
                steps: [],
                isLoading: true
              })
              chainUpdated = true
            }

            if (lastAssistantId) {
              if (processResearchEvent(data, lastAssistantId)) {
                console.log('[AI-Chat] Research chain updated for', lastAssistantId)
                chainUpdated = true
              }
            } else {
              // Buffer research events until assistant message exists
              console.log('[AI-Chat] Buffering research event (no assistant message yet)', data?.eventType)
              pendingResearchEventsRef.current.push(data)
            }
          }

          // Session ID - sync currentSession when backend creates/returns a session
          if (data?.sessionId && data.sessionId !== currentSession?.id) {
            console.log(`[AI-Chat] Syncing session from backend: ${data.sessionId}`)
            const existingSession = sessions.find(s => s.id === data.sessionId)
            if (existingSession) {
              setCurrentSession(existingSession)
            } else {
              fetchSessions().then(() => {
                const newSession = useChatHistoryStore.getState().sessions.find(s => s.id === data.sessionId)
                if (newSession) {
                  setCurrentSession(newSession)
                }
              })
            }
          }
        }) // End of dataItems.forEach
      }) // End of newItems.forEach

      if (chainUpdated) {
        setResearchChainUpdateTrigger(prev => prev + 1)
      }
    }
  }, [aiData, aiMessages, currentSession?.id, sessions, setCurrentSession, fetchSessions, processResearchEvent])

  // Use useMemo to convert AI messages to local format - this prevents re-renders during streaming
  const convertedMessages = useMemo<Message[]>(() => {
    if (aiMessages.length === 0) return []

    return aiMessages.map((m: any, index: number): Message => {
      const reasoningTool = m.toolInvocations?.find((t: any) => t.toolName === 'reasoning')
      const toolReasoning = reasoningTool?.result?.reasoning
      const reasoning = toolReasoning || reasoningMapRef.current.get(m.id)

      return {
        id: m.id,
        role: m.role as "user" | "assistant",
        content: m.content,
        timestamp: m.createdAt || new Date(),
        model: selectedModel,
        status: (index === aiMessages.length - 1 && isAiLoading) ? 'streaming' : 'sent',
        reasoning: reasoning,
        researchChain: researchChainMapRef.current.get(m.id),
        audioUrl: audioUrlMapRef.current.get(m.id),
        searchResults: searchResultsMapRef.current.get(m.id),
        videos: videosMapRef.current.get(m.id),
        metadata: m.metadata,
        inputType: m.inputType,
      }
    })
  }, [aiMessages, selectedModel, isAiLoading, researchChainUpdateTrigger])

  // Unified message merging - combines AI SDK messages with local messages
  // This ensures text, vision, voice, and all modes appear together seamlessly
  const messages = useMemo(() => {
    // Start with AI SDK messages (converted from aiMessages)
    const merged = [...convertedMessages]

    // Add localMessages that aren't already in merged
    localMessages.forEach(localMsg => {
      const exists = merged.some(m =>
        // Check by ID
        (m.id && m.id === localMsg.id) ||
        (m.tempId && m.tempId === localMsg.tempId) ||
        // Check by content + role + timestamp (within 2 seconds)
        (m.role === localMsg.role &&
          m.content === localMsg.content &&
          Math.abs(m.timestamp.getTime() - localMsg.timestamp.getTime()) < 2000)
      )
      if (!exists) {
        merged.push(localMsg)
      }
    })

    // Sort by timestamp to maintain chronological order
    return merged.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
  }, [convertedMessages, localMessages])

  // Sync loaded history INTO AI SDK
  useEffect(() => {
    if (currentSession && storeMessages && storeMessages.length > 0 && aiMessages.length === 0) {
      // Clear the maps first when loading new history
      searchResultsMapRef.current.clear()
      videosMapRef.current.clear()
      audioUrlMapRef.current.clear()
      reasoningMapRef.current.clear()
      researchChainMapRef.current.clear()
      processedDataLengthRef.current = 0
      prevAiDataLengthRef.current = 0

      const formattedForAi: any[] = storeMessages.map((msg: any) => {
        const msgId = msg.id?.toString() || uuidv4()

        if (msg.metadata) {
          const sources = msg.metadata.sources || msg.metadata.searchResults
          const videos = msg.metadata.videos

          if (sources && sources.length > 0) {
            searchResultsMapRef.current.set(msgId, sources)
          }
          if (videos && videos.length > 0) {
            videosMapRef.current.set(msgId, videos)
          }
        }

        if (msg.reasoning) {
          reasoningMapRef.current.set(msgId, msg.reasoning)
        }

        if (msg.researchChain) {
          researchChainMapRef.current.set(msgId, msg.researchChain)
        }

        return {
          id: msgId,
          role: msg.role,
          content: msg.content,
          createdAt: new Date(msg.created_at || Date.now()),
          metadata: msg.metadata,
          inputType: msg.input_type,
        }
      })
      setAiMessages(formattedForAi)
    }
  }, [storeMessages, currentSession, setAiMessages, aiMessages.length])

  // Fetch sessions on mount
  useEffect(() => {
    if (user) {
      fetchSessions()
    }
  }, [fetchSessions, user])

  // Optimized scroll to bottom - only scroll on significant changes, not every token
  useEffect(() => {
    if (skipNextScrollRef.current) {
      skipNextScrollRef.current = false
      return
    }

    if (scrollRef.current && messages.length > 0) {
      // Use requestAnimationFrame for smooth scrolling
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo({
          top: scrollRef.current.scrollHeight,
          behavior: 'smooth'
        })
      })
    }
  }, [messages.length]) // Only scroll when message count changes, not on every content update

  const handleNewChat = useCallback(async () => {
    const newSession = await createNewChat()
    if (newSession) {
      setLocalMessages([])
      setAiMessages([])
      audioUrlMapRef.current.clear()
      searchResultsMapRef.current.clear()
      videosMapRef.current.clear()
      reasoningMapRef.current.clear()
    }
  }, [createNewChat, setAiMessages])

  const handleSelectChat = useCallback(async (id: string) => {
    setAiMessages([])
    setLocalMessages([])
    audioUrlMapRef.current.clear()
    searchResultsMapRef.current.clear()
    videosMapRef.current.clear()
    reasoningMapRef.current.clear()
    researchChainMapRef.current.clear()
    await selectSession(id)
    setSidebarOpen(false)
  }, [selectSession, setAiMessages])

  const isDuplicateMessage = useCallback((newMessage: Message, existingMessages: Message[]): boolean => {
    const recentMessages = existingMessages.slice(-3)
    return recentMessages.some(msg =>
      msg.role === newMessage.role &&
      msg.content === newMessage.content &&
      Math.abs(msg.timestamp.getTime() - newMessage.timestamp.getTime()) < 2000
    )
  }, [])

  const { fetchWithRetry } = useApiWithRetry()

  const handleSendMessage = useCallback(async (input: string | MessageObject) => {
    let messageContent = ""
    let messageAttachments: Attachment[] = []

    if (typeof input === 'string') {
      messageContent = input
      if (!messageContent.trim()) return
    } else {
      const msgObj = input as MessageObject
      messageContent = msgObj.content
      messageAttachments = msgObj.attachments || []

      if (msgObj.inputType === 'voice') {
        if (!isDuplicateMessage(msgObj as Message, messages)) {
          setLocalMessages((prev) => [...prev, msgObj as Message])
        }
        return
      }

      if (!isDuplicateMessage(msgObj as Message, messages)) {
        setLocalMessages((prev) => [...prev, msgObj as Message])
      }
    }

    if (isLoading) return

    const hasImages = messageAttachments.some(a => a.type === 'image')
    if (hasImages && isVisionModel(selectedModel || '')) {
      const imageAttachment = messageAttachments.find(a => a.type === 'image')
      if (imageAttachment) {
        // Get the user message that was just added to update its status later
        const lastMessage = messages[messages.length - 1]
        const userTempId = lastMessage?.tempId || lastMessage?.id
        await handleVisionMessage(messageContent, imageAttachment.data, messageAttachments, userTempId)
      }
      return
    }

    const assistantId = uuidv4()
    const tempId = uuidv4()

    if (typeof input === 'string') {
      const userMessage: Message = {
        tempId,
        role: "user",
        content: messageContent,
        timestamp: new Date(),
        model: selectedModel,
        status: "pending",
      }
      setLocalMessages((prev) => [...prev, userMessage])

      if (isResearchMode || isVisionModel(selectedModel || '')) {
        const placeholderAiMsg: Message = {
          id: assistantId,
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          model: selectedModel,
          status: 'streaming',
          // Initialize research chain for research mode to show live progress immediately
          ...(isResearchMode && {
            researchChain: {
              summary: "Researching...",
              steps: [],
              isLoading: true
            }
          })
        }
        setLocalMessages((prev) => [...prev, placeholderAiMsg])
        // Store in ref for streaming updates
        if (isResearchMode) {
          researchChainMapRef.current.set(assistantId, placeholderAiMsg.researchChain!)
        }
      }

      if (!isResearchMode && !isVisionModel(selectedModel || '')) {
        setIsLoading(true)
        await append({
          role: 'user',
          content: messageContent,
        })
        return;
      }
    }

    setIsLoading(true)

    let sessionId = currentSession?.id
    if (!sessionId) {
      const newSession = await createNewChat()
      sessionId = newSession?.id
    }

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('Authentication required. Please log in again.')
      }

      const endpoint = isResearchMode ? '/api/research-chat' : '/api/chat'

      const requestBody: any = {
        message: messageContent,
        history: messages.map(m => ({
          role: m.role,
          content: m.content
        })),
        model: selectedModel,
        session_id: sessionId || null,
        low_vram: lowVram,
        text_only: textOnly,
        attachments: messageAttachments.length > 0 ? messageAttachments : undefined
      }

      if (isResearchMode) {
        requestBody.enableWebSearch = true
        requestBody.exaggeration = 0.5
        requestBody.temperature = 0.8
        requestBody.cfg_weight = 0.5
      }

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
        timeout: 3600000,
        maxRetries: 0,
        onChunk: (chunk: any) => {
          // FIX: Use flushSync to force immediate re-render for live streaming UI
          // Without this, React batches updates and UI only refreshes at the end
          flushSync(() => setLocalMessages((prev) => {
            const newMessages = [...prev]
            const index = newMessages.findIndex(m => m.id === assistantId)
            if (index === -1) return prev

            const currentMsg = newMessages[index]
            let updates: Partial<Message> = {}
            let hasUpdates = false

            if (chunk.status === 'progress' || chunk.status === 'researching') {
              const statusText = chunk.message || chunk.detail
              const eventType = chunk.type
              
              if (statusText || eventType) {
                // Build research chain from logs
                // Check ref first in case the initial state update hasn't propagated yet
                const currentChain = currentMsg.researchChain || 
                  researchChainMapRef.current.get(assistantId) || {
                    summary: "Researching...",
                    steps: [],
                    isLoading: true
                  }

                // Handle structured event types from backend streaming
                // IMPORTANT: Create new arrays/objects to ensure React detects changes
                if (eventType === 'search_query') {
                  // New search query started
                  const query = chunk.query || statusText
                  const newSteps = [...currentChain.steps, {
                    type: 'search',
                    query: query,
                    resultCount: 0,
                    results: []
                  }]
                  updates.researchChain = { ...currentChain, steps: newSteps }
                  researchChainMapRef.current.set(assistantId, updates.researchChain)
                  hasUpdates = true
                }
                else if (eventType === 'search_result') {
                  // Search result found - add to last search step
                  const title = chunk.title || 'Unknown'
                  const url = chunk.url || ''
                  const domain = chunk.domain || ''

                  // Create new steps array with updated search step
                  const newSteps = currentChain.steps.map((step: any, i: number) => {
                    // Find the last search step
                    const isLastSearch = step.type === 'search' &&
                      !currentChain.steps.slice(i + 1).some((s: any) => s.type === 'search')

                    if (isLastSearch && !step.results.some((r: any) => r.url === url)) {
                      return {
                        ...step,
                        results: [...step.results, { title, url, domain }],
                        resultCount: step.results.length + 1
                      }
                    }
                    return step
                  })
                  updates.researchChain = { ...currentChain, steps: newSteps }
                  researchChainMapRef.current.set(assistantId, updates.researchChain)
                  hasUpdates = true
                }
                else if (eventType === 'reading') {
                  // Reading content from a domain
                  const domain = chunk.domain || statusText
                  const newSteps = [...currentChain.steps, {
                    type: 'read',
                    domain: domain,
                    summary: 'Reading content...'
                  }]
                  updates.researchChain = { ...currentChain, steps: newSteps }
                  researchChainMapRef.current.set(assistantId, updates.researchChain)
                  hasUpdates = true
                }
                // Legacy log parsing for backward compatibility
                else if (statusText) {
                  const lowerLog = statusText.toLowerCase()

                  // Check for result count updates (e.g. "Found 5 relevant search results for query:")
                  const resultCountMatch = statusText.match(/Found (\d+) relevant search results/i)
                  if (resultCountMatch) {
                    const count = parseInt(resultCountMatch[1], 10)
                    // Update the last search step's result count
                    for (let i = currentChain.steps.length - 1; i >= 0; i--) {
                      if (currentChain.steps[i].type === 'search') {
                        (currentChain.steps[i] as any).resultCount = count
                        break
                      }
                    }
                    updates.researchChain = { ...currentChain }
                    researchChainMapRef.current.set(assistantId, updates.researchChain)
                    hasUpdates = true
                  }
                  // Check for URL extraction from raw result logs (e.g. "Raw result 1: Title='...', URL='...'")
                  else if (statusText.includes("Raw result") || statusText.includes("URL='")) {
                    const urlMatch = statusText.match(/URL='([^']+)'/i)
                    const titleMatch = statusText.match(/Title='([^']+)'/i)
                    if (urlMatch) {
                      const url = urlMatch[1]
                      const title = titleMatch ? titleMatch[1] : url
                      let domain = url
                      try {
                        domain = new URL(url).hostname.replace('www.', '')
                      } catch { }

                      // Create new steps array with updated search step (immutable update)
                      const newSteps = currentChain.steps.map((step: any, i: number) => {
                        const isLastSearch = step.type === 'search' &&
                          !currentChain.steps.slice(i + 1).some((s: any) => s.type === 'search')

                        if (isLastSearch && !step.results.some((r: any) => r.url === url)) {
                          return {
                            ...step,
                            results: [...step.results, { title, url, domain }],
                            resultCount: step.results.length + 1
                          }
                        }
                        return step
                      })
                      updates.researchChain = { ...currentChain, steps: newSteps }
                      researchChainMapRef.current.set(assistantId, updates.researchChain)
                      hasUpdates = true
                    }
                  }
                  // Avoid duplicate steps for other log types
                  else {
                    const lastStep = currentChain.steps[currentChain.steps.length - 1] as any
                    if (!lastStep || (lastStep.content !== statusText && lastStep.query !== statusText && lastStep.domain !== statusText)) {
                      let newStep: any = null

                      if (lowerLog.includes('searching for') || lowerLog.includes('search') && !lowerLog.includes('result')) {
                        const queryMatch = statusText.match(/['"]([^'"]+)['"]/i)
                        const query = queryMatch ? queryMatch[1] : statusText.replace(/searching for|search/gi, '').trim() || statusText
                        newStep = {
                          type: 'search',
                          query: query,
                          resultCount: 0,
                          results: []
                        }
                      } else if (lowerLog.includes('read') || lowerLog.includes('brow') || lowerLog.includes('access') || lowerLog.includes('fetch') || lowerLog.includes('extract')) {
                        const urlInLog = statusText.match(/https?:\/\/[^\s]+/i)
                        let domain = statusText
                        if (urlInLog) {
                          try {
                            domain = new URL(urlInLog[0]).hostname.replace('www.', '')
                          } catch { }
                        }
                        newStep = {
                          type: 'read',
                          domain: domain,
                          summary: 'Reading content...'
                        }
                      } else if (!lowerLog.includes('ddgs') && !lowerLog.includes('primp') && !lowerLog.includes('response:')) {
                        newStep = {
                          type: 'thinking',
                          content: statusText
                        }
                      }

                      if (newStep) {
                        const newSteps = [...currentChain.steps, newStep]
                        updates.researchChain = { ...currentChain, steps: newSteps }
                        researchChainMapRef.current.set(assistantId, updates.researchChain)
                        hasUpdates = true
                      }
                    }
                  }
                }
              }
            }

            if (chunk.status === 'streaming' && chunk.content) {
              updates.content = (currentMsg.content || '') + chunk.content
              updates.status = 'sent'
              hasUpdates = true
            }

            if (chunk.status === 'complete') {
              const finalContent = chunk.response || chunk.final_answer
              if (finalContent) {
                updates.content = finalContent
                updates.status = 'sent'
                hasUpdates = true
              }
              if (chunk.reasoning) {
                updates.reasoning = chunk.reasoning
                hasUpdates = true
              }
              if (chunk.audio_path) {
                updates.audioUrl = chunk.audio_path
                hasUpdates = true
              }
              // Mark research chain as complete (check both message state AND ref for auto-research)
              const chainFromMsg = currentMsg.researchChain
              const chainFromRef = researchChainMapRef.current.get(assistantId)
              const existingChain = chainFromMsg || chainFromRef
              if (existingChain) {
                updates.researchChain = {
                  ...existingChain,
                  isLoading: false,
                  summary: chunk.research_summary || existingChain.summary || "Research completed"
                }
                researchChainMapRef.current.set(assistantId, updates.researchChain)
                hasUpdates = true
              }
            }

            if (chunk.sources || chunk.search_results) {
              updates.searchResults = chunk.sources || chunk.search_results
              hasUpdates = true
            }

            if (chunk.videos) {
              updates.videos = chunk.videos
              hasUpdates = true
            }

            if (chunk.research_chain) {
              updates.researchChain = chunk.research_chain
              researchChainMapRef.current.set(assistantId, chunk.research_chain)
              hasUpdates = true
            }

            if (hasUpdates) {
              return newMessages.map((msg, i) =>
                i === index ? { ...msg, ...updates } : msg
              )
            }

            return prev
          }))
        }
      })

      if (typeof input === 'string') {
        setLocalMessages((prev) =>
          prev.map((msg) =>
            msg.tempId === tempId ? { ...msg, status: "sent" } : msg
          )
        )
      }

      const assistantContent = data.final_answer ||
        data.response ||
        (data.history && data.history.length > 0
          ? data.history[data.history.length - 1]?.content
          : '')

      // CRITICAL: Use the SAME assistantId we created at the start, not a new one
      // Also preserve the research chain we built during streaming if backend didn't send one
      const existingResearchChain = researchChainMapRef.current.get(assistantId)

      const assistantMessage: Message = {
        id: assistantId,  // Use the same ID, not a new one!
        role: "assistant",
        content: assistantContent,
        timestamp: new Date(),
        model: selectedModel,
        status: "sent",
        audioUrl: data.audio_path || undefined,
        reasoning: data.reasoning,
        searchResults: data.search_results || data.sources,
        searchQuery: data.searchQuery,
        videos: data.videos,
        researchChain: data.research_chain || (existingResearchChain ? { ...existingResearchChain, isLoading: false } : undefined),
        autoResearched: data.auto_researched,
      }

      setLocalMessages((prev) =>
        prev.map(msg => msg.id === assistantId ? assistantMessage : msg)
      )
    } catch (error) {
      console.error("Chat error:", error)
      if (typeof input === 'string') {
        setLocalMessages((prev) =>
          prev.map((msg) =>
            msg.tempId === tempId ? { ...msg, status: "failed" } : msg
          )
        )
      }
    } finally {
      setIsLoading(false)
    }
  }, [messages, isLoading, selectedModel, isResearchMode, currentSession, lowVram, textOnly, isDuplicateMessage, fetchWithRetry, append, createNewChat])

  // Handle vision messages
  const handleVisionMessage = useCallback(async (prompt: string, imageData: string, attachments: Attachment[], userTempId?: string) => {
    setIsLoading(true)

    // Add placeholder assistant message (user message already added by handleSendMessage)
    const assistantId = (Date.now() + 1).toString()
    const placeholderAiMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      model: selectedModel,
      status: 'streaming'
    }
    setLocalMessages((prev) => [...prev, placeholderAiMsg])

    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('Authentication required')
      }

      const images = attachments
        .filter(a => a.type === 'image')
        .map(a => a.data)

      let sessionId = currentSession?.id
      if (!sessionId) {
        const newSession = await createNewChat()
        sessionId = newSession?.id
      }

      const data = await fetchWithRetry('/api/vision-chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          message: prompt || 'What do you see in this image?',
          images: images,
          history: messages.map(m => ({
            role: m.role,
            content: m.content
          })),
          model: selectedModel,
          session_id: sessionId,
          low_vram: lowVram,
          text_only: textOnly
        }),
        credentials: 'include'
      }, {
        timeout: 600000,
        lowVram: lowVram
      })

      // Sync currentSession with the session used/created by vision-chat
      if (data.session_id) {
        console.log(`[Vision] Session from backend: ${data.session_id}`)
        if (data.session_id !== currentSession?.id) {
          await fetchSessions()
          // Find and set the session as current
          const visionSession = useChatHistoryStore.getState().sessions.find(s => s.id === data.session_id)
          if (visionSession) {
            setCurrentSession(visionSession)
            console.log(`[Vision] Set currentSession to: ${visionSession.id}`)
          }
        }
      }

      // Update user message status to sent
      if (userTempId) {
        setLocalMessages((prev) =>
          prev.map((msg) =>
            (msg.id === userTempId || msg.tempId === userTempId) ? { ...msg, status: "sent" } : msg
          )
        )
      }

      // Update assistant placeholder with actual response
      const assistantMessage: Message = {
        id: assistantId,
        role: "assistant",
        content: data.response || data.final_answer || 'I analyzed the image.',
        timestamp: new Date(),
        model: selectedModel,
        status: "sent",
        audioUrl: data.audio_path,
        reasoning: data.reasoning,
      }

      setLocalMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId ? assistantMessage : msg
        )
      )

    } catch (error) {
      console.error("Vision error:", error)

      // Update user message status to failed
      if (userTempId) {
        setLocalMessages((prev) =>
          prev.map((msg) =>
            (msg.id === userTempId || msg.tempId === userTempId) ? { ...msg, status: "failed" } : msg
          )
        )
      }

      // Update assistant placeholder with error message
      const errorMessage: Message = {
        id: assistantId,
        role: "assistant",
        content: `Vision analysis failed: ${error instanceof Error ? error.message : 'Unknown error'}. Make sure you have a VL model selected and pulled (llava, moondream, bakllava, etc.) on your Ollama server.`,
        timestamp: new Date(),
        model: selectedModel,
        status: "failed",
      }
      setLocalMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId ? errorMessage : msg
        )
      )
    } finally {
      setIsLoading(false)
    }
  }, [currentSession, selectedModel, messages, lowVram, textOnly, fetchWithRetry, createNewChat, fetchSessions, setCurrentSession])

  // Memoize the message list rendering to prevent re-renders during streaming
  const messageList = useMemo(() => {
    return messages.map((message, index) => (
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
        videos={message.videos}
        audioUrl={message.audioUrl}
        reasoning={message.reasoning}
        imageUrl={message.imageUrl}
        inputType={message.inputType}
        status={message.status}
        metadata={message.metadata}
        researchChain={message.researchChain}
      />
    ))
  }, [messages])

  if (isAuthLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <Sparkles className="h-10 w-10 animate-pulse text-primary" />
      </div>
    )
  }

  if (!user) {
    return null
  }

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Sidebar */}
      <div
        className={`${sidebarOpen ? "translate-x-0" : "-translate-x-full"
          } fixed inset-y-0 left-0 z-30 h-full transition-transform duration-300 lg:relative lg:translate-x-0`}
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
        {/* Header */}
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

        {/* Chat Area */}
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
              messageList
            )}
            {isLoading && messages[messages.length - 1]?.role !== 'assistant' && (
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

        {/* Input Area */}
        <div className="sticky bottom-0 z-10 shrink-0 border-t border-border bg-background">
          <ChatInput
            onSend={handleSendMessage}
            isLoading={isLoading}
            isResearchMode={isResearchMode}
            selectedModel={selectedModel}
            sessionId={currentSession?.id}
          />
        </div>
      </div>
    </div>
  )
}
