/**
 * Notes tab over `/api/notebooks/{id}/notes`: your own notes plus the answers,
 * summaries and audio scripts you chose to keep. Pinned notes stay on top.
 */

import { Button, cn, Codicon, Input, Streamdown, Textarea, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { harvisApi } from './api'
import { relativeTime } from './format'
import { createNote, errorText, listKey, type Note, notesKey, sortNotes, statsKey } from './notebook-shared'

const NOTE_BADGE: Record<Note['type'], string> = {
  ai_note: 'AI',
  highlight: 'Highlight',
  summary: 'Summary',
  user_note: 'Note'
}

export function useNotes(notebookId: string) {
  return useQuery({
    queryFn: () =>
      harvisApi<{ notes: Note[] }>(`/api/notebooks/${notebookId}/notes?limit=200`).then(r => sortNotes(r.notes ?? [])),
    queryKey: notesKey(notebookId)
  })
}

function NewNote({ notebookId, onDone }: { notebookId: string; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  return (
    <form
      className="space-y-1.5 rounded-lg border p-3"
      onSubmit={async event => {
        event.preventDefault()
        setBusy(true)
        setError('')

        try {
          await createNote(notebookId, { content: content.trim(), title: title.trim() || null, type: 'user_note' })
          onDone()
        } catch (err) {
          setError(errorText(err))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Input onChange={e => setTitle(e.target.value)} placeholder="Title (optional)" value={title} />
      <Textarea
        autoFocus
        className="min-h-24 text-sm"
        onChange={e => setContent(e.target.value)}
        placeholder="Write a note…"
        value={content}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex justify-end gap-1.5">
        <Button onClick={onDone} size="sm" type="button" variant="ghost">
          Cancel
        </Button>
        <Button disabled={!content.trim() || busy} size="sm" type="submit">
          {busy ? 'Saving…' : 'Save note'}
        </Button>
      </div>
    </form>
  )
}

function NoteCard({ note, notebookId }: { note: Note; notebookId: string }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(note.title ?? '')
  const [content, setContent] = useState(note.content)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: notesKey(notebookId) })
    void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
    void queryClient.invalidateQueries({ queryKey: listKey })
  }

  const call = async (init: RequestInit) => {
    setBusy(true)
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/notes/${note.id}`, init)
      refresh()

      return true
    } catch (err) {
      setError(errorText(err))

      return false
    } finally {
      setBusy(false)
    }
  }

  const patch = (body: Record<string, unknown>) => call({ method: 'PATCH', body: JSON.stringify(body) })

  return (
    <li className={cn('space-y-1.5 rounded-lg border p-3', note.is_pinned && 'border-primary/40')}>
      <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
        <span
          className={cn(
            'rounded px-1 py-0.5 text-[0.65rem] tracking-wide uppercase',
            note.type === 'user_note' ? 'bg-(--ui-bg-tertiary)' : 'bg-primary/10 text-primary'
          )}
        >
          {NOTE_BADGE[note.type] ?? note.type}
        </span>
        <span className="min-w-0 flex-1 truncate">{relativeTime(note.updated_at || note.created_at)}</span>
        <Button
          aria-label={note.is_pinned ? 'Unpin note' : 'Pin note'}
          disabled={busy}
          onClick={() => void patch({ is_pinned: !note.is_pinned })}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name={note.is_pinned ? 'pinned' : 'pin'} size="0.8rem" />
        </Button>
        <Button
          aria-label="Edit note"
          disabled={busy}
          onClick={() => {
            setTitle(note.title ?? '')
            setContent(note.content)
            setEditing(e => !e)
          }}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name="edit" size="0.8rem" />
        </Button>
        <Button
          aria-label="Delete note"
          disabled={busy}
          onClick={() => {
            if (window.confirm('Delete this note?')) {
              void call({ method: 'DELETE' })
            }
          }}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name="trash" size="0.8rem" />
        </Button>
      </div>
      {editing ? (
        <div className="space-y-1.5">
          <Input onChange={e => setTitle(e.target.value)} placeholder="Title (optional)" value={title} />
          <Textarea className="min-h-24 text-sm" onChange={e => setContent(e.target.value)} value={content} />
          <div className="flex justify-end gap-1.5">
            <Button onClick={() => setEditing(false)} size="sm" variant="ghost">
              Cancel
            </Button>
            <Button
              disabled={!content.trim() || busy}
              onClick={async () => {
                if (await patch({ content: content.trim(), title: title.trim() || null })) {
                  setEditing(false)
                }
              }}
              size="sm"
            >
              Save
            </Button>
          </div>
        </div>
      ) : (
        <>
          {note.title && <p className="text-sm font-medium">{note.title}</p>}
          <div className="prose prose-sm max-w-none text-sm dark:prose-invert">
            <Streamdown mode="static">{note.content}</Streamdown>
          </div>
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </li>
  )
}

export function NotebookNotes({ notebookId }: { notebookId: string }) {
  const queryClient = useQueryClient()
  const notes = useNotes(notebookId)
  const [adding, setAdding] = useState(false)
  const list = notes.data ?? []

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <p className="flex-1 text-xs text-(--ui-text-tertiary)">
          Keep your own notes here, or save an answer, summary or script from the other tabs.
        </p>
        {!adding && (
          <Button onClick={() => setAdding(true)} size="sm" variant="outline">
            <Codicon name="add" size="0.8rem" /> New note
          </Button>
        )}
      </div>
      {adding && (
        <NewNote
          notebookId={notebookId}
          onDone={() => {
            setAdding(false)
            void queryClient.invalidateQueries({ queryKey: notesKey(notebookId) })
            void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
            void queryClient.invalidateQueries({ queryKey: listKey })
          }}
        />
      )}
      {notes.isLoading ? (
        <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
      ) : notes.error ? (
        <p className="text-xs text-destructive">{errorText(notes.error)}</p>
      ) : list.length === 0 ? (
        <p className="text-xs text-(--ui-text-tertiary)">No notes yet.</p>
      ) : (
        <ul className="space-y-2">
          {list.map(n => (
            <NoteCard key={n.id} note={n} notebookId={notebookId} />
          ))}
        </ul>
      )}
    </section>
  )
}
