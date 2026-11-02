import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim, TICKS_PER_10MIN } from "../sim.js";
import { pickOutfit } from "../appearance.js";

const world = parseMap(ISLAND_MAP);
const runTicks = (sim, n) => { for (let i = 0; i < n; i++) { sim.tick(); sim.checkInvariants(); } };
const at = (a, p) => a.tile.x === p.x && a.tile.y === p.y && !a.next;

const OUTFITS = [
  { id: "default", precedence: 100 },
  { id: "hoodie", precedence: 0, weight: 3 },
  { id: "tee", precedence: 0, weight: 1 },
  { id: "parka", precedence: -10, season: "winter" },
  { id: "raincoat", precedence: -20, outdoors: true, condition: (c) => c.weather === "rain" },
  { id: "kimono", precedence: -50, condition: (c) => c.festival === "obon" },
  { id: "nightgown", precedence: -100, slot: "sleepy" },
];

test("outfits: lowest precedence among matching entries wins", () => {
  assert.equal(pickOutfit(OUTFITS, { season: "winter" }, () => 0).id, "parka");
  assert.equal(pickOutfit(OUTFITS, { weather: "rain", outdoors: true }, () => 0).id, "raincoat");
  assert.equal(pickOutfit(OUTFITS, { weather: "rain", outdoors: false }, () => 0).id, "hoodie", "raincoat is outdoors-only");
  assert.equal(pickOutfit(OUTFITS, { festival: "obon", season: "summer" }, () => 0).id, "kimono");
});

test("outfits: ties are broken by weight", () => {
  assert.equal(pickOutfit(OUTFITS, {}, () => 0.0).id, "hoodie");
  assert.equal(pickOutfit(OUTFITS, {}, () => 0.74).id, "hoodie");
  assert.equal(pickOutfit(OUTFITS, {}, () => 0.76).id, "tee");
});

test("outfits: exclusive slots only apply when that slot is asked for, with a fallback", () => {
  assert.notEqual(pickOutfit(OUTFITS, {}, () => 0).id, "nightgown");
  assert.equal(pickOutfit(OUTFITS, { slot: "sleepy" }, () => 0).id, "nightgown");
  assert.equal(pickOutfit([{ id: "x", precedence: 0, season: "fall" }], { season: "spring" }, () => 0).id, "default");
});

test("schedules: agents leave for scheduled places at the scheduled time", () => {
  const sim = new Sim({ world, autonomy: true, rng: () => 0.99, agents: [
    { id: "cy", start: { x: 4, y: 17 }, schedule: { "07:00": "plaza", "08:00": "cafe" } }] });
  sim.setTime("06:50");
  runTicks(sim, TICKS_PER_10MIN);
  assert.equal(sim.timeString(), "07:00");
  assert.ok(sim.agent("cy").goal || sim.agent("cy").next, "left for the plaza");
  runTicks(sim, TICKS_PER_10MIN * 3);
  assert.ok(at(sim.agent("cy"), world.places.plaza), "arrived at plaza");
});

test("bedtime: sleepy outfit at 21:00, everyone walks to bed at 22:00, sleeps, wakes at 06:00", () => {
  const sim = new Sim({ world, autonomy: true, rng: () => 0.99, agents: [
    { id: "ada", start: world.places.plaza }, { id: "bo", start: world.places.garden },
    { id: "pip", start: world.places.fountain, pet: true }] });
  sim.setTime("20:50");
  runTicks(sim, TICKS_PER_10MIN);
  assert.equal(sim.agent("ada").outfit.id, "pajamas", "sleepy outfit from 21:00");
  sim.setTime("21:50");
  runTicks(sim, TICKS_PER_10MIN + 1800);
  for (const id of ["ada", "bo"]) {
    const a = sim.agent(id);
    assert.ok(at(a, a.bed), `${id} in bed`);
    assert.equal(a.sleeping, true, `${id} asleep`);
  }
  const pip = sim.agent("pip");
  assert.equal(pip.sleeping, true, "pip asleep somewhere");
  assert.ok(pip.sleepSpot, "pip chose a sleep spot");
  sim.setTime("05:50");
  runTicks(sim, TICKS_PER_10MIN);
  assert.equal(sim.agent("ada").sleeping, false, "awake at 06:00");
  assert.notEqual(sim.agent("ada").outfit.id, "pajamas");
});

test("wander: an idle agent re-rolls every 6-12 s and stays near home", () => {
  const home = world.places.plaza;
  let seed = 3;
  const rng = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const sim = new Sim({ world, wander: true, rng, agents: [{ id: "ada", start: home }] });
  const moves = [];
  sim.on("wander", (e) => moves.push(e));
  runTicks(sim, 60 * 60);
  assert.ok(moves.length >= 4 && moves.length <= 11, `${moves.length} wanders in 60 s`);
  for (let i = 1; i < moves.length; i++) {
    const gap = moves[i].tick - moves[i - 1].tick;
    assert.ok(gap >= 360, `gap ${gap} >= 6 s`);
  }
  for (const m of moves) assert.ok(Math.abs(m.to.x - home.x) + Math.abs(m.to.y - home.y) <= 3, "near home");
});

test("homes: on maps with home doors, agents walk in at bedtime, vanish (freeing the tile), and walk out at 06:00", () => {
  const w = { ...world, homeDoors: [{ x: 15, y: 12 }] };
  const sim = new Sim({ world: w, autonomy: true, rng: () => 0.99, agents: [
    { id: "ada", start: { x: 3, y: 12 } }, { id: "bo", start: { x: 27, y: 15 } }] });
  sim.setTime("21:50");
  runTicks(sim, TICKS_PER_10MIN + 2400);
  for (const id of ["ada", "bo"]) {
    const a = sim.agent(id);
    assert.equal(a.inside, true, `${id} went inside`);
    assert.equal(sim.claimant(w.homeDoors[0]), undefined, "door tile is free while they sleep");
  }
  sim.setTime("05:50");
  runTicks(sim, TICKS_PER_10MIN + 60);
  for (const id of ["ada", "bo"]) {
    const a = sim.agent(id);
    assert.equal(a.inside, false, `${id} came out`);
    assert.equal(sim.claimant(a.tile), id, "standing on a claimed tile again");
  }
});
