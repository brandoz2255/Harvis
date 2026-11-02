/**
 * The add-source box on the Sources tab: a web page or YouTube link, a file, pasted
 * text, or Discover. When the embedding model is missing it offers the download
 * right here and, once that finishes, retries every source that failed for lack of it.
 */

import { Button, cn, Codicon, Input, Textarea, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useRef, useState } from 'react'

import { harvisApi } from './api'
import { capabilitiesKey, fileBlockedReason, useCapabilities } from './notebook-capabilities'
import { NotebookDiscover } from './notebook-discover'
import { errorText, type Source, sourcesKey } from './notebook-shared'
import { UPLOAD_ACCEPT, UPLOAD_HINT } from './notebook-source-meta'
import { embedderKey, fetchEmbedderStatus, NotebooksInstallPanel } from './notebooks-install'

type Kind = 'discover' | 'file' | 'text' | 'url'

const KIND_SHORT: Record<Kind, [label: string, icon: string]> = {
  discover: ['Discover', 'search'],
  file: ['File', 'cloud-upload'],
  text: ['Text', 'note'],
  url: ['Link', 'link']
}

const KIND_LABEL: Record<Kind, string> = {
  discover: 'Discover',
  file: 'Upload a file',
  text: 'Paste text',
  url: 'Web page or YouTube'
}

/** Sources that failed (most often for lack of an embedder) get another go. Returns how many were retried. */
export async function retryFailedSources(notebookId: string, sources: readonly Source[]): Promise<number> {
  const failed = sources.filter(s => s.status === 'error')

  await Promise.allSettled(
    failed.map(s => harvisApi(`/api/notebooks/${notebookId}/sources/${s.id}/retry`, { method: 'POST' }))
  )

  return failed.length
}

export function AddSource({
  notebookId,
  onAdded,
  sources
}: {
  notebookId: string
  onAdded: () => void
  sources: readonly Source[]
}) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<Kind>('url')
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retried, setRetried] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)
  const caps = useCapabilities()

  const embedder = useQuery({
    queryFn: fetchEmbedderStatus,
    queryKey: embedderKey,
    retry: false,
    staleTime: 30_000
  })

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
    const why = fileBlockedReason(file.name, caps)

    if (why) {
      setError(why)

      return
    }

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

  const afterInstall = async () => {
    await queryClient.invalidateQueries({ queryKey: embedderKey })
    await queryClient.invalidateQueries({ queryKey: capabilitiesKey })
    const count = await retryFailedSources(notebookId, sources)
    setRetried(count)

    if (count > 0) {
      void queryClient.invalidateQueries({ queryKey: sourcesKey(notebookId) })
    }
  }

  const status = embedder.data

  return (
    <div className="space-y-2.5 rounded-xl border bg-(--ui-bg-editor) p-2.5">
      {status?.state === 'not_installed' && (
        <NotebooksInstallPanel onInstalled={() => void afterInstall()} status={status} />
      )}
      {retried > 0 && (
        <p className="text-xs text-(--ui-text-tertiary)">
          Installed. Trying {retried} source{retried === 1 ? '' : 's'} that failed again.
        </p>
      )}
      {status?.state !== 'not_installed' && caps?.embedder.reason && (
        <p className="text-xs text-destructive">{caps.embedder.reason}</p>
      )}
      {status?.leaves_machine && (
        <p className="flex items-start gap-1.5 text-xs text-(--ui-text-secondary)" role="note">
          <Codicon className="mt-0.5 shrink-0" name="cloud" size="0.8rem" />
          <span>
            Cloud embeddings are on: the text of every source you add is sent to the embedding service
            {status.model ? ` (${status.model})` : ''} to be indexed.
          </span>
        </p>
      )}
      <div className="flex gap-0.5 rounded-lg bg-(--ui-bg-tertiary) p-0.5 text-xs" role="group">
        {(['url', 'file', 'text', 'discover'] as const).map(k => (
          <button
            aria-label={KIND_LABEL[k]}
            aria-pressed={kind === k}
            className={cn(
              'flex flex-auto items-center justify-center gap-1 rounded-md px-1 py-1 whitespace-nowrap transition-colors',
              kind === k
                ? 'bg-(--ui-bg-editor) text-foreground shadow-xs'
                : 'text-(--ui-text-tertiary) hover:text-foreground'
            )}
            key={k}
            onClick={() => setKind(k)}
            title={KIND_LABEL[k]}
            type="button"
          >
            <Codicon name={KIND_SHORT[k][1]} size="0.75rem" />
            <span className="truncate">{KIND_SHORT[k][0]}</span>
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
            placeholder="Web page or YouTube link"
            type="url"
            value={url}
          />
          <Button disabled={!/^https?:\/\/\S+/.test(url.trim()) || busy} size="sm" type="submit">
            Add
          </Button>
        </form>
      )}
      {kind === 'file' && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <input
            accept={UPLOAD_ACCEPT}
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
          <span className="text-xs text-(--ui-text-tertiary)">{UPLOAD_HINT}</span>
        </div>
      )}
      {kind === 'file' && (caps?.audio_sources.reason || caps?.image_sources.reason) && (
        <ul className="space-y-0.5 text-xs text-(--ui-text-tertiary)">
          {caps?.audio_sources.reason && <li>Audio: {caps.audio_sources.reason}</li>}
          {caps?.image_sources.reason && <li>Images: {caps.image_sources.reason}</li>}
        </ul>
      )}
      {kind === 'discover' && <NotebookDiscover notebookId={notebookId} onAdded={onAdded} />}
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
