import type { ConnectionState } from '@hermes/shared'
import { useStore } from '@nanostores/react'
import { useEffect, useId, useRef, useState } from 'react'

import { useMediaQuery } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'
import { $petState, type PetState } from '@/store/pet'
import { $gatewayState } from '@/store/session'

// The Harvis mark (public/harvis-logo.svg) drawn inline so its eyes can move.
// Every pose is a CSS transform on the eyes (styles.css, `.hv-face`), so a
// change of mood glides instead of snapping. Same geometry as the PNG, so the
// static mark and the live face read as one character.

export type FaceMood = 'idle' | 'thinking' | 'working' | 'waiting' | 'success' | 'error' | 'sleeping'
type Pose = 'center' | 'left' | 'right' | 'wave'
type Poke = 'startled' | 'angry' | null

// The chat's activity signals (the same ones the desktop pet reads), as moods.
const MOOD_FROM_PET: Record<PetState, FaceMood> = {
  failed: 'error',
  idle: 'idle',
  jump: 'success',
  review: 'thinking',
  run: 'working',
  waiting: 'waiting',
  wave: 'success'
}

// The old empty-chat mascot's idle beat: look around, then wave, one step every 2 s.
const IDLE_CYCLE: readonly Pose[] = ['center', 'left', 'center', 'right', 'center', 'wave']
const IDLE_STEP_MS = 2000
const STARTLE_MS = 300
const ANGRY_MS = 1000
const ANGRY_CLICKS = 4
const CLICK_WINDOW_MS = 1500

export function harvisFaceMood(pet: PetState, gateway: ConnectionState): FaceMood {
  // Lost the gateway: nothing can answer, so it dozes. ('idle' is before the first connect.)
  if (gateway === 'closed' || gateway === 'error') {
    return 'sleeping'
  }

  return MOOD_FROM_PET[pet] ?? 'idle'
}

export interface HarvisFaceProps {
  /** Fixed mood. Leave unset with `live` to follow the chat. */
  mood?: FaceMood
  /** Follow the chat's activity and the gateway connection. */
  live?: boolean
  /** Clicks startle it; four quick clicks make it cross. */
  interactive?: boolean
  className?: string
  label?: string
}

export function HarvisFace({ mood, live = false, interactive = false, className, label = 'Harvis' }: HarvisFaceProps) {
  const pet = useStore($petState)
  const gateway = useStore($gatewayState)
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const resolved: FaceMood = mood ?? (live ? harvisFaceMood(pet, gateway) : 'idle')
  const [pose, setPose] = useState<Pose>('center')
  const [poke, setPoke] = useState<Poke>(null)
  const clicks = useRef<number[]>([])
  const pokeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const uid = useId().replace(/:/g, '')

  useEffect(() => {
    setPose('center')

    if (resolved !== 'idle' || reduceMotion) {
      return
    }

    let step = 0

    const id = window.setInterval(() => {
      // A background window keeps its place in the cycle instead of animating unseen.
      if (document.hidden) {
        return
      }

      step = (step + 1) % IDLE_CYCLE.length
      setPose(IDLE_CYCLE[step])
    }, IDLE_STEP_MS)

    return () => window.clearInterval(id)
  }, [resolved, reduceMotion])

  useEffect(() => () => clearTimeout(pokeTimer.current), [])

  const onPoke = () => {
    // Stays cross for its full second; extra clicks don't downgrade it to a startle.
    if (poke === 'angry') {
      return
    }

    const now = Date.now()
    clicks.current = [...clicks.current.filter(t => now - t < CLICK_WINDOW_MS), now]
    const angry = clicks.current.length >= ANGRY_CLICKS

    if (angry) {
      clicks.current = []
    }

    setPoke(angry ? 'angry' : 'startled')
    clearTimeout(pokeTimer.current)
    pokeTimer.current = setTimeout(() => setPoke(null), angry ? ANGRY_MS : STARTLE_MS)
  }

  const face = (
    <svg aria-hidden="true" viewBox="0 0 512 512">
      <defs>
        <linearGradient id={`${uid}-bezel`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#6f9bff" />
          <stop offset="1" stopColor="#3a63e0" />
        </linearGradient>
        <linearGradient id={`${uid}-screen`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#1b2a55" />
          <stop offset="1" stopColor="#0e1630" />
        </linearGradient>
        <filter height="180%" id={`${uid}-glow`} width="220%" x="-60%" y="-40%">
          <feGaussianBlur result="b" stdDeviation="9" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g className="hv-body">
        <rect fill={`url(#${uid}-bezel)`} height="384" rx="104" width="416" x="48" y="64" />
        <rect fill={`url(#${uid}-screen)`} height="304" rx="72" width="336" x="88" y="104" />
        <g className="hv-look">
          <g className="hv-blink">
            <g className="hv-eyes" filter={`url(#${uid}-glow)`}>
              <rect className="hv-eye hv-eye-l" height="112" rx="24" width="48" x="170" y="200" />
              <rect className="hv-eye hv-eye-r" height="112" rx="24" width="48" x="294" y="200" />
            </g>
          </g>
        </g>
      </g>
    </svg>
  )

  const shared = {
    'aria-label': label,
    className: cn('hv-face size-14 shrink-0', interactive && 'pointer-events-auto cursor-pointer', className),
    'data-mood': resolved,
    'data-poke': poke ?? undefined,
    'data-pose': pose
  }

  if (interactive) {
    return (
      <button {...shared} onClick={onPoke} type="button">
        {face}
      </button>
    )
  }

  return (
    <span {...shared} role="img">
      {face}
    </span>
  )
}
