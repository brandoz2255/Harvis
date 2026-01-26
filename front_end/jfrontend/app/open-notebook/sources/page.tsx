'use client'

import { useEffect, useState, useMemo } from 'react'
import { useNotebookStore, NotebookSource } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import {
  FileText,
  Globe,
  File,
  Headphones,
  Youtube,
  Image as ImageIcon,
  Search,
  RefreshCw,
  Loader2,
  Plus,
  Filter,
  Grid,
  List,
  CheckCircle,
  Clock,
  AlertCircle,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SourceCard, SourceCardCompact } from '@/components/notebook/SourceCard'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { useCreateDialogsStore } from '@/stores/openNotebookUiStore'

// Source type icons mapping
const SOURCE_TYPE_ICONS: Record<string, React.ElementType> = {
  pdf: File,
  text: FileText,
  url: Globe,
  markdown: FileText,
  doc: File,
  transcript: FileText,
  audio: Headphones,
  youtube: Youtube,
  image: ImageIcon,
}

// Status filter options
const STATUS_FILTERS = [
  { value: 'all', label: 'All', icon: null },
  { value: 'ready', label: 'Ready', icon: CheckCircle },
  { value: 'processing', label: 'Processing', icon: Clock },
  { value: 'error', label: 'Failed', icon: AlertCircle },
]

export default function OpenNotebookSourcesPage() {
  const { user, isLoading: authLoading } = useUser()
  const { openSourceDialog } = useCreateDialogsStore()
  const {
    sources,
    fetchSources,
    deleteSource,
    isOpenNotebookAvailable,
    checkServiceHealth,
  } = useNotebookStore()

  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [deleteConfirmSource, setDeleteConfirmSource] = useState<string | null>(null)

  useEffect(() => {
    checkServiceHealth()
  }, [checkServiceHealth])

  useEffect(() => {
    if (!authLoading && user) {
      loadSources()
    }
  }, [authLoading, user])

  const loadSources = async () => {
    setIsLoading(true)
    await fetchSources()
    setIsLoading(false)
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchSources()
    setIsRefreshing(false)
  }

  const handleDeleteSource = async () => {
    if (!deleteConfirmSource) return
    await deleteSource(deleteConfirmSource)
    setDeleteConfirmSource(null)
  }

  // Get unique types for filter
  const uniqueTypes = useMemo(() => {
    const types = new Set(sources.map(s => s.type))
    return Array.from(types).sort()
  }, [sources])

  // Filter sources
  const filteredSources = useMemo(() => {
    return sources.filter(source => {
      // Search filter
      const matchesSearch = !searchQuery ||
        (source.title?.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (source.original_filename?.toLowerCase().includes(searchQuery.toLowerCase()))

      // Status filter
      const matchesStatus = statusFilter === 'all' || source.status === statusFilter

      // Type filter
      const matchesType = typeFilter === 'all' || source.type === typeFilter

      return matchesSearch && matchesStatus && matchesType
    })
  }, [sources, searchQuery, statusFilter, typeFilter])

  // Group by status for stats
  const statusStats = useMemo(() => {
    return {
      total: sources.length,
      ready: sources.filter(s => s.status === 'ready').length,
      processing: sources.filter(s => s.status === 'processing').length,
      error: sources.filter(s => s.status === 'error').length,
    }
  }, [sources])

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
          <FileText className="w-10 h-10 text-primary" />
        </div>
        <h2 className="text-3xl font-bold mb-3">Sources</h2>
        <p className="text-muted-foreground mb-8 max-w-md">
          Manage all your sources in one place. Upload files, add URLs, and import content.
        </p>
        <Button onClick={() => window.location.href = '/login'}>
          Sign In to Get Started
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
              <FileText className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">Sources</h1>
              <p className="text-sm text-muted-foreground">
                {statusStats.total} sources ({statusStats.ready} ready)
              </p>
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
            <Button onClick={() => openSourceDialog()}>
              <Plus className="w-4 h-4 mr-2" />
              Add Source
            </Button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-[300px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search sources..."
              className="w-full pl-9 pr-4 py-2 bg-muted border border-border rounded-lg placeholder-muted-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
            {STATUS_FILTERS.map(filter => (
              <button
                key={filter.value}
                onClick={() => setStatusFilter(filter.value)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                  statusFilter === filter.value
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>

          {/* Type Filter */}
          {uniqueTypes.length > 1 && (
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="px-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="all">All Types</option>
              {uniqueTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          )}

          {/* View Toggle */}
          <div className="flex items-center gap-1 p-1 bg-muted rounded-lg ml-auto">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded-md transition-colors ${
                viewMode === 'grid'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Grid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded-md transition-colors ${
                viewMode === 'list'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Sources List */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        ) : filteredSources.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
              <FileText className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-xl mb-2">
              {searchQuery || statusFilter !== 'all' || typeFilter !== 'all'
                ? 'No sources found'
                : 'No sources yet'}
            </h3>
            <p className="text-muted-foreground mb-8 max-w-md mx-auto">
              {searchQuery || statusFilter !== 'all' || typeFilter !== 'all'
                ? 'Try adjusting your filters'
                : 'Add your first source to get started. You can upload files, add URLs, or import content.'}
            </p>
            {!searchQuery && statusFilter === 'all' && typeFilter === 'all' && (
              <Button onClick={() => openSourceDialog()}>
                <Plus className="w-5 h-5 mr-2" />
                Add Source
              </Button>
            )}
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredSources.map((source) => (
              <SourceCard
                key={source.id}
                source={source}
                showContextToggle={false}
                onDelete={() => setDeleteConfirmSource(source.id)}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSources.map((source) => (
              <SourceCardCompact
                key={source.id}
                source={source}
                onClick={() => {}}
              />
            ))}
          </div>
        )}

        {/* Delete Confirmation Dialog */}
        <ConfirmDialog
          open={!!deleteConfirmSource}
          onOpenChange={(open) => !open && setDeleteConfirmSource(null)}
          title="Delete Source"
          description="Are you sure you want to delete this source? This action cannot be undone."
          confirmText="Delete"
          confirmVariant="destructive"
          onConfirm={handleDeleteSource}
        />
      </div>
    </div>
  )
}
