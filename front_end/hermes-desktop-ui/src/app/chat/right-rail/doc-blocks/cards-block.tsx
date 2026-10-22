import { useMemo } from 'react'

import { parseCardsBlock } from '@/lib/harvis-doc-blocks'

import { BlockFrame } from './block-frame'

/** Numbered cards: accent number badge, bold title, a highlighted line (address, owner) and a detail line. */
export function CardsBlock({ code }: { code: string }) {
  const { cards, title } = useMemo(() => parseCardsBlock(code), [code])

  if (!cards.length) {
    return null
  }

  return (
    <BlockFrame kind="cards" title={title}>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-2.5">
        {cards.map((card, i) => (
          <li
            className="relative min-w-0 rounded-lg border border-border bg-card p-3 pt-3.5 shadow-xs"
            data-slot="doc-card"
            key={i}
          >
            <span
              aria-hidden
              className="absolute -top-2 -left-1.5 grid size-5 place-items-center rounded-full bg-primary text-[0.65rem] font-semibold tabular-nums text-primary-foreground"
            >
              {i + 1}
            </span>
            <div className="text-[0.9em] font-semibold leading-snug wrap-anywhere">{card.title}</div>
            {card.highlight && (
              <div className="mt-0.5 font-mono text-[0.78em] text-primary wrap-anywhere">{card.highlight}</div>
            )}
            {card.detail && <div className="mt-1 text-[0.78em] leading-snug text-muted-foreground">{card.detail}</div>}
          </li>
        ))}
      </ul>
    </BlockFrame>
  )
}
