// Office 3D renderer, Scene layout, view transform and desk hit-testing.
// Ported from office-3d v1.4.4 (desktop/plugin.js, commit 127c28a) by oslook and the
// office-3d contributors, MIT licensed: see ../LICENSE. Changes for Harvis: split into
// modules, figure colour comes from entry.color, and a busy bot walking to its desk
// (entry.seated === false) leaves the chair empty.

import { ISO_X, ISO_Y, iso } from './geometry.js'
import { buildPalette } from './scene.js'

export const DESK_ROW_SPACING = 3.2
export const DESK_COL_SPACING = 3.6
export const WORK_ORIGIN = { x: 0.5, y: 0.5 }
// Floor margin around the desk grid. 3.3 reproduces the original 6.5-deep work
// floor for a two-row grid, so a six-profile install looks exactly as before.
export const WORK_PAD = 3.3
export const LOUNGE_DEPTH = 6.0 // lounge zone depth (its furniture is a fixed size)
export const LOUNGE_GAP = 0.5   // gap between the work floor and the lounge floor
export const LOUNGE_W = 11      // minimum scene width, so the lounge ring always fits
// The lounge GROUP — ring of stools + coffee table + sofa — is a fixed size. Its
// own bounding box, measured from the anchor sceneLayout hands out, spans
// x [-0.3, +3.8] and y [-0.1, +4.55], so its centre sits at these offsets.
// sceneLayout therefore anchors the group at the ZONE's centre instead of at the
// work floor's left edge: pinning it left crammed the whole group into the first
// third of an 11-wide zone and left the rest of the floor empty.
export const LOUNGE_GROUP_CX = 2.05
export const LOUNGE_GROUP_CY = 2.225
export const MAX_COLS = 5       // widest desk grid
export const MIN_SCALE = 10     // smallest scene scale that still fits a huge install
export const MAX_SCALE = 64

// ---------------------------------------------------------------------------
// View transform (zoom + pan).
//
// `zoom` is a MULTIPLIER on the fit-to-canvas scale, so 1 = "fit the whole
// office" and the default look is byte-identical to before this feature. The
// transform is a pure function of (canvas size, layout, zoom, pan) precisely so
// the wheel/pan handlers and drawFrame can never disagree about where a desk
// landed — a click is hit-tested against the very transform the pixels came
// from (drawFrame hands it back).
// ---------------------------------------------------------------------------
export const VIEW_ZOOM_MIN = 0.4
export const VIEW_ZOOM_MAX = 6

export function clampZoom(z) {
  if (!Number.isFinite(z)) return 1
  return Math.max(VIEW_ZOOM_MIN, Math.min(VIEW_ZOOM_MAX, z))
}

export function frameTransform(cssW, cssH, L, zoom, panX, panY) {
  const margin = 24
  const sceneH = Math.max(120, cssH)
  const scaleFit = Math.min(
    (cssW - margin * 2) / L.projW,
    (sceneH - margin * 2) / L.projH,
  )
  // Clamp the FIT to a sane band (a 40-profile install must not vanish, a tiny
  // one must not fill the screen), then let the user's zoom multiply it freely.
  const base = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scaleFit))
  const z = clampZoom(zoom)
  const scale = base * z
  const leftMost = (0 - L.worldH) * ISO_X * scale
  const topMost = -3.0 * scale
  const px = Number.isFinite(panX) ? panX : 0
  const py = Number.isFinite(panY) ? panY : 0
  const ox = margin - leftMost +
    Math.max(0, (cssW - margin * 2 - L.projW * scale) / 2) + px
  const oy = margin - topMost + py
  return { ox, oy, scale, fit: scaleFit, zoom: z }
}

// Zoom to `nextZoom` while keeping the world point under (ax, ay) pinned to
// that screen position — the standard "zoom at the cursor" feel. Both the
// before and after transforms come from frameTransform, so the anchoring is
// exact rather than approximate.
export function zoomAbout(cssW, cssH, L, view, nextZoom, ax, ay) {
  const before = frameTransform(cssW, cssH, L, view.zoom, view.panX, view.panY)
  const nx = clampZoom(nextZoom)
  const base = frameTransform(cssW, cssH, L, nx, 0, 0)
  const k = before.scale === 0 ? 1 : base.scale / before.scale
  const cx = Number.isFinite(ax) ? ax : cssW / 2
  const cy = Number.isFinite(ay) ? ay : cssH / 2
  return {
    zoom: nx,
    panX: cx - (cx - before.ox) * k - base.ox,
    panY: cy - (cy - before.oy) * k - base.oy,
  }
}

// Near-square desk grid for `count` desks: 6 -> 3x2 (unchanged), 9 -> 3x3,
// 12 -> 4x3, 25 -> 5x5.
export function deskGrid(count) {
  const n = Math.max(1, Math.floor(count) || 1)
  let cols = Math.max(2, Math.min(MAX_COLS, Math.ceil(Math.sqrt(n))))
  if (cols > n) cols = n
  return { cols, rows: Math.ceil(n / cols) }
}

// World-space extents of the whole scene for `count` desks, plus the isometric
// bounding box used to fit it into the canvas.
// Harvis: upstream's lounge is one fixed group. Here each group seats LOUNGE_SEATS,
// and a busier lounge gets more groups side by side, widening the floor to fit them.
export const LOUNGE_SEATS = 6
export const LOUNGE_POD_W = 5.5

