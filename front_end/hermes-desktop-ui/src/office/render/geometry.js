// Office 3D renderer, Isometric projection, colour and text helpers.
// Ported from office-3d v1.4.4 (desktop/plugin.js, commit 127c28a) by oslook and the
// office-3d contributors, MIT licensed: see ../LICENSE. Changes for Harvis: split into
// modules, figure colour comes from entry.color, and a busy bot walking to its desk
// (entry.seated === false) leaves the chair empty.

export const ISO_X = Math.SQRT1_2 // cos(45°) ≈ 0.7071
export const ISO_Y = 0.5          // classic isometric-ish tilt

export function iso(x, y, z, scale) {
  const sx = (x - y) * ISO_X * scale
  const sy = ((x + y) * ISO_Y - z) * scale
  return [sx, sy]
}

// ---------------------------------------------------------------------------
// Color helpers.
// ---------------------------------------------------------------------------
export function hexToRgb(hex) {
  if (!hex || typeof hex !== 'string') return null
  let h = hex.trim()
  // Accept rgb()/rgba() as well as #hex. The palette mixes both — e.g. a sofa
  // base of `shade(accent, -0.4)` is an "rgb(...)" string — and when this only
  // understood #hex the whole shading chain silently no-op'd, leaving the object
  // painted in ONE flat colour (the sofa read as a plain slab for exactly this
  // reason: every face of it ended up the same rgb()).
  if (h[0] !== '#') {
    const m = /^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)/i.exec(h)
    if (!m) return null
    const r = Math.round(parseFloat(m[1]))
    const g = Math.round(parseFloat(m[2]))
    const b = Math.round(parseFloat(m[3]))
    if ([r, g, b].some((v) => Number.isNaN(v))) return null
    return { r, g, b }
  }
  if (h.length === 4) {
    h = '#' + h[1] + h[1] + h[2] + h[2] + h[3] + h[3]
  }
  if (h.length !== 7) return null
  const r = parseInt(h.slice(1, 3), 16)
  const g = parseInt(h.slice(3, 5), 16)
  const b = parseInt(h.slice(5, 7), 16)
  if ([r, g, b].some((v) => Number.isNaN(v))) return null
  return { r, g, b }
}

export function shade(hex, amount) {
  // amount: -1..1 ; negative darkens, positive lightens
  const rgb = hexToRgb(hex)
  if (!rgb) return hex
  const mix = amount >= 0 ? 255 : 0
  const t = Math.abs(amount)
  const r = Math.round(rgb.r + (mix - rgb.r) * t)
  const g = Math.round(rgb.g + (mix - rgb.g) * t)
  const b = Math.round(rgb.b + (mix - rgb.b) * t)
  return 'rgb(' + r + ', ' + g + ', ' + b + ')'
}

export function rgba(hex, a) {
  const rgb = hexToRgb(hex)
  if (!rgb) return hex
  return 'rgba(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ', ' + a + ')'
}

// Match the local Bots roster fallback while keeping profile IDs for routing.
export function profileName(entry) {
  if (typeof entry.display_name === 'string' && entry.display_name.trim()) return entry.display_name.trim()
  const id = entry.profile || ''
  if (id.trim().toLowerCase() === 'default') return 'Hermes'
  return id.replace(/[-_]+/g, ' ').trim().replace(/\b\w/g, ch => ch.toUpperCase())
}

// Darken a profile-hued name ink in LIGHT mode so it stays legible on the
// near-white pill (P.pillColor). In DARK mode the raw profile color is
// already legible on the dark pill, so pass it through unchanged.
export function nameInk(pcolor, P) {
  return P && P.mode === 'light' ? shade(pcolor, -0.45) : pcolor
}

// Format elapsed idle duration compactly.
// <60s  -> "idle 45s"
// <60m  -> "idle 12m"
// else  -> "idle 2h3m"
export function formatIdle(elapsedMs) {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) elapsedMs = 0
  const totalSec = Math.floor(elapsedMs / 1000)
  if (totalSec < 60) return 'idle ' + totalSec + 's'
  const totalMin = Math.floor(totalSec / 60)
  if (totalMin < 60) return 'idle ' + totalMin + 'm'
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return 'idle ' + h + 'h' + m + 'm'
}

