// Office 3D renderer, Solid primitives and figure parts (boxes, discs, cylinders, limbs, heads).
// Ported from office-3d v1.4.4 (desktop/plugin.js, commit 127c28a) by oslook and the
// office-3d contributors, MIT licensed: see ../LICENSE. Changes for Harvis: split into
// modules, figure colour comes from entry.color, and a busy bot walking to its desk
// (entry.seated === false) leaves the chair empty.

import { ISO_X, ISO_Y, hexToRgb, iso, rgba, shade } from './geometry.js'

export function drawIsoBox(c, ox, oy, x, y, z, w, d, h, scale, colors) {
  const [tlx, tly] = iso(x, y, z + h, scale)
  const [trx, try_] = iso(x + w, y, z + h, scale)
  const [brx, bry] = iso(x + w, y + d, z + h, scale)
  const [blx, bly] = iso(x, y + d, z + h, scale)

  const [tblx, tbly] = iso(x, y + d, z, scale)
  const [tbrx, tbry] = iso(x + w, y + d, z, scale)
  const [tfrx, tfry] = iso(x + w, y, z, scale)

  c.lineWidth = 1
  c.strokeStyle = colors.stroke

  // Front-right face (visible toward viewer along +x side)
  c.beginPath()
  c.moveTo(ox + trx, oy + try_)
  c.lineTo(ox + brx, oy + bry)
  c.lineTo(ox + tbrx, oy + tbry)
  c.lineTo(ox + tfrx, oy + tfry)
  c.closePath()
  c.fillStyle = colors.right
  c.fill()
  c.stroke()

  // Front-left face (+y side)
  c.beginPath()
  c.moveTo(ox + brx, oy + bry)
  c.lineTo(ox + blx, oy + bly)
  c.lineTo(ox + tblx, oy + tbly)
  c.lineTo(ox + tbrx, oy + tbry)
  c.closePath()
  c.fillStyle = colors.left
  c.fill()
  c.stroke()

  // Top face
  c.beginPath()
  c.moveTo(ox + tlx, oy + tly)
  c.lineTo(ox + trx, oy + try_)
  c.lineTo(ox + brx, oy + bry)
  c.lineTo(ox + blx, oy + bly)
  c.closePath()
  c.fillStyle = colors.top
  c.fill()
  c.stroke()
}

export function drawIsoDisc(c, ox, oy, x, y, z, radius, scale, fill, stroke) {
  const [cx, cy] = iso(x, y, z, scale)
  c.save()
  c.translate(ox + cx, oy + cy)
  c.scale(1, ISO_Y / ISO_X) // squash for fake perspective
  c.beginPath()
  c.arc(0, 0, radius * scale, 0, Math.PI * 2)
  c.restore()
  c.fillStyle = fill
  c.fill()
  if (stroke) {
    c.strokeStyle = stroke
    c.lineWidth = 1
    c.stroke()
  }
}

// ---------------------------------------------------------------------------
// Volumetric figure helpers.
//
// Human figures use a restrained set of upper-left-lit polygon planes. The
// cylinder/disc helpers remain unchanged for furniture and cups; only the
// dedicated figure helpers below draw anatomical forms. Body points stay in
// world coordinates until projected, so rendering does not alter pose geometry.
// ---------------------------------------------------------------------------

// World (x, y, z) -> absolute screen point for the frame's transform.
export function screenPt(ox, oy, x, y, z, scale) {
  const [px, py] = iso(x, y, z, scale)
  return [ox + px, oy + py]
}

export function fillEllipse(c, cx, cy, rx, ry, style) {
  if (!(rx > 0)) return
  c.save()
  c.translate(cx, cy)
  c.scale(1, ry / rx)
  c.beginPath()
  c.arc(0, 0, rx, 0, Math.PI * 2)
  c.restore()
  c.fillStyle = style
  c.fill()
}

// Soft elliptical contact shadow on the ground under a figure — the single
// cheapest cue that a body is standing on the floor rather than floating.
export function softShadow(c, ox, oy, x, y, rWorld, scale, ink, aMax) {
  const [cx, cy] = screenPt(ox, oy, x, y, 0.012, scale)
  const rx = rWorld * scale
  if (!(rx > 0.5)) return
  const ry = rx * (ISO_Y / ISO_X)
  const rgb = hexToRgb(ink) || { r: 0, g: 0, b: 0 }
  const col = (a) => 'rgba(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ', ' + a + ')'
  const g = c.createRadialGradient(cx, cy, 0, cx, cy, rx)
  g.addColorStop(0, col(aMax))
  g.addColorStop(0.55, col(aMax * 0.5))
  g.addColorStop(1, col(0))
  c.save()
  c.translate(cx, cy)
  c.scale(1, ry / rx)
  c.beginPath()
  c.arc(0, 0, rx, 0, Math.PI * 2)
  c.restore()
  c.fillStyle = g
  c.fill()
}

