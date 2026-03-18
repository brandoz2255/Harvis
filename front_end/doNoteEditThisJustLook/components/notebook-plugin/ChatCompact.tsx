'use client'

import { useEffect, useState, useRef } from 'react'
import { Send, Loader2, ArrowLeft, MessageSquare, Trash2 } from 'lucide-react'
import { useNotebookStore } from '@/stores/notebookStore'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'

export default function ChatCompact() {
  const { messages, isChatting, isLoadingMessages, fetchChatHistory, sendMessage, clearChatHistory, currentNotebook } =
    useNotebookStore()
  const { selectedNotebookId, setActiveTab, selectNotebook } = useNotebookPluginStore()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selectedNotebookId) {
      fetchChatHistory(selectedNotebookId)
    }
  }, [selectedNotebookId, fetchChatHistory])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!selectedNotebookId) {
    return (
      <div className="p-6 text-center">
        <MessageSquare className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Select a notebook to chat</p>
        <button
          onClick={() => setActiveTab('notebooks')}
          className="mt-2 text-xs text-primary hover:underline"
        >
          Go to Notebooks
        </button>
      </div>
    )
  }

  const handleSend = async () => {
    if (!input.trim() || !selectedNotebookId || isChatting) return
    const msg = input.trim()
    setInput('')
    await sendMessage(selectedNotebookId, msg)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <button
          onClick={() => { selectNotebook(null); setActiveTab('notebooks') }}
          className="p-1 rounded text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-sm font-medium text-foreground truncate flex-1">
          {currentNotebook?.title || 'Chat'}
        </span>
        {messages.length > 0 && (
          <button
            onClick={() => selectedNotebookId && clearChatHistory(selectedNotebookId)}
            className="p-1 rounded text-muted-foreground/50 hover:text-destructive"
            title="Clear chat"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {isLoadingMessages ? (
          <div className="text-center text-sm text-muted-foreground py-4">Loading chat...</div>
        ) : messages.length === 0 ? (
          <div className="text-center py-8">
            <MessageSquare className="w-6 h-6 mx-auto mb-2 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground">Ask questions about your sources</p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] px-3 py-2 rounded-lg text-sm ${
                  msg.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-secondary text-foreground'
                }`}
              >
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-1.5 pt-1.5 border-t border-border/50">
                    <p className="text-[10px] text-muted-foreground">
                      {msg.citations.length} source{msg.citations.length !== 1 ? 's' : ''} cited
                    </p>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-border shrink-0">
        <div className="flex items-end gap-2 bg-secondary border border-border rounded-lg p-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Ask about your sources..."
            rows={1}
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground
                       resize-none focus:outline-none max-h-24"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isChatting}
            className="p-1.5 rounded-md bg-primary text-primary-foreground
                       hover:bg-primary/90 disabled:opacity-50 shrink-0"
          >
            {isChatting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
