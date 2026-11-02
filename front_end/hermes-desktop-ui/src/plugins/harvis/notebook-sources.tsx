/**
 * Sources panel, laid out like Gemini Notebook's: add a page, YouTube video,
 * file or pasted text, watch each source go pending → processing → ready over
 * the backend's SSE status stream, tick which sources chat and Studio use
 * (with "Select all sources"), and open a ready source to read it. Each row's
 * "⋯" holds the Harvis extras: Full or Summary context, re-index and remove.
 */

import { Button, Checkbox, cn, Codicon, StatusDot, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { AddSource } from './notebook-add-source'
import { reindexNotebook, reindexSource, reindexSummary } from './notebook-reindex'
import {
  CONTEXT_LEVELS,
  type ContextLevel,
  levelOf,
  requestQuestion,
  setContextLevel,
  useContextLevels
} from './notebook-selection'
import { errorText, listKey, type Source, sourceLabel, sourcesKey, statsKey } from './notebook-shared'
import { NotebookSourceInsights } from './notebook-source-insights'
import { ingestNotice, insightsState, needsReindex } from './notebook-source-meta'
import { NotebookSourceViewer } from './notebook-source-viewer'

const SOURCE_TONE = { error: 'bad', pending: 'warn', processing: 'warn', ready: 'good' } as const

const SOURCE_ICON: Record<string, string> = {
  audio: 'unmute',
  doc: 'file',
  epub: 'book',
  image: 'file-media',
  markdown: 'markdown',
  pdf: 'file-pdf',
  pptx: 'preview',
  text: 'note',
  transcript: 'symbol-string',
  url: 'globe',
  xlsx: 'table',
  youtube: 'device-camera-video'
}

interface StatusEvent {
  source_id?: string
  status?: Source['status']
  chunk_count?: number
  error_message?: string
  done?: boolean
  error?: string
}

/** Keeps one EventSource per source that is still being read, patching the cached list as it moves. */
export function useSourceWatchers(notebookId: string, sources: Source[]) {
  const queryClient = useQueryClient()
  const watchers = useRef(new Map<string, EventSource>())

  useEffect(() => {
    if (typeof EventSource === 'undefined') {
      return
    }

    const active = watchers.current
    const settle = (id: string) => {
      active.get(id)?.close()
      active.delete(id)
      void queryClient.invalidateQueries({ queryKey: sourcesKey(notebookId) })
      void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
      void queryClient.invalidateQueries({ queryKey: listKey })
    }

    for (const s of sources) {
      const busy = s.status === 'pending' || s.status === 'processing'

      if (!busy || active.has(s.id)) {
        continue
      }

      const es = new EventSource(`/api/notebooks/${notebookId}/sources/${s.id}/status/stream`, {
        withCredentials: true
      })

      es.onmessage = message => {
        let data: StatusEvent

        try {
          data = JSON.parse(message.data as string) as StatusEvent
        } catch {
          return
        }

        if (data.error) {
          settle(s.id)

          return
        }

        queryClient.setQueryData<Source[]>(sourcesKey(notebookId), list =>
          list?.map(item =>
            item.id === s.id
              ? {
                  ...item,
                  status: data.status ?? item.status,
                  chunk_count: data.chunk_count ?? item.chunk_count,
                  error_message: data.error_message || item.error_message
                }
              : item
          )
        )

        if (data.done) {
          settle(s.id)
        }
      }

      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          settle(s.id)
        }
      }

      active.set(s.id, es)
    }
  }, [notebookId, queryClient, sources])

  useEffect(() => {
    const active = watchers.current

    return () => {
      for (const es of active.values()) {
        es.close()
      }

      active.clear()
    }
  }, [])
}

function LevelPicker({
  level,
  onChange,
  source
}: {
  level: ContextLevel
  onChange: (level: ContextLevel) => void
  source: Source
}) {
  return (
    <span
      aria-label={`What chat reads of ${sourceLabel(source)}`}
      className="inline-flex rounded border text-[0.65rem]"
      role="group"
    >
      {CONTEXT_LEVELS.map(l => (
        <button
          aria-pressed={level === l.id}
          className={cn(
            'px-1.5 py-0.5 first:rounded-l last:rounded-r',
            level === l.id ? 'bg-(--ui-bg-tertiary) text-foreground' : 'text-(--ui-text-tertiary) hover:text-foreground'
          )}
          key={l.id}
          onClick={() => onChange(l.id)}
          title={l.description}
          type="button"
        >
          {l.label}
        </button>
      ))}
    </span>
  )
}

