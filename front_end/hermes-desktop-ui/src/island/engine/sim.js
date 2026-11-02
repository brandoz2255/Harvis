// Island simulation: agents walk tile-by-tile with tile reservation.
// Design (ours), informed by the REA Stardew run:
//  - routes plan against the map only (Stardew schedule A* ignores characters);
//  - conflicts resolve at runtime: claim the next tile before entering it, wait if
//    it is taken, replan after a short wait, give up after ~5 s (Stardew: 5000 ms);
//  - head-on standoffs use a fixed priority (Stardew: name compare), but the loser
//    steps aside instead of freezing, so nobody ever overlaps.
import { key } from "./world.js";
import { findPath } from "./pathfinding.js";
import { lineOfSight } from "./world.js";
import { chatChance, buildTopicPool, openerFor, replyFor } from "./social.js";
import { pickOutfit, DEFAULT_WARDROBE } from "./appearance.js";

export const TICK_MS = 1000 / 60;
/** Tiles per tick. Sprint is the hard cap any agent may move in one tick. */
export const SPEED = { walk: 0.05, sprint: 0.11 };
export const SPRINT_MIN_STEPS = 8; // routes at least this long are sprinted
const REPLAN_AFTER = 24; // ticks waiting before rerouting around others (~0.4 s)
const GIVE_UP_AFTER = Math.round(5000 / TICK_MS); // Stardew pausedTimer limit
const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];

// Clock: 10 game minutes per 7 real seconds (Stardew's documented pace).
export const TICKS_PER_10MIN = Math.round(7000 / TICK_MS); // 420
export const DAY_START_MIN = 6 * 60;
// Social timings (Stardew sayHiTo / showTextAboveHead / updateEmote, Terraria ~7 s chats).
export const BUBBLE_TICKS = Math.round(3000 / TICK_MS); // 180
export const CHAT_TICKS = Math.round(7000 / TICK_MS); // 420
const REPLY_DELAY = [Math.round(1000 / TICK_MS), Math.round(500 / TICK_MS)]; // 60 + 0..30
const REPLY_CHANCE = 0.66;
const CHAT_COOLDOWN = TICKS_PER_10MIN * 3; // 30 game minutes before chatting again
const CHAT_RANGE = 4; // tiles (Manhattan), plus line of sight
const LOOK_RANGE = 5; // '!' reaction radius
const EMOTE_FRAMES = 4;
const EMOTE_FADE_TICKS = 1; // ~20 ms per fade frame
const EMOTE_HOLD_TICKS = Math.round(250 / TICK_MS); // 15 per held frame
// Daily life.
const SLEEPY_HOUR = 21; // pajamas on
const BED_HOUR = 22; // walk to bed
const WAKE_HOUR = 6;
const WANDER_GAP = [360, 360]; // 6 s + 0..6 s (Stardew randomSquareMovement: 6000-12000 ms)
const WANDER_RADIUS = 3;
// Pet sleep spot chances (Stardew PetData.SleepOnBedChance / NearBed / Rug).
const PET_WARDROBE = [{ id: "fur", precedence: 0 }, { id: "fur", precedence: 0, slot: "sleepy" }];
const PET_SLEEP = { bed: 0.4, nearBed: 0.35, rug: 0.25 };

export class Sim {
  constructor({ world, agents, autonomy = true, wander = false, rng = Math.random, weather = "sun", season = "summer", festival = null }) {
    this.world = world;
    this.autonomy = autonomy;
    this.wander = wander;
    this.rng = rng;
    this.weather = weather;
    this.season = season;
    this.festival = festival;
    this.ticks = 0;
    this.minutes = DAY_START_MIN;
    this.listeners = new Map();
    this.claims = new Map(); // tile key -> agent id (tile stood on + tile being entered)
    this.agents = [];
    for (const cfg of agents) this.addAgent(cfg, { quiet: true });
  }

