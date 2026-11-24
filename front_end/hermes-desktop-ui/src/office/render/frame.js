// One frame of the Harvis office. Follows Office 3D's drawFrame (MIT, see ../LICENSE):
// floors, zone labels, selection mat, lounge furniture, desks back to front, then the
// lounge figures. Harvis adds walking figures from life.js, more lounge groups as the
// idle count grows, an honest "status unknown" desk, and speech bubbles on top.

import { iso, drawNameBadge } from './geometry.js'
import { LOUNGE_DEPTH, deskSlot, frameTransform, loungeSeat, sceneLayout } from './layout.js'
import { buildPalette, drawFloor, drawLounge, drawSelection } from './scene.js'
import { deskLayout, drawDeskAndAvatar, drawLoungeAvatar } from './avatars.js'
import { hallY } from './life.js'
import { drawBubble, drawTv, drawWalker } from './walker.js'

export function officeLayout(entries) {
  const list = Array.isArray(entries) ? entries : []
  return sceneLayout(list.length, list.filter(e => e.state === 'idle').length)
}

function deskEntry(entry, fig) {
  return {
    ...entry,
    online: entry.state === 'busy' || entry.state === 'idle',
    busy: entry.state === 'busy',
    seated: Boolean(fig && fig.mode === 'desk'),
  }
}

export function drawOfficeFrame(canvas, c, entries, life, tSec, selectedIndex, view) {
  const list = Array.isArray(entries) ? entries : []
  const P = buildPalette(canvas)
  const { stroke, textSec, textTer, textQuat, accent } = P
  const palette = { stroke, textSec, textTer, textQuat, accent, P }

  const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1))
  const cssW = canvas.clientWidth || 640
  const cssH = canvas.clientHeight || 400
  c.setTransform(1, 0, 0, 1, 0, 0)
  c.clearRect(0, 0, canvas.width, canvas.height)
  c.scale(dpr, dpr)
  c.fillStyle = P.bg
  c.fillRect(0, 0, cssW, cssH)

  const L = officeLayout(list)
  const T = frameTransform(cssW, cssH, L, view ? view.zoom : 1, view ? view.panX : 0, view ? view.panY : 0)
  const { ox, oy, scale } = T
  const figures = life ? life.update(list, L, tSec) : []
  const figByIndex = new Map(figures.map(f => [f.index, f]))

  drawFloor(c, ox, oy, 0, 0, L.worldW, L.workH, scale, { fill: P.floorWorkFill, stroke })
  drawFloor(c, ox, oy, 0, L.loungeY0, L.worldW, LOUNGE_DEPTH, scale, { fill: P.floorLoungeFill, stroke })

  c.font = '10px system-ui, -apple-system, "Segoe UI", sans-serif'
  c.fillStyle = textTer
  c.textAlign = 'right'
  {
    const [lx, ly] = iso(L.worldW, L.workH, 0, scale)
    c.fillText('WORK', ox + lx + 24, oy + ly - 22)
  }
  {
    const [lx, ly] = iso(L.worldW, L.loungeY0 + LOUNGE_DEPTH, 0, scale)
    c.fillText('LOUNGE', ox + lx + 24, oy + ly - 22)
  }
  c.textAlign = 'start'

  if (typeof selectedIndex === 'number' && selectedIndex >= 0 && selectedIndex < list.length) {
    drawSelection(c, ox, oy, scale, deskSlot(selectedIndex, L.cols), accent)
  }

  if (L.lounges.length > 1) drawTv(c, ox, oy, scale, 0.25, L.loungeY0 + 1.6, P, tSec)
  for (const pod of L.lounges) drawLounge(c, ox, oy, scale, stroke, textQuat, accent, tSec, P, pod)

  const hits = []
  const hy = hallY(L)
  const walkers = figures.filter(f => f.mode === 'walk' || f.mode === 'stand')
  const workWalkers = walkers.filter(f => f.y <= hy + 0.01)
  const loungeWalkers = walkers.filter(f => f.y > hy + 0.01)

  // Work zone and hallway: desks and walking figures together, back to front.
  const work = list.map((entry, i) => {
    const slot = deskSlot(i, L.cols)
    return { depth: slot.x + slot.y + 1.7, draw: () => drawDesk(c, ox, oy, scale, slot, entry, i, figByIndex.get(i), tSec, palette) }
  })
  for (const f of workWalkers) work.push({ depth: f.x + f.y, draw: () => hits.push({ index: f.index, ...drawWalker(c, ox, oy, scale, f, list[f.index], tSec, P, accent) }) })
  work.sort((a, b) => a.depth - b.depth).forEach(d => d.draw())

  // Lounge: seated idle bots and lounge walkers, back to front.
  const lounge = []
  let seatedIdx = 0
  for (const f of figures) {
    if (f.mode !== 'seat' || !f.seat) continue
    const slot = loungeSeat(f.seat.index, f.seat.total, L)
    const entry = { ...list[f.index], online: true, busy: false }
    const idx = seatedIdx++
    lounge.push({ depth: slot.x + slot.y, draw: () => {
      drawLoungeAvatar(c, ox, oy, scale, slot, entry, f.index, tSec, idx, palette)
      const [hx, hy2] = iso(slot.x, slot.y, 1.43, scale)
      hits.push({ index: f.index, x: ox + hx, y: oy + hy2, r: Math.max(10, scale * 0.6) })
    } })
  }
  for (const f of loungeWalkers) lounge.push({ depth: f.x + f.y, draw: () => hits.push({ index: f.index, ...drawWalker(c, ox, oy, scale, f, list[f.index], tSec, P, accent) }) })
  lounge.sort((a, b) => a.depth - b.depth).forEach(d => d.draw())

  // Bubbles go on top of everything so nothing hides them.
  for (const f of figures) {
    if (!f.bubble) continue
    const anchor = bubbleAnchor(f, L, ox, oy, scale)
    drawBubble(c, f.bubble, anchor[0], anchor[1], P)
  }

  return { ox, oy, scale, zoom: T.zoom, layout: L, hits }
}

