
"use client"

import type React from "react"

import { useState, useRef, useEffect, forwardRef, useImperativeHandle, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  Send,
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  Cpu,
  Zap,
  Target,
  Monitor,
  Globe,
  Search,
  ExternalLink,
  BookOpen,
  RefreshCw,
  Wifi,
  WifiOff,
  MessageSquare,
} from "lucide-react"
import { v4 as uuidv4 } from 'uuid'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useAIOrchestrator } from "./AIOrchestrator"
import { useAIInsights } from "@/hooks/useAIInsights"
import ChatHistory from "./ChatHistory"
import { useChatHistoryStore } from "@/stores/chatHistoryStore"
import AuthStatus from "./AuthStatus"

interface Message {
  id?: string;
  tempId?: string;
  status?: "pending" | "sent" | "failed";
  role: "user" | "assistant";
  content: string;
  timestamp: Date
  model?: string
  inputType?: "text" | "voice" | "screen"
  searchResults?: SearchResult[]
  searchQuery?: string
}


interface SearchResult {
  title: string
  url: string
  snippet: string
  timestamp: string
}

interface ResearchChatResponse {
  history: Message[]
  audio_path?: string
  searchResults?: SearchResult[]
  searchQuery?: string
  reasoning?: string  // Reasoning content from reasoning models
  final_answer?: string  // Final answer without reasoning
}


export interface ChatHandle {
  addAIMessage: (content: string, source?: string) => void;
}

