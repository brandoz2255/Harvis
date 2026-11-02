// The HUD over the user's own game art, in Harvis's look rather than the game's: glass panels
// in the app's own colours (the host sends its theme; dark until it does), the Harvis blue,
// our own pixel digits and weather icons, a day bar instead of the sundial, and the house RGB
// glitch when the time or weather changes. Only the world (map, villagers, emotes, speech
// bubbles) comes from the user's game files.

export const SANS_FONT = '"Segoe UI", -apple-system, BlinkMacSystemFont, system-ui, sans-serif';

// Harvis skin, dark and light (themes/presets.ts nousTheme).
export const DARK = { mode: "dark", panel: "#0d1117", alpha: 0.86, raised: "#161b22", line: "#30363d", fg: "#e6edf3", muted: "#7d8590", accent: "#4a84fe", accentFg: "#161616", ok: "#3fb950" };
export const LIGHT = { mode: "light", panel: "#ffffff", alpha: 0.9, raised: "#f6f8fa", line: "#d0d7de", fg: "#1f2328", muted: "#656d76", accent: "#0053fd", accentFg: "#ffffff", ok: "#1a7f37" };

const HEX = /^#[0-9a-f]{6}$/i;

/** Host -> island {type:"island:theme", mode, colors}: only #rrggbb values get through. */
export function hudTheme(msg) {
  const base = msg?.mode === "light" ? LIGHT : DARK;
  const c = msg?.colors && typeof msg.colors === "object" ? msg.colors : {};
  const pick = (v, fallback) => (typeof v === "string" && HEX.test(v) ? v : fallback);
  return {
    ...base,
    panel: pick(c.background, base.panel), raised: pick(c.popover, base.raised), line: pick(c.border, base.line),
    fg: pick(c.foreground, base.fg), muted: pick(c.mutedForeground, base.muted),
    accent: pick(c.primary, base.accent), accentFg: pick(c.primaryForeground, base.accentFg),
  };
}

export function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

// ---------------------------------------------------------------- pure bits (tested)
const WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

/** {clock: "9:40", half: "PM"} for a game time in minutes since midnight. */
export function formatTime(minutes) {
  const m = ((minutes % 1440) + 1440) % 1440, hh = Math.floor(m / 60), mm = m % 60;
  return { clock: `${((hh + 11) % 12) + 1}:${String(mm).padStart(2, "0")}`, half: hh < 12 ? "AM" : "PM" };
}

export function formatDate(d = new Date()) { return `${WEEKDAYS[d.getDay()]} ${d.getDate()}`; }

/** Share of the waking day gone, 6:00 am -> 2:00 am, like the game's sundial. */
export function dayFraction(minutes) {
  const m = ((minutes - 360) % 1440 + 1440) % 1440;
  return Math.min(1, m / 1200);
}

export function skyIcon(minutes, weather) {
  if (weather === "rain" || weather === "storm") return "rain";
  const h = (((minutes % 1440) + 1440) % 1440) / 60;
  return h >= 19 || h < 5.5 ? "moon" : "sun";
}

export function agentStatus(a) {
  if (a.inside) return { label: "at home", tone: "off" };
  if (a.activity) return { label: a.activity.label, tone: "work" };
  if (a.chat) return { label: "chatting", tone: "chat" };
  if (a.next) return { label: "walking", tone: "move" };
  return { label: "idle", tone: "idle" };
}

export function toneColor(t, tone) {
  return tone === "work" ? t.accent : tone === "chat" ? t.ok : tone === "move" ? rgba(t.accent, 0.55) : tone === "off" ? t.line : t.muted;
}

/** Below this canvas width the HUD folds down to fit the small corner widget. */
export const COMPACT_W = 640;

