// Office life for Harvis: where each bot's figure is right now. Upstream Office 3D
// teleports a figure between its desk and the lounge; here a bot whose real state
// changes walks there along the aisles and the hallway, an idle bot sometimes
// strolls out to the hallway, and an idle bot sometimes says a line of chatter.
//
// Only real state changes move a bot between zones. Strolls and chatter are
// decoration: every chatter bubble is kind 'sim' and is drawn differently from a
// 'real' bubble, which only ever carries a real session title.
//
// Pure: no canvas, no DOM, no clock of its own. The caller passes time in seconds.

import { deskLayout } from './avatars.js'
import { LOUNGE_GAP, deskSlot, loungeSeat } from './layout.js'

export const WALK_SPEED = 1.5 // world units per second
export const DOOR_X = -0.8 // off the floor's west edge; figures fade in and out here

// Short, harmless lines. None of them claims work, results or anything a bot did.
export const SIM_LINES = [
  'tea is good today',
  'stretching for a sec',
  'anyone seen my mug?',
  'nice and quiet',
  'hm.',
  'brb',
  '*hums*',
  'lo-fi on?',
  'back in a bit',
  'good chair, this one',
]

export function hashString(text) {
  let h = 2166136261
  for (const ch of String(text || '')) {
    h ^= ch.charCodeAt(0)
    h = Math.imul(h, 16777619) >>> 0
  }
  return h >>> 0
}

// Deterministic 0..1 noise from a bot key and a counter, so tests can pin it.
export function noise(key, n) {
  let x = (hashString(key) ^ Math.imul(n + 1, 2654435761)) >>> 0
  x = Math.imul(x ^ (x >>> 15), 2246822507) >>> 0
  x = Math.imul(x ^ (x >>> 13), 3266489909) >>> 0
  return ((x ^ (x >>> 16)) >>> 0) / 4294967296
}

export function hallY(L) {
  return L.workH + LOUNGE_GAP / 2
}

// The point a bot occupies at a place, and the walk from there out to the hallway.
export function placeChain(place, L) {
  const hy = hallY(L)
  if (place.kind === 'desk') {
    const slot = deskSlot(place.index, L.cols)
    const S = deskLayout(slot)
    const aisleY = slot.y + 2.3
    const aisleX = slot.x + 2.9
    return [[S.cx, S.cy], [S.cx, aisleY], [aisleX, aisleY], [aisleX, hy]]
  }
  if (place.kind === 'seat') {
    const seat = loungeSeat(place.index, place.total, L)
    const pods = L.lounges && L.lounges.length ? L.lounges : [L.lounge]
    const pod = pods[Math.min(pods.length - 1, Math.floor(place.index / 6))]
    const cx = pod.x + 2.0
    const laneX = seat.x >= cx ? cx + 2.6 : cx - 2.6
    return [[seat.x, seat.y], [laneX, seat.y], [laneX, hy]]
  }
  if (place.kind === 'spot') return [[place.x, hy]]
  return [[DOOR_X, hy]]
}

// A route from one place to another: out to the hallway, along it, and back in.
export function route(from, to, L) {
  const out = placeChain(from, L)
  const back = placeChain(to, L).slice().reverse()
  const path = out.concat(back)
  return path.filter((p, i) => i === 0 || Math.hypot(p[0] - path[i - 1][0], p[1] - path[i - 1][1]) > 1e-6)
}

function placeId(place) {
  return place ? place.kind + ':' + (place.index ?? '') : 'gone'
}

function homeOf(entry, index, idleIndex, idleTotal) {
  if (entry.state === 'busy') return { kind: 'desk', index }
  if (entry.state === 'idle') return { kind: 'seat', index: idleIndex, total: idleTotal }
  return null
}

function pointOf(place, L) {
  return placeChain(place, L)[0]
}