export function loungePods(idleCount) {
  return Math.max(1, Math.ceil((Math.max(0, Math.floor(idleCount) || 0)) / LOUNGE_SEATS))
}

export function sceneLayout(count, idleCount = 0) {
  const { cols, rows } = deskGrid(count)
  const workW = (cols - 1) * DESK_COL_SPACING + WORK_PAD
  const workH = (rows - 1) * DESK_ROW_SPACING + WORK_PAD
  const pods = loungePods(idleCount)
  const worldW = Math.max(LOUNGE_W, workW, pods * LOUNGE_POD_W + 1)
  const loungeY0 = workH + LOUNGE_GAP
  const worldH = loungeY0 + LOUNGE_DEPTH
  // Ground plane projects to (w + h) * ISO_X wide and (w + h) * ISO_Y tall;
  // add the z extent above it (monitors + name labels sit at z ≈ 2.1-3.0).
  return {
    cols,
    rows,
    workW,
    workH,
    worldW,
    worldH,
    loungeY0,
    projW: (worldW + worldH) * ISO_X,
    projH: (worldW + worldH) * ISO_Y + 3.0,
    // Lounge furniture is anchored so the GROUP is centred in the lounge zone
    // (see LOUNGE_GROUP_C*), instead of hanging off the work floor's left edge.
    lounge: {
      x: worldW / 2 - LOUNGE_GROUP_CX,
      y: loungeY0 + LOUNGE_DEPTH / 2 - LOUNGE_GROUP_CY,
    },
    // One furniture group per LOUNGE_SEATS idle bots, centred as a row.
    lounges: Array.from({ length: pods }, (_, i) => ({
      x: worldW / 2 + (i - (pods - 1) / 2) * LOUNGE_POD_W - LOUNGE_GROUP_CX,
      y: loungeY0 + LOUNGE_DEPTH / 2 - LOUNGE_GROUP_CY,
    })),
  }
}

// Seat `index` of `total` idle bots: fill each group's stool ring in turn.
export function loungeSeat(index, total, L) {
  const pods = L.lounges && L.lounges.length ? L.lounges : [L.lounge]
  const pod = Math.min(pods.length - 1, Math.floor(index / LOUNGE_SEATS))
  const inPod = Math.min(LOUNGE_SEATS, total - pod * LOUNGE_SEATS)
  return loungeSlot(index - pod * LOUNGE_SEATS, inPod, pods[pod])
}

export function deskSlot(index, cols) {
  const col = index % cols
  const row = Math.floor(index / cols)
  return {
    x: WORK_ORIGIN.x + col * DESK_COL_SPACING,
    y: WORK_ORIGIN.y + row * DESK_ROW_SPACING,
  }
}

export function loungeSlot(index, total, lounge) {
  const t = total > 0 ? total : 1
  const angle = (index / t) * Math.PI * 2
  const r = 1.7
  return {
    x: lounge.x + 2.0 + Math.cos(angle) * r,
    y: lounge.y + 1.6 + Math.sin(angle) * r,
  }
}

// ---------------------------------------------------------------------------
// Hit testing.
//
// A desk is clickable, so the click handler needs the inverse of the frame
// projection. drawFrame hands back the transform it drew with (ox/oy/scale +
// the layout), and these helpers turn a CSS-pixel point back into a desk index.
// Pure functions — no canvas, no DOM — so they are unit-testable.
// ---------------------------------------------------------------------------
export const DESK_W = 2.2        // desk footprint (x)
export const DESK_D = 1.1        // desk footprint (y)
export const DESK_H = 1.6        // desk + monitor + name label, for the click target

// Screen-space (CSS px) bounding box of one desk's clickable volume.
export function deskHitBox(slot, ox, oy, scale) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const dx of [0, DESK_W]) {
    for (const dy of [0, DESK_D]) {
      for (const dz of [0, DESK_H]) {
        const [px, py] = iso(slot.x + dx, slot.y + dy, dz, scale)
        const sx = ox + px
        const sy = oy + py
        if (sx < x0) x0 = sx
        if (sx > x1) x1 = sx
        if (sy < y0) y0 = sy
        if (sy > y1) y1 = sy
      }
    }
  }
  return { x0, y0, x1, y1 }
}

// Which desk is under (px, py) in CSS px? Boxes overlap in an isometric scene,
// so among the hits pick the FRONT-most one (largest slot.x + slot.y, the order
// drawFrame paints in), which is the desk the user actually sees on top.
export function hitTestDesks(entries, frame, px, py) {
  if (!frame || !Array.isArray(entries)) return -1
  const { ox, oy, scale, layout } = frame
  let bestIndex = -1
  let bestDepth = -Infinity
  for (let i = 0; i < entries.length; i++) {
    const slot = deskSlot(i, layout.cols)
    const box = deskHitBox(slot, ox, oy, scale)
    if (px < box.x0 || px > box.x1 || py < box.y0 || py > box.y1) continue
    const depth = slot.x + slot.y
    if (depth > bestDepth) {
      bestDepth = depth
      bestIndex = i
    }
  }
  return bestIndex
}

// ---------------------------------------------------------------------------
// Palette that FOLLOWS the Hermes global theme. buildPalette reads the app's
// --ui-bg each frame and picks a light or dark scene palette from its
// luminance, so toggling Hermes's theme flips the office automatically.
// getComputedStyle also supplies the accent color.
// ---------------------------------------------------------------------------
