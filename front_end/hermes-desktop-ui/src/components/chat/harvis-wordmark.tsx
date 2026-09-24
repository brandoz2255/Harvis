import type { CSSProperties } from 'react'

import { cn } from '@/lib/utils'

/**
 * The faces the empty chat's HARVIS cycles through, in order. The first is the
 * original Harvis wordmark (Inter Bold, wide tracking) and is the one shown
 * when the viewer asks for reduced motion. `.harvis-face` keyframes in
 * styles.css assume exactly six entries.
 */
const FACES: ReadonlyArray<CSSProperties> = [
  { fontFamily: "'Harvis Inter', 'Inter', sans-serif", fontWeight: 700, letterSpacing: '0.2em' },
  { fontFamily: "'Collapse', sans-serif", fontWeight: 700, letterSpacing: '0.08em' },
  { fontFamily: "'Rules Expanded', sans-serif", fontWeight: 700, letterSpacing: '0.02em', fontSize: '0.78em' },
  { fontFamily: "'Mondwest', serif", fontWeight: 400, letterSpacing: '0.04em' },
  { fontFamily: "'Neuebit', monospace", fontWeight: 700, letterSpacing: '0.06em', fontSize: '1.15em' },
  { fontFamily: "'Rules Compressed', sans-serif", fontWeight: 500, letterSpacing: '0.1em', fontSize: '1.1em' }
]

/** The empty chat's hero: HARVIS cross-fading through the Harvis faces. */
export function HarvisWordmark({ className, text = 'Harvis' }: { className?: string; text?: string }) {
  return (
    <p aria-label={text} className={cn('harvis-cycle m-0', className)} role="img">
      {FACES.map((face, index) => (
        <span
          aria-hidden="true"
          key={index}
          style={{ ...face, '--harvis-cycle-count': FACES.length, '--harvis-cycle-index': index } as CSSProperties}
        >
          {text}
        </span>
      ))}
    </p>
  )
}

/** The Harvis name as a label (titlebar corner): the original wordmark face. */
export function HarvisName({ className }: { className?: string }) {
  return <span className={cn('harvis-name select-none text-foreground', className)}>Harvis</span>
}
