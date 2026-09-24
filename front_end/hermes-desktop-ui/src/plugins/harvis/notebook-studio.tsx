/**
 * Studio tab: turn a source into a summary, key points, study questions,
 * an outline, a plain-language rewrite or action items (`/transform`), and
 * make an audio overview of the notebook (`/podcasts/generate/stream`, which
 * writes a two-speaker script with Ollama and voices it through the speech
 * service when one is reachable). Everything made here can be kept as a note.
 */

import {
  Button,
  cn,
  Codicon,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Streamdown,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { harvisApi } from './api'
import { relativeTime } from './format'
import {
  createNote,
  errorText,
  listKey,
  notesKey,
  type Podcast,
  podcastAudioUrl,
  podcastsKey,
  readSse,
  type Source,
  sourceLabel,
  statsKey,
  toTransformationType,
  type Transformation,
  transformationLabel,
  type TransformationType,
  transformationsKey,
  useChosenModel
} from './notebook-shared'

const DURATIONS = [3, 5, 10, 15] as const

function KeepAsNote({ content, notebookId, title }: { content: string; notebookId: string; title: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  return (
    <Button
      disabled={state !== 'idle'}
      onClick={async () => {
        setState('saving')

        try {
          await createNote(notebookId, { content, title, type: 'ai_note' })
          setState('saved')
          void queryClient.invalidateQueries({ queryKey: notesKey(notebookId) })
          void queryClient.invalidateQueries({ queryKey: statsKey(notebookId) })
          void queryClient.invalidateQueries({ queryKey: listKey })
        } catch {
          setState('error')
        }
      }}
      size="xs"
      variant="ghost"
    >
      {{ error: 'Could not save', idle: 'Save as note', saved: 'Saved to notes', saving: 'Saving…' }[state]}
    </Button>
  )
}

function Clamped({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 600

  return (
    <div>
      <div className={cn('prose prose-sm max-w-none text-sm dark:prose-invert', !open && long && 'line-clamp-6')}>
        <Streamdown mode="static">{text}</Streamdown>
      </div>
      {long && (
        <Button className="mt-1" onClick={() => setOpen(o => !o)} size="xs" variant="ghost">
          {open ? 'Show less' : 'Show more'}
        </Button>
      )}
    </div>
  )
}

function Transformations({ notebookId, sources }: { notebookId: string; sources: Source[] }) {
  const queryClient = useQueryClient()
  const { chosen } = useChosenModel()
  const ready = sources.filter(s => s.status === 'ready')
  const [sourceId, setSourceId] = useState('')
  const [type, setType] = useState('summary')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const types = useQuery({
    queryFn: () =>
      harvisApi<{ transformations: TransformationType[] }>('/api/notebooks/transformations/types').then(
        r => r.transformations ?? []
      ),
    queryKey: ['harvis', 'notebooks', 'transformation-types'],
    staleTime: Infinity
  })

  const history = useQuery({
    queryFn: () =>
      harvisApi<{ transformations: Transformation[] }>(`/api/notebooks/${notebookId}/transformations?limit=50`).then(
        r => r.transformations ?? []
      ),
    queryKey: transformationsKey(notebookId)
  })

  const pickedSource = ready.find(s => s.id === sourceId) ?? ready[0]
  const titleOf = (id: null | string) => {
    const s = sources.find(x => x.id === id)

    return s ? sourceLabel(s) : 'a removed source'
  }

  const run = async () => {
    if (!pickedSource || !chosen) {
      return
    }

    setBusy(true)
    setError('')

    try {
      await harvisApi(`/api/notebooks/${notebookId}/sources/${pickedSource.id}/transform`, {
        method: 'POST',
        body: JSON.stringify({ transformation: toTransformationType(type), model: chosen })
      })
      void queryClient.invalidateQueries({ queryKey: transformationsKey(notebookId) })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const list = history.data ?? []

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Summaries and study aids</h3>
      {ready.length === 0 ? (
        <p className="text-xs text-(--ui-text-tertiary)">Add a source and wait for it to be read first.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <Select onValueChange={setType} value={type}>
            <SelectTrigger aria-label="What to make" className="h-7 w-44 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(types.data ?? [{ id: 'summary', name: 'Summary', description: '' }]).map(t => (
                <SelectItem key={t.id} value={t.id}>
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-xs text-(--ui-text-tertiary)">of</span>
          <Select onValueChange={setSourceId} value={pickedSource?.id ?? ''}>
            <SelectTrigger aria-label="Which source" className="h-7 w-56 text-xs">
              <SelectValue placeholder="Pick a source" />
            </SelectTrigger>
            <SelectContent>
              {ready.map(s => (
                <SelectItem key={s.id} value={s.id}>
                  {sourceLabel(s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button disabled={busy || !pickedSource || !chosen} onClick={() => void run()} size="sm">
            {busy ? 'Writing…' : 'Make it'}
          </Button>
          {!chosen && <span className="text-xs text-(--ui-text-tertiary)">No model online.</span>}
        </div>
      )}
      {busy && (
        <p className="text-xs text-(--ui-text-tertiary)">Reading the source and writing… this can take a minute.</p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {history.isLoading ? (
        <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
      ) : history.error ? (
        <p className="text-xs text-destructive">{errorText(history.error)}</p>
      ) : list.length > 0 ? (
        <ul className="space-y-2">
          {list.map(t => {
            const label = transformationLabel(t.transformation_type, types.data)

            return (
              <li className="space-y-1 rounded-lg border p-3" key={t.id}>
                <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium text-foreground">{label}</span> of {titleOf(t.source_id)}
                    {t.model_used ? ` · ${t.model_used}` : ''} · {relativeTime(t.created_at)}
                  </span>
                  <KeepAsNote
                    content={t.transformed_content}
                    notebookId={notebookId}
                    title={`${label}: ${titleOf(t.source_id)}`}
                  />
                </div>
                <Clamped text={t.transformed_content} />
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}

function PodcastCard({ notebookId, podcast: p }: { notebookId: string; podcast: Podcast }) {
  const queryClient = useQueryClient()
  const [showScript, setShowScript] = useState(false)
  const [audioGone, setAudioGone] = useState(false)
  const [error, setError] = useState('')
  const audio = podcastAudioUrl(p)
  const script = (p.transcript ?? [])
    .map(line => `**${line.speaker || 'Speaker'}:** ${line.dialogue || line.text || ''}`)
    .join('\n\n')

  return (
    <li className="space-y-1.5 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm">{p.title || 'Audio overview'}</span>
        <span className="text-xs text-(--ui-text-tertiary)">
          {p.style}
          {p.duration_seconds ? ` · ${Math.round(p.duration_seconds / 60)} min` : ''}
          {p.created_at ? ` · ${relativeTime(p.created_at)}` : ''}
        </span>
        <Button
          aria-label="Delete audio overview"
          onClick={async () => {
            try {
              await harvisApi(`/api/notebooks/podcasts/${p.id}`, { method: 'DELETE' })
              void queryClient.invalidateQueries({ queryKey: podcastsKey(notebookId) })
            } catch (err) {
              setError(errorText(err))
            }
          }}
          size="icon-xs"
          variant="ghost"
        >
          <Codicon name="trash" size="0.8rem" />
        </Button>
      </div>
      {audio && !audioGone ? (
        <audio className="h-8 w-full" controls onError={() => setAudioGone(true)} preload="none" src={audio} />
      ) : (
        <p className="text-xs text-(--ui-text-tertiary)">
          {p.status === 'error'
            ? p.error_message || 'Generation failed.'
            : audioGone
              ? 'The audio file is no longer available; the script is still here.'
              : 'Script only: the speech service was not reachable, so no audio was made.'}
        </p>
      )}
      {script && (
        <>
          <Button onClick={() => setShowScript(s => !s)} size="xs" variant="ghost">
            {showScript ? 'Hide script' : 'Show script'}
          </Button>
          {showScript && (
            <>
              <div className="prose prose-sm max-w-none text-sm dark:prose-invert">
                <Streamdown mode="static">{script}</Streamdown>
              </div>
              <KeepAsNote content={script} notebookId={notebookId} title={`Script: ${p.title || 'Audio overview'}`} />
            </>
          )}
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </li>
  )
}

function AudioOverview({ notebookId, sources, title }: { notebookId: string; sources: Source[]; title: string }) {
  const { chosen } = useChosenModel()
  const queryClient = useQueryClient()
  const ready = sources.filter(s => s.status === 'ready')
  const [style, setStyle] = useState('conversational')
  const [minutes, setMinutes] = useState<string>('5')
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const abort = useRef<AbortController | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const styles = useQuery({
    queryFn: () =>
      harvisApi<{ styles: TransformationType[] }>('/api/notebooks/podcasts/styles').then(r => r.styles ?? []),
    queryKey: ['harvis', 'notebooks', 'podcast-styles'],
    staleTime: Infinity
  })

  const podcasts = useQuery({
    queryFn: () =>
      harvisApi<{ podcasts: Podcast[] }>(`/api/notebooks/podcasts/by-notebook/${notebookId}`).then(
        r => r.podcasts ?? []
      ),
    queryKey: podcastsKey(notebookId)
  })

  const generate = async () => {
    const controller = new AbortController()
    abort.current = controller
    setProgress('Starting…')
    setError('')

    try {
      await readSse(
        '/api/notebooks/podcasts/generate/stream',
        {
          duration_minutes: Number(minutes),
          generate_audio: true,
          ...(chosen ? { model: chosen } : {}),
          notebook_id: notebookId,
          source_ids: ready.map(s => s.id),
          speakers: 2,
          style,
          title: `${title} — audio overview`
        },
        ({ data, event }) => {
          if (event === 'progress' && typeof data.message === 'string') {
            setProgress(data.message)
          } else if (event === 'error') {
            setError(typeof data.error === 'string' ? data.error : 'Generation failed.')
          }
        },
        controller.signal
      )
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(errorText(err))
      }
    } finally {
      setProgress('')
      abort.current = null
      void queryClient.invalidateQueries({ queryKey: podcastsKey(notebookId) })
    }
  }

  const list = podcasts.data ?? []

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Audio overview</h3>
      <p className="text-xs text-(--ui-text-tertiary)">
        Two hosts talk through everything in your sources. The script is written first, then voiced.
      </p>
      {ready.length === 0 ? (
        <p className="text-xs text-(--ui-text-tertiary)">Add a source and wait for it to be read first.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <Select onValueChange={setStyle} value={style}>
            <SelectTrigger aria-label="Style" className="h-7 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(styles.data ?? [{ id: 'conversational', name: 'Conversational', description: '' }]).map(s => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select onValueChange={setMinutes} value={minutes}>
            <SelectTrigger aria-label="Length" className="h-7 w-28 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DURATIONS.map(d => (
                <SelectItem key={d} value={String(d)}>
                  {d} minutes
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {progress ? (
            <Button onClick={() => abort.current?.abort()} size="sm" variant="outline">
              Stop
            </Button>
          ) : (
            <Button onClick={() => void generate()} size="sm">
              <Codicon name="mic" size="0.8rem" /> Generate
            </Button>
          )}
        </div>
      )}
      {progress && (
        <p className="text-xs text-(--ui-text-tertiary)">
          <Codicon name="loading" size="0.8rem" spinning /> {progress}
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {podcasts.isLoading ? (
        <p className="text-xs text-(--ui-text-tertiary)">Loading…</p>
      ) : podcasts.error ? (
        <p className="text-xs text-destructive">{errorText(podcasts.error)}</p>
      ) : list.length > 0 ? (
        <ul className="space-y-2">
          {list.map(p => (
            <PodcastCard key={p.id} notebookId={notebookId} podcast={p} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function NotebookStudio({
  notebookId,
  sources,
  title
}: {
  notebookId: string
  sources: Source[]
  title: string
}) {
  return (
    <section className="space-y-6">
      <Transformations notebookId={notebookId} sources={sources} />
      <AudioOverview notebookId={notebookId} sources={sources} title={title} />
    </section>
  )
}
