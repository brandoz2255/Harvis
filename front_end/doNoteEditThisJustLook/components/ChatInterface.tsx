"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Send, Volume2, VolumeX } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
}

interface ChatResponse {
  history: Message[]
  audio_path?: string
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return

    const userMessage: Message = {
      role: "user",
      content: inputValue,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue("")
    setIsLoading(true)

    const payload = {
      message: inputValue,
      history: messages,
      model: "mistral",
    }

    // Retry logic with 3 attempts
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        // Get the JWT token from localStorage
        const token = localStorage.getItem('token')
        console.log('ChatInterface: Retrieved token:', token ? `${token.substring(0, 20)}...` : 'null')
        if (!token) {
          throw new Error('Authentication required. Please log in.')
        }

        const response = await fetch("/api/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`,
          },
          body: JSON.stringify(payload),
          credentials: 'include', // Ensure headers are sent through proxy
        })

        if (!response.ok) throw new Error(await response.text())

        const data: ChatResponse = await response.json()

        // Clear and show full conversation history (like original)
        setMessages(
          data.history.map((msg) => ({
            ...msg,
            timestamp: new Date(),
          })),
        )

        if (data.audio_path) {
          setAudioUrl(data.audio_path)
          // Auto-play audio response
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.play().catch(() => {
                console.warn("Autoplay blocked. Use Replay button.")
              })
            }
          }, 500)
        }

        setIsLoading(false)
        return // Success, exit retry loop
      } catch (error) {
        console.error(`Chat attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          const errorMessage: Message = {
            role: "assistant",
            content: "Sorry, I'm having trouble right now.",
            timestamp: new Date(),
          }
          setMessages((prev) => [...prev, errorMessage])
        }
        // Wait before retry (exponential backoff)
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsLoading(false)
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
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

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 h-[600px] flex flex-col">
      <div className="p-4 border-b border-blue-500/30">
        <h2 className="text-xl font-semibold text-blue-300">Chat Interface</h2>
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
                <span className="text-xs opacity-70 mt-1 block">{message.timestamp.toLocaleTimeString()}</span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {isLoading && (
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
        <div className="flex space-x-2">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Type your message..."
            className="flex-1 bg-gray-800 border-gray-600 text-white placeholder-gray-400 focus:border-blue-500"
            disabled={isLoading}
          />
          <Button
            onClick={sendMessage}
            disabled={isLoading || !inputValue.trim()}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>

        {audioUrl && (
          <div className="mt-3 flex items-center space-x-2">
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
}