export const BUTTONS = [
  { icon: "pause", action: "speed:0", label: "Pause" }, { text: "1×", action: "speed:1", label: "Normal speed" },
  { text: "4×", action: "speed:4", label: "Fast" }, { icon: "drop", text: "Rain", action: "rain" },
  { icon: "moonS", text: "Night", action: "time:21:50" }, { icon: "sunS", text: "Day", action: "time:08:00" },
];

// ---------------------------------------------------------------- pixel icons
// '#' = main colour, '+' = second colour, anything else = clear.
const ICONS = {
  sun: ["....#....", ".#.....#.", "...###...", "..#####..", "#.#####.#", "..#####..", "...###...", ".#.....#.", "....#...."],
  moon: ["...####..", "..###....", ".###.....", ".###.....", ".###.....", ".###.....", ".####....", "..#####..", "...####.."],
  rain: ["...###.....", "..#####.##.", ".##########", "###########", ".#########.", "...........", "..+..+..+..", ".+..+..+...", "..........."],
  drop: ["..#..", "..#..", ".###.", "#####", "#####", ".###."],
  sunS: ["...#...", ".#...#.", "..###..", "#.###.#", "..###..", ".#...#.", "...#..."],
  moonS: ["..###", ".##..", "##...", "##...", "##...", ".##..", "..###"],
  pause: ["##.##", "##.##", "##.##", "##.##", "##.##"],
};

export function drawIcon(g, name, x, y, px, main, second = main) {
  const rows = ICONS[name]; if (!rows) return;
  for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[r].length; c++) {
    const ch = rows[r][c]; if (ch !== "#" && ch !== "+") continue;
    g.fillStyle = ch === "#" ? main : second;
    g.fillRect(Math.round(x + c * px), Math.round(y + r * px), px, px);
  }
}

export const iconSize = (name, px) => ({ w: (ICONS[name]?.[0].length ?? 0) * px, h: (ICONS[name]?.length ?? 0) * px });

