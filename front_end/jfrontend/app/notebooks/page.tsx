'use client'

import { useEffect, useState, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useNotebookStore, Notebook } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import {
  Plus,
  BookOpen,
  FileText,
  MessageSquare,
  StickyNote,
  Clock,
  Trash2,
  Edit2,
  Loader2,
  Search,
  RefreshCw,
  MoreHorizontal,
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Mic,
  Sparkles,
  Podcast,
  Youtube
} from 'lucide-react'

// Feature highlights for the notebooks page
const FEATURES = [
  {
    icon: <Youtube className="w-5 h-5" />,
    title: 'YouTube Import',
    description: 'Extract transcripts from videos'
  },
  {
    icon: <Sparkles className="w-5 h-5" />,
    title: 'AI Transformations',
    description: 'Summarize, extract key points, and more'
  },
  {
    icon: <Mic className="w-5 h-5" />,
    title: 'Podcast Generation',
    description: 'Turn notebooks into audio podcasts'
  }
]

export default function NotebooksPage() {
  const router = useRouter()
  const { user, isLoading: authLoading } = useUser()
  const {
    notebooks,
    isLoadingNotebooks,
    error,
    fetchNotebooks,
    createNotebook,
    deleteNotebook,
    updateNotebook
  } = useNotebookStore()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [editingNotebook, setEditingNotebook] = useState<Notebook | null>(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [showArchivedSection, setShowArchivedSection] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

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
      router.push(`/notebooks/${notebook.id}`)
    }
  }

  const handleDeleteNotebook = async (notebookId: string) => {
    await deleteNotebook(notebookId)
    setShowDeleteConfirm(null)
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
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
        <div className="w-20 h-20 rounded-full bg-gradient-to-br from-orange-400 via-pink-500 to-purple-600 flex items-center justify-center mb-6">
          <BookOpen className="w-10 h-10 text-white" />
        </div>
        <h2 className="text-3xl font-bold text-white mb-3">Open Notebook</h2>
        <p className="text-gray-400 mb-8 max-w-md">
          Create notebooks, upload sources, chat with your documents using RAG, 
          and generate podcasts from your content.
        </p>
        
        {/* Feature highlights */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 max-w-2xl">
          {FEATURES.map((feature, i) => (
            <div key={i} className="p-4 bg-gray-800/50 rounded-xl border border-gray-700/50 text-left">
              <div className="text-purple-400 mb-2">{feature.icon}</div>
              <h3 className="font-medium text-white text-sm">{feature.title}</h3>
              <p className="text-xs text-gray-500">{feature.description}</p>
            </div>
          ))}
        </div>
        
        <button
          onClick={() => router.push('/login')}
          className="px-8 py-3 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-xl hover:opacity-90 transition-opacity font-medium"
        >
          Sign In to Get Started
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-400 via-pink-500 to-purple-600 flex items-center justify-center">
            <BookOpen className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Notebooks</h1>
            <p className="text-sm text-gray-500">{activeNotebooks.length} active notebooks</p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors ml-2"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search notebooks..."
              className="w-64 pl-9 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
            />
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-lg hover:opacity-90 transition-opacity font-medium"
          >
            <Plus className="w-4 h-4" />
            New Notebook
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-red-900/50 border border-red-700 rounded-lg text-red-200">
          {error}
        </div>
      )}

      {/* Loading */}
      {isLoadingNotebooks ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
        </div>
      ) : activeNotebooks.length === 0 && archivedNotebooks.length === 0 ? (
        <div className="text-center py-16">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-gray-800 flex items-center justify-center">
            <BookOpen className="w-10 h-10 text-gray-600" />
          </div>
          <h3 className="text-xl text-white mb-2">
            {searchQuery ? 'No notebooks found' : 'Create your first notebook'}
          </h3>
          <p className="text-gray-500 mb-8 max-w-md mx-auto">
            {searchQuery 
              ? 'Try a different search term' 
              : 'Notebooks help you organize your research. Add sources, take notes, and chat with your documents.'}
          </p>
          {!searchQuery && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-xl hover:opacity-90 transition-opacity font-medium"
            >
              <Plus className="w-5 h-5" />
              Create Notebook
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-8">
          {/* Active Notebooks */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-lg font-semibold text-white">Active Notebooks</h2>
              <span className="text-sm text-gray-500">({activeNotebooks.length})</span>
            </div>
            
            {activeNotebooks.length === 0 ? (
              <div className="p-8 text-center bg-gray-800/30 rounded-xl border border-gray-700/50">
                <p className="text-gray-500">
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
                    onDelete={() => setShowDeleteConfirm(notebook.id)}
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
                className="flex items-center gap-2 mb-4 hover:text-white transition-colors"
              >
                {showArchivedSection ? (
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                )}
                <h2 className="text-lg font-semibold text-gray-400">Archived Notebooks</h2>
                <span className="text-sm text-gray-600">({archivedNotebooks.length})</span>
              </button>
              
              {showArchivedSection && (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {archivedNotebooks.map((notebook) => (
                    <NotebookCard
                      key={notebook.id}
                      notebook={notebook}
                      isArchived
                      onEdit={(e) => handleEditNotebook(e, notebook)}
                      onDelete={() => setShowDeleteConfirm(notebook.id)}
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
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-400 via-pink-500 to-purple-600 flex items-center justify-center">
                <BookOpen className="w-5 h-5 text-white" />
              </div>
              <h2 className="text-xl font-bold text-white">
                {editingNotebook ? 'Edit Notebook' : 'Create New Notebook'}
              </h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Name</label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="My Research Notebook"
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && (editingNotebook ? handleSaveEdit() : handleCreateNotebook())}
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Description (optional)</label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Add a description to help you remember what this notebook is for..."
                  rows={3}
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setShowCreateModal(false)
                  setEditingNotebook(null)
                  setNewTitle('')
                  setNewDescription('')
                }}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={editingNotebook ? handleSaveEdit : handleCreateNotebook}
                disabled={!newTitle.trim()}
                className="px-6 py-2 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-xl hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed font-medium"
              >
                {editingNotebook ? 'Save Changes' : 'Create Notebook'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-xl font-bold text-white mb-2">Delete Notebook</h2>
            <p className="text-gray-400 mb-6">
              Are you sure you want to delete this notebook? This action cannot be undone and will delete all sources, notes, and chat history.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDeleteConfirm(null)}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteNotebook(showDeleteConfirm)}
                className="px-6 py-2 bg-red-600 text-white rounded-xl hover:bg-red-700 transition-colors font-medium"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
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
      onClick={() => router.push(`/notebooks/${notebook.id}`)}
      className={`group relative p-5 rounded-xl border transition-all cursor-pointer ${
        isArchived 
          ? 'bg-gray-800/30 border-gray-700/50 hover:border-gray-600' 
          : 'bg-gray-800/50 border-gray-700 hover:border-purple-500/50 hover:bg-gray-800'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className={`p-2 rounded-lg ${isArchived ? 'bg-gray-700/50' : 'bg-purple-600/20'}`}>
            <BookOpen className={`w-5 h-5 ${isArchived ? 'text-gray-500' : 'text-purple-400'}`} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className={`font-semibold truncate transition-colors ${
              isArchived 
                ? 'text-gray-400 group-hover:text-gray-300' 
                : 'text-white group-hover:text-purple-400'
            }`}>
              {notebook.title}
            </h3>
            {isArchived && (
              <span className="inline-block mt-1 px-2 py-0.5 text-xs bg-gray-700 text-gray-400 rounded">
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
            className="p-1.5 text-gray-500 hover:text-white hover:bg-gray-700 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
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
              <div className="absolute right-0 top-8 z-20 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 min-w-[140px]">
                <button
                  onClick={(e) => {
                    onEdit(e)
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-2"
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
                  className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-gray-700 flex items-center gap-2"
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
        <p className="text-sm text-gray-500 mb-4 line-clamp-2">
          {notebook.description}
        </p>
      )}

      {/* Stats */}
      <div className="flex items-center gap-3 pt-3 border-t border-gray-700/50">
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
          isArchived ? 'bg-gray-700/50 text-gray-500' : 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
        }`}>
          <FileText className="w-3 h-3" />
          <span>{notebook.source_count}</span>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
          isArchived ? 'bg-gray-700/50 text-gray-500' : 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
        }`}>
          <StickyNote className="w-3 h-3" />
          <span>{notebook.note_count}</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1 text-xs text-gray-600">
          <Clock className="w-3 h-3" />
          <span>{formatTimeAgo(notebook.updated_at)}</span>
        </div>
      </div>
    </div>
  )
}
