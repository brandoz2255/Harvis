// Canvas 2D renderer. Everything is drawn in code (no third-party art), 16 px tiles.
// Layers (Stardew map idea): Back (ground, cached once) -> fountain water -> characters (y-sorted) ->
// Front (tree canopies, awnings, lamp heads) -> night lights -> screen-space UI (bubbles, emotes).
// Redraw only when something changed (research: 64% CPU continuous vs ~0.1% on change).
// The town's tiles and props live in town-art.js; this file draws people, weather and the UI.
import { TILE, PAL, hash, px, drawGround, drawProp, drawFront, drawFountain, fountainBoxes, fountainFx, drawLights, glowSprite } from "./town-art.js";
import { drawObject } from "./ambient.js";

export { TILE };

// Agent colours come from each agent's own config (Harvis session); these helpers derive shades.
function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const ch = (v) => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f)));
  return "#" + [n >> 16, (n >> 8) & 255, n & 255].map((v) => ch(v).toString(16).padStart(2, "0")).join("");
}
const HAIRS = ["#5a3a1a", "#3b2a22", "#e8e0ff", "#ff3d8b", "#1d1d1d", "#c98a3b", "#7a4bd1", "#d9d0c0"];
function hashStr(str) { let h = 2166136261; for (const c of str) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; }
const OUTFIT_TINT = {
  raincoat: { main: "#f2d03b", dark: "#c9a823" },
  pajamas: { main: "#9fc3f0", dark: "#7699c8", stripe: "#e8f1ff" },
  yukata: { main: "#33407a", dark: "#232c57", stripe: "#e3e7ff" },
  default: { main: "#9a9a9a", dark: "#6e6e6e" },
};

// ---------------------------------------------------------------- characters
function colorsFor(a) {
  const main = a.color ?? "#cccccc";
  const base = { main, dark: shade(main, -0.3), hair: HAIRS[hashStr(a.id) % HAIRS.length] };
  const o = a.outfit?.id;
  const tint = o && o !== "casual" ? OUTFIT_TINT[o] : null;
  return { ...base, ...(tint ?? {}) };
}

function drawHuman(g, a, t) {
  const c = colorsFor(a);
  const X = Math.round(a.pos.x * TILE), Y = Math.round(a.pos.y * TILE);
  const moving = !!a.next;
  const bob = moving ? (Math.floor(t / 8) % 2) : 0;
  px(g, X + 3, Y + 13, 10, 3, "#00000040"); // shadow
  if (a.sleeping) {
    // in bed: just the head on the pillow, blanket covers the rest
    px(g, X + 5, Y + 2, 6, 5, "#f2c9a0"); px(g, X + 5, Y + 1, 6, 2, c.hair);
    px(g, X + 2, Y + 6, 12, 8, c.main); px(g, X + 2, Y + 6, 12, 1, c.stripe ?? "#ffffff66");
    return;
  }
  const y0 = Y - 6 - bob;
  // legs
  const step = moving ? (Math.floor(t / 8) % 2 ? 1 : -1) : 0;
  px(g, X + 5, y0 + 15, 2, 4 + step, PAL.outline);
  px(g, X + 9, y0 + 15, 2, 4 - step, PAL.outline);
  // body
  px(g, X + 3, y0 + 8, 10, 8, PAL.outline);
  px(g, X + 4, y0 + 9, 8, 6, c.main);
  px(g, X + 4, y0 + 13, 8, 2, c.dark);
  if (c.stripe) { px(g, X + 4, y0 + 10, 8, 1, c.stripe); px(g, X + 4, y0 + 12, 8, 1, c.stripe); }
  // head
  px(g, X + 3, y0, 10, 9, PAL.outline);
  px(g, X + 4, y0 + 1, 8, 7, "#f2c9a0");
  px(g, X + 4, y0, 8, 3, c.hair);
  if (a.facing === "down") { px(g, X + 5, y0 + 4, 1, 2, PAL.outline); px(g, X + 10, y0 + 4, 1, 2, PAL.outline); }
  else if (a.facing === "left") { px(g, X + 5, y0 + 4, 1, 2, PAL.outline); px(g, X + 9, y0, 3, 6, c.hair); }
  else if (a.facing === "right") { px(g, X + 10, y0 + 4, 1, 2, PAL.outline); px(g, X + 4, y0, 3, 6, c.hair); }
  else px(g, X + 4, y0, 8, 7, c.hair); // back of head
  if (a.outfit?.id === "raincoat") px(g, X + 3, y0 - 1, 10, 3, c.main); // hood
  if (a.outfit?.id === "pajamas") { px(g, X + 9, y0 - 3, 3, 3, c.main); px(g, X + 11, y0 - 4, 2, 2, "#ffffff"); } // nightcap
}

