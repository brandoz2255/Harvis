// Tile-art renderer + HUD, drawn with art from the user's OWN game files (bring your own:
// imported on their machine by scripts/island/import-stardew.mjs, never shipped or served by
// Harvis). Generic: the asset source, map preset and session agents are all passed in.
//
// Sheet layouts (checked against the real files):
//   villager  Characters/<Name>.png  16x32 frames, rows: 0 down, 1 right, 2 up, 3 left, 4 frames each
//   cat       Animals/cat.png         32x32 frames, rows 0 down, 1 right, 2 up, 3 right (flip = left); row 7 = asleep
//   emotes    TileSheets/emotes.png   16x16, 4 frames per row; row 0 = bubble pop-in
//   portraits Portraits/<Name>.png    64x64, 2 per row (0 neutral, 1 happy)
//   font      LooseSprites/font_bold  8x16 grid from ' ' (SpriteText)
//   UI        LooseSprites/Cursors (speech-bubble scroll only; the HUD is Harvis's own, see hud.js)
import { loadStardewMap, drawLayers, BELOW, ABOVE } from "./stardew-map.js";
import { Ambient, drawObject } from "../ambient.js";
import {
  DARK, COMPACT_W, BUTTONS, GLITCH_MS, SANS_FONT, hudTheme, rgba, formatTime, formatDate, dayFraction, skyIcon,
  agentStatus, toneColor, drawIcon, iconSize, notched, panel, text, fit, wrapText, pixelText, pixelWidth, drawGlitched,
} from "./hud.js";

export const EMOTE_ROW = { "?": 2, angry: 3, "!": 4, heart: 5, z: 6, sweat: 7, happy: 8, x: 9, "…": 10, music: 14 };
const UI = { scrollL: [325, 318, 12, 18], scrollM: [337, 318, 1, 18], scrollR: [338, 318, 12, 18] };

// ---------------------------------------------------------------- asset pack
export async function loadStardewPack(source) {
  const [cursors, menuTiles, emotes, font] = await Promise.all([
    source.image("LooseSprites/Cursors.png"), source.image("Maps/MenuTiles.png"),
    source.image("TileSheets/emotes.png"), source.image("LooseSprites/font_bold.png"),
  ]);
  const cache = new Map();
  const get = (key) => {
    if (!cache.has(key)) cache.set(key, source.image(`${key}.png`).catch(() => null));
    return cache.get(key);
  };
  return { source, cursors, menuTiles, emotes, font: buildFont(font), image: get };
}

/** Measure each glyph's real width from the font sheet (auto-kerning). */
function buildFont(img) {
  const c = document.createElement("canvas");
  c.width = img.width; c.height = img.height;
  const g = c.getContext("2d"); g.drawImage(img, 0, 0);
  const data = g.getImageData(0, 0, img.width, img.height).data;
  const cols = img.width / 8, rows = img.height / 16, widths = [];
  for (let i = 0; i < cols * rows; i++) {
    const sx = (i % cols) * 8, sy = Math.floor(i / cols) * 16;
    let right = -1;
    for (let x = 0; x < 8; x++) for (let y = 0; y < 16; y++) if (data[((sy + y) * img.width + sx + x) * 4 + 3] > 40) right = Math.max(right, x);
    widths.push(right < 0 ? 4 : right + 2);
  }
  return { img, cols, widths };
}

export function textWidth(font, text, s) {
  let w = 0;
  for (const ch of text) { const i = ch.charCodeAt(0) - 32; w += (font.widths[i] ?? 6) * s; }
  return w;
}

export function drawText(g, font, text, x, y, s = 2, alpha = 1) {
  g.save(); g.globalAlpha = alpha;
  let cx = x;
  for (const ch of text) {
    const i = ch.charCodeAt(0) - 32;
    if (i < 0 || i >= font.widths.length) { cx += 6 * s; continue; }
    g.drawImage(font.img, (i % font.cols) * 8, Math.floor(i / font.cols) * 16, 8, 16, Math.round(cx), Math.round(y), 8 * s, 16 * s);
    cx += font.widths[i] * s;
  }
  g.restore();
  return cx - x;
}

