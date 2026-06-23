'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams, useRouter, useSearchParams, usePathname } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { notebooksApi } from '@/lib/api/notebooks'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { AppShell } from '@/components/layout/AppShell'
import { SourcesColumn } from '../components/SourcesColumn'
import { NotesColumn } from '../components/NotesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { LibraryColumn } from '../components/LibraryColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useIsDesktop } from '@/lib/hooks/use-media-query'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { SourceDetailContent } from '@/components/source/SourceDetailContent'
import { FileText, StickyNote, MessageSquare, ArrowLeft } from 'lucide-react'

export type ContextMode = 'off' | 'insights' | 'full'

export interface ContextSelections {
  sources: Record<string, ContextMode>
  notes: Record<string, ContextMode>
}

export default function NotebookPage() {
  const { t } = useTranslation()
  const params = useParams()

  // Ensure the notebook ID is properly decoded from URL
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)

  // Detect desktop to avoid double-mounting ChatColumn
  const isDesktop = useIsDesktop()

  // Mobile tab state (Sources, Notes, or Chat)
  const [mobileActiveTab, setMobileActiveTab] = useState<'sources' | 'notes' | 'chat'>('chat')

  // A source opened inline (takes over the left column + expands it for reading) instead
  // of an overlay modal. URL-backed (?source=&highlight=&claim=) so it survives refresh /
  // back / deep-link, AND so chat-citation clicks reuse SourceDetailContent's highlight/
  // claim scroll-to-passage (it reads those params from useSearchParams).
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const openSourceId = searchParams.get('source')
  const openSourcePrefixed = openSourceId
    ? openSourceId.includes(':')
      ? openSourceId
      : `source:${openSourceId}`
    : null
  const openSource = (id: string | null, highlight?: string, claim?: string) => {
    const params = new URLSearchParams(Array.from(searchParams.entries()))
    if (id) {
      params.set('source', id)
      if (highlight) params.set('highlight', highlight)
      else params.delete('highlight')
      if (claim) params.set('claim', claim)
      else params.delete('claim')
    } else {
      params.delete('source')
      params.delete('highlight')
      params.delete('claim')
    }
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  // Auto-naming: no name prompt on create. The AI generates a BROAD-SCOPE title + emoji
  // + a 3-5 sentence synopsis (stored in description) from the notebook's sources, and
  // RE-evaluates as more sources are added so the name/scope broadens to cover them all
  // — until the user renames it manually.
  //
  // Loop guard: autoname updates the name → notebook query invalidates → effect re-runs.
  // We only (re)name when the source count has GROWN since the last naming. State lives
  // in localStorage (keyed by notebook id) so it survives remounts AND lets us detect a
  // manual rename (current name ≠ last auto-title ⇒ stop).
  const queryClient = useQueryClient()
  const autonameBusyRef = useRef(false)
  useEffect(() => {
    if (autonameBusyRef.current) return
    if (!notebook || !sources || sources.length === 0) return
    if (typeof window === 'undefined') return

    const lsKey = `onb:autoname:${notebookId}`
    let state: { count: number; title: string } | null = null
    try {
      const raw = window.localStorage.getItem(lsKey)
      if (raw) state = JSON.parse(raw)
    } catch {
      state = null
    }

    const name = (notebook.name || '').trim()
    const lower = name.toLowerCase()
    const untitled =
      lower === '' || lower === 'new notebook' || lower === 'untitled' || lower === 'untitled notebook'

    // User manually renamed (name no longer matches our last auto-title) → stop.
    if (state && state.title && name !== state.title) return
    // Existing notebook we've never auto-named that already has a real name → leave it.
    if (!untitled && !state) return
    // Only (re)name when the source count has grown since the last naming.
    const namedCount = state?.count ?? 0
    if (sources.length <= namedCount) return

    autonameBusyRef.current = true
    const targetCount = sources.length
    notebooksApi
      .autoname(notebookId)
      .then((res) => {
        try {
          window.localStorage.setItem(
            lsKey,
            JSON.stringify({ count: targetCount, title: res?.title ?? name })
          )
        } catch {
          /* ignore localStorage quota errors */
        }
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebook(notebookId) })
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.notebooks })
      })
      .catch(() => {
        /* leave the stored count unchanged so a later source add retries */
      })
      .finally(() => {
        autonameBusyRef.current = false
      })
  }, [notebook, sources, notebookId, queryClient])

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections(prev => {
        const newSourceSelections = { ...prev.sources }
        sources.forEach(source => {
          const currentMode = newSourceSelections[source.id]
          const hasInsights = source.insights_count > 0

          if (currentMode === undefined) {
            // Initial setup - default based on insights availability
            newSourceSelections[source.id] = hasInsights ? 'insights' : 'full'
          } else if (currentMode === 'full' && hasInsights) {
            // Source gained insights while in 'full' mode - auto-switch to 'insights'
            newSourceSelections[source.id] = 'insights'
          }
        })
        return { ...prev, sources: newSourceSelections }
      })
    }
  }, [sources])

  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections(prev => {
        const newNoteSelections = { ...prev.notes }
        notes.forEach(note => {
          // Only set default if not already set
          if (!(note.id in newNoteSelections)) {
            // Notes default to 'full'
            newNoteSelections[note.id] = 'full'
          }
        })
        return { ...prev, notes: newNoteSelections }
      })
    }
  }, [notes])

  // Handler to update context selection
  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections(prev => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode
      }
    }))
  }

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!notebook) {
    return (
      <AppShell>
        <div className="p-6">
          <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
          <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex flex-col flex-1 min-h-0">
        {/* Header band removed — the chat overview card already shows the notebook's
            emoji, title, date, source count, and synopsis, so a top band here just
            repeated the description. Archive/Delete live on each hub card's ⋯ menu. */}
        <div className="flex-1 p-6 overflow-x-auto flex flex-col">
          {/* Mobile: Tabbed interface - only render on mobile to avoid double-mounting */}
          {!isDesktop && (
            <>
              <div className="lg:hidden mb-4">
                <Tabs value={mobileActiveTab} onValueChange={(value) => setMobileActiveTab(value as 'sources' | 'notes' | 'chat')}>
                  <TabsList className="grid w-full grid-cols-3">
                    <TabsTrigger value="sources" className="gap-2">
                      <FileText className="h-4 w-4" />
                      {t('navigation.sources')}
                    </TabsTrigger>
                    <TabsTrigger value="notes" className="gap-2">
                      <StickyNote className="h-4 w-4" />
                      {t('common.notes')}
                    </TabsTrigger>
                    <TabsTrigger value="chat" className="gap-2">
                      <MessageSquare className="h-4 w-4" />
                      {t('common.chat')}
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              {/* Mobile: Show only active tab */}
              <div className="flex-1 overflow-hidden lg:hidden">
                {mobileActiveTab === 'sources' && (
                  <SourcesColumn
                    sources={sources}
                    isLoading={sourcesLoading}
                    notebookId={notebookId}
                    notebookName={notebook?.name}
                    onRefresh={refetchSources}
                    contextSelections={contextSelections.sources}
                    onContextModeChange={(sourceId, mode) => handleContextModeChange(sourceId, mode, 'source')}
                    hasNextPage={hasNextPage}
                    isFetchingNextPage={isFetchingNextPage}
                    fetchNextPage={fetchNextPage}
                  />
                )}
                {mobileActiveTab === 'notes' && (
                  <NotesColumn
                    notes={notes}
                    isLoading={notesLoading}
                    notebookId={notebookId}
                    contextSelections={contextSelections.notes}
                    onContextModeChange={(noteId, mode) => handleContextModeChange(noteId, mode, 'note')}
                  />
                )}
                {mobileActiveTab === 'chat' && (
                  <ChatColumn
                    notebookId={notebookId}
                    contextSelections={contextSelections}
                    sources={sources}
                    sourcesLoading={sourcesLoading}
                    notebook={notebook}
                  />
                )}
              </div>
            </>
          )}

          {/* Desktop: merged Library (Sources + Notes) on the left, wide Chat center */}
          <div className="hidden lg:flex h-full min-h-0 gap-6 flex-row">
            {/* Left: Library (Sources + Notes). When a source is opened it takes over this
                side and the column expands wider (flex-1) for comfortable reading. */}
            <div className={openSourcePrefixed ? 'flex-1 min-w-0 min-h-0' : 'flex-none w-96 min-h-0'}>
              {openSourcePrefixed ? (
                <div className="h-full min-h-0 flex flex-col rounded-xl border border-border bg-card overflow-hidden">
                  <div className="flex-shrink-0 flex items-center border-b border-border px-2 py-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="gap-1.5"
                      onClick={() => openSource(null)}
                    >
                      <ArrowLeft className="h-4 w-4" />
                      {t('navigation.sources')}
                    </Button>
                  </div>
                  <div className="flex-1 overflow-y-auto min-h-0 p-4">
                    <SourceDetailContent
                      key={openSourcePrefixed}
                      sourceId={openSourcePrefixed}
                      onClose={() => openSource(null)}
                    />
                  </div>
                </div>
              ) : (
                <LibraryColumn
                  sources={sources}
                  sourcesLoading={sourcesLoading}
                  notebookId={notebookId}
                  notebookName={notebook?.name}
                  onRefreshSources={refetchSources}
                  hasNextPage={hasNextPage}
                  isFetchingNextPage={isFetchingNextPage}
                  fetchNextPage={fetchNextPage}
                  notes={notes}
                  notesLoading={notesLoading}
                  contextSelections={contextSelections}
                  onContextModeChange={handleContextModeChange}
                  onOpenSource={(id) => openSource(id)}
                />
              )}
            </div>

            {/* Chat — wide center */}
            <div className="flex-1 min-w-0 lg:pr-6 lg:-mr-6">
              <ChatColumn
                notebookId={notebookId}
                contextSelections={contextSelections}
                sources={sources}
                sourcesLoading={sourcesLoading}
                onOpenSource={(id, highlight, claim) => openSource(id, highlight, claim)}
                notebook={notebook}
              />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
