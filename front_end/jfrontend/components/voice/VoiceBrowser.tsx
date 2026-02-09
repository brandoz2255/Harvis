'use client'

import { useEffect, useCallback, useMemo, useRef, useState } from 'react'
import {
  Search,
  Loader2,
  Download,
  Play,
  Pause,
  Star,
  Filter,
  X,
  ExternalLink,
  Zap,
  AlertCircle,
  Check
} from 'lucide-react'
import { useVoiceStore } from '@/stores/voiceStore'

interface CatalogVoice {
  id: string
  name: string
  slug: string
  category: string
  description?: string
  download_url?: string
  preview_url?: string
  file_size?: number
  downloads?: number
  rating?: number
  tags: string[]
  created_at?: string
}

interface VoiceBrowserProps {
  embedded?: boolean
  isOpen?: boolean
  onClose?: () => void
  onImportComplete?: () => void
  userId?: string
  maxHeightPx?: number
}

const CATEGORY_OPTIONS = [
  { value: '', label: 'All Categories' },
  { value: 'cartoon', label: 'Cartoon' },
  { value: 'tv_show', label: 'TV Shows' },
  { value: 'celebrity', label: 'Celebrity' },
  { value: 'character', label: 'Character' },
  { value: 'gaming', label: 'Gaming' },
  { value: 'anime', label: 'Anime' },
  { value: 'custom', label: 'Custom' },
]

const CATEGORY_COLORS: Record<string, string> = {
  cartoon: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  tv_show: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  celebrity: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  character: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  gaming: 'bg-green-500/20 text-green-400 border-green-500/30',
  anime: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  custom: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
}

