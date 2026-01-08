'use client'

import { useEffect, useState, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useNotebookStore, NotebookSource, NotebookNote, ChatMessage } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import {
  ArrowLeft,
  Plus,
  Upload,
  Link,
  FileText,
  File,
  Globe,
  Trash2,
  Edit2,
  Pin,
  Send,
  Loader2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Clock,
  X,
  MessageSquare,
  StickyNote,
  Sparkles,
  Settings,
  Share2,
  MoreVertical,
  Copy,
  Headphones,
  Video,
  Map,
  ClipboardList,
  BookOpen,
  HelpCircle,
  Search,
  Youtube,
  Clipboard,
  Mic,
  Wand2
} from 'lucide-react'

// New Open Notebook integration components
import TransformPanel from '@/components/notebook/TransformPanel'
import PodcastGenerator from '@/components/notebook/PodcastGenerator'

// Source type icons
const sourceTypeIcons: Record<string, React.ReactNode> = {
  pdf: <File className="w-4 h-4 text-red-400" />,
  text: <FileText className="w-4 h-4 text-blue-400" />,
  url: <Globe className="w-4 h-4 text-green-400" />,
  markdown: <FileText className="w-4 h-4 text-purple-400" />,
  doc: <File className="w-4 h-4 text-blue-400" />,
  transcript: <FileText className="w-4 h-4 text-yellow-400" />,
  audio: <Headphones className="w-4 h-4 text-orange-400" />,
  youtube: <Youtube className="w-4 h-4 text-red-500" />,
  image: <FileText className="w-4 h-4 text-pink-400" />,
}

// Status indicators
const statusIndicators: Record<string, React.ReactNode> = {
  pending: <Clock className="w-3 h-3 text-gray-400" />,
  processing: <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />,
  ready: <CheckCircle className="w-3 h-3 text-green-400" />,
  error: <AlertCircle className="w-3 h-3 text-red-400" />,
}

