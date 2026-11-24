import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim, TICKS_PER_10MIN } from "../sim.js";
import { setPresence } from "../presence.js";
import { agentStatus } from "../stardew/hud.js";

const world = parseMap(ISLAND_MAP);
const doorWorld = parseMap({ ...ISLAND_MAP, homeDoors: [ISLAND_MAP.places.home] });
const runTicks = (sim, n) => { for (let i = 0; i < n; i++) { sim.tick(); sim.checkInvariants(); } };
const dist = (a, p) => Math.abs(a.tile.x - p.x) + Math.abs(a.tile.y - p.y);
const make = (w = world, agents = [{ id: "ada", start: w.places.plaza }, { id: "bo", start: w.places.garden }]) =>
  new Sim({ world: w, autonomy: true, wander: true, rng: () => 0.99, agents });

test("presence: busy walks to the desk and stays there typing", () => {
  const sim = make();
  sim.setTime("10:00");
  assert.equal(setPresence(sim, "ada", "busy"), true);
  const ada = sim.agent("ada");
  assert.equal(ada.activity.kind, "working");
  runTicks(sim, TICKS_PER_10MIN * 4);
  assert.ok(dist(ada, world.places.cafe) <= 4, "at the desk (the cafe on the built-in map)");
  assert.equal(ada.facing, "up", "facing the screen");
  const before = { ...ada.tile };
  runTicks(sim, TICKS_PER_10MIN * 6);
  assert.deepEqual(ada.tile, before, "no wandering off while busy");
  assert.equal(agentStatus(ada).tone, "work");
});

test("presence: two busy residents get a desk each", () => {
  const sim = make();
  sim.setTime("10:00");
  setPresence(sim, "ada", "busy");
  setPresence(sim, "bo", "busy");
  runTicks(sim, TICKS_PER_10MIN * 6);
  const ada = sim.agent("ada"), bo = sim.agent("bo");
  assert.notDeepEqual(ada.spot, bo.spot, "different desks");
  assert.deepEqual(ada.tile, ada.spot);
  assert.deepEqual(bo.tile, bo.spot);
  assert.equal(bo.facing, "up");
});

test("presence: idle residents spread over the couches", () => {
  const sim = make();
  sim.setTime("10:00");
  setPresence(sim, "ada", "idle");
  setPresence(sim, "bo", "idle");
  runTicks(sim, TICKS_PER_10MIN * 5);
  const ada = sim.agent("ada"), bo = sim.agent("bo");
  assert.ok(dist(ada, world.places.benchW) <= 4, "ada on the west bench");
  assert.ok(dist(bo, world.places.benchE) <= 4, "bo on the east bench");
  assert.equal(ada.activity.label, "on the couch");
  assert.equal(agentStatus(ada).tone, "idle");
});

test("presence: away leaves through the door, survives the morning, and comes back when busy", () => {
  assert.ok(doorWorld.isWalkable(doorWorld.homeDoors[0].x, doorWorld.homeDoors[0].y), "fixture door is walkable");
  const sim = make(doorWorld);
  sim.setTime("10:00");
  setPresence(sim, "ada", "away");
  runTicks(sim, TICKS_PER_10MIN * 6);
  const ada = sim.agent("ada");
  assert.equal(ada.inside, true, "went through the door");
  assert.equal(agentStatus(ada).label, "out of office");
  sim.setTime("05:50");
  runTicks(sim, TICKS_PER_10MIN);
  assert.equal(ada.inside, true, "the 06:00 wake-up does not bring an away bot back");
  setPresence(sim, "ada", "busy");
  assert.equal(ada.inside, false, "back out of the door");
  runTicks(sim, TICKS_PER_10MIN * 6);
  assert.ok(dist(ada, doorWorld.places.cafe) <= 4, "walked to the desk");
});

test("presence: away on a map without doors goes to bed, and clearing it restores the island day", () => {
  const sim = make();
  sim.setTime("10:00");
  setPresence(sim, "bo", "away");
  runTicks(sim, TICKS_PER_10MIN * 8);
  const bo = sim.agent("bo");
  assert.equal(bo.sleeping, true);
  assert.equal(bo.inside, false);
  setPresence(sim, "bo", undefined);
  assert.equal(bo.presence, null);
  sim.setTime("10:50");
  runTicks(sim, TICKS_PER_10MIN);
  assert.equal(bo.sleeping, false, "the plain day wakes it during daytime");
});

test("presence: unknown agents and pets are ignored", () => {
  const sim = make(world, [{ id: "pip", start: world.places.fountain, pet: true }]);
  assert.equal(setPresence(sim, "nobody", "busy"), false);
  assert.equal(setPresence(sim, "pip", "busy"), false);
  assert.equal(sim.agent("pip").activity, null);
});
