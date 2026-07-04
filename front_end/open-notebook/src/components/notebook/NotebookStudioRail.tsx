'use client'

import { useEffect, useState } from 'react'
import {
  Sparkles,
  FileQuestion,
  Layers,
  BookOpen,
  FileText,
  HelpCircle,
  History,
  Mic,
  Trash2,
  Loader2,
} from 'lucide-react'
import { useNotebookArtifacts, useDeleteArtifact } from '@/lib/hooks/use-artifacts'
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs'
import { resolvePodcastAssetUrl } from '@/lib/api/podcasts'
import type { ArtifactKind, ArtifactLogItem, GeneratableKind } from '@/lib/api/artifacts'

interface Props {
  notebookId: string
  onCreate: (kind: GeneratableKind) => void
  onReview: (item: ArtifactLogItem) => void
}

const ICON: Record<ArtifactKind, typeof FileQuestion> = {
  quiz: FileQuestion,
  flashcards: Layers,
  study_guide: BookOpen,
  briefing: FileText,
  faq: HelpCircle,
  timeline: History,
  podcast: Mic,
}

const ACTIVE_PODCAST = ['pending', 'generating', 'running', 'queued']

function rel(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const s = Math.max(1, Math.floor((Date.now() - t) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return `${Math.floor(d / 7)}w ago`
}

function CreateBtn({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof FileQuestion
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center justify-center gap-1 rounded-lg border border-border bg-card hover:border-primary/50 hover:bg-accent/50 transition py-2.5 text-xs font-medium"
    >
      <Icon className="h-4 w-4 text-muted-foreground" />
      <span>{label}</span>
    </button>
  )
}

function LogRow({
  item,
  onReview,
  onDelete,
}: {
  item: ArtifactLogItem
  onReview: (item: ArtifactLogItem) => void
  onDelete: (item: ArtifactLogItem) => void
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  useEffect(() => {
    if (!confirming) return
    const t = setTimeout(() => setConfirming(false), 3000)
    return () => clearTimeout(t)
  }, [confirming])
  const Icon = ICON[item.kind] ?? Sparkles
  const isPodcast = item.kind === 'podcast'
  const isActive = isPodcast && ACTIVE_PODCAST.includes(item.status)
  const isFailed = isPodcast && (item.status === 'error' || item.status === 'failed')
  const isReady = !isPodcast || item.status === 'completed' || item.status === 'ready'

  const handleClick = async () => {
    if (isPodcast) {
      if (!isReady) return
      if (audioUrl) {
        setAudioUrl(null)
        return
      }
      const url = await resolvePodcastAssetUrl(item.audio_url || undefined)
      setAudioUrl(url ?? item.audio_url ?? null)
    } else {
      onReview(item)
    }
  }

  return (
    <div className="group rounded-lg border border-border bg-card hover:border-primary/30 transition">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <button
          onClick={handleClick}
          disabled={isActive}
          className="flex items-center gap-2 flex-1 min-w-0 text-left disabled:cursor-default"
        >
          <span className="shrink-0 flex h-6 w-6 items-center justify-center rounded-md bg-muted text-muted-foreground">
            {isActive ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{item.title}</span>
            <span className={`block text-[10px] ${isFailed ? 'text-destructive' : 'text-muted-foreground'}`}>
              {isActive ? 'Generating…' : isFailed ? 'Failed — tap to retry from Podcasts' : rel(item.created_at)}
            </span>
          </span>
        </button>
        <button
          onClick={() => {
            if (confirming) onDelete(item)
            else setConfirming(true)
          }}
          title={confirming ? 'Click again to delete' : 'Delete'}
          className={`transition shrink-0 p-1 ${
            confirming
              ? 'opacity-100 text-destructive'
              : 'opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive'
          }`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {audioUrl && (
        <div className="px-2.5 pb-2">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio controls autoPlay src={audioUrl} className="w-full h-8" />
        </div>
      )}
    </div>
  )
}

/** Persistent Studio rail: Create entry points + a log of everything generated for
    this notebook (quizzes, flashcards, study guides, podcasts), reviewable in place. */
export function NotebookStudioRail({ notebookId, onCreate, onReview }: Props) {
  const { data: items, isLoading } = useNotebookArtifacts(notebookId)
  const del = useDeleteArtifact(notebookId)
  const { openPodcastDialog } = useCreateDialogs()

  return (
    <div className="h-full min-h-0 flex flex-col">
      {/* Create */}
      <div className="flex-shrink-0">
        <div className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-primary" /> Studio
        </div>
        <div className="grid grid-cols-2 gap-2">
          <CreateBtn icon={FileQuestion} label="Quiz" onClick={() => onCreate('quiz')} />
          <CreateBtn icon={Layers} label="Flashcards" onClick={() => onCreate('flashcards')} />
          <CreateBtn icon={BookOpen} label="Study Guide" onClick={() => onCreate('study_guide')} />
          <CreateBtn icon={FileText} label="Briefing Doc" onClick={() => onCreate('briefing')} />
          <CreateBtn icon={HelpCircle} label="FAQ" onClick={() => onCreate('faq')} />
          <CreateBtn icon={History} label="Timeline" onClick={() => onCreate('timeline')} />
          <div className="col-span-2">
            <button
              onClick={() => openPodcastDialog(notebookId)}
              className="w-full flex items-center justify-center gap-2 rounded-lg border border-border bg-card hover:border-primary/50 hover:bg-accent/50 transition py-2.5 text-xs font-medium"
            >
              <Mic className="h-4 w-4 text-muted-foreground" />
              <span>Audio Overview</span>
            </button>
          </div>
        </div>
      </div>

      {/* Log */}
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mt-5 mb-2 flex-shrink-0">
        Generated
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1 space-y-1.5">
        {isLoading && <div className="text-xs text-muted-foreground py-2">Loading…</div>}
        {!isLoading && (!items || items.length === 0) && (
          <div className="text-xs text-muted-foreground py-8 text-center leading-relaxed px-2">
            Nothing yet. Generate a quiz, flashcards, a study guide, or a podcast — it&apos;ll be
            saved here to review anytime.
          </div>
        )}
        {items?.map((item) => (
          <LogRow key={item.id} item={item} onReview={onReview} onDelete={(it) => del.mutate(it)} />
        ))}
      </div>
    </div>
  )
}
