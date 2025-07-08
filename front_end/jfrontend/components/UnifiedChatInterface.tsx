
"use client"

import type React from "react"

import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from "react"
import { motion, AnimatePresence } from "framer-motion"
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
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useAIOrchestrator } from "./AIOrchestrator"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  model?: string
  inputType?: "text" | "voice" | "screen"
  searchResults?: SearchResult[]
  searchQuery?: string
}

interface ChatResponse {
  history: Message[]
  audio_path?: string
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
}


export interface ChatHandle {
  addAIMessage: (content: string, source?: string) => void;
}

const UnifiedChatInterface = forwardRef<ChatHandle, {}>((props, ref) => {
  const { orchestrator, hardware, isDetecting } = useAIOrchestrator()
  const [selectedModel, setSelectedModel] = useState("auto")
  const [priority, setPriority] = useState<"speed" | "accuracy" | "balanced">("balanced")

  const [messages, setMessages] = useState<Message[]>([])
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

  const availableModels = [
    { value: "auto", label: "🤖 Auto-Select" },
    ...orchestrator.getAllModels().map((model) => ({
      value: model.name,
      label: model.name.charAt(0).toUpperCase() + model.name.slice(1),
    })),
  ]

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

  const getOptimalModel = (message: string): string => {
    if (selectedModel !== "auto") return selectedModel

    // Analyze message to determine task type
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

    return orchestrator.selectOptimalModel(taskType, priority)
  }

  const sendMessage = async (inputType: "text" | "voice" = "text") => {
    if ((!inputValue.trim() && inputType === "text") || isLoading) return

    const messageContent = inputType === "text" ? inputValue : "Voice message"
    const optimalModel = getOptimalModel(messageContent)

    const userMessage: Message = {
      role: "user",
      content: messageContent,
      timestamp: new Date(),
      model: optimalModel,
      inputType,
    }

    setMessages((prev) => [...prev, userMessage])
    if (inputType === "text") setInputValue("")
    setIsLoading(true)

    // Check if research mode is enabled and if the query seems to need web search
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
    const payload = {
      message: messageContent,
      history: messages,
      model: optimalModel,
      ...(needsWebSearch && { enableWebSearch: true }),
    }

    // Retry logic with 3 attempts
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        })

        if (!response.ok) throw new Error(await response.text())

        const data: ResearchChatResponse = await response.json()

        // Update messages with model info and search results
        const updatedHistory = data.history.map((msg, index) => ({
          ...msg,
          timestamp: new Date(),
          model: msg.role === "assistant" ? optimalModel : msg.model,
          ...(index === data.history.length - 1 &&
            msg.role === "assistant" && {
              searchResults: data.searchResults,
              searchQuery: data.searchQuery,
            }),
        }))

        setMessages(updatedHistory)

        // Update search results if available
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

        setIsLoading(false)
        return
      } catch (error) {
        console.error(`Chat attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          const errorMessage: Message = {
            role: "assistant",
            content: "Sorry, I'm having trouble right now.",
            timestamp: new Date(),
            inputType: "text",
          }
          setMessages((prev) => [...prev, errorMessage])
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsLoading(false)
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

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage("text")
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
    const optimalModel = orchestrator.selectOptimalModel("voice", priority)

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const formData = new FormData()
        formData.append("file", audioBlob, "mic.wav")
        formData.append("model", optimalModel)

        const response = await fetch("/api/mic-chat", {
          method: "POST",
          body: formData,
        })

        if (!response.ok) throw new Error("Network response was not ok")

        const data = await response.json()

        // Update messages with voice input
        const updatedHistory = data.history.map((msg: any, index: number) => ({
          ...msg,
          timestamp: new Date(),
          model: msg.role === "assistant" ? optimalModel : undefined,
          inputType: index === data.history.length - 2 ? "voice" : msg.inputType,
        }))

        setMessages(updatedHistory)

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
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 h-[700px] flex flex-col">
      <div className="p-4 border-b border-blue-500/30">
        <div className="flex justify-between items-center mb-3">
          <div className="flex items-center space-x-3">
            <h2 className="text-xl font-semibold text-blue-300">AI Assistant</h2>
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
              className="bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1 focus:border-blue-500 focus:outline-none"
            >
              {availableModels.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
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
        <AnimatePresence>
          {messages.map((message, index) => (
            <motion.div
              key={index}
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
                <p className="text-sm">{message.content}</p>

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
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-blue-500/30">
        <div className="flex space-x-2 mb-3">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
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
  )
})

UnifiedChatInterface.displayName = "UnifiedChatInterface"

export default UnifiedChatInterface
