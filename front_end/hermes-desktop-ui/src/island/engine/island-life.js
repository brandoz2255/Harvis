// Island happenings + building. Generic: happenings come from session config,
// buildables are simple canvas-drawn objects any session can use.
// A build: agent walks to the spot, hammers for a bit, object persists for the session.
export const BUILDABLES = {
  lamp:      { label: "street lamp", ticks: 60 * 8, light: true },
  garden:    { label: "garden",      ticks: 60 * 10 },
  foodcart:  { label: "food cart",   ticks: 60 * 6 },
  signpost:  { label: "signpost",    ticks: 60 * 5 },
  stall:     { label: "market stall",ticks: 60 * 9 },
  bench:     { label: "bench",       ticks: 60 * 7 },
};

/** Start a build: walk there, hammer, place. Returns false if spot/kind invalid.
 *  The exact tile is snapped to the nearest free walkable tile, and the build
 *  is cancelled if the agent can't get there or goes inside. */
export function startBuild(sim, agentId, spot, kind = "lamp") {
  const spec = BUILDABLES[kind];
  const a = sim.agent(agentId);
  if (!spec || !a || !spot) return false;
  sim.world.objects ??= new Map();
  spot = sim.world.isWalkable(spot.x, spot.y) && !sim.world.objects.has(`${spot.x},${spot.y}`)
    ? spot : sim.nearestFreeTo(spot, a, 6);
  if (!spot) return false;
  const key = `${spot.x},${spot.y}`;
  if (sim.world.objects.has(key)) return false;
  const ok = sim.orderMove(agentId, spot);
  if (ok === false) return false;
  a.build = { kind, spot, left: spec.ticks, arrived: false, expires: sim.ticks + 60 * 90 };
  sim.emit("buildStart", { id: agentId, kind, spot });
  return true;
}

/** Per-tick driver. Call from app loop (or wire to sim.tick via this helper). */
export function tickBuilds(sim) {
  for (const a of sim.agents) {
    const b = a.build;
    if (!b) continue;
    const cancel = () => { a.build = null; if (a.activity?.label?.startsWith("building")) a.activity = null; sim.emit("buildCancel", { id: a.id, kind: b.kind }); };
    if (a.inside || sim.ticks > b.expires) { cancel(); continue; }
    const at = Math.round(a.pos.x) === b.spot.x && Math.round(a.pos.y) === b.spot.y;
    if (!at) { if (!b.arrived && !a.goal && !a.next) cancel(); continue; } // gave up walking there
    if (!b.arrived) { b.arrived = true; a.activity = { label: `building a ${BUILDABLES[b.kind].label}` }; }
    if (sim.ticks % 90 === 0) sim.emote(a.id, "!"); // hammering beats
    if (--b.left <= 0) {
      sim.world.objects.set(`${b.spot.x},${b.spot.y}`, { kind: b.kind, x: b.spot.x, y: b.spot.y, builtAt: sim.ticks, by: a.id });
      a.activity = null; a.build = null;
      sim.emote(a.id, "happy");
      sim.say(a, `Done! ${BUILDABLES[b.kind].label} finished.`);
      sim.emit("buildDone", { id: a.id, kind: b.kind, spot: b.spot });
    }
  }
}

/** Scheduled island happenings from session config:
 *  happenings: [{ time:"19:00", place:"busstop", minAgents:2, chatBoost:0.4, build?: "lamp" }]
 *  At `time`, agents gather at the named place. If `build` is set and the spot is empty,
 *  one agent builds it first. Cheap: checked once per game-minute. */
export function tickHappenings(sim, happenings, fired) {
  const now = sim.timeString().slice(0, 5);
  for (const h of happenings ?? []) {
    const key = `${sim.day ?? 0}:${h.time}:${h.place}`;
    if (h.time !== now || fired.has(key)) continue;
    fired.add(key);
    const place = sim.world.places?.[h.place];
    if (!place) continue;
    let builder = null;
    if (h.build && !(sim.world.objects?.size)) {
      const free = sim.agents.filter((x) => !x.inside && !x.chat);
      builder = free[0];
      if (builder) startBuild(sim, builder.id, { x: place.x + 1, y: place.y + 1 }, h.build);
    }
    for (const a of sim.agents) {
      if (a.inside || a.id === builder?.id || a.pet) continue;
      sim.orderMove(a.id, { x: place.x + (Math.random() * 4 - 2 | 0), y: place.y + (Math.random() * 4 - 2 | 0) });
    }
    if (h.chatBoost) for (const a of sim.agents) a.chatty = Math.min(1, (a.chatty ?? 0.3) + h.chatBoost);
    sim.emit("happening", { name: h.name ?? `${h.time} @ ${h.place}` });
    // decay the boost after ~1 game hour
    if (h.chatBoost) setTimeout(() => { for (const a of sim.agents) a.chatty = Math.max(0.05, (a.chatty ?? 0.3) - h.chatBoost); }, 420 * TICKMS);
  }
}
const TICKMS = 1000 / 60;
