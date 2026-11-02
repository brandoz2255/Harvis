/**
 * The Studio panel, laid out like Gemini Notebook's: one tile per output in
 * Gemini's order (Audio Overview, Mind Map, Reports, Flashcards, Quiz, Slide
 * Deck, Data Table), each with its own pencil to customize before making it,
 * over the list of everything made so far and the notebook's notes. Reports
 * groups the four Markdown formats. "Transform a source" is a Harvis extra.
 */

import { Button, cn, Codicon, Textarea, useQuery, useQueryClient } from '@hermes/plugin-sdk'
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
  listArtifacts,
  PROMPT_MAX
} from './notebook-artifacts'
import { NotebookNotes } from './notebook-notes'
import { isDefaultSelection, selectedSourceIds } from './notebook-selection'
import { errorText, podcastAudioUrl, type Source, useChosenModel } from './notebook-shared'
import { AudioOverview, Transformations } from './notebook-studio'

type View = 'audio' | 'home' | 'reports' | 'transform' | { artifact: Artifact } | { customize: GeneratableKind }

const kindInfo = (kind: GeneratableKind) => CREATE_KINDS.find(c => c.kind === kind)!

/** How long the rail keeps looking for an artifact a chat action is making in the background. */
const CHAT_WAIT_MS = 5 * 60_000
/** An artifact of the asked kind this recent counts as the one the chat made. */
const CHAT_RECENT_MS = 10 * 60_000

/** The artifact a chat action ("make me a quiz on Mars") made, once it has landed in the log. */
export function chatMadeArtifact(list: Artifact[] | undefined, kind: string, openedAt: number) {
  return list?.find(a => a.kind === kind && Date.parse(a.created_at) >= openedAt - CHAT_RECENT_MS)
}

const REPORT_KINDS: { hint: string; kind: GeneratableKind }[] = [
  { hint: 'The key points and what they mean, for a quick catch-up', kind: 'briefing' },
  { hint: 'Key terms, short-answer questions and essay prompts', kind: 'study_guide' },
  { hint: 'The questions a newcomer would ask, answered', kind: 'faq' },
  { hint: 'What happened when, with the people involved', kind: 'timeline' }
]

/** Single-click tiles, in Gemini Notebook's order; Reports opens its own list. */
const TILE_KINDS: GeneratableKind[] = ['mindmap', 'flashcards', 'quiz', 'slides', 'data_table']

const TILE_LABEL: Partial<Record<GeneratableKind, string>> = { mindmap: 'Mind Map' }

const PLACEHOLDER = 'e.g. Write for a beginner and focus on costs'

function Tile({
  busy,
  disabled,
  icon,
  label,
  onClick,
  onCustomize
}: {
  busy?: boolean
  disabled?: boolean
  icon: string
  label: string
  onClick: () => void
  onCustomize?: () => void
}) {
  return (
    <div className="group relative">
      <button
        className="flex w-full items-center gap-2 rounded-lg border bg-(--ui-bg-secondary) py-2.5 pr-7 pl-2.5 text-left text-xs font-medium transition hover:border-(--ui-stroke-secondary) hover:bg-(--ui-bg-tertiary) disabled:opacity-50"
        disabled={disabled}
        onClick={onClick}
        type="button"
      >
        <Codicon className="text-(--ui-text-tertiary)" name={busy ? 'loading' : icon} size="1rem" spinning={busy} />
        <span className="min-w-0 flex-1 truncate" title={label}>
          {label}
        </span>
      </button>
      {onCustomize && (
        <button
          aria-label={`Customize ${label}`}
          className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded p-1 text-(--ui-text-tertiary) opacity-60 transition group-hover:opacity-100 hover:bg-(--ui-bg-secondary) hover:text-foreground disabled:opacity-30"
          disabled={disabled}
          onClick={onCustomize}
          title="Customize"
          type="button"
        >
          <Codicon name="edit" size="0.75rem" />
        </button>
      )}
    </div>
  )
}

