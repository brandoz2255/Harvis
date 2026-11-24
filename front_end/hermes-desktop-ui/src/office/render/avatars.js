// Office 3D renderer, Workstations, seated poses and the desk and lounge figures.
// Ported from office-3d v1.4.4 (desktop/plugin.js, commit 127c28a) by oslook and the
// office-3d contributors, MIT licensed: see ../LICENSE. Changes for Harvis: split into
// modules, figure colour comes from entry.color, and a busy bot walking to its desk
// (entry.seated === false) leaves the chair empty.

import { drawNameBadge, formatIdle, hexToRgb, iso, nameInk, profileName, rgba, shade } from './geometry.js'
import { DESK_FACING, LOUNGE_FACING, drawCylinder, drawFigureBand, drawFigureTorso, drawHead, drawIsoBoxSoft, drawIsoDiscSoft, drawLimb, drawPalm, figurePoly, fillEllipse, screenPt, softShadow } from './shapes.js'
import { DESK_D, DESK_W } from './layout.js'

export function deskLayout(slot) {
  // NOTE: the sitter deliberately sits at the desk's west end while the monitor
  // and keyboard are centred a little further east. That offset is what makes the
  // hands reach forward past the body. Centring everything on the sitter instead
  // made the typing read worse — do NOT re-align these without comparing the
  // render before and after.
  const chairX = slot.x + 0.15
  const chairY = slot.y + 0.72
  const cx = chairX + 0.45
  const cy = chairY + 0.45
  const seatZ = 0.50           // hips on the cushion (its top sits at 0.48)
  const torsoH = 0.62
  const topZ = seatZ + torsoH
  const torsoR = 0.29
  // Seen from behind there is no need to show neck skin: the head sits IN the
  // collar, and a skin cylinder that size read as a third blob next to the two
  // hands. The neck stays, but it is narrow and almost entirely covered.
  const neckR = 0.10
  const neckTopZ = topZ + 0.10
  const collarR = 0.19
  const collarTopZ = topZ + 0.065
  const headR = 0.29
  const headCz = topZ + 0.05 + headR // the head's lowest point is topZ + 0.05
  const kbX = slot.x + 0.65
  const kbY = slot.y + 0.70
  const kbW = 0.80
  const kbD = 0.30
  const handZ = 0.82
  const handY = kbY + kbD * 0.5
  return {
    chairX, chairY, cx, cy, seatZ, torsoH, topZ, torsoR,
    neckR, neckTopZ, collarR, collarTopZ, headR, headCz,
    kbX, kbY, kbW, kbD, handZ, handY,
    monX: slot.x + 0.62,
    monY: slot.y + 0.14,
    panW: 0.92, panD: 0.07, panH: 0.60, panZ: 0.86,
    mugX: slot.x + 1.86,
    mugY: slot.y + 0.52,
    shoulderZ: topZ - 0.10,
    // Every SHOULDER lands inside the torso's silhouette and every HAND well
    // outside it. drawDeskAndAvatar paints both arms BEFORE the torso, so the
    // body occludes the top of each arm while both hands stay visible on the
    // keys — that ordering is the layering fix.
    shoulders: [
      [cx - 0.26, cy - 0.04, topZ - 0.10],
      [cx + 0.26, cy - 0.04, topZ - 0.10],
    ],
    hands: [
      [kbX + 0.20, handY, handZ],
      [kbX + kbW - 0.20, handY, handZ],
    ],
  }
}