function drawPet(g, a, t) {
  const X = Math.round(a.pos.x * TILE), Y = Math.round(a.pos.y * TILE);
  const bob = a.next ? Math.floor(t / 6) % 2 : 0;
  px(g, X + 3, Y + 12, 10, 3, "#00000040");
  const fur = "#f08a3c", belly = "#fff3e0";
  if (a.sleeping) {
    px(g, X + 3, Y + 7, 10, 6, PAL.outline); px(g, X + 4, Y + 8, 8, 4, fur);
    px(g, X + 10, Y + 9, 3, 3, fur); px(g, X + 2, Y + 10, 3, 2, belly); // curled tail
    return;
  }
  const y0 = Y + 2 - bob;
  const flip = a.facing === "left";
  const hx = flip ? X + 2 : X + 9;
  px(g, X + 3, y0 + 5, 10, 6, PAL.outline); px(g, X + 4, y0 + 6, 8, 4, fur); px(g, X + 5, y0 + 8, 6, 2, belly);
  px(g, hx - 1, y0, 7, 7, PAL.outline); px(g, hx, y0 + 1, 5, 5, fur);
  px(g, hx, y0 - 2, 2, 2, fur); px(g, hx + 3, y0 - 2, 2, 2, fur); // ears
  if (a.facing !== "up") { px(g, hx + 1, y0 + 3, 1, 1, PAL.outline); px(g, hx + 3, y0 + 3, 1, 1, PAL.outline); }
  const tx = flip ? X + 12 : X + 1;
  px(g, tx, y0 + 3 + (Math.floor(t / 20) % 2), 2, 4, fur); // tail flick
  px(g, X + 5, y0 + 11, 2, 2, PAL.outline); px(g, X + 9, y0 + 11, 2, 2, PAL.outline);
}

// ---------------------------------------------------------------- UI overlay (screen space)
const EMOTE_GLYPH = { "!": "!", "?": "?", heart: "♥", z: "z", music: "♪", sweat: "💧", spark: "✦" };

function drawBubble(ui, a, zoom, text) {
  const cx = (a.pos.x * TILE + 8) * zoom, top = (a.pos.y * TILE - 10) * zoom;
  ui.font = `${Math.max(11, Math.round(5.5 * zoom))}px "Pixelify Sans", "Silkscreen", ui-monospace, monospace`;
  const w = Math.ceil(ui.measureText(text).width) + 12, h = Math.round(9 * zoom);
  const x = Math.round(cx - w / 2), y = Math.round(top - h - 6);
  ui.fillStyle = "#2a1e1a"; ui.fillRect(x - 2, y - 2, w + 4, h + 4);
  ui.fillStyle = "#fffaf0"; ui.fillRect(x, y, w, h);
  ui.fillStyle = "#2a1e1a"; ui.fillRect(cx - 3, y + h + 2, 6, 3); ui.fillRect(cx - 1, y + h + 5, 2, 2);
  ui.fillStyle = "#fffaf0"; ui.fillRect(cx - 2, y + h, 4, 2);
  ui.fillStyle = "#2a1e1a"; ui.textBaseline = "middle"; ui.fillText(text, x + 6, y + h / 2 + 1);
}

function drawEmote(ui, a, zoom) {
  const e = a.emote; if (!e) return;
  const alpha = e.phase === "in" ? (e.frame + 1) / 4 : e.phase === "out" ? 1 - (e.frame + 1) / 4 : 1;
  const lift = e.phase === "hold" ? (e.frame % 2) : 0;
  const cx = (a.pos.x * TILE + 8) * zoom, y = (a.pos.y * TILE - 16 - lift) * zoom;
  ui.globalAlpha = Math.max(0, alpha);
  const s = Math.round(8 * zoom);
  ui.fillStyle = "#2a1e1a"; ui.fillRect(cx - s / 2 - 2, y - s - 2, s + 4, s + 4);
  ui.fillStyle = e.kind === "!" ? "#ffe066" : "#fffaf0"; ui.fillRect(cx - s / 2, y - s, s, s);
  ui.fillStyle = e.kind === "heart" ? "#e8456b" : "#2a1e1a";
  ui.font = `bold ${Math.round(6.5 * zoom)}px ui-monospace, monospace`;
  ui.textAlign = "center"; ui.textBaseline = "middle";
  ui.fillText(EMOTE_GLYPH[e.kind] ?? e.kind, cx, y - s / 2 + 1);
  ui.textAlign = "start"; ui.globalAlpha = 1;
}

