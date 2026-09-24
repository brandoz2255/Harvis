/**
 * Read one source: the text Harvis extracted and split into passages, as the
 * backend stored it (`/sources/{id}/content`).
 */

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  useQuery
} from '@hermes/plugin-sdk'

import { harvisApi } from './api'
import { errorText, type Source, sourceLabel } from './notebook-shared'

interface SourceContent {
  source_id: string
  title: null | string
  type: string
  content: string
  length: number
}

export function NotebookSourceViewer({
  notebookId,
  onClose,
  source
}: {
  notebookId: string
  onClose: () => void
  source: null | Source
}) {
  const content = useQuery({
    enabled: !!source,
    queryFn: () => harvisApi<SourceContent>(`/api/notebooks/${notebookId}/sources/${source?.id}/content`),
    queryKey: ['harvis', 'notebooks', notebookId, 'sources', source?.id, 'content'],
    staleTime: 5 * 60_000
  })

  return (
    <Dialog onOpenChange={next => !next && onClose()} open={!!source}>
      <DialogContent bodyClassName="flex max-h-[80vh] flex-col gap-3 p-4" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{source ? sourceLabel(source) : ''}</DialogTitle>
          <DialogDescription>
            {source
              ? `${source.type}, ${source.chunk_count ?? 0} passage${source.chunk_count === 1 ? '' : 's'}` +
                (content.data ? `, ${content.data.length.toLocaleString()} characters` : '')
              : ''}
          </DialogDescription>
        </DialogHeader>
        {content.isLoading ? (
          <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
        ) : content.error ? (
          <p className="text-xs text-destructive">{errorText(content.error)}</p>
        ) : !content.data?.content ? (
          <p className="text-xs text-(--ui-text-tertiary)">Nothing was extracted from this source.</p>
        ) : (
          <pre className="min-h-0 flex-1 overflow-y-auto rounded-md bg-(--ui-bg-tertiary) p-3 text-xs whitespace-pre-wrap">
            {content.data.content}
          </pre>
        )}
        {content.data?.content && (
          <div className="flex justify-end">
            <Button
              onClick={() => void navigator.clipboard.writeText(content.data?.content ?? '')}
              size="sm"
              variant="ghost"
            >
              Copy text
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