const UnifiedChatInterface = forwardRef<ChatHandle, {}>((_, ref) => {
  const { orchestrator, hardware, models, ollamaModels, ollamaConnected, ollamaError, refreshOllamaModels } = useAIOrchestrator()
  
  const { logUserInteraction, completeInsight, logReasoningProcess } = useAIInsights()
  
  // Chat history integration
  const { 
    currentSession, 
    messages: storeMessages, 
    createSession, 
    createNewChat, 
    selectSession,
    refreshSessionMessages,
    isHistoryVisible,
    error: storeError,
    isLoadingMessages 
  } = useChatHistoryStore()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [lastSyncedMessages, setLastSyncedMessages] = useState<number>(0)
  
  const [selectedModel, setSelectedModel] = useState("auto")
  const [priority, setPriority] = useState<"speed" | "accuracy" | "balanced">("balanced")

  const [messages, setMessages] = useState<Message[]>([])
  const [isUsingStoreMessages, setIsUsingStoreMessages] = useState(false)
  const [inputValue, setInputValue] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  const [isResearchMode, setIsResearchMode] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [lastSearchQuery, setLastSearchQuery] = useState("")

  // Voice recording states
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])


  // Expose method to add AI messages from external components
  useImperativeHandle(ref, () => ({
    addAIMessage: (content: string, source = "AI") => {
      const aiMessage: Message = {
        role: "assistant",
        content: content,
        timestamp: new Date(),
        model: source,
        inputType: "screen",
      }
      setMessages((prev) => [...prev, aiMessage])
    },
  }))

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Primary session sync effect - handles session changes
  useEffect(() => {
    const currentSessionId = currentSession?.id || null
    
    if (currentSessionId !== sessionId) {
      console.log(`🔄 Session change detected: ${sessionId} -> ${currentSessionId}`)
      
      setSessionId(currentSessionId)
      
      if (currentSessionId) {
        setIsUsingStoreMessages(true)
        // Clear messages immediately for responsive UI
        setMessages([])
        setLastSyncedMessages(0)
        console.log(`🔄 Switching to session ${currentSessionId} - cleared local messages`)
      } else {
        setIsUsingStoreMessages(false)
        setMessages([])
        setLastSyncedMessages(0)
        console.log('🆕 Started new chat - cleared messages')
      }
    }
  }, [currentSession?.id, sessionId])
  
  // Message sync effect - handles message updates for current session
  useEffect(() => {
    if (isUsingStoreMessages && currentSession?.id === sessionId && storeMessages) {
        setMessages(prevMessages => {
            const localMap = new Map<string, Message>();
            prevMessages.forEach(m => {
                if (m.tempId) localMap.set(m.tempId, m);
                else if (m.id) localMap.set(m.id, m);
            });

            const reconciled = storeMessages.map(storeMsg => {
                const storeMsgCasted = storeMsg as any;
                const key = storeMsgCasted.tempId || storeMsgCasted.id;
                const timestamp = storeMsgCasted.created_at ? new Date(storeMsgCasted.created_at) : new Date();
                
                if (key && localMap.has(key)) {
                    return {
                        ...storeMsg,
                        status: "sent",
                        timestamp,
                    } as Message;
                }
                return {
                    ...storeMsg,
                    status: "sent",
                    timestamp,
                } as Message;
            });

            return reconciled;
        });
    }
}, [storeMessages, isUsingStoreMessages, currentSession?.id, sessionId]);

  
  const handleCreateSession = useCallback(async () => {
    if (!sessionId) {
      try {
        const newSession = await createSession('New Chat', selectedModel)
        if (newSession) {
          setSessionId(newSession.id)
        }
      } catch (error) {
        console.error('Failed to create session:', error)
      }
    }
  }, [sessionId, selectedModel]) // Removed createSession from deps to prevent recreation

  // Create new session when first message is sent and no session exists - stabilized
  useEffect(() => {
    if (messages.length === 1 && !sessionId && !currentSession && !isUsingStoreMessages) {
      // Use a timeout to prevent race conditions
      const timeoutId = setTimeout(() => {
        handleCreateSession()
      }, 100)
      
      return () => clearTimeout(timeoutId)
    }
  }, [messages.length, sessionId, currentSession, isUsingStoreMessages]) // Removed handleCreateSession from deps

  const handleSessionSelect = async (selectedSessionId: string) => {
    try {
      console.log(`🎯 UI: Selecting session ${selectedSessionId}`)
      
      // Let the store handle session selection and message loading
      await selectSession(selectedSessionId)
      
      // If messages don't load within a reasonable time, try refreshing
      setTimeout(async () => {
        const currentState = useChatHistoryStore.getState()
        if (currentState.currentSession?.id === selectedSessionId && 
            currentState.messages.length === 0 && 
            !currentState.isLoadingMessages &&
            currentState.currentSession.message_count > 0) {
          console.log(`🔄 Messages didn't load, attempting refresh for session ${selectedSessionId}`)
          await refreshSessionMessages(selectedSessionId)
        }
      }, 2000)
      
    } catch (error) {
      console.error('Failed to select session:', error)
    }
  }
  

  const persistMessage = async (message: Message, reasoning?: string) => {
    if (!sessionId) return

    try {
      const token = localStorage.getItem('token')
      console.log('UnifiedChatInterface: Retrieved token:', token ? `${token.substring(0, 20)}...` : 'null')
      
      if (!token) {
        console.error('UnifiedChatInterface: No token found')
        return
      }
      
      const response = await fetch('/api/chat-history/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          session_id: sessionId,
          role: message.role,
          content: message.content,
          reasoning: reasoning,
          model_used: message.model,
          input_type: message.inputType || 'text',
          metadata: {
            timestamp: message.timestamp.toISOString(),
            ...(message.searchResults && { searchResults: message.searchResults }),
            ...(message.searchQuery && { searchQuery: message.searchQuery }),
          },
        }),
        credentials: 'include',
      })

      if (!response.ok) {
        console.error('Failed to persist message:', response.statusText)
      }
    } catch (error) {
      console.error('Error persisting message:', error)
    }
  }

  const getOptimalModel = (message: string): string => {
    if (selectedModel !== "auto") {
      // If user selected a specific model, use it
      return selectedModel
    }

    // Auto-select mode: analyze message to determine best model
    const lowerMessage = message.toLowerCase()
    let taskType = "general"

    if (lowerMessage.includes("code") || lowerMessage.includes("program") || lowerMessage.includes("debug")) {
      taskType = "code"
    } else if (lowerMessage.includes("write") || lowerMessage.includes("creative") || lowerMessage.includes("story")) {
      taskType = "creative"
    } else if (lowerMessage.includes("translate") || lowerMessage.includes("language")) {
      taskType = "multilingual"
    } else if (lowerMessage.includes("quick") || lowerMessage.includes("fast")) {
      taskType = "lightweight"
    }

    // Use the orchestrator to select optimal model from available models
    const optimalModel = orchestrator.selectOptimalModel(taskType, priority)
    
    // If the optimal model is available in our models list, use it
    // Otherwise, fall back to first available Ollama model or built-in model
    if (models.includes(optimalModel)) {
      return optimalModel
    }
    
    // Fallback: prefer Ollama models if available, otherwise use built-in
    if (ollamaModels.length > 0) {
      return ollamaModels[0]
    }
    
    return orchestrator.getAllModels()[0]?.name || "mistral"
  }


