'use client'

import { useState, useRef } from 'react'
import { NotebookSource } from '@/stores/notebookStore'
import SourceCard from './SourceCard'
import {
  Plus,
  Upload,
  Link,
  FileText,
  Globe,
  Youtube,
  Clipboard,
  Search,
  Grid,
  List,
  Filter,
  SortAsc,
  Loader2,
  X,
  Sparkles,
  BookOpen,
  Copy
} from 'lucide-react'

interface SourcesViewProps {
  sources: NotebookSource[]
  isLoading: boolean
  selectedSources: Set<string>
  onSourceSelect: (sourceId: string) => void
  onSourceDelete: (sourceId: string) => void
  onSourceTransform: (source: NotebookSource) => void
  onAddSource: () => void
}

export default function SourcesView({
  sources,
  isLoading,
  selectedSources,
  onSourceSelect,
  onSourceDelete,
  onSourceTransform,
  onAddSource,
}: SourcesViewProps) {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<string>('all')
  const [sortBy, setSortBy] = useState<'date' | 'name' | 'type'>('date')
  const [showFilterMenu, setShowFilterMenu] = useState(false)
  const [showSortMenu, setShowSortMenu] = useState(false)

  // Filter and sort sources
  const filteredSources = sources
    .filter(source => {
      const matchesSearch = (source.title || source.original_filename || '')
        .toLowerCase()
        .includes(searchQuery.toLowerCase())
      const matchesType = filterType === 'all' || source.type === filterType
      return matchesSearch && matchesType
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return (a.title || a.original_filename || '').localeCompare(b.title || b.original_filename || '')
        case 'type':
          return a.type.localeCompare(b.type)
        case 'date':
        default:
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      }
    })

  // Get unique source types for filter
  const sourceTypes = Array.from(new Set(sources.map(s => s.type)))

  const readyCount = sources.filter(s => s.status === 'ready').length
  const processingCount = sources.filter(s => s.status === 'processing' || s.status === 'pending').length

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[#0a0a0a]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-semibold text-white">Sources</h2>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <span className="px-2 py-0.5 bg-green-500/10 text-green-400 rounded">
              {readyCount} ready
            </span>
            {processingCount > 0 && (
              <span className="px-2 py-0.5 bg-blue-500/10 text-blue-400 rounded flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                {processingCount} processing
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search sources..."
              className="w-64 pl-9 pr-3 py-2 text-sm bg-[#111111] border border-gray-800 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Filter */}
          <div className="relative">
            <button
              onClick={() => setShowFilterMenu(!showFilterMenu)}
              className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors ${
                filterType !== 'all'
                  ? 'bg-blue-500/10 text-blue-400 border border-blue-500/30'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800 border border-gray-800'
              }`}
            >
              <Filter className="w-4 h-4" />
              Filter
            </button>

            {showFilterMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowFilterMenu(false)} />
                <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[140px]">
                  <button
                    onClick={() => {
                      setFilterType('all')
                      setShowFilterMenu(false)
                    }}
                    className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 ${
                      filterType === 'all' ? 'text-blue-400' : 'text-gray-300'
                    }`}
                  >
                    All types
                  </button>
                  {sourceTypes.map(type => (
                    <button
                      key={type}
                      onClick={() => {
                        setFilterType(type)
                        setShowFilterMenu(false)
                      }}
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 capitalize ${
                        filterType === type ? 'text-blue-400' : 'text-gray-300'
                      }`}
                    >
                      {type}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Sort */}
          <div className="relative">
            <button
              onClick={() => setShowSortMenu(!showSortMenu)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors border border-gray-800"
            >
              <SortAsc className="w-4 h-4" />
              Sort
            </button>

            {showSortMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowSortMenu(false)} />
                <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-gray-800 rounded-lg shadow-xl py-1 z-20 min-w-[140px]">
                  {[
                    { id: 'date', label: 'Date added' },
                    { id: 'name', label: 'Name' },
                    { id: 'type', label: 'Type' },
                  ].map(option => (
                    <button
                      key={option.id}
                      onClick={() => {
                        setSortBy(option.id as 'date' | 'name' | 'type')
                        setShowSortMenu(false)
                      }}
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 ${
                        sortBy === option.id ? 'text-blue-400' : 'text-gray-300'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* View Toggle */}
          <div className="flex items-center bg-[#111111] border border-gray-800 rounded-lg p-0.5">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded ${
                viewMode === 'grid'
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Grid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded ${
                viewMode === 'list'
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <List className="w-4 h-4" />
            </button>
          </div>

          {/* Add Source Button */}
          <button
            onClick={onAddSource}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-lg hover:opacity-90 transition-opacity text-sm font-medium"
          >
            <Plus className="w-4 h-4" />
            Add Source
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
          </div>
        ) : filteredSources.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            {sources.length === 0 ? (
              <>
                <div className="w-20 h-20 mb-6 rounded-2xl bg-gradient-to-br from-orange-400/20 via-pink-500/20 to-purple-600/20 flex items-center justify-center">
                  <FileText className="w-10 h-10 text-gray-500" />
                </div>
                <h3 className="text-lg font-medium text-white mb-2">No sources yet</h3>
                <p className="text-gray-500 mb-6 max-w-md">
                  Add sources to your notebook to start chatting with your documents.
                  Upload PDFs, paste URLs, or add text directly.
                </p>
                <button
                  onClick={onAddSource}
                  className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-orange-500 via-pink-500 to-purple-600 text-white rounded-xl hover:opacity-90 transition-opacity font-medium"
                >
                  <Plus className="w-5 h-5" />
                  Add Your First Source
                </button>
              </>
            ) : (
              <>
                <Search className="w-12 h-12 text-gray-500 mb-4" />
                <h3 className="text-lg font-medium text-white mb-2">No matches found</h3>
                <p className="text-gray-500">
                  Try adjusting your search or filters
                </p>
              </>
            )}
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {filteredSources.map(source => (
              <SourceCard
                key={source.id}
                source={source}
                isSelected={selectedSources.has(source.id)}
                viewMode="grid"
                onSelect={() => onSourceSelect(source.id)}
                onDelete={() => onSourceDelete(source.id)}
                onTransform={() => onSourceTransform(source)}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSources.map(source => (
              <SourceCard
                key={source.id}
                source={source}
                isSelected={selectedSources.has(source.id)}
                viewMode="list"
                onSelect={() => onSourceSelect(source.id)}
                onDelete={() => onSourceDelete(source.id)}
                onTransform={() => onSourceTransform(source)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Selection Actions Bar */}
      {selectedSources.size > 0 && (
        <div className="border-t border-gray-800 px-6 py-3 bg-[#111111] flex items-center justify-between">
          <span className="text-sm text-gray-400">
            {selectedSources.size} source{selectedSources.size !== 1 ? 's' : ''} selected
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                selectedSources.forEach(id => onSourceDelete(id))
              }}
              className="px-3 py-1.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
            >
              Delete selected
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