  /** Add an agent mid-session (Harvis: agent created). Starts on the nearest free tile. */
  addAgent(cfg, { quiet = false } = {}) {
    if (this.agent(cfg.id)) return this.agent(cfg.id);
    let start = { ...cfg.start };
    if (!this.world.isWalkable(start.x, start.y) || this.claimant(start) !== undefined) {
      start = this.nearestFreeTo(start, { id: cfg.id }, 8) ?? start;
    }
    const pet = !!cfg.pet;
    const a = {
      id: cfg.id, name: cfg.name ?? cfg.id, color: cfg.color ?? null, sprite: cfg.sprite ?? null, meta: cfg.meta ?? {},
      persona: cfg.persona ?? {}, pet, schedule: cfg.schedule ?? {},
      wardrobe: cfg.wardrobe ?? (pet ? PET_WARDROBE : DEFAULT_WARDROBE), outfit: null,
      home: { ...start }, nextWanderTick: 0, sleeping: false, bedtime: false, sleepSpot: null, inside: false,
      tile: { ...start }, next: null, progress: 0, pos: { ...start }, path: [], goal: null,
      speed: SPEED.walk, facing: "down", waited: 0, status: "idle",
      chat: null, chatCooldownUntil: 0, bubble: null, emote: null, activity: null, pendingSay: null, lastSaid: null,
    };
    // Beds / home doors come from the map, handed out to whichever agents the session has.
    const taken = new Set(this.agents.map((b) => b.bed && `${b.bed.x},${b.bed.y}`));
    const pool = (pet ? this.world.petBeds : this.world.beds) ?? [];
    a.bed = cfg.bed ?? pool.find((b) => !taken.has(`${b.x},${b.y}`)) ?? null;
    const doors = this.world.homeDoors ?? [];
    a.homeDoor = cfg.homeDoor ?? doors[(cfg.homeIndex ?? this.agents.length) % (doors.length || 1)] ?? null;
    a.nextWanderTick = this.ticks + WANDER_GAP[0] + Math.floor(this.rng() * WANDER_GAP[1]);
    this.agents.push(a);
    this.claim(a, a.tile);
    this.dressFor(a);
    if (!quiet) this.emit("agentAdded", { id: a.id });
    return a;
  }

  /** Remove an agent (Harvis: agent deleted). Frees its tiles and ends its chat. */
  removeAgent(id) {
    const a = this.agent(id);
    if (!a) return false;
    if (a.chat) this.endChat(a);
    for (const t of [a.tile, a.next]) if (t) this.release(a, t);
    this.agents = this.agents.filter((b) => b !== a);
    this.emit("agentRemoved", { id });
    return true;
  }

