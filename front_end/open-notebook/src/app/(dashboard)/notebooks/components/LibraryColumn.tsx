'use client'

import { useState } from 'react'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileText, StickyNote } from 'lucide-react'
import { SourcesColumn } from './SourcesColumn'
import { NotesColumn } from './NotesColumn'
import type { SourceListResponse, NoteResponse } from '@/lib/types/api'
import type { ContextSelections, ContextMode } from '../[id]/page'
import { useTranslation } from '@/lib/hooks/use-translation'

interface LibraryColumnProps {
  sources?: SourceListResponse[]
  sourcesLoading: boolean
  notebookId: string
  notebookName?: string
  onRefreshSources?: () => void
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
  fetchNextPage?: () => void
  notes?: NoteResponse[]
  notesLoading: boolean
  contextSelections: ContextSelections
  onContextModeChange: (itemId: string, mode: ContextMode, type: 'source' | 'note') => void
  // When provided, clicking a source opens it inline (parent-controlled) instead of a modal.
  onOpenSource?: (sourceId: string) => void
}

/**
 * Merged left panel for the notebook detail page: Sources + Notes folded into a
 * single column with a tab toggle, so Chat can take the wide center. Reuses the
 * existing SourcesColumn / NotesColumn in `embedded` mode (no per-column collapse).
 */
export function LibraryColumn({
  sources,
  sourcesLoading,
  notebookId,
  notebookName,
  onRefreshSources,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  notes,
  notesLoading,
  contextSelections,
  onContextModeChange,
  onOpenSource,
}: LibraryColumnProps) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'sources' | 'notes'>('sources')

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <Tabs value={tab} onValueChange={(v) => setTab(v as 'sources' | 'notes')} className="flex-shrink-0">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="sources" className="gap-2">
            <FileText className="h-4 w-4" />
            {t('navigation.sources')}
            {sources ? ` (${sources.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="notes" className="gap-2">
            <StickyNote className="h-4 w-4" />
            {t('common.notes')}
            {notes ? ` (${notes.length})` : ''}
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="flex-1 min-h-0">
        {tab === 'sources' ? (
          <SourcesColumn
            embedded
            sources={sources}
            isLoading={sourcesLoading}
            notebookId={notebookId}
            notebookName={notebookName}
            onRefresh={onRefreshSources}
            contextSelections={contextSelections.sources}
            onContextModeChange={(id, mode) => onContextModeChange(id, mode, 'source')}
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            fetchNextPage={fetchNextPage}
            onOpenSource={onOpenSource}
          />
        ) : (
          <NotesColumn
            embedded
            notes={notes}
            isLoading={notesLoading}
            notebookId={notebookId}
            contextSelections={contextSelections.notes}
            onContextModeChange={(id, mode) => onContextModeChange(id, mode, 'note')}
          />
        )}
      </div>
    </div>
  )
}
