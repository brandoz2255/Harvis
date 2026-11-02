/**
 * Read one source: the text Harvis extracted and split into passages, as the
 * backend stored it (`/sources/{id}/content`). Opened from a citation, it scrolls
 * to the cited passage and marks it.
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
import { useEffect, useMemo, useRef } from 'react'

import { harvisApi } from './api'
import { locatePassage, type PassageTarget } from './notebook-citations'
import { errorText, type Source, sourceLabel } from './notebook-shared'

interface SourceContent {
  source_id: string
  title: null | string
  type: string
  content: string
  length: number
  /** Character offset where each PDF or slide page starts in `content`; null when unknown. */
  page_starts?: null | number[]
}

export function NotebookSourceViewer({
  notebookId,
  onClose,
  source,
  target
}: {
  notebookId: string
  onClose: () => void
  source: null | Source
  /** The passage to scroll to and mark, from a citation. */
  target?: null | PassageTarget
}) {
  const content = useQuery({
    enabled: !!source,
    queryFn: () => harvisApi<SourceContent>(`/api/notebooks/${notebookId}/sources/${source?.id}/content`),
    queryKey: ['harvis', 'notebooks', notebookId, 'sources', source?.id, 'content'],
    staleTime: 5 * 60_000
  })

  const body = content.data?.content ?? ''
  const markRef = useRef<HTMLElement | null>(null)

  const range = useMemo(
    () => (target && body ? locatePassage(body, target, content.data?.page_starts) : null),
    [body, content.data?.page_starts, target]
  )

  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: 'center' })
  }, [range, body])

  const details = source
    ? [
        source.type || content.data?.type,
        source.type ? `${source.chunk_count ?? 0} passage${source.chunk_count === 1 ? '' : 's'}` : null,
        content.data ? `${content.data.length.toLocaleString()} characters` : null
      ]
        .filter(Boolean)
        .join(', ')
    : ''

  const marked = range && range.end > range.start

  return (
    <Dialog onOpenChange={next => !next && onClose()} open={!!source}>
      <DialogContent bodyClassName="flex max-h-[80vh] flex-col gap-3 p-4" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{source ? sourceLabel(source) : ''}</DialogTitle>
          <DialogDescription>{details}</DialogDescription>
        </DialogHeader>
        {target && body && (
          <p className="text-xs text-(--ui-text-tertiary)">
            {marked
              ? `Cited passage marked${target.page ? ` (page ${target.page})` : ''}.`
              : range
                ? `Jumped to page ${target.page}; the exact passage could not be marked.`
                : `The cited passage could not be found in the text${target.page ? ` (page ${target.page})` : ''}.`}
          </p>
        )}
        {content.isLoading ? (
          <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
        ) : content.error ? (
          <p className="text-xs text-destructive">{errorText(content.error)}</p>
        ) : !body ? (
          <p className="text-xs text-(--ui-text-tertiary)">Nothing was extracted from this source.</p>
        ) : (
          <pre className="min-h-0 flex-1 overflow-y-auto rounded-md bg-(--ui-bg-tertiary) p-3 text-xs whitespace-pre-wrap">
            {range ? (
              <>
                {body.slice(0, range.start)}
                {marked ? (
                  <mark
                    className="rounded bg-yellow-300/50 text-inherit"
                    data-testid="cited-passage"
                    ref={el => {
                      markRef.current = el
                    }}
                  >
                    {body.slice(range.start, range.end)}
                  </mark>
                ) : (
                  <span
                    data-testid="cited-page"
                    ref={el => {
                      markRef.current = el
                    }}
                  />
                )}
                {body.slice(range.end)}
              </>
            ) : (
              body
            )}
          </pre>
        )}
        {body && (
          <div className="flex justify-end">
            <Button onClick={() => void navigator.clipboard.writeText(body)} size="sm" variant="ghost">
              Copy text
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
