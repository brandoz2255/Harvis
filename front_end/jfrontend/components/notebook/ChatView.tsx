'use client'

import { useState, useRef, useEffect } from 'react'
import { ChatMessage, NotebookSource, Citation } from '@/stores/notebookStore'
import {
  Send,
  Loader2,
  Copy,
  Check,
  RefreshCw,
  MoreVertical,
  Trash2,
  FileText,
  Download,
  Sparkles,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  BookOpen,
  ExternalLink,
  Cpu
} from 'lucide-react'

interface ChatViewProps {
  messages: ChatMessage[]
  sources: NotebookSource[]
  isLoading: boolean
  isChatting: boolean
  onSendMessage: (message: string, model: string) => void
  onClearHistory: () => void
}

const AI_MODELS = [
  { id: 'gpt-oss:latest', name: 'GPT-OSS', description: 'Fast general purpose' },
  { id: 'mistral', name: 'Mistral', description: 'Balanced performance' },
  { id: 'llama3.2:latest', name: 'Llama 3.2', description: 'Latest Meta model' },
  { id: 'deepseek-r1:8b', name: 'DeepSeek R1', description: 'Reasoning model' },
  { id: 'qwq:latest', name: 'QwQ', description: 'Advanced reasoning' },
]

const SUGGESTED_PROMPTS = [
  "What are the key points in my sources?",
  "Summarize the main topics covered",
  "What questions can I answer from these documents?",
  "Find contradictions or disagreements between sources",
  "Create a timeline of events mentioned",
  "List action items or recommendations",
]

