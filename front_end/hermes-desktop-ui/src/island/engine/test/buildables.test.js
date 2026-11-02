import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim } from "../sim.js";
import { BUILDABLES, startBuild, tickBuilds, tickHappenings } from "../island-life.js";
import { drawObject, Ambient } from "../ambient.js";

const world = parseMap(ISLAND_MAP);
const painter = () => {
  const calls = [];
  const g = new Proxy({}, { get: (_t, p) => p === "calls" ? calls : (...a) => { calls.push([p, ...a]); return g; }, set: () => true });
  return g;
};

test("buildables are things a town has, not beach things", () => {
  assert.deepEqual(Object.keys(BUILDABLES).sort(), ["bench", "foodcart", "garden", "lamp", "signpost", "stall"]);
  for (const gone of ["campfire", "sandcastle", "tent"]) assert.equal(BUILDABLES[gone], undefined, gone);
  assert.equal(BUILDABLES.lamp.light, true);
});

test("an agent walks to a spot on the sidewalk, builds a food cart there, and it persists", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "ada", start: world.places.plaza }] });
  assert.equal(startBuild(sim, "ada", { x: 20, y: 8 }, "foodcart"), true);
  assert.equal(startBuild(sim, "ada", { x: 20, y: 8 }, "campfire"), false, "old kinds are rejected");
  for (let i = 0; i < 60 * 40 && !sim.world.objects.size; i++) { sim.tick(); tickBuilds(sim); }
  const [o] = [...sim.world.objects.values()];
  assert.equal(o.kind, "foodcart");
  assert.ok(world.isWalkable(o.x, o.y) || world.charAt(o.x, o.y) === "L", "built on the street, not in a wall");
});

test("startBuild defaults to a street lamp", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "ada", start: world.places.plaza }] });
  startBuild(sim, "ada", { x: 14, y: 12 });
  assert.equal(sim.agent("ada").build.kind, "lamp");
});

test("a 'busstop' happening gathers everyone at the bus stop", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "ada", start: world.places.plaza }, { id: "bo", start: world.places.park }] });
  sim.setTime("19:00");
  tickHappenings(sim, [{ time: "19:00", place: "busstop" }], new Set());
  for (const a of sim.agents) assert.ok(a.goal, `${a.id} is on the way`);
});

test("every buildable draws something, and only the lamp lights the night", () => {
  const day = { minutes: 12 * 60, ticks: 0 }, night = { minutes: 22 * 60, ticks: 0 };
  for (const kind of Object.keys(BUILDABLES)) {
    const a = painter(), b = painter();
    drawObject(a, { kind, x: 3, y: 3 }, day);
    drawObject(b, { kind, x: 3, y: 3 }, night);
    assert.ok(a.calls.filter((c) => c[0] === "fillRect").length >= 3, `${kind} draws`);
    const glows = b.calls.filter((c) => c[0] === "arc").length;
    assert.equal(glows > 0, kind === "lamp", `${kind} glow at night`);
    assert.equal(a.calls.filter((c) => c[0] === "arc").length, 0, `${kind} no glow by day`);
  }
});

test("ambient pigeons only land on walkable ground and stay there", () => {
  const sim = new Sim({ world, autonomy: false, agents: [] });
  const amb = new Ambient(sim.world);
  sim.minutes = 12 * 60; // daytime
  let seen = 0;
  for (let i = 0; i < 4 * 6000; i++) {
    sim.ticks = i;
    amb.tick(sim);
    for (const c of amb.critters) if (c.type === "pigeon") {
      seen++;
      assert.ok(world.isWalkable(Math.floor(c.x / 16), Math.floor(c.y / 16)), `pigeon on ${c.x},${c.y}`);
    }
  }
  assert.ok(seen > 0, "pigeons showed up");
  assert.ok(!amb.critters.some((c) => c.type === "fish"), "no fish in the town");
  amb.draw(painter(), 0);
});

test("ambient critters stay inside the area the camera can show", () => {
  const sim = new Sim({ world, autonomy: false, agents: [] });
  const area = { x: 7 * 16, y: 7 * 16, w: 16 * 16, h: 8 * 16 }; // the street and plaza, not the whole map
  const amb = new Ambient(sim.world, area);
  for (const minutes of [12 * 60, 22 * 60]) {
    sim.minutes = minutes; amb.critters = [];
    let seen = 0;
    for (let i = 0; i < 4 * 6000; i++) {
      sim.ticks = i;
      amb.tick(sim);
      for (const c of amb.critters) {
        if (c.type === "bird") continue; // birds fly in from just off the left edge
        seen++;
        assert.ok(c.x >= area.x && c.x <= area.x + area.w && c.y >= area.y && c.y <= area.y + area.h, `${c.type} at ${c.x},${c.y}`);
      }
    }
    assert.ok(seen > 0, `critters showed up at ${minutes / 60}:00`);
  }
});