function drawDesk(c, ox, oy, scale, slot, entry, i, fig, tSec, palette) {
  drawDeskAndAvatar(c, ox, oy, scale, slot, deskEntry(entry, fig), i, tSec, palette)
  if (entry.state !== 'unknown') return
  // No reliable signal for this bot: say so instead of guessing busy or idle.
  const S = deskLayout(slot)
  const [ux, uy] = iso(S.monX + 0.4, S.monY + 0.4, 2.6, scale)
  c.save()
  c.font = '9px system-ui, -apple-system, "Segoe UI", sans-serif'
  c.textAlign = 'center'
  drawNameBadge(c, 'status unknown', ox + ux, oy + uy, {
    fontPx: 9,
    textColor: palette.P.offlineNameColor,
    borderColor: palette.P.pillBorder,
    pillColor: palette.P.pillColor,
    dotColor: null,
  })
  c.restore()
}

function bubbleAnchor(f, L, ox, oy, scale) {
  let x = f.x
  let y = f.y
  let z = 2.0
  if (f.mode === 'seat' && f.seat) {
    const slot = loungeSeat(f.seat.index, f.seat.total, L)
    x = slot.x
    y = slot.y
    z = 2.15
  } else if (f.mode === 'desk') {
    const S = deskLayout(deskSlot(f.index, L.cols))
    x = S.cx
    y = S.cy
    z = 2.3
  }
  const [px, py] = iso(x, y, z, scale)
  return [ox + px, oy + py - 12]
}

// Front-most figure under the point, else -1. Figures drawn later are in front.
export function hitTestFigures(frame, px, py) {
  if (!frame || !Array.isArray(frame.hits)) return -1
  for (let i = frame.hits.length - 1; i >= 0; i--) {
    const h = frame.hits[i]
    if (Math.hypot(px - h.x, py - h.y) <= h.r) return h.index
  }
  return -1
}
