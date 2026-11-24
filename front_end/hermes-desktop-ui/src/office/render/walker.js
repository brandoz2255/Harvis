// Harvis additions to the Office 3D renderer: a standing or walking figure, speech
// bubbles and the TV a bigger lounge gets. Built from the ported Office 3D parts
// (MIT, see ../LICENSE) so the new figure matches the seated ones.

import { ISO_X, ISO_Y, drawNameBadge, iso, nameInk, profileName, shade } from './geometry.js'
import { drawFigureBand, drawFigureTorso, drawHead, drawIsoBoxSoft, drawLimb, figurePoly, screenPt, softShadow } from './shapes.js'
import { DOOR_X } from './life.js'

// Screen direction of a world step, for the head's facing.
export function screenFacing(dir) {
  const sx = (dir[0] - dir[1]) * ISO_X
  const sy = (dir[0] + dir[1]) * ISO_Y
  const l = Math.hypot(sx, sy)
  return l > 1e-6 ? [sx / l, sy / l] : [0.19, 0.98]
}

// Fade in and out at the door so arrivals and exits are not a pop.
export function doorAlpha(x) {
  return Math.max(0, Math.min(1, (x - DOOR_X) / 0.9))
}

// Returns the head's screen point and radius, for hit-testing and bubbles.
export function drawWalker(c, ox, oy, scale, fig, entry, tSec, P, accent) {
  const pcolor = entry.color || accent
  const walking = fig.mode === 'walk'
  const len = Math.hypot(fig.dir[0], fig.dir[1]) || 1
  const fx = fig.dir[0] / len
  const fy = fig.dir[1] / len
  const px = -fy
  const py = fx
  const phase = walking ? (tSec - fig.walkStart) * 7.5 : 0
  const swing = walking ? 0.2 * Math.sin(phase) : 0
  const bob = walking ? 0.02 * Math.abs(Math.cos(phase)) : 0
  const hipZ = 0.6 + bob
  const topZ = 1.2 + bob
  const project = p => screenPt(ox, oy, p[0], p[1], p[2], scale)

  c.save()
  c.globalAlpha = doorAlpha(fig.x)
  softShadow(c, ox, oy, fig.x, fig.y, 0.42, scale, P.shadowInk, 0.24)

  const legW = Math.max(1.5, 0.16 * scale)
  const armW = Math.max(1.4, 0.13 * scale)
  const sides = [-1, 1].map(side => {
    const s = side * swing
    const hip = [fig.x + px * side * 0.12, fig.y + py * side * 0.12, hipZ]
    const foot = [hip[0] + fx * s * 1.0, hip[1] + fy * s * 1.0, 0.05]
    const knee = [(hip[0] + foot[0]) / 2 + fx * 0.04, (hip[1] + foot[1]) / 2 + fy * 0.04, 0.32]
    const shoulder = [fig.x + px * side * 0.25, fig.y + py * side * 0.25, topZ - 0.1]
    const hand = [shoulder[0] - fx * s * 0.9, shoulder[1] - fy * s * 0.9, 0.66 + bob]
    const elbow = [(shoulder[0] + hand[0]) / 2, (shoulder[1] + hand[1]) / 2, 0.88 + bob]
    return { hip, knee, foot, shoulder, elbow, hand, depth: hip[0] + hip[1] }
  })
  sides.sort((a, b) => a.depth - b.depth)

  const drawLeg = s => {
    const hip = project(s.hip)
    const knee = project(s.knee)
    const foot = project(s.foot)
    drawLimb(c, hip, knee, legW, P.trouser)
    drawLimb(c, knee, foot, legW * 0.86, P.trouser)
    figurePoly(c, [[foot[0] - legW * 0.45, foot[1] - legW * 0.2], [foot[0] + legW * 0.6, foot[1] - legW * 0.15],
      [foot[0] + legW * 0.8, foot[1] + legW * 0.4], [foot[0] - legW * 0.4, foot[1] + legW * 0.42]], P.shoe)
  }
  const drawArm = s => {
    drawLimb(c, project(s.shoulder), project(s.elbow), armW, shade(pcolor, -0.16))
    drawLimb(c, project(s.elbow), project(s.hand), armW * 0.9, P.skin)
  }

  drawLeg(sides[0])
  drawArm(sides[0])
  drawLeg(sides[1])
  drawFigureTorso(c, ox, oy, fig.x, fig.y, hipZ - 0.05, topZ, 0.25, scale, pcolor, P.trouser)
  drawFigureBand(c, ox, oy, fig.x, fig.y, topZ - 0.03, topZ + 0.11, 0.1, scale, P.skin)
  drawArm(sides[1])

  const headR = 0.26
  const head = project([fig.x, fig.y, topZ + 0.37])
  drawHead(c, head[0], head[1], headR * scale, {
    skin: P.skin,
    skinShadow: P.skinShadow,
    hair: P.hair,
    hairLit: P.hairLit,
    facing: walking ? screenFacing(fig.dir) : [0.19, 0.98],
    blink: Math.sin(tSec * 1.3 + fig.index * 2.1) > 0.965 ? 0.14 : 1,
  })

  const [nx, ny] = iso(fig.x, fig.y, topZ + 0.37 + headR, scale)
  c.font = '10px system-ui, -apple-system, "Segoe UI", sans-serif'
  c.textAlign = 'center'
  drawNameBadge(c, profileName(entry), ox + nx, oy + ny - 6, {
    fontPx: 10,
    textColor: nameInk(pcolor, P),
    borderColor: P.pillBorder,
    pillColor: P.pillColor,
    dotColor: null,
  })
  c.textAlign = 'start'
  c.restore()
  return { x: head[0], y: head[1], r: Math.max(10, headR * scale * 2.2) }
}

