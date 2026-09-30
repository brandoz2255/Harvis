/**
 * Review one generated artifact in the Studio rail: a quiz you can take, a deck
 * of flashcards you can flip, or a Markdown report you can keep as a note.
 */

import { Button, cn, Codicon, Streamdown, useQueryClient } from '@hermes/plugin-sdk'
import { useState } from 'react'

import type { Artifact, Flashcard, QuizQuestion } from './notebook-artifacts'
import { createNote, listKey, notesKey, statsKey } from './notebook-shared'

function Quiz({ questions }: { questions: QuizQuestion[] }) {
  const [picked, setPicked] = useState<Record<number, number>>({})
  const answered = Object.keys(picked).length
  const correct = questions.filter((q, i) => picked[i] === q.answer).length

  return (
    <div className="space-y-4">
      {questions.map((q, i) => (
        <div className="space-y-1.5" key={i}>
          <p className="text-sm font-medium">
            {i + 1}. {q.q}
          </p>
          <div className="grid gap-1">
            {q.options.map((option, j) => {
              const chosen = picked[i] === j
              const reveal = picked[i] !== undefined

              return (
                <button
                  className={cn(
                    'rounded-md border px-2.5 py-1.5 text-left text-xs transition',
                    !reveal && 'hover:bg-(--ui-bg-tertiary)',
                    reveal && j === q.answer && 'border-emerald-500/60 bg-emerald-500/10',
                    reveal && chosen && j !== q.answer && 'border-destructive/60 bg-destructive/10'
                  )}
                  disabled={reveal}
                  key={j}
                  onClick={() => setPicked(prev => ({ ...prev, [i]: j }))}
                  type="button"
                >
                  {option}
                </button>
              )
            })}
          </div>
          {picked[i] !== undefined && q.explanation && (
            <p className="text-xs text-(--ui-text-tertiary)">{q.explanation}</p>
          )}
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
        <span className="flex-1">
          {answered === 0 ? 'Pick an answer to check it.' : `${correct} of ${answered} right so far`}
        </span>
        {answered > 0 && (
          <Button onClick={() => setPicked({})} size="xs" variant="ghost">
            Start over
          </Button>
        )}
      </div>
    </div>
  )
}

function Flashcards({ cards }: { cards: Flashcard[] }) {
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const card = cards[index]

  const go = (next: number) => {
    setIndex((next + cards.length) % cards.length)
    setFlipped(false)
  }

  return (
    <div className="space-y-2">
      <button
        aria-label={flipped ? 'Show the front' : 'Show the answer'}
        className="flex min-h-40 w-full items-center justify-center rounded-lg border bg-(--ui-bg-secondary) p-4 text-center text-sm transition hover:border-(--ui-stroke-secondary)"
        onClick={() => setFlipped(f => !f)}
        type="button"
      >
        <span className={cn(flipped ? 'text-(--ui-text-secondary)' : 'font-medium')}>
          {flipped ? card.back : card.front}
        </span>
      </button>
      <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
        <Button aria-label="Previous card" onClick={() => go(index - 1)} size="xs" variant="ghost">
          <Codicon name="chevron-left" size="0.8rem" />
        </Button>
        <span className="flex-1 text-center">
          {index + 1} / {cards.length} · {flipped ? 'answer' : 'tap to flip'}
        </span>
        <Button aria-label="Next card" onClick={() => go(index + 1)} size="xs" variant="ghost">
          <Codicon name="chevron-right" size="0.8rem" />
        </Button>
      </div>
    </div>
  )
}

function KeepReport({ artifact, notebookId }: { artifact: Artifact; notebookId: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<'error' | 'idle' | 'saved' | 'saving'>('idle')

  return (
    <Button
      disabled={state !== 'idle'}
      onClick={async () => {
        setState('saving')

        try {
          await createNote(notebookId, {
            content: artifact.content?.markdown ?? '',
            title: artifact.title,
            type: 'ai_note'
          })
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

export function ArtifactView({
  artifact,
  notebookId,
  onBack
}: {
  artifact: Artifact
  notebookId: string
  onBack: () => void
}) {
  const content = artifact.content ?? {}

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Button aria-label="Back to Studio" onClick={onBack} size="xs" variant="ghost">
          <Codicon name="arrow-left" size="0.8rem" />
        </Button>
        <h4 className="min-w-0 flex-1 truncate text-sm font-semibold">{artifact.title}</h4>
      </div>
      {content.questions?.length ? (
        <Quiz questions={content.questions} />
      ) : content.cards?.length ? (
        <Flashcards cards={content.cards} />
      ) : content.markdown ? (
        <>
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Streamdown mode="static">{content.markdown}</Streamdown>
          </div>
          <KeepReport artifact={artifact} notebookId={notebookId} />
        </>
      ) : (
        <p className="text-xs text-(--ui-text-tertiary)">This item has nothing to show.</p>
      )}
    </div>
  )
}