// Vertical cylinder from z0 (bottom) to z1 (top), centred on (x, y). Rounded
// caps + a left-lit side wall read as a limb/torso, unlike a hard box.
export function drawCylinder(c, ox, oy, x, y, z0, z1, r, scale, base) {
  const rx = r * scale
  if (!(rx > 0.4)) return
  const [cx, yTop] = screenPt(ox, oy, x, y, z1, scale)
  const [, yBot] = screenPt(ox, oy, x, y, z0, scale)
  const ry = rx * (ISO_Y / ISO_X)
  // Bottom cap (in shadow) — its front half peeks below the body.
  fillEllipse(c, cx, yBot, rx, ry, shade(base, -0.34))
  // Side wall: highlight band just left of centre, deep shadow on the right.
  const g = c.createLinearGradient(cx - rx, 0, cx + rx, 0)
  g.addColorStop(0.0, shade(base, -0.20))
  g.addColorStop(0.28, shade(base, 0.20))
  g.addColorStop(0.60, shade(base, 0.0))
  g.addColorStop(1.0, shade(base, -0.42))
  c.fillStyle = g
  c.fillRect(cx - rx, yTop, rx * 2, Math.max(0, yBot - yTop))
  // Top cap: rim-lit like a surface facing the light.
  const gt = c.createLinearGradient(cx - rx, yTop - ry, cx + rx, yTop + ry)
  gt.addColorStop(0, shade(base, 0.34))
  gt.addColorStop(1, shade(base, 0.02))
  fillEllipse(c, cx, yTop, rx, ry, gt)
}

// An isometric box with per-face GRADIENTS and only the lit top-front edges
// highlighted, instead of flat fills plus a hard 1px outline all the way round —
// that outline is what made the furniture read as a wireframe toy. Light comes
// from the upper-left, as everywhere else in this scene.
export function drawIsoBoxSoft(c, ox, oy, x, y, z, w, d, h, scale, base, opts) {
  const o = opts || {}
  const [tlx, tly] = iso(x, y, z + h, scale)
  const [trx, trY] = iso(x + w, y, z + h, scale)
  const [brx, bry] = iso(x + w, y + d, z + h, scale)
  const [blx, bly] = iso(x, y + d, z + h, scale)
  const [tblx, tbly] = iso(x, y + d, z, scale)
  const [tbrx, tbry] = iso(x + w, y + d, z, scale)
  const [tfrx, tfry] = iso(x + w, y, z, scale)
  const ax = (v) => ox + v

  // Right face (+x): brightest along its top edge, falling off toward the floor.
  const gr = c.createLinearGradient(0, oy + trY, 0, oy + tbry)
  gr.addColorStop(0, shade(base, -0.12))
  gr.addColorStop(1, shade(base, -0.44))
  c.beginPath()
  c.moveTo(ax(trx), oy + trY)
  c.lineTo(ax(brx), oy + bry)
  c.lineTo(ax(tbrx), oy + tbry)
  c.lineTo(ax(tfrx), oy + tfry)
  c.closePath()
  c.fillStyle = gr
  c.fill()

  // Left face (+y): the shaded side, darkest at the bottom.
  const gl = c.createLinearGradient(0, oy + bly, 0, oy + tbly)
  gl.addColorStop(0, shade(base, -0.36))
  gl.addColorStop(1, shade(base, -0.06))
  c.beginPath()
  c.moveTo(ax(brx), oy + bry)
  c.lineTo(ax(blx), oy + bly)
  c.lineTo(ax(tblx), oy + tbly)
  c.lineTo(ax(tbrx), oy + tbry)
  c.closePath()
  c.fillStyle = gl
  c.fill()

  // Top face: lit from the far corner, easing off toward the viewer.
  const lift = o.top == null ? 0.26 : o.top
  const gt = c.createLinearGradient(ax(tlx), oy + tly, ax(brx), oy + bry)
  gt.addColorStop(0, shade(base, lift))
  gt.addColorStop(1, shade(base, lift - 0.20))
  c.beginPath()
  c.moveTo(ax(tlx), oy + tly)
  c.lineTo(ax(trx), oy + trY)
  c.lineTo(ax(brx), oy + bry)
  c.lineTo(ax(blx), oy + bly)
  c.closePath()
  c.fillStyle = gt
  c.fill()

  // Edge light on the two top-front edges only — the rim a real object catches
  // from above, rather than an outline everywhere.
  if (o.edge !== false) {
    c.save()
    c.strokeStyle = 'rgba(255, 255, 255, ' +
      (o.edgeAlpha == null ? 0.12 : o.edgeAlpha) + ')'
    c.lineWidth = 1
    c.beginPath()
    c.moveTo(ax(tlx), oy + tly)
    c.lineTo(ax(trx), oy + trY)
    c.lineTo(ax(brx), oy + bry)
    c.stroke()
    c.restore()
  }
}

