// Runs only against the user's own imported game files; skipped when ISLAND_STARDEW_ASSETS is unset.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { parseTbin } from "../stardew/tbin.js";
import { worldFromTbin } from "../stardew/stardew-world.js";
import { findPath } from "../pathfinding.js";
import { Sim, TICKS_PER_10MIN, SPEED } from "../sim.js";
import { ISLAND_S } from "../stardew/maps/island-s.js";
import { TOWN } from "../stardew/maps/town.js";
import { normalizeSession } from "../agents.js";
import { DEMO_SESSION } from "../../examples/demo-session.js";

// Point ISLAND_STARDEW_ASSETS at the folder written by scripts/island/import-stardew.mjs (never committed).
const ASSETS = (process.env.ISLAND_STARDEW_ASSETS ?? "").replace(/\/$/, "");
const mapPath = (name) => `${ASSETS}/Maps/${name}.tbin`;
const haveMap = (name) => !!ASSETS && existsSync(mapPath(name));
const MAP = mapPath("Island_S");
const have = haveMap("Island_S");
const haveTown = haveMap("Town");

const buildMap = (name, preset) => worldFromTbin(parseTbin(readFileSync(mapPath(name))), { places: preset.places, homeDoors: preset.homeDoors });
function build() {
  return buildMap("Island_S", ISLAND_S);
}

test("Island_S: tBIN parses with the real layers", { skip: !have && "set ISLAND_STARDEW_ASSETS" }, () => {
  const map = parseTbin(readFileSync(MAP));
  assert.deepEqual(map.layers.map((l) => l.id), ["Back", "Buildings", "Front", "AlwaysFront"]);
  assert.equal(map.layers[0].size.w, 43);
  assert.equal(map.layers[0].size.h, 60);
});

test("Island_S: every hub spot, start and the home door are walkable and reachable", { skip: !have && "set ISLAND_STARDEW_ASSETS" }, () => {
  const w = build();
  const spots = { ...ISLAND_S.places, homeDoor: ISLAND_S.homeDoors[0] };
  for (const [name, p] of Object.entries(spots)) {
    assert.ok(w.isWalkable(p.x, p.y), `${name} walkable`);
    if (name !== "plaza") assert.ok(findPath(w, ISLAND_S.places.plaza, p, { maxNodes: 20000 }), `${name} reachable from plaza`);
  }
});

test("Island_S: the sea is not walkable but the dock is", { skip: !have && "set ISLAND_STARDEW_ASSETS" }, () => {
  const w = build();
  assert.equal(w.isWalkable(10, 45), false, "open water");
  assert.equal(w.isWalkable(21, 42), true, "dock planks");
});

/** One simulated day (06:00 to 06:00) on `w`: nobody overlaps, teleports or gives up, and everyone goes home. */
function fullDay(w) {
  let seed = 11;
  const rng = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const agents = normalizeSession(DEMO_SESSION, w);
  const sim = new Sim({ world: w, rng, wander: true, agents });
  let giveUps = 0, insideAt3 = -1, chats = 0;
  sim.on("chatStart", () => chats++);
  for (let i = 0; i < TICKS_PER_10MIN * 6 * 24; i++) {
    const before = sim.agents.map((a) => ({ ...a.pos, inside: a.inside }));
    sim.tick(); sim.checkInvariants();
    sim.agents.forEach((a, j) => {
      if (!a.inside && !before[j].inside) assert.ok(Math.hypot(a.pos.x - before[j].x, a.pos.y - before[j].y) <= SPEED.sprint + 1e-9, `${a.id} teleported`);
      if (a.status === "blocked") { giveUps++; a.status = "idle"; }
    });
    if (sim.timeString() === "03:00" && insideAt3 < 0) insideAt3 = sim.agents.filter((a) => a.inside).length;
  }
  assert.equal(giveUps, 0);
  assert.equal(insideAt3, agents.length, "everyone home by 03:00");
  assert.ok(sim.agents.every((a) => !a.inside), "everyone back out by 06:00");
  assert.ok(chats >= 3, `${chats} chats (demo has two quiet personas)`);
}

test("Island_S: a full day with the real map — no overlaps, teleports, or give-ups; all go home", { skip: !have && "set ISLAND_STARDEW_ASSETS" }, () => {
  fullDay(build());
});

const skipTown = !haveTown && "set ISLAND_STARDEW_ASSETS (needs Maps/Town.tbin)";

test("Town: tBIN parses with the real layers and size", { skip: skipTown }, () => {
  const map = parseTbin(readFileSync(mapPath("Town")));
  const ids = map.layers.map((l) => l.id);
  for (const id of ["Back", "Buildings", "Front", "AlwaysFront"]) assert.ok(ids.includes(id), `${id} layer`);
  assert.equal(map.layers[0].size.w, 130);
  assert.equal(map.layers[0].size.h, 110);
});

test("Town: every place and home door is walkable, inside the view, and reachable from the plaza", { skip: skipTown }, () => {
  const w = buildMap("Town", TOWN);
  const { view } = TOWN;
  assert.ok(TOWN.places.plaza && TOWN.places.work, "the sim and sessions need plaza and work");
  const spots = { ...TOWN.places, ...Object.fromEntries(TOWN.homeDoors.map((d, i) => [`homeDoor${i}`, d])) };
  for (const [name, p] of Object.entries(spots)) {
    assert.ok(w.isWalkable(p.x, p.y), `${name} walkable`);
    assert.ok(p.x >= view.x && p.x < view.x + view.w && p.y >= view.y && p.y < view.y + view.h, `${name} inside the view`);
    if (name in TOWN.places) assert.equal(w.isNoStop(p.x, p.y), false, `${name} is somewhere agents can stand`);
    if (name !== "plaza") assert.ok(findPath(w, TOWN.places.plaza, p, { maxNodes: 20000 }), `${name} reachable from plaza`);
  }
});

test("Town: the river is not walkable but the bridge over it is", { skip: skipTown }, () => {
  const w = buildMap("Town", TOWN);
  assert.equal(w.isWalkable(73, 58), false, "river");
  assert.equal(w.isWalkable(TOWN.places.bridge.x, TOWN.places.bridge.y), true, "bridge planks");
  assert.equal(w.isWalkable(49, 63), false, "the mailbox blocks its tile");
});

test("Town: a full day with the real map — no overlaps, teleports, or give-ups; all go home", { skip: skipTown }, () => {
  fullDay(buildMap("Town", TOWN));
});
