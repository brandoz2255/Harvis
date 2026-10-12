/** A quiz you take in place: pick answers, see each explanation as you go, get a score at the end, retry. */

import { Button, cn } from '@hermes/plugin-sdk'
import { useState } from 'react'

import type { QuizQuestion } from './notebook-artifacts'

export function Quiz({ questions }: { questions: QuizQuestion[] }) {
  const [picked, setPicked] = useState<Record<number, number>>({})
  const answered = Object.keys(picked).length
  const correct = questions.filter((q, i) => picked[i] === q.answer).length
  const finished = answered === questions.length

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
          {picked[i] !== undefined && (
            <p className="text-xs text-(--ui-text-tertiary)">
              {picked[i] === q.answer ? 'Correct.' : `Not quite. The answer is: ${q.options[q.answer]}.`}
              {q.explanation ? ` ${q.explanation}` : ''}
            </p>
          )}
        </div>
      ))}
      {finished ? (
        <div className="flex items-center gap-2 rounded-lg border bg-(--ui-bg-secondary) p-3 text-sm">
          <span className="flex-1 font-medium">
            You scored {correct} of {questions.length}
          </span>
          <Button onClick={() => setPicked({})} size="sm" variant="outline">
            Try again
          </Button>
        </div>
      ) : (
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
      )}
    </div>
  )
}