function LogRow({ item, onDelete, onOpen }: { item: Artifact; onDelete: () => void; onOpen: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [playing, setPlaying] = useState(false)
  const podcast = item.kind === 'podcast'
  const active = isPodcastActive(item)
  const failed = podcast && (item.status === 'error' || item.status === 'failed')
  const scriptOnly = podcast && item.status === 'script_only'
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
          disabled={active || failed || scriptOnly || (podcast && !audio)}
          onClick={() => (podcast ? setPlaying(p => !p) : onOpen())}
          type="button"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-(--ui-bg-tertiary) text-(--ui-text-tertiary)">
            <Codicon name={active ? 'loading' : KIND_ICON[item.kind]} size="0.8rem" spinning={active} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{item.title}</span>
            <span
              className={cn(
                'block text-[0.65rem]',
                failed || scriptOnly ? 'text-destructive' : 'text-(--ui-text-tertiary)'
              )}
            >
              {active
                ? 'Generating…'
                : failed
                  ? item.error_message || 'Failed'
                  : scriptOnly
                    ? `Script only. ${item.error_message || 'The audio could not be made.'}`
                    : relativeTime(item.created_at)}
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
  expecting,
  notebookId,
  sources,
  title
}: {
  /** A kind a chat action is generating in the background (`&make=quiz` on the notebook link). */
  expecting?: string
  notebookId: string
  sources: Source[]
  title: string
}) {
  const queryClient = useQueryClient()
  const { chosen } = useChosenModel()
  const [view, setView] = useState<View>('home')
  const [making, setMaking] = useState<GeneratableKind | null>(null)
  const [error, setError] = useState('')
  const [prompt, setPrompt] = useState('')
  const ready = sources.some(s => s.status === 'ready')

  const awaited = CREATE_KINDS.some(c => c.kind === expecting) ? (expecting as GeneratableKind) : null
  const [openedAt] = useState(() => Date.now())
  const waiting = (list: Artifact[] | undefined) =>
    awaited !== null && Date.now() - openedAt < CHAT_WAIT_MS && !chatMadeArtifact(list, awaited, openedAt)

  const log = useQuery({
    queryFn: () => listArtifacts(notebookId),
    queryKey: artifactsKey(notebookId),
    refetchInterval: query => {
      const list = query.state.data as Artifact[] | undefined

      return list?.some(isPodcastActive) ? 5000 : waiting(list) ? 4000 : false
    }
  })

  // Open the chat-made artifact once, when it lands.
  const landed = awaited ? chatMadeArtifact(log.data, awaited, openedAt) : undefined
  const [shown, setShown] = useState(false)

  useEffect(() => {
    if (landed && !shown) {
      setShown(true)
      setView({ artifact: landed })
    }
  }, [landed, shown])

  const create = async (kind: GeneratableKind, instructions = '') => {
    setError('')

    // Sources left unticked are left out; with the default selection no list is sent and the server uses them all.
    const sourceIds = isDefaultSelection(notebookId, sources) ? undefined : selectedSourceIds(notebookId, sources)

    if (sourceIds && sourceIds.length === 0) {
      setError('No source is selected. Tick at least one in Sources.')

      return
    }

    setMaking(kind)

    try {
      const artifact = await generateArtifact(notebookId, kind, chosen, { prompt: instructions, sourceIds })
      await queryClient.invalidateQueries({ queryKey: artifactsKey(notebookId) })
      setPrompt('')
      setView({ artifact })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setMaking(null)
    }
  }

  const home = () => {
    setError('')
    setView('home')
  }

  const back = (
    <Button aria-label="Back to Studio" onClick={home} size="xs" variant="ghost">
      <Codicon name="arrow-left" size="0.8rem" /> Studio
    </Button>
  )

  const status = (
    <>
      {making && (
        <p className="mt-2 text-xs text-(--ui-text-tertiary)">
          Writing your {kindInfo(making).label.toLowerCase()} from the sources…
        </p>
      )}
      {!making && awaited && log.data && waiting(log.data) && (
        <p className="mt-2 text-xs text-(--ui-text-tertiary)" data-testid="chat-making">
          Writing your {kindInfo(awaited).label.toLowerCase()} from the sources. It opens here when it is ready.
        </p>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </>
  )

  if (typeof view === 'object' && 'artifact' in view) {
    return <ArtifactView artifact={view.artifact} notebookId={notebookId} onBack={home} />
  }

  if (typeof view === 'object') {
    const kind = view.customize
    const info = kindInfo(kind)

    return (
      <div className="space-y-2">
        {back}
        <h4 className="flex items-center gap-2 text-sm font-medium">
          <Codicon className="text-(--ui-text-tertiary)" name={info.icon} size="1rem" /> Customize{' '}
          {TILE_LABEL[kind] ?? info.label}
        </h4>
        <label className="block text-xs text-(--ui-text-tertiary)">
          What should it focus on?
          <Textarea
            autoFocus
            className="mt-1 min-h-24 text-xs"
            maxLength={PROMPT_MAX}
            onChange={e => setPrompt(e.target.value)}
            placeholder={PLACEHOLDER}
            value={prompt}
          />
        </label>
        <Button disabled={!ready || making !== null} onClick={() => void create(kind, prompt)} size="sm">
          {making === kind ? 'Generating…' : 'Generate'}
        </Button>
        {status}
      </div>
    )
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

  if (view === 'reports') {
    return (
      <div className="space-y-2">
        {back}
        <h4 className="text-sm font-medium">Reports</h4>
        <p className="text-xs text-(--ui-text-tertiary)">Pick a format. Use the pencil to tell it what to focus on.</p>
        <ul className="space-y-1.5">
          {REPORT_KINDS.map(r => {
            const info = kindInfo(r.kind)

            return (
              <li className="group relative" key={r.kind}>
                <button
                  className="flex w-full items-start gap-2 rounded-lg border bg-(--ui-bg-secondary) py-2 pr-8 pl-2.5 text-left transition hover:border-(--ui-stroke-secondary) disabled:opacity-50"
                  disabled={!ready || making !== null}
                  onClick={() => void create(r.kind)}
                  type="button"
                >
                  <Codicon
                    className="mt-0.5 text-(--ui-text-tertiary)"
                    name={making === r.kind ? 'loading' : info.icon}
                    size="0.9rem"
                    spinning={making === r.kind}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-medium">{info.label}</span>
                    <span className="block text-[0.65rem] text-(--ui-text-tertiary)">{r.hint}</span>
                  </span>
                </button>
                <button
                  aria-label={`Customize ${info.label}`}
                  className="absolute top-2 right-1.5 rounded p-1 text-(--ui-text-tertiary) hover:text-foreground"
                  disabled={!ready || making !== null}
                  onClick={() => setView({ customize: r.kind })}
                  title="Customize"
                  type="button"
                >
                  <Codicon name="edit" size="0.75rem" />
                </button>
              </li>
            )
          })}
        </ul>
        {status}
      </div>
    )
  }

  const items = log.data ?? []
  const idle = !ready || making !== null

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="grid shrink-0 grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
        <Tile
          disabled={!ready}
          icon="mic"
          label="Audio Overview"
          onClick={() => setView('audio')}
          onCustomize={() => setView('audio')}
        />
        {TILE_KINDS.slice(0, 1).map(kind => (
          <Tile
            busy={making === kind}
            disabled={idle}
            icon={kindInfo(kind).icon}
            key={kind}
            label={TILE_LABEL[kind] ?? kindInfo(kind).label}
            onClick={() => void create(kind)}
            onCustomize={() => setView({ customize: kind })}
          />
        ))}
        <Tile
          busy={making !== null && REPORT_KINDS.some(r => r.kind === making)}
          disabled={!ready}
          icon="file"
          label="Reports"
          onClick={() => setView('reports')}
        />
        {TILE_KINDS.slice(1).map(kind => (
          <Tile
            busy={making === kind}
            disabled={idle}
            icon={kindInfo(kind).icon}
            key={kind}
            label={TILE_LABEL[kind] ?? kindInfo(kind).label}
            onClick={() => void create(kind)}
            onCustomize={() => setView({ customize: kind })}
          />
        ))}
        <Tile disabled={!ready} icon="wand" label="Transform a source" onClick={() => setView('transform')} />
      </div>
      {!ready && <p className="mt-2 text-xs text-(--ui-text-tertiary)">Add a source to start making things.</p>}
      {status}
      <div className="mt-4 border-t pt-3">
        {log.isLoading ? (
          <p className="py-2 text-xs text-(--ui-text-tertiary)">Loading…</p>
        ) : log.error ? (
          <p className="py-2 text-xs text-destructive">{errorText(log.error)}</p>
        ) : items.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs leading-relaxed text-(--ui-text-tertiary)">
            Studio output will be saved here. Make an audio overview, a quiz, flashcards or a report and it stays here
            to review anytime.
          </p>
        ) : (
          <ul aria-label="Studio output" className="space-y-1.5">
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
      <div className="mt-4 border-t pt-3">
        <h4 className="mb-2 text-[0.65rem] font-medium tracking-wide text-(--ui-text-tertiary) uppercase">Notes</h4>
        <NotebookNotes notebookId={notebookId} />
      </div>
    </div>
  )
}
