import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap, key } from "../world.js";
import { findPath } from "../pathfinding.js";

const world = parseMap(ISLAND_MAP);
const adjacent = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y) === 1;

function assertValidPath(path, start, goal) {
  assert.ok(path, "expected a path");
  assert.deepEqual(path.at(-1), goal, "ends at goal");
  let prev = start;
  for (const step of path) {
    assert.ok(adjacent(prev, step), `4-neighbour step ${JSON.stringify(prev)} -> ${JSON.stringify(step)}`);
    assert.ok(world.isWalkable(step.x, step.y), `walkable ${JSON.stringify(step)}`);
    prev = step;
  }
}

test("finds a 4-neighbour walkable path from plaza to the end of the bus stop nook", () => {
  const start = world.places.plaza, goal = world.places.busstop;
  assertValidPath(findPath(world, start, goal), start, goal);
});

test("leaves the apartment through its single door", () => {
  const start = world.places.home, goal = world.places.plaza;
  const path = findPath(world, start, goal);
  assertValidPath(path, start, goal);
  assert.ok(path.some((p) => p.x === 5 && p.y === 6), "passes the door tile");
});

test("walks from the cafe to the shop by way of the street and its sidewalks", () => {
  const start = world.places.cafe, goal = world.places.shop;
  const path = findPath(world, start, goal);
  assertValidPath(path, start, goal);
  assert.ok(path.some((p) => p.x === 15 && p.y === 6), "out of the cafe door");
  assert.ok(path.some((p) => p.x === 25 && p.y === 6), "in at the shop door");
  assert.ok(!path.some((p) => world.charAt(p.x, p.y) === "#"), "never through a wall");
});

test("crosses the road on a crosswalk rather than through traffic lanes", () => {
  const path = findPath(world, { x: 15, y: 7 }, { x: 15, y: 12 });
  assertValidPath(path, { x: 15, y: 7 }, { x: 15, y: 12 });
  for (const p of path.filter((q) => q.y === 9 || q.y === 10)) assert.equal(world.charAt(p.x, p.y), "x", `crosswalk at ${p.x},${p.y}`);
});

test("the park is entered through its gate", () => {
  const path = findPath(world, world.places.plaza, world.places.park);
  assertValidPath(path, world.places.plaza, world.places.park);
  assert.ok(path.some((p) => p.x === 23 && p.y === 15), "passes the gate tile");
});

test("returns an empty path when already at the goal", () => {
  assert.deepEqual(findPath(world, { x: 16, y: 11 }, { x: 16, y: 11 }), []);
});

test("returns null for an unwalkable goal", () => {
  assert.equal(findPath(world, world.places.plaza, { x: 0, y: 0 }), null);
});

test("treats blocked tiles as walls (door blocked = apartment sealed)", () => {
  const blocked = new Set([key(5, 6)]);
  assert.equal(findPath(world, world.places.home, world.places.plaza, { blocked }), null);
});

test("prefers the sidewalk over the road when both are the same length", () => {
  // Along row 7 the sidewalk costs 0.7 a tile against 1 for the road beside it.
  const path = findPath(world, { x: 3, y: 7 }, { x: 28, y: 7 });
  assert.ok(path.every((p) => p.y === 7), "stays on the sidewalk row");
});
