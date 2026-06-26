'use client'

import { useState } from 'react'
import type { Flashcard } from '@/lib/api/artifacts'

/** Click-to-flip study flashcards. */
export function FlashcardsView({ cards }: { cards: Flashcard[] }) {
  const [flipped, setFlipped] = useState<Record<number, boolean>>({})

  const list = (Array.isArray(cards) ? cards : []).filter((c) => c && (c.front || c.back))

  if (list.length === 0) {
    return <div className="text-sm text-muted-foreground py-4">These flashcards couldn’t be displayed — try regenerating.</div>
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 py-1">
      {list.map((c, ci) => (
        <button
          key={ci}
          onClick={() => setFlipped((f) => ({ ...f, [ci]: !f[ci] }))}
          className="text-left rounded-xl border border-border bg-card hover:border-primary/40 transition p-4 min-h-[110px] flex flex-col"
        >
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
            {flipped[ci] ? 'Back' : 'Front'}
          </div>
          <div className="text-sm flex-1">{flipped[ci] ? c.back : c.front}</div>
          <div className="text-[10px] text-muted-foreground mt-2 opacity-70">Click to flip</div>
        </button>
      ))}
    </div>
  )
}