// Format a large token count compactly: 1234 -> "1.2k", 1_500_000 -> "1.5M",
// 1_200_000_000 -> "1.2B". Values <1000 render as-is.
export function formatCompact(n) {
  if (!Number.isFinite(n)) return '0'
  const abs = Math.abs(n)
  if (abs < 1000) return String(Math.trunc(n))
  const units = [
    { v: 1e9, s: 'B' },
    { v: 1e6, s: 'M' },
    { v: 1e3, s: 'k' },
  ]
  for (const u of units) {
    if (abs >= u.v) {
      const q = n / u.v
      // 1 decimal, but drop trailing ".0"
      const s = (Math.round(q * 10) / 10).toFixed(1)
      return (s.endsWith('.0') ? s.slice(0, -2) : s) + u.s
    }
  }
  return String(Math.trunc(n))
}

// Draw text with a subtle dark stroke/shadow behind it so it stays legible
// over the floor. Assumes caller has already set font, textAlign, and fillStyle.
export function drawTextWithHalo(c, text, x, y) {
  const prevLineWidth = c.lineWidth
  const prevStroke = c.strokeStyle
  const prevJoin = c.lineJoin
  const prevMiter = c.miterLimit
  c.lineWidth = 3
  c.strokeStyle = 'rgba(0, 0, 0, 0.55)'
  c.lineJoin = 'round'
  c.miterLimit = 2
  c.strokeText(text, x, y)
  c.lineWidth = prevLineWidth
  c.strokeStyle = prevStroke
  c.lineJoin = prevJoin
  c.miterLimit = prevMiter
  c.fillText(text, x, y)
}

// Draw a pill-shaped background badge behind a name label so it stays
// legible over the isometric floor regardless of underlying colors.
//
// Convention: the canvas context is already scale(dpr, dpr) transformed
// in drawFrame(), so all other draw code in this file uses raw CSS-pixel
// units (font "10px ...", lineWidth 1, etc.). We follow the same
// convention here — no explicit dpr multipliers — so the badge scales
// with the rest of the scene automatically.
//
// Caller MUST have already set c.font and c.textAlign = 'center'.
// opts: { fontPx, textColor, borderColor?, dotColor? }
export function drawNameBadge(c, text, cx, y, opts) {
  const fontPx = opts && opts.fontPx ? opts.fontPx : 10
  const padX = 5
  const padY = 2
  const textW = c.measureText(text).width
  const dotR = opts && opts.dotColor ? fontPx * 0.28 : 0
  const dotGap = dotR > 0 ? dotR + 3 : 0
  const innerW = textW + dotGap
  const width = innerW + padX * 2
  const height = fontPx + padY * 2
  const rectX = cx - width / 2
  const rectY = y - height / 2
  const r = height / 2

  // Rounded-rect pill path (inline; no helper exists in this file).
  c.beginPath()
  c.moveTo(rectX + r, rectY)
  c.lineTo(rectX + width - r, rectY)
  c.arcTo(rectX + width, rectY, rectX + width, rectY + r, r)
  c.lineTo(rectX + width, rectY + height - r)
  c.arcTo(rectX + width, rectY + height, rectX + width - r, rectY + height, r)
  c.lineTo(rectX + r, rectY + height)
  c.arcTo(rectX, rectY + height, rectX, rectY + height - r, r)
  c.lineTo(rectX, rectY + r)
  c.arcTo(rectX, rectY, rectX + r, rectY, r)
  c.closePath()

  c.fillStyle = (opts && opts.pillColor) ? opts.pillColor : 'rgba(8, 10, 14, 0.9)'
  c.fill()
  if (opts && opts.borderColor) {
    const prevLW = c.lineWidth
    const prevSS = c.strokeStyle
    c.lineWidth = 1
    c.strokeStyle = opts.borderColor
    c.stroke()
    c.lineWidth = prevLW
    c.strokeStyle = prevSS
  }

  // Optional identity dot on the left inside the pill.
  let textCX = cx
  if (dotR > 0) {
    const dotCX = rectX + padX + dotR
    const dotCY = rectY + height / 2
    const prevFS = c.fillStyle
    c.beginPath()
    c.arc(dotCX, dotCY, dotR, 0, Math.PI * 2)
    c.fillStyle = opts.dotColor
    c.fill()
    c.fillStyle = prevFS
    // Nudge text right so it doesn't collide with the dot.
    textCX = cx + dotGap / 2
  }

  // Draw text last, vertically centered in the pill.
  const prevBaseline = c.textBaseline
  const prevFill = c.fillStyle
  c.textBaseline = 'middle'
  c.fillStyle = opts.textColor
  c.fillText(text, textCX, rectY + height / 2)
  c.textBaseline = prevBaseline
  c.fillStyle = prevFill
}

// ---------------------------------------------------------------------------
// Iso primitives.
// ---------------------------------------------------------------------------
