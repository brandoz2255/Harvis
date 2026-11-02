// The tBIN parser and the map-to-world conversion, on a synthetic map (no game files needed).
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseTbin } from "../stardew/tbin.js";
import { worldFromTbin } from "../stardew/stardew-world.js";
import { findPath } from "../pathfinding.js";
import { tinyMap, TINY_PRESET } from "./fixtures.js";

test("parseTbin: layers, sizes and tile indexes survive a round trip", () => {
  const map = parseTbin(tinyMap());
  assert.deepEqual(map.layers.map((l) => l.id), ["Back", "Buildings", "Front"]);
  assert.deepEqual(map.layers[0].size, { w: 6, h: 4 });
  assert.equal(map.tilesheets[0].image, "tiny_sheet");
  assert.equal(map.layers[0].tiles[1].index, 0);
  assert.equal(map.layers[1].tiles[1 * 6 + 3].index, 2);
  assert.equal(map.layers[1].tiles[0], null);
});

test("parseTbin: refuses bytes that are not a tBIN10 map", () => {
  assert.throws(() => parseTbin(new TextEncoder().encode("not a map at all").buffer), /not a tBIN10/);
});

test("worldFromTbin: water and walls block, open ground is walkable and routable", () => {
  const w = worldFromTbin(parseTbin(tinyMap()), { places: TINY_PRESET.places, homeDoors: TINY_PRESET.homeDoors });
  assert.equal(w.isWalkable(0, 0), false, "water");
  assert.equal(w.isWalkable(3, 1), false, "wall");
  assert.equal(w.isOpaque(3, 1), true);
  assert.equal(w.isWalkable(1, 1), true);
  assert.equal(w.isWalkable(-1, 0), false, "off the map");
  assert.ok(findPath(w, { x: 1, y: 1 }, { x: 5, y: 3 }), "a route exists around the wall");
});

// Hand-built bytes: the magic, then whatever build() appends.
function crafted(build) {
  const b = [];
  const i32 = (v) => { for (let i = 0; i < 4; i++) b.push((v >>> (8 * i)) & 255); };
  const str = (s) => { i32(s.length); for (const ch of s) b.push(ch.charCodeAt(0)); };
  for (const ch of "tBIN10") b.push(ch.charCodeAt(0));
  build({ b, i32, str });
  return Uint8Array.from(b);
}
const layerHeader = ({ b, i32, str }, w, h) => {
  str("m"); str(""); i32(0); i32(0); // id, description, no properties, no tilesheets
  i32(1); str("Back"); b.push(1); str(""); i32(w); i32(h); i32(16); i32(16); i32(0);
};

test("parseTbin: a negative string length throws instead of looping", () => {
  const buf = crafted(({ i32 }) => { i32(-8); });
  assert.throws(() => parseTbin(buf), /string length -8/);
});

test("parseTbin: a string longer than the file throws", () => {
  const buf = crafted(({ i32 }) => { i32(0x7fffffff); });
  assert.throws(() => parseTbin(buf), /out of range/);
});

test("parseTbin: a file cut off mid-field throws a clear error", () => {
  const full = new Uint8Array(tinyMap());
  for (const n of [8, 30, full.length - 3]) assert.throws(() => parseTbin(full.slice(0, n)), /truncated|out of range|bad tile tag/, `cut at ${n}`);
});

test("parseTbin: oversized or negative layer dimensions are refused before allocating", () => {
  for (const [w, h] of [[100000, 100000], [1001, 1], [1, 1001], [-1, 5], [5, -1], [1000, 1000 + 1]]) {
    assert.throws(() => parseTbin(crafted((c) => layerHeader(c, w, h))), /out of range/, `${w}x${h}`);
  }
});

test("parseTbin: a layer at the size cap is accepted when its rows are present", () => {
  const buf = crafted((c) => {
    layerHeader(c, 1000, 1000);
    for (let y = 0; y < 1000; y++) { c.b.push("N".charCodeAt(0)); c.i32(1000); }
  });
  assert.equal(parseTbin(buf).layers[0].tiles.length, 1_000_000);
});

test("parseTbin: a null run that leaves the row or goes backwards throws", () => {
  for (const run of [-4, 7]) {
    const buf = crafted((c) => { layerHeader(c, 6, 1); c.b.push("N".charCodeAt(0)); c.i32(run); });
    assert.throws(() => parseTbin(buf), /bad null run/, `run ${run}`);
  }
});

test("parseTbin: an animated tile with no frames throws", () => {
  const buf = crafted((c) => { layerHeader(c, 1, 1); c.b.push("A".charCodeAt(0)); c.i32(100); c.i32(0); });
  assert.throws(() => parseTbin(buf), /frame count/);
});

test("parseTbin: a layer count above the layer-count cap is refused as out of range (this trips the layer-count cap, not the cumulative tile cap tested below)", () => {
  const nLayers = 100;
  const buf = crafted(({ b, i32, str }) => {
    str("m"); str(""); i32(0); i32(0); i32(nLayers);
    for (let i = 0; i < nLayers; i++) {
      str("L"); b.push(1); str(""); i32(1000); i32(1000); i32(16); i32(16); i32(0);
      for (let y = 0; y < 1000; y++) { b.push("N".charCodeAt(0)); i32(1000); }
    }
  });
  assert.throws(() => parseTbin(buf), /out of range/);
});

test("parseTbin: the cumulative cap trips on the layer that crosses it, not after parsing it", () => {
  // Header-only layers: if the cap were checked after the rows, this would fail as truncated instead.
  const buf = crafted(({ b, i32, str }) => {
    str("m"); str(""); i32(0); i32(0); i32(5);
    for (let i = 0; i < 5; i++) {
      str("L"); b.push(1); str(""); i32(1000); i32(1000); i32(16); i32(16); i32(0);
      if (i < 4) for (let y = 0; y < 1000; y++) { b.push("N".charCodeAt(0)); i32(1000); }
    }
  });
  assert.throws(() => parseTbin(buf), /across its layers/);
});

test("parseTbin: absurd layer and tilesheet counts are refused", () => {
  for (const n of [-1, 1000, 0x7fffffff]) {
    assert.throws(() => parseTbin(crafted(({ i32, str }) => { str("m"); str(""); i32(0); i32(0); i32(n); })), /layer count/, `layers ${n}`);
    assert.throws(() => parseTbin(crafted(({ i32, str }) => { str("m"); str(""); i32(0); i32(n); })), /tilesheet count/, `sheets ${n}`);
  }
});