function drawZzz(ui, a, zoom, t) {
  const cx = (a.pos.x * TILE + 12) * zoom, y = (a.pos.y * TILE) * zoom;
  ui.fillStyle = "#e8f1ff"; ui.font = `bold ${Math.round(5 * zoom)}px ui-monospace, monospace`;
  const k = Math.floor(t / 30) % 3;
  for (let i = 0; i <= k; i++) ui.fillText("z", cx + i * 3 * zoom, y - i * 4 * zoom);
}

// ---------------------------------------------------------------- lighting
function skyTint(hourFloat) {
  // returns [r,g,b,a] overlay for time of day
  if (hourFloat >= 7 && hourFloat < 17.5) return null;
  if (hourFloat >= 17.5 && hourFloat < 19.5) return [255, 140, 60, ((hourFloat - 17.5) / 2) * 0.22];
  if (hourFloat >= 19.5 && hourFloat < 21) return [40, 40, 110, 0.22 + ((hourFloat - 19.5) / 1.5) * 0.25];
  if (hourFloat >= 21 || hourFloat < 5) return [20, 24, 80, 0.5];
  if (hourFloat >= 5 && hourFloat < 7) return [255, 170, 120, 0.3 - ((hourFloat - 5) / 2) * 0.3];
  return null;
}

// ---------------------------------------------------------------- renderer
export class Renderer {
  constructor(canvas, sim, { zoom = 2 } = {}) {
    this.canvas = canvas;
    this.sim = sim;
    this.world = sim.world;
    this.setZoom(zoom);
    this.back = document.createElement("canvas");
    this.back.width = this.world.w * TILE; this.back.height = this.world.h * TILE;
    this.front = document.createElement("canvas");
    this.front.width = this.back.width; this.front.height = this.back.height;
    this.scene = document.createElement("canvas");
    this.scene.width = this.back.width; this.scene.height = this.back.height;
    this.lights = document.createElement("canvas"); // lit windows and lamp halos, drawn at night
    this.lights.width = this.back.width; this.lights.height = this.back.height;
    this.fountains = fountainBoxes(this.world);
    this.buildStatic();
    this.lastSig = "";
    this.draws = 0;
    this.selected = null;
    this.lowFx = false; // set by the host (island:lowfx) while a run is busy: fewer rain drops
  }

  setZoom(z) {
    this.zoom = z;
    this.canvas.width = this.world.w * TILE * z;
    this.canvas.height = this.world.h * TILE * z;
    this.lastSig = "";
  }

  buildStatic() {
    const g = this.back.getContext("2d");
    const bedOwner = {};
    for (const a of this.sim.agents) if (a.bed && !a.pet) bedOwner[a.bed.x + "," + a.bed.y] = a.color;
    for (let y = 0; y < this.world.h; y++) for (let x = 0; x < this.world.w; x++)
      drawGround(g, this.world.charAt(x, y), x, y, this.world);
    for (let y = 0; y < this.world.h; y++) for (let x = 0; x < this.world.w; x++)
      drawProp(g, this.world.charAt(x, y), x, y, this.world, bedOwner[x + "," + y]);
    for (const b of this.fountains) drawFountain(g, b);
    drawFront(this.front.getContext("2d"), this.world);
    drawLights(this.lights.getContext("2d"), this.world, glowSprite());
  }

  /** Cheap signature of everything visible; if unchanged we skip the frame. */
  signature() {
    const s = this.sim;
    let sig = `${s.minutes}|${this.selected}|${s.weather}|`;
    if (this.fountains.length && !this.lowFx) sig += `f${Math.floor(s.ticks / 20) % 4},`; // water animates ~3 fps
    if (s.world.objects?.size) sig += `o${s.world.objects.size},`;
    for (const a of s.agents) {
      sig += `${a.pos.x.toFixed(3)},${a.pos.y.toFixed(3)},${a.facing},${a.outfit?.id},${a.sleeping},${a.bubble?.text ?? ""},`;
      if (a.emote) sig += `${a.emote.phase}${a.emote.frame},`;
      if (a.next) sig += `w${Math.floor(s.ticks / 8) % 2},`;
      if (a.sleeping) sig += `z${Math.floor(s.ticks / 30) % 3},`;
      if (a.pet && !a.sleeping) sig += `t${Math.floor(s.ticks / 20) % 2},`;
    }
    return sig;
  }

