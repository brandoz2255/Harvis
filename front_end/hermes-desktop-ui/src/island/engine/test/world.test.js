import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, TILES, parseMap, lineOfSight } from "../world.js";
import { findPath } from "../pathfinding.js";

const world = parseMap(ISLAND_MAP);

test("town map is a 32x20 rectangle", () => {
  assert.equal(world.w, 32);
  assert.equal(world.h, 20);
  for (const row of ISLAND_MAP.rows) assert.equal(row.length, 32);
});

test("every map character has a legend entry, and none of them is beach scenery", () => {
  for (const row of ISLAND_MAP.rows) for (const ch of row) assert.ok(TILES[ch], `legend has "${ch}"`);
  const names = Object.values(TILES).map((t) => t.name);
  for (const gone of ["water", "sand", "dock", "torii", "shrine", "pond"]) assert.ok(!names.includes(gone), `${gone} is gone`);
  for (const city of ["sidewalk", "road", "crosswalk", "fountain", "lamp", "planter", "tree"]) assert.ok(names.includes(city), `${city} exists`);
});

test("walkability follows tile types", () => {
  assert.equal(world.isWalkable(5, 6), true, "apartment door");
  assert.equal(world.isWalkable(4, 6), false, "shopfront wall");
  assert.equal(world.isWalkable(0, 0), false, "building corner");
  assert.equal(world.isWalkable(10, 8), false, "lamp post");
  assert.equal(world.isWalkable(8, 8), false, "tree in a planter");
  assert.equal(world.isWalkable(9, 12), false, "planter");
  assert.equal(world.isWalkable(15, 15), false, "fountain");
  assert.equal(world.isWalkable(12, 1), false, "cafe counter");
  assert.equal(world.isWalkable(22, 1), false, "shop shelf");
  assert.equal(world.isWalkable(2, 1), true, "bed");
  assert.equal(world.isWalkable(10, 9), true, "road");
  assert.equal(world.isWalkable(15, 9), true, "crosswalk");
  assert.equal(world.isWalkable(20, 14), true, "plaza cobbles");
  assert.equal(world.isWalkable(28, 17), true, "park flowers");
  assert.equal(world.isWalkable(-1, 3), false, "off map");
});

test("the town's edge is closed: no walkable tile on the border, and off-map reads as hedge", () => {
  for (let x = 0; x < world.w; x++) for (const y of [0, world.h - 1]) assert.equal(world.isWalkable(x, y), false, `top/bottom ${x},${y}`);
  for (let y = 0; y < world.h; y++) for (const x of [0, world.w - 1]) assert.equal(world.isWalkable(x, y), false, `sides ${x},${y}`);
  assert.equal(world.charAt(-1, 4), "h");
  assert.equal(world.charAt(40, 40), "h");
});

test("chokepoints are marked no-stop so nobody parks on them", () => {
  for (const [x, y] of [[5, 6], [15, 6], [25, 6]]) assert.equal(world.isNoStop(x, y), true, `door ${x},${y}`);
  assert.equal(world.isNoStop(23, 15), true, "park gate");
  assert.equal(world.isNoStop(4, 15), true, "bus stop nook entrance");
  assert.equal(world.isNoStop(15, 12), false, "plaza");
  assert.equal(world.isNoStop(4, 17), false, "bus stop");
});

test("noStop chokepoints really are one tile wide", () => {
  for (const [x, y] of ISLAND_MAP.noStop) {
    const side = (dx, dy) => world.isWalkable(x + dx, y + dy);
    assert.ok(!(side(1, 0) && side(-1, 0) && side(0, 1) && side(0, -1)), `${x},${y} is a junction, not a gap`);
    const horizontal = side(1, 0) && side(-1, 0) && !side(0, 1) && !side(0, -1);
    const vertical = side(0, 1) && side(0, -1) && !side(1, 0) && !side(-1, 0);
    assert.ok(horizontal || vertical, `${x},${y} is walled on both sides`);
  }
});

test("line of sight is blocked by walls and trees but not by a fountain or fences", () => {
  assert.equal(lineOfSight(world, { x: 2, y: 3 }, { x: 12, y: 3 }), false, "through the apartment wall");
  assert.equal(lineOfSight(world, { x: 8, y: 13 }, { x: 12, y: 13 }), false, "through a tree");
  assert.equal(lineOfSight(world, { x: 12, y: 15 }, { x: 19, y: 15 }), true, "across the fountain");
  assert.equal(lineOfSight(world, { x: 15, y: 11 }, { x: 15, y: 13 }), true, "down the crosswalk");
});

test("beds and named places resolve to walkable tiles", () => {
  for (const [name, p] of Object.entries(world.places))
    assert.equal(world.isWalkable(p.x, p.y), true, `place ${name}`);
  for (const [name, p] of Object.entries(world.beds))
    assert.equal(world.isWalkable(p.x, p.y), true, `bed ${name}`);
  for (const p of world.petBeds) assert.equal(world.charAt(p.x, p.y), "c", "pet bed is a cushion");
});

test("the town's named places are the ones sessions and topics use", () => {
  assert.deepEqual(Object.keys(world.places).sort(),
    ["benchE", "benchW", "busstop", "cafe", "fountain", "garden", "home", "north", "park", "plaza", "shop"]);
  for (const name of ["pond", "dock", "shrine", "beach", "cabin"]) assert.equal(world.places[name], undefined, `${name} was renamed`);
});

test("everything you can stand on is reachable from the plaza; doors lead somewhere", () => {
  const seen = new Set([world.places.plaza.y * 1000 + world.places.plaza.x]);
  const todo = [world.places.plaza];
  while (todo.length) {
    const p = todo.pop();
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const x = p.x + dx, y = p.y + dy, k = y * 1000 + x;
      if (world.isWalkable(x, y) && !seen.has(k)) { seen.add(k); todo.push({ x, y }); }
    }
  }
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++)
    if (world.isWalkable(x, y)) assert.ok(seen.has(y * 1000 + x), `${x},${y} (${world.charAt(x, y)}) is cut off`);
  for (const [name, p] of Object.entries(world.places)) assert.ok(findPath(world, world.places.plaza, p) !== null, `${name} reachable`);
  for (const p of [...world.beds, ...world.petBeds]) assert.ok(findPath(world, world.places.plaza, p) !== null, `bed ${p.x},${p.y} reachable`);
});

test("three shopfronts, each with one door onto the sidewalk", () => {
  const doors = [];
  world.rows.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === "d") doors.push({ x, y }); }));
  assert.equal(doors.length, 3);
  for (const d of doors) assert.equal(world.charAt(d.x, d.y + 1), "=", `sidewalk outside door ${d.x}`);
});