function SourceRow({
  level,
  notebookId,
  onLevel,
  onOpen,
  source: s
}: {
  level: ContextLevel
  notebookId: string
  onLevel: (level: ContextLevel) => void
  onOpen: (source: Source) => void
  source: Source
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const [showInsights, setShowInsights] = useState(false)
  const [more, setMore] = useState(false)
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })
  const insights = insightsState(s)
  const notice = ingestNotice(s)

  const act = async (run: () => Promise<unknown>) => {
    setError('')

    try {
      await run()
      refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  const detail =
    s.status === 'ready'
      ? `${s.type}, ${s.chunk_count ?? 0} passage${s.chunk_count === 1 ? '' : 's'}` +
        (insights === 'pending' ? ', writing a summary…' : insights === 'error' ? ', no summary' : '')
      : s.status === 'error'
        ? s.error_message || 'Could not read this source.'
        : s.status === 'processing'
          ? `Reading… ${s.chunk_count ? `${s.chunk_count} passages so far` : ''}`
          : 'Waiting to be read…'

  const label = sourceLabel(s)

  return (
    <li
      className={cn(
        'group/source space-y-1 rounded-lg px-2.5 py-1.5 text-sm hover:bg-(--ui-bg-tertiary)',
        more && 'bg-(--ui-bg-tertiary)'
      )}
    >
      <div className="flex items-center gap-2.5">
        <span className="grid size-7 shrink-0 place-items-center rounded-md bg-(--ui-bg-editor) text-(--ui-text-secondary)">
          <Codicon name={SOURCE_ICON[s.type] ?? 'file'} size="0.85rem" />
        </span>
        <button
          className="min-w-0 flex-1 text-left disabled:cursor-default"
          disabled={s.status !== 'ready'}
          onClick={() => onOpen(s)}
          title={s.status === 'ready' ? 'Read this source' : undefined}
          type="button"
        >
          <span className={cn('block truncate font-medium', s.status === 'ready' && 'hover:underline')}>{label}</span>
          <span className="flex items-center gap-1.5 text-xs text-(--ui-text-tertiary)">
            {s.status !== 'ready' && <StatusDot tone={SOURCE_TONE[s.status] ?? 'muted'} />}
            <span className="truncate">{error || detail}</span>
          </span>
        </button>
        {s.status === 'error' && (
          <Button
            onClick={() =>
              void act(() => harvisApi(`/api/notebooks/${notebookId}/sources/${s.id}/retry`, { method: 'POST' }))
            }
            size="sm"
            variant="ghost"
          >
            Retry
          </Button>
        )}
        <button
          aria-expanded={more}
          aria-label={`More for ${label}`}
          className={cn(
            'shrink-0 rounded p-1 text-(--ui-text-tertiary) opacity-0 transition-opacity group-hover/source:opacity-100 hover:bg-(--ui-bg-secondary) hover:text-foreground focus-visible:opacity-100',
            more && 'opacity-100'
          )}
          onClick={() => setMore(v => !v)}
          title="More"
          type="button"
        >
          <Codicon name="kebab-vertical" size="0.8rem" />
        </button>
        <Checkbox
          aria-label={`Use ${label}`}
          checked={s.status === 'ready' && level !== 'off'}
          disabled={s.status !== 'ready'}
          onCheckedChange={on => onLevel(on === true ? 'full' : 'off')}
        />
      </div>
      {more && (
        <div className="flex flex-wrap items-center gap-1.5 pl-9.5">
          {s.status === 'ready' && <LevelPicker level={level} onChange={onLevel} source={s} />}
          {s.status === 'ready' && insights !== 'none' && (
            <Button aria-expanded={showInsights} onClick={() => setShowInsights(v => !v)} size="xs" variant="ghost">
              {showInsights ? 'Hide summary' : 'Summary'}
            </Button>
          )}
          {s.status === 'ready' && (
            <Button
              aria-label={`Re-index ${label}`}
              onClick={() => void act(() => reindexSource(notebookId, s.id))}
              size="xs"
              title="Read this source again and rebuild its search index"
              variant="ghost"
            >
              <Codicon name="refresh" size="0.75rem" /> Re-index
            </Button>
          )}
          <Button
            aria-label="Remove source"
            onClick={() =>
              void act(() => harvisApi(`/api/notebooks/${notebookId}/sources/${s.id}`, { method: 'DELETE' }))
            }
            size="xs"
            variant="ghost"
          >
            <Codicon name="trash" size="0.75rem" /> Remove
          </Button>
        </div>
      )}
      {s.status === 'ready' && needsReindex(s) && (
        <p className="pl-9.5 text-xs text-(--ui-text-secondary)">
          Indexed with a different embedding model. Re-index it for better answers.
        </p>
      )}
      {notice && <p className="pl-9.5 text-xs text-(--ui-text-secondary)">{notice}</p>}
      {showInsights && insights !== 'none' && (
        <NotebookSourceInsights
          className="ml-9.5"
          notebookId={notebookId}
          onAsk={q => requestQuestion(notebookId, q)}
          source={s}
        />
      )}
    </li>
  )
}

function SourcesHeader({ notebookId, sources }: { notebookId: string; sources: Source[] }) {
  const queryClient = useQueryClient()
  const levels = useContextLevels(notebookId)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const ready = sources.filter(s => s.status === 'ready')
  const reading = ready.filter(s => levelOf(levels, s.id) !== 'off').length

  const reindexAll = async () => {
    setBusy(true)
    setMessage('')
    setFailed(false)

    try {
      setMessage(reindexSummary(await reindexNotebook(notebookId)))
      void queryClient.invalidateQueries({ queryKey: sourcesKey(notebookId) })
    } catch (err) {
      setFailed(true)
      setMessage(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const allOn = ready.length > 0 && reading === ready.length

  const selectAll = (on: boolean) => {
    for (const s of ready) {
      const level = levelOf(levels, s.id)

      if (on ? level === 'off' : level !== 'off') {
        setContextLevel(notebookId, s.id, on ? 'full' : 'off')
      }
    }
  }

  return (
    <>
      <div className="flex items-center gap-1 px-1 text-xs text-(--ui-text-tertiary)">
        <span className="min-w-0 flex-1 truncate" title="Chat and Studio use the ticked sources">
          Chat reads {reading} of {ready.length} source{ready.length === 1 ? '' : 's'}
        </span>
        <Button
          aria-label="Re-index all"
          disabled={busy || ready.length === 0}
          onClick={() => void reindexAll()}
          size="icon-xs"
          title={busy ? 'Starting…' : 'Re-index all sources'}
          variant="ghost"
        >
          <Codicon className={cn(busy && 'animate-spin')} name="refresh" size="0.75rem" />
        </Button>
      </div>
      {message && (
        <p className={cn('px-1 text-xs', failed ? 'text-destructive' : 'text-(--ui-text-tertiary)')}>{message}</p>
      )}
      <SelectAllRow
        checked={allOn ? true : reading === 0 ? false : 'indeterminate'}
        disabled={ready.length === 0}
        onChange={selectAll}
      />
    </>
  )
}

function SelectAllRow({
  checked,
  disabled,
  onChange
}: {
  checked: 'indeterminate' | boolean
  disabled: boolean
  onChange: (on: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-(--ui-text-secondary) hover:bg-(--ui-bg-tertiary)">
      <span className="flex-1">Select all sources</span>
      <Checkbox
        aria-label="Select all sources"
        checked={checked}
        disabled={disabled}
        onCheckedChange={on => onChange(on === true)}
      />
    </label>
  )
}

export function NotebookSources({ notebookId, sources }: { notebookId: string; sources: Source[] }) {
  const queryClient = useQueryClient()
  const levels = useContextLevels(notebookId)
  const [open, setOpen] = useState<null | Source>(null)

  return (
    <section className="space-y-3">
      <AddSource
        notebookId={notebookId}
        onAdded={() => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })}
        sources={sources}
      />
      {sources.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 px-4 py-8 text-center text-xs text-(--ui-text-tertiary)">
          <Codicon name="library" size="1.4rem" />
          <p>No sources yet. Add a page, a file, or some text.</p>
        </div>
      ) : (
        <div className="space-y-1">
          <SourcesHeader notebookId={notebookId} sources={sources} />
          <ul className="space-y-0.5">
            {sources.map(s => (
              <SourceRow
                key={s.id}
                level={levelOf(levels, s.id)}
                notebookId={notebookId}
                onLevel={level => setContextLevel(notebookId, s.id, level)}
                onOpen={setOpen}
                source={s}
              />
            ))}
          </ul>
        </div>
      )}
      <NotebookSourceViewer notebookId={notebookId} onClose={() => setOpen(null)} source={open} />
    </section>
  )
}
