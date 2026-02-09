'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useNotebookStore, NotebookNote, NotebookSource } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import AddSourceModal from '@/components/notebook/AddSourceModal'
import TransformPanel from '@/components/notebook/TransformPanel'
import SourcesColumn from '@/components/notebook/SourcesColumn'
import NotesColumn from '@/components/notebook/NotesColumn'
import ChatColumn from '@/components/notebook/ChatColumn'
import PodcastView from '@/components/notebook/PodcastView'
import NoteEditorDialog from '@/components/notebook/NoteEditorDialog'
import { ContextMode } from '@/components/notebook/types'
import { Loader2, AlertCircle, ArrowLeft, FileText, MessageSquare, Mic, StickyNote } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import OpenNotebookAPI from '@/lib/openNotebookApi'

export default function NotebookWorkspacePage() {
  const router = useRouter()
  const params = useParams()
  // Decode the URL-encoded notebook ID from the route params
  const notebookId = decodeURIComponent(params.id as string)
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
    sendMessage,
    clearChatHistory,
    createNote,
    updateNote,
    deleteNote,
    setError,
  } = useNotebookStore()

  // UI state
  const [showAddSourceModal, setShowAddSourceModal] = useState(false)
  const [showTransformPanel, setShowTransformPanel] = useState(false)
  const [transformSource, setTransformSource] = useState<NotebookSource | null>(null)
  const [noteDialogOpen, setNoteDialogOpen] = useState(false)
  const [editingNote, setEditingNote] = useState<NotebookNote | null>(null)
  const [mobileTab, setMobileTab] = useState<'sources' | 'notes' | 'chat' | 'podcast'>('chat')
  const [activeView, setActiveView] = useState<'workspace' | 'podcast'>('workspace')
  const [selectedSource, setSelectedSource] = useState<NotebookSource | null>(null)
  const [sourceDetail, setSourceDetail] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  const [contextSelections, setContextSelections] = useState<{
    sources: Record<string, ContextMode>
    notes: Record<string, ContextMode>
  }>({
    sources: {},
    notes: {},
  })

  // Load notebook on mount
  useEffect(() => {
    if (!authLoading && user && notebookId) {
      selectNotebook(notebookId)
    }
  }, [authLoading, user, notebookId, selectNotebook])

  useEffect(() => {
    if (sources.length > 0) {
      setContextSelections((prev) => {
        const next = { ...prev.sources }
        sources.forEach((source) => {
          if (!next[source.id]) {
            next[source.id] = "full"
          }
        })
        return { ...prev, sources: next }
      })
    }
  }, [sources])

  useEffect(() => {
    if (notes.length > 0) {
      setContextSelections((prev) => {
        const next = { ...prev.notes }
        notes.forEach((note) => {
          if (!next[note.id]) {
            next[note.id] = "full"
          }
        })
        return { ...prev, notes: next }
      })
    }
  }, [notes])

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
  const handleTitleChange = async (title: string) => {
    if (notebookId) {
      await updateNotebook(notebookId, title)
    }
  }

  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections((prev) => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode,
      },
    }))
  }

  const handleSourceDelete = async (sourceId: string) => {
    if (notebookId) {
      await deleteSource(notebookId, sourceId)
    }
  }

  const handleSourceTransform = (source: NotebookSource) => {
    setTransformSource(source)
    setShowTransformPanel(true)
  }

  const handleViewSource = async (source: NotebookSource) => {
    setSelectedSource(source)
    setDetailLoading(true)
    setDetailError(null)
    setSourceDetail(null)
    try {
      const result = await OpenNotebookAPI.sources.get(source.id)
      setSourceDetail(result.full_text || result.content || '')
    } catch (error: any) {
      setDetailError(error?.message || 'Failed to load source content')
    } finally {
      setDetailLoading(false)
    }
  }

  const handleFileUpload = async (files: FileList) => {
    if (!notebookId) return
    for (const file of Array.from(files)) {
      await uploadSource(notebookId, file)
    }
    setShowAddSourceModal(false)
  }

  const handleAddUrl = async (url: string) => {
    if (!notebookId) return
    await addUrlSource(notebookId, url)
    setShowAddSourceModal(false)
  }

  const handleAddText = async (title: string, content: string) => {
    if (!notebookId) return
    await addTextSource(notebookId, title, content)
    setShowAddSourceModal(false)
  }

  const handleAddYouTube = async (url: string) => {
    if (!notebookId) return
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/notebooks/${notebookId}/sources/youtube`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ url, title: null })
      })
      if (response.ok) {
        selectNotebook(notebookId)
      }
    } catch (err) {
      console.error('Failed to add YouTube source:', err)
    }
    setShowAddSourceModal(false)
  }

  const handleSendMessage = async (message: string) => {
    if (notebookId) {
      await sendMessage(notebookId, message)
    }
  }

  const handleClearChatHistory = async () => {
    if (notebookId) {
      await clearChatHistory(notebookId)
    }
  }

  // Loading state
  if (authLoading || isLoadingNotebooks) {
    return (
      <div className="flex items-center justify-center h-full bg-[#0a0a0a]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    )
  }

  // Not authenticated
  if (!user) {
    router.push('/login')
    return null
  }

  // Notebook not found
  if (!currentNotebook) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-[#0a0a0a] text-center">
        <AlertCircle className="w-16 h-16 text-gray-500 mb-4" />
        <h2 className="text-2xl font-bold text-white mb-2">Notebook not found</h2>
        <p className="text-gray-400 mb-6">This notebook may have been deleted or you don&apos;t have access to it.</p>
        <button
          onClick={() => router.push('/notebooks')}
          className="flex items-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Notebooks
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-[#0a0a0a]">
      {/* Header with back button and title */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/notebooks')}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
            title="Back to notebooks"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-lg font-semibold text-white">{currentNotebook.title}</h1>
            <p className="text-xs text-gray-500">
              {sources.length} sources • {notes.length} notes
            </p>
          </div>
        </div>
        
        {/* View Toggle */}
        <div className="flex items-center gap-1 bg-gray-800/50 p-1 rounded-lg">
          <button
            onClick={() => setActiveView('workspace')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              activeView === 'workspace'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <FileText className="w-4 h-4" />
            Workspace
          </button>
          <button
            onClick={() => setActiveView('podcast')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              activeView === 'podcast'
                ? 'bg-gradient-to-r from-orange-500/20 to-pink-500/20 text-orange-400 border border-orange-500/30'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <Mic className="w-4 h-4" />
            Podcast
          </button>
        </div>
      </div>

      {/* Podcast View */}
      {activeView === 'podcast' && (
        <PodcastView
          notebookId={notebookId}
          notebookTitle={currentNotebook.title}
          sources={sources}
          notes={notes}
        />
      )}

      {/* Workspace View */}
      {activeView === 'workspace' && (
        <div className="flex-1 overflow-hidden p-6">
          {/* Mobile tabs */}
          <div className="flex items-center gap-2 mb-4 lg:hidden">
            {(['sources', 'notes', 'chat'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setMobileTab(tab)}
                className={`px-3 py-2 rounded-lg text-xs font-medium ${
                  mobileTab === tab
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300'
                }`}
              >
                {tab.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Desktop three-panel */}
          <div className="hidden lg:grid lg:grid-cols-3 gap-6 h-full">
          <SourcesColumn
            sources={sources}
            isLoading={isLoadingSources}
            contextSelections={contextSelections.sources}
            onContextModeChange={(id, mode) => handleContextModeChange(id, mode, 'source')}
            onAddSource={() => setShowAddSourceModal(true)}
            onDeleteSource={handleSourceDelete}
            onTransformSource={handleSourceTransform}
            onViewSource={handleViewSource}
          />
          <NotesColumn
            notes={notes}
            isLoading={isLoadingNotes}
            contextSelections={contextSelections.notes}
            onContextModeChange={(id, mode) => handleContextModeChange(id, mode, 'note')}
            onWriteNote={() => {
              setEditingNote(null)
              setNoteDialogOpen(true)
            }}
            onEditNote={(note) => {
              setEditingNote(note)
              setNoteDialogOpen(true)
            }}
            onDeleteNote={async (noteId) => {
              await deleteNote(notebookId, noteId)
            }}
          />
          <ChatColumn
            messages={messages}
            isLoading={isLoadingMessages}
            isChatting={isChatting}
            onSendMessage={handleSendMessage}
            onClearHistory={handleClearChatHistory}
            onSaveAsNote={async (content) => {
              await createNote(notebookId, content, 'user_note')
            }}
            sourcesCount={sources.length}
            notesCount={notes.length}
            contextSelections={contextSelections}
          />
        </div>

        {/* Mobile stacked panels */}
        <div className="lg:hidden h-full">
          {mobileTab === 'sources' && (
            <SourcesColumn
              sources={sources}
              isLoading={isLoadingSources}
              contextSelections={contextSelections.sources}
              onContextModeChange={(id, mode) => handleContextModeChange(id, mode, 'source')}
              onAddSource={() => setShowAddSourceModal(true)}
              onDeleteSource={handleSourceDelete}
              onTransformSource={handleSourceTransform}
              onViewSource={handleViewSource}
            />
          )}
          {mobileTab === 'notes' && (
          <NotesColumn
            notes={notes}
            isLoading={isLoadingNotes}
              contextSelections={contextSelections.notes}
              onContextModeChange={(id, mode) => handleContextModeChange(id, mode, 'note')}
              onWriteNote={() => {
                setEditingNote(null)
                setNoteDialogOpen(true)
              }}
              onEditNote={(note) => {
                setEditingNote(note)
                setNoteDialogOpen(true)
              }}
              onDeleteNote={async (noteId) => {
                await deleteNote(notebookId, noteId)
              }}
            />
          )}
          {mobileTab === 'chat' && (
            <ChatColumn
              messages={messages}
              isLoading={isLoadingMessages}
              isChatting={isChatting}
              onSendMessage={handleSendMessage}
              onClearHistory={handleClearChatHistory}
              onSaveAsNote={async (content) => {
                await createNote(notebookId, content, 'user_note')
              }}
              sourcesCount={sources.length}
              notesCount={notes.length}
              contextSelections={contextSelections}
            />
          )}
        </div>
      </div>
      )}

      {/* Add Source Modal */}
      <AddSourceModal
        isOpen={showAddSourceModal}
        onClose={() => setShowAddSourceModal(false)}
        sourcesCount={sources.length}
        onFileUpload={handleFileUpload}
        onAddUrl={handleAddUrl}
        onAddText={handleAddText}
        onAddYouTube={handleAddYouTube}
      />

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

      <NoteEditorDialog
        open={noteDialogOpen}
        onOpenChange={setNoteDialogOpen}
        initialTitle={editingNote?.title}
        initialContent={editingNote?.content}
        onSave={async (title, content) => {
          if (editingNote) {
            await updateNote(notebookId, editingNote.id, content, title)
          } else {
            await createNote(notebookId, content, 'user_note', title)
          }
        }}
      />

      <Dialog open={!!selectedSource} onOpenChange={(open) => !open && setSelectedSource(null)}>
        <DialogContent className="max-w-3xl bg-[#0a0a0a] border border-gray-800 text-white">
          <DialogHeader>
            <DialogTitle>Extracted Content</DialogTitle>
            <DialogDescription className="text-gray-400">
              {selectedSource?.title || selectedSource?.original_filename || 'Source'}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto rounded-lg border border-gray-800 bg-[#111111] p-4 text-sm text-gray-200 whitespace-pre-wrap">
            {detailLoading && (
              <div className="flex items-center gap-2 text-gray-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading extracted content...
              </div>
            )}
            {detailError && (
              <div className="text-red-400">{detailError}</div>
            )}
            {!detailLoading && !detailError && (sourceDetail || 'No extracted content available yet.')}
          </div>
        </DialogContent>
      </Dialog>

      {/* Error Toast */}
      {error && (
        <div className="fixed bottom-4 right-4 p-4 bg-red-900/90 border border-red-700 rounded-lg text-red-200 flex items-center gap-3 z-50 max-w-md">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
          <button
            onClick={() => setError(null)}
            className="p-1 hover:text-white ml-auto"
          >
            &times;
          </button>
        </div>
      )}
    </div>
  )
}
