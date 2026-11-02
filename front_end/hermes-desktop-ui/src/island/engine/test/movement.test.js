import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim, SPEED } from "../sim.js";

const world = parseMap(ISLAND_MAP);
const at = (a, p) => a.tile.x === p.x && a.tile.y === p.y && a.next === null;

function run(sim, ticks, until) {
  for (let i = 0; i < ticks; i++) {
    const before = sim.agents.map((a) => ({ ...a.pos }));
    sim.tick();
    sim.checkInvariants();
    sim.agents.forEach((a, j) => {
      const d = Math.hypot(a.pos.x - before[j].x, a.pos.y - before[j].y);
      assert.ok(d <= SPEED.sprint + 1e-9, `${a.id} moved ${d} tiles in one tick (teleport)`);
    });
    if (until?.()) return i + 1;
  }
  return ticks;
}

test("a single ordered agent walks tile by tile and arrives", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "ada", start: { x: 15, y: 12 } }] });
  const goal = world.places.busstop;
  sim.orderMove("ada", goal);
  const used = run(sim, 3000, () => at(sim.agent("ada"), goal));
  assert.ok(at(sim.agent("ada"), goal), `arrived (took ${used} ticks)`);
});

test("sprints on long routes and walks on short ones", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "a", start: { x: 3, y: 7 } }] });
  sim.orderMove("a", { x: 29, y: 7 });
  sim.tick();
  assert.equal(sim.agent("a").speed, SPEED.sprint, "long route sprints");
  const sim2 = new Sim({ world, autonomy: false, agents: [{ id: "b", start: { x: 15, y: 12 } }] });
  sim2.orderMove("b", { x: 17, y: 12 });
  sim2.tick();
  assert.equal(sim2.agent("b").speed, SPEED.walk, "short route walks");
});

test("head-on standoff in the single apartment door resolves without overlap", () => {
  const sim = new Sim({
    world, autonomy: false,
    agents: [{ id: "inside", start: { x: 5, y: 4 } }, { id: "outside", start: { x: 5, y: 8 } }],
  });
  const goalIn = { x: 5, y: 12 }, goalOut = { x: 5, y: 3 };
  sim.orderMove("inside", goalIn);
  sim.orderMove("outside", goalOut);
  const used = run(sim, 4000, () => at(sim.agent("inside"), goalIn) && at(sim.agent("outside"), goalOut));
  assert.ok(at(sim.agent("inside"), goalIn), "inside agent got out");
  assert.ok(at(sim.agent("outside"), goalOut), `outside agent got in (took ${used} ticks)`);
});

test("an ordered move onto an occupied tile stops next to it instead of overlapping or stalling", () => {
  const sim = new Sim({
    world, autonomy: false,
    agents: [{ id: "a", start: { x: 14, y: 11 } }, { id: "b", start: { x: 16, y: 11 } }],
  });
  sim.orderMove("a", { x: 16, y: 11 }); // b stands there and never moves
  let gaveUp = false;
  for (let i = 0; i < 600; i++) { sim.tick(); sim.checkInvariants(); gaveUp ||= sim.agent("a").status === "blocked"; }
  const a = sim.agent("a");
  assert.ok(!(a.tile.x === 16 && a.tile.y === 11), "never entered b's tile");
  assert.equal(Math.abs(a.tile.x - 16) + Math.abs(a.tile.y - 11), 1, "stands right next to the spot");
  assert.equal(a.status, "idle");
  assert.equal(gaveUp, false, "no 5 s stall");
});

test("stress: five agents on random errands never overlap, teleport, or deadlock", () => {
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  const places = Object.values(world.places);
  const ids = ["ada", "bo", "cy", "dee", "pip"];
  const sim = new Sim({ world, autonomy: false, agents: ids.map((id, i) => ({ id, start: places[i] })) });
  let orders = 0, arrivals = 0, giveUps = 0;
  for (let i = 0; i < 60 * 60 * 5; i++) {
    for (const a of sim.agents) {
      if (a.status === "blocked") { giveUps++; a.status = "idle"; }
      if (a.status === "idle" && !a.next) {
        const g = places[Math.floor(rnd() * places.length)];
        if (g.x !== a.tile.x || g.y !== a.tile.y) { sim.orderMove(a.id, g); orders++; }
      }
    }
    const before = sim.agents.map((a) => ({ s: a.status, ...a.pos }));
    sim.tick();
    sim.checkInvariants();
    sim.agents.forEach((a, j) => {
      assert.ok(Math.hypot(a.pos.x - before[j].x, a.pos.y - before[j].y) <= SPEED.sprint + 1e-9, "no teleport");
      if (before[j].s !== "idle" && a.status === "idle") arrivals++;
    });
  }
  assert.ok(orders > 400, `enough traffic (${orders})`);
  assert.ok(arrivals >= orders - ids.length, `arrivals ${arrivals}/${orders}`);
  assert.equal(giveUps, 0);
});

test("regression: a full dead-end bus stop nook behind a 1-tile neck never gridlocks", () => {
  const sim = new Sim({ world, autonomy: false, agents: [
    { id: "a", start: { x: 3, y: 17 } }, { id: "b", start: { x: 4, y: 17 } }, { id: "c", start: { x: 5, y: 17 } },
    { id: "d", start: { x: 4, y: 13 } }] });
  sim.orderMove("d", world.places.busstop); // wants in while the nook is full
  for (const id of ["a", "b", "c"]) sim.orderMove(id, world.places.plaza); // everyone inside wants out
  let blocked = 0;
  for (let i = 0; i < 3000; i++) {
    sim.tick(); sim.checkInvariants();
    for (const ag of sim.agents) if (ag.status === "blocked") blocked++;
    if (sim.agents.every((ag) => ag.status === "idle" && !ag.next)) break;
  }
  assert.equal(blocked, 0, "nobody gave up");
  assert.ok(sim.agents.every((ag) => ag.status === "idle"), "everyone settled");
  const d = sim.agent("d");
  assert.ok(d.tile.y >= 16, `d made it into the nook (${d.tile.x},${d.tile.y})`);
});
