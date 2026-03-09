'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useNotebookStore, type NotebookSource } from '@/stores/notebookStore'
import OpenNotebookAPI from '@/lib/openNotebookApi'
import {
  ArrowLeft, FileText, Globe, Youtube, Clipboard, Image,
  Music, Loader2, Clock, Copy, Check,
  Hash, AlertCircle, CheckCircle2, Trash2, RotateCcw, X
} from 'lucide-react'

interface SourceDetailViewerProps {
  source: NotebookSource
  notebookId: string
  onBack: () => void
  onDelete?: (sourceId: string) => void
  compact?: boolean
  highlightText?: string
  onClearHighlight?: () => void
}

const SOURCE_ICON_MAP: Record<string, typeof FileText> = {
  pdf: FileText, url: Globe, youtube: Youtube,
  text: Clipboard, image: Image, audio: Music,
  markdown: FileText, doc: FileText, transcript: FileText,
}

export default function SourceDetailViewer({
  source: initialSource, notebookId, onBack, onDelete, compact = false,
  highlightText, onClearHighlight,
}: SourceDetailViewerProps) {
  const { refreshSourceStatus } = useNotebookStore()
  const [liveSource, setLiveSource] = useState(initialSource)
  const [content, setContent] = useState<string | null>(null)
  const [contentLength, setContentLength] = useState(0)
  const [isLoadingContent, setIsLoadingContent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isRetrying, setIsRetrying] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [copied, setCopied] = useState(false)
  const highlightRef = useRef<HTMLMarkElement>(null)
  const contentScrollRef = useRef<HTMLDivElement>(null)

  const SourceIcon = SOURCE_ICON_MAP[liveSource.type] || FileText
  const isProcessing = liveSource.status === 'processing' || liveSource.status === 'pending'

  const storeSource = useNotebookStore(s => s.sources.find(src => src.id === initialSource.id))
  useEffect(() => {
    if (storeSource) setLiveSource(storeSource)
  }, [storeSource])

  // SSE streaming while processing
  useEffect(() => {
    if (!isProcessing) return
    const cancel = OpenNotebookAPI.sources.streamStatus(notebookId, liveSource.id, (data) => {
      if (data.error) return
      const statusMap: Record<string, string> = { ready: 'ready', completed: 'ready', error: 'error', failed: 'error', processing: 'processing', pending: 'pending' }
      const mappedStatus = statusMap[data.status] || data.status
      setLiveSource(prev => ({
        ...prev,
        status: mappedStatus as any,
        chunk_count: data.chunk_count ?? prev.chunk_count,
        error_message: data.error_message || prev.error_message,
      }))
      if (data.done) {
        refreshSourceStatus(notebookId, liveSource.id)
        loadContent()
      }
    })
    return () => cancel()
  }, [isProcessing, notebookId, liveSource.id, refreshSourceStatus])

  // Load content when source is ready
  useEffect(() => {
    if (liveSource.status === 'ready' || liveSource.status === 'error') {
      loadContent()
    }
  }, [liveSource.status, liveSource.id])

  const loadContent = async () => {
    setIsLoadingContent(true)
    try {
      const data = await OpenNotebookAPI.sources.getContent(notebookId, liveSource.id)
      setContent(data.content)
      setContentLength(data.length)
    } catch {
      setContent(null)
    } finally {
      setIsLoadingContent(false)
    }
  }

  const handleRetry = async () => {
    setIsRetrying(true)
    try {
      await OpenNotebookAPI.sources.retry(notebookId, liveSource.id)
      setLiveSource(prev => ({ ...prev, status: 'processing', error_message: undefined }))
    } catch (err: any) {
      setError(err.message || 'Retry failed')
    } finally {
      setIsRetrying(false)
    }
  }

  const handleDelete = async () => {
    setIsDeleting(true)
    try {
      if (onDelete) onDelete(liveSource.id)
    } catch {
      setIsDeleting(false)
    }
  }

  const handleCopy = async () => {
    if (!content) return
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'ready': return 'text-green-400'
      case 'processing': return 'text-yellow-400'
      case 'error': return 'text-destructive'
      default: return 'text-muted-foreground'
    }
  }

  useEffect(() => {
    if (highlightText && highlightRef.current) {
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 200)
    }
  }, [highlightText, content])

  const renderHighlightedContent = useCallback((text: string) => {
    if (!highlightText) return text

    const searchText = highlightText.replace(/\.{3}$/, '').trim()
    if (!searchText || searchText.length < 10) return text

    const idx = text.toLowerCase().indexOf(searchText.toLowerCase())
    if (idx === -1) {
      const words = searchText.split(/\s+/).filter(w => w.length > 4)
      if (words.length >= 2) {
        const fuzzyPattern = words.slice(0, 5).join('|')
        const regex = new RegExp(`(${fuzzyPattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
        const parts = text.split(regex)
        if (parts.length > 1) {
          return (
            <>
              {parts.map((part, i) =>
                regex.test(part) ? (
                  <mark key={i} ref={i === 1 ? highlightRef : undefined}
                    className="bg-yellow-400/30 text-foreground rounded px-0.5">{part}</mark>
                ) : part
              )}
            </>
          )
        }
      }
      return text
    }

    const before = text.slice(0, idx)
    const match = text.slice(idx, idx + searchText.length)
    const after = text.slice(idx + searchText.length)

    return (
      <>
        {before}
        <mark ref={highlightRef} className="bg-yellow-400/30 text-foreground rounded px-0.5">{match}</mark>
        {after}
      </>
    )
  }, [highlightText])

  const StatusIcon = liveSource.status === 'ready' ? CheckCircle2
    : liveSource.status === 'processing' ? Loader2
    : liveSource.status === 'error' ? AlertCircle
    : Clock

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <button onClick={onBack}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary shrink-0">
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <SourceIcon className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="text-xs font-semibold text-foreground truncate flex-1">
          {liveSource.title || liveSource.original_filename || 'Untitled'}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          {content && (
            <button onClick={handleCopy}
              className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary"
              title="Copy content">
              {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
            </button>
          )}
          {(liveSource.status === 'error' || liveSource.status === 'processing') && (
            <button onClick={handleRetry} disabled={isRetrying}
              className="p-1 rounded text-muted-foreground hover:text-primary hover:bg-secondary disabled:opacity-50"
              title="Retry processing">
              {isRetrying ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
            </button>
          )}
          <button onClick={handleDelete} disabled={isDeleting}
            className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-secondary disabled:opacity-50"
            title="Delete source">
            {isDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Metadata */}
      <div className="px-3 py-2 space-y-1.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2 text-[10px]">
          <StatusIcon className={`w-3 h-3 ${statusColor(liveSource.status)} ${isProcessing ? 'animate-spin' : ''}`} />
          <span className={statusColor(liveSource.status)}>
            {liveSource.status === 'processing' ? 'Processing...' : liveSource.status}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">{liveSource.type}</span>
          {contentLength > 0 && (
            <>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{contentLength.toLocaleString()} chars</span>
            </>
          )}
        </div>

        {isProcessing && (
          <div className="space-y-1.5">
            <div className="flex-1 h-1 bg-secondary rounded-full overflow-hidden">
              <div className="h-full bg-yellow-400 rounded-full animate-pulse" style={{ width: '60%' }} />
            </div>
            <p className="text-[9px] text-muted-foreground animate-pulse">
              Extracting content and generating embeddings...
            </p>
          </div>
        )}

        {liveSource.chunk_count > 0 && (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <Hash className="w-3 h-3" />
            <span>{liveSource.chunk_count} chunks indexed</span>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground">
          Added {new Date(liveSource.created_at).toLocaleDateString()}
        </p>

        {liveSource.error_message && (
          <div className="flex items-start gap-1 text-[10px] text-destructive">
            <AlertCircle className="w-3 h-3 shrink-0 mt-0.5" />
            <span>{liveSource.error_message}</span>
          </div>
        )}
      </div>

      {/* Transcript / Content */}
      <div ref={contentScrollRef} className="flex-1 overflow-y-auto">
        {isLoadingContent && (
          <div className="flex items-center justify-center gap-2 p-6 text-xs text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading content...
          </div>
        )}

        {!isLoadingContent && content && (
          <div className="p-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-semibold text-foreground uppercase tracking-wider">
                Extracted Content
              </p>
              <div className="flex items-center gap-2">
                {highlightText && onClearHighlight && (
                  <button
                    onClick={onClearHighlight}
                    className="flex items-center gap-1 px-1.5 py-0.5 text-[9px] text-yellow-400 bg-yellow-400/10 border border-yellow-400/30 rounded hover:bg-yellow-400/20 transition-colors"
                  >
                    <X className="w-2.5 h-2.5" />
                    Clear highlight
                  </button>
                )}
                <span className="text-[9px] text-muted-foreground">
                  {contentLength.toLocaleString()} characters
                </span>
              </div>
            </div>
            <div className="p-3 bg-secondary/30 border border-border/50 rounded-lg text-xs text-foreground/90 whitespace-pre-wrap leading-relaxed font-mono max-h-none overflow-visible">
              {renderHighlightedContent(content)}
            </div>
          </div>
        )}

        {!isLoadingContent && !content && !isProcessing && (
          <div className="p-3 text-center">
            <p className="text-xs text-muted-foreground">
              {liveSource.status === 'error'
                ? 'Content extraction failed. Try retrying with the button above.'
                : 'No content extracted yet.'}
            </p>
          </div>
        )}

        {error && (
          <div className="mx-3 mb-3 p-2 bg-destructive/10 border border-destructive/30 rounded text-xs text-destructive">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