// A horizontal disc with a radial gradient: cushion tops, plinths, tabletops.
export function drawIsoDiscSoft(c, ox, oy, x, y, z, radius, scale, base, opts) {
  const o = opts || {}
  const [cx, cy] = screenPt(ox, oy, x, y, z, scale)
  const rx = radius * scale
  if (!(rx > 0.4)) return
  const ry = rx * (ISO_Y / ISO_X)
  const lift = o.top == null ? 0.22 : o.top
  const g = c.createRadialGradient(
    cx - rx * 0.30, cy - ry * 0.30, rx * 0.10,
    cx, cy, rx,
  )
  g.addColorStop(0, shade(base, lift))
  g.addColorStop(1, shade(base, -0.20))
  fillEllipse(c, cx, cy, rx, ry, g)
}

// A limb segment (arm/leg): round-capped stroke plus a thin lit highlight so
// the stroke reads as a cylinder rather than a flat ribbon. `bend` nudges the
// control point (px) to suggest an elbow/knee.
// Human-only faceted primitives. Furniture keeps its original cylinder/box helpers.
export function figurePoly(c, points, ink) {
  c.beginPath(); points.forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p))
  c.closePath(); c.fillStyle=ink; c.fill()
}
export function drawLimb(c, p0, p1, width, base, bend) {
  if (!(width > 0.5)) return
  const dx=p1[0]-p0[0],dy=p1[1]-p0[1],len=Math.hypot(dx,dy)||1
  const n=[-dy/len,dx/len],u=[dx/len,dy/len]
  const at=(p,w,t=0)=>[p[0]+n[0]*w+u[0]*t,p[1]+n[1]*w+u[1]*t]
  const a=at(p0,width*.50,-width*.12),b=at(p0,-width*.50,-width*.12)
  const d=at(p1,width*.34,width*.10),e=at(p1,-width*.34,width*.10)
  figurePoly(c,[a,b,e,d],shade(base,-.12))
  figurePoly(c,[a,p0,p1,d],shade(base,.12))
}
export function drawPalm(c, p, width, skin, grip=false) {
  const x=p[0],y=p[1],w=width
  figurePoly(c,[[x-w*.55,y-w*.28],[x-w*.18,y-w*.52],[x+w*.45,y-w*.32],
    [x+w*.55,y+w*.18],[x+w*.10,y+w*.46],[x-w*.45,y+w*.32]],skin)
  figurePoly(c,[[x-w*.55,y-w*.28],[x-w*.18,y-w*.52],[x+w*.45,y-w*.32],
    [x+w*.10,y]],shade(skin,.12))
  if(grip)figurePoly(c,[[x-w*.5,y],[x-w*.18,y-w*.12],[x+w*.08,y+w*.12],
    [x-w*.12,y+w*.35]],shade(skin,-.16))
}
export function drawFigureBand(c,ox,oy,x,y,z0,z1,r,scale,ink) {
  const a=screenPt(ox,oy,x,y,z1,scale),b=screenPt(ox,oy,x,y,z0,scale),w=r*scale
  figurePoly(c,[[a[0]-w,a[1]],[a[0]+w*.65,a[1]-w*.22],[a[0]+w,a[1]+w*.25],
    [b[0]+w*.80,b[1]],[b[0],b[1]+w*.25],[b[0]-w,b[1]]],ink)
  figurePoly(c,[[a[0]+w*.25,a[1]],[a[0]+w,a[1]+w*.25],[b[0]+w*.80,b[1]],
    [b[0]+w*.25,b[1]+w*.18]],shade(ink,-.18))
}
export function drawFigureTorso(c,ox,oy,x,y,z0,z1,r,scale,cloth,pants) {
  const [cx,yt]=screenPt(ox,oy,x,y,z1,scale),[,yb]=screenPt(ox,oy,x,y,z0,scale)
  const w=r*scale,h=yb-yt
  const pt=(a,b)=>[cx+a*w,yt+b*h]
  // Trapezoidal shoulders, chest, narrower waist, seated pelvic shelf.
  figurePoly(c,[pt(-.42,-.10),pt(.42,-.10),pt(1,.10),pt(.78,.83),
    pt(.92,1.04),pt(.40,1.18),pt(-.75,1.10),pt(-.84,.78),pt(-1,.12)],cloth)
  figurePoly(c,[pt(-.42,-.10),pt(.42,-.10),pt(1,.10),pt(.15,.24),pt(-1,.12)],shade(cloth,.18))
  figurePoly(c,[pt(.15,.24),pt(1,.10),pt(.78,.83),pt(.92,1.04),pt(.30,1.10)],shade(cloth,-.20))
  figurePoly(c,[pt(-.84,.78),pt(.78,.83),pt(.92,1.04),pt(.40,1.18),pt(-.75,1.10)],pants)
}