// Stable identity phase: reordering profiles does not synchronise their gestures.
export function posePhase(profile) {
  let h = 0
  for (const ch of String(profile || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return (h % 1009) / 1009
}
export function deskPose(slot, profile, tSec) {
  const S = deskLayout(slot)
  const phase = posePhase(profile) * Math.PI * 2
  const breath = 0.006 * Math.sin(tSec * 1.35 + phase)
  const hands = S.hands.map((h, a) => [h[0] + 0.006 * Math.sin(tSec * 3 + phase + a),
    h[1], 0.817 + 0.007 * (0.5 + 0.5 * Math.sin(tSec * 7 + phase + a * 2.3))])
  const shoulders = S.shoulders.map(p => [p[0], p[1], p[2] + breath])
  const elbows = shoulders.map((p, a) => [p[0] * 0.45 + hands[a][0] * 0.55,
    p[1] * 0.48 + hands[a][1] * 0.52 + 0.035, 0.86 + breath * 0.5])
  return {S, breath, hands, shoulders, elbows, head: [S.cx, S.cy, S.headCz + breath]}
}
// Two-bone geometry: the pole is a direction, projected perpendicular to the
// shoulder/wrist axis. Fixed lengths and an outward pole keep the elbow on one
// continuous branch (including the sip hold), rather than stretching a sleeve.
export function armElbow(shoulder, hand, upper, lower, pole) {
  const delta = hand.map((v,i) => v-shoulder[i])
  const distance = Math.hypot(...delta)
  const axis = delta.map(v => v/distance)
  const dot = pole.reduce((s,v,i) => s+v*axis[i],0)
  const normal = pole.map((v,i) => v-dot*axis[i])
  const norm = Math.hypot(...normal)
  const along = (upper*upper-lower*lower+distance*distance)/(2*distance)
  const height = Math.sqrt(Math.max(0,upper*upper-along*along))
  return shoulder.map((v,i) => v+axis[i]*along+normal[i]/norm*height)
}
// Smooth rest -> lift -> sip hold -> lower -> rest; hips and feet never bob.
export function loungePose(slot, profile, tSec) {
  const phase = ((tSec / 12 + posePhase(profile)) % 1 + 1) % 1
  const smooth = v => { v = Math.max(0, Math.min(1, v)); return v * v * (3 - 2 * v) }
  const lift = phase < 0.25 ? 0 : phase < 0.48 ? smooth((phase - 0.25) / 0.23)
    : phase < 0.64 ? 1 : phase < 0.88 ? 1 - smooth((phase - 0.64) / 0.24) : 0
  const stage = phase < 0.25 || phase >= 0.88 ? 'rest' : phase < 0.48 ? 'lift' : phase < 0.64 ? 'sip' : 'lower'
  const breath = 0.004 * Math.sin(tSec * 1.1 + posePhase(profile) * 6.28)
  const topZ = 1.06 + breath
  const head = [slot.x, slot.y, topZ + 0.37]
  const mix = (a,b) => a + (b-a)*lift
  const cup = [slot.x + mix(0.37, 0.12), slot.y + mix(0.12, 0.10), mix(0.68, head[2] - 0.206)]
  const hand = [cup[0] + 0.08, cup[1] - 0.015, cup[2] + 0.015]
  const shoulders = [[slot.x-0.24,slot.y,topZ-0.09],[slot.x+0.24,slot.y,topZ-0.09]]
  const lapHand = [slot.x-0.16,slot.y+0.17,0.39]
  const elbows = [armElbow(shoulders[0],lapHand,0.33,0.30,[-1,0.35,0]),
    armElbow(shoulders[1],hand,0.32,0.32,[1,0,0])]
  return {phase, lift, stage, topZ, seatZ: 0.46, head, headR: 0.26, cup, hand,
    shoulders, elbows, lapHand,
    legs: [-1,1].map(a => ({hip:[slot.x+a*0.14,slot.y,0.49],
      knee:[slot.x+a*0.20,slot.y+0.18,0.26],foot:[slot.x+a*0.23,slot.y+0.21,0.05]}))}
}
// Explicit shoulder/elbow/wrist segments, with a rounded joint at the elbow.
export function drawPoseArm(c, project, shoulder, elbow, hand, width, cloth, skin) {
  const a=project(shoulder), b=project(elbow), d=project(hand)
  drawLimb(c,a,b,width,cloth)
  drawLimb(c,b,d,width*0.86,cloth)
  drawPalm(c,d,width,skin)
}

export function drawDeskAndAvatar(c, ox, oy, scale, slot, entry, index, tSec, palette) {
  const { stroke, textSec, textTer, textQuat, accent, P } = palette
  const online = !!entry.online
  const busy = !!entry.busy
  const alpha = online ? 1 : 0.45
  const pcolor = entry.color || accent
  const S = deskLayout(slot)

  c.save()
  c.globalAlpha = alpha

  // ---- Desk ----------------------------------------------------------------
  // Grounding shadow, then a soft-shaded top so the wood catches the light
  // along its back edge instead of reading as a wireframe box.
  softShadow(c, ox, oy, slot.x + DESK_W / 2, slot.y + DESK_D / 2, 1.05, scale,
    P.shadowInk, 0.20)
  drawIsoBoxSoft(c, ox, oy, slot.x, slot.y, 0, DESK_W, DESK_D, 0.75, scale, P.deskWood)

  // ---- Monitor: plinth + neck + bezel panel, and the light it throws ------
  const monX = S.monX
  const monY = S.monY
  const panW = S.panW
  const panD = S.panD
  const panH = S.panH
  const panZ = S.panZ
  const monCX = monX + panW * 0.5
  const monCY = monY + panD * 0.5
  drawIsoDiscSoft(c, ox, oy, monCX, monCY, 0.77, 0.15, scale, P.monitorShell, { top: 0.10 })
  drawCylinder(c, ox, oy, monCX, monCY, 0.75, panZ + 0.02, 0.045, scale, P.monitorShell)
  // The halo the panel throws is drawn BEFORE the panel, so it spills around it
  // rather than washing over the screen. Additive, tinted by the running state.
  if (online) {
    const glowInk = busy ? P.screenGreenBusy : P.screenGreenIdle
    const rgb = hexToRgb(glowInk) || { r: 140, g: 230, b: 170 }
    const [gx, gy] = screenPt(ox, oy, monCX, monCY, panZ + panH * 0.5, scale)
    const gr = Math.max(6, panW * 0.5 * scale * 2.0)
    const gg = c.createRadialGradient(gx, gy, gr * 0.10, gx, gy, gr)
    gg.addColorStop(0, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ', 0.16)')
    gg.addColorStop(0.5, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ', 0.06)')
    gg.addColorStop(1, 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ', 0)')
    c.save()
    c.globalCompositeOperation = 'lighter'
    fillEllipse(c, gx, gy, gr, gr, gg)
    c.restore()
  }
  drawIsoBoxSoft(c, ox, oy, monX, monY, panZ, panW, panD, panH, scale,
    P.monitorShell, { top: 0.16 })

  // The screen itself: the panel's FRONT face (+y side), inset for the bezel.
  // (u, v) ∈ [0,1]² maps onto that inset parallelogram, so the fake code lines
  // land on the glass rather than over the frame.
  const bezU0 = 0.055
  const bezU1 = 0.945
  const bezV0 = 0.07
  const bezV1 = 0.93
  const sp = (u, v) => screenPt(
    ox, oy,
    monX + (bezU0 + u * (bezU1 - bezU0)) * panW,
    monY + panD,
    panZ + (bezV0 + v * (bezV1 - bezV0)) * panH,
    scale,
  )
  {
    const p00 = sp(0, 0)
    const p10 = sp(1, 0)
    const p11 = sp(1, 1)
    const p01 = sp(0, 1)
    // Cool-grey glass either way: brightness alone signals on/off, so the
    // screen never clashes with the profile-colored person in front of it.
    const sg = c.createLinearGradient(p01[0], p01[1], p11[0], p11[1])
    sg.addColorStop(0, online ? P.screenOnGlow : P.screenOffGlow)
    sg.addColorStop(1, online ? P.screenOnBase : P.screenOff)
    c.beginPath()
    c.moveTo(p00[0], p00[1])
    c.lineTo(p10[0], p10[1])
    c.lineTo(p11[0], p11[1])
    c.lineTo(p01[0], p01[1])
    c.closePath()
    c.fillStyle = sg
    c.fill()
  }

  // Screen CONTENT when online: fake code/UI lines so a running station looks
  // alive. Terminal-green regardless of the profile hue.
  if (online) {
    c.save()
    const screenText = busy ? P.screenGreenBusy : P.screenGreenIdle
    // Title bar across the top.
    c.strokeStyle = screenText
    c.lineWidth = 2
    const [tx0, ty0] = sp(0.10, 0.86)
    const [tx1, ty1] = sp(0.58, 0.86)
    c.beginPath(); c.moveTo(tx0, ty0); c.lineTo(tx1, ty1); c.stroke()
    // Code lines: a few left-aligned rows of varying width, brighter when busy.
    c.lineWidth = busy ? 1.6 : 1.2
    const rows = [
      [0.10, 0.68, 0.58],
      [0.18, 0.56, 0.66],
      [0.18, 0.44, 0.44],
      [0.10, 0.32, 0.62],
      [0.26, 0.20, 0.36],
    ]
    for (let i = 0; i < rows.length; i++) {
      const [uStart, v, uLen] = rows[i]
      c.strokeStyle = screenText
      const [ax2, ay2] = sp(uStart, v)
      const [bx2, by2] = sp(uStart + uLen, v)
      c.beginPath(); c.moveTo(ax2, ay2); c.lineTo(bx2, by2); c.stroke()
    }
    // Busy: a blinking cursor block at the end of an active line.
    if (busy) {
      const blink = (Math.sin(tSec * 4 + index) + 1) / 2
      c.globalAlpha = 0.35 + 0.55 * blink
      c.fillStyle = screenText
      const [cxp, cyp] = sp(0.60, 0.68)
      const [cxp2] = sp(0.64, 0.68)
      const cw = Math.abs(cxp2 - cxp) || 3
      c.fillRect(cxp, cyp - 3, cw, 6)
    }
    c.restore()
  }

  // ---- Keyboard + mouse: what the hands are actually on -------------------
  // Without these the hands hovered over a bare desktop and the arms had to
  // reach to the monitor to land anywhere. The keyboard sits at the FRONT of
  // the desk, close to the sitter, so the arms fall forward-and-down.
  const kbX = S.kbX
  const kbY = S.kbY
  const kbW = S.kbW
  const kbD = S.kbD
  drawIsoBoxSoft(c, ox, oy, kbX, kbY, 0.75, kbW, kbD, 0.045, scale,
    P.keyboard, { top: 0.06, edgeAlpha: 0.10 })
  drawIsoDiscSoft(c, ox, oy, kbX + kbW + 0.13, kbY + kbD * 0.5, 0.795, 0.065,
    scale, P.keyboard, { top: 0.16 })

  // A mug on the free right-hand end of the desk, so the surface is not bare.
  const mugX = S.mugX
  const mugY = S.mugY
  drawCylinder(c, ox, oy, mugX, mugY, 0.75, 0.90, 0.10, scale, P.chairBackTop)
  drawIsoDiscSoft(c, ox, oy, mugX, mugY, 0.905, 0.075, scale, P.hair, { top: 0.10 })

  // ---- Chair: plinth + gas post + cushion (the backrest paints later) -----
  // The sitter sits at the LEFT end of the desk, not on the centre line: in this
  // projection "forward" (-y) also moves a point up-and-right on screen, so a
  // centred sitter leaves their hands inside their own torso silhouette (they
  // read as sitting on their lap). Clearance is a property of (x - y): a hand
  // shows outside the torso only when its (x - y) exceeds the torso's by ~0.41.
  const chairX = S.chairX
  const chairY = S.chairY
  const chairCX = S.cx
  const chairCY = S.cy
  drawIsoDiscSoft(c, ox, oy, chairCX, chairCY, 0.02, 0.30, scale, P.chairBase, { top: 0.08 })
  drawCylinder(c, ox, oy, chairCX, chairCY, 0.02, 0.34, 0.055, scale, P.chairPost)
  drawCylinder(c, ox, oy, chairCX, chairCY, 0.34, 0.48, 0.33, scale, P.chairTop)
  // Chair BACK is drawn later (after the sitter) so it correctly occludes their
  // lower back — in iso painter's order the backrest sits at the highest +y and
  // must paint last.
  const drawChairBack = () => {
    drawIsoBoxSoft(c, ox, oy, chairX + 0.02, chairY + 0.72, 0.46, 0.86, 0.16, 0.62,
      scale, P.chairBackTop, { top: 0.14 })
  }

  // At-desk avatar only when busy and actually in the chair (not walking to it).
  const seated = busy && entry.seated !== false
  if (seated) {
    const pose = deskPose(slot, entry.profile, tSec)
    const typing = pose.breath
    const cxw = S.cx // sitter centre (world)
    const cyw = S.cy
    const seatZ = S.seatZ + typing
    const topZ = S.topZ + typing

    // The sitter is a shaded FIGURE: a grounding shadow, a gradient-cylinder
    // torso (the CLOTHES carry the profile color = identity, while skin/hair stay
    // neutral), a NARROW neck so the head is not a ball glued to the shoulders,
    // two arms reaching down-forward onto the keyboard, and a sphere head.
    // The arms are painted BEFORE the torso, and that ordering is the whole fix:
    // each shoulder sits INSIDE the torso's silhouette while each hand is well
    // OUTSIDE it, so the body occludes the top of every arm and both hands stay
    // visible on the keys. Painting the arms LAST instead lays the near hand ON
    // TOP of the body (the layering bug) — only the draw order matters here.
    const armW = Math.max(1.5, 0.15 * scale)
    const armBase = shade(pcolor, -0.20)
    const project = p => screenPt(ox,oy,...p,scale)
    softShadow(c, ox, oy, cxw, cyw, 0.72, scale, P.shadowInk, 0.30)
    // Both arms remain behind the torso, preserving the approved handedness.
    for (let a=0;a<2;a++) drawPoseArm(c,project,pose.shoulders[a],pose.elbows[a],
      pose.hands[a],armW,armBase,P.skin)

    drawFigureTorso(c,ox,oy,cxw,cyw,seatZ,topZ,S.torsoR,scale,pcolor,P.trouser)
    // Only a small outer sleeve cap crosses the torso silhouette. Keep the
    // distant forearm/hand behind the body and the cap well away from the neck;
    // the anatomical shoulder and all workstation coordinates stay untouched.
    c.save()
    const torsoCentre = project([cxw,cyw,topZ])
    c.beginPath()
    c.rect(torsoCentre[0]-scale,torsoCentre[1]-0.065*scale,0.88*scale,0.25*scale)
    c.clip()
    const capEnd = pose.shoulders[0].map((v,i) => v+(pose.elbows[0][i]-v)*0.38)
    drawLimb(c,project(pose.shoulders[0]),project(capEnd),armW,armBase)
    c.restore()
    // Collar + neck. The collar (clothes, wider) frames the neck, and the head
    // sits low enough that the neck is nearly all covered — a bare skin
    // cylinder on the shoulders read as a bald patch.
    drawFigureBand(c, ox, oy, cxw, cyw, topZ - 0.07, S.collarTopZ + typing, S.collarR,
      scale, shade(pcolor, -0.14))
    drawFigureBand(c, ox, oy, cxw, cyw, topZ - 0.08, S.neckTopZ + typing, S.neckR,
      scale, P.skin)

    // Head: shaded sphere + hair; the blink is a rare, quick squash. Facing is
    // the DESK direction (-y in world = up-right on screen), so we see the back
    // of the head — the sitter is looking at the monitor, not out at us.
    const headR = S.headR * scale
    const [hx, hy] = screenPt(ox, oy, cxw, cyw, S.headCz + typing, scale)
    const blink = Math.sin(tSec * 1.4 + index * 2.1) > 0.965 ? 0.14 : 1
    drawHead(c, hx, hy, headR, {
      skin: P.skin,
      skinShadow: P.skinShadow,
      hair: P.hair,
      hairLit: P.hairLit,
      facing: DESK_FACING,
      blink,
    })

    // Backrest paints after the sitter so it occludes their back.
    drawChairBack()

    // Floating name label just above the head.
    const nameFontPx = 10
    c.font = nameFontPx + 'px system-ui, -apple-system, "Segoe UI", sans-serif'
    c.textAlign = 'center'
    drawNameBadge(c, profileName(entry), hx, hy - headR - 6, {
      fontPx: nameFontPx,
      textColor: nameInk(pcolor, P),
      borderColor: P.pillBorder,
      pillColor: P.pillColor,
      dotColor: null,
    })
    c.textAlign = 'start'
  } else {
    // Empty chair (idle/offline): still draw the backrest for a complete chair.
    drawChairBack()
  }

  // When NOT busy, the desk is empty (idle -> person is in the lounge;
  // offline -> person hasn't shown up). Still label the empty desk above the
  // chair so you can tell whose station it is. Offline reads dim (grey);
  // idle reads in the profile color.
  if (!seated) {
    const [dnx, dny] = iso(monX + 0.4, monY + 0.4, 2.1, scale)
    const deskNameFontPx = 10
    c.save()
    c.globalAlpha = 1
    c.font = deskNameFontPx + 'px system-ui, -apple-system, "Segoe UI", sans-serif'
    c.textAlign = 'center'
    drawNameBadge(c, profileName(entry), ox + dnx, oy + dny, {
      fontPx: deskNameFontPx,
      textColor: online ? nameInk(pcolor, P) : P.offlineNameColor,
      borderColor: P.pillBorder,
      pillColor: P.pillColor,
      dotColor: null,
    })
    c.textAlign = 'start'
    c.restore()
  }

  c.restore()
}

export function drawLoungeAvatar(c, ox, oy, scale, slot, entry, index, tSec, idx, palette) {
  const { stroke, textSec, textTer, accent, P } = palette
  const online = !!entry.online
  const alpha = online ? 1 : 0.35
  const pcolor = entry.color || accent
  const pose = loungePose(slot, entry.profile, online ? tSec : 0)
  const project = p => screenPt(ox,oy,...p,scale)

  c.save()
  c.globalAlpha = alpha

  // Stool: a neutral column with a seat cushion on top, so the sitter has
  // something to sit on and legs that reach the floor.
  softShadow(c, ox, oy, slot.x, slot.y - 0.14, 0.62, scale, P.shadowInk, 0.26)
  drawCylinder(c, ox, oy, slot.x, slot.y, 0, 0.38, 0.28, scale, P.chairPost)
  drawCylinder(c, ox, oy, slot.x, slot.y, 0.38, 0.45, 0.33, scale, P.stool)
  drawIsoDiscSoft(c, ox, oy, slot.x, slot.y, 0.455, 0.33, scale, P.chairTop, { top: 0.16 })

  const seatZ = pose.seatZ
  const legW = Math.max(1.5, 0.17 * scale)
  for (const leg of pose.legs) {
    const hip=project(leg.hip), knee=project(leg.knee), foot=project(leg.foot)
    drawLimb(c,hip,knee,legW,P.trouser)
    drawLimb(c,knee,foot,legW*0.86,P.trouser)
    figurePoly(c,[[foot[0]-legW*.45,foot[1]-legW*.22],[foot[0]+legW*.65,foot[1]-legW*.15],[foot[0]+legW,foot[1]+legW*.40],[foot[0]-legW*.35,foot[1]+legW*.45]],P.shoe)
  }
  const topZ = pose.topZ
  const armW = Math.max(1.4, 0.145 * scale)
  const handBase = shade(pcolor,-0.16)
  // Far sleeve disappears behind the body; its hand rests visibly on the knee.
  drawPoseArm(c,project,pose.shoulders[0],pose.elbows[0],pose.lapHand,armW,handBase,P.skin)
  drawFigureTorso(c,ox,oy,slot.x,slot.y,seatZ,topZ,.26,scale,pcolor,P.trouser)
  drawFigureBand(c,ox,oy,slot.x,slot.y,topZ-0.03,topZ+0.11,0.105,scale,P.skin)
  const headR = pose.headR
  const headCZ = pose.head[2]
  const [hx,hy] = project(pose.head)
  const blink = Math.sin(tSec * 1.4 + idx * 2.1) > 0.965 ? 0.14 : 1
  drawHead(c, hx, hy, headR * scale, {
    skin: P.skin,
    skinShadow: P.skinShadow,
    hair: P.hair,
    hairLit: P.hairLit,
    facing: LOUNGE_FACING,
    blink,
  })

  // Near arm and cup share one pose. Cup rim stops at the LOWER lip, not
  // through the face; cup body and grasp paint in front of the raised forearm.
  drawPoseArm(c,project,pose.shoulders[1],pose.elbows[1],pose.hand,armW,handBase,P.skin)
  if (online) {
    const [cupX,cupY,cupZ] = pose.cup
    drawCylinder(c,ox,oy,cupX,cupY,cupZ-0.055,cupZ+0.08,0.085,scale,'#f2ede4')
    drawIsoDiscSoft(c,ox,oy,cupX,cupY,cupZ+0.082,0.067,scale,'#76543b')
    const hp=project(pose.hand)
    drawPalm(c,hp,armW*.85,P.skin,true)
  }

  // Floating name label just above the head disc.
  // Draw at full opacity (outside the avatar's dimming alpha) so the name
  // stays legible even when the avatar is offline/greyed.
  const [nhx, nhy] = iso(slot.x, slot.y, headCZ + headR, scale)
  const nameY = oy + nhy - 6
  const nameFontPx = 10
  c.save()
  c.globalAlpha = 1
  c.font = nameFontPx + 'px system-ui, -apple-system, "Segoe UI", sans-serif'
  c.textAlign = 'center'
  drawNameBadge(c, profileName(entry), ox + nhx, nameY, {
    fontPx: nameFontPx,
    textColor: nameInk(pcolor, P),
    borderColor: P.pillBorder,
    pillColor: P.pillColor,
    dotColor: null,
  })

  // Idle duration — only for online, non-busy avatars with a valid idle_since.
  // (drawLoungeAvatar is only called when !busy, so we just check online + idle_since.)
  if (online && entry.idle_since != null && Number.isFinite(entry.idle_since)) {
    const elapsedMs = Date.now() - entry.idle_since * 1000
    const idleFontPx = 9
    c.font = idleFontPx + 'px system-ui, -apple-system, "Segoe UI", sans-serif'
    // Profile-colored text on the dark pill, same as the name, so it reads
    // clearly. Placed ABOVE the name pill (smaller screen-y) so it never
    // overlaps the avatar's head/body which sit below the name.
    drawNameBadge(c, formatIdle(elapsedMs), ox + nhx, nameY - (nameFontPx + 2), {
      fontPx: idleFontPx,
      textColor: nameInk(pcolor, P),
      borderColor: P.pillBorder,
      pillColor: P.pillColor,
      dotColor: null,
    })
  }
  c.textAlign = 'start'
  c.restore()

  c.restore()
}

// ---------------------------------------------------------------------------
// React components.
// ---------------------------------------------------------------------------
