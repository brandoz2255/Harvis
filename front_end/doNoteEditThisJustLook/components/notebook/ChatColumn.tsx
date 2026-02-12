"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChatMessage, NotebookNote } from "@/stores/notebookStore"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { MessageSquare, Send, Loader2, ChevronDown, Plus } from "lucide-react"
import ReactMarkdown from "react-markdown"
import { ContextMode } from "./types"

interface ChatColumnProps {
  messages: ChatMessage[]
  isLoading: boolean
  isChatting: boolean
  onSendMessage: (message: string) => Promise<void>
  onClearHistory: () => Promise<void>
  onSaveAsNote: (content: string) => Promise<void>
  sourcesCount: number
  notesCount: number
  contextSelections: {
    sources: Record<string, ContextMode>
    notes: Record<string, ContextMode>
  }
}

export default function ChatColumn({
  messages,
  isLoading,
  isChatting,
  onSendMessage,
  onClearHistory,
  onSaveAsNote,
  sourcesCount,
  notesCount,
  contextSelections,
}: ChatColumnProps) {
  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const contextStats = useMemo(() => {
    const includedSources = Object.values(contextSelections.sources).filter(
      (mode) => mode !== "off"
    ).length
    const includedNotes = Object.values(contextSelections.notes).filter(
      (mode) => mode !== "off"
    ).length
    const tokensApprox = Math.round((includedSources + includedNotes) * 1200)
    return { includedSources, includedNotes, tokensApprox }
  }, [contextSelections])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim()) return
    const value = input.trim()
    setInput("")
    await onSendMessage(value)
  }

  return (
    <div className="flex flex-col min-h-0 border border-gray-800 rounded-lg overflow-hidden bg-[#0a0a0a]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="text-sm font-semibold text-white">Chat</div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <button
            className="flex items-center gap-1 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700"
            onClick={onClearHistory}
          >
            <Plus className="h-3 w-3" />
            New Session
          </button>
          <div className="flex items-center gap-1 px-2 py-1 rounded bg-gray-800">
            Session: Default <ChevronDown className="h-3 w-3" />
          </div>
        </div>
      </div>

      <div className="px-4 py-2 border-b border-gray-800 text-xs text-gray-400">
        Context: {contextStats.includedSources} sources, {contextStats.includedNotes} notes (
        ~{contextStats.tokensApprox.toLocaleString()} tokens)
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {isLoading ? (
          <div className="text-sm text-gray-400">Loading chat…</div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center text-gray-400 py-8">
            <MessageSquare className="h-8 w-8 mb-3" />
            <div className="text-sm">Ask about your sources and notes.</div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`rounded-lg p-3 ${
                message.role === "user" ? "bg-blue-600 text-white ml-auto" : "bg-gray-900 text-gray-100"
              } max-w-[85%]`}
            >
              {message.role === "assistant" ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <div className="text-sm whitespace-pre-wrap">{message.content}</div>
              )}

              {message.role === "assistant" && (
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-xs text-blue-300 hover:text-blue-200"
                    onClick={() => onSaveAsNote(message.content)}
                  >
                    Save as Note
                  </Button>
                </div>
              )}

              {message.citations && message.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {message.citations.map((citation, idx) => (
                    <span
                      key={`${message.id}-cite-${idx}`}
                      className="text-[10px] px-2 py-0.5 rounded bg-gray-800 text-gray-300"
                    >
                      [{idx + 1}] {citation.source_title || "Source"}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
        {isChatting && (
          <div className="text-xs text-gray-400 flex items-center gap-2">
            <Loader2 className="h-3 w-3 animate-spin" /> Generating response…
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-gray-800">
        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your message..."
            className="min-h-[56px] bg-gray-900 border-gray-800 text-white placeholder-gray-500"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim() || isChatting}
            className="bg-blue-600 hover:bg-blue-700 text-white"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}








