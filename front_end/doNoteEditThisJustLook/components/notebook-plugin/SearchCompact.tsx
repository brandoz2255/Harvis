'use client'

import { useState } from 'react'
import { Search, Loader2, FileText, BookOpen } from 'lucide-react'
import OpenNotebookAPI from '@/lib/openNotebookApi'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'
import { useNotebookStore } from '@/stores/notebookStore'

interface SearchResult {
  id: string
  type: 'source' | 'note' | 'notebook'
  title: string
  snippet: string
  notebook_id?: string
  score?: number
}

export default function SearchCompact() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const { selectNotebook, setActiveTab } = useNotebookPluginStore()

  const handleSearch = async () => {
    if (!query.trim()) return
    setIsSearching(true)
    try {
      const resp = await OpenNotebookAPI.search.search(query.trim())
      // Map response to our format
      const mapped: SearchResult[] = (resp.results || []).map((r: any) => ({
        id: r.id || r.source_id || String(Math.random()),
        type: r.type || 'source',
        title: r.title || r.source_title || 'Untitled',
        snippet: r.content?.substring(0, 150) || r.snippet || '',
        notebook_id: r.notebook_id,
        score: r.score,
      }))
      setResults(mapped)
    } catch (err) {
      console.error('Search failed:', err)
      setResults([])
    } finally {
      setIsSearching(false)
    }
  }

  const handleResultClick = (result: SearchResult) => {
    if (result.notebook_id) {
      selectNotebook(result.notebook_id)
      useNotebookStore.getState().selectNotebook(result.notebook_id)
      setActiveTab('sources')
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search Input */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center gap-2 bg-secondary border border-border rounded-lg px-3 py-2">
          <Search className="w-4 h-4 text-muted-foreground shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search across notebooks..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          {isSearching && <Loader2 className="w-4 h-4 animate-spin text-primary shrink-0" />}
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto">
        {results.length === 0 && !isSearching ? (
          <div className="p-6 text-center">
            <Search className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">
              {query ? 'No results found' : 'Search across all your notebooks'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {results.map((result) => (
              <button
                key={result.id}
                onClick={() => handleResultClick(result)}
                className="w-full flex items-start gap-3 px-4 py-3 text-left
                           hover:bg-secondary/50 transition-colors"
              >
                {result.type === 'notebook' ? (
                  <BookOpen className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                ) : (
                  <FileText className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{result.title}</p>
                  {result.snippet && (
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{result.snippet}</p>
                  )}
                  {result.score !== undefined && (
                    <p className="text-[10px] text-muted-foreground/70 mt-0.5">
                      Relevance: {(result.score * 100).toFixed(0)}%
                    </p>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
