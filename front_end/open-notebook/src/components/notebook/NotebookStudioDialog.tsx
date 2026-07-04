'use client'

import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { QuizView } from '@/components/studio/QuizView'
import { FlashcardsView } from '@/components/studio/FlashcardsView'
import { StudyGuideView } from '@/components/studio/StudyGuideView'
import { useGenerateArtifact } from '@/lib/hooks/use-artifacts'
import { useCreateNote } from '@/lib/hooks/use-notes'
import type { ArtifactLogItem, GeneratableKind } from '@/lib/api/artifacts'
import {
  Sparkles,
  FileQuestion,
  Layers,
  BookOpen,
  FileText,
  HelpCircle,
  History,
  RotateCcw,
  StickyNote,
  Check,
  Loader2,
} from 'lucide-react'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  notebookId: string
  notebookTitle?: string
  /** Generate this kind immediately on open (Studio "Create" buttons). */
  initialKind?: GeneratableKind | null
  /** Review an already-generated artifact instead of generating (log rows). */
  reviewItem?: ArtifactLogItem | null
  /** Sources currently CHECKED in the Sources panel — generation grounds on these. */
  selectedSourceIds?: string[]
  /** Total sources in the notebook (for the "N of M sources" grounding line). */
  totalSourceCount?: number
}

const KINDS: { id: GeneratableKind; label: string; desc: string; icon: typeof FileQuestion }[] = [
  { id: 'quiz', label: 'Quiz', desc: 'Multiple-choice questions', icon: FileQuestion },
  { id: 'flashcards', label: 'Flashcards', desc: 'Front / back study cards', icon: Layers },
  { id: 'study_guide', label: 'Study Guide', desc: 'Structured study notes', icon: BookOpen },
  { id: 'briefing', label: 'Briefing Doc', desc: 'Themes, facts & quotes', icon: FileText },
  { id: 'faq', label: 'FAQ', desc: 'Questions readers would ask', icon: HelpCircle },
  { id: 'timeline', label: 'Timeline', desc: 'Events & cast of characters', icon: History },
]

/** Renders the body of an artifact (review or freshly generated). */
function ArtifactBody({ item }: { item: ArtifactLogItem }) {
  if (item.kind === 'quiz' && item.content?.questions) return <QuizView questions={item.content.questions} />
  if (item.kind === 'flashcards' && item.content?.cards) return <FlashcardsView cards={item.content.cards} />
  // All report kinds (study_guide / briefing / faq / timeline) are Markdown.
  if (item.content?.markdown != null) return <StudyGuideView markdown={item.content.markdown} />
  return <div className="text-sm text-muted-foreground py-4">Nothing to show.</div>
}