function wrap(font, text, s, maxW) {
  const words = String(text).split(/\s+/), lines = [];
  let line = "";
  for (const w of words) {
    const t = line ? line + " " + w : w;
    if (textWidth(font, t, s) > maxW && line) { lines.push(line); line = w; } else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

/** Stardew's drawTextureBox: 9-slice with corners = 1/3 of the source. */
export function drawBox(g, img, [sx, sy, sw, sh], x, y, w, h, scale = 1) {
  const c = Math.floor(sw / 3), cs = c * scale, m = sw - 2 * c;
  x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h);
  g.drawImage(img, sx + c, sy + c, m, m, x + cs, y + cs, w - 2 * cs, h - 2 * cs);           // fill
  g.drawImage(img, sx + c, sy, m, c, x + cs, y, w - 2 * cs, cs);                             // top
  g.drawImage(img, sx + c, sy + sh - c, m, c, x + cs, y + h - cs, w - 2 * cs, cs);           // bottom
  g.drawImage(img, sx, sy + c, c, m, x, y + cs, cs, h - 2 * cs);                             // left
  g.drawImage(img, sx + sw - c, sy + c, c, m, x + w - cs, y + cs, cs, h - 2 * cs);           // right
  g.drawImage(img, sx, sy, c, c, x, y, cs, cs);
  g.drawImage(img, sx + sw - c, sy, c, c, x + w - cs, y, cs, cs);
  g.drawImage(img, sx, sy + sh - c, c, c, x, y + h - cs, cs, cs);
  g.drawImage(img, sx + sw - c, sy + sh - c, c, c, x + w - cs, y + h - cs, cs, cs);
}

function cut(g, img, [sx, sy, sw, sh], x, y, s = 1) {
  g.drawImage(img, sx, sy, sw, sh, Math.round(x), Math.round(y), sw * s, sh * s);
}

// ---------------------------------------------------------------- renderer
const DIR_ROW = { down: 0, right: 1, up: 2, left: 3 };

export class StardewRenderer {
  constructor(canvas, sim, pack, mapData, { zoom = 3, ui = 3, view = null } = {}) {
    Object.assign(this, { canvas, sim, pack, mapData, zoom, ui });
    const L = mapData.map.layers[0];
    this.mapW = L.size.w * 16; this.mapH = L.size.h * 16;
    this.view = view ? { x: view.x * 16, y: view.y * 16, w: view.w * 16, h: view.h * 16 } : { x: 0, y: 0, w: this.mapW, h: this.mapH };
    this.below = document.createElement("canvas"); this.above = document.createElement("canvas");
    for (const c of [this.below, this.above]) { c.width = this.mapW; c.height = this.mapH; }
    drawLayers(this.below.getContext("2d"), mapData, BELOW);
    drawLayers(this.above.getContext("2d"), mapData, ABOVE);
    this.cam = { x: this.view.x, y: this.view.y };
    this.selected = null;
    this.manualCam = false;
    this.hits = [];
    this.lastSig = "";
    this.draws = 0;
    this.sprites = new Map(); // agent id -> {sheet, portrait}
    this.ambient = new Ambient(sim.world, this.view);
    this.lowFx = false; // set by the perf governor: fewer rain drops, no critters
    this.log = []; // recent lines for the dialogue box
    this.theme = DARK; // the host's look, once it sends one (setTheme)
    this.glitchAt = -Infinity; this.glitchP = -1; this.glitchBuf = null;
    this.reducedMotion = !!globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    sim.on("bubble", (e) => { this.log.push({ id: e.id, text: e.text, t: sim.ticks }); if (this.log.length > 30) this.log.shift(); });
  }

  /** Resolve sprite + portrait images. Default: stable-random pick from the villager pool
   *  (hash of the agent id), so nothing is hardcoded; session can still set a.sprite. */
  spritesFor(a) {
    if (this.sprites.has(a.id)) return this.sprites.get(a.id);
    const POOL = ["Abigail", "Alex", "Elliott", "Emily", "Haley", "Harvey", "Leah", "Maru", "Penny", "Sam", "Sebastian", "Shane"];
    let h = 0; for (const ch of String(a.id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const key = a.sprite ?? (a.pet ? "Animals/cat" : `Characters/${POOL[h % POOL.length]}`);
    const entry = { key, sheet: null, portrait: null, pet: key.startsWith("Animals/") };
    this.sprites.set(a.id, entry);
    this.pack.image(key).then((img) => { entry.sheet = img; this.lastSig = ""; });
    if (!entry.pet) this.pack.image(key.replace("Characters/", "Portraits/")).then((img) => { entry.portrait = img; this.lastSig = ""; });
    return entry;
  }

  /** A theme from hud.js's hudTheme(), or a raw island:theme message to resolve. */
  setTheme(theme) {
    this.theme = typeof theme?.accent === "string" && typeof theme?.panel === "string" ? theme : hudTheme(theme);
    this.lastSig = "";
  }

  /** The house RGB glitch on the clock, when the time or weather is changed by hand. */
  flashHud(now = performance.now()) {
    if (this.lowFx || this.reducedMotion) return;
    this.glitchAt = now; this.lastSig = "";
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = 1;
    this.canvas.width = Math.max(320, Math.floor(r.width * dpr));
    this.canvas.height = Math.max(240, Math.floor(r.height * dpr));
    this.lastSig = "";
  }

  get vw() { return this.canvas.width / this.zoom; }
  get vh() { return this.canvas.height / this.zoom; }

  updateCamera() {
    if (this.manualCam) return this.clampCam();
    const visible = this.sim.agents.filter((a) => !a.inside);
    const sel = this.selected && this.sim.agent(this.selected);
    let tx, ty;
    if (sel && !sel.inside) { tx = sel.pos.x * 16 + 8; ty = sel.pos.y * 16; }
    else if (visible.length) { tx = visible.reduce((s, a) => s + a.pos.x, 0) / visible.length * 16; ty = visible.reduce((s, a) => s + a.pos.y, 0) / visible.length * 16; }
    else { tx = this.view.x + this.view.w / 2; ty = this.view.y + this.view.h / 2; }
    const want = { x: tx - this.vw / 2, y: ty - this.vh / 2 };
    this.cam.x += (want.x - this.cam.x) * 0.12;
    this.cam.y += (want.y - this.cam.y) * 0.12;
    this.clampCam();
  }

  clampCam() {
    const v = this.view;
    this.cam.x = this.vw >= v.w ? v.x - (this.vw - v.w) / 2 : Math.max(v.x, Math.min(v.x + v.w - this.vw, this.cam.x));
    this.cam.y = this.vh >= v.h ? v.y - (this.vh - v.h) / 2 : Math.max(v.y, Math.min(v.y + v.h - this.vh, this.cam.y));
  }

  pan(dx, dy) { this.manualCam = true; this.cam.x -= dx / this.zoom; this.cam.y -= dy / this.zoom; this.clampCam(); this.lastSig = ""; }

  signature() {
    const s = this.sim;
    let sig = `${s.minutes}|${this.selected}|${s.weather}|${Math.round(this.cam.x)},${Math.round(this.cam.y)}|${this.canvas.width}x${this.canvas.height}|${this.speed}|`;
    const gp = (performance.now() - this.glitchAt) / GLITCH_MS;
    this.glitchP = gp >= 0 && gp < 1 ? gp : -1;
    if (this.glitchP >= 0) sig += `g${Math.floor(this.glitchP * 12)}|`;
    for (const a of s.agents) {
      sig += `${a.pos.x.toFixed(2)},${a.pos.y.toFixed(2)},${a.facing},${a.inside ? 1 : 0},${a.bubble?.text ?? ""},${a.activity?.label ?? ""},`;
      if (a.emote) sig += `${a.emote.phase}${a.emote.frame},`;
      if (a.next) sig += `w${Math.floor(s.ticks / 8) % 4},`;
      if (a.sleeping && !a.inside) sig += `z${Math.floor(s.ticks / 30) % 2},`;
    }
    if (s.weather === "rain") sig += `r${Math.floor(s.ticks / 3)}`;
    if (!this.lowFx) sig += this.ambient.sig();
    if (s.world.objects?.size) sig += `o${s.world.objects.size}${Math.floor(s.ticks / 8) % 2}`;
    return sig;
  }

  draw(force = false) {
    this.updateCamera();
    const sig = this.signature();
    if (!force && sig === this.lastSig) return false;
    this.lastSig = sig;
    this.draws++;
    const g = this.canvas.getContext("2d");
    g.imageSmoothingEnabled = false;
    const z = this.zoom, cx = Math.round(this.cam.x * z) / z, cy = Math.round(this.cam.y * z) / z;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#3a6ea5"; g.fillRect(0, 0, this.canvas.width, this.canvas.height);
    g.setTransform(z, 0, 0, z, -cx * z, -cy * z);
    g.drawImage(this.below, 0, 0);
    if (this.sim.world.objects) for (const o of this.sim.world.objects.values()) drawObject(g, o, this.sim);
    const order = this.sim.agents.filter((a) => !a.inside).sort((a, b) => a.pos.y - b.pos.y);
    for (const a of order) this.drawAgent(g, a);
    g.drawImage(this.above, 0, 0);
    for (const a of order) this.drawEmote(g, a);
    if (!this.lowFx) { this.ambient.tick(this.sim); this.ambient.draw(g, this.sim.ticks); }
    g.setTransform(1, 0, 0, 1, 0, 0);
    this.drawWeatherAndLight(g);
    // world-anchored text (bubbles) in screen space for crisp glyphs
    for (const a of order) if (a.bubble) this.drawBubble(g, a, cx, cy);
    this.hits = [];
    this.drawClock(g);
    this.drawResidents(g);
    this.drawDialogue(g);
    this.drawButtons(g);
    return true;
  }

  drawAgent(g, a) {
    const sp = this.spritesFor(a);
    const x = a.pos.x * 16, y = a.pos.y * 16;
    g.fillStyle = "rgba(0,0,0,0.25)"; g.beginPath(); g.ellipse(x + 8, y + 14, 6, 2.5, 0, 0, Math.PI * 2); g.fill();
    if (!sp.sheet) { g.fillStyle = a.color ?? "#ccc"; g.fillRect(x + 4, y - 8, 8, 20); return; }
    const walking = !!a.next, f = walking ? Math.floor(this.sim.ticks / 8) % 4 : 0;
    if (sp.pet) {
      if (a.sleeping) { g.drawImage(sp.sheet, (Math.floor(this.sim.ticks / 30) % 2) * 32, 7 * 32, 32, 32, x - 8, y - 16, 32, 32); return; }
      const row = a.facing === "left" ? 3 : DIR_ROW[a.facing];
      if (a.facing === "left") { g.save(); g.translate(x + 24, 0); g.scale(-1, 1); g.drawImage(sp.sheet, f * 32, 1 * 32, 32, 32, 0, y - 16, 32, 32); g.restore(); }
      else g.drawImage(sp.sheet, f * 32, row * 32, 32, 32, x - 8, y - 16, 32, 32);
      return;
    }
    g.drawImage(sp.sheet, f * 16, DIR_ROW[a.facing] * 32, 16, 32, Math.round(x), Math.round(y - 16), 16, 32);
    if (this.selected === a.id) { // selection arrow, in the HUD's accent
      g.fillStyle = this.theme.accent; const bob = Math.floor(this.sim.ticks / 15) % 2;
      g.fillRect(x + 6, y - 24 - bob, 4, 2); g.fillRect(x + 7, y - 22 - bob, 2, 2);
    }
  }

  drawEmote(g, a) {
    const e = a.emote; if (!e) return;
    const row = e.phase === "hold" ? (EMOTE_ROW[e.kind] ?? 4) : 0;
    const frame = e.phase === "out" ? 3 - e.frame : e.frame;
    const x = a.pos.x * 16, y = a.pos.y * 16 - 34;
    g.drawImage(this.pack.emotes, frame * 16, row * 16, 16, 16, Math.round(x), Math.round(y), 16, 16);
  }

  drawBubble(g, a, cx, cy) {
    const { font, cursors } = this.pack, s = 2, u = 2;
    const text = a.bubble.text;
    const w = Math.ceil(textWidth(font, text, s));
    const sx = (a.pos.x * 16 + 8 - cx) * this.zoom, sy = (a.pos.y * 16 - 38 - cy) * this.zoom;
    const left = Math.round(sx - w / 2), top = Math.round(sy - 18 * u);
    cut(g, cursors, UI.scrollL, left - 12 * u, top, u);
    g.drawImage(cursors, ...UI.scrollM, left, top, w, 18 * u);
    cut(g, cursors, UI.scrollR, left + w, top, u);
    drawText(g, font, text, left, top + 4 * u - 3, s);
  }

  drawWeatherAndLight(g) {
    const W = this.canvas.width, H = this.canvas.height, h = (this.sim.minutes % 1440) / 60;
    if (this.sim.weather === "rain") {
      g.fillStyle = "rgba(20,32,64,0.28)"; g.fillRect(0, 0, W, H);
      // slanted streaks, one path for the lot
      g.strokeStyle = "rgba(170,200,255,0.5)"; g.lineWidth = 2;
      g.beginPath();
      const drops = this.lowFx ? 60 : 200;
      for (let i = 0; i < drops; i++) {
        const x = (i * 97.3 + this.sim.ticks * 3) % (W + 40) - 20, y = (i * 53.7 + this.sim.ticks * 10) % (H + 30) - 30;
        g.moveTo(Math.round(x), Math.round(y)); g.lineTo(Math.round(x - 4), Math.round(y + 14));
      }
      g.stroke();
    }
    // dusk blue -> night navy -> dawn, blended so no hour jumps
    const NIGHT = [8, 12, 36], DUSK = [52, 46, 120], DAWN = [60, 70, 130];
    let a = 0, c = NIGHT;
    if (h >= 18 && h < 20) { const k = (h - 18) / 2; a = k * 0.5; c = DUSK.map((v, i) => v + (NIGHT[i] - v) * k); }
    else if (h >= 20 || h < 5) a = 0.5;
    else if (h >= 5 && h < 6.5) { const k = (h - 5) / 1.5; a = 0.5 * (1 - k); c = NIGHT.map((v, i) => v + (DAWN[i] - v) * k); }
    if (a > 0) { g.fillStyle = `rgba(${c.map(Math.round).join(",")},${a.toFixed(3)})`; g.fillRect(0, 0, W, H); }
  }

  get compact() { return this.canvas.width < COMPACT_W; }

  drawClock(g) {
    const t = this.theme, W = this.canvas.width, compact = this.compact;
    const cw = compact ? 148 : 236, ch = compact ? 44 : 76, x = W - cw - (compact ? 8 : 12), y = compact ? 8 : 12;
    this.clockRect = { x, y, w: cw, h: ch };
    const icon = skyIcon(this.sim.minutes, this.sim.weather), time = formatTime(this.sim.minutes), frac = dayFraction(this.sim.minutes);
    const iconColor = icon === "moon" ? t.fg : t.accent;
    const paint = (b) => {
      panel(b, t, 0, 0, cw, ch);
      if (compact) {
        const s = iconSize(icon, 2);
        drawIcon(b, icon, 10 + (22 - s.w) / 2, 9, 2, iconColor === t.accent && icon === "rain" ? t.fg : iconColor, t.accent);
        const tw = pixelText(b, time.clock, 40, 9, 2, t.fg);
        pixelText(b, time.half, 40 + tw + 6, 9, 2, t.muted);
        this.dayBar(b, 40, 31, cw - 52, frac, 2);
        return;
      }
      b.fillStyle = rgba(t.accent, 0.12); notched(b, 12, 12, 52, 52, 2); b.fill();
      b.strokeStyle = rgba(t.accent, 0.35); b.lineWidth = 1; notched(b, 12.5, 12.5, 51, 51, 2); b.stroke();
      const s = iconSize(icon, 4);
      drawIcon(b, icon, 12 + (52 - s.w) / 2, 12 + (52 - s.h) / 2, 4, icon === "rain" ? t.fg : iconColor, t.accent);
      const tw = pixelText(b, time.clock, 78, 14, 4, t.fg);
      pixelText(b, time.half, 78 + tw + 8, 28, 2, t.muted);
      pixelText(b, formatDate(), 78, 49, 2, t.muted);
      this.dayBar(b, 78, 68, cw - 92, frac, 2);
    };
    this.glitchBuf ??= typeof document !== "undefined" ? document.createElement("canvas") : null;
    drawGlitched(g, this.glitchBuf, x, y, cw + 4, ch + 4, this.glitchP, paint);
  }

  /** How much of the waking day is gone (6 am to 2 am), in place of the game's sundial. */
  dayBar(g, x, y, w, frac, h) {
    const t = this.theme, fill = Math.round(w * frac);
    g.fillStyle = t.line; g.fillRect(x, y, w, h);
    g.fillStyle = t.accent; g.fillRect(x, y, fill, h);
    g.fillRect(x + fill - 2, y - 2, 4, h + 4);
  }

  drawResidents(g) {
    if (this.compact) return this.drawResidentsCompact(g);
    const t = this.theme, rows = this.sim.agents, H = this.canvas.height;
    const x = 12, y = 12, w = 264, head = 38, rowH = 46;
    const room = Math.max(1, Math.floor((H - y - head - 18) / rowH));
    const shown = rows.slice(0, rows.length > room ? room - 1 : room), more = rows.length - shown.length;
    const h = head + shown.length * rowH + (more ? 26 : 0) + 6;
    panel(g, t, x, y, w, h);
    if ("letterSpacing" in g) g.letterSpacing = "1.5px";
    text(g, "AGENTS", x + 16, y + 24, { size: 11, weight: "700", color: t.muted });
    if ("letterSpacing" in g) g.letterSpacing = "0px";
    const count = String(rows.length), pw = pixelWidth(count, 2) + 14;
    g.fillStyle = rgba(t.accent, 0.16); notched(g, x + w - 14 - pw, y + 11, pw, 20, 2); g.fill();
    pixelText(g, count, x + w - 14 - pw + 7, y + 14, 2, t.accent);
    g.fillStyle = t.line; g.fillRect(x + 1, y + head - 1, w - 2, 1);
    shown.forEach((a, i) => {
      const ry = y + head + 4 + i * rowH, sp = this.spritesFor(a), st = agentStatus(a);
      if (this.selected === a.id) {
        g.fillStyle = rgba(t.accent, 0.14); notched(g, x + 6, ry, w - 12, rowH - 4, 2); g.fill();
        g.strokeStyle = t.accent; g.lineWidth = 1; notched(g, x + 6.5, ry + 0.5, w - 13, rowH - 5, 2); g.stroke();
      }
      this.drawAvatar(g, sp, x + 14, ry + 4, 34);
      text(g, fit(g, a.name, w - 80, 13, SANS_FONT, "600"), x + 58, ry + 18, { size: 13, weight: "600", color: t.fg });
      g.fillStyle = toneColor(t, st.tone); g.fillRect(x + 58, ry + 26, 6, 6);
      text(g, fit(g, st.label, w - 92, 12), x + 70, ry + 33, { size: 12, color: t.muted });
      this.hits.push({ x: x + 6, y: ry, w: w - 12, h: rowH - 4, kind: "agent", id: a.id });
    });
    if (more) text(g, `+${more} more`, x + 16, y + h - 14, { size: 12, color: t.muted });
  }

  /** Small screens (the corner widget): a column of avatar tiles with a status dot each. */
  drawResidentsCompact(g) {
    const t = this.theme, H = this.canvas.height, x = 8, size = 36, gap = 6;
    const room = Math.max(1, Math.floor((H - 16 + gap) / (size + gap)));
    this.sim.agents.slice(0, room).forEach((a, i) => {
      const ry = 8 + i * (size + gap), st = agentStatus(a);
      panel(g, t, x, ry, size, size);
      this.drawAvatar(g, this.spritesFor(a), x + 1, ry + 1, size - 2, false);
      if (this.selected === a.id) { g.strokeStyle = t.accent; g.lineWidth = 2; notched(g, x + 1, ry + 1, size - 2, size - 2, 2); g.stroke(); }
      g.fillStyle = t.panel; g.fillRect(x + size - 11, ry + size - 11, 10, 10);
      g.fillStyle = toneColor(t, st.tone); g.fillRect(x + size - 9, ry + size - 9, 6, 6);
      this.hits.push({ x, y: ry, w: size, h: size, kind: "agent", id: a.id });
    });
  }

  /** The head of the down-facing frame at 2x (a pet's whole frame), on a tile. */
  drawAvatar(g, sp, x, y, size, tile = true) {
    const t = this.theme;
    if (tile) {
      g.fillStyle = t.raised; notched(g, x, y, size, size, 2); g.fill();
      g.strokeStyle = t.line; g.lineWidth = 1; notched(g, x + 0.5, y + 0.5, size - 1, size - 1, 2); g.stroke();
    }
    if (!sp.sheet) return;
    const o = Math.round((size - 32) / 2);
    if (sp.pet) g.drawImage(sp.sheet, 0, 0, 32, 32, x + o, y + o, 32, 32);
    else g.drawImage(sp.sheet, 0, 0, 16, 16, x + o, y + o + 1, 32, 32);
  }

  drawDialogue(g) {
    const a = this.selected && this.sim.agent(this.selected);
    if (!a) return;
    const t = this.theme, sp = this.spritesFor(a), st = agentStatus(a);
    const W = this.canvas.width, H = this.canvas.height;
    const line = a.bubble?.text ?? a.lastSaid ?? (a.activity ? `Working on: ${a.activity.label}` : a.inside ? "Zzz..." : `Hi, I'm ${a.name}.`);
    if (this.compact) {
      const bx = 52, bw = W - bx - 8, bh = 54, by = H - bh - 8;
      panel(g, t, bx, by, bw, bh);
      this.nameChip(g, a.name, bx + 8, by + 8, 11, 18);
      text(g, fit(g, line, bw - 16, 12), bx + 8, by + 44, { size: 12, color: t.fg });
      this.hits.push({ x: bx, y: by, w: bw, h: bh, kind: "dialogue", id: a.id });
      return;
    }
    const hasP = !!sp.portrait, bw = Math.min(900, W - 24), bh = hasP ? 160 : 140, bx = Math.round((W - bw) / 2), by = H - bh - 12;
    panel(g, t, bx, by, bw, bh);
    let tx = bx + 20;
    if (hasP) {
      g.fillStyle = t.raised; notched(g, bx + 16, by + 16, 128, 128, 2); g.fill();
      const pIdx = a.bubble || a.emote?.kind === "music" ? 1 : 0;
      g.drawImage(sp.portrait, (pIdx % 2) * 64, Math.floor(pIdx / 2) * 64, 64, 64, bx + 16, by + 16, 128, 128);
      g.strokeStyle = t.line; g.lineWidth = 1; notched(g, bx + 16.5, by + 16.5, 127, 127, 2); g.stroke();
      tx = bx + 164;
    }
    const cw = this.nameChip(g, a.name, tx, by + 18, 13, 24);
    g.fillStyle = toneColor(t, st.tone); g.fillRect(tx + cw + 12, by + 27, 6, 6);
    text(g, fit(g, st.label, bx + bw - tx - cw - 40, 12), tx + cw + 24, by + 34, { size: 12, color: t.muted });
    wrapText(g, line, bx + bw - 20 - tx, 16).slice(0, 3)
      .forEach((l, i) => text(g, l, tx, by + 70 + i * 23, { size: 16, color: t.fg }));
    if (a.meta?.model) text(g, fit(g, `${a.meta.provider ?? ""} ${a.meta.model}`.trim(), bx + bw - 20 - tx, 12), tx, by + bh - 16, { size: 12, color: t.muted });
    this.hits.push({ x: bx, y: by, w: bw, h: bh, kind: "dialogue", id: a.id });
  }

  /** The speaker's name on an accent chip; returns its width. */
  nameChip(g, name, x, y, size, h) {
    const t = this.theme, label = fit(g, name, 220, size, SANS_FONT, "700");
    g.font = `700 ${size}px ${SANS_FONT}`;
    const w = Math.ceil(g.measureText(label).width) + 20;
    g.fillStyle = t.accent; notched(g, x, y, w, h, 2); g.fill();
    text(g, label, x + w / 2, y + h / 2 + 1, { size, weight: "700", color: t.accentFg, align: "center", base: "middle" });
    return w;
  }

  drawButtons(g) {
    if (this.compact || !this.clockRect) return;
    const t = this.theme, h = 30, y = this.clockRect.y + this.clockRect.h + 8;
    g.font = `600 12px ${SANS_FONT}`;
    const segW = (b) => {
      const iw = b.icon ? iconSize(b.icon, 2).w : 0;
      if (!b.text) return iw + 24;
      return Math.ceil(g.measureText(b.text).width) + (b.icon ? iw + 6 : 0) + 24;
    };
    const isOn = (b) => b.action === `speed:${this.speed}` || (b.action === "rain" && this.sim.weather === "rain");
    let x = this.clockRect.x + this.clockRect.w;
    for (const items of [BUTTONS.slice(3), BUTTONS.slice(0, 3)]) {
      const ws = items.map(segW), total = ws.reduce((s, w) => s + w, 0);
      x -= total;
      panel(g, t, x, y, total, h);
      let sx = x;
      items.forEach((b, i) => {
        const w = ws[i], on = isOn(b), color = on ? t.accentFg : t.fg;
        if (on) { g.fillStyle = t.accent; notched(g, sx + 3, y + 3, w - 6, h - 6, 2); g.fill(); }
        else if (i > 0 && !isOn(items[i - 1])) { g.fillStyle = t.line; g.fillRect(sx, y + 8, 1, h - 16); }
        let cx = sx + 12;
        if (b.icon) {
          const s = iconSize(b.icon, 2);
          drawIcon(g, b.icon, b.text ? cx : sx + (w - s.w) / 2, y + (h - s.h) / 2, 2, color);
          cx += s.w + 6;
        }
        if (b.text) text(g, b.text, b.icon ? cx : sx + w / 2, y + h / 2 + 1, { size: 12, weight: "600", color, align: b.icon ? "left" : "center", base: "middle" });
        this.hits.push({ x: sx, y, w, h, kind: "button", action: b.action, label: b.label ?? b.text });
        sx += w;
      });
      x -= 8;
    }
  }

  /** Screen point -> HUD hit, else world tile. */
  hitTest(px, py) {
    for (let i = this.hits.length - 1; i >= 0; i--) {
      const h = this.hits[i];
      if (px >= h.x && py >= h.y && px < h.x + h.w && py < h.y + h.h) return h;
    }
    const wx = px / this.zoom + this.cam.x, wy = py / this.zoom + this.cam.y;
    const tile = { x: Math.floor(wx / 16), y: Math.floor(wy / 16) };
    const agent = this.sim.agents.find((a) => !a.inside && Math.abs(a.pos.x * 16 + 8 - wx) < 9 && wy > a.pos.y * 16 - 18 && wy < a.pos.y * 16 + 16);
    return agent ? { kind: "agent", id: agent.id } : { kind: "tile", tile };
  }
}

export async function loadStardewScene(source, preset) {
  const [pack, mapData] = await Promise.all([loadStardewPack(source), loadStardewMap(source, preset.map)]);
  return { pack, mapData };
}
