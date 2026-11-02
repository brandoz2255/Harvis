import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { TILE, PAL, drawGround, drawProp, drawFront, drawFountain, fountainBoxes, fountainFx, drawLights, isWindow } from "../town-art.js";

const world = parseMap(ISLAND_MAP);

// A recording 2D context: no pixels, just what was painted and where.
function recorder() {
  const calls = [];
  const g = new Proxy({}, {
    get: (_t, prop) => prop === "calls" ? calls : (...args) => { calls.push([prop, ...args]); return g; },
    set: (_t, prop, v) => { if (prop === "fillStyle") calls.push(["fillStyle", v]); return true; },
  });
  return g;
}
const fills = (calls) => calls.filter((c) => c[0] === "fillRect");
const colours = (calls) => calls.filter((c) => c[0] === "fillStyle").map((c) => c[1]);

test("every ground tile paints a full 16x16 tile, and never throws", () => {
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++) {
    const ch = world.charAt(x, y);
    if (ch === "#") continue; // walls are props; nothing shows through them
    const g = recorder();
    drawGround(g, ch, x, y, world);
    const rects = fills(g.calls);
    const inside = rects.every((c) => c[1] >= x * TILE && c[2] >= y * TILE && c[1] + c[3] <= (x + 1) * TILE && c[2] + c[4] <= (y + 1) * TILE);
    const area = rects.reduce((n, c) => n + c[3] * c[4], 0);
    assert.ok(inside, `ground under "${ch}" at ${x},${y} stays in its tile`);
    assert.ok(area >= TILE * TILE, `ground under "${ch}" at ${x},${y} covers its tile`);
  }
});

test("props, the front layer and the lights draw without throwing and stay near the map", () => {
  const g = recorder();
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++) drawProp(g, world.charAt(x, y), x, y, world, "#ff8844");
  drawFront(g, world);
  drawLights(g, world, { glow: true });
  assert.ok(fills(g.calls).length > 500);
  for (const c of fills(g.calls)) assert.ok(c[1] > -4 * TILE && c[1] < (world.w + 4) * TILE, `x ${c[1]}`);
});

test("bed owners colour their blanket", () => {
  const g = recorder();
  drawProp(g, "b", 2, 1, world, "#12ab34");
  assert.ok(colours(g.calls).includes("#12ab34"));
});

test("a striped awning goes over the cafe and shop doors, a plain porch roof over the apartment's", () => {
  const g = recorder();
  drawFront(g, world);
  const cols = colours(g.calls);
  assert.ok(cols.includes("#c8503c"), "cafe awning stripe");
  assert.ok(cols.includes("#3f8f5c"), "shop awning stripe");
  assert.ok(cols.includes("#f4ead0"), "cream stripe");
  assert.ok(cols.includes(PAL.lamp), "lamp glass");
  assert.ok(cols.includes(PAL.leaf), "tree canopy");
});

test("windows sit on shopfronts only, never on the door tile or the building corners", () => {
  assert.equal(isWindow(world, 2, 6), true);
  assert.equal(isWindow(world, 5, 6), false, "door");
  assert.equal(isWindow(world, 0, 6), false, "corner");
  assert.equal(isWindow(world, 12, 0), false, "back wall seen from inside");
});

test("one fountain basin, 4x3 tiles, is found and drawn; the jets change from phase to phase", () => {
  const boxes = fountainBoxes(world);
  assert.deepEqual(boxes, [{ x: 14, y: 14, w: 4, h: 3 }]);
  const base = recorder();
  drawFountain(base, boxes[0]);
  assert.ok(colours(base.calls).includes(PAL.water));
  const shapes = [0, 1, 2, 3].map((ph) => { const g = recorder(); fountainFx(g, boxes[0], ph); return JSON.stringify(fills(g.calls)); });
  assert.equal(new Set(shapes).size, 4, "four distinct animation frames");
});

test("a fountain's water never leaves its basin", () => {
  const [b] = fountainBoxes(world);
  for (let ph = 0; ph < 4; ph++) {
    const g = recorder();
    fountainFx(g, b, ph);
    for (const c of fills(g.calls)) {
      assert.ok(c[1] >= b.x * TILE && c[1] + c[3] <= (b.x + b.w) * TILE, `x ${c[1]} in the basin`);
      assert.ok(c[2] >= (b.y - 1) * TILE && c[2] + c[4] <= (b.y + b.h) * TILE, `y ${c[2]} near the basin`);
    }
  }
});

test("the palette has paving and road, and the sand, dock and shrine colours are gone", () => {
  for (const gone of ["sand", "sandDot", "dock", "torii", "shrine", "pond"]) assert.equal(PAL[gone], undefined, gone);
  assert.ok(Array.isArray(PAL.pave) && Array.isArray(PAL.plaza));
});