export default function NotebookWorkspacePage() {
  const router = useRouter()
  const params = useParams()
  const notebookId = params.id as string
  const { user, isLoading: authLoading } = useUser()

  const {
    currentNotebook,
    sources,
    notes,
    messages,
    isLoadingNotebooks,
    isLoadingSources,
    isLoadingNotes,
    isLoadingMessages,
    isChatting,
    error,
    selectNotebook,
    updateNotebook,
    uploadSource,
    addUrlSource,
    addTextSource,
    deleteSource,
    refreshSourceStatus,
    createNote,
    updateNote,
    deleteNote,
    sendMessage,
    clearChatHistory,
    setError,
  } = useNotebookStore()

  // Local state
  const [showSourceModal, setShowSourceModal] = useState(false)
  const [sourceType, setSourceType] = useState<'upload' | 'url' | 'text' | 'youtube'>('upload')
  const [urlInput, setUrlInput] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  
  // Open Notebook integration state
  const [showTransformPanel, setShowTransformPanel] = useState(false)
  const [transformSource, setTransformSource] = useState<NotebookSource | null>(null)
  const [showPodcastGenerator, setShowPodcastGenerator] = useState(false)
  const [noteContent, setNoteContent] = useState('')
  const [editingNote, setEditingNote] = useState<NotebookNote | null>(null)
  const [selectedModel, setSelectedModel] = useState('gpt-oss:latest')
  const [showChatMenu, setShowChatMenu] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleInput, setTitleInput] = useState('')
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())

  const chatContainerRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const chatMenuRef = useRef<HTMLDivElement>(null)

  // Close chat menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (chatMenuRef.current && !chatMenuRef.current.contains(event.target as Node)) {
        setShowChatMenu(false)
      }
    }
    
    if (showChatMenu) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showChatMenu])

  // Load notebook on mount
  useEffect(() => {
    if (!authLoading && user && notebookId) {
      selectNotebook(notebookId)
    }
  }, [authLoading, user, notebookId, selectNotebook])

  // Set title input when notebook loads
  useEffect(() => {
    if (currentNotebook) {
      setTitleInput(currentNotebook.title)
    }
  }, [currentNotebook])

  // Auto-scroll chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [messages])

  // Poll for source status updates
  useEffect(() => {
    const processingSourceIds = sources
      .filter(s => s.status === 'processing' || s.status === 'pending')
      .map(s => s.id)

    if (processingSourceIds.length === 0 || !notebookId) return

    const interval = setInterval(() => {
      processingSourceIds.forEach(sourceId => {
        refreshSourceStatus(notebookId, sourceId)
      })
    }, 3000)

    return () => clearInterval(interval)
  }, [sources, notebookId, refreshSourceStatus])

  // Handlers
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || !notebookId) return

    for (const file of Array.from(files)) {
      await uploadSource(notebookId, file)
    }

    setShowSourceModal(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleAddUrl = async () => {
    if (!urlInput.trim() || !notebookId) return
    await addUrlSource(notebookId, urlInput.trim())
    setUrlInput('')
    setShowSourceModal(false)
  }

  const handleAddYouTube = async () => {
    if (!youtubeUrl.trim() || !notebookId) return
    try {
      const response = await fetch(`/api/notebooks/${notebookId}/sources/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          url: youtubeUrl.trim(),
          title: null
        })
      })
      if (response.ok) {
        setYoutubeUrl('')
        setShowSourceModal(false)
        // Refresh sources
        selectNotebook(notebookId)
      }
    } catch (err) {
      console.error('Failed to add YouTube source:', err)
    }
  }

  const openTransformPanel = (source: NotebookSource) => {
    setTransformSource(source)
    setShowTransformPanel(true)
  }

  const handleAddText = async () => {
    if (!textTitle.trim() || !textContent.trim() || !notebookId) return
    await addTextSource(notebookId, textTitle.trim(), textContent.trim())
    setTextTitle('')
    setTextContent('')
    setShowSourceModal(false)
  }

  const handleSendMessage = async () => {
    if (!chatInput.trim() || !notebookId || isChatting) return
    const message = chatInput
    setChatInput('')
    await sendMessage(notebookId, message, selectedModel)
  }

  const handleCreateNote = async () => {
    if (!noteContent.trim() || !notebookId) return
    await createNote(notebookId, noteContent.trim())
    setNoteContent('')
  }

  const handleSaveNote = async () => {
    if (!editingNote || !noteContent.trim() || !notebookId) return
    await updateNote(notebookId, editingNote.id, noteContent.trim())
    setEditingNote(null)
    setNoteContent('')
  }

  const handleTitleSave = async () => {
    if (!titleInput.trim() || !notebookId) return
    await updateNotebook(notebookId, titleInput.trim())
    setEditingTitle(false)
  }

  const toggleSourceSelection = (sourceId: string) => {
    const newSelected = new Set(selectedSources)
    if (newSelected.has(sourceId)) {
      newSelected.delete(sourceId)
    } else {
      newSelected.add(sourceId)
    }
    setSelectedSources(newSelected)
  }

  if (authLoading || isLoadingNotebooks) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  if (!user) {
    router.push('/login')
    return null
  }

  if (!currentNotebook) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
        <AlertCircle className="w-16 h-16 text-gray-500 mb-4" />
        <h2 className="text-2xl font-bold text-white mb-2">Notebook not found</h2>
        <button
          onClick={() => router.push('/notebooks')}
          className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Back to Notebooks
        </button>
      </div>
    )
  }

  const readySources = sources.filter(s => s.status === 'ready').length

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col bg-[#1a1a1a] -mx-4 -my-8 px-0">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-[#1a1a1a]">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/notebooks')}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          {editingTitle ? (
            <input
              type="text"
              value={titleInput}
              onChange={(e) => setTitleInput(e.target.value)}
              onBlur={handleTitleSave}
              onKeyDown={(e) => e.key === 'Enter' && handleTitleSave()}
              className="text-lg font-medium text-white bg-transparent border-b border-blue-500 focus:outline-none"
              autoFocus
            />
          ) : (
            <h1
              className="text-lg font-medium text-white cursor-pointer hover:text-gray-300"
              onClick={() => setEditingTitle(true)}
            >
              {currentNotebook.title}
            </h1>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowPodcastGenerator(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800 rounded-lg transition-colors"
            title="Generate Podcast"
          >
            <Mic className="w-4 h-4 text-orange-400" />
            Podcast
          </button>
          <button className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800 rounded-lg transition-colors">
            <Share2 className="w-4 h-4" />
            Share
          </button>
          <button className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors">
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Main Content - 3 Column Layout */}
      <div className="flex-1 flex min-h-0">
        {/* Left Panel - Sources */}
        <div className="w-80 flex-shrink-0 border-r border-gray-800 flex flex-col bg-[#1a1a1a]">
          <div className="p-4 border-b border-gray-800">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">Sources</span>
              <button className="p-1 text-gray-400 hover:text-white">
                <MoreVertical className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Add Sources Button */}
          <div className="p-3">
            <button
              onClick={() => setShowSourceModal(true)}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 rounded-lg transition-colors border border-gray-700 border-dashed"
            >
              <Plus className="w-4 h-4" />
              Add sources
            </button>
          </div>

          {/* Search Sources */}
          <div className="px-3 pb-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                type="text"
                placeholder="Search the web for new sources"
                className="w-full pl-9 pr-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Source List */}
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            {isLoadingSources ? (
              <div className="flex justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-blue-400" />
              </div>
            ) : sources.length === 0 ? (
              <div className="text-center py-8 px-4">
                <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-gray-800 flex items-center justify-center">
                  <FileText className="w-6 h-6 text-gray-500" />
                </div>
                <p className="text-sm text-gray-400 mb-1">Saved sources will appear here</p>
                <p className="text-xs text-gray-500">
                  Click Add source above to add PDFs, websites, text, videos, or import a file directly from Drive.
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                {sources.map((source) => (
                  <div
                    key={source.id}
                    className={`group flex items-start gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                      selectedSources.has(source.id) ? 'bg-blue-600/20 border border-blue-500/50' : 'hover:bg-gray-800'
                    }`}
                    onClick={() => toggleSourceSelection(source.id)}
                  >
                    <input
                      type="checkbox"
                      checked={selectedSources.has(source.id)}
                      onChange={() => toggleSourceSelection(source.id)}
                      className="mt-1 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        {sourceTypeIcons[source.type] || <FileText className="w-4 h-4 text-gray-400" />}
                        <span className="text-sm text-white truncate">
                          {source.title || source.original_filename || 'Untitled'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        {statusIndicators[source.status]}
                        <span className="text-xs text-gray-500">
                          {source.status === 'ready'
                            ? `${source.chunk_count} chunks`
                            : source.status === 'processing'
                            ? 'Processing...'
                            : source.status}
                        </span>
                      </div>
                      {source.error_message && (
                        <p className="text-xs text-red-400 mt-1 truncate">
                          {source.error_message}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                      {source.status === 'ready' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            openTransformPanel(source)
                          }}
                          className="p-1 text-gray-500 hover:text-purple-400"
                          title="Transform with AI"
                        >
                          <Wand2 className="w-3 h-3" />
                        </button>
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteSource(notebookId, source.id)
                        }}
                        className="p-1 text-gray-500 hover:text-red-400"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Center Panel - Chat */}
        <div className="flex-1 flex flex-col min-w-0 bg-[#1a1a1a]">
          {/* Chat Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white">Chat</span>
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                {selectedModel}
              </span>
              <button className="p-1 text-gray-400 hover:text-white" title="Chat help">
                <HelpCircle className="w-4 h-4" />
              </button>
            </div>
            <div className="relative" ref={chatMenuRef}>
              <button 
                onClick={() => setShowChatMenu(!showChatMenu)}
                className="p-1 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
              
              {/* Chat Options Dropdown */}
              {showChatMenu && (
                <div className="absolute right-0 top-full mt-1 w-72 bg-[#252525] border border-gray-700 rounded-lg shadow-xl z-50">
                  {/* Model Selection */}
                  <div className="p-3 border-b border-gray-700">
                    <label className="text-xs text-gray-400 uppercase tracking-wider font-medium">
                      AI Model
                    </label>
                    <div className="mt-2 space-y-1">
                      {[
                        { id: 'gpt-oss:latest', name: 'GPT-OSS', desc: '⚡ Fast - General purpose', fast: true },
                        { id: 'codellama:7b', name: 'CodeLlama 7B', desc: 'Best for code & technical' },
                        { id: 'deepseek-coder:6.7b', name: 'DeepSeek Coder', desc: 'Advanced coding assistant' },
                      ].map((model) => (
                        <button
                          key={model.id}
                          onClick={() => {
                            setSelectedModel(model.id)
                            setShowChatMenu(false)
                          }}
                          className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                            selectedModel === model.id
                              ? 'bg-blue-600/20 border border-blue-500/50'
                              : 'hover:bg-gray-700'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-white">{model.name}</span>
                            {selectedModel === model.id && (
                              <CheckCircle className="w-4 h-4 text-blue-400" />
                            )}
                          </div>
                          <p className="text-xs text-gray-500 mt-0.5">{model.desc}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                  
                  {/* Chat Options */}
                  <div className="p-2">
                    <button
                      onClick={() => {
                        clearChatHistory(notebookId)
                        setShowChatMenu(false)
                      }}
                      className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-4 h-4 text-gray-400" />
                      Clear chat history
                    </button>
                    <button
                      onClick={() => {
                        // Copy chat to clipboard
                        const chatText = messages.map(m => `${m.role}: ${m.content}`).join('\n\n')
                        navigator.clipboard.writeText(chatText)
                        setShowChatMenu(false)
                      }}
                      className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Copy className="w-4 h-4 text-gray-400" />
                      Copy conversation
                    </button>
                    <button
                      onClick={() => {
                        // Export chat as markdown
                        const chatMd = `# Chat Export - ${currentNotebook?.title || 'Notebook'}\n\n` +
                          messages.map(m => `**${m.role === 'user' ? 'You' : 'AI'}:**\n${m.content}`).join('\n\n---\n\n')
                        const blob = new Blob([chatMd], { type: 'text/markdown' })
                        const url = URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = `chat-${notebookId}.md`
                        a.click()
                        setShowChatMenu(false)
                      }}
                      className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <FileText className="w-4 h-4 text-gray-400" />
                      Export as Markdown
                    </button>
                  </div>
                  
                  {/* Info Section */}
                  <div className="p-3 border-t border-gray-700 bg-gray-800/50">
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <Sparkles className="w-3 h-3" />
                      <span>Responses are AI-generated based on your sources</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Chat Messages */}
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-4"
          >
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-8">
                <p className="text-gray-400 text-sm mb-8">
                  Upload a source to get started
                </p>

                {readySources > 0 && (
                  <div className="w-full max-w-md space-y-3">
                    <p className="text-xs text-gray-500 mb-4">Try asking:</p>
                    {[
                      "What are the key points in my sources?",
                      "Summarize the main topics covered",
                      "What questions can I answer from these documents?"
                    ].map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => setChatInput(suggestion)}
                        className="w-full text-left px-4 py-3 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                {messages.map((msg) => (
                  <ChatBubble key={msg.id} message={msg} />
                ))}
                {isChatting && (
                  <div className="flex items-center gap-2 text-gray-400 px-4">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">Thinking...</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Chat Input */}
          <div className="p-4 border-t border-gray-800">
            <div className="flex items-center gap-2 bg-gray-800 rounded-xl px-4 py-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                placeholder={
                  readySources === 0
                    ? 'Add sources to start chatting...'
                    : 'Start typing...'
                }
                disabled={isChatting || readySources === 0}
                className="flex-1 bg-transparent text-white placeholder-gray-500 focus:outline-none disabled:opacity-50 text-sm"
              />
              <span className="text-xs text-gray-500">{sources.length} sources</span>
              <button
                onClick={handleSendMessage}
                disabled={!chatInput.trim() || isChatting || readySources === 0}
                className="p-2 text-gray-400 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-2 text-center">
              NotebookLM can be inaccurate; please double-check its responses.
            </p>
          </div>
        </div>

        {/* Right Panel - Studio */}
        <div className="w-80 flex-shrink-0 border-l border-gray-800 flex flex-col bg-[#1a1a1a]">
          <div className="p-4 border-b border-gray-800">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">Studio</span>
              <button className="p-1 text-gray-400 hover:text-white">
                <MoreVertical className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Studio Options */}
          <div className="p-4 grid grid-cols-3 gap-3">
            {[
              { icon: Headphones, label: 'Audio Overview' },
              { icon: Video, label: 'Video Overview' },
              { icon: Map, label: 'Mind Map' },
              { icon: ClipboardList, label: 'Reports' },
              { icon: BookOpen, label: 'Flashcards' },
              { icon: HelpCircle, label: 'Quiz' },
            ].map(({ icon: Icon, label }) => (
              <button
                key={label}
                className="flex flex-col items-center gap-2 p-3 rounded-lg hover:bg-gray-800 transition-colors"
              >
                <Icon className="w-5 h-5 text-gray-400" />
                <span className="text-xs text-gray-400">{label}</span>
              </button>
            ))}
          </div>

          {/* Notes Section */}
          <div className="flex-1 flex flex-col border-t border-gray-800">
            <div className="p-4 border-b border-gray-800">
              <span className="text-sm text-gray-400">Notes</span>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {notes.length === 0 ? (
                <div className="text-center py-8">
                  <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-gray-800 flex items-center justify-center">
                    <StickyNote className="w-6 h-6 text-gray-500" />
                  </div>
                  <p className="text-sm text-gray-400 mb-1">Notes will be saved here.</p>
                  <p className="text-xs text-gray-500">
                    Click the button below to add a note.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {notes.map((note) => (
                    <NoteCard
                      key={note.id}
                      note={note}
                      onEdit={() => {
                        setEditingNote(note)
                        setNoteContent(note.content)
                      }}
                      onDelete={() => deleteNote(notebookId, note.id)}
                      onTogglePin={() => updateNote(notebookId, note.id, undefined, undefined, !note.is_pinned)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Add Note Button */}
            <div className="p-4 border-t border-gray-800">
              <button
                onClick={() => {
                  const content = prompt('Enter note content:')
                  if (content && notebookId) {
                    createNote(notebookId, content)
                  }
                }}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors text-sm"
              >
                <Plus className="w-4 h-4" />
                Add note
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Add Source Modal */}
      {showSourceModal && (
        <AddSourcesModal
          isOpen={showSourceModal}
          onClose={() => setShowSourceModal(false)}
          notebookId={notebookId}
          sourcesCount={sources.length}
          onFileUpload={handleFileUpload}
          onAddUrl={async (url: string) => {
            await addUrlSource(notebookId, url)
            setShowSourceModal(false)
          }}
          onAddText={async (title: string, content: string) => {
            await addTextSource(notebookId, title, content)
            setShowSourceModal(false)
          }}
          onAddYouTube={async (url: string) => {
            try {
              const response = await fetch(`/api/notebooks/${notebookId}/sources/youtube`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ url, title: null })
              })
              if (response.ok) {
                selectNotebook(notebookId)
              }
            } catch (err) {
              console.error('Failed to add YouTube source:', err)
            }
            setShowSourceModal(false)
          }}
          fileInputRef={fileInputRef}
        />
      )}

      {/* Transform Panel */}
      {showTransformPanel && transformSource && (
        <TransformPanel
          notebookId={notebookId}
          sourceId={transformSource.id}
          sourceTitle={transformSource.title || transformSource.original_filename || 'Untitled'}
          onClose={() => {
            setShowTransformPanel(false)
            setTransformSource(null)
          }}
        />
      )}

      {/* Podcast Generator */}
      {showPodcastGenerator && currentNotebook && (
        <PodcastGenerator
          notebookId={notebookId}
          notebookTitle={currentNotebook.title}
          onClose={() => setShowPodcastGenerator(false)}
        />
      )}

      {/* Error Toast */}
      {error && (
        <div className="fixed bottom-4 right-4 p-4 bg-red-900/90 border border-red-700 rounded-lg text-red-200 flex items-center gap-3 z-50">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="p-1 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

// Chat Bubble Component
function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-gray-800 text-gray-100'
        }`}
      >
        <p className="whitespace-pre-wrap text-sm">{message.content}</p>

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-600/50">
            <div className="flex flex-wrap gap-2">
              {message.citations.map((citation, i) => (
                <span
                  key={i}
                  className="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300"
                  title={citation.quote}
                >
                  {citation.source_title || `Source ${i + 1}`}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Note Card Component
function NoteCard({
  note,
  onEdit,
  onDelete,
  onTogglePin,
}: {
  note: NotebookNote
  onEdit: () => void
  onDelete: () => void
  onTogglePin: () => void
}) {
  return (
    <div
      className={`group p-3 rounded-lg transition-colors ${
        note.is_pinned
          ? 'bg-yellow-900/20 border border-yellow-700/50'
          : 'bg-gray-800 hover:bg-gray-700'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-gray-300 line-clamp-3">{note.content}</p>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={onTogglePin}
            className={`p-1 rounded transition-colors ${
              note.is_pinned ? 'text-yellow-400' : 'text-gray-400 hover:text-white'
            }`}
          >
            <Pin className="w-3 h-3" />
          </button>
          <button
            onClick={onDelete}
            className="p-1 text-gray-400 hover:text-red-400 transition-colors"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-500 mt-2">
        {new Date(note.created_at).toLocaleDateString()}
      </p>
    </div>
  )
}

// Add Sources Modal Component - NotebookLM Style
interface AddSourcesModalProps {
  isOpen: boolean
  onClose: () => void
  notebookId: string
  sourcesCount: number
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void
  onAddUrl: (url: string) => Promise<void>
  onAddText: (title: string, content: string) => Promise<void>
  onAddYouTube?: (url: string) => Promise<void>
  fileInputRef: React.RefObject<HTMLInputElement | null>
}

function AddSourcesModal({
  isOpen,
  onClose,
  notebookId,
  sourcesCount,
  onFileUpload,
  onAddUrl,
  onAddText,
  onAddYouTube,
  fileInputRef,
}: AddSourcesModalProps) {
  const [showUrlInput, setShowUrlInput] = useState(false)
  const [showTextInput, setShowTextInput] = useState(false)
  const [showYouTubeInput, setShowYouTubeInput] = useState(false)
  const [urlValue, setUrlValue] = useState('')
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const [isDragging, setIsDragging] = useState(false)

  if (!isOpen) return null

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = e.dataTransfer.files
    if (files.length > 0 && fileInputRef.current) {
      const dataTransfer = new DataTransfer()
      Array.from(files).forEach(file => dataTransfer.items.add(file))
      fileInputRef.current.files = dataTransfer.files
      const event = { target: fileInputRef.current } as React.ChangeEvent<HTMLInputElement>
      onFileUpload(event)
    }
  }

  const handleUrlSubmit = async () => {
    if (urlValue.trim()) {
      await onAddUrl(urlValue.trim())
      setUrlValue('')
      setShowUrlInput(false)
    }
  }

  const handleTextSubmit = async () => {
    if (textTitle.trim() && textContent.trim()) {
      await onAddText(textTitle.trim(), textContent.trim())
      setTextTitle('')
      setTextContent('')
      setShowTextInput(false)
    }
  }

  const handleYouTubeSubmit = async () => {
    if (youtubeUrl.trim() && onAddYouTube) {
      await onAddYouTube(youtubeUrl.trim())
      setYoutubeUrl('')
      setShowYouTubeInput(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-[#1e1e1e] border border-gray-700 rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-400 via-pink-500 to-purple-600 flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">NotebookLM</h2>
              <h3 className="text-base text-gray-300">Add sources</h3>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-2 px-4 py-2 text-sm text-white bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors">
              <Sparkles className="w-4 h-4" />
              Discover sources
            </button>
            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(85vh-80px)]">
          <p className="text-gray-300 mb-1">
            Sources let NotebookLM base its responses on the information that matters most to you.
          </p>
          <p className="text-sm text-gray-500 mb-6">
            (Examples: marketing plans, course reading, research notes, meeting transcripts, sales documents, etc.)
          </p>

          {/* Upload Area */}
          <div
            className={`border-2 border-dashed rounded-xl p-10 mb-6 text-center transition-all cursor-pointer ${
              isDragging 
                ? 'border-blue-500 bg-blue-500/10' 
                : 'border-gray-600 hover:border-gray-500 hover:bg-gray-800/30'
            }`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={onFileUpload}
              accept=".pdf,.txt,.md,.doc,.docx,.mp3,.wav,.png,.jpg,.jpeg,.gif,.webp"
              multiple
              className="hidden"
            />
            <div className="w-14 h-14 mx-auto mb-4 rounded-full bg-gray-700/50 flex items-center justify-center">
              <Upload className="w-7 h-7 text-blue-400" />
            </div>
            <p className="text-white font-medium mb-2">Upload sources</p>
            <p className="text-gray-400 text-sm">
              Drag & drop or <span className="text-blue-400 hover:underline cursor-pointer">choose file</span> to upload
            </p>
            <p className="text-gray-500 text-xs mt-4 max-w-lg mx-auto">
              Supported file types: PDF, .txt, Markdown, Audio (e.g. mp3), .docx, .avif, .bmp, .gif, .ico, .jp2, .webp, .tif, .tiff, .heic, .heif, .jpeg, .jpg, .jpe
            </p>
          </div>

          {/* Source Type Options */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            {/* Google Workspace */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5">
                  <svg viewBox="0 0 24 24" className="w-5 h-5">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                </div>
                <span className="text-sm text-white">Google Workspace</span>
              </div>
              <button className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors">
                <FileText className="w-3 h-3" />
                Google Drive
              </button>
            </div>

            {/* Link */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <Link className="w-5 h-5 text-gray-400" />
                <span className="text-sm text-white">Link</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => setShowUrlInput(true)}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  <Globe className="w-3 h-3" />
                  Website
                </button>
                <button
                  onClick={() => setShowYouTubeInput(true)}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  <Youtube className="w-3 h-3 text-red-500" />
                  YouTube
                </button>
              </div>
            </div>

            {/* Paste text */}
            <div className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center gap-2 mb-3">
                <Clipboard className="w-5 h-5 text-gray-400" />
                <span className="text-sm text-white">Paste text</span>
              </div>
              <button
                onClick={() => setShowTextInput(true)}
                className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                <Copy className="w-3 h-3" />
                Copied text
              </button>
            </div>
          </div>

          {/* URL Input Section */}
          {showUrlInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium">Add website URL</span>
                <button
                  onClick={() => {
                    setShowUrlInput(false)
                    setUrlValue('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={urlValue}
                  onChange={(e) => setUrlValue(e.target.value)}
                  placeholder="https://example.com/article"
                  className="flex-1 px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleUrlSubmit()}
                />
                <button
                  onClick={handleUrlSubmit}
                  disabled={!urlValue.trim()}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {/* YouTube Input Section */}
          {showYouTubeInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium flex items-center gap-2">
                  <Youtube className="w-4 h-4 text-red-500" />
                  Add YouTube video
                </span>
                <button
                  onClick={() => {
                    setShowYouTubeInput(false)
                    setYoutubeUrl('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-gray-400 mb-3">
                Paste a YouTube URL and we'll extract the transcript automatically.
              </p>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={youtubeUrl}
                  onChange={(e) => setYoutubeUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="flex-1 px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-red-500 text-sm"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleYouTubeSubmit()}
                />
                <button
                  onClick={handleYouTubeSubmit}
                  disabled={!youtubeUrl.trim()}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          {/* Text Input Section */}
          {showTextInput && (
            <div className="mb-6 p-4 bg-gray-800/50 rounded-xl border border-gray-700/50">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white font-medium">Paste text content</span>
                <button
                  onClick={() => {
                    setShowTextInput(false)
                    setTextTitle('')
                    setTextContent('')
                  }}
                  className="p-1 text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-3">
                <input
                  type="text"
                  value={textTitle}
                  onChange={(e) => setTextTitle(e.target.value)}
                  placeholder="Title for this source"
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  autoFocus
                />
                <textarea
                  value={textContent}
                  onChange={(e) => setTextContent(e.target.value)}
                  placeholder="Paste your text content here..."
                  rows={6}
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm resize-none"
                />
                <div className="flex justify-end">
                  <button
                    onClick={handleTextSubmit}
                    disabled={!textTitle.trim() || !textContent.trim()}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  >
                    Add Source
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Source Limit */}
          <div className="flex items-center gap-3">
            <FileText className="w-4 h-4 text-gray-500" />
            <span className="text-sm text-gray-400">Source limit</span>
            <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all"
                style={{ width: `${Math.min((sourcesCount / 50) * 100, 100)}%` }}
              />
            </div>
            <span className="text-sm text-gray-400">{sourcesCount} / 50</span>
          </div>
        </div>
      </div>
    </div>
  )
}
