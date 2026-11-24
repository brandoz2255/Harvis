// What a bot is really doing picks where it is on the island.
//
//   busy  at the cafe (a chair from world.desks on maps that list them)
//   idle  on the benches and fountain (world.couches on maps that list them)
//   away  walks through its door (or to its bed on maps without doors)
//
// Agents without a presence keep the plain island day (schedule, wandering, bedtime).
// keepPresence runs from Sim.dailyLife, so a door that was blocked or an event that
// cleared the activity is put right on the next ten-minute tick.

export const PRESENCES = ["busy", "idle", "away"];

const DESK = ["desk", "work", "cafe", "plaza"];
const COUCHES = [["couch", "lounge"], ["benchW", "benchE", "fountain", "plaza"]];

const ACTIVITY = {
  busy: { kind: "working", label: "at the desk", say: "Busy at my desk." },
  idle: { kind: "lounging", label: "on the couch", say: "Taking a break on the couch." },
};

function placeFor(sim, a, presence) {
  // Maps with real seats (the office): the first free chair or couch cushion; all taken, stand near.
  const seats = presence === "busy" ? sim.world.desks : sim.world.couches;
  const seat = seats?.length ? freeSeat(sim, seats, a) : null;
  if (seat) return seat;
  const places = sim.world.places ?? {};
  let names = DESK;
  if (presence === "idle") {
    // Spread loungers over every couch the map has instead of piling onto the first.
    const couches = COUCHES.map((group) => group.filter((n) => places[n])).find((group) => group.length) ?? [];
    const i = Math.max(0, sim.agents.indexOf(a));
    names = couches.length ? [couches[i % couches.length]] : DESK;
  }
  const name = names.find((n) => places[n]);
  const target = name ? places[name] : Object.values(places)[0];
  return target ? freeSpot(sim, target, a, 4) ?? target : null;
}

// sim.nearestFreeTo, minus tiles another resident already holds as its spot: two
// busy bots both pick the free desk tile, and the second stops a step short of it.
function freeSpot(sim, t, a, maxR) {
  const held = new Set(sim.agents.filter((b) => b !== a && b.spot).map((b) => `${b.spot.x},${b.spot.y}`));
  const w = sim.world;
  let best = null, bestD = Infinity;
  for (let dy = -maxR; dy <= maxR; dy++)
    for (let dx = -maxR; dx <= maxR; dx++) {
      const p = { x: t.x + dx, y: t.y + dy };
      const d = Math.abs(dx) + Math.abs(dy);
      if (d === 0 || d > maxR || d >= bestD || held.has(`${p.x},${p.y}`)) continue;
      if (!w.isWalkable(p.x, p.y) || w.isNoStop(p.x, p.y) || w.cost(p.x, p.y) >= 5) continue;
      const holder = sim.claimant(p);
      if (holder !== undefined && holder !== a.id) continue;
      best = p; bestD = d;
    }
  return best;
}

function freeSeat(sim, seats, a) {
  const held = new Set(sim.agents.filter((b) => b !== a && b.spot).map((b) => `${b.spot.x},${b.spot.y}`));
  return seats.find((p) => {
    if (held.has(`${p.x},${p.y}`) || !sim.world.isWalkable(p.x, p.y)) return false;
    const holder = sim.claimant(p);
    return holder === undefined || holder === a.id;
  }) ?? null;
}

function near(a, spot, r = 4) {
  return Math.abs(a.tile.x - spot.x) + Math.abs(a.tile.y - spot.y) <= r;
}

/** Set one agent's presence; anything that is not a known presence clears it. */
export function setPresence(sim, id, presence) {
  const a = sim.agent(id);
  if (!a || a.pet) return false;
  const next = PRESENCES.includes(presence) ? presence : null;
  if (a.presence === next) return true;
  a.presence = next;
  a.spot = null;
  if (!next) {
    if (a.activity && (a.activity.kind === "working" || a.activity.kind === "lounging")) a.activity = null;
    sim.emit("activity", { id: a.id, activity: a.activity });
    return true;
  }
  keepPresence(sim, a);
  sim.emit("presence", { id: a.id, presence: next });
  return true;
}

/** Keep an agent where its presence says it is. */
export function keepPresence(sim, a) {
  if (a.presence === "away") {
    if (a.activity) { a.activity = null; sim.emit("activity", { id: a.id, activity: null }); }
    if (!a.sleeping) sim.goToBed(a);
    return;
  }
  if (a.sleeping || a.inside) sim.wake(a);
  if (a.inside) return; // doorway crowded; next tick
  const want = ACTIVITY[a.presence];
  if (!a.activity || a.activity.say !== want.say) {
    a.activity = { ...want };
    sim.emit("activity", { id: a.id, activity: a.activity });
  }
  if (a.chat) sim.endChat(a);
  if (!a.spot) a.spot = placeFor(sim, a, a.presence);
  if (!a.spot) return;
  if (!near(a, a.spot, 0) && !a.goal && !a.next && !a.path.length) sim.orderMove(a.id, a.spot);
  // At the desk: back to the camera, facing the screen. On a couch: facing the room.
  else if (near(a, a.spot, 0)) {
    if (a.presence === "busy") a.facing = "up";
    else if (sim.world.couches?.length) a.facing = "down";
  }
}
