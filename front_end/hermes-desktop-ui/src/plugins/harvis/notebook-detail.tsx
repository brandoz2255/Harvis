/**
 * One notebook: its name and description (editable, or auto-named from its
 * sources), a stats line, and four tabs — Sources, Chat, Notes and Studio.
 */

import {
  Button,
  Codicon,
  EmptyState,
  Input,
  SegmentedControl,
  Textarea,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import { NotebookChat } from './notebook-chat'
import { NotebookNotes } from './notebook-notes'
import {
  errorText,
  listKey,
  type NotebookInfo,
  notebookKey,
  type NotebookStats,
  type Source,
  sourcesKey,
  statsKey
} from './notebook-shared'
import { NotebookSources, useSourceWatchers } from './notebook-sources'
import { NotebookStudio } from './notebook-studio'

type Tab = 'chat' | 'notes' | 'sources' | 'studio'

function EditDetails({ notebook, onDone }: { notebook: NotebookInfo; onDone: () => void }) {
  const [title, setTitle] = useState(notebook.title)
  const [description, setDescription] = useState(notebook.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  return (
    <form
      className="space-y-1.5"
      onSubmit={async event => {
        event.preventDefault()
        setBusy(true)
        setError('')

        try {
          await harvisApi(`/api/notebooks/${notebook.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ title: title.trim(), description: description.trim() || null })
          })
          onDone()
        } catch (err) {
          setError(errorText(err))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Input aria-label="Title" onChange={e => setTitle(e.target.value)} value={title} />
      <Textarea
        aria-label="Description"
        className="min-h-16 text-sm"
        onChange={e => setDescription(e.target.value)}
        placeholder="What this notebook is for (optional)"
        value={description}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex justify-end gap-1.5">
        <Button onClick={onDone} size="sm" type="button" variant="ghost">
          Cancel
        </Button>
        <Button disabled={!title.trim() || busy} size="sm" type="submit">
          Save
        </Button>
      </div>
    </form>
  )
}

function StatsLine({ stats }: { stats: NotebookStats | undefined }) {
  if (!stats) {
    return null
  }

  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const parts = [
    plural(stats.source_count, 'source'),
    plural(stats.chunk_count, 'passage'),
    plural(stats.note_count, 'note')
  ]

  if (stats.message_count > 0) {
    parts.push(plural(stats.message_count, 'message'))
  }

  if (stats.processing_sources > 0) {
    parts.push(`${stats.processing_sources} still being read`)
  }

  return <p className="text-xs text-(--ui-text-tertiary)">{parts.join(' · ')}</p>
}

export function NotebookDetail({ notebookId, onDeleted }: { notebookId: string; onDeleted: () => void }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [naming, setNaming] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<null | Tab>(null)

  const notebook = useQuery({
    queryFn: () => harvisApi<NotebookInfo>(`/api/notebooks/${notebookId}`),
    queryKey: notebookKey(notebookId)
  })

  const sources = useQuery({
    queryFn: () => harvisApi<Source[]>(`/api/notebooks/${notebookId}/sources`),
    queryKey: sourcesKey(notebookId),
    // The SSE status watcher below is the fast path; this is the fallback when it can't connect.
    refetchInterval: query => {
      const list = query.state.data as Source[] | undefined

      return list?.some(s => s.status === 'pending' || s.status === 'processing') ? 4000 : false
    }
  })

  const stats = useQuery({
    queryFn: () => harvisApi<NotebookStats>(`/api/notebooks/${notebookId}/stats`),
    queryKey: statsKey(notebookId)
  })

  useSourceWatchers(notebookId, sources.data ?? [])

  const refreshHeader = () => {
    void queryClient.invalidateQueries({ queryKey: notebookKey(notebookId) })
    void queryClient.invalidateQueries({ queryKey: listKey })
  }

  const autoname = async () => {
    setNaming(true)
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/autoname`, { method: 'POST' })
      refreshHeader()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setNaming(false)
    }
  }

  if (notebook.error) {
    return <EmptyState description={errorText(notebook.error)} title="Could not open this notebook" />
  }

  const list = sources.data ?? []
  const ready = list.some(s => s.status === 'ready')
  const current: Tab = tab ?? (ready ? 'chat' : 'sources')
  const nb = notebook.data
  const count = (n: number) => (n > 0 ? ` (${n})` : '')

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        {editing && nb ? (
          <EditDetails
            notebook={nb}
            onDone={() => {
              setEditing(false)
              refreshHeader()
            }}
          />
        ) : (
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-lg font-semibold">
                {nb?.emoji ? `${nb.emoji} ` : ''}
                {nb?.title ?? (notebook.isLoading ? 'Loading…' : 'Notebook')}
              </h2>
              {nb?.description && <p className="text-sm text-(--ui-text-tertiary)">{nb.description}</p>}
              <StatsLine stats={stats.data} />
            </div>
            <Button disabled={!nb} onClick={() => setEditing(true)} size="sm" variant="ghost">
              <Codicon name="edit" size="0.8rem" /> Edit
            </Button>
            <Button
              disabled={naming || list.length === 0}
              onClick={() => void autoname()}
              size="sm"
              title="Let Harvis name this notebook from its sources"
              variant="ghost"
            >
              <Codicon name="sparkle" size="0.8rem" /> {naming ? 'Naming…' : 'Auto-name'}
            </Button>
            <Button
              onClick={async () => {
                if (window.confirm('Delete this notebook and all its sources?')) {
                  try {
                    await harvisApi(`/api/notebooks/${notebookId}`, { method: 'DELETE' })
                    onDeleted()
                  } catch (err) {
                    setError(errorText(err))
                  }
                }
              }}
              size="sm"
              variant="ghost"
            >
              <Codicon name="trash" size="0.8rem" /> Delete
            </Button>
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      <SegmentedControl
        onChange={setTab}
        options={[
          { id: 'sources', label: `Sources${count(list.length)}` },
          { id: 'chat', label: 'Chat' },
          { id: 'notes', label: `Notes${count(stats.data?.note_count ?? nb?.note_count ?? 0)}` },
          { id: 'studio', label: 'Studio' }
        ]}
        value={current}
      />
      {sources.isLoading ? (
        <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
      ) : sources.error ? (
        <p className="text-xs text-destructive">{errorText(sources.error)}</p>
      ) : current === 'sources' ? (
        <NotebookSources notebookId={notebookId} sources={list} />
      ) : current === 'chat' ? (
        <NotebookChat notebookId={notebookId} ready={ready} />
      ) : current === 'notes' ? (
        <NotebookNotes notebookId={notebookId} />
      ) : (
        <NotebookStudio notebookId={notebookId} sources={list} title={nb?.title ?? 'Notebook'} />
      )}
    </div>
  )
}
