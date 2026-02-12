"use client"

import React, { useRef, useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, Loader2, Send, ChevronDown, ChevronUp, User, Bot } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { safeTrim, toStr } from '@/lib/strings'

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  reasoning?: string
}

interface AIChatPanelProps {
  chatMessages: ChatMessage[]
  isAIProcessing: boolean
  selectedModel: string
  availableModels: Array<{ name: string; provider: string; type: string }>
  onSendMessage: (message: string) => void
  onModelChange: (model: string) => void
  className?: string
}

export default function AIChatPanel({
  chatMessages,
  isAIProcessing,
  selectedModel,
  availableModels,
  onSendMessage,
  onModelChange,
  className = ""
}: AIChatPanelProps) {
  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [showReasoning, setShowReasoning] = useState<{ [key: number]: boolean }>({})

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [chatMessages])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [input])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!safeTrim(input) || isAIProcessing) return

    const message = safeTrim(input)
    setInput("")
    onSendMessage(message)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const toggleReasoning = (index: number) => {
    setShowReasoning(prev => ({
      ...prev,
      [index]: !prev[index]
    }))
  }

  const formatTimestamp = (timestamp: Date) => {
    return timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className={`h-full flex flex-col bg-gray-900 ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-400" />
            <h3 className="font-semibold text-white">AI Assistant</h3>
          </div>
          
          {/* Model Selector */}
          <div className="flex items-center gap-2">
            <select
              value={selectedModel}
              onChange={(e) => onModelChange(e.target.value)}
              className="bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-white"
            >
              {availableModels.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <Bot className="w-12 h-12 mb-4 opacity-50" />
            <p className="text-lg font-medium">Start a conversation</p>
            <p className="text-sm mt-2 text-center">
              Ask me anything about your code, get help with debugging, or request explanations.
            </p>
          </div>
        ) : (
          <AnimatePresence>
            {chatMessages.map((message, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className={`flex gap-3 max-w-[80%] ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                  {/* Avatar */}
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                    message.role === 'user' 
                      ? 'bg-blue-600' 
                      : 'bg-purple-600'
                  }`}>
                    {message.role === 'user' ? (
                      <User className="w-4 h-4 text-white" />
                    ) : (
                      <Bot className="w-4 h-4 text-white" />
                    )}
                  </div>

                  {/* Message Content */}
                  <div className={`flex flex-col ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                    <Card className={`p-3 ${
                      message.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-800 text-white border-gray-700'
                    }`}>
                      <div className="whitespace-pre-wrap text-sm">
                        {message.content}
                      </div>
                    </Card>

                    {/* Reasoning Toggle */}
                    {message.reasoning && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleReasoning(index)}
                        className="mt-2 text-xs text-gray-400 hover:text-white"
                      >
                        {showReasoning[index] ? (
                          <>
                            <ChevronUp className="w-3 h-3 mr-1" />
                            Hide Reasoning
                          </>
                        ) : (
                          <>
                            <ChevronDown className="w-3 h-3 mr-1" />
                            Show Reasoning
                          </>
                        )}
                      </Button>
                    )}

                    {/* Reasoning Content */}
                    {message.reasoning && showReasoning[index] && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mt-2 w-full"
                      >
                        <Card className="p-3 bg-gray-800 border-gray-700">
                          <div className="text-xs text-gray-300 whitespace-pre-wrap">
                            {message.reasoning}
                          </div>
                        </Card>
                      </motion.div>
                    )}

                    {/* Timestamp */}
                    <div className="text-xs text-gray-500 mt-1">
                      {formatTimestamp(message.timestamp)}
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}

        {/* Processing Indicator */}
        {isAIProcessing && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-3 justify-start"
          >
            <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <Card className="p-3 bg-gray-800 border-gray-700">
              <div className="flex items-center gap-2 text-sm text-gray-300">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>AI is thinking...</span>
              </div>
            </Card>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-700 flex-shrink-0">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask me anything about your code..."
            className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
            rows={1}
            disabled={isAIProcessing}
          />
          <Button
            type="submit"
            disabled={!safeTrim(input) || isAIProcessing}
            className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2"
          >
            {isAIProcessing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </form>
      </div>
    </div>
  )
}
