'use client'

import { useEffect, useState, useRef } from 'react'
import { useNotebookStore, type NotebookSource, type NotebookNote, type ChatMessage, type Citation } from '@/stores/notebookStore'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'
import OpenNotebookAPI from '@/lib/openNotebookApi'
import AddSourceModal from './AddSourceModal'
import SourceDetailViewer from './SourceDetailViewer'
import PodcastStudio from './PodcastStudio'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowLeft, Plus, FileText, MessageSquare, StickyNote, Mic,
  Send, Loader2, Trash2, Link, Type, MoreVertical,
  AlertCircle, ChevronDown, ChevronUp, Maximize2, Minimize2,
  Sparkles, Copy, Check, Cpu, Download, Globe, Youtube, ExternalLink
} from 'lucide-react'

type MobileTab = 'sources' | 'notes' | 'chat' | 'podcast'

const SUGGESTED_PROMPTS = [
  "What are the key points in my sources?",
  "Summarize the main topics covered",
  "Find contradictions between sources",
  "List action items or recommendations",
]

export default function NotebookWorkspace() {
  const {
    currentNotebook, sources, notes, messages,
    isLoadingSources, isLoadingNotes, isLoadingMessages, isChatting,
    selectedModel, error,
    selectNotebook: loadNotebook, updateNotebook,
    uploadSource, addUrlSource, addTextSource, addYouTubeSource, deleteSource,
    refreshSourceStatus, sendMessage, clearChatHistory, setSelectedModel,
    createNote, updateNote, deleteNote, setError,
  } = useNotebookStore()

  const {
    selectedNotebookId, selectNotebook, setActiveTab, viewMode, toggleViewMode,
  } = useNotebookPluginStore()

  const [mobileTab, setMobileTab] = useState<MobileTab>('chat')
  const [showAddSource, setShowAddSource] = useState(false)
  const [selectedSource, setSelectedSource] = useState<NotebookSource | null>(null)
  const [highlightText, setHighlightText] = useState<string | undefined>(undefined)
  const [chatInput, setChatInput] = useState('')
  const [noteInput, setNoteInput] = useState('')
  const [noteTitle, setNoteTitle] = useState('')
  const [showNoteForm, setShowNoteForm] = useState(false)
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [showOptionsMenu, setShowOptionsMenu] = useState(false)
  const [models, setModels] = useState<Array<{ name: string }>>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const isFullMode = viewMode === 'full'

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + 'px'
    }
  }, [chatInput])

  useEffect(() => {
    if (!selectedNotebookId) return
    const processingIds = sources
      .filter(s => s.status === 'processing' || s.status === 'pending')
      .map(s => s.id)
    if (processingIds.length === 0) return

    const cancellers: (() => void)[] = []
    processingIds.forEach(id => {
      const cancel = OpenNotebookAPI.sources.streamStatus(selectedNotebookId, id, (data) => {
        if (data.error) return
        refreshSourceStatus(selectedNotebookId, id)
      })
      cancellers.push(cancel)
    })
    return () => cancellers.forEach(c => c())
  }, [sources, selectedNotebookId, refreshSourceStatus])

  useEffect(() => {
    OpenNotebookAPI.models.list().then(m => setModels(m)).catch(() => {})
  }, [])

  const handleBack = () => {
    selectNotebook(null)
    setActiveTab('notebooks')
  }

  const handleFileUpload = async (files: FileList) => {
    if (!selectedNotebookId) return
    for (let i = 0; i < files.length; i++) {
      await uploadSource(selectedNotebookId, files[i])
    }
  }

  const handleSendMessage = async (text?: string) => {
    const msg = (text || chatInput).trim()
    if (!msg || !selectedNotebookId || isChatting) return
    setChatInput('')
    if (inputRef.current) inputRef.current.style.height = 'auto'
    await sendMessage(selectedNotebookId, msg, selectedModel)
  }

  const handleCreateNote = async () => {
    if (!noteInput.trim() || !selectedNotebookId) return
    await createNote(selectedNotebookId, noteInput.trim(), 'user_note', noteTitle.trim() || undefined)
    setNoteInput('')
    setNoteTitle('')
    setShowNoteForm(false)
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
    a.href = url; a.download = 'chat-export.md'; a.click()
    setShowOptionsMenu(false)
  }

  const handleCitationClick = (sourceId: string, quote?: string) => {
    const source = sources.find(s => s.id === sourceId)
    if (!source) return
    setSelectedSource(source)
    setHighlightText(quote)
    setMobileTab('sources')
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'ready': return 'text-green-400'
      case 'processing': return 'text-yellow-400'
      case 'error': return 'text-destructive'
      default: return 'text-muted-foreground'
    }
  }

  const sourceIcon = (type: string) => {
    switch (type) {
      case 'url': return <Globe className="w-3 h-3 text-green-400" />
      case 'youtube': return <Youtube className="w-3 h-3 text-red-500" />
      default: return <FileText className="w-3 h-3 text-muted-foreground" />
    }
  }

  const readySources = sources.filter(s => s.status === 'ready')

  if (!selectedNotebookId || !currentNotebook) {
    return (
      <div className="p-6 text-center">
        <FileText className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Select a notebook first</p>
        <button onClick={handleBack} className="mt-2 text-xs text-primary hover:underline">
          Go to Notebooks
        </button>
      </div>
    )
  }

  // ─── Sources Panel (JSX, not a component function) ───────────────────────
  const sourcesPanel = selectedSource ? (
    <SourceDetailViewer
      source={selectedSource}
      notebookId={selectedNotebookId}
      onBack={() => { setSelectedSource(null); setHighlightText(undefined) }}
      onDelete={(sourceId) => {
        deleteSource(selectedNotebookId, sourceId)
        setSelectedSource(null)
        setHighlightText(undefined)
      }}
      compact={!isFullMode}
      highlightText={highlightText}
      onClearHighlight={() => setHighlightText(undefined)}
    />
  ) : (
    <div className="flex flex-col h-full border border-border rounded-lg bg-card/50 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <FileText className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">Sources</span>
          <span className="text-[10px] text-muted-foreground">({sources.length})</span>
        </div>
        <button
          onClick={() => setShowAddSource(!showAddSource)}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {showAddSource && (
        <AddSourceModal
          isOpen={true}
          onClose={() => setShowAddSource(false)}
          sourcesCount={sources.length}
          onFileUpload={handleFileUpload}
          onAddUrl={(url) => addUrlSource(selectedNotebookId, url).then(() => {})}
          onAddText={(title, content) => addTextSource(selectedNotebookId, title, content).then(() => {})}
          onAddYouTube={(url) => addYouTubeSource(selectedNotebookId, url).then(() => {})}
          compact={!isFullMode}
        />
      )}

      <div className="flex-1 overflow-y-auto">
        {isLoadingSources ? (
          <div className="p-3 text-center text-xs text-muted-foreground">Loading...</div>
        ) : sources.length === 0 ? (
          <div className="p-4 text-center">
            <FileText className="w-5 h-5 mx-auto mb-1 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground">No sources yet</p>
            <button onClick={() => setShowAddSource(true)}
              className="mt-2 text-[10px] text-primary hover:underline">
              Add your first source
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {sources.map(source => (
              <div key={source.id}
                className="flex items-center gap-2 px-3 py-2 hover:bg-secondary/50 group cursor-pointer"
                onClick={() => setSelectedSource(source)}
              >
                {sourceIcon(source.type)}
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-foreground truncate">{source.title || source.original_filename || 'Untitled'}</p>
                  <p className="text-[10px] text-muted-foreground">
                    <span className={statusColor(source.status)}>{source.status}</span>
                    {' · '}{source.type}
                    {source.chunk_count > 0 && <> · {source.chunk_count} chunks</>}
                  </p>
                </div>
                <button onClick={(e) => { e.stopPropagation(); deleteSource(selectedNotebookId, source.id) }}
                  className="p-0.5 rounded text-muted-foreground/30 hover:text-destructive opacity-0 group-hover:opacity-100 shrink-0">
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )

  // ─── Notes Panel (JSX, not a component function) ─────────────────────────
  const notesPanel = (
    <div className="flex flex-col h-full border border-border rounded-lg bg-card/50 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <StickyNote className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">Notes</span>
          <span className="text-[10px] text-muted-foreground">({notes.length})</span>
        </div>
        <button onClick={() => setShowNoteForm(!showNoteForm)}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary">
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {showNoteForm && (
        <div className="p-2 border-b border-border space-y-1 shrink-0">
          <input type="text" value={noteTitle} onChange={e => setNoteTitle(e.target.value)}
            placeholder="Title (optional)" className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
          <textarea value={noteInput} onChange={e => setNoteInput(e.target.value)}
            placeholder="Write your note..." rows={3} className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none" autoFocus />
          <div className="flex gap-1">
            <button onClick={handleCreateNote} disabled={!noteInput.trim()}
              className="flex-1 py-1 text-[10px] bg-primary text-primary-foreground rounded disabled:opacity-50">Save</button>
            <button onClick={() => setShowNoteForm(false)} className="px-2 py-1 text-[10px] text-muted-foreground">Cancel</button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {isLoadingNotes ? (
          <div className="p-3 text-center text-xs text-muted-foreground">Loading...</div>
        ) : notes.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">No notes yet</div>
        ) : (
          <div className="divide-y divide-border">
            {notes.map(note => (
              <div key={note.id} className="px-3 py-2 hover:bg-secondary/50 group">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-foreground truncate">{note.title || 'Untitled'}</p>
                    <p className="text-[10px] text-muted-foreground line-clamp-2 mt-0.5">{note.content}</p>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">{note.type}</span>
                      {note.is_pinned && <span className="text-[9px]">📌</span>}
                    </div>
                  </div>
                  <button onClick={() => selectedNotebookId && deleteNote(selectedNotebookId, note.id)}
                    className="p-0.5 rounded text-muted-foreground/30 hover:text-destructive opacity-0 group-hover:opacity-100 shrink-0">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )

  // ─── Chat Panel (JSX, not a component function) ──────────────────────────
  const chatPanel = (
    <div className="flex flex-col h-full border border-border rounded-lg bg-card/50 overflow-hidden">
      {/* Chat Header with model selector and options */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground">Chat</span>

          {/* Model Selector */}
          <div className="relative">
            <button onClick={() => setShowModelMenu(!showModelMenu)}
              className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-secondary border border-border rounded text-muted-foreground hover:text-foreground">
              <span className="truncate max-w-[60px]">{selectedModel || 'mistral'}</span>
              <ChevronDown className="w-2.5 h-2.5" />
            </button>
            {showModelMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowModelMenu(false)} />
                <div className="absolute left-0 top-full mt-1 bg-popover border border-border rounded-lg shadow-xl py-1 z-20 min-w-[140px]">
                  {models.map(m => (
                    <button key={m.name} onClick={() => { setSelectedModel(m.name); setShowModelMenu(false) }}
                      className={`w-full px-2 py-1 text-left text-[10px] hover:bg-secondary ${selectedModel === m.name ? 'text-primary' : 'text-foreground'}`}>
                      <div className="flex items-center justify-between">
                        <span>{m.name}</span>
                        {selectedModel === m.name && <Check className="w-3 h-3 text-primary" />}
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <span className="text-[9px] text-muted-foreground">{readySources.length} src</span>
        </div>

        {/* Options Menu */}
        <div className="relative">
          <button onClick={() => setShowOptionsMenu(!showOptionsMenu)}
            className="p-1 rounded text-muted-foreground/50 hover:text-foreground" title="Options">
            <MoreVertical className="w-3 h-3" />
          </button>
          {showOptionsMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowOptionsMenu(false)} />
              <div className="absolute right-0 top-full mt-1 bg-popover border border-border rounded-lg shadow-xl py-1 z-20 min-w-[130px]">
                <button onClick={handleCopyChat}
                  className="w-full px-2 py-1 text-left text-[10px] text-foreground hover:bg-secondary flex items-center gap-1">
                  <Copy className="w-3 h-3" /> Copy chat
                </button>
                <button onClick={handleExportMarkdown}
                  className="w-full px-2 py-1 text-left text-[10px] text-foreground hover:bg-secondary flex items-center gap-1">
                  <Download className="w-3 h-3" /> Export .md
                </button>
                <hr className="my-1 border-border" />
                <button onClick={() => { selectedNotebookId && clearChatHistory(selectedNotebookId); setShowOptionsMenu(false) }}
                  className="w-full px-2 py-1 text-left text-[10px] text-destructive hover:bg-secondary flex items-center gap-1">
                  <Trash2 className="w-3 h-3" /> Clear
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-2 space-y-3">
        {isLoadingMessages ? (
          <div className="text-center text-xs text-muted-foreground py-4">Loading...</div>
        ) : messages.length === 0 ? (
          <div className="text-center py-4">
            <Sparkles className="w-5 h-5 mx-auto mb-1 text-primary/40" />
            <p className="text-[10px] text-muted-foreground mb-3">Ask questions about your sources</p>

            {readySources.length > 0 ? (
              <div className="space-y-1">
                {SUGGESTED_PROMPTS.map((prompt, i) => (
                  <button key={i} onClick={() => handleSendMessage(prompt)}
                    className="w-full text-left px-2 py-1.5 text-[10px] text-muted-foreground bg-secondary/50 border border-border hover:border-primary/30 rounded transition-colors">
                    {prompt}
                  </button>
                ))}
              </div>
            ) : (
              <div className="px-2 py-1.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[10px] text-yellow-400">
                Add sources to start chatting
              </div>
            )}
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <ChatBubble key={msg.id} message={msg} sources={sources} onCitationClick={handleCitationClick} />
            ))}
            {isChatting && (
              <div className="flex items-center gap-2 text-muted-foreground py-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span className="text-[10px]">Thinking...</span>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-2 border-t border-border shrink-0">
        <div className="flex items-end gap-1.5 bg-secondary border border-border rounded-lg p-1.5">
          <textarea ref={inputRef} value={chatInput} onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() } }}
            placeholder={readySources.length === 0 ? "Add sources first..." : "Ask about your sources..."}
            disabled={isChatting || readySources.length === 0}
            rows={1}
            className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground resize-none focus:outline-none max-h-20 disabled:opacity-50" />
          <button onClick={() => handleSendMessage()} disabled={!chatInput.trim() || isChatting || readySources.length === 0}
            className="p-1 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shrink-0">
            {isChatting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button onClick={handleBack}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary shrink-0">
            <ArrowLeft className="w-3.5 h-3.5" />
          </button>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-foreground truncate">{currentNotebook.title}</h2>
            <p className="text-[10px] text-muted-foreground">{sources.length} sources · {notes.length} notes</p>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button onClick={toggleViewMode} title={isFullMode ? 'Half view' : 'Full page'}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary">
            {isFullMode ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Tab bar + content */}
      <div className="flex-1 overflow-hidden p-2">
        {!isFullMode && (
          <div className="flex items-center gap-1 mb-2">
            {(['sources', 'notes', 'chat', 'podcast'] as const).map(tab => (
              <button key={tab} onClick={() => setMobileTab(tab)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium ${
                  mobileTab === tab ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground hover:text-foreground'
                }`}>
                {tab === 'sources' && <FileText className="w-3 h-3" />}
                {tab === 'notes' && <StickyNote className="w-3 h-3" />}
                {tab === 'chat' && <MessageSquare className="w-3 h-3" />}
                {tab === 'podcast' && <Mic className="w-3 h-3" />}
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
        )}

        {isFullMode ? (
          <div className="grid grid-cols-4 gap-3 h-full">
            {sourcesPanel}
            {notesPanel}
            {chatPanel}
            <div className="flex flex-col h-full overflow-hidden bg-secondary/20 rounded-lg border border-border/50">
              <PodcastStudio
                notebookId={selectedNotebookId}
                notebookTitle={currentNotebook.title}
                sources={sources}
                notes={notes}
                compact={false}
              />
            </div>
          </div>
        ) : (
          <div className="h-[calc(100%-32px)]">
            {mobileTab === 'sources' && sourcesPanel}
            {mobileTab === 'notes' && notesPanel}
            {mobileTab === 'chat' && chatPanel}
            {mobileTab === 'podcast' && (
              <div className="h-full overflow-hidden">
                <PodcastStudio
                  notebookId={selectedNotebookId}
                  notebookTitle={currentNotebook.title}
                  sources={sources}
                  notes={notes}
                  compact={true}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Full-screen Add Source Modal */}
      {isFullMode && showAddSource && (
        <AddSourceModal
          isOpen={true}
          onClose={() => setShowAddSource(false)}
          sourcesCount={sources.length}
          onFileUpload={handleFileUpload}
          onAddUrl={(url) => addUrlSource(selectedNotebookId, url).then(() => {})}
          onAddText={(title, content) => addTextSource(selectedNotebookId, title, content).then(() => {})}
          onAddYouTube={(url) => addYouTubeSource(selectedNotebookId, url).then(() => {})}
          compact={false}
        />
      )}

      {/* Error Toast */}
      {error && (
        <div className="absolute bottom-2 left-2 right-2 p-2 bg-destructive/90 border border-destructive rounded-lg text-destructive-foreground flex items-center gap-2 z-50 text-xs">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="p-0.5 hover:opacity-70">&times;</button>
        </div>
      )}
    </div>
  )
}

// ─── Compact Markdown Components for notebook chat ──────────────────────────

const notebookMarkdownComponents = {
  p({ children, ...props }: any) {
    return <p className="text-xs leading-relaxed mb-1.5 last:mb-0" {...props}>{children}</p>
  },
  strong({ children, ...props }: any) {
    return <strong className="font-bold text-foreground" {...props}>{children}</strong>
  },
  em({ children, ...props }: any) {
    return <em className="italic" {...props}>{children}</em>
  },
  a({ children, href, ...props }: any) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-primary hover:underline inline-flex items-center gap-0.5" {...props}>
        {children}<ExternalLink className="h-2.5 w-2.5" />
      </a>
    )
  },
  ul({ children, ...props }: any) {
    return <ul className="list-disc list-inside space-y-0.5 mb-1.5 text-xs" {...props}>{children}</ul>
  },
  ol({ children, ...props }: any) {
    return <ol className="list-decimal list-inside space-y-0.5 mb-1.5 text-xs" {...props}>{children}</ol>
  },
  li({ children, ...props }: any) {
    return <li className="text-xs leading-relaxed" {...props}>{children}</li>
  },
  h1({ children, ...props }: any) {
    return <h1 className="text-sm font-bold mb-1" {...props}>{children}</h1>
  },
  h2({ children, ...props }: any) {
    return <h2 className="text-xs font-bold mb-1" {...props}>{children}</h2>
  },
  h3({ children, ...props }: any) {
    return <h3 className="text-xs font-semibold mb-0.5" {...props}>{children}</h3>
  },
  blockquote({ children, ...props }: any) {
    return <blockquote className="border-l-2 border-primary/40 pl-2 my-1 text-xs text-muted-foreground italic" {...props}>{children}</blockquote>
  },
  code({ children, className, inline, ...props }: any) {
    if (inline || !className) {
      return <code className="rounded bg-violet-500/20 px-1 py-0.5 text-[10px] font-mono text-violet-300" {...props}>{children}</code>
    }
    return (
      <pre className="my-1 p-2 rounded-md bg-black/30 overflow-x-auto">
        <code className="text-[10px] font-mono" {...props}>{children}</code>
      </pre>
    )
  },
}

// ─── Chat Bubble Component ──────────────────────────────────────────────────

function ChatBubble({ message, sources, onCitationClick }: {
  message: ChatMessage
  sources: NotebookSource[]
  onCitationClick?: (sourceId: string, quote?: string) => void
}) {
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
    return citation.source_title || source?.title || source?.original_filename || 'Source'
  }

  return (
    <div className={`flex items-start gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-secondary' : 'bg-gradient-to-br from-blue-500 to-purple-500'
      }`}>
        {isUser
          ? <span className="text-[8px] font-medium text-foreground">You</span>
          : <Sparkles className="w-3 h-3 text-white" />
        }
      </div>

      <div className={`flex-1 max-w-[85%] ${isUser ? 'flex flex-col items-end' : ''}`}>
        <div className={`group relative rounded-lg px-2.5 py-1.5 ${
          isUser ? 'bg-primary text-primary-foreground' : 'bg-secondary text-foreground'
        }`}>
          {isUser ? (
            <p className="whitespace-pre-wrap text-xs leading-relaxed break-words">{message.content}</p>
          ) : (
            <div className="prose-sm max-w-none break-words">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={notebookMarkdownComponents}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          <button onClick={handleCopy}
            className={`absolute top-1 right-1 p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity ${
              isUser ? 'hover:bg-primary/80' : 'hover:bg-secondary/80'
            }`}>
            {copied ? <Check className="w-2.5 h-2.5 text-green-400" /> : <Copy className="w-2.5 h-2.5 text-muted-foreground" />}
          </button>
        </div>

        {/* Reasoning */}
        {!isUser && message.reasoning && (
          <div className="mt-1">
            <button onClick={() => setShowReasoning(!showReasoning)}
              className="flex items-center gap-1 text-[9px] text-purple-400 hover:text-purple-300">
              <Cpu className="w-2.5 h-2.5" />
              {showReasoning ? 'Hide' : 'Show'} reasoning
              {showReasoning ? <ChevronUp className="w-2.5 h-2.5" /> : <ChevronDown className="w-2.5 h-2.5" />}
            </button>
            {showReasoning && (
              <div className="mt-1 p-2 bg-purple-500/10 border border-purple-500/30 rounded text-[10px] text-muted-foreground">
                <p className="whitespace-pre-wrap">{message.reasoning}</p>
              </div>
            )}
          </div>
        )}

        {/* Citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {message.citations.map((citation, i) => (
              <CitationBadge key={i} citation={citation} title={getSourceTitle(citation)} onClick={onCitationClick} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Citation Badge Component ───────────────────────────────────────────────

function CitationBadge({ citation, title, onClick }: {
  citation: Citation
  title: string
  onClick?: (sourceId: string, quote?: string) => void
}) {
  const [showTooltip, setShowTooltip] = useState(false)

  const handleClick = () => {
    if (onClick && citation.source_id) {
      onClick(citation.source_id, citation.quote)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="flex items-center gap-1 px-1.5 py-0.5 bg-popover border border-border rounded text-[9px] text-muted-foreground hover:text-primary hover:border-primary/50 hover:bg-primary/5 transition-colors cursor-pointer"
      >
        <FileText className="w-2.5 h-2.5" />
        <span className="truncate max-w-[80px]">{title}</span>
        {citation.page && <span className="text-muted-foreground/60">p.{citation.page}</span>}
      </button>

      {showTooltip && citation.quote && (
        <div className="absolute bottom-full left-0 mb-1 w-48 p-2 bg-popover border border-border rounded-lg shadow-xl z-10">
          <p className="text-[9px] text-muted-foreground italic">&ldquo;{citation.quote}&rdquo;</p>
          <p className="text-[8px] text-primary mt-1">Click to view in source</p>
          <div className="absolute bottom-0 left-3 transform translate-y-full">
            <div className="w-0 h-0 border-l-[4px] border-r-[4px] border-t-[4px] border-transparent border-t-border" />
          </div>
        </div>
      )}
    </div>
  )
}
