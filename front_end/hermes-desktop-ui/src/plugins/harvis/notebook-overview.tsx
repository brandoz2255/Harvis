/**
 * The notebook's overview, pinned to the top of its chat the way open-notebook
 * shows it: emoji, name, source count and date, the synopsis, and (before the
 * first question) suggested questions as chips. Edit, auto-name and delete sit
 * in a small row beside it, so the workspace needs no header band.
 */

import { Button, Codicon, Input, Textarea, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { suggestionsKey, suggestQuestions } from './notebook-artifacts'
import { errorText, listKey, type NotebookInfo, notebookKey, type Source, useChosenModel } from './notebook-shared'

/** The title the notebooks grid gives a new notebook; auto-named once it has a ready source. */
export const UNTITLED = 'Untitled notebook'

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

interface AutonameState {
  count: number
  title: string
}

const autonameKey = (id: string) => `onb:autoname:${id}`

function recallAutoname(id: string): AutonameState | null {
  try {
    const raw = window.localStorage.getItem(autonameKey(id))

    return raw ? (JSON.parse(raw) as AutonameState) : null
  } catch {
    return null
  }
}

function rememberAutoname(id: string, state: AutonameState) {
  try {
    window.localStorage.setItem(autonameKey(id), JSON.stringify(state))
  } catch {
    // storage full or blocked: the next ready source simply names it again
  }
}

/** Title, emoji and a 3-5 sentence synopsis from the sources (the /onb facade's autoname). */
const autonameFromSources = (id: string) =>
  harvisApi<{ description: string; emoji: string; title: string }>(
    `/onb-api/notebooks/${encodeURIComponent(id)}/autoname`,
    { method: 'POST' }
  )

function dateLabel(iso: string | undefined) {
  const t = iso ? Date.parse(iso) : NaN

  return Number.isNaN(t)
    ? ''
    : new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function NotebookOverview({
  ask,
  empty,
  notebook,
  onBack,
  onDeleted,
  sources
}: {
  ask: (question: string) => void
  /** No questions asked yet: show suggested questions. */
  empty: boolean
  notebook: NotebookInfo | undefined
  onBack?: () => void
  onDeleted: () => void
  sources: Source[]
}) {
  const queryClient = useQueryClient()
  const { chosen } = useChosenModel()
  const [editing, setEditing] = useState(false)
  const [naming, setNaming] = useState(false)
  const [error, setError] = useState('')
  const readyCount = sources.filter(s => s.status === 'ready').length
  const id = notebook?.id ?? ''

  const suggestions = useQuery({
    enabled: empty && readyCount > 0 && !!id,
    queryFn: () => suggestQuestions(id, chosen),
    queryKey: suggestionsKey(id, readyCount),
    retry: false,
    staleTime: Infinity
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: notebookKey(id) })
    void queryClient.invalidateQueries({ queryKey: listKey })
  }

  const autoname = async () => {
    setNaming(true)
    setError('')

    try {
      const res = await autonameFromSources(id)
      rememberAutoname(id, { count: readyCount, title: res.title })
      refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setNaming(false)
    }
  }

  // open-notebook's rule: name (title, emoji, synopsis) from the sources while the
  // notebook is untitled, and again whenever more sources are ready, until the
  // user renames it by hand. Shares its localStorage key with the /onb UI.
  const busy = useRef(false)
  const title = notebook?.title

  useEffect(() => {
    if (busy.current || !title || readyCount === 0) {
      return
    }

    const state = recallAutoname(id)
    const lower = title.trim().toLowerCase()
    const untitled = ['', 'new notebook', 'untitled', UNTITLED.toLowerCase()].includes(lower)

    if ((state && state.title && title !== state.title) || (!untitled && !state)) {
      return
    }

    if (readyCount <= (state?.count ?? 0)) {
      return
    }

    busy.current = true
    void autoname().finally(() => {
      busy.current = false
    })
    // autoname is recreated every render; the ref keeps this to one call at a time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, title, readyCount])

  if (editing && notebook) {
    return (
      <EditDetails
        notebook={notebook}
        onDone={() => {
          setEditing(false)
          refresh()
        }}
      />
    )
  }

  const date = dateLabel(notebook?.created_at ?? notebook?.updated_at)
  const chips = empty ? (suggestions.data ?? []) : []

  return (
    <div className="max-w-2xl pb-2">
      <div className="mb-2 flex items-center gap-0.5">
        {onBack && (
          <Button aria-label="All notebooks" onClick={onBack} size="xs" title="All notebooks" variant="ghost">
            <Codicon name="arrow-left" size="0.8rem" />
          </Button>
        )}
        <span className="flex-1" />
        <Button disabled={!notebook} onClick={() => setEditing(true)} size="xs" variant="ghost">
          <Codicon name="edit" size="0.8rem" /> Edit
        </Button>
        <Button
          disabled={naming || readyCount === 0}
          onClick={() => void autoname()}
          size="xs"
          title="Let Harvis name and summarise this notebook from its sources"
          variant="ghost"
        >
          <Codicon name="sparkle" size="0.8rem" /> {naming ? 'Naming…' : 'Auto-name'}
        </Button>
        <Button
          onClick={async () => {
            if (window.confirm('Delete this notebook and all its sources?')) {
              try {
                await harvisApi(`/api/notebooks/${id}`, { method: 'DELETE' })
                onDeleted()
              } catch (err) {
                setError(errorText(err))
              }
            }
          }}
          size="xs"
          variant="ghost"
        >
          <Codicon name="trash" size="0.8rem" /> Delete
        </Button>
      </div>
      <div className="mb-3 text-5xl leading-none">{notebook?.emoji || '📓'}</div>
      <h2 className="text-2xl font-bold tracking-tight">{notebook?.title ?? 'Loading…'}</h2>
      <p className="mt-1.5 text-xs text-(--ui-text-tertiary)">
        {sources.length} {sources.length === 1 ? 'source' : 'sources'}
        {date ? ` · ${date}` : ''}
      </p>
      {notebook?.description ? (
        <p className="mt-4 text-sm leading-relaxed whitespace-pre-line text-(--ui-text-secondary)">
          {notebook.description}
        </p>
      ) : naming ? (
        <p className="mt-4 text-sm text-(--ui-text-quaternary) italic">Generating an overview of your sources…</p>
      ) : readyCount > 0 ? null : sources.length > 0 ? (
        <p className="mt-4 text-sm text-(--ui-text-tertiary)">Reading your sources…</p>
      ) : (
        <p className="mt-4 text-sm text-(--ui-text-tertiary)">Add a source on the left to start asking questions.</p>
      )}
      {chips.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {chips.map(q => (
            <button
              className="rounded-full border bg-(--ui-bg-secondary) px-3 py-1.5 text-left text-xs text-(--ui-text-secondary) transition hover:border-(--ui-stroke-secondary) hover:text-foreground"
              key={q}
              onClick={() => ask(q)}
              type="button"
            >
              {q}
            </button>
          ))}
        </div>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      {!empty && <div className="mt-6 border-b" />}
    </div>
  )
}
