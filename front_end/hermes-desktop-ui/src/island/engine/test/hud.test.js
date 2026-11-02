// The Harvis-styled HUD over the user's own game art: theme intake, the pure helpers, and where
// the clickable regions land in the normal and the small (corner widget) layouts.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DARK, LIGHT, BUTTONS, hudTheme, formatTime, formatDate, dayFraction, skyIcon, agentStatus, pixelWidth,
} from "../stardew/hud.js";
import { StardewRenderer } from "../stardew/stardew-ui.js";

// A 2D context where every call is a no-op and text is 7 px per character.
const g = new Proxy({}, {
  get: (_t, k) => (k === "measureText" ? (s) => ({ width: String(s).length * 7 }) : () => {}),
  set: () => true,
});

test("hudTheme: dark by default, light on request, and only #rrggbb colours get through", () => {
  assert.deepEqual(hudTheme(null), { ...DARK });
  assert.equal(hudTheme({ mode: "light" }).panel, LIGHT.panel);
  const t = hudTheme({ mode: "dark", colors: { primary: "#112233", background: "red", border: "url(x)", foreground: "#abcdef" } });
  assert.equal(t.accent, "#112233");
  assert.equal(t.fg, "#abcdef");
  assert.equal(t.panel, DARK.panel, "a named colour is ignored");
  assert.equal(t.line, DARK.line, "anything that is not a hex colour is ignored");
});

test("formatTime and formatDate read like a phone clock", () => {
  assert.deepEqual(formatTime(0), { clock: "12:00", half: "AM" });
  assert.deepEqual(formatTime(9 * 60 + 5), { clock: "9:05", half: "AM" });
  assert.deepEqual(formatTime(12 * 60), { clock: "12:00", half: "PM" });
  assert.deepEqual(formatTime(21 * 60 + 40 + 1440), { clock: "9:40", half: "PM" });
  assert.equal(formatDate(new Date(2026, 9, 28)), "WED 28");
});

test("dayFraction runs from 6 am to 2 am and stays full overnight", () => {
  assert.equal(dayFraction(6 * 60), 0);
  assert.equal(dayFraction(16 * 60), 0.5);
  assert.equal(dayFraction(26 * 60), 1);
  assert.ok(dayFraction(3 * 60) >= 0 && dayFraction(3 * 60) <= 1);
});

test("skyIcon: rain wins, then the moon at night, the sun by day", () => {
  assert.equal(skyIcon(12 * 60, "rain"), "rain");
  assert.equal(skyIcon(22 * 60, "sun"), "moon");
  assert.equal(skyIcon(4 * 60, "sun"), "moon");
  assert.equal(skyIcon(10 * 60, "sun"), "sun");
});

test("agentStatus names what an agent is doing", () => {
  assert.deepEqual(agentStatus({ inside: true }), { label: "at home", tone: "off" });
  assert.deepEqual(agentStatus({ activity: { label: "Fixing tests" } }), { label: "Fixing tests", tone: "work" });
  assert.equal(agentStatus({ chat: {} }).tone, "chat");
  assert.equal(agentStatus({}).label, "idle");
});

test("pixelWidth counts glyph widths plus one-pixel gaps", () => {
  assert.equal(pixelWidth("1", 2), 10);
  assert.equal(pixelWidth("11", 2), 22);
  assert.ok(pixelWidth("9:40", 4) > pixelWidth("940", 2));
});

function fakeRenderer(width, height, extra = {}) {
  const agents = [{ id: "harvis", name: "Harvis", pos: { x: 1, y: 1 } }, { id: "scout", name: "Scout", pos: { x: 2, y: 1 }, inside: true }];
  return Object.assign(Object.create(StardewRenderer.prototype), {
    canvas: { width, height }, theme: DARK, hits: [], speed: 1, selected: null, glitchP: -1, glitchBuf: null,
    sim: { minutes: 10 * 60, weather: "sun", agents, agent: (id) => agents.find((a) => a.id === id) },
    spritesFor: () => ({}),
    ...extra,
  });
}

test("normal layout: every control and every agent row is clickable, inside the canvas", () => {
  const r = fakeRenderer(1280, 720);
  r.drawClock(g); r.drawResidents(g); r.drawButtons(g);
  assert.deepEqual(r.hits.filter((h) => h.kind === "button").map((h) => h.action).sort(), BUTTONS.map((b) => b.action).sort());
  assert.deepEqual(r.hits.filter((h) => h.kind === "agent").map((h) => h.id), ["harvis", "scout"]);
  for (const h of r.hits) assert.ok(h.x >= 0 && h.y >= 0 && h.x + h.w <= 1280 && h.y + h.h <= 720, JSON.stringify(h));
  const buttons = r.hits.filter((h) => h.kind === "button");
  for (const a of buttons) for (const b of buttons) {
    if (a !== b) assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y, "buttons overlap");
  }
});

test("small layout: no speed or weather buttons, agents as tiles, the dialogue stays on screen", () => {
  const r = fakeRenderer(320, 240, { selected: "harvis" });
  assert.equal(r.compact, true);
  r.drawClock(g); r.drawResidents(g); r.drawDialogue(g); r.drawButtons(g);
  assert.equal(r.hits.some((h) => h.kind === "button"), false);
  assert.equal(r.hits.filter((h) => h.kind === "agent").length, 2);
  const d = r.hits.find((h) => h.kind === "dialogue");
  assert.ok(d && d.x + d.w <= 320 && d.y + d.h <= 240);
});

test("setTheme takes a resolved theme or a raw message, and flashHud respects reduced motion", () => {
  const r = fakeRenderer(1280, 720);
  r.setTheme({ mode: "light" });
  assert.equal(r.theme.panel, LIGHT.panel);
  r.setTheme(DARK);
  assert.equal(r.theme, DARK);
  r.glitchAt = -Infinity; r.reducedMotion = true; r.flashHud(1000);
  assert.equal(r.glitchAt, -Infinity);
  r.reducedMotion = false; r.lowFx = false; r.flashHud(1000);
  assert.equal(r.glitchAt, 1000);
});