export function createOfficeLife() {
  const bots = new Map()
  let lastT = null
  let primed = false
  let layoutShape = null

  function startWalk(bot, path, tSec) {
    bot.path = path.slice(1)
    bot.x = path[0][0]
    bot.y = path[0][1]
    bot.walkStart = tSec
  }

  // A walk's points belong to the layout it was planned on. When the office grows or
  // shrinks mid-walk, re-plan from where the figure stands so it never walks off the floor.
  function replan(L) {
    const hy = hallY(L)
    for (const bot of bots.values()) {
      bot.x = Math.max(DOOR_X, Math.min(L.worldW, bot.x))
      bot.y = Math.max(0, Math.min(L.worldH, bot.y))
      if (!bot.path.length) {
        // Resting at a desk or seat: the grid may have reflowed under it.
        if (bot.at && (bot.at.kind === 'desk' || bot.at.kind === 'seat')) [bot.x, bot.y] = pointOf(bot.at, L)
        else if (bot.at && bot.at.kind === 'spot') bot.y = hy
        continue
      }
      if (!bot.dest) continue
      let dest = bot.dest
      if (dest.kind === 'spot') dest = { ...dest, x: Math.min(dest.x, Math.max(1, L.worldW - 1)) }
      if (dest.kind === 'desk' && dest.index >= L.cols * L.rows) dest = { kind: 'door' }
      bot.dest = dest
      const back = placeChain(dest, L).slice().reverse()
      const path = [[bot.x, hy], ...back]
      bot.path = path.filter((p, i) => Math.hypot(p[0] - (i ? path[i - 1][0] : bot.x), p[1] - (i ? path[i - 1][1] : bot.y)) > 1e-6)
    }
  }

  function update(entries, L, tSec) {
    const list = Array.isArray(entries) ? entries : []
    const shape = [L.cols, L.rows, L.worldW, (L.lounges || []).length].join(':')
    if (layoutShape !== null && shape !== layoutShape) replan(L)
    layoutShape = shape
    const dt = lastT == null ? 0 : Math.max(0, Math.min(0.25, tSec - lastT))
    lastT = tSec
    const idleTotal = list.filter(e => e.state === 'idle').length
    let idleIndex = 0
    const seen = new Set()
    const figures = []

    list.forEach((entry, index) => {
      const key = entry.key
      seen.add(key)
      const home = homeOf(entry, index, entry.state === 'idle' ? idleIndex++ : -1, idleTotal)
      let bot = bots.get(key)
      if (!bot) {
        bot = { at: null, path: [], x: DOOR_X, y: hallY(L), linger: 0, stroll: false, said: 0, bubble: null,
          nextStroll: tSec + 20 + noise(key, 1) * 50, nextLine: tSec + 6 + noise(key, 2) * 30, busySince: null }
        bots.set(key, bot)
        if (!primed && home) {
          // First paint: everyone is already where the data says. No made-up entrance.
          bot.at = home
          ;[bot.x, bot.y] = pointOf(home, L)
        } else if (home) {
          bot.at = { kind: 'door' }
        }
      }

      const want = placeId(home)
      const walking = bot.path.length > 0
      // A seated bot whose seat or desk moved (roster order, lounge size) just takes it.
      if (!walking && bot.at && home && bot.at.kind === home.kind && placeId(bot.at) !== want) {
        bot.at = home
        ;[bot.x, bot.y] = pointOf(home, L)
      } else if (!walking && bot.at && home && bot.at.kind === home.kind && home.kind === 'seat') {
        bot.at = home // same seat, but keep its total current for the ring
        ;[bot.x, bot.y] = pointOf(home, L)
      }
      const atHome = bot.at && bot.at.kind !== 'spot' && (placeId(bot.at) === want || (!home && bot.at.kind === 'door'))
      if (!walking && bot.linger <= 0 && !atHome && bot.at) {
        startWalk(bot, route(bot.at, home || { kind: 'door' }, L), tSec)
        bot.dest = home || { kind: 'door' }
        bot.stroll = false
      }

      // Busy now: a real bubble with the real session title, once on start and then now and then.
      if (entry.state === 'busy') {
        if (bot.busySince == null) bot.busySince = tSec
        const since = tSec - bot.busySince
        if (entry.task && (since < 0.1 || (since % 75 < dt && since > 1))) {
          bot.bubble = { kind: 'real', text: entry.task, until: tSec + 6 }
        }
      } else {
        bot.busySince = null
      }

      advance(bot, entry, L, tSec, dt, home)
      if (bot.bubble && bot.bubble.until <= tSec) bot.bubble = null

      const gone = !bot.path.length && (!bot.at || bot.at.kind === 'door')
      if (gone) return
      const walkingNow = bot.path.length > 0
      const target = walkingNow ? bot.path[0] : null
      figures.push({
        index,
        key,
        x: bot.x,
        y: bot.y,
        mode: walkingNow ? 'walk' : bot.at.kind === 'desk' ? 'desk' : bot.at.kind === 'seat' ? 'seat' : 'stand',
        seat: bot.at && bot.at.kind === 'seat' && !walkingNow ? bot.at : null,
        dir: target ? [target[0] - bot.x, target[1] - bot.y] : [0, 1],
        walkStart: bot.walkStart || 0,
        bubble: bot.bubble,
      })
    })

    for (const key of [...bots.keys()]) if (!seen.has(key)) bots.delete(key)
    primed = true
    return figures
  }

  function advance(bot, entry, L, tSec, dt, home) {
    if (bot.path.length) {
      let step = WALK_SPEED * dt
      while (step > 0 && bot.path.length) {
        const [tx, ty] = bot.path[0]
        const d = Math.hypot(tx - bot.x, ty - bot.y)
        if (d <= step) {
          bot.x = tx
          bot.y = ty
          step -= d
          bot.path.shift()
        } else {
          bot.x += ((tx - bot.x) / d) * step
          bot.y += ((ty - bot.y) / d) * step
          step = 0
        }
      }
      if (!bot.path.length) {
        bot.at = bot.dest
        if (bot.at && bot.at.kind === 'spot') bot.linger = 5 + noise(entry.key, Math.floor(tSec)) * 6
      }
      return
    }
    if (bot.linger > 0) {
      bot.linger -= dt
      if (bot.linger <= 0 && bot.at && bot.at.kind === 'spot') {
        // Stroll over: back to wherever the data says this bot belongs now.
        bot.dest = home || { kind: 'door' }
        startWalk(bot, route(bot.at, bot.dest, L), tSec)
      }
    }
    if (entry.state !== 'idle' || !bot.at) return
    if (tSec >= bot.nextLine) {
      bot.said++
      bot.nextLine = tSec + 18 + noise(entry.key, 100 + bot.said) * 40
      const line = SIM_LINES[Math.floor(noise(entry.key, 200 + bot.said) * SIM_LINES.length)]
      bot.bubble = { kind: 'sim', text: line, until: tSec + 4.5 }
    }
    if (bot.at.kind === 'seat' && tSec >= bot.nextStroll) {
      bot.nextStroll = tSec + 45 + noise(entry.key, 300 + bot.said) * 75
      const x = 1 + noise(entry.key, 400 + bot.said) * Math.max(1, L.worldW - 2)
      bot.dest = { kind: 'spot', x, index: 0 }
      bot.stroll = true
      startWalk(bot, route(bot.at, bot.dest, L), tSec)
    }
  }

  return { update, bots }
}
