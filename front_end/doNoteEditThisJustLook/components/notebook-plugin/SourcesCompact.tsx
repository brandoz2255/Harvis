'use client'

import { useEffect, useState } from 'react'
import { Plus, FileText, Link, Type, Trash2, ArrowLeft, Loader2 } from 'lucide-react'
import { useNotebookStore } from '@/stores/notebookStore'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'

type AddMode = null | 'url' | 'text'

export default function SourcesCompact() {
  const { sources, isLoadingSources, fetchSources, addUrlSource, addTextSource, deleteSource, currentNotebook } =
    useNotebookStore()
  const { selectedNotebookId, setActiveTab, selectNotebook } = useNotebookPluginStore()
  const [addMode, setAddMode] = useState<AddMode>(null)
  const [urlInput, setUrlInput] = useState('')
  const [textTitle, setTextTitle] = useState('')
  const [textContent, setTextContent] = useState('')
  const [isAdding, setIsAdding] = useState(false)

  useEffect(() => {
    if (selectedNotebookId) {
      fetchSources(selectedNotebookId)
    }
  }, [selectedNotebookId, fetchSources])

  if (!selectedNotebookId) {
    return (
      <div className="p-6 text-center">
        <FileText className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Select a notebook first</p>
        <button
          onClick={() => setActiveTab('notebooks')}
          className="mt-2 text-xs text-primary hover:underline"
        >
          Go to Notebooks
        </button>
      </div>
    )
  }

  const handleAddUrl = async () => {
    if (!urlInput.trim() || !selectedNotebookId) return
    setIsAdding(true)
    await addUrlSource(selectedNotebookId, urlInput.trim())
    setUrlInput('')
    setAddMode(null)
    setIsAdding(false)
  }

  const handleAddText = async () => {
    if (!textContent.trim() || !selectedNotebookId) return
    setIsAdding(true)
    await addTextSource(selectedNotebookId, textTitle.trim() || 'Untitled', textContent.trim())
    setTextTitle('')
    setTextContent('')
    setAddMode(null)
    setIsAdding(false)
  }

  const handleDelete = async (e: React.MouseEvent, sourceId: string) => {
    e.stopPropagation()
    if (selectedNotebookId && confirm('Delete this source?')) {
      await deleteSource(selectedNotebookId, sourceId)
    }
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'ready': return 'text-green-400'
      case 'processing': return 'text-yellow-400'
      case 'error': return 'text-destructive'
      default: return 'text-muted-foreground'
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => { selectNotebook(null); setActiveTab('notebooks') }}
            className="p-1 rounded text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium text-foreground truncate">
            {currentNotebook?.title || 'Sources'}
          </span>
        </div>

        {/* Add Source Buttons */}
        {addMode === null ? (
          <div className="flex gap-2">
            <button
              onClick={() => setAddMode('url')}
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs
                         bg-secondary text-foreground rounded-md hover:bg-secondary/80 transition-colors"
            >
              <Link className="w-3.5 h-3.5" /> URL
            </button>
            <button
              onClick={() => setAddMode('text')}
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs
                         bg-secondary text-foreground rounded-md hover:bg-secondary/80 transition-colors"
            >
              <Type className="w-3.5 h-3.5" /> Text
            </button>
          </div>
        ) : addMode === 'url' ? (
          <div className="space-y-2">
            <input
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddUrl()}
              placeholder="https://..."
              className="w-full px-3 py-1.5 text-sm bg-secondary border border-border rounded-md
                         text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              autoFocus
            />
            <div className="flex gap-2">
              <button
                onClick={handleAddUrl}
                disabled={isAdding}
                className="flex-1 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
              >
                {isAdding ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : 'Add URL'}
              </button>
              <button onClick={() => setAddMode(null)} className="px-2 text-xs text-muted-foreground hover:text-foreground">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <input
              type="text"
              value={textTitle}
              onChange={(e) => setTextTitle(e.target.value)}
              placeholder="Title..."
              className="w-full px-3 py-1.5 text-sm bg-secondary border border-border rounded-md
                         text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              autoFocus
            />
            <textarea
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              placeholder="Paste your text..."
              rows={3}
              className="w-full px-3 py-1.5 text-sm bg-secondary border border-border rounded-md
                         text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none"
            />
            <div className="flex gap-2">
              <button
                onClick={handleAddText}
                disabled={isAdding}
                className="flex-1 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
              >
                {isAdding ? <Loader2 className="w-3 h-3 animate-spin mx-auto" /> : 'Add Text'}
              </button>
              <button onClick={() => setAddMode(null)} className="px-2 text-xs text-muted-foreground hover:text-foreground">
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Sources List */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingSources ? (
          <div className="p-4 text-center text-sm text-muted-foreground">Loading sources...</div>
        ) : sources.length === 0 ? (
          <div className="p-6 text-center">
            <FileText className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">No sources yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">Add a URL or paste text to get started</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {sources.map((source) => (
              <div
                key={source.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-secondary/50 transition-colors group"
              >
                <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {source.title || source.original_filename || 'Untitled'}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    <span className={statusColor(source.status)}>{source.status}</span>
                    {' '}&middot;{' '}{source.type}
                    {source.chunk_count > 0 && <> &middot; {source.chunk_count} chunks</>}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(e, source.id)}
                  className="p-1 rounded text-muted-foreground/50 hover:text-destructive
                             opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