  on(event, fn) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(fn);
  }
  emit(event, data) { for (const fn of this.listeners.get(event) ?? []) fn(data); }

  timeString() {
    const m = this.minutes % (24 * 60);
    return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  }
  get hour() { return Math.floor((this.minutes % 1440) / 60); }

  /** Jump the clock (tests, debug panel). */
  setTime(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    this.minutes = h * 60 + m;
  }

  agent(id) { return this.agents.find((a) => a.id === id); }
  claimant(t) { return this.claims.get(key(t.x, t.y)); }
  claim(a, t) { this.claims.set(key(t.x, t.y), a.id); }
  release(a, t) { if (this.claimant(t) === a.id) this.claims.delete(key(t.x, t.y)); }

  /** Tiles held by everyone except `self` (for rerouting around them). */
  othersBlocked(self) {
    const s = new Set();
    for (const [k, id] of this.claims) if (id !== self.id) s.add(k);
    return s;
  }

  orderMove(id, goal) {
    const a = this.agent(id);
    if (a.chat) this.endChat(a);
    a.goal = { ...goal };
    this.plan(a, false);
  }

  plan(a, avoidOthers) {
    const from = a.next ?? a.tile;
    const path = findPath(this.world, from, a.goal, avoidOthers ? { blocked: this.othersBlocked(a) } : {});
    if (!path) return false;
    a.path = path;
    a.speed = path.length >= SPRINT_MIN_STEPS ? SPEED.sprint : SPEED.walk;
    a.status = path.length ? "walking" : "idle";
    a.waited = 0;
    return true;
  }

  tick() {
    this.ticks++;
    for (const a of this.agents) this.step(a);
    for (const a of this.agents) this.updateTimers(a);
    if (this.ticks % TICKS_PER_10MIN === 0) {
      this.minutes += 10;
      this.emit("tenMinutes", { time: this.timeString() });
      if (this.autonomy) {
        this.dailyLife();
        this.socialRoll();
      }
      for (const a of this.agents) this.dressFor(a);
    }
    if (this.wander) for (const a of this.agents) this.maybeWander(a);
  }

  // ---------- daily life ----------

  outfitContext(a) {
    const ch = this.world.charAt(a.tile.x, a.tile.y);
    const indoors = ch === "_" || ch === "b" || ch === "d";
    const sleepy = a.sleeping || this.hour >= SLEEPY_HOUR || this.hour < WAKE_HOUR;
    return { season: this.season, weather: this.weather, festival: this.festival, outdoors: !indoors, slot: sleepy ? "sleepy" : null };
  }

  dressFor(a) {
    const next = pickOutfit(a.wardrobe, this.outfitContext(a), this.rng);
    if (a.outfit?.id !== next.id) { a.outfit = next; this.emit("outfit", { id: a.id, outfit: next.id }); }
  }

  dailyLife() {
    const time = this.timeString(), h = this.hour;
    for (const a of this.agents) {
      if (a.sleeping && h >= WAKE_HOUR && h < BED_HOUR) this.wake(a);
      if (a.sleeping) continue;
      if (h >= BED_HOUR || h < WAKE_HOUR) { this.goToBed(a); continue; }
      const place = a.schedule[time];
      if (place && this.world.places[place] && !a.activity && !a.pendingSay) {
        if (a.chat) this.endChat(a);
        a.home = { ...this.world.places[place] };
        this.orderMove(a.id, this.world.places[place]);
      }
    }
  }

  goToBed(a) {
    const home = a.homeDoor;
    if (!a.sleepSpot) a.sleepSpot = home ?? (a.pet ? this.petSleepSpot(a) : a.bed);
    if (!a.sleepSpot) return;
    a.bedtime = true;
    if (a.chat) this.endChat(a);
    if (a.tile.x === a.sleepSpot.x && a.tile.y === a.sleepSpot.y && !a.next) return this.fallAsleep(a);
    // Shared door: if someone is standing in it, go in once they have.
    if (home && this.claimant(home) !== undefined && this.claimant(home) !== a.id) {
      const next = this.nearestFreeTo(home, a);
      if (next && (!a.goal || a.goal.x !== next.x || a.goal.y !== next.y)) this.orderMove(a.id, next);
      return;
    }
    if (!a.goal || a.goal.x !== a.sleepSpot.x || a.goal.y !== a.sleepSpot.y) this.orderMove(a.id, a.sleepSpot);
  }

  petSleepSpot(a) {
    const r = this.rng();
    const humans = this.agents.filter((b) => b !== a && !b.pet && b.bed).map((b) => [b.id, b.bed]);
    const free = (t) => t && this.world.isWalkable(t.x, t.y) && this.claimant(t) === undefined;
    if (r < PET_SLEEP.bed && a.bed) return a.bed;
    if (r < PET_SLEEP.bed + PET_SLEEP.nearBed && humans.length) {
      const [, bed] = humans[Math.floor(this.rng() * humans.length)];
      const foot = { x: bed.x, y: bed.y + 1 };
      if (free(foot)) return foot;
    }
    const rugs = [];
    for (let y = 0; y < this.world.h; y++) for (let x = 0; x < this.world.w; x++)
      if (this.world.charAt(x, y) === "_" && free({ x, y }) && !this.world.isNoStop(x, y)) rugs.push({ x, y });
    return rugs.length ? rugs[Math.floor(this.rng() * rugs.length)] : a.bed;
  }

  fallAsleep(a) {
    a.sleeping = true;
    a.status = "sleeping";
    a.bubble = null;
    a.facing = "down";
    if (a.homeDoor) {
      // Walked through their door (Stardew villagers going home): leave the map, free the tile.
      a.inside = true;
      this.release(a, a.tile);
    }
    this.dressFor(a);
    this.emit("sleep", { id: a.id });
  }

  wake(a) {
    if (a.inside) {
      const door = a.homeDoor;
      const spot = this.claimant(door) === undefined ? door : this.nearestFreeTo(door, a);
      if (!spot) return; // doorway crowded; try again next tick
      a.tile = { ...spot }; a.pos = { ...spot }; a.next = null; a.path = []; a.goal = null;
      this.claim(a, a.tile);
      a.inside = false;
    }
    a.sleeping = false;
    a.bedtime = false;
    a.sleepSpot = null;
    a.status = "idle";
    this.emit("wake", { id: a.id });
  }

  maybeWander(a) {
    if (a.activity || a.pendingSay || a.inside) return;
    if (a.sleeping || a.bedtime || a.chat || a.goal || a.next || a.path.length) return;
    if (this.ticks < a.nextWanderTick) return;
    const opts = [];
    for (let dy = -WANDER_RADIUS; dy <= WANDER_RADIUS; dy++)
      for (let dx = -WANDER_RADIUS; dx <= WANDER_RADIUS; dx++) {
        const t = { x: a.home.x + dx, y: a.home.y + dy };
        if (Math.abs(dx) + Math.abs(dy) > WANDER_RADIUS || (t.x === a.tile.x && t.y === a.tile.y)) continue;
        if (this.world.isWalkable(t.x, t.y) && !this.world.isNoStop(t.x, t.y) && this.claimant(t) === undefined &&
          this.world.cost(t.x, t.y) < 5) opts.push(t);
      }
    if (!opts.length) return;
    const to = opts[Math.floor(this.rng() * opts.length)];
    this.orderMove(a.id, to);
    a.speed = SPEED.walk; // strolling, never sprinting
    a.nextWanderTick = this.ticks + WANDER_GAP[0] + Math.floor(this.rng() * WANDER_GAP[1]);
    this.emit("wander", { id: a.id, tick: this.ticks, to });
  }

  // ---------- social ----------

  canChat(a) {
    return !a.chat && !a.activity && !a.pendingSay && !a.inside && !a.pet && !a.bedtime && this.ticks >= a.chatCooldownUntil && !a.sleeping &&
      !this.world.isNoStop(a.tile.x, a.tile.y);
  }

  socialRoll() {
    for (const a of this.agents) {
      if (!this.canChat(a)) continue;
      if (this.rng() >= chatChance(a.persona)) continue;
      const partner = this.agents.find((b) => b !== a && this.canChat(b) &&
        Math.abs(b.tile.x - a.tile.x) + Math.abs(b.tile.y - a.tile.y) <= CHAT_RANGE &&
        lineOfSight(this.world, a.tile, b.tile));
      if (partner) this.startChat(a, partner);
    }
  }

  startChat(a, b, opts = {}) {
    const topic = opts.topic ?? this.pickTopic(a, b);
    for (const [me, other] of [[a, b], [b, a]]) {
      me.chat = { with: other.id, topic, endTick: this.ticks + CHAT_TICKS, resumeGoal: me.goal };
      me.path = []; // finish the current step, then stand still
      me.goal = null;
      me.facing = faceToward(me.tile, other.tile);
      if (!me.next) me.status = "idle";
    }
    a.chat.script = [{ who: a, at: this.ticks, text: opts.opener ?? openerFor(topic, this.rng) }];
    if (!opts.opener && this.rng() < REPLY_CHANCE) {
      const at = this.ticks + REPLY_DELAY[0] + Math.floor(this.rng() * REPLY_DELAY[1]);
      a.chat.script.push({ who: b, at, text: replyFor(this.rng) });
      a.chat.script.push({ who: a, at: at + BUBBLE_TICKS, text: replyFor(this.rng) });
    }
    this.emit("chatStart", { a: a.id, b: b.id, topic });
    this.runScript(a);
  }

  /** A real message between two agents (Harvis): chat now if close, else walk over first. */
  deliverMessage(a, b, text) {
    const near = Math.abs(a.tile.x - b.tile.x) + Math.abs(a.tile.y - b.tile.y) <= CHAT_RANGE &&
      lineOfSight(this.world, a.tile, b.tile);
    if (a.chat) this.endChat(a);
    if (near) {
      if (b.chat) this.endChat(b);
      this.startChat(a, b, { opener: text, topic: "message" });
      return true;
    }
    a.pendingSay = { to: b.id, text };
    const spot = this.nearestFreeTo(b.tile, a, 3);
    if (spot) this.orderMove(a.id, spot);
    return true;
  }

  flushPendingSay(a) {
    const p = a.pendingSay;
    if (!p || a.next || a.path.length) return;
    a.pendingSay = null;
    const b = this.agent(p.to);
    const near = b && !b.inside && Math.abs(a.tile.x - b.tile.x) + Math.abs(a.tile.y - b.tile.y) <= CHAT_RANGE + 1;
    if (near) {
      if (b.chat) this.endChat(b);
      this.startChat(a, b, { opener: p.text, topic: "message" });
    } else this.say(a, p.text);
  }

  pickTopic(a, b) {
    const nearby = this.agents.filter((c) => c !== a && c !== b &&
      Math.abs(c.tile.x - a.tile.x) + Math.abs(c.tile.y - a.tile.y) <= 8).map((c) => c.id);
    const pool = buildTopicPool({ weather: this.weather, hour: this.hour, place: this.placeNear(a.tile), nearby }, a.persona);
    return pool[Math.floor(this.rng() * pool.length)];
  }

  placeNear(t) {
    let best = null, bestD = 6;
    for (const [name, p] of Object.entries(this.world.places)) {
      const d = Math.abs(p.x - t.x) + Math.abs(p.y - t.y);
      if (d < bestD) { best = name; bestD = d; }
    }
    return best;
  }

  runScript(a) {
    const script = a.chat?.script;
    while (script?.length && script[0].at <= this.ticks) {
      const line = script.shift();
      this.say(line.who, line.text);
    }
  }

  say(a, text, ticks = BUBBLE_TICKS) {
    a.bubble = { text, until: this.ticks + ticks };
    a.lastSaid = text;
    this.emit("bubble", { id: a.id, text });
  }

  endChat(a) {
    const b = a.chat && this.agent(a.chat.with);
    for (const me of [a, b].filter(Boolean)) {
      if (!me.chat) continue;
      const resume = me.chat.resumeGoal;
      me.chat = null;
      me.chatCooldownUntil = this.ticks + CHAT_COOLDOWN;
      if (resume) { me.goal = resume; this.plan(me, false); }
    }
    this.emit("chatEnd", { a: a.id, b: b?.id });
  }

  // ---------- emotes ----------

  emote(id, kind) {
    const a = this.agent(id);
    if (a.emote) return false; // Stardew doEmote: ignored while one is playing
    a.emote = { kind, frame: 0, phase: "in", t: 0 };
    this.emit("emote", { id, kind });
    if (kind === "!") {
      for (const b of this.agents) {
        if (b === a || b.chat || b.status !== "idle" || b.next) continue;
        const d = Math.abs(b.tile.x - a.tile.x) + Math.abs(b.tile.y - a.tile.y);
        if (d <= LOOK_RANGE && lineOfSight(this.world, b.tile, a.tile)) b.facing = faceToward(b.tile, a.tile);
      }
    }
    return true;
  }

  updateTimers(a) {
    if (a.bubble && this.ticks >= a.bubble.until) a.bubble = null;
    if (a.pendingSay) this.flushPendingSay(a);
    if (a.chat) {
      if (a.chat.script) this.runScript(a);
      if (this.ticks >= a.chat.endTick) this.endChat(a);
    }
    const e = a.emote;
    if (e) {
      e.t++;
      const limit = e.phase === "hold" ? EMOTE_HOLD_TICKS : EMOTE_FADE_TICKS;
      if (e.t >= limit) {
        e.t = 0;
        e.frame++;
        if (e.frame >= EMOTE_FRAMES) {
          e.frame = 0;
          if (e.phase === "in") e.phase = "hold";
          else if (e.phase === "hold") e.phase = "out";
          else a.emote = null;
        }
      }
    }
  }

  step(a) {
    if (!a.next && a.path.length) this.tryClaimNext(a);
    if (!a.next) { a.pos = { ...a.tile }; return; }
    a.progress = Math.min(1, a.progress + a.speed);
    a.pos = {
      x: a.tile.x + (a.next.x - a.tile.x) * a.progress,
      y: a.tile.y + (a.next.y - a.tile.y) * a.progress,
    };
    if (a.progress >= 1) {
      this.release(a, a.tile);
      a.tile = a.next;
      a.next = null;
      a.progress = 0;
      a.pos = { ...a.tile };
      if (!a.path.length && a.afterSidestep) {
        a.goal = a.afterSidestep;
        a.afterSidestep = null;
        this.plan(a, false); // resume the original trip from the side tile
      } else if (!a.path.length) { a.status = "idle"; a.goal = null; }
    }
  }

  tryClaimNext(a) {
    const step = a.path[0];
    a.facing = facingToward(a.tile, step);
    let holder = this.claimant(step);
    // "Don't block the box": only enter a chokepoint if the tile beyond it is free too.
    if ((holder === undefined || holder === a.id) && this.world.isNoStop(step.x, step.y) && a.path[1]) {
      const beyond = this.claimant(a.path[1]);
      if (beyond !== undefined && beyond !== a.id) holder = beyond;
    }
    if (holder === undefined || holder === a.id) {
      a.path.shift();
      a.next = step;
      a.progress = 0;
      a.waited = 0;
      a.status = "walking";
      this.claim(a, step);
      return;
    }
    // Blocked by someone. Wait, then try to route around, then resolve standoffs.
    a.waited++;
    a.status = "waiting";
    const other = this.agent(holder);
    // Destination occupied by someone standing still: stop beside it instead of queuing.
    const isGoal = a.goal && step.x === a.goal.x && step.y === a.goal.y;
    if (isGoal && other && !other.next && !other.path.length) {
      const spot = this.nearestFreeTo(a.goal, a);
      if (spot && spot.x === a.tile.x && spot.y === a.tile.y) { a.path = []; a.goal = null; a.status = "idle"; a.waited = 0; return; }
      if (spot) { a.goal = spot; if (this.plan(a, true)) return; }
    }
    if (this.isStandoff(a, other) && this.shouldYield(a, other)) {
      if (this.sidestep(a, other)) return;
    }
    if (a.waited % REPLAN_AFTER === 0 && !this.plan(a, true)) {
      // Reroute failed. If someone is standing on the destination, settle for the nearest free tile.
      const gh = a.goal && this.claimant(a.goal);
      if (gh !== undefined && gh !== a.id) {
        const spot = this.nearestFreeTo(a.goal, a);
        if (spot && spot.x === a.tile.x && spot.y === a.tile.y) { a.path = []; a.goal = null; a.status = "idle"; a.waited = 0; return; }
        if (spot) { const old = a.goal; a.goal = spot; if (!this.plan(a, true)) a.goal = old; }
      }
    }
    if (a.waited >= GIVE_UP_AFTER) { a.path = []; a.goal = null; a.status = "blocked"; a.waited = 0; }
  }

  /** Closest free standing tile to `t` (BFS ring order), counting `self`'s own tile as free. */
  nearestFreeTo(t, self, maxR = 3) {
    let best = null, bestD = Infinity;
    for (let dy = -maxR; dy <= maxR; dy++)
      for (let dx = -maxR; dx <= maxR; dx++) {
        const p = { x: t.x + dx, y: t.y + dy };
        const d = Math.abs(dx) + Math.abs(dy);
        if (d === 0 || d > maxR || d > bestD) continue;
        const holder = this.claimant(p);
        if (!this.world.isWalkable(p.x, p.y) || this.world.isNoStop(p.x, p.y) || this.world.cost(p.x, p.y) >= 5) continue;
        if (holder !== undefined && holder !== self.id) continue;
        const mine = holder === self.id ? -0.5 : 0; // prefer staying put on ties
        if (d + mine < bestD) { best = p; bestD = d + mine; }
      }
    return best;
  }

  /** b wants (within its next two steps) the tile a is standing on — i.e. they block each other. */
  isStandoff(a, b) {
    if (!b) return false;
    const wants = [b.next, ...b.path].filter(Boolean).slice(0, 2);
    return wants.some((t) => t.x === a.tile.x && t.y === a.tile.y);
  }

  /** The one who can step aside does; if both can, the lower-priority (later name) yields. */
  shouldYield(a, b) {
    const aCan = this.sidestepTiles(a, b).length > 0;
    const bCan = this.sidestepTiles(b, a).length > 0;
    if (aCan !== bCan) return aCan;
    return a.id.localeCompare(b.id) > 0;
  }

  sidestepTiles(a, b) {
    const lane = new Set([b.tile, b.next, ...b.path.slice(0, 8)].filter(Boolean).map((t) => key(t.x, t.y)));
    return DIRS.map(([dx, dy]) => ({ x: a.tile.x + dx, y: a.tile.y + dy })).filter(
      (t) => this.world.isWalkable(t.x, t.y) && !this.world.isNoStop(t.x, t.y) &&
        this.claimant(t) === undefined && !lane.has(key(t.x, t.y)),
    );
  }

  sidestep(a, b) {
    const [t] = this.sidestepTiles(a, b);
    if (!t) return false;
    a.path = [t]; // step aside first, then replan from there
    const goal = a.goal;
    this.tryClaimNextRaw(a);
    a.afterSidestep = goal;
    return true;
  }

  tryClaimNextRaw(a) {
    const step = a.path.shift();
    a.facing = facingToward(a.tile, step);
    a.next = step; a.progress = 0; a.waited = 0; a.status = "yielding";
    this.claim(a, step);
  }

  checkInvariants() {
    const seen = new Map();
    for (const a of this.agents) {
      if (a.inside) continue;
      for (const t of [a.tile, a.next].filter(Boolean)) {
        const k = key(t.x, t.y);
        if (seen.has(k) && seen.get(k) !== a.id) throw new Error(`overlap at ${t.x},${t.y}: ${a.id} & ${seen.get(k)}`);
        seen.set(k, a.id);
        if (!this.world.isWalkable(t.x, t.y)) throw new Error(`${a.id} on unwalkable ${t.x},${t.y}`);
      }
      if (a.next && Math.abs(a.next.x - a.tile.x) + Math.abs(a.next.y - a.tile.y) !== 1)
        throw new Error(`${a.id} claimed non-adjacent tile`);
    }
  }
}

export function facingToward(from, to) {
  if (to.x > from.x) return "right";
  if (to.x < from.x) return "left";
  if (to.y > from.y) return "down";
  return "up";
}

/** Face another tile along its dominant axis (for chats and '!' reactions). */
export function faceToward(from, to) {
  const dx = to.x - from.x, dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? "right" : "left";
  return dy > 0 ? "down" : "up";
}
