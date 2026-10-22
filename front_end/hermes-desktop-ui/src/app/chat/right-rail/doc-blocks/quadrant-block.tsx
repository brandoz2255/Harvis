import { useMemo } from 'react'

import { parseQuadrant } from '@/lib/harvis-doc-blocks'
import { cn } from '@/lib/utils'

import { BlockFrame } from './block-frame'

/** 2x2 priority grid: x grows right, y grows up, so the top-left cell is high y / low x. */
export function QuadrantBlock({ code }: { code: string }) {
  const quadrant = useMemo(() => parseQuadrant(code), [code])

  if (!quadrant.cells.some(c => c.name || c.items.length)) {
    return null
  }

  return (
    <BlockFrame kind="quadrant" title={quadrant.title}>
      <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1.5">
        <div
          className="row-start-1 flex items-center justify-center text-[0.7em] font-medium text-muted-foreground [writing-mode:vertical-rl] rotate-180"
          data-slot="quadrant-axis-y"
        >
          {quadrant.y ? `${quadrant.y} →` : ''}
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          {quadrant.cells.map((cell, i) => (
            <div
              className={cn(
                'min-h-24 min-w-0 rounded-md border p-2.5',
                i === 0 ? 'border-primary/30 bg-primary/8' : 'border-border/70 bg-muted/30'
              )}
              data-slot="quadrant-cell"
              key={i}
            >
              <div className={cn('mb-1 text-[0.8em] font-semibold', i === 0 && 'text-primary')}>{cell.name}</div>
              {cell.items.length > 0 && (
                <ul className="grid gap-0.5 text-[0.8em] leading-snug text-foreground/85">
                  {cell.items.map((item, j) => (
                    <li className="flex gap-1.5" key={j}>
                      <span aria-hidden className="mt-[0.45em] size-1 shrink-0 rounded-full bg-current/50" />
                      <span className="min-w-0 wrap-anywhere">{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
        <div
          className="col-start-2 text-center text-[0.7em] font-medium text-muted-foreground"
          data-slot="quadrant-axis-x"
        >
          {quadrant.x ? `${quadrant.x} →` : ''}
        </div>
      </div>
    </BlockFrame>
  )
}
