'use client'

/**
 * IDE AI Assistant Panel
 * Chat interface for AI code assistance
 * Separate from home chat, linked to IDE session
 */

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  Send,
  Paperclip,
  X,
  Code,
  FileCode,
  Loader2,
  Copy,
  Check,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IDEChatAPI, IDEProvidersAPI, ChatMessage, ChatAttachment, ProviderInfo } from '../lib/ide-api'
import { useToast } from './Toast'
import { useRouter } from 'next/navigation'

interface AIAssistantProps {
  sessionId: string | null
  onInsertAtCursor?: (text: string) => void
  currentFilePath?: string
  copilotModel?: string
  onCopilotModelChange?: (model: string) => void
  copilotEnabled?: boolean
  onCopilotToggle?: () => void
}

interface Message extends ChatMessage {
  id: string
  timestamp: Date
}

export function AIAssistant({
  sessionId,
  onInsertAtCursor,
  currentFilePath,
  copilotModel = 'gpt-oss',
  onCopilotModelChange,
  copilotEnabled = true,
  onCopilotToggle,
}: AIAssistantProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const toast = useToast()
  const router = useRouter()
  const [model, setModel] = useState<string>('gpt-oss')
  const [availableProviders, setAvailableProviders] = useState<ProviderInfo[]>([])
  const [isLoadingProviders, setIsLoadingProviders] = useState(false)

  // Load available providers on mount
  useEffect(() => {
    const loadProviders = async () => {
      setIsLoadingProviders(true)
      try {
        const response = await IDEProvidersAPI.getProviders()
        setAvailableProviders(response.providers)
        // Set default model if available
        if (response.providers.length > 0 && !response.providers.find(p => p.id === model)) {
          const codeProvider = response.providers.find(p => p.capabilities.includes('code'))
          if (codeProvider) {
            setModel(codeProvider.id)
          } else {
            setModel(response.providers[0].id)
          }
        }
      } catch (error) {
        console.error('Failed to load providers:', error)
        // Fallback to default
        setAvailableProviders([{ id: 'gpt-oss', label: 'GPT-OSS', type: 'ollama', capabilities: ['chat', 'completion', 'code'] }])
      } finally {
        setIsLoadingProviders(false)
      }
    }
    loadProviders()
  }, [])


  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // Focus textarea on mount
  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const handleSend = useCallback(async () => {
    if (!input.trim() || !sessionId || isStreaming) return

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsStreaming(true)

    // Prepare assistant message
    const assistantMessageId = `assistant-${Date.now()}`
    let assistantContent = ''

    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        timestamp: new Date(),
      },
    ])

    try {
      // Stream response
      const history: ChatMessage[] = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }))

      for await (const token of IDEChatAPI.send(
        sessionId,
        userMessage.content,
        history,
        attachments.length > 0 ? attachments : undefined,
        undefined,
        model
      )) {
        assistantContent += token
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? { ...m, content: assistantContent }
              : m
          )
        )
      }

      // Clear attachments after send
      setAttachments([])
    } catch (error: any) {
      console.error('Chat error:', error)
      
      // Check for 401 Unauthorized
      const isUnauthorized = error.message?.includes('401') || 
                            error.message?.includes('Unauthorized') ||
                            error.message?.includes('Authorization missing')
      
      if (isUnauthorized) {
        toast.error('Authentication required. Please log in again.', 5000)
        // Show re-authenticate button
        setTimeout(() => {
          if (confirm('Your session has expired. Would you like to log in again?')) {
            router.push('/login')
          }
        }, 500)
      } else {
        toast.error(`Chat error: ${error.message || 'Failed to get response'}`)
      }
      
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMessageId
            ? {
                ...m,
                content: `Error: ${error.message || 'Failed to get response'}`,
              }
            : m
        )
      )
    } finally {
      setIsStreaming(false)
    }
  }, [input, sessionId, isStreaming, messages, attachments, currentFilePath, toast, model])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  const handleAttachCurrentFile = useCallback(() => {
    if (!currentFilePath) return

    // Check if already attached
    if (attachments.some((a) => a.path === currentFilePath)) {
      return
    }

    // Add attachment (content will be read when sending)
    setAttachments((prev) => [...prev, { path: currentFilePath }])
  }, [currentFilePath, attachments])

  const handleRemoveAttachment = useCallback((path: string) => {
    setAttachments((prev) => prev.filter((a) => a.path !== path))
  }, [])

  const handleCopyCode = useCallback((text: string, messageId: string) => {
    navigator.clipboard.writeText(text)
    setCopiedId(messageId)
    setTimeout(() => setCopiedId(null), 2000)
  }, [])

  const handleInsertAtCursor = useCallback(
    (text: string) => {
      onInsertAtCursor?.(text)
    },
    [onInsertAtCursor]
  )

  return (
    <div className="flex flex-col h-full bg-gray-900 border-l border-gray-700">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Code className="w-5 h-5 text-purple-400" />
            <span className="font-semibold text-white">AI Assistant</span>
          </div>
          {sessionId && (
            <div className="text-xs text-gray-400">
              Session: {sessionId.slice(0, 8)}...
            </div>
          )}
        </div>

        {/* Chat Settings */}
        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-xs text-gray-400">Chat Model</label>
          <select
            className="bg-gray-800 text-gray-100 text-xs rounded px-2 py-1 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            title="Choose AI chat model"
            disabled={isLoadingProviders}
         >
            {availableProviders.length > 0 ? (
              availableProviders
                .filter(p => p.capabilities.includes('chat'))
                .map(provider => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label} {provider.type === 'cloud' ? '(Cloud)' : ''}
                  </option>
                ))
            ) : (
              <option value="gpt-oss">gpt-oss</option>
            )}
          </select>
        </div>

        {/* Inline Suggestions Settings */}
        <div className="flex items-center gap-3 flex-wrap border-t border-gray-700 pt-3">
          <label className="text-xs text-gray-400">Suggestion Model</label>
          <select
            className="bg-gray-800 text-gray-100 text-xs rounded px-2 py-1 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={copilotModel}
            onChange={(e) => onCopilotModelChange?.(e.target.value)}
            title="Choose inline suggestion model"
            disabled={isLoadingProviders}
          >
            {availableProviders.length > 0 ? (
              availableProviders
                .filter(p => p.capabilities.includes('completion') || p.capabilities.includes('code'))
                .map(provider => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label}
                  </option>
                ))
            ) : (
              <option value="gpt-oss">GPT-OSS</option>
            )}
          </select>
          <button
            onClick={onCopilotToggle}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              copilotEnabled 
                ? 'bg-green-600 text-white hover:bg-green-700' 
                : 'bg-gray-600 text-gray-300 hover:bg-gray-500'
            }`}
            title={copilotEnabled ? 'Disable inline suggestions' : 'Enable inline suggestions'}
          >
            Suggestions {copilotEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 p-4 overflow-auto" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500">
            <Code className="w-12 h-12 mb-4 text-gray-600" />
            <p className="text-sm">Start a conversation with the AI</p>
            <p className="text-xs mt-2">Ask questions, request code, or get help</p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-lg p-3 ${
                    message.role === 'user'
                      ? 'bg-purple-600 text-white'
                      : 'bg-gray-800 text-gray-100'
                  }`}
                >
                  {message.role === 'assistant' ? (
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          code({ node, inline, className, children, ...props }) {
                            const codeString = String(children).replace(/\n$/, '')
                            return !inline ? (
                              <div className="relative group">
                                <pre className="bg-gray-950 rounded p-3 overflow-x-auto">
                                  <code className={className} {...props}>
                                    {children}
                                  </code>
                                </pre>
                                <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-6 px-2 text-xs"
                                    onClick={() =>
                                      handleCopyCode(codeString, message.id)
                                    }
                                  >
                                    {copiedId === message.id ? (
                                      <Check className="w-3 h-3" />
                                    ) : (
                                      <Copy className="w-3 h-3" />
                                    )}
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-6 px-2 text-xs"
                                    onClick={() => handleInsertAtCursor(codeString)}
                                  >
                                    Insert
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <code className={className} {...props}>
                                {children}
                              </code>
                            )
                          },
                        }}
                      >
                        {message.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  )}

                  {/* Action buttons for assistant messages */}
                </div>
              </div>
            ))}

            {isStreaming && messages[messages.length - 1]?.role === 'assistant' && (
              <div className="flex items-center gap-2 text-gray-400 text-sm">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>AI is thinking...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-700 p-4">
        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((attachment) => (
              <div
                key={attachment.path}
                className="flex items-center gap-1 bg-gray-800 rounded px-2 py-1 text-xs"
              >
                <FileCode className="w-3 h-3" />
                <span className="text-gray-300">
                  {attachment.path.split('/').pop()}
                </span>
                <button
                  onClick={() => handleRemoveAttachment(attachment.path)}
                  className="text-gray-500 hover:text-gray-300"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleAttachCurrentFile}
            disabled={!currentFilePath || !sessionId}
            className="flex-shrink-0"
            title={!currentFilePath ? 'No file open' : 'Attach current file'}
          >
            <Paperclip className="w-4 h-4" />
          </Button>
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              !sessionId
                ? 'Select a session to start chatting...'
                : 'Ask the AI assistant...'
            }
            disabled={!sessionId || isStreaming}
            className="flex-1 min-h-[60px] max-h-[200px] bg-gray-800 border-gray-700 text-white resize-none"
          />
          <Button
            size="sm"
            onClick={handleSend}
            disabled={!input.trim() || !sessionId || isStreaming}
            className="flex-shrink-0 bg-purple-600 hover:bg-purple-700"
          >
            {isStreaming ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>

        <div className="mt-2 text-xs text-gray-500">
          Press Enter to send, Shift+Enter for new line
        </div>
      </div>
    </div>
  )
}


