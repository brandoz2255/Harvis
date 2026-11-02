// startIsland's battery governor must not keep a disposed island alive. No DOM: the globals it
// touches are faked and the render loop never runs (requestAnimationFrame is a no-op).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { parseTbin } from "../stardew/tbin.js";
import { worldFromTbin } from "../stardew/stardew-world.js";
import { startIsland } from "../stardew/stardew-app.js";
import { tinyMap, TINY_PRESET } from "./fixtures.js";

const NAMES = ["navigator", "window", "document", "ResizeObserver", "requestAnimationFrame", "cancelAnimationFrame"];

function fakeCanvas() {
  const g = new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
  return {
    width: 0, height: 0, parentElement: null,
    getContext: () => g,
    getBoundingClientRect: () => ({ width: 640, height: 480 }),
    addEventListener() {}, setPointerCapture() {},
  };
}

const saved = Object.fromEntries(NAMES.map((n) => [n, Object.getOwnPropertyDescriptor(globalThis, n)]));
const def = (n, value) => Object.defineProperty(globalThis, n, { value, configurable: true, writable: true });
const nav = {};
def("navigator", nav);
def("window", { addEventListener() {}, removeEventListener() {} });
def("document", { createElement: fakeCanvas, addEventListener() {}, removeEventListener() {}, hidden: false });
def("ResizeObserver", class { observe() {} disconnect() {} });
def("requestAnimationFrame", () => 1);
def("cancelAnimationFrame", () => {});
after(() => { for (const n of NAMES) saved[n] ? Object.defineProperty(globalThis, n, saved[n]) : delete globalThis[n]; });

function fakeBattery() {
  const b = { charging: false, level: 1, listeners: new Set() };
  b.addEventListener = (type, fn) => { if (type === "levelchange") b.listeners.add(fn); };
  b.removeEventListener = (type, fn) => { if (type === "levelchange") b.listeners.delete(fn); };
  return b;
}

async function island(getBattery) {
  nav.getBattery = getBattery;
  const mapData = { map: parseTbin(tinyMap()), sheets: {}, name: "Tiny" };
  const world = worldFromTbin(mapData.map, { places: TINY_PRESET.places, homeDoors: TINY_PRESET.homeDoors });
  return startIsland({ canvas: fakeCanvas(), world, agents: [], pack: {}, mapData, preset: TINY_PRESET });
}

const settle = () => new Promise((r) => setTimeout(r, 0));

test("dispose() removes the battery levelchange listener", async () => {
  const b = fakeBattery();
  const app = await island(() => Promise.resolve(b));
  await settle();
  assert.equal(b.listeners.size, 1, "listener attached while the island is live");
  app.dispose();
  assert.equal(b.listeners.size, 0, "listener gone after dispose");
});

test("a low battery still steps the island down to low-fx", async () => {
  const b = fakeBattery(); b.level = 0.1;
  const app = await island(() => Promise.resolve(b));
  await settle();
  assert.equal(app.r.lowFx, true);
  app.dispose();
});

test("getBattery resolving after dispose attaches nothing", async () => {
  const b = fakeBattery();
  let resolve;
  const app = await island(() => new Promise((r) => { resolve = r; }));
  app.dispose();
  resolve(b);
  await settle();
  assert.equal(b.listeners.size, 0);
  assert.equal(app.r.lowFx, false, "a disposed island is not touched by a late battery reading");
});

test("a rejecting or missing getBattery is harmless", async () => {
  (await island(() => Promise.reject(new Error("denied")))).dispose();
  (await island(undefined)).dispose();
  await settle();
});