export default function ChatView({
  messages,
  sources,
  isLoading,
  isChatting,
  onSendMessage,
  onClearHistory,
}: ChatViewProps) {
  const [input, setInput] = useState('')
  const [selectedModel, setSelectedModel] = useState('gpt-oss:latest')
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [showOptionsMenu, setShowOptionsMenu] = useState(false)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const readySources = sources.filter(s => s.status === 'ready')

  // Auto-scroll to bottom
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [messages, isChatting])

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 150) + 'px'
    }
  }, [input])

  const handleSend = () => {
    if (!input.trim() || isChatting || readySources.length === 0) return
    onSendMessage(input.trim(), selectedModel)
    setInput('')
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleCopyChat = () => {
    const chatText = messages.map(m => `${m.role === 'user' ? 'You' : 'AI'}: ${m.content}`).join('\n\n')
    navigator.clipboard.writeText(chatText)
    setShowOptionsMenu(false)
  }

  const handleExportMarkdown = () => {
    const chatMd = `# Chat Export\n\n` +
      messages.map(m => `**${m.role === 'user' ? 'You' : 'AI'}:**\n${m.content}`).join('\n\n---\n\n')
    const blob = new Blob([chatMd], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'chat-export.md'
    a.click()
    setShowOptionsMenu(false)
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[#0a0a0a]">
      {/* Chat Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">Chat</h2>

          {/* Model Selector */}
          <div className="relative">
            <button
              onClick={() => setShowModelMenu(!showModelMenu)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-[#111111] border border-gray-800 rounded-lg text-gray-300 hover:text-white transition-colors"
            >
              <span>{AI_MODELS.find(m => m.id === selectedModel)?.name || selectedModel}</span>
              <ChevronDown className="w-3 h-3" />
            </button>

            {showModelMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowModelMenu(false)} />
                <div className="absolute left-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[200px]">
                  {AI_MODELS.map(model => (
                    <button
                      key={model.id}
                      onClick={() => {
                        setSelectedModel(model.id)
                        setShowModelMenu(false)
                      }}
                      className={`w-full px-3 py-2 text-left hover:bg-gray-800 ${
                        selectedModel === model.id ? 'bg-blue-500/10' : ''
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className={`text-sm ${selectedModel === model.id ? 'text-blue-400' : 'text-white'}`}>
                          {model.name}
                        </span>
                        {selectedModel === model.id && (
                          <Check className="w-4 h-4 text-blue-400" />
                        )}
                      </div>
                      <p className="text-xs text-gray-500">{model.description}</p>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <span className="text-xs text-gray-500">
            {readySources.length} source{readySources.length !== 1 ? 's' : ''} available
          </span>
        </div>

        {/* Options Menu */}
        <div className="relative">
          <button
            onClick={() => setShowOptionsMenu(!showOptionsMenu)}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <MoreVertical className="w-5 h-5" />
          </button>

          {showOptionsMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowOptionsMenu(false)} />
              <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[180px]">
                <button
                  onClick={handleCopyChat}
                  className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
                >
                  <Copy className="w-4 h-4" />
                  Copy conversation
                </button>
                <button
                  onClick={handleExportMarkdown}
                  className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800 flex items-center gap-2"
                >
                  <Download className="w-4 h-4" />
                  Export as Markdown
                </button>
                <hr className="my-1 border-gray-800" />
                <button
                  onClick={() => {
                    onClearHistory()
                    setShowOptionsMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-gray-800 flex items-center gap-2"
                >
                  <Trash2 className="w-4 h-4" />
                  Clear history
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Messages Container */}
      <div ref={chatContainerRef} className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="w-16 h-16 mb-6 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center">
              <Sparkles className="w-8 h-8 text-blue-400" />
            </div>
            <h3 className="text-lg font-medium text-white mb-2">Start a conversation</h3>
            <p className="text-gray-500 mb-8 max-w-md">
              Ask questions about your sources and I'll help you find answers with citations.
            </p>

            {readySources.length > 0 ? (
              <div className="w-full max-w-lg space-y-2">
                <p className="text-xs text-gray-500 mb-3">Try asking:</p>
                <div className="grid grid-cols-2 gap-2">
                  {SUGGESTED_PROMPTS.slice(0, 4).map((prompt, i) => (
                    <button
                      key={i}
                      onClick={() => setInput(prompt)}
                      className="text-left px-4 py-3 text-sm text-gray-300 bg-[#111111] border border-gray-800 hover:border-gray-700 rounded-lg transition-colors"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-4 py-3">
                <p className="text-sm text-yellow-400">
                  Add sources to your notebook to start chatting
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {messages.map((message) => (
              <ChatBubble key={message.id} message={message} sources={sources} />
            ))}
            {isChatting && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="w-4 h-4 text-white" />
                </div>
                <div className="flex items-center gap-2 text-gray-400 py-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-sm">Thinking...</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="px-6 py-4 border-t border-gray-800">
        <div className="flex items-end gap-3 bg-[#111111] border border-gray-800 rounded-xl p-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              readySources.length === 0
                ? "Add sources to start chatting..."
                : "Ask a question about your sources..."
            }
            disabled={isChatting || readySources.length === 0}
            rows={1}
            className="flex-1 bg-transparent text-white placeholder-gray-500 focus:outline-none disabled:opacity-50 resize-none text-sm"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isChatting || readySources.length === 0}
            className="p-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex-shrink-0"
          >
            <Send className="w-4 h-4 text-white" />
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-2 text-center">
          AI responses are based on your sources and may not always be accurate.
        </p>
      </div>
    </div>
  )
}

// Chat Bubble Component
interface ChatBubbleProps {
  message: ChatMessage
  sources: NotebookSource[]
}

function ChatBubble({ message, sources }: ChatBubbleProps) {
  const [copied, setCopied] = useState(false)
  const [showReasoning, setShowReasoning] = useState(false)
  const isUser = message.role === 'user'

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const getSourceTitle = (citation: Citation) => {
    const source = sources.find(s => s.id === citation.source_id)
    return citation.source_title || source?.title || source?.original_filename || 'Unknown source'
  }

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
          isUser
            ? 'bg-gray-700'
            : 'bg-gradient-to-br from-blue-500 to-purple-500'
        }`}
      >
        {isUser ? (
          <span className="text-xs font-medium text-white">You</span>
        ) : (
          <Sparkles className="w-4 h-4 text-white" />
        )}
      </div>

      {/* Message Content */}
      <div className={`flex-1 max-w-[80%] ${isUser ? 'flex flex-col items-end' : ''}`}>
        <div
          className={`group relative rounded-2xl px-4 py-3 ${
            isUser
              ? 'bg-blue-600 text-white'
              : 'bg-[#111111] border border-gray-800 text-gray-100'
          }`}
        >
          {/* Message Text */}
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>

          {/* Copy Button */}
          <button
            onClick={handleCopy}
            className={`absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity ${
              isUser ? 'hover:bg-blue-500' : 'hover:bg-gray-800'
            }`}
          >
            {copied ? (
              <Check className="w-3 h-3 text-green-400" />
            ) : (
              <Copy className="w-3 h-3 text-gray-400" />
            )}
          </button>
        </div>

        {/* Reasoning Section (for AI messages) */}
        {!isUser && message.reasoning && (
          <div className="mt-2">
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300"
            >
              <Cpu className="w-3 h-3" />
              {showReasoning ? 'Hide' : 'Show'} reasoning
              {showReasoning ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {showReasoning && (
              <div className="mt-2 p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg text-sm text-gray-400">
                <p className="whitespace-pre-wrap">{message.reasoning}</p>
              </div>
            )}
          </div>
        )}

        {/* Citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.citations.map((citation, i) => (
              <CitationBadge key={i} citation={citation} title={getSourceTitle(citation)} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Citation Badge Component
interface CitationBadgeProps {
  citation: Citation
  title: string
}

function CitationBadge({ citation, title }: CitationBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false)

  return (
    <div className="relative">
      <button
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="flex items-center gap-1.5 px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300 hover:text-white hover:border-gray-600 transition-colors"
      >
        <FileText className="w-3 h-3" />
        <span className="truncate max-w-[120px]">{title}</span>
        {citation.page && <span className="text-gray-500">p.{citation.page}</span>}
      </button>

      {/* Tooltip with quote */}
      {showTooltip && citation.quote && (
        <div className="absolute bottom-full left-0 mb-2 w-64 p-3 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-10">
          <p className="text-xs text-gray-400 italic">&ldquo;{citation.quote}&rdquo;</p>
          <div className="absolute bottom-0 left-4 transform translate-y-full">
            <div className="w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-700" />
          </div>
        </div>
      )}
    </div>
  )
}
