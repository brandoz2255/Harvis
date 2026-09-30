/**
 * The Studio rail from open-notebook: Create buttons (Quiz, Flashcards, Study
 * Guide, Briefing Doc, FAQ, Timeline, Audio Overview) over a "Generated" log of
 * everything made for this notebook, each reviewable in place. The per-source
 * transformations live behind "Transform a source" so nothing was lost.
 */

import { Button, cn, Codicon, useQuery, useQueryClient } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { relativeTime } from './format'
import { ArtifactView } from './notebook-artifact-view'
import {
  type Artifact,
  artifactsKey,
  CREATE_KINDS,
  deleteArtifact,
  generateArtifact,
  type GeneratableKind,
  isPodcastActive,
  KIND_ICON,
  listArtifacts
} from './notebook-artifacts'
import { errorText, podcastAudioUrl, type Source, useChosenModel } from './notebook-shared'
import { AudioOverview, Transformations } from './notebook-studio'

type View = 'audio' | 'home' | 'transform' | { artifact: Artifact }

function CreateButton({
  busy,
  disabled,
  icon,
  label,
  onClick
}: {
  busy?: boolean
  disabled?: boolean
  icon: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      className="flex flex-col items-center justify-center gap-1 rounded-lg border bg-(--ui-bg-secondary) py-2.5 text-xs font-medium transition hover:border-(--ui-stroke-secondary) hover:bg-(--ui-bg-tertiary) disabled:opacity-50"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <Codicon className="text-(--ui-text-tertiary)" name={busy ? 'loading' : icon} size="1rem" spinning={busy} />
      <span>{label}</span>
    </button>
  )
}

function LogRow({ item, onDelete, onOpen }: { item: Artifact; onDelete: () => void; onOpen: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [playing, setPlaying] = useState(false)
  const podcast = item.kind === 'podcast'
  const active = isPodcastActive(item)
  const failed = podcast && (item.status === 'error' || item.status === 'failed')
  const audio = podcast ? podcastAudioUrl({ audio_path: null, audio_url: item.audio_url }) : null

  useEffect(() => {
    if (!confirming) {
      return
    }

    const timer = setTimeout(() => setConfirming(false), 3000)

    return () => clearTimeout(timer)
  }, [confirming])

  return (
    <li className="group rounded-lg border bg-(--ui-bg-secondary) transition hover:border-(--ui-stroke-secondary)">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <button
          className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default"
          disabled={active || failed || (podcast && !audio)}
          onClick={() => (podcast ? setPlaying(p => !p) : onOpen())}
          type="button"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-(--ui-bg-tertiary) text-(--ui-text-tertiary)">
            <Codicon name={active ? 'loading' : KIND_ICON[item.kind]} size="0.8rem" spinning={active} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{item.title}</span>
            <span className={cn('block text-[0.65rem]', failed ? 'text-destructive' : 'text-(--ui-text-tertiary)')}>
              {active ? 'Generating…' : failed ? item.error_message || 'Failed' : relativeTime(item.created_at)}
            </span>
          </span>
        </button>
        {!podcast && (
          <button
            aria-label={confirming ? 'Click again to delete' : 'Delete'}
            className={cn(
              'shrink-0 p-1 transition',
              confirming
                ? 'text-destructive'
                : 'text-(--ui-text-tertiary) opacity-0 group-hover:opacity-100 hover:text-destructive'
            )}
            onClick={() => (confirming ? onDelete() : setConfirming(true))}
            title={confirming ? 'Click again to delete' : 'Delete'}
            type="button"
          >
            <Codicon name="trash" size="0.8rem" />
          </button>
        )}
      </div>
      {playing && audio && (
        <div className="px-2.5 pb-2">
          <audio autoPlay className="h-8 w-full" controls src={audio} />
        </div>
      )}
    </li>
  )
}

export function NotebookStudioRail({
  notebookId,
  sources,
  title
}: {
  notebookId: string
  sources: Source[]
  title: string
}) {
  const queryClient = useQueryClient()
  const { chosen } = useChosenModel()
  const [view, setView] = useState<View>('home')
  const [making, setMaking] = useState<GeneratableKind | null>(null)
  const [error, setError] = useState('')
  const ready = sources.some(s => s.status === 'ready')

  const log = useQuery({
    queryFn: () => listArtifacts(notebookId),
    queryKey: artifactsKey(notebookId),
    refetchInterval: query => ((query.state.data as Artifact[] | undefined)?.some(isPodcastActive) ? 5000 : false)
  })

  const create = async (kind: GeneratableKind) => {
    setMaking(kind)
    setError('')

    try {
      const artifact = await generateArtifact(notebookId, kind, chosen)
      await queryClient.invalidateQueries({ queryKey: artifactsKey(notebookId) })
      setView({ artifact })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setMaking(null)
    }
  }

  const back = (
    <Button aria-label="Back to Studio" onClick={() => setView('home')} size="xs" variant="ghost">
      <Codicon name="arrow-left" size="0.8rem" /> Studio
    </Button>
  )

  if (typeof view === 'object') {
    return <ArtifactView artifact={view.artifact} notebookId={notebookId} onBack={() => setView('home')} />
  }

  if (view === 'audio' || view === 'transform') {
    return (
      <div className="space-y-2">
        {back}
        {view === 'audio' ? (
          <AudioOverview notebookId={notebookId} sources={sources} title={title} />
        ) : (
          <Transformations notebookId={notebookId} sources={sources} />
        )}
      </div>
    )
  }

  const items = log.data ?? []

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid shrink-0 grid-cols-2 gap-2">
        {CREATE_KINDS.map(c => (
          <CreateButton
            busy={making === c.kind}
            disabled={!ready || making !== null}
            icon={c.icon}
            key={c.kind}
            label={c.label}
            onClick={() => void create(c.kind)}
          />
        ))}
        <CreateButton disabled={!ready} icon="mic" label="Audio Overview" onClick={() => setView('audio')} />
        <CreateButton disabled={!ready} icon="wand" label="Transform a source" onClick={() => setView('transform')} />
      </div>
      {!ready && <p className="mt-2 text-xs text-(--ui-text-tertiary)">Add a source to start making things.</p>}
      {making && (
        <p className="mt-2 text-xs text-(--ui-text-tertiary)">
          Writing your {CREATE_KINDS.find(c => c.kind === making)?.label.toLowerCase()} from the sources…
        </p>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      <h4 className="mt-5 mb-2 shrink-0 text-[0.65rem] font-medium tracking-wide text-(--ui-text-tertiary) uppercase">
        Generated
      </h4>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {log.isLoading ? (
          <p className="py-2 text-xs text-(--ui-text-tertiary)">Loading…</p>
        ) : log.error ? (
          <p className="py-2 text-xs text-destructive">{errorText(log.error)}</p>
        ) : items.length === 0 ? (
          <p className="px-2 py-8 text-center text-xs leading-relaxed text-(--ui-text-tertiary)">
            Nothing yet. Make a quiz, flashcards, a study guide or a podcast and it stays here to review anytime.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {items.map(item => (
              <LogRow
                item={item}
                key={item.id}
                onDelete={async () => {
                  try {
                    await deleteArtifact(notebookId, item.id)
                    void queryClient.invalidateQueries({ queryKey: artifactsKey(notebookId) })
                  } catch (err) {
                    setError(errorText(err))
                  }
                }}
                onOpen={() => setView({ artifact: item })}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
