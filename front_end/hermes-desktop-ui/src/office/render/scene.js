// Office 3D renderer, Theme palette, selection mat, floors and lounge furniture.
// Ported from office-3d v1.4.4 (desktop/plugin.js, commit 127c28a) by oslook and the
// office-3d contributors, MIT licensed: see ../LICENSE. Changes for Harvis: split into
// modules, figure colour comes from entry.color, and a busy bot walking to its desk
// (entry.seated === false) leaves the chair empty.

import { iso, rgba, shade } from './geometry.js'
import { drawCylinder, drawIsoBoxSoft, softShadow } from './shapes.js'
import { DESK_D, DESK_W } from './layout.js'

export function buildPalette(canvas) {
  const cs = getComputedStyle(canvas)
  const accentDark = (cs.getPropertyValue('--ui-accent') || '#4c9aff').trim() || '#4c9aff'
  const accentLight = (cs.getPropertyValue('--ui-accent') || '#2563eb').trim() || '#2563eb'
  // FOLLOW THE HOST THEME via the definitive signal: Hermes toggles a `.dark`
  // class on document.documentElement (:root.dark in styles.css, Tailwind
  // darkMode:class). No color parsing / luminance guessing needed.
  let isDark = true
  try {
    isDark = document.documentElement.classList.contains('dark')
  } catch (e) {
    isDark = true
  }
  const isLight = !isDark
  if (isLight) {
    return {
      mode: 'light',
      bg: '#f4f5f7',
      stroke: '#c9ced6',
      textSec: '#3a3f45',
      textTer: '#6b7280',
      textQuat: '#9aa1ab',
      accent: accentLight,
      // Floor overlays: dark-tinted rgba on light bg so zones read.
      floorWorkFill: 'rgba(20, 24, 32, 0.05)',
      floorLoungeFill: 'rgba(20, 24, 32, 0.09)',
      // Furniture (lighter greys for chair + monitor body on light bg).
      chairTop: '#c3c8d0',
      chairBackTop: '#cfd4dc',
      chairPost: '#9aa1ab',
      chairBase: '#aeb4be',
      monitorShell: '#c6cbd3',
      keyboard: '#b6bcc6',
      deskWood: '#c9a876',
      screenOff: '#dfe3e8',
      screenOffGlow: '#e8ecf1',
      // Screen ON base/glow — cool but LIGHT-tinted so the terminal-green
      // content still reads and the monitor doesn't look muddy on the light bg.
      screenOnBase: '#b7ccd4',
      screenOnGlow: '#cfe0e6',
      stool: '#b0b6c0',
      // Screen-on green (slightly darker on light bg for contrast).
      screenGreenBusy: '#1f9d57',
      screenGreenIdle: '#178a49',
      // Name pill: light with subtle border and dark text.
      pillColor: 'rgba(255, 255, 255, 0.85)',
      pillBorder: 'rgba(0, 0, 0, 0.15)',
      offlineNameColor: '#9aa1ab',
      // Figure tones (skin/hair/trousers are neutral so the profile-colored
      // clothes still carry identity; only the person is ever profile-hued).
      skin: '#f2c69d',
      skinShadow: '#cf9a63',
      hair: '#3b2c22',
      hairLit: '#5b4433',
      trouser: '#7d879a',
      shoe: '#40464f',
      shadowInk: '#232a36',
    }
  }
  // DARK (default; keeps existing look).
  const cs2 = cs
  return {
    mode: 'dark',
    bg: ((cs2.getPropertyValue('--ui-bg') || '#0b0d10').trim() || '#0b0d10'),
    stroke: '#2a2f36',
    textSec: '#c8ccd1',
    textTer: '#8b9098',
    textQuat: '#5b6169',
    accent: accentDark,
    floorWorkFill: rgba(accentDark, 0.04),
    floorLoungeFill: rgba(accentDark, 0.07),
    chairTop: '#3a3f45',
    chairBackTop: '#43484e',
    chairPost: '#22262b',
    chairBase: '#2a2f36',
    monitorShell: '#2f353d',
    keyboard: '#3c434c',
    deskWood: '#9c7a52',
    screenOff: '#151719',
    screenOffGlow: '#1c1f22',
    screenOnBase: '#263d47',
    screenOnGlow: '#2f4a55',
    stool: '#2c3035',
    screenGreenBusy: '#39ff88',
    screenGreenIdle: '#2fbf6a',
    pillColor: 'rgba(8, 10, 14, 0.9)',
    pillBorder: null,
    offlineNameColor: '#5a5f66',
    // Figure tones — see the light-mode note above.
    skin: '#e9b98f',
    skinShadow: '#a9713f',
    hair: '#241d1a',
    hairLit: '#3f342a',
    trouser: '#39414e',
    shoe: '#22262c',
    shadowInk: '#000000',
  }
}

