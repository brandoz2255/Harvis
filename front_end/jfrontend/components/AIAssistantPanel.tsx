"use client"

import React, { useRef, useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Sparkles, Loader2, Send, ChevronDown, ChevronUp, User, Bot } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  reasoning?: string
}

interface AIAssistantPanelProps {
  sessionId: string | null
  containerStatus: string
  selectedFile: string | null
  onSendMessage: (message: string) => Promise<void>
  messages: ChatMessage[]
  isProcessing: boolean
  selectedModel: string
  availableModels: Array<{ name: string; provider: string; type: string }>
  onModelChange: (model: string) => void
  className?: string
}

const AIAssistantPanel: React.FC<AIAssistantPanelProps> = ({
  sessionId,
  containerStatus,
  selectedFile,
  onSendMessage,
  messages,
  isProcessing,
  selectedModel,
  availableModels,
  onModelChange,
  className = ""
}) => {
  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [input])

  const handleSend = async () => {
    if (!input.trim() || !sessionId || isProcessing) return
    
    await onSendMessage(input)
    setInput("")
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter to send, Shift+Enter for new line
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Model Selector */}
      <div className="p-4 border-b border-purple-500/30 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-purple-400" />
          <select
            value={selectedModel}
            onChange={(e) => onModelChange(e.target.value)}
            className="flex-1 bg-gray-800 border border-gray-600 text-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
          >
            {availableModels.length > 0 ? (
              availableModels.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.name} ({model.provider})
                </option>
              ))
            ) : (
              <option value={selectedModel}>{selectedModel}</option>
            )}
          </select>
        </div>
      </div>

      {/* Chat Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center text-center">
            <div>
              <Sparkles className="w-12 h-12 text-purple-400 mx-auto mb-4" />
              <p className="text-gray-400 text-sm">AI Assistant Ready</p>
              <p className="text-gray-500 text-xs mt-2">
                Ask me anything about your code!
              </p>
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <ChatMessageBubble key={idx} message={msg} />
            ))}
            {isProcessing && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-purple-400" />
                </div>
                <div className="flex-1">
                  <Card className="bg-gray-800/50 border-gray-700 p-3 inline-block">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                      <span className="text-sm text-gray-400">Thinking...</span>
                    </div>
                  </Card>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4 border-t border-purple-500/30 flex-shrink-0">
        {!sessionId ? (
          <div className="text-center py-4">
            <p className="text-gray-500 text-sm">
              Select a session to chat with AI
            </p>
          </div>
        ) : (
          <div className="flex gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Ask the AI assistant... (Shift+Enter for new line)"
              disabled={isProcessing}
              rows={1}
              className="flex-1 bg-gray-800 border border-gray-600 text-gray-200 placeholder:text-gray-500 rounded px-3 py-2 text-sm focus:outline-none focus:border-purple-500 resize-none max-h-32 overflow-y-auto"
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isProcessing}
              className="bg-purple-600 hover:bg-purple-700 text-white self-end"
            >
              <Send className="w-4 h-4" />
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

// Chat Message Bubble Component
const ChatMessageBubble: React.FC<{ message: ChatMessage }> = ({ message }) => {
  const [showReasoning, setShowReasoning] = useState(false)
  const isUser = message.role === "user"

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-purple-600' : 'bg-gray-700'
      }`}>
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-purple-400" />
        )}
      </div>

      {/* Message Content */}
      <div className={`flex-1 ${isUser ? 'flex justify-end' : ''}`}>
        <div className={`inline-block max-w-[85%] ${isUser ? 'text-right' : ''}`}>
          <Card className={`p-3 ${
            isUser 
              ? 'bg-purple-600 border-purple-500 text-white' 
              : 'bg-gray-800/50 border-gray-700 text-gray-200'
          }`}>
            <MessageContent content={message.content} isUser={isUser} />
          </Card>

          {/* Reasoning (for AI messages only) */}
          {!isUser && message.reasoning && (
            <div className="mt-2">
              <button
                onClick={() => setShowReasoning(!showReasoning)}
                className="text-xs text-gray-500 hover:text-gray-400 flex items-center gap-1"
              >
                {showReasoning ? (
                  <>
                    <ChevronUp className="w-3 h-3" />
                    Hide reasoning
                  </>
                ) : (
                  <>
                    <ChevronDown className="w-3 h-3" />
                    Show reasoning
                  </>
                )}
              </button>
              <AnimatePresence>
                {showReasoning && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mt-2"
                  >
                    <Card className="bg-gray-900/50 border-gray-700 p-3">
                      <p className="text-xs text-gray-400">{message.reasoning}</p>
                    </Card>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}

          {/* Timestamp */}
          <div className={`text-xs text-gray-500 mt-1 ${isUser ? 'text-right' : ''}`}>
            {message.timestamp.toLocaleTimeString()}
          </div>
        </div>
      </div>
    </motion.div>
  )
}

// Message Content Component with code block formatting
const MessageContent: React.FC<{ content: string; isUser: boolean }> = ({ content, isUser }) => {
  // Ensure content is always a string, not a Blob or other object
  const contentStr = typeof content === 'string' ? content : String(content || '')
  
  // Simple code block detection and formatting
  const parts = contentStr.split(/(```[\s\S]*?```|`[^`]+`)/g)

  return (
    <div className="text-sm whitespace-pre-wrap break-words">
      {parts.map((part, idx) => {
        // Multi-line code block
        if (part.startsWith('```') && part.endsWith('```')) {
          const code = part.slice(3, -3).trim()
          const lines = code.split('\n')
          const language = lines[0].match(/^[a-z]+$/) ? lines.shift() : ''
          const codeContent = lines.join('\n')

          return (
            <div key={idx} className="my-2">
              {language && (
                <Badge variant="outline" className="mb-1 text-xs border-gray-600 text-gray-400">
                  {language}
                </Badge>
              )}
              <pre className={`${
                isUser ? 'bg-purple-700/30' : 'bg-gray-900'
              } border border-gray-700 rounded p-3 overflow-x-auto`}>
                <code className="text-xs font-mono">{codeContent}</code>
              </pre>
            </div>
          )
        }
        
        // Inline code
        if (part.startsWith('`') && part.endsWith('`')) {
          const code = part.slice(1, -1)
          return (
            <code
              key={idx}
              className={`${
                isUser ? 'bg-purple-700/30' : 'bg-gray-900'
              } px-1.5 py-0.5 rounded text-xs font-mono`}
            >
              {code}
            </code>
          )
        }

        // Regular text
        return <span key={idx}>{part}</span>
      })}
    </div>
  )
}

export default AIAssistantPanel
