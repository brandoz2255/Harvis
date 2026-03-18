'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useNotebookStore, Notebook } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import {
  Plus,
  BookOpen,
  FileText,
  MessageSquare,
  Clock,
  Trash2,
  Edit2,
  Loader2,
  Search
} from 'lucide-react'

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

  useEffect(() => {
    if (!authLoading && user) {
      fetchNotebooks()
    }
  }, [authLoading, user, fetchNotebooks])

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

  const handleDeleteNotebook = async (e: React.MouseEvent, notebookId: string) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to delete this notebook? This action cannot be undone.')) {
      await deleteNotebook(notebookId)
    }
  }

  const handleEditNotebook = async (e: React.MouseEvent, notebook: Notebook) => {
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

  const filteredNotebooks = notebooks.filter(n =>
    n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (n.description && n.description.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
        <BookOpen className="w-16 h-16 text-gray-500 mb-4" />
        <h2 className="text-2xl font-bold text-white mb-2">Sign in to use Notebooks</h2>
        <p className="text-gray-400 mb-6">Create notebooks, upload sources, and chat with your documents.</p>
        <button
          onClick={() => router.push('/login')}
          className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Sign In
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <BookOpen className="w-8 h-8 text-blue-400" />
            Notebooks
          </h1>
          <p className="text-gray-400 mt-1">
            Create notebooks, upload sources, and chat with your documents using RAG
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-5 h-5" />
          New Notebook
        </button>
      </div>

      {/* Search */}
      <div className="relative mb-6">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search notebooks..."
          className="w-full pl-10 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
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
          <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
        </div>
      ) : filteredNotebooks.length === 0 ? (
        <div className="text-center py-12">
          <BookOpen className="w-16 h-16 text-gray-600 mx-auto mb-4" />
          <h3 className="text-xl text-gray-400 mb-2">
            {searchQuery ? 'No notebooks found' : 'No notebooks yet'}
          </h3>
          <p className="text-gray-500 mb-6">
            {searchQuery ? 'Try a different search term' : 'Create your first notebook to get started'}
          </p>
          {!searchQuery && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Plus className="w-5 h-5" />
              Create Notebook
            </button>
          )}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredNotebooks.map((notebook) => (
            <div
              key={notebook.id}
              onClick={() => router.push(`/notebooks/${notebook.id}`)}
              className="group p-6 bg-gray-800 border border-gray-700 rounded-xl hover:border-blue-500 transition-all cursor-pointer"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-600/20 rounded-lg">
                    <BookOpen className="w-6 h-6 text-blue-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-white group-hover:text-blue-400 transition-colors">
                      {notebook.title}
                    </h3>
                  </div>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => handleEditNotebook(e, notebook)}
                    className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={(e) => handleDeleteNotebook(e, notebook.id)}
                    className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {notebook.description && (
                <p className="text-gray-400 text-sm mb-4 line-clamp-2">
                  {notebook.description}
                </p>
              )}

              <div className="flex items-center gap-4 text-sm text-gray-500">
                <div className="flex items-center gap-1">
                  <FileText className="w-4 h-4" />
                  <span>{notebook.source_count} sources</span>
                </div>
                <div className="flex items-center gap-1">
                  <MessageSquare className="w-4 h-4" />
                  <span>{notebook.note_count} notes</span>
                </div>
              </div>

              <div className="flex items-center gap-1 mt-3 text-xs text-gray-500">
                <Clock className="w-3 h-3" />
                <span>Updated {new Date(notebook.updated_at).toLocaleDateString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {(showCreateModal || editingNotebook) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 w-full max-w-md">
            <h2 className="text-xl font-bold text-white mb-4">
              {editingNotebook ? 'Edit Notebook' : 'Create New Notebook'}
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Title</label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="My Research Notebook"
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Description (optional)</label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Add a description..."
                  rows={3}
                  className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
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
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {editingNotebook ? 'Save Changes' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