// ... (rest of the component)

  const sendMessage = async (inputType: "text" | "voice" = "text") => {
    if ((!inputValue.trim() && inputType === "text") || isLoading) return

    const messageContent = inputType === "text" ? inputValue : "Voice message"
    const tempId = uuidv4();
    const optimalModel = getOptimalModel(messageContent)

    const optimisticMessage: Message = {
      tempId,
      role: "user",
      content: messageContent,
      timestamp: new Date(),
      model: optimalModel,
      inputType,
      status: "pending",
    }

    setMessages(prev => [...prev, optimisticMessage])
    if (inputType === "text") setInputValue("")
    setIsLoading(true)
    
    // Log user interaction for AI insights
    const userInsightId = logUserInteraction(messageContent, optimalModel)

    // Persist user message only if we have a session
    if (currentSession?.id) {
      await persistMessage(optimisticMessage)
    }

    const needsWebSearch =
      isResearchMode &&
      (messageContent.toLowerCase().includes("search") ||
        messageContent.toLowerCase().includes("research") ||
        messageContent.toLowerCase().includes("latest") ||
        messageContent.toLowerCase().includes("current") ||
        messageContent.toLowerCase().includes("news") ||
        messageContent.toLowerCase().includes("what is") ||
        messageContent.toLowerCase().includes("who is") ||
        messageContent.toLowerCase().includes("when did") ||
        messageContent.toLowerCase().includes("how to"))

    const apiEndpoint = needsWebSearch ? "/api/research-chat" : "/api/chat"
    const contextMessages = messages

    const payload = {
      message: messageContent,
      history: contextMessages,
      model: optimalModel,
      session_id: currentSession?.id || sessionId || null,
      tempId, // Pass tempId to the backend
      ...(needsWebSearch && {
        enableWebSearch: true,
        exaggeration: 0.5,
        temperature: 0.8,
        cfg_weight: 0.5
      }),
    }

    try {
      const response = await fetch(apiEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        credentials: 'include',
      })

      if (!response.ok) throw new Error(await response.text())

      const data: ResearchChatResponse = await response.json()

      setMessages(currentMessages => {
        // Update optimistic user message to "sent" status if it matches tempId
        const updatedMessages = [...currentMessages]
        const optimisticIndex = updatedMessages.findIndex(msg => msg.tempId === tempId)
        if (optimisticIndex >= 0) {
          updatedMessages[optimisticIndex] = {
            ...updatedMessages[optimisticIndex],
            status: "sent"
          }
        }

        // Add only the latest assistant message if it's not already present
        const serverAssistantMessages = data.history.filter(msg => msg.role === "assistant")
        const latestAssistantMessage = serverAssistantMessages[serverAssistantMessages.length - 1]
        
        if (latestAssistantMessage) {
          // Check if this assistant message already exists (by content and timestamp proximity)
          const isDuplicate = updatedMessages.some(existingMsg => 
            existingMsg.role === "assistant" && 
            existingMsg.content === latestAssistantMessage.content &&
            Math.abs(existingMsg.timestamp.getTime() - new Date().getTime()) < 5000 // Within 5 seconds
          )
          
          if (!isDuplicate) {
            const newAssistantMessage = {
              ...latestAssistantMessage,
              status: "sent" as const,
              timestamp: new Date((latestAssistantMessage as any).timestamp || Date.now())
            }
            updatedMessages.push(newAssistantMessage)
          }
        }

        return updatedMessages
      })

      const assistantResponse = data.history.find(msg => msg.role === "assistant")
      if (assistantResponse && currentSession?.id) {
        const aiMessage: Message = {
          ...assistantResponse,
          timestamp: new Date(),
          model: optimalModel,
          inputType: "text",
        }
        await persistMessage(aiMessage, data.reasoning)
      }

      // Complete the user interaction insight
      if (assistantResponse) {
        completeInsight(userInsightId, `Response generated using ${optimalModel}`, "done")
      }

      // Handle reasoning content if present
      if (data.reasoning) {
        // Log the reasoning process in AI insights
        const reasoningInsightId = logReasoningProcess(data.reasoning, optimalModel)
        completeInsight(reasoningInsightId, "Reasoning process completed", "done")
      }

      if (data.searchResults) {
        setSearchResults(data.searchResults)
        setLastSearchQuery(data.searchQuery || messageContent)
      }

      if (data.audio_path) {
        setAudioUrl(data.audio_path)
        setTimeout(() => {
          if (audioRef.current) {
            audioRef.current.play().catch(() => {
              console.warn("Autoplay blocked. Use Replay button.")
            })
          }
        }, 500)
      }
    } catch (error) {
      console.error(`Chat attempt failed:`, error)
      setMessages(currentMessages => currentMessages.map(msg =>
        msg.tempId === tempId ? { ...msg, status: "failed" } : msg
      ))
      
      // Complete the user interaction insight with error
      completeInsight(userInsightId, `Error: ${error}`, "error")
    } finally {
      setIsLoading(false)
    }
  }

  const performWebSearch = async (query: string) => {
    if (!query.trim() || isSearching) return

    setIsSearching(true)
    setLastSearchQuery(query)

    try {
      const response = await fetch("/api/web-search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          model: selectedModel === "auto" ? "mistral" : selectedModel,
          maxResults: 5,
        }),
        credentials: 'include',
      })

      if (response.ok) {
        const data = await response.json()
        setSearchResults(data.results || [])

        // Add search results as a system message
        const searchMessage: Message = {
          role: "assistant",
          content: `Found ${data.results?.length || 0} search results for "${query}"`,
          timestamp: new Date(),
          model: "Web Search",
          inputType: "text",
          searchResults: data.results,
          searchQuery: query,
        }
        setMessages((prev) => [...prev, searchMessage])
      }
    } catch (error) {
      console.error("Web search failed:", error)
    } finally {
      setIsSearching(false)
    }
  }


  const toggleAudio = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause()
      } else {
        audioRef.current.play()
      }
    }
  }

  // Voice recording functions
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" })
        await sendAudioToBackend(audioBlob)
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
    } catch (error) {
      console.error("Error accessing microphone:", error)
      alert("Unable to access microphone. Please check permissions.")
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      setIsProcessing(true)
    }
  }

  const sendAudioToBackend = async (audioBlob: Blob) => {
    // Use the selected model instead of auto-selecting
    console.log("🎤 Voice Chat Debug - selectedModel:", selectedModel)
    const modelToUse = selectedModel === "auto" 
      ? orchestrator.selectOptimalModel("voice", priority)
      : selectedModel
    console.log("🎤 Voice Chat Debug - modelToUse:", modelToUse)

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const formData = new FormData()
        formData.append("file", audioBlob, "mic.wav")
        formData.append("model", modelToUse)
        if (currentSession?.id || sessionId) {
          formData.append("session_id", currentSession?.id || sessionId || "")
        }

        const response = await fetch("/api/mic-chat", {
          method: "POST",
          body: formData,
          credentials: 'include',
        })

        if (!response.ok) throw new Error("Network response was not ok")

        const data = await response.json()

        // Update messages with voice input
        const updatedHistory = data.history.map((msg: any, index: number) => ({
          ...msg,
          timestamp: new Date(),
          model: msg.role === "assistant" ? modelToUse : undefined,
          inputType: index === data.history.length - 2 ? "voice" : msg.inputType,
        }))

        // Update messages for current session only
        setMessages(updatedHistory)

        // Persist voice messages to current session
        const userVoiceMsg = data.history.find((msg: any) => msg.role === "user")
        const assistantResponse = data.history.find((msg: any) => msg.role === "assistant")
        
        if (currentSession?.id) {
          if (userVoiceMsg) {
            const userMessage: Message = {
              ...userVoiceMsg,
              timestamp: new Date(),
              inputType: "voice",
            }
            await persistMessage(userMessage)
          }
          if (assistantResponse) {
            const aiMessage: Message = {
              ...assistantResponse,
              timestamp: new Date(),
              model: modelToUse,
              inputType: "text",
            }
            await persistMessage(aiMessage, data.reasoning)
          }
        }

        // Handle reasoning content if present (same as regular chat)
        if (data.reasoning) {
          // Log the reasoning process in AI insights
          const reasoningInsightId = logReasoningProcess(data.reasoning, modelToUse)
          completeInsight(reasoningInsightId, "Reasoning process completed", "done")
        }

        if (data.audio_path) {
          setAudioUrl(data.audio_path)
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.play().catch(console.warn)
            }
          }, 500)
        }

        setIsProcessing(false)
        return
      } catch (error) {
        console.error(`Audio processing attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          alert("Sorry, there was an error processing your audio.")
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsProcessing(false)
  }

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const getInputTypeIcon = (inputType?: string) => {
    switch (inputType) {
      case "voice":
        return <Mic className="w-2 h-2 mr-1" />
      case "screen":
        return <Monitor className="w-2 h-2 mr-1" />
      default:
        return null
    }
  }

  return (
    <>
      <ChatHistory 
        onSessionSelect={handleSessionSelect}
        currentSessionId={sessionId || undefined}
      />
      
      {/* Error Display */}
      {storeError && (
        <div className="mb-4">
          <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 text-red-400 text-sm flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="w-2 h-2 bg-red-500 rounded-full"></div>
              <span>{storeError}</span>
            </div>
            <div className="flex space-x-2">
              {(storeError.includes('Could not load chat history') || storeError.includes('Request timed out')) && currentSession && (
                <Button
                  onClick={() => refreshSessionMessages(currentSession.id)}
                  size="sm"
                  variant="outline"
                  className="text-red-400 border-red-500/50 hover:bg-red-500/10"
                  disabled={isLoadingMessages}
                >
                  {isLoadingMessages ? 'Retrying...' : 'Retry'}
                </Button>
              )}
              {storeError.includes('Could not start new chat') && (
                <Button
                  onClick={() => window.location.reload()}
                  size="sm"
                  variant="outline"
                  className="text-red-400 border-red-500/50 hover:bg-red-500/10"
                >
                  Refresh Page
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
      
      <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 h-[700px] flex flex-col">
      <div className="p-4 border-b border-blue-500/30">
        <div className="flex justify-between items-center mb-3">
          <div className="flex items-center space-x-3">
            <div className="flex flex-col">
              <h2 className="text-xl font-semibold text-blue-300">AI Assistant</h2>
              {currentSession && (
                <div className="flex items-center space-x-2 mt-1">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                  <span className="text-xs text-gray-400 truncate max-w-48">
                    {currentSession.title}
                  </span>
                  <span className="text-xs text-gray-500">•</span>
                  <span className="text-xs text-gray-500">
                    {currentSession.message_count} messages
                  </span>
                </div>
              )}
            </div>
            <Button
              onClick={() => setIsResearchMode(!isResearchMode)}
              size="sm"
              variant={isResearchMode ? "default" : "outline"}
              className={`${
                isResearchMode
                  ? "bg-green-600 hover:bg-green-700 text-white"
                  : "bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
              }`}
            >
              <Globe className="w-3 h-3 mr-1" />
              Research Mode
            </Button>
          </div>
          <div className="flex items-center space-x-4">
            {/* Authentication Status */}
            <AuthStatus />
            
            {/* Ollama Connection Status */}
            <div className="flex items-center space-x-2">
              <Badge 
                variant="outline" 
                className={`text-xs ${ollamaConnected ? 'border-green-500 text-green-400' : 'border-red-500 text-red-400'}`}
                title={ollamaError || (ollamaConnected ? 'Connected to Ollama server' : 'Cannot connect to Ollama server')}
              >
                {ollamaConnected ? <Wifi className="w-3 h-3 mr-1" /> : <WifiOff className="w-3 h-3 mr-1" />}
                Ollama {ollamaConnected ? `(${ollamaModels.length} models)` : 'Offline'}
              </Badge>
              <Button
                onClick={refreshOllamaModels}
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0 text-gray-400 hover:text-white"
                title={`Refresh Ollama models${ollamaError ? ` (Last error: ${ollamaError})` : ''}`}
              >
                <RefreshCw className="w-3 h-3" />
              </Button>
            </div>
            
            {hardware && (
              <div className="flex items-center space-x-2 text-xs">
                <Badge variant="outline" className="border-green-500 text-green-400">
                  <Cpu className="w-3 h-3 mr-1" />
                  {hardware.cpuCores} cores
                </Badge>
                {hardware.gpu && (
                  <Badge variant="outline" className="border-blue-500 text-blue-400">
                    GPU ✓
                  </Badge>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between space-x-4">
          <div className="flex items-center space-x-2">
            <span className="text-sm text-gray-400">Model:</span>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1 focus:border-blue-500 focus:outline-none min-w-[200px]"
            >
              {/* Auto-select option */}
              <option value="auto">🤖 Auto-Select</option>
              
              {/* Built-in models */}
              {orchestrator.getAllModels().length > 0 && (
                <optgroup label="Built-in Models">
                  {orchestrator.getAllModels().map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name.charAt(0).toUpperCase() + model.name.slice(1)}
                    </option>
                  ))}
                </optgroup>
              )}
              
              {/* Ollama models */}
              {ollamaModels.length > 0 && (
                <optgroup label={`Ollama Models (${ollamaModels.length})`}>
                  {ollamaModels.map((modelName) => (
                    <option key={modelName} value={modelName}>
                      🦙 {modelName}
                    </option>
                  ))}
                </optgroup>
              )}
              
              {/* Show message if no Ollama models */}
              {!ollamaConnected && (
                <optgroup label="Ollama (Offline)">
                  <option disabled>No Ollama models available</option>
                </optgroup>
              )}
            </select>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-sm text-gray-400">Priority:</span>
            <div className="flex space-x-1">
              <Button
                size="sm"
                variant={priority === "speed" ? "default" : "outline"}
                onClick={() => setPriority("speed")}
                className="h-6 px-2 text-xs"
              >
                <Zap className="w-3 h-3 mr-1" />
                Speed
              </Button>
              <Button
                size="sm"
                variant={priority === "balanced" ? "default" : "outline"}
                onClick={() => setPriority("balanced")}
                className="h-6 px-2 text-xs"
              >
                Balanced
              </Button>
              <Button
                size="sm"
                variant={priority === "accuracy" ? "default" : "outline"}
                onClick={() => setPriority("accuracy")}
                className="h-6 px-2 text-xs"
              >
                <Target className="w-3 h-3 mr-1" />
                Accuracy
              </Button>
            </div>
          </div>
        </div>

        {isResearchMode && (
          <div className="mt-3 p-2 bg-green-900/20 border border-green-500/30 rounded-lg">
            <div className="flex items-center space-x-2 mb-2">
              <BookOpen className="w-4 h-4 text-green-400" />
              <span className="text-sm text-green-400 font-medium">Research Mode Active</span>
            </div>
            <p className="text-xs text-gray-400">
              AI will automatically search the web for current information when needed. Use keywords like &quot;search&quot;,
              &quot;latest&quot;, &quot;current&quot;, or &quot;research&quot; to trigger web searches.
            </p>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Empty state when no session and no messages */}
        {!currentSession && messages.length === 0 && !isLoadingMessages && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <div className="text-gray-400">
              <MessageSquare className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <h3 className="text-lg font-medium text-gray-300 mb-2">Start a Conversation</h3>
              <p className="text-sm text-gray-500 max-w-md">
                Type a message below or start a new chat session to begin. Your conversations will be saved and accessible from the chat history.
              </p>
            </div>
          </div>
        )}
        
        <AnimatePresence>
          {messages.map((message, index) => (
            <motion.div
              key={message.tempId || message.id || index}
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -20, scale: 0.95 }}
              transition={{ duration: 0.3 }}
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] p-3 rounded-lg ${
                  message.role === "user" ? "bg-blue-600 text-white" : "bg-gray-700 text-gray-100"
                }`}
                style={{
                  opacity: message.status === "pending" ? 0.6 : 1,
                  borderColor: message.status === "failed" ? "red" : "transparent",
                  borderWidth: message.status === "failed" ? "1px" : "0px",
                }}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center space-x-2">
                    {message.inputType && (
                      <Badge variant="outline" className="text-xs border-purple-500 text-purple-400">
                        {getInputTypeIcon(message.inputType)}
                        {message.inputType === "screen"
                          ? "Screen"
                          : message.inputType.charAt(0).toUpperCase() + message.inputType.slice(1)}
                      </Badge>
                    )}
                    {message.model && message.role === "assistant" && (
                      <Badge variant="outline" className="text-xs border-green-500 text-green-400">
                        {message.model}
                      </Badge>
                    )}
                    {message.searchQuery && (
                      <Badge variant="outline" className="text-xs border-orange-500 text-orange-400">
                        <Search className="w-2 h-2 mr-1" />
                        Web Search
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs opacity-70">{message.timestamp.toLocaleTimeString()}</span>
                </div>
                <div className="text-sm prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      ul: ({ children }) => <ul className="list-disc ml-4 mb-2">{children}</ul>,
                      ol: ({ children }) => <ol className="list-decimal ml-4 mb-2">{children}</ol>,
                      li: ({ children }) => <li className="mb-1">{children}</li>,
                      strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
                      em: ({ children }) => <em className="italic">{children}</em>,
                      h1: ({ children }) => <h1 className="text-lg font-bold mb-2">{children}</h1>,
                      h2: ({ children }) => <h2 className="text-md font-semibold mb-2">{children}</h2>,
                      h3: ({ children }) => <h3 className="text-sm font-medium mb-1">{children}</h3>,
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-4 border-gray-500 pl-4 italic mb-2">{children}</blockquote>
                      ),
                      code: ({ children, ...props }) => {
                        const isInline = !props.className;
                        return isInline ? (
                          <code className="bg-gray-600 px-1 py-0.5 rounded text-xs">{children}</code>
                        ) : (
                          <code className="block bg-gray-600 p-2 rounded text-xs overflow-x-auto">{children}</code>
                        );
                      },
                      a: ({ href, children }) => (
                        <a href={href} className="text-blue-400 hover:text-blue-300 underline" target="_blank" rel="noopener noreferrer">
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>

                {/* Search Results Display */}
                {message.searchResults && message.searchResults.length > 0 && (
                  <div className="mt-3 space-y-2">
                    <div className="flex items-center space-x-2">
                      <Search className="w-3 h-3 text-orange-400" />
                      <span className="text-xs text-orange-400 font-medium">
                        Search Results for: &quot;{message.searchQuery}&quot;
                      </span>
                    </div>
                    <div className="space-y-2">
                      {message.searchResults.slice(0, 3).map((result, idx) => (
                        <div key={idx} className="bg-gray-800/50 rounded p-2 border-l-2 border-orange-500/50">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <h4 className="text-xs font-medium text-orange-300 mb-1 line-clamp-1">{result.title}</h4>
                              <p className="text-xs text-gray-400 mb-1 line-clamp-2">{result.snippet}</p>
                              <a
                                href={result.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-400 hover:text-blue-300 flex items-center space-x-1"
                              >
                                <span className="truncate max-w-48">{result.url}</span>
                                <ExternalLink className="w-2 h-2 flex-shrink-0" />
                              </a>
                            </div>
                          </div>
                        </div>
                      ))}
                      {message.searchResults.length > 3 && (
                        <div className="text-xs text-gray-500 text-center">
                          +{message.searchResults.length - 3} more results
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Loading indicator */}
        {(isLoading || isProcessing) && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
            <div className="bg-gray-700 p-3 rounded-lg">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
                <div
                  className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.1s" }}
                ></div>
                <div
                  className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                ></div>
              </div>
            </div>
          </motion.div>
        )}
        
        {/* Loading messages indicator */}
        {isLoadingMessages && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-center">
            <div className="bg-gray-800/50 p-3 rounded-lg border border-blue-500/30">
              <div className="flex items-center space-x-2 text-gray-400">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                <span className="text-sm">
                  {currentSession ? `Loading messages for "${currentSession.title}"...` : 'Loading chat history...'}
                </span>
              </div>
            </div>
          </motion.div>
        )}
        
        {/* Session isolation indicator */}
        {currentSession && messages.length > 0 && (
          <div className="text-center py-2">
            <div className="inline-flex items-center space-x-2 text-xs text-gray-500 bg-gray-800/30 px-3 py-1 rounded-full">
              <div className="w-1.5 h-1.5 bg-blue-500 rounded-full"></div>
              <span>Session: {currentSession.title}</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-blue-500/30">
        <div className="flex space-x-2 mb-3">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                sendMessage("text")
              }
            }}
            placeholder={isResearchMode ? "Ask me anything or request research..." : "Type your message..."}
            className="flex-1 bg-gray-800 border-gray-600 text-white placeholder-gray-400 focus:border-blue-500"
            disabled={isLoading || isProcessing}
          />
          <Button
            onClick={() => sendMessage("text")}
            disabled={isLoading || isProcessing || !inputValue.trim()}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            <Send className="w-4 h-4" />
          </Button>
          {isResearchMode && (
            <Button
              onClick={() => performWebSearch(inputValue)}
              disabled={isSearching || !inputValue.trim()}
              className="bg-orange-600 hover:bg-orange-700 text-white"
              title="Perform web search"
            >
              {isSearching ? (
                <div className="w-4 h-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <Search className="w-4 h-4" />
              )}
            </Button>
          )}
          <Button
            onClick={toggleRecording}
            disabled={isProcessing}
            className={`${
              isRecording ? "bg-red-600 hover:bg-red-700 animate-pulse" : "bg-purple-600 hover:bg-purple-700"
            } text-white`}
          >
            {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </Button>
        </div>

        {/* Search Results Summary */}
        {searchResults.length > 0 && lastSearchQuery && (
          <div className="mb-3 p-2 bg-orange-900/20 border border-orange-500/30 rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Search className="w-3 h-3 text-orange-400" />
                <span className="text-xs text-orange-400">
                  Found {searchResults.length} results for &quot;{lastSearchQuery}&quot;
                </span>
              </div>
              <Button
                onClick={() => {
                  setSearchResults([])
                  setLastSearchQuery("")
                }}
                size="sm"
                variant="ghost"
                className="text-gray-400 hover:text-white h-5 w-5 p-0"
              >
                ×
              </Button>
            </div>
          </div>
        )}

        {audioUrl && (
          <div className="flex items-center space-x-2">
            <Button
              onClick={toggleAudio}
              variant="outline"
              size="sm"
              className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
            >
              {isPlaying ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            </Button>
            <span className="text-sm text-gray-400">Voice Response</span>
            <audio
              ref={audioRef}
              src={audioUrl}
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
              onEnded={() => setIsPlaying(false)}
              className="hidden"
            />
          </div>
        )}
      </div>
    </Card>
    </>
  )
})

UnifiedChatInterface.displayName = "UnifiedChatInterface"

export default UnifiedChatInterface