function roundRect(c, x, y, w, h, r) {
  c.beginPath()
  c.moveTo(x + r, y)
  c.arcTo(x + w, y, x + w, y + h, r)
  c.arcTo(x + w, y + h, x, y + h, r)
  c.arcTo(x, y + h, x, y, r)
  c.arcTo(x, y, x + w, y, r)
  c.closePath()
}

export function clip(text, max) {
  const t = String(text || '').replace(/\s+/g, ' ').trim()
  return t.length > max ? t.slice(0, max - 1) + '…' : t
}

// Real bubbles are solid and carry a real session title. Simulated chatter is
// dashed, italic and starts with "~", so the two can never be confused.
export function drawBubble(c, bubble, x, y, P) {
  const sim = bubble.kind === 'sim'
  const text = sim ? '~ ' + clip(bubble.text, 34) : clip(bubble.text, 42)
  c.save()
  c.globalAlpha = 1
  c.font = (sim ? 'italic ' : '') + '11px system-ui, -apple-system, "Segoe UI", sans-serif'
  const w = c.measureText(text).width + 14
  const h = 20
  const bx = x - w / 2
  const by = y - h - 10
  roundRect(c, bx, by, w, h, 7)
  c.fillStyle = sim ? (P.mode === 'light' ? 'rgba(255,255,255,0.82)' : 'rgba(20,24,30,0.78)') : (P.mode === 'light' ? '#ffffff' : '#1c2128')
  c.fill()
  c.setLineDash(sim ? [3, 3] : [])
  c.lineWidth = 1
  c.strokeStyle = sim ? P.textTer : P.accent || P.textSec
  c.stroke()
  c.setLineDash([])
  c.beginPath()
  c.moveTo(x - 5, by + h)
  c.lineTo(x, by + h + 6)
  c.lineTo(x + 5, by + h)
  c.fillStyle = c.fillStyle
  c.fill()
  c.fillStyle = sim ? P.textTer : P.textSec
  c.textAlign = 'center'
  c.textBaseline = 'middle'
  c.fillText(text, x, by + h / 2 + 0.5)
  c.restore()
}

// A low cabinet with a wall TV, against the lounge's west edge. The screen is on
// the +x face, the one the viewer sees. It shows an idle glow, never content.
export function drawTv(c, ox, oy, scale, x, y, P, tSec) {
  const wood = P.mode === 'light' ? '#c9a876' : '#6b4b2a'
  drawIsoBoxSoft(c, ox, oy, x, y, 0, 0.5, 2.0, 0.42, scale, wood, { top: 0.18 })
  drawIsoBoxSoft(c, ox, oy, x + 0.12, y + 0.1, 0.62, 0.1, 1.8, 1.0, scale, P.monitorShell || '#2a2e34', { top: 0.12 })
  const corners = [[x + 0.23, y + 0.18, 0.7], [x + 0.23, y + 1.82, 0.7], [x + 0.23, y + 1.82, 1.54], [x + 0.23, y + 0.18, 1.54]]
    .map(p => screenPt(ox, oy, p[0], p[1], p[2], scale))
  const glow = 0.5 + 0.5 * Math.sin(tSec * 0.6)
  figurePoly(c, corners, shade(P.screenOnBase || '#263d47', 0.05 * glow))
}
