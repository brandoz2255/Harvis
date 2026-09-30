import { type CSSProperties, useEffect, useState } from 'react'

import { useMediaQuery } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'

/**
 * The faces the empty chat's HARVIS cycles through, in order. The first is the
 * original Harvis wordmark (Inter Bold, wide tracking) and is the one shown
 * when the viewer asks for reduced motion.
 */
const FACES: ReadonlyArray<CSSProperties> = [
  { fontFamily: "'Harvis Inter', 'Inter', sans-serif", fontWeight: 700, letterSpacing: '0.2em' },
  { fontFamily: "'Collapse', sans-serif", fontWeight: 700, letterSpacing: '0.08em' },
  { fontFamily: "'Rules Expanded', sans-serif", fontWeight: 700, letterSpacing: '0.02em', fontSize: '0.78em' },
  { fontFamily: "'Mondwest', serif", fontWeight: 400, letterSpacing: '0.04em' },
  { fontFamily: "'Neuebit', monospace", fontWeight: 700, letterSpacing: '0.06em', fontSize: '1.15em' },
  { fontFamily: "'Rules Compressed', sans-serif", fontWeight: 500, letterSpacing: '0.1em', fontSize: '1.1em' }
]

/**
 * How each change of face plays, taken in turn. Five against six faces, so the
 * pairings drift and the same face rarely arrives the same way twice. Each has
 * keyframes under `.harvis-cycle[data-transition=…]` in styles.css; `scramble`
 * also decodes the letters here.
 */
const TRANSITIONS = ['flip', 'glitch', 'rise', 'scramble', 'wipe'] as const

type Transition = (typeof TRANSITIONS)[number]

type Phase = 'in' | 'out' | 'rest'

const HOLD_MS = 4200
const SCRAMBLE_MS = 750
// Redraw the noise at ~22 fps: every frame is a blur, not a decode.
const SCRAMBLE_FRAME_MS = 45
const GLYPHS = '#%&@*+=/<>?!$01'

const noise = () => GLYPHS[Math.floor(Math.random() * GLYPHS.length)]

/** Letters resolve left to right; the ones not yet settled show noise. */
const scrambled = (text: string, progress: number) =>
  Array.from(text, (ch, i) => (progress > (i + 1) / (text.length + 1) ? ch : noise())).join('')

function useScramble(text: string, active: boolean): string {
  const [shown, setShown] = useState(() => (active ? scrambled(text, 0) : text))

  useEffect(() => {
    if (!active) {
      setShown(text)

      return
    }

    const start = performance.now()
    let last = 0
    let frame = 0

    const tick = (now: number) => {
      const progress = (now - start) / SCRAMBLE_MS

      if (progress >= 1) {
        setShown(text)

        return
      }

      if (now - last >= SCRAMBLE_FRAME_MS) {
        last = now
        setShown(scrambled(text, progress))
      }

      frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(frame)
  }, [text, active])

  return shown
}

function FaceLayer({
  face,
  phase,
  text,
  transition
}: {
  face: CSSProperties
  phase: Phase
  text: string
  transition: Transition
}) {
  const shown = useScramble(text, phase === 'in' && transition === 'scramble')

  return (
    <span aria-hidden="true" className="harvis-face" data-phase={phase} style={face}>
      {Array.from(shown, (ch, i) => (
        <span className="harvis-letter" key={i} style={{ '--i': i } as CSSProperties}>
          {ch}
        </span>
      ))}
    </span>
  )
}

/** The empty chat's hero: HARVIS changing face, a different way each time. */
export function HarvisWordmark({ className, text = 'Harvis' }: { className?: string; text?: string }) {
  const still = useMediaQuery('(prefers-reduced-motion: reduce)')
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (still) {
      return
    }

    const id = window.setInterval(() => setStep(s => s + 1), HOLD_MS)

    return () => window.clearInterval(id)
  }, [still])

  const at = still ? 0 : step
  const transition = TRANSITIONS[(at + TRANSITIONS.length - 1) % TRANSITIONS.length]

  // Fresh keys every step, so both layers remount and their animations replay.
  return (
    <p
      aria-label={text}
      className={cn('harvis-cycle m-0', className)}
      data-transition={at ? transition : undefined}
      role="img"
    >
      {at > 0 && (
        <FaceLayer
          face={FACES[(at - 1) % FACES.length]}
          key={`out-${at}`}
          phase="out"
          text={text}
          transition={transition}
        />
      )}
      <FaceLayer
        face={FACES[at % FACES.length]}
        key={`in-${at}`}
        phase={at ? 'in' : 'rest'}
        text={text}
        transition={transition}
      />
    </p>
  )
}

/** The Harvis name as a label (titlebar corner): the original wordmark face. */
export function HarvisName({ className }: { className?: string }) {
  return <span className={cn('harvis-name select-none text-foreground', className)}>Harvis</span>
}