// Accent outline on the floor under the SELECTED desk, so a click has visible
// feedback. Drawn before the desks so it reads as a mat, not a box.
export function drawSelection(c, ox, oy, scale, slot, accent) {
  const pad = 0.28
  const corners = [
    [slot.x - pad, slot.y - pad],
    [slot.x + DESK_W + pad, slot.y - pad],
    [slot.x + DESK_W + pad, slot.y + DESK_D + pad],
    [slot.x - pad, slot.y + DESK_D + pad],
  ]
  c.save()
  c.beginPath()
  corners.forEach(([x, y], i) => {
    const [px, py] = iso(x, y, 0.02, scale)
    if (i === 0) c.moveTo(ox + px, oy + py)
    else c.lineTo(ox + px, oy + py)
  })
  c.closePath()
  // Never parse the accent (it can be an oklch()/color-mix() expression the
  // canvas will not accept) — modulate alpha on the color itself.
  c.globalAlpha = 0.16
  c.fillStyle = accent
  c.fill()
  c.globalAlpha = 0.9
  c.strokeStyle = accent
  c.lineWidth = 2.5
  c.stroke()
  c.restore()
}

// ---------------------------------------------------------------------------
// Frame draw.
// ---------------------------------------------------------------------------
export function drawFloor(c, ox, oy, x, y, w, d, scale, style) {
  const [ax, ay] = iso(x, y, 0, scale)
  const [bx, by] = iso(x + w, y, 0, scale)
  const [cx, cy] = iso(x + w, y + d, 0, scale)
  const [dx, dy] = iso(x, y + d, 0, scale)
  c.beginPath()
  c.moveTo(ox + ax, oy + ay)
  c.lineTo(ox + bx, oy + by)
  c.lineTo(ox + cx, oy + cy)
  c.lineTo(ox + dx, oy + dy)
  c.closePath()
  c.fillStyle = style.fill
  c.fill()
  c.lineWidth = 1
  c.strokeStyle = style.stroke
  c.stroke()
}

// Lounge furniture footprint, in ONE place: drawLounge draws from these numbers
// and the test harness asserts on them (the group has to stay inside the zone
// and must not collide with the ring of stools).
export function loungeLayout(lounge) {
  return {
    sx: lounge.x + 0.6,          // sofa
    sy: lounge.y + 3.55,         // 3.55 clears the stool ring's south slot
    sofaW: 3.2,
    sofaD: 1.0,
    tx: lounge.x + 1.1,          // coffee table
    ty: lounge.y + 0.9,
    tw: 2.0,
    td: 1.0,
  }
}

// World-space upholstery dimensions. Screen-top extrema at different x/y are
// NOT a height constraint: the far arm naturally projects above the near back.
export function sofaDims() {
  const seatZ = 0.45
  const legH = 0.12
  return {
    armW: 0.28,
    legH,
    seatZ,
    backTop: seatZ + 0.57,   // normal back, not a screen-bbox-driven high wall
    armTop: seatZ + 0.25,
  }
}

