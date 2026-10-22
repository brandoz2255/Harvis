import { useEffect, useRef } from 'react'

import { useMediaQuery } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'

/** Sparse to dense. Index 0 is a blank cell, so low noise leaves open ground. */
const RAMP = ' .,:;-=+*#%@'
const FONT_PX = 9
const FRAME_MS = 80
// While a ripple is moving the field redraws at ~30 fps so the ring reads as motion.
const RIPPLE_FRAME_MS = 33
// Two-octave value noise sits in a narrow band (median ~0.49, 90th pct ~0.67).
// Below FLOOR draws nothing, so about a quarter of cells carry a glyph and the
// field reads as drifting patches, not a wall of text; CEIL maps to full density.
const FLOOR = 0.58
const CEIL = 0.8

const RIPPLE_MS = 1400
const RIPPLE_PX_PER_MS = 0.75
const RIPPLE_BAND_PX = 34
const RIPPLE_COLOR = '#3b8bff'
const MAX_RIPPLES = 4

function hash(x: number, y: number, z: number): number {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 2147483647)
  h = Math.imul(h ^ (h >>> 13), 1274126177)

  return ((h ^ (h >>> 16)) >>> 0) / 4294967295
}

const fade = (t: number) => t * t * (3 - 2 * t)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

const smoothstep = (edge0: number, edge1: number, x: number) =>
  fade(Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0))))

function valueNoise(x: number, y: number, z: number): number {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const zi = Math.floor(z)
  const u = fade(x - xi)
  const v = fade(y - yi)
  const w = fade(z - zi)

  const plane = (k: number) =>
    lerp(
      lerp(hash(xi, yi, k), hash(xi + 1, yi, k), u),
      lerp(hash(xi, yi + 1, k), hash(xi + 1, yi + 1, k), u),
      v
    )

  return lerp(plane(zi), plane(zi + 1), w)
}

/** Density in [0, 1] for one cell at time `t` (seconds). Pure, so it is testable. */
export function fieldDensity(col: number, row: number, t: number): number {
  const n =
    valueNoise(col * 0.045, row * 0.09, t * 0.08) * 0.7 + valueNoise(col * 0.16, row * 0.32, t * 0.25) * 0.3

  return Math.min(1, Math.max(0, (n - FLOOR) / (CEIL - FLOOR)))
}

/** The glyph and opacity a density draws as; blank cells return null. */
export function glyphFor(density: number): null | { alpha: number; glyph: string } {
  const index = Math.min(RAMP.length - 1, Math.floor(density * RAMP.length))

  if (index <= 0) {
    return null
  }

  return { alpha: 0.12 + density * 0.38, glyph: RAMP[index] }
}

/**
 * How strongly a ripple lights a point `distance` px from where it was clicked,
 * `age` ms after the click: a ring that grows outward and fades as it goes.
 */
export function rippleStrength(distance: number, age: number): number {
  if (age < 0 || age >= RIPPLE_MS) {
    return 0
  }

  const ring = 1 - Math.abs(distance - age * RIPPLE_PX_PER_MS) / RIPPLE_BAND_PX

  return ring <= 0 ? 0 : ring * (1 - age / RIPPLE_MS)
}

type Ripple = { x: number; y: number; at: number }

/**
 * A drifting field of dim characters, painted on a canvas (a full screen is
 * ~20k cells, which only a canvas redraws cheaply). It paints in the element's
 * own `color`, so the theme decides the ink. A click anywhere over it sends a
 * blue ring out through the characters, even when the click lands on content
 * stacked above it.
 *
 * `clear` keeps an oval in the middle empty for whatever sits on top: 0 fills
 * edge to edge, 0.2 leaves roughly the middle fifth bare. Ripples ignore it.
 *
 * Reduced motion gets one still frame and no ripples; a hidden tab stops the loop.
 */
export function AsciiField({ className, clear = 0 }: { className?: string; clear?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const still = useMediaQuery('(prefers-reduced-motion: reduce)')

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')

    if (!canvas || !ctx) {
      return
    }

    let width = 0
    let height = 0
    let raf = 0
    let last = -Infinity
    let ripples: Ripple[] = []
    const start = performance.now()

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const draw = (now: number) => {
      const t = (now - start) / 1000
      const cellW = FONT_PX * 0.62
      const cellH = FONT_PX * 1.15
      const cols = Math.ceil(width / cellW)
      const rows = Math.ceil(height / cellH)
      const ink = getComputedStyle(canvas).color
      ripples = ripples.filter(r => now - r.at < RIPPLE_MS)

      ctx.clearRect(0, 0, width, height)
      ctx.font = `${FONT_PX}px ui-monospace, 'SF Mono', Menlo, monospace`
      ctx.textBaseline = 'top'

      for (let row = 0; row < rows; row++) {
        const y = row * cellH
        const ny = (y + cellH / 2 - height / 2) / (height / 2)

        for (let col = 0; col < cols; col++) {
          const x = col * cellW

          let wave = 0

          for (const r of ripples) {
            wave = Math.max(wave, rippleStrength(Math.hypot(x - r.x, y - r.y), now - r.at))
          }

          if (wave > 0.05) {
            ctx.fillStyle = RIPPLE_COLOR
            ctx.globalAlpha = 0.25 + wave * 0.7
            ctx.fillText(RAMP[Math.max(1, Math.ceil(wave * (RAMP.length - 1)))], x, y)

            continue
          }

          const cell = glyphFor(fieldDensity(col, row, t))

          if (!cell) {
            continue
          }

          const nx = (x + cellW / 2 - width / 2) / (width / 2)
          // Same falloff as a CSS `radial-gradient(ellipse at center, …)`: 1 at a corner.
          const edge = clear > 0 ? smoothstep(clear, clear + 0.55, Math.hypot(nx, ny) / Math.SQRT2) : 1

          if (edge > 0.02) {
            ctx.fillStyle = ink
            ctx.globalAlpha = cell.alpha * edge
            ctx.fillText(cell.glyph, x, y)
          }
        }
      }

      ctx.globalAlpha = 1
    }

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop)

      if (document.hidden || now - last < (ripples.length ? RIPPLE_FRAME_MS : FRAME_MS)) {
        return
      }

      last = now
      draw(now)
    }

    const onPointerDown = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      const x = event.clientX - rect.left
      const y = event.clientY - rect.top

      if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
        return
      }

      ripples = [...ripples, { x, y, at: performance.now() }].slice(-MAX_RIPPLES)
      last = -Infinity
    }

    const observer = new ResizeObserver(() => {
      resize()
      draw(performance.now())
    })

    observer.observe(canvas)
    resize()

    if (still) {
      draw(start)
    } else {
      raf = requestAnimationFrame(loop)
      // Capture: content above the field may stop propagation of its own clicks.
      window.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true })
    }

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      window.removeEventListener('pointerdown', onPointerDown, { capture: true })
    }
  }, [clear, still])

  return (
    <canvas
      aria-hidden
      className={cn('pointer-events-none h-full w-full text-muted-foreground', className)}
      data-slot="ascii-field"
      ref={canvasRef}
    />
  )
}