  draw(force = false) {
    const sig = this.signature();
    if (!force && sig === this.lastSig) return false;
    this.lastSig = sig;
    this.draws++;
    const t = this.sim.ticks, z = this.zoom;
    const g = this.scene.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.drawImage(this.back, 0, 0);
    if (!this.lowFx) for (const b of this.fountains) fountainFx(g, b, Math.floor(t / 20) % 4);
    if (this.world.objects?.size) for (const o of this.world.objects.values()) drawObject(g, o, this.sim);
    // selection ring
    const sel = this.selected && this.sim.agent(this.selected);
    if (sel) {
      g.strokeStyle = "#fff8"; g.lineWidth = 1;
      g.strokeRect(Math.round(sel.pos.x * TILE) + 1.5, Math.round(sel.pos.y * TILE) + 1.5, TILE - 3, TILE - 3);
      if (sel.goal) {
        g.strokeStyle = "#ffe06699";
        g.strokeRect(sel.goal.x * TILE + 3.5, sel.goal.y * TILE + 3.5, TILE - 7, TILE - 7);
      }
    }
    const order = [...this.sim.agents].sort((a, b) => a.pos.y - b.pos.y);
    for (const a of order) (a.pet ? drawPet : drawHuman)(g, a, t);
    g.drawImage(this.front, 0, 0);
    // weather
    if (this.sim.weather === "rain") {
      g.fillStyle = "#1c2a4a30"; g.fillRect(0, 0, this.scene.width, this.scene.height);
      g.fillStyle = "#cfe3ff88";
      for (let i = 0, drops = this.lowFx ? 60 : 140; i < drops; i++) {
        const rx = Math.floor(hash(i, 1) * this.scene.width), ry = Math.floor((hash(i, 2) * this.scene.height + t * 4) % this.scene.height);
        g.fillRect(rx, ry, 1, 4);
      }
    }
    const tint = skyTint((this.sim.minutes % 1440) / 60);
    if (tint) {
      g.fillStyle = `rgba(${tint[0]},${tint[1]},${tint[2]},${tint[3]})`;
      g.fillRect(0, 0, this.scene.width, this.scene.height);
      if (tint[3] > 0.12) { // lit windows, warm rooms and lamp halos fade in with the dark
        g.globalAlpha = Math.min(1, (tint[3] - 0.12) / 0.3);
        g.drawImage(this.lights, 0, 0);
        g.globalAlpha = 1;
      }
    }
    // upscale to the visible canvas, pixel-perfect
    const out = this.canvas.getContext("2d");
    out.imageSmoothingEnabled = false;
    out.drawImage(this.scene, 0, 0, this.canvas.width, this.canvas.height);
    // screen-space UI (crisp text at any zoom)
    for (const a of order) {
      if (a.sleeping) drawZzz(out, a, z, t);
      if (a.bubble) drawBubble(out, a, z, a.bubble.text);
      drawEmote(out, a, z);
      if (this.selected === a.id || a.chat) {
        out.font = `${Math.max(10, Math.round(4.5 * z))}px ui-monospace, monospace`;
        out.fillStyle = "#000a"; const label = a.name ?? a.id;
        const w = out.measureText(label).width + 6;
        const lx = Math.round((a.pos.x * TILE + 8) * z - w / 2), ly = Math.round((a.pos.y * TILE + 17) * z);
        out.fillRect(lx, ly, w, 5 * z); out.fillStyle = "#fff"; out.textBaseline = "top"; out.fillText(label, lx + 3, ly + 1);
      }
    }
    return true;
  }

  /** Canvas pixel -> tile. */
  tileAt(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const sx = (clientX - r.left) * (this.canvas.width / r.width), sy = (clientY - r.top) * (this.canvas.height / r.height);
    return { x: Math.floor(sx / (TILE * this.zoom)), y: Math.floor(sy / (TILE * this.zoom)) };
  }

  agentAt(tile) {
    return this.sim.agents.find((a) => Math.round(a.pos.x) === tile.x && Math.round(a.pos.y) === tile.y);
  }
}