// The sofa, in its own function so a diagnostic can draw each part in a distinct
// colour. The back stays on LARGE y, facing the coffee table at smaller y.
// Paint far (-x) arm, seat/seams, near (+y) back, then near (+x) arm.
// The rear upholstery is a single panel, not the inside cushion divisions.
export function drawSofa(c, ox, oy, scale, P, LL, tint) {
  const t = tint || {}
  const sofa = t.sofa || (P.mode === 'light' ? '#b9c2cf' : shade(P.accent, -0.4))
  const backInk = t.back || shade(sofa, -0.26)
  const armInk = t.arm || shade(sofa, -0.06)
  const legInk = t.leg || shade(sofa, -0.48)
  const seamInk = t.seam || shade(sofa, -0.52)
  const sx = LL.sx
  const sy = LL.sy
  const sofaW = LL.sofaW
  const sofaD = LL.sofaD
  const D = sofaDims()
  const armW = D.armW
  const legH = D.legH
  const seatZ = D.seatZ
  const backTop = D.backTop
  const armTop = D.armTop
  const backY = sy + sofaD - 0.22
  const backX = sx + armW
  const backW = sofaW - armW * 2
  softShadow(c, ox, oy, sx + sofaW / 2, sy + sofaD / 2, 1.95, scale,
    P.shadowInk || '#000000', 0.18)
  // Legs first, so the frame and arms paint over their tops.
  for (const fx of [0.24, sofaW - 0.24]) {
    for (const fy of [0.24, sofaD - 0.24]) {
      drawCylinder(c, ox, oy, sx + fx, sy + fy, 0, legH, 0.062, scale, legInk)
    }
  }
  // Far arm first: its rear end must disappear behind the back, not cover it.
  drawIsoBoxSoft(c, ox, oy, sx, sy, legH, armW, sofaD, armTop - legH, scale,
    t.farArm || armInk, { top: 0.16 })
  // Frame between the arms, lifted on the legs (no coincident arm surfaces).
  drawIsoBoxSoft(c, ox, oy, backX, sy, legH, backW, sofaD, seatZ - legH, scale, sofa,
    { top: 0.14 })
  // Seat divisions belong on the seat only, BEFORE the opaque backrest.
  c.save()
  c.strokeStyle = seamInk
  c.lineWidth = Math.max(1, scale * 0.013)
  const seg = (a, b) => {
    const [a0x, a0y] = iso(a[0], a[1], a[2], scale)
    const [a1x, a1y] = iso(b[0], b[1], b[2], scale)
    c.beginPath()
    c.moveTo(ox + a0x, oy + a0y)
    c.lineTo(ox + a1x, oy + a1y)
    c.stroke()
  }

  for (let i = 1; i < 3; i++) {
    const bx = backX + (backW * i) / 3
    seg([bx, sy, seatZ], [bx, backY, seatZ])
  }
  c.restore()
  // Near back masks hidden seat lines and the far arm's rear corner.
  drawIsoBoxSoft(c, ox, oy, backX, backY, seatZ, backW, 0.22, backTop - seatZ, scale,
    backInk, { top: 0.08 })
  // Near arm is the only arm that overlaps the backrest's near end.
  drawIsoBoxSoft(c, ox, oy, sx + sofaW - armW, sy, legH, armW, sofaD, armTop - legH,
    scale, t.nearArm || armInk, { top: 0.16 })
}

export function drawLounge(c, ox, oy, scale, stroke, tint, accent, tSec, palette, lounge) {
  const P = palette || {}
  const isLight = P.mode === 'light'
  // Sofa fabric base: a muted blue-grey in dark, a soft light fabric in light.
  const sofa = isLight ? '#b9c2cf' : shade(accent, -0.4)
  // Coffee-table wood: deep walnut in dark, light oak in light.
  const wood = isLight ? '#c9a876' : '#6b4b2a'
  // Anchored to the lounge origin the scene layout computed, so the zone
  // follows the desk grid.
  // ---- Sofa ----
  // Geometry and comments live in drawSofa(); the footprint comes from
  // loungeLayout() so the tests can assert on the same numbers.
  drawSofa(c, ox, oy, scale, P, loungeLayout(lounge))
  // ---- Coffee table: long enough that three cups fit with a margin ----------
  const { tx, ty, tw, td } = loungeLayout(lounge)
  const legIn = 0.14
  const legs = [
    [legIn, legIn], [tw - legIn, legIn],
    [legIn, td - legIn], [tw - legIn, td - legIn],
  ]
  legs.sort((a, b) => (a[0] + a[1]) - (b[0] + b[1]))
  for (let i = 0; i < legs.length; i++) {
    drawCylinder(c, ox, oy, tx + legs[i][0], ty + legs[i][1], 0, 0.34, 0.05, scale, wood)
  }
  const tableZ = 0.34
  const topH = 0.09
  drawIsoBoxSoft(c, ox, oy, tx, ty, tableZ, tw, td, topH, scale, wood, { top: 0.18 })

  // Teacups — 🍵 emoji, evenly spaced across the top with a margin each side and
  // centred in depth so they stand ON the table rather than over its edges.
  c.save()
  c.textAlign = 'center'
  c.textBaseline = 'alphabetic'
  const cupPx = Math.max(9, Math.round(scale * 0.30))
  c.font = cupPx + 'px system-ui, "Apple Color Emoji", "Segoe UI Emoji", sans-serif'
  for (let i = 0; i < 3; i++) {
    const cxw = tx + tw * (i + 1) / 4
    const cyw = ty + td * 0.5
    // Tableware is stationary; only the separate hand-held cup is animated.
    const [px, py] = iso(cxw, cyw, tableZ + topH, scale)
    c.fillText('🍵', ox + px, oy + py)
  }
  c.textAlign = 'start'
  c.textBaseline = 'alphabetic'
  c.restore()
}

// Pure world-space layout of ONE workstation: desk fixtures, chair and the
// sitter's shoulders/hands. Extracted so the drawing code and the tests share
// the SAME numbers — "the hands must clear the torso" is geometry, not taste,
// and eyeballing it got it wrong twice.
