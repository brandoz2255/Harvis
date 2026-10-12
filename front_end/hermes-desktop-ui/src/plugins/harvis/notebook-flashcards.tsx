/**
 * A flashcard deck you study in place. Click the card or press Space to flip it,
 * arrows (or the buttons) to move, Shuffle to mix the deck. "Got it" takes a card
 * out of the pile; "Again" sends it to the back to come round once more. When the
 * pile is empty the deck is done and can be studied again.
 */

import { Button, cn, Codicon } from '@hermes/plugin-sdk'
import { type KeyboardEvent, useState } from 'react'

import type { Flashcard } from './notebook-artifacts'

export const shuffled = <T,>(items: T[], random: () => number = Math.random): T[] => {
  const out = [...items]

  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }

  return out
}

const order = (n: number) => Array.from({ length: n }, (_, i) => i)

export function Flashcards({ cards }: { cards: Flashcard[] }) {
  const [queue, setQueue] = useState<number[]>(() => order(cards.length))
  const [at, setAt] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [known, setKnown] = useState(0)
  const [rounds, setRounds] = useState(0)

  if (queue.length === 0) {
    return (
      <div className="space-y-2 rounded-lg border bg-(--ui-bg-secondary) p-4 text-center text-sm">
        <p className="font-medium">
          Done. You knew all {cards.length} card{cards.length === 1 ? '' : 's'}.
        </p>
        {rounds > 0 && (
          <p className="text-xs text-(--ui-text-tertiary)">
            {rounds} time{rounds === 1 ? '' : 's'} a card came back for another look.
          </p>
        )}
        <Button
          onClick={() => {
            setQueue(order(cards.length))
            setAt(0)
            setKnown(0)
            setRounds(0)
            setFlipped(false)
          }}
          size="sm"
          variant="outline"
        >
          Study again
        </Button>
      </div>
    )
  }

  const index = Math.min(at, queue.length - 1)
  const card = cards[queue[index]]

  const go = (next: number) => {
    setAt((next + queue.length) % queue.length)
    setFlipped(false)
  }

  const gotIt = () => {
    const rest = queue.filter((_, i) => i !== index)
    setQueue(rest)
    setAt(Math.min(index, Math.max(rest.length - 1, 0)))
    setKnown(k => k + 1)
    setFlipped(false)
  }

  const again = () => {
    setQueue([...queue.filter((_, i) => i !== index), queue[index]])
    setAt(Math.min(index, queue.length - 1))
    setRounds(r => r + 1)
    setFlipped(false)
  }

  const shuffle = () => {
    setQueue(q => shuffled(q))
    setAt(0)
    setFlipped(false)
  }

  const onKey = (event: KeyboardEvent) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault()
      setFlipped(f => !f)
    } else if (event.key === 'ArrowRight') {
      go(index + 1)
    } else if (event.key === 'ArrowLeft') {
      go(index - 1)
    }
  }

  return (
    <div className="space-y-2">
      <div
        aria-label={flipped ? 'Show the front' : 'Show the answer'}
        className="flex min-h-40 w-full cursor-pointer items-center justify-center rounded-lg border bg-(--ui-bg-secondary) p-4 text-center text-sm transition outline-none hover:border-(--ui-stroke-secondary) focus-visible:ring-2"
        onClick={() => setFlipped(f => !f)}
        onKeyDown={onKey}
        role="button"
        tabIndex={0}
      >
        <span className={cn(flipped ? 'text-(--ui-text-secondary)' : 'font-medium')}>
          {flipped ? card.back : card.front}
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)">
        <Button aria-label="Previous card" onClick={() => go(index - 1)} size="xs" variant="ghost">
          <Codicon name="chevron-left" size="0.8rem" />
        </Button>
        <span className="flex-1 text-center">
          {index + 1} of {queue.length} left · {known} known · {flipped ? 'answer' : 'click or press Space to flip'}
        </span>
        <Button aria-label="Next card" onClick={() => go(index + 1)} size="xs" variant="ghost">
          <Codicon name="chevron-right" size="0.8rem" />
        </Button>
      </div>
      <div className="flex items-center gap-1.5">
        <Button disabled={!flipped} onClick={again} size="sm" variant="outline">
          Again
        </Button>
        <Button disabled={!flipped} onClick={gotIt} size="sm">
          Got it
        </Button>
        <span className="flex-1" />
        <Button onClick={shuffle} size="xs" variant="ghost">
          <Codicon name="arrow-swap" size="0.8rem" /> Shuffle
        </Button>
      </div>
    </div>
  )
}