// ---------------------------------------------------------------- pixel type (ours, 5x7)
const GLYPHS = {
  0: [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."], 1: ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
  2: [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"], 3: ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
  4: ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."], 5: ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
  6: ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."], 7: ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
  8: [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."], 9: [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
  ":": [".", ".", "#", ".", "#", ".", "."], " ": ["..", "..", "..", "..", "..", "..", ".."],
  A: [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"], D: ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
  E: ["#####", "#....", "#....", "####.", "#....", "#....", "#####"], F: ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
  H: ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"], I: ["###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"],
  M: ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"], N: ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
  O: [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."], P: ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
  R: ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"], S: [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
  T: ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."], U: ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  W: ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
};

/** Width of `str` in our pixel type at `px` per pixel (1 px gap between glyphs). */
export function pixelWidth(str, px) {
  let w = 0;
  for (const ch of str) w += ((GLYPHS[ch] ?? GLYPHS[" "])[0].length + 1) * px;
  return Math.max(0, w - px);
}

/** Draws `str` with its top-left at x,y; returns the width. Covers digits, ':', space and the clock's letters. */
export function pixelText(g, str, x, y, px, color) {
  g.fillStyle = color;
  let cx = Math.round(x);
  for (const ch of str) {
    const rows = GLYPHS[ch] ?? GLYPHS[" "];
    for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[r].length; c++) {
      if (rows[r][c] === "#") g.fillRect(cx + c * px, Math.round(y) + r * px, px, px);
    }
    cx += (rows[0].length + 1) * px;
  }
  return pixelWidth(str, px);
}

// ---------------------------------------------------------------- shapes
/** A rect with 2px pixel-cut corners: reads as Harvis's rounded cards and as pixel art. */
export function notched(g, x, y, w, h, n = 2) {
  x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h);
  g.beginPath();
  g.moveTo(x + n, y); g.lineTo(x + w - n, y); g.lineTo(x + w, y + n); g.lineTo(x + w, y + h - n);
  g.lineTo(x + w - n, y + h); g.lineTo(x + n, y + h); g.lineTo(x, y + h - n); g.lineTo(x, y + n);
  g.closePath();
}

/** Glass panel: a hard drop shadow (no blur: this redraws every frame), fill, 1px border. */
export function panel(g, t, x, y, w, h) {
  g.fillStyle = "rgba(0,0,0,0.28)"; notched(g, x + 2, y + 3, w, h, 3); g.fill();
  g.fillStyle = rgba(t.panel, t.alpha); notched(g, x, y, w, h, 3); g.fill();
  g.strokeStyle = t.line; g.lineWidth = 1; notched(g, x + 0.5, y + 0.5, w - 1, h - 1, 3); g.stroke();
}

export function text(g, str, x, y, { size = 14, font = SANS_FONT, weight = "", color, align = "left", base = "alphabetic" } = {}) {
  g.font = `${weight ? weight + " " : ""}${size}px ${font}`;
  g.fillStyle = color; g.textAlign = align; g.textBaseline = base;
  g.fillText(str, Math.round(x), Math.round(y));
  return g.measureText(str).width;
}

export function fit(g, str, maxW, size, font = SANS_FONT, weight = "") {
  g.font = `${weight ? weight + " " : ""}${size}px ${font}`;
  if (g.measureText(str).width <= maxW) return str;
  let s = str;
  while (s.length > 1 && g.measureText(s + "…").width > maxW) s = s.slice(0, -1);
  return s + "…";
}

export function wrapText(g, str, maxW, size, font = SANS_FONT) {
  g.font = `${size}px ${font}`;
  const words = String(str).split(/\s+/), lines = [];
  let line = "";
  for (const w of words) {
    const t = line ? `${line} ${w}` : w;
    if (g.measureText(t).width > maxW && line) { lines.push(line); line = w; } else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

// ---------------------------------------------------------------- the house glitch
export const GLITCH_MS = 420;

/**
 * Draws `paint(ctx)` (a chip of w x h at the origin) to `g` at x,y. While a glitch is running
 * (0 <= p < 1) it splits into red and cyan copies and tears horizontal slices, like the
 * Harvis wordmark's `harvis-glitch-in`, then snaps clean.
 */
export function drawGlitched(g, buf, x, y, w, h, p, paint) {
  if (!(p >= 0 && p < 1) || !buf) { g.save(); g.translate(x, y); paint(g); g.restore(); return; }
  if (buf.width !== w || buf.height !== h) { buf.width = w; buf.height = h; }
  const b = buf.getContext("2d");
  b.clearRect(0, 0, w, h); paint(b);
  const k = Math.round((1 - p) * 6), frame = Math.floor(p * 10);
  g.save();
  g.globalAlpha = 0.55;
  tinted(g, buf, "#ff3d7f", x - k, y);
  tinted(g, buf, "#2ee6ff", x + k, y);
  g.globalAlpha = 1;
  const cuts = [0, 0.22, 0.48, 0.71, 1];
  for (let i = 0; i < cuts.length - 1; i++) {
    const sy = Math.round(cuts[i] * h), sh = Math.round(cuts[i + 1] * h) - sy;
    const dx = ((i + frame) % 3 - 1) * k;
    g.drawImage(buf, 0, sy, w, sh, x + dx, y + sy, w, sh);
  }
  g.restore();
}

let tintBuf = null;
function tinted(g, src, color, x, y) {
  tintBuf ??= typeof document !== "undefined" ? document.createElement("canvas") : null;
  if (!tintBuf) return;
  if (tintBuf.width !== src.width || tintBuf.height !== src.height) { tintBuf.width = src.width; tintBuf.height = src.height; }
  const t = tintBuf.getContext("2d");
  t.globalCompositeOperation = "copy"; t.drawImage(src, 0, 0);
  t.globalCompositeOperation = "source-in"; t.fillStyle = color; t.fillRect(0, 0, src.width, src.height);
  t.globalCompositeOperation = "source-over";
  g.drawImage(tintBuf, x, y);
}
