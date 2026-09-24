/**
 * Sources tab: add a page, YouTube video, file or pasted text, watch each new
 * source go pending → processing → ready over the backend's SSE status stream,
 * and open a ready source to read what Harvis extracted from it.
 */

import { Button, cn, Codicon, Input, StatusDot, Textarea, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { NotebookSourceViewer } from './notebook-source-viewer'
import { errorText, listKey, type Source, sourceLabel, sourcesKey, statsKey } from './notebook-shared'

const SOURCE_TONE = { error: 'bad', pending: 'warn', processing: 'warn', ready: 'good' } as const

const SOURCE_ICON: Record<string, string> = {
  audio: 'unmute',
  doc: 'file',
  image: 'file-media',
  markdown: 'markdown',
  pdf: 'file-pdf',
  text: 'note',
  transcript: 'symbol-string',
  url: 'globe',
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

function AddSource({ notebookId, onAdded }: { notebookId: string; onAdded: () => void }) {
  const [kind, setKind] = useState<'file' | 'text' | 'url'>('url')
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const submit = async (init: RequestInit, path: string) => {
    setBusy(true)
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/sources/${path}`, { method: 'POST', ...init })
      setUrl('')
      setTitle('')
      setText('')
      onAdded()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const upload = (file: File) => {
    const form = new FormData()
    form.append('file', file)
    void submit({ body: form }, 'upload')
  }

  const addText = () => {
    const form = new FormData()
    form.append('title', title.trim() || 'Pasted text')
    form.append('content', text)
    void submit({ body: form }, 'text')
  }

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex gap-1 text-xs">
        {(['url', 'file', 'text'] as const).map(k => (
          <button
            className={cn(
              'rounded px-2 py-0.5',
              kind === k ? 'bg-(--ui-bg-tertiary) text-foreground' : 'text-(--ui-text-tertiary) hover:text-foreground'
            )}
            key={k}
            onClick={() => setKind(k)}
            type="button"
          >
            {{ file: 'Upload a file', text: 'Paste text', url: 'Web page or YouTube' }[k]}
          </button>
        ))}
      </div>
      {kind === 'url' && (
        <form
          className="flex gap-1.5"
          onSubmit={event => {
            event.preventDefault()
            const youtube = /youtu\.?be/.test(url)
            void submit({ body: JSON.stringify({ url: url.trim() }) }, youtube ? 'youtube' : 'url')
          }}
        >
          <Input
            className="min-w-0 flex-1"
            onChange={e => setUrl(e.target.value)}
            placeholder="https://…"
            type="url"
            value={url}
          />
          <Button disabled={!/^https?:\/\/\S+/.test(url.trim()) || busy} size="sm" type="submit">
            Add
          </Button>
        </form>
      )}
      {kind === 'file' && (
        <div className="flex items-center gap-2">
          <input
            accept=".pdf,.txt,.md,.docx,.doc,.html,.csv,.mp3,.wav,.m4a"
            className="hidden"
            onChange={e => {
              const file = e.target.files?.[0]

              if (file) {
                upload(file)
              }

              e.target.value = ''
            }}
            ref={fileRef}
            type="file"
          />
          <Button disabled={busy} onClick={() => fileRef.current?.click()} size="sm" variant="outline">
            <Codicon name="cloud-upload" size="0.8rem" /> Choose a file
          </Button>
          <span className="text-xs text-(--ui-text-tertiary)">PDF, Word, text, Markdown, or audio.</span>
        </div>
      )}
      {kind === 'text' && (
        <div className="space-y-1.5">
          <Input onChange={e => setTitle(e.target.value)} placeholder="Title (optional)" value={title} />
          <Textarea className="min-h-24 text-sm" onChange={e => setText(e.target.value)} value={text} />
          <Button disabled={!text.trim() || busy} onClick={addText} size="sm">
            Add text
          </Button>
        </div>
      )}
      {busy && <p className="text-xs text-(--ui-text-tertiary)">Adding…</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function SourceRow({
  notebookId,
  onOpen,
  source: s
}: {
  notebookId: string
  onOpen: (source: Source) => void
  source: Source
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })

  const act = async (path: string, method: string) => {
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/sources/${s.id}${path}`, { method })
      refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  const detail =
    s.status === 'ready'
      ? `${s.type}, ${s.chunk_count ?? 0} passage${s.chunk_count === 1 ? '' : 's'}`
      : s.status === 'error'
        ? s.error_message || 'Could not read this source.'
        : s.status === 'processing'
          ? `Reading… ${s.chunk_count ? `${s.chunk_count} passages so far` : ''}`
          : 'Waiting to be read…'

  return (
    <li className="flex items-center gap-2 px-3 py-2 text-sm">
      <StatusDot tone={SOURCE_TONE[s.status] ?? 'muted'} />
      <Codicon className="text-(--ui-text-tertiary)" name={SOURCE_ICON[s.type] ?? 'file'} size="0.9rem" />
      <button
        className="min-w-0 flex-1 text-left disabled:cursor-default"
        disabled={s.status !== 'ready'}
        onClick={() => onOpen(s)}
        title={s.status === 'ready' ? 'Read this source' : undefined}
        type="button"
      >
        <span className={cn('block truncate', s.status === 'ready' && 'hover:underline')}>{sourceLabel(s)}</span>
        <span className="block text-xs text-(--ui-text-tertiary)">{error || detail}</span>
      </button>
      {s.status === 'error' && (
        <Button onClick={() => void act('/retry', 'POST')} size="sm" variant="ghost">
          Retry
        </Button>
      )}
      <Button aria-label="Remove source" onClick={() => void act('', 'DELETE')} size="sm" variant="ghost">
        <Codicon name="trash" size="0.8rem" />
      </Button>
    </li>
  )
}

export function NotebookSources({ notebookId, sources }: { notebookId: string; sources: Source[] }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState<null | Source>(null)

  return (
    <section className="space-y-2">
      {sources.length === 0 ? (
        <p className="text-xs text-(--ui-text-tertiary)">No sources yet. Add a page, a file, or some text.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {sources.map(s => (
            <SourceRow key={s.id} notebookId={notebookId} onOpen={setOpen} source={s} />
          ))}
        </ul>
      )}
      <AddSource
        notebookId={notebookId}
        onAdded={() => void queryClient.invalidateQueries({ queryKey: ['harvis', 'notebooks'] })}
      />
      <NotebookSourceViewer notebookId={notebookId} onClose={() => setOpen(null)} source={open} />
    </section>
  )
}
