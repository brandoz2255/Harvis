'use client'

import { useState } from 'react'
import { Check, X } from 'lucide-react'
import type { QuizQuestion } from '@/lib/api/artifacts'

/** Interactive multiple-choice quiz: pick an option → reveal correct/wrong + explanation. */
export function QuizView({ questions }: { questions: QuizQuestion[] }) {
  const [picked, setPicked] = useState<Record<number, number>>({})

  // Defensive: never let a malformed question crash the whole page.
  const list = (Array.isArray(questions) ? questions : []).filter(
    (q) => q && typeof q.q === 'string' && Array.isArray(q.options) && q.options.length > 0,
  )

  if (list.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">This quiz couldn’t be displayed — try regenerating.</div>
  }

  return (
    <div className="space-y-3 py-1">
      {list.map((q, qi) => (
        <div key={qi} className="rounded-xl border border-border bg-card p-4">
          <div className="text-sm font-medium mb-2">
            {qi + 1}. {q.q}
          </div>
          <div className="space-y-1.5">
            {q.options.map((opt, oi) => {
              const answered = picked[qi] !== undefined
              const isCorrect = oi === q.answer
              const isPicked = picked[qi] === oi
              let cls = 'border-border hover:bg-accent/50'
              if (answered && isCorrect)
                cls = 'border-green-500/50 bg-green-500/10 text-green-700 dark:text-green-300'
              else if (answered && isPicked)
                cls = 'border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-300'
              else if (answered) cls = 'border-border opacity-60'
              return (
                <button
                  key={oi}
                  disabled={answered}
                  onClick={() => setPicked((p) => ({ ...p, [qi]: oi }))}
                  className={`w-full text-left text-sm rounded-lg border px-3 py-2 transition flex items-center gap-2 ${cls}`}
                >
                  <span className="font-mono text-xs opacity-70">{String.fromCharCode(65 + oi)}</span>
                  <span className="flex-1">{opt}</span>
                  {answered && isCorrect && <Check className="h-4 w-4 shrink-0" />}
                  {answered && isPicked && !isCorrect && <X className="h-4 w-4 shrink-0" />}
                </button>
              )
            })}
          </div>
          {picked[qi] !== undefined && q.explanation && (
            <div className="text-xs text-muted-foreground mt-2 border-t border-border pt-2">
              {q.explanation}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