export function NotebookStudioDialog({
  open,
  onOpenChange,
  notebookId,
  notebookTitle,
  initialKind,
  reviewItem,
  selectedSourceIds,
  totalSourceCount,
}: Props) {
  const generate = useGenerateArtifact(notebookId)
  const createNote = useCreateNote()
  const [kind, setKind] = useState<GeneratableKind | null>(null)
  const [result, setResult] = useState<ArtifactLogItem | null>(null)
  const [error, setError] = useState('')
  const [savedNote, setSavedNote] = useState(false)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const isReview = !!reviewItem
  const loading = generate.isPending

  const runGenerate = async (k: GeneratableKind) => {
    setKind(k)
    setResult(null)
    setError('')
    setSavedNote(false)
    try {
      const item = await generate.mutateAsync({ kind: k, sourceIds: selectedSourceIds })
      if (mounted.current) setResult(item)
    } catch (e) {
      if (!mounted.current) return
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Generation failed — try again.')
    }
  }

  // Seed mode from props each time the dialog opens.
  useEffect(() => {
    if (!open) return
    setSavedNote(false)
    if (reviewItem) {
      setKind(reviewItem.kind === 'podcast' ? null : (reviewItem.kind as GeneratableKind))
      setResult(reviewItem)
      setError('')
    } else if (initialKind) {
      runGenerate(initialKind)
    } else {
      setKind(null)
      setResult(null)
      setError('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reviewItem, initialKind])

  const reset = () => {
    setKind(null)
    setResult(null)
    setError('')
    setSavedNote(false)
  }

  // Save a Markdown report to this notebook's Notes (NotebookLM "Save to note").
  const canSaveToNote = !!result?.content?.markdown?.trim()
  const handleSaveToNote = () => {
    if (!result?.content?.markdown || savedNote) return
    createNote.mutate(
      {
        title: result.title,
        content: result.content.markdown,
        note_type: 'ai',
        notebook_id: notebookId,
      },
      { onSuccess: () => mounted.current && setSavedNote(true) },
    )
  }

  // Grounding line: which sources this generation draws from.
  const selCount = selectedSourceIds?.length ?? 0
  const groundingLabel =
    !isReview && selCount > 0
      ? totalSourceCount != null && selCount < totalSourceCount
        ? `Grounded in ${selCount} of ${totalSourceCount} selected ${totalSourceCount === 1 ? 'source' : 'sources'}`
        : `Grounded in ${selCount} ${selCount === 1 ? 'source' : 'sources'}`
      : null

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            {isReview ? reviewItem!.title : `Create from ${notebookTitle || 'this notebook'}`}
          </DialogTitle>
          {groundingLabel && (
            <p className="text-xs text-muted-foreground">{groundingLabel}</p>
          )}
        </DialogHeader>

        {/* Generate mode, no kind chosen → picker */}
        {!isReview && !kind && !loading && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 py-2">
            {KINDS.map((kk) => {
              const Icon = kk.icon
              return (
                <button
                  key={kk.id}
                  onClick={() => runGenerate(kk.id)}
                  className="text-left rounded-xl border border-border bg-card hover:border-primary/50 hover:bg-accent/50 transition p-4"
                >
                  <Icon className="h-5 w-5 mb-2 text-muted-foreground" />
                  <div className="text-sm font-medium">{kk.label}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{kk.desc}</div>
                </button>
              )
            })}
          </div>
        )}

        {(kind || isReview) && (
          <div className="flex-1 overflow-y-auto min-h-0 pr-1">
            {loading && (
              <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
                <LoadingSpinner />
                <span className="text-xs">Generating from your notebook…</span>
              </div>
            )}
            {error && !loading && <div className="text-sm text-destructive py-4">{error}</div>}
            {!loading && result && <ArtifactBody key={result.id} item={result} />}
          </div>
        )}

        {/* Footer */}
        {!loading && (kind || isReview) && result && (
          <div className="flex items-center justify-between pt-2 border-t border-border mt-2">
            {!isReview ? (
              <Button variant="ghost" size="sm" onClick={reset}>
                <RotateCcw className="h-3.5 w-3.5 mr-1.5" /> Choose another
              </Button>
            ) : (
              <span />
            )}
            <div className="flex items-center gap-2">
              {canSaveToNote && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSaveToNote}
                  disabled={createNote.isPending || savedNote}
                >
                  {createNote.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : savedNote ? (
                    <Check className="h-3.5 w-3.5 mr-1.5 text-green-500" />
                  ) : (
                    <StickyNote className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  {savedNote ? 'Saved to notes' : 'Save to note'}
                </Button>
              )}
              {!isReview && kind && (
                <Button size="sm" onClick={() => runGenerate(kind)} disabled={loading}>
                  Regenerate
                </Button>
              )}
            </div>
          </div>
        )}
        {/* Error-state footer (generate mode): allow retry / picking another kind */}
        {!loading && !result && error && !isReview && kind && (
          <div className="flex items-center justify-between pt-2 border-t border-border mt-2">
            <Button variant="ghost" size="sm" onClick={reset}>
              <RotateCcw className="h-3.5 w-3.5 mr-1.5" /> Choose another
            </Button>
            <Button size="sm" onClick={() => runGenerate(kind)}>
              Retry
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