export default function VoiceBrowser({ isOpen, onClose, onImportComplete, userId }: VoiceBrowserProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [voices, setVoices] = useState<CatalogVoice[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [importingSlug, setImportingSlug] = useState<string | null>(null)
  const [importProgress, setImportProgress] = useState<{ stage: string; progress: number } | null>(null)
  const [importedSlugs, setImportedSlugs] = useState<Set<string>>(new Set())
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const { fetchRvcVoices } = useVoiceStore()

  const embedded = (arguments[0] as VoiceBrowserProps)?.embedded ?? false
  const maxHeightPx = (arguments[0] as VoiceBrowserProps)?.maxHeightPx ?? 520

  const resolvedUserId = useMemo(() => {
    if (userId) return userId
    try {
      const token = typeof window !== 'undefined' ? window.localStorage.getItem('token') : null
      if (!token) return null
      const parts = token.split('.')
      if (parts.length < 2) return null
      const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
      const json = JSON.parse(atob(payload))
      return String(json.sub || json.user_id || '')
    } catch {
      return null
    }
  }, [userId])

  // Debounced search
  const searchVoices = useCallback(async (query: string, category: string, targetPage: number, append: boolean) => {
    if (append) {
      setIsLoadingMore(true)
    } else {
      setIsLoading(true)
    }
    setError(null)

    try {
      const params = new URLSearchParams()
      if (query) params.set('q', query)
      if (category) params.set('category', category)
      params.set('page', String(targetPage))

      const response = await fetch(`/api/tts/rvc/catalog/search?${params}`, {
        credentials: 'include'
      })

      if (!response.ok) {
        throw new Error('Failed to search voice catalog')
      }

      const data = await response.json()
      const models = (data.models || []) as CatalogVoice[]
      setHasMore(Boolean(data.has_more))
      setVoices(prev => (append ? [...prev, ...models] : models))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load voices')
      if (!append) setVoices([])
      setHasMore(false)
    } finally {
      setIsLoading(false)
      setIsLoadingMore(false)
    }
  }, [])

  // Load initial voices and on filter change (reset paging)
  useEffect(() => {
    if (embedded || isOpen) {
      setPage(1)
      setHasMore(true)
      const timer = setTimeout(() => {
        searchVoices(searchQuery, selectedCategory, 1, false)
      }, 300) // Debounce
      return () => clearTimeout(timer)
    }
  }, [embedded, isOpen, searchQuery, selectedCategory, searchVoices])

  // Infinite scroll: load next page when sentinel appears
  useEffect(() => {
    if (!sentinelRef.current) return
    if (!(embedded || isOpen)) return
    if (!hasMore) return
    if (isLoading || isLoadingMore) return

    const el = sentinelRef.current
    const obs = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return
        if (!hasMore) return
        if (isLoading || isLoadingMore) return
        setPage((p) => p + 1)
      },
      { root: null, rootMargin: '200px', threshold: 0.01 }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [embedded, isOpen, hasMore, isLoading, isLoadingMore])

  // Fetch more when page increments
  useEffect(() => {
    if (page === 1) return
    if (!(embedded || isOpen)) return
    if (!hasMore) return
    searchVoices(searchQuery, selectedCategory, page, true)
  }, [page, embedded, isOpen, hasMore, searchQuery, selectedCategory, searchVoices])

  // Handle import
  const handleImport = async (voice: CatalogVoice) => {
    if (!voice.download_url) {
      setError('This voice does not have a download URL')
      return
    }
    if (!resolvedUserId) {
      setError('Unable to determine user id for import (missing auth token)')
      return
    }

    setImportingSlug(voice.slug)
    setImportProgress({ stage: 'starting', progress: 0 })

    try {
      const response = await fetch('/api/tts/rvc/voices/import-url', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: voice.download_url,
          name: voice.name,
          slug: voice.slug,
          category: voice.category,
          description: voice.description || '',
          user_id: resolvedUserId
        })
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || 'Import failed')
      }

      const result = await response.json()

      if (result.success) {
        setImportedSlugs(prev => new Set([...prev, voice.slug]))
        // Refresh the RVC voices list
        await fetchRvcVoices()
        if (onImportComplete) {
          onImportComplete()
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import voice')
    } finally {
      setImportingSlug(null)
      setImportProgress(null)
    }
  }

  // Handle preview playback (if preview URL available)
  const handlePreview = (voice: CatalogVoice) => {
    if (!voice.preview_url) return

    if (playingId === voice.id) {
      setPlayingId(null)
      return
    }

    setPlayingId(voice.id)
    const audio = new Audio(voice.preview_url)
    audio.onended = () => setPlayingId(null)
    audio.onerror = () => setPlayingId(null)
    audio.play().catch(() => setPlayingId(null))
  }

  // Format file size
  const formatSize = (bytes?: number): string => {
    if (!bytes) return ''
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (!embedded && !isOpen) return null

  const content = (
    <>
      {/* Search & Filters */}
      <div className={embedded ? 'space-y-3' : 'p-4 border-b border-white/10 space-y-3'}>
        {/* Search input */}
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search voices... (e.g., Spongebob, Miku)"
            className="w-full pl-11 pr-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-white/30 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        {/* Category filter (best-effort) */}
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-4 h-4 text-white/40" />
          {CATEGORY_OPTIONS.map(cat => (
            <button
              key={cat.value}
              onClick={() => setSelectedCategory(cat.value)}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                selectedCategory === cat.value
                  ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/50'
                  : 'bg-white/5 text-white/60 border-white/10 hover:border-white/30'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className={embedded ? 'mt-3 flex items-center gap-3 p-3 rounded-xl bg-red-500/10 border border-red-500/30' : 'mx-4 mt-4 flex items-center gap-3 p-3 rounded-xl bg-red-500/10 border border-red-500/30'}>
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
          <p className="text-sm text-red-400 flex-1">{error}</p>
          <button onClick={() => setError(null)} className="p-1 hover:bg-red-500/20 rounded">
            <X className="w-4 h-4 text-red-400" />
          </button>
        </div>
      )}

      {/* Voice list */}
      <div
        className={embedded ? 'mt-3 overflow-y-auto pr-1' : 'flex-1 overflow-y-auto p-4'}
        style={embedded ? { maxHeight: maxHeightPx } : undefined}
      >
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
            <span className="ml-3 text-white/60">Loading top voices...</span>
          </div>
        ) : voices.length === 0 ? (
          <div className="text-center py-12">
            <Search className="w-12 h-12 mx-auto text-white/20 mb-4" />
            <h3 className="text-lg font-medium text-white/70 mb-2">No voices found</h3>
            <p className="text-sm text-white/50">
              Try a different search term
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {voices.map(voice => {
              const isImporting = importingSlug === voice.slug
              const isImported = importedSlugs.has(voice.slug)
              const categoryColor = CATEGORY_COLORS[voice.category] || CATEGORY_COLORS.custom

              return (
                <div
                  key={voice.id}
                  className="group p-4 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 transition-all"
                >
                  <div className="flex items-start gap-4">
                    {/* Voice info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium text-white truncate">{voice.name}</h4>
                        <span className={`px-2 py-0.5 text-xs rounded-full border ${categoryColor}`}>
                          {voice.category?.replace('_', ' ') || 'custom'}
                        </span>
                        <a
                          href={`https://voice-models.com/model/${voice.id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-auto p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-all"
                          title="Open on voice-models.com"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      </div>

                      {voice.description && (
                        <p className="text-sm text-white/60 line-clamp-1 mb-2">
                          {voice.description}
                        </p>
                      )}

                      <div className="flex items-center gap-4 text-xs text-white/40">
                        {typeof voice.downloads === 'number' && voice.downloads > 0 && (
                          <span className="flex items-center gap-1">
                            <Download className="w-3 h-3" />
                            {voice.downloads.toLocaleString()}
                          </span>
                        )}
                        {typeof voice.rating === 'number' && voice.rating > 0 && (
                          <span className="flex items-center gap-1">
                            <Star className="w-3 h-3" />
                            {voice.rating.toFixed(1)}
                          </span>
                        )}
                        {voice.file_size && (
                          <span>{formatSize(voice.file_size)}</span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      {/* Preview button */}
                      {voice.preview_url && (
                        <button
                          onClick={() => handlePreview(voice)}
                          className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white/60 hover:text-white transition-all"
                        >
                          {playingId === voice.id ? (
                            <Pause className="w-4 h-4" />
                          ) : (
                            <Play className="w-4 h-4" />
                          )}
                        </button>
                      )}

                      {/* Import button */}
                      <button
                        onClick={() => handleImport(voice)}
                        disabled={isImporting || isImported || !voice.download_url}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all ${
                          isImported
                            ? 'bg-green-500/20 text-green-400 cursor-default'
                            : isImporting
                            ? 'bg-cyan-500/20 text-cyan-400 cursor-wait'
                            : !voice.download_url
                            ? 'bg-white/5 text-white/30 cursor-not-allowed'
                            : 'bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30'
                        }`}
                      >
                        {isImported ? (
                          <>
                            <Check className="w-4 h-4" />
                            Imported
                          </>
                        ) : isImporting ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Importing...
                          </>
                        ) : !voice.download_url ? (
                          <>
                            <ExternalLink className="w-4 h-4" />
                            No URL
                          </>
                        ) : (
                          <>
                            <Download className="w-4 h-4" />
                            Import
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Import progress */}
                  {isImporting && importProgress && (
                    <div className="mt-3 pt-3 border-t border-white/10">
                      <div className="flex items-center justify-between text-xs text-white/50 mb-1">
                        <span className="capitalize">{importProgress.stage}...</span>
                        <span>{importProgress.progress}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all"
                          style={{ width: `${importProgress.progress}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              )
            })}

            {/* Infinite scroll sentinel */}
            <div ref={sentinelRef} />
            {isLoadingMore && (
              <div className="flex items-center justify-center py-6 text-white/60 text-sm">
                <Loader2 className="w-4 h-4 animate-spin text-cyan-400 mr-2" />
                Loading more...
              </div>
            )}
            {!hasMore && voices.length > 0 && (
              <div className="text-center py-6 text-xs text-white/40">
                End of results
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )

  if (embedded) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/5 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-cyan-400" />
            <p className="text-sm font-medium text-white/80">voice-models.com Top</p>
          </div>
          <p className="text-xs text-white/40">Scroll to load more</p>
        </div>
        {content}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0a0a0a] rounded-2xl border border-white/10 w-full max-w-4xl max-h-[90vh] shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-cyan-500/30 to-blue-500/30">
              <Zap className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Browse Voice Models</h2>
              <p className="text-xs text-white/50">Import character voices from voice-models.com</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-white/60" />
          </button>
        </div>
        {content}

        {/* Footer */}
        <div className="p-4 border-t border-white/10 flex items-center justify-between">
          <p className="text-xs text-white/40">
            Voices are stored in your personal library
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}

