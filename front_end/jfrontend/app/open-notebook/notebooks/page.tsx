'use client'

import { useEffect, useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useNotebookStore, Notebook } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import { useCreateDialogsStore } from '@/stores/openNotebookUiStore'
import {
  Plus,
  BookOpen,
  FileText,
  StickyNote,
  Clock,
  Trash2,
  Edit2,
  Loader2,
  Search,
  RefreshCw,
  MoreHorizontal,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'

export default function OpenNotebookNotebooksPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useUser()
  const { openNotebookDialog } = useCreateDialogsStore()
  const {
    notebooks,
    isLoadingNotebooks,
    error,
    isOpenNotebookAvailable,
    fetchNotebooks,
    createNotebook,
    deleteNotebook,
    updateNotebook,
    checkServiceHealth
  } = useNotebookStore()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [editingNotebook, setEditingNotebook] = useState<Notebook | null>(null)
  const [deleteConfirmNotebook, setDeleteConfirmNotebook] = useState<string | null>(null)
  const [showArchivedSection, setShowArchivedSection] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    checkServiceHealth()
  }, [checkServiceHealth])

  useEffect(() => {
    if (!authLoading && user) {
      fetchNotebooks()
    }
  }, [authLoading, user, fetchNotebooks])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchNotebooks()
    setIsRefreshing(false)
  }

  const handleCreateNotebook = async () => {
    if (!newTitle.trim()) return

    const notebook = await createNotebook(newTitle.trim(), newDescription.trim() || undefined)
    if (notebook) {
      setShowCreateModal(false)
      setNewTitle('')
      setNewDescription('')
      router.push(`/open-notebook/notebooks/${notebook.id}`)
    }
  }

  const handleDeleteNotebook = async () => {
    if (!deleteConfirmNotebook) return
    await deleteNotebook(deleteConfirmNotebook)
    setDeleteConfirmNotebook(null)
  }

  const handleEditNotebook = (e: React.MouseEvent, notebook: Notebook) => {
    e.stopPropagation()
    setEditingNotebook(notebook)
    setNewTitle(notebook.title)
    setNewDescription(notebook.description || '')
  }

  const handleSaveEdit = async () => {
    if (!editingNotebook || !newTitle.trim()) return

    await updateNotebook(editingNotebook.id, newTitle.trim(), newDescription.trim() || undefined)
    setEditingNotebook(null)
    setNewTitle('')
    setNewDescription('')
  }

  // Filter notebooks by search and active/archived status
  const normalizedQuery = searchQuery.trim().toLowerCase()

  const { activeNotebooks, archivedNotebooks } = useMemo(() => {
    const filtered = notebooks.filter(n =>
      n.title.toLowerCase().includes(normalizedQuery) ||
      (n.description && n.description.toLowerCase().includes(normalizedQuery))
    )

    return {
      activeNotebooks: filtered.filter(n => n.is_active !== false),
      archivedNotebooks: filtered.filter(n => n.is_active === false)
    }
  }, [notebooks, normalizedQuery])

  const hasArchivedNotebooks = archivedNotebooks.length > 0

  // Time formatting helper
  const formatTimeAgo = (date: string) => {
    const now = new Date()
    const then = new Date(date)
    const diffMs = now.getTime() - then.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return then.toLocaleDateString()
  }

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-4">
        <div className="w-20 h-20 rounded-full bg-primary/20 flex items-center justify-center mb-6">
          <BookOpen className="w-10 h-10 text-primary" />
        </div>
        <h2 className="text-3xl font-bold mb-3">Open Notebook</h2>
        <p className="text-muted-foreground mb-8 max-w-md">
          Create notebooks, upload sources, chat with your documents using RAG,
          and generate podcasts from your content.
        </p>
        <Button onClick={() => router.push('/login')}>
          Sign In to Get Started
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">Notebooks</h1>
              <p className="text-sm text-muted-foreground">{activeNotebooks.length} active notebooks</p>
            </div>
            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors ml-2"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
            {/* Service Status */}
            <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs ${
              isOpenNotebookAvailable
                ? 'bg-green-500/10 text-green-500 border border-green-500/20'
                : 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/20'
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${isOpenNotebookAvailable ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'}`} />
              {isOpenNotebookAvailable ? 'Connected' : 'Connecting...'}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search notebooks..."
                className="w-64 pl-9 pr-4 py-2 bg-muted border border-border rounded-lg text-foreground placeholder-muted-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
            <Button onClick={() => setShowCreateModal(true)}>
              <Plus className="w-4 h-4 mr-2" />
              New Notebook
            </Button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg flex items-center justify-between">
            <span className="text-destructive">{error}</span>
            <div className="flex gap-2">
              {error.includes('login') && (
                <Button variant="outline" size="sm" onClick={() => router.push('/login')}>
                  Login
                </Button>
              )}
              {(error.includes('connect') || error.includes('Server') || error.includes('try again')) && (
                <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isRefreshing}>
                  <RefreshCw className={`w-3 h-3 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
                  Retry
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Loading */}
        {isLoadingNotebooks ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        ) : activeNotebooks.length === 0 && archivedNotebooks.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
              <BookOpen className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl mb-2">
              {searchQuery ? 'No notebooks found' : 'Create your first notebook'}
            </h3>
            <p className="text-muted-foreground mb-8 max-w-md mx-auto">
              {searchQuery
                ? 'Try a different search term'
                : 'Notebooks help you organize your research. Add sources, take notes, and chat with your documents.'}
            </p>
            {!searchQuery && (
              <Button onClick={() => setShowCreateModal(true)}>
                <Plus className="w-5 h-5 mr-2" />
                Create Notebook
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-8">
            {/* Active Notebooks */}
            <div>
              <div className="flex items-center gap-2 mb-4">
                <h2 className="text-lg font-semibold">Active Notebooks</h2>
                <span className="text-sm text-muted-foreground">({activeNotebooks.length})</span>
              </div>

              {activeNotebooks.length === 0 ? (
                <div className="p-8 text-center bg-muted/30 rounded-xl border border-border">
                  <p className="text-muted-foreground">
                    {searchQuery ? 'No active notebooks match your search' : 'No active notebooks'}
                  </p>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {activeNotebooks.map((notebook) => (
                    <NotebookCard
                      key={notebook.id}
                      notebook={notebook}
                      onEdit={(e) => handleEditNotebook(e, notebook)}
                      onDelete={() => setDeleteConfirmNotebook(notebook.id)}
                      formatTimeAgo={formatTimeAgo}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Archived Notebooks */}
            {hasArchivedNotebooks && (
              <div>
                <button
                  onClick={() => setShowArchivedSection(!showArchivedSection)}
                  className="flex items-center gap-2 mb-4 hover:text-foreground transition-colors"
                >
                  {showArchivedSection ? (
                    <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  )}
                  <h2 className="text-lg font-semibold text-muted-foreground">Archived Notebooks</h2>
                  <span className="text-sm text-muted-foreground">({archivedNotebooks.length})</span>
                </button>

                {showArchivedSection && (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {archivedNotebooks.map((notebook) => (
                      <NotebookCard
                        key={notebook.id}
                        notebook={notebook}
                        isArchived
                        onEdit={(e) => handleEditNotebook(e, notebook)}
                        onDelete={() => setDeleteConfirmNotebook(notebook.id)}
                        formatTimeAgo={formatTimeAgo}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Create/Edit Modal */}
        {(showCreateModal || editingNotebook) && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
            <div className="bg-card border border-border rounded-2xl p-6 w-full max-w-md shadow-2xl">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
                  <BookOpen className="w-5 h-5 text-primary" />
                </div>
                <h2 className="text-xl font-bold">
                  {editingNotebook ? 'Edit Notebook' : 'Create New Notebook'}
                </h2>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-muted-foreground mb-1">Name</label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="My Research Notebook"
                    className="w-full px-4 py-3 bg-muted border border-border rounded-xl placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    autoFocus
                    onKeyDown={(e) => e.key === 'Enter' && (editingNotebook ? handleSaveEdit() : handleCreateNotebook())}
                  />
                </div>

                <div>
                  <label className="block text-sm text-muted-foreground mb-1">Description (optional)</label>
                  <textarea
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="Add a description to help you remember what this notebook is for..."
                    rows={3}
                    className="w-full px-4 py-3 bg-muted border border-border rounded-xl placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 mt-6">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setShowCreateModal(false)
                    setEditingNotebook(null)
                    setNewTitle('')
                    setNewDescription('')
                  }}
                >
                  Cancel
                </Button>
                <Button
                  onClick={editingNotebook ? handleSaveEdit : handleCreateNotebook}
                  disabled={!newTitle.trim()}
                >
                  {editingNotebook ? 'Save Changes' : 'Create Notebook'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Delete Confirmation Dialog */}
        <ConfirmDialog
          open={!!deleteConfirmNotebook}
          onOpenChange={(open) => !open && setDeleteConfirmNotebook(null)}
          title="Delete Notebook"
          description="Are you sure you want to delete this notebook? This action cannot be undone and will delete all sources, notes, and chat history."
          confirmText="Delete"
          confirmVariant="destructive"
          onConfirm={handleDeleteNotebook}
        />
      </div>
    </div>
  )
}

// Notebook Card Component
interface NotebookCardProps {
  notebook: Notebook
  isArchived?: boolean
  onEdit: (e: React.MouseEvent) => void
  onDelete: () => void
  formatTimeAgo: (date: string) => string
}

function NotebookCard({ notebook, isArchived, onEdit, onDelete, formatTimeAgo }: NotebookCardProps) {
  const router = useRouter()
  const [showMenu, setShowMenu] = useState(false)

  return (
    <div
      onClick={() => router.push(`/open-notebook/notebooks/${notebook.id}`)}
      className={`group relative p-5 rounded-xl border transition-all cursor-pointer card-hover ${
        isArchived
          ? 'bg-muted/30 border-border/50'
          : 'bg-card border-border hover:border-primary/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className={`p-2 rounded-lg ${isArchived ? 'bg-muted' : 'bg-primary/20'}`}>
            <BookOpen className={`w-5 h-5 ${isArchived ? 'text-muted-foreground' : 'text-primary'}`} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className={`font-semibold truncate transition-colors ${
              isArchived
                ? 'text-muted-foreground group-hover:text-foreground'
                : 'group-hover:text-primary'
            }`}>
              {notebook.title}
            </h3>
            {isArchived && (
              <span className="inline-block mt-1 px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded">
                Archived
              </span>
            )}
          </div>
        </div>

        {/* Actions Menu */}
        <div className="relative">
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowMenu(!showMenu)
            }}
            className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg opacity-0 group-hover:opacity-100 transition-all"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>

          {showMenu && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowMenu(false)
                }}
              />
              <div className="absolute right-0 top-8 z-20 bg-popover border border-border rounded-lg shadow-xl py-1 min-w-[140px]">
                <button
                  onClick={(e) => {
                    onEdit(e)
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-muted flex items-center gap-2"
                >
                  <Edit2 className="w-4 h-4" />
                  Edit
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete()
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-destructive hover:bg-muted flex items-center gap-2"
                >
                  <Trash2 className="w-4 h-4" />
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Description */}
      {notebook.description && (
        <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
          {notebook.description}
        </p>
      )}

      {/* Stats */}
      <div className="flex items-center gap-3 pt-3 border-t border-border/50">
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
          isArchived ? 'bg-muted text-muted-foreground' : 'bg-primary/10 text-primary border border-primary/20'
        }`}>
          <FileText className="w-3 h-3" />
          <span>{notebook.source_count}</span>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
          isArchived ? 'bg-muted text-muted-foreground' : 'bg-primary/10 text-primary border border-primary/20'
        }`}>
          <StickyNote className="w-3 h-3" />
          <span>{notebook.note_count}</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="w-3 h-3" />
          <span>{formatTimeAgo(notebook.updated_at)}</span>
        </div>
      </div>
    </div>
  )
}
