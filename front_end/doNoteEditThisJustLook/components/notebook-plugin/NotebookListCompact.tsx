'use client'

import { useEffect, useState } from 'react'
import { Plus, BookOpen, Trash2, ChevronRight } from 'lucide-react'
import { useNotebookStore, Notebook } from '@/stores/notebookStore'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'

export default function NotebookListCompact() {
  const { notebooks, isLoadingNotebooks, fetchNotebooks, createNotebook, deleteNotebook } =
    useNotebookStore()
  const { selectNotebook, setActiveTab } = useNotebookPluginStore()
  const [newTitle, setNewTitle] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  useEffect(() => {
    fetchNotebooks()
  }, [fetchNotebooks])

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    const nb = await createNotebook(newTitle.trim())
    if (nb) {
      setNewTitle('')
      setIsCreating(false)
      selectNotebook(nb.id)
      setActiveTab('sources')
    }
  }

  const handleSelect = (nb: Notebook) => {
    selectNotebook(nb.id)
    // Also tell the data store to load this notebook's data
    useNotebookStore.getState().selectNotebook(nb.id)
    setActiveTab('sources')
  }

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (confirm('Delete this notebook?')) {
      await deleteNotebook(id)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Create Section */}
      <div className="p-3 border-b border-border">
        {isCreating ? (
          <div className="flex gap-2">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="Notebook name..."
              className="flex-1 px-3 py-1.5 text-sm bg-secondary border border-border rounded-md
                         text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              autoFocus
            />
            <button
              onClick={handleCreate}
              className="px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
            >
              Create
            </button>
            <button
              onClick={() => setIsCreating(false)}
              className="px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setIsCreating(true)}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm font-medium
                       bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Notebook
          </button>
        )}
      </div>

      {/* Notebook List */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingNotebooks ? (
          <div className="p-4 text-center text-sm text-muted-foreground">Loading...</div>
        ) : notebooks.length === 0 ? (
          <div className="p-6 text-center">
            <BookOpen className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">No notebooks yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">Create one to get started</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {notebooks.map((nb) => (
              <button
                key={nb.id}
                onClick={() => handleSelect(nb)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left
                           hover:bg-secondary/50 transition-colors group"
              >
                <BookOpen className="w-4 h-4 text-primary shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{nb.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {nb.source_count} sources &middot; {nb.note_count} notes
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={(e) => handleDelete(e, nb.id)}
                    className="p-1 rounded text-muted-foreground/50 hover:text-destructive
                               opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                  <ChevronRight className="w-4 h-4 text-muted-foreground/50" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