// A shaded head: a radial-gradient sphere with the hair cut away around a face
// oval, plus (only once the head is a few px across) eyes, catch-lights and a
// mouth. `blink` in [0,1] squashes the eyes shut.
//
// `facing` is the SCREEN-space direction the face points along, because the two
// poses look in genuinely different directions:
//   [0.19, 0.98]  — nearly straight down = out at the viewer. The lounge sitter
//                   relaxes facing the room, so we see the face.
//   [0.82, -0.58] — up-right = along -y in world = at the desk. The sitter works
//                   facing the monitor, so we see the BACK of the head: the hair
//                   stays a full cap and only a sliver of cheek shows. (The
//                   viewer looks from screen-down, so "up-right" is away.)
// Facial features are only drawn when the face is turned toward the viewer;
// that single gate is what makes each pose read correctly.
// Head facing per pose, in SCREEN space (see drawHead). A unit step along world
// -y projects to (0.816, -0.577) — right and up — so the desk sitter, who faces
// the monitor, is seen from behind. The lounge sitter faces out at the viewer.
export const DESK_FACING = [0.816, -0.577]
export const LOUNGE_FACING = [0.19, 0.98]
export const FACE_TV_MIN = 0.45

// Upright chamfered skull and jaw: broad planes, no random triangulation.
// Mouth remains at +.85r screen-y, calibrated to the actual tea rim trajectory.
export function drawHead(c,cx,cy,r,opts) {
  if(!(r>.6))return
  const f=opts.facing||LOUNGE_FACING, l=Math.hypot(...f)||1,fx=f[0]/l,fy=f[1]/l
  const face=opts.face!==false&&fy>FACE_TV_MIN
  const pt=(x,y)=>[cx+x*r,cy+y*r], poly=(a,ink)=>figurePoly(c,a.map(p=>pt(...p)),ink)
  const skull=[[-.65,-.88],[.24,-1],[.77,-.66],[.94,-.12],[.78,.54],[.38,.92],[-.20,1],[-.72,.63],[-.93,.03],[-.87,-.48]]
  poly(skull,opts.hair)
  poly([[-.65,-.88],[.24,-1],[.77,-.66],[.13,-.42],[-.87,-.48]],opts.hairLit)
  if(face){
    poly([[-.66,-.34],[-.25,-.48],[.28,-.32],[.69,-.40],[.78,.23],
      [.59,.72],[.28,.96],[-.18,.98],[-.57,.69],[-.76,.16]],opts.skin)
    poly([[.48,-.35],[.69,-.40],[.78,.23],[.59,.72],[.28,.96],[.40,.41]],shade(opts.skin,-.14))
    poly([[-.66,-.34],[-.25,-.48],[.28,-.32],[.04,-.08],[-.70,.12]],shade(opts.skin,.12))
  }else{
    poly([[.77,-.66],[.94,-.12],[.78,.54],[.56,.70],[.63,.10]],opts.skin)
    poly([[.60,.29],[.75,.20],[.78,.43],[.64,.58]],shade(opts.skin,-.12))
  }
  if(r<7||!face)return
  const ex=fx*r*.26,ey=fy*r*.26,sep=r*.29*Math.min(1,Math.abs(fy))
  const blink=opts.blink==null?1:opts.blink
  for(const side of [-1,1]){
    const x=cx+ex+side*sep,y=cy+ey
    figurePoly(c,[[x-r*.09,y-r*.065*blink],[x+r*.09,y-r*.04*blink],
      [x+r*.08,y+r*.065*blink],[x-r*.085,y+r*.06*blink]],opts.eyeColor||'#1f242c')
  }
  if(r>=12)poly([[fx*.26,.37],[fx*.26-.065,.53],[fx*.26+.08,.53]],shade(opts.skin,-.12))
  c.beginPath();c.moveTo(cx+ex-r*.15,cy+r*.85);c.lineTo(cx+ex+r*.15,cy+r*.85)
  c.strokeStyle=shade(opts.skinShadow||opts.skin,-.30);c.lineWidth=Math.max(.7,r*.035);c.lineCap='butt';c.stroke()
}

// ---------------------------------------------------------------------------
// Scene layout.
//
// The desk grid is DERIVED from the number of profiles: a fixed 3-column grid
// pushed the 7th desk outside the work floor (y=6.9 > the 6.5-deep floor), so
// the office overflowed as soon as an install had more than six profiles.
// Everything here is pure — no canvas, no DOM — so it can be unit-tested.
// ---------------------------------------------------------------------------
