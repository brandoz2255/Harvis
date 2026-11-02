// Harvis session agents -> island residents.
// Every Harvis user brings their own agents (local models, API models, personalities).
// This module is the only place that knows the session shape; the sim stays generic.
//
// Session agent shape (all fields optional except id):
//   { id, name, provider, model, personality: "free text",
//     persona: { chatty: -1..1, adds: [topics], removes: [topics] },
//     appearance: { color: "#rrggbb", sprite: "<asset-pack sprite key>" },
//     schedule: { "HH:MM": "<place name>" }, pet: false }

const ID_RE = /^[A-Za-z0-9_.:-]{1,64}$/;
const PALETTE = ["#e2a63b", "#d9774b", "#8b6fe0", "#2fd3c7", "#5fbf5a", "#e8628a", "#4d8fe0", "#c9b458", "#a0705a", "#7fd6f2"];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Heuristic persona from a free-text personality string (no model call needed). */
export function personaFromText(text = "") {
  const t = String(text).toLowerCase();
  let chatty = 0;
  for (const w of ["outgoing", "talkative", "chatty", "friendly", "social", "bubbly", "extrovert", "energetic"]) if (t.includes(w)) chatty += 0.35;
  for (const w of ["quiet", "shy", "reserved", "introvert", "terse", "keeps to itself", "stoic", "laconic"]) if (t.includes(w)) chatty -= 0.35;
  const adds = [], removes = [];
  if (/(cod(e|ing)|program|engineer|developer|debug)/.test(t)) adds.push("code");
  if (/(research|science|paper|analy)/.test(t)) adds.push("work");
  if (/(gossip|drama|rumou?r)/.test(t) && !/never gossip|no gossip|hates gossip/.test(t)) adds.push("gossip");
  if (/never gossip|no gossip|hates gossip|doesn't gossip/.test(t)) removes.push("gossip");
  return { chatty: clamp(Number(chatty.toFixed(2)), -1, 1), adds, removes };
}

/** A default day built from whatever places the map has, offset per agent so they spread out. */
function defaultSchedule(world, index) {
  const names = Object.keys(world.places ?? {});
  if (!names.length) return {};
  const slots = ["08:00", "10:30", "13:00", "15:30", "18:00", "20:00"];
  const out = {};
  slots.forEach((time, i) => { out[time] = names[(index * 3 + i * 2) % names.length]; });
  return out;
}

function startFor(world, index, taken) {
  const spots = Object.values(world.places ?? {});
  for (let k = 0; k < spots.length; k++) {
    const p = spots[(index + k) % spots.length];
    if (world.isWalkable(p.x, p.y) && !taken.has(`${p.x},${p.y}`)) return { ...p };
  }
  // fall back to scanning for any walkable free tile
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++)
    if (world.isWalkable(x, y) && !world.isNoStop(x, y) && !taken.has(`${x},${y}`)) return { x, y };
  throw new Error("map has no free walkable tile");
}

export function normalizeAgent(raw, world, index = 0, taken = new Set()) {
  if (!raw || typeof raw.id !== "string" || !ID_RE.test(raw.id)) throw new Error(`agent needs a safe string id (got ${JSON.stringify(raw?.id)})`);
  const fromText = personaFromText(raw.personality);
  const p = raw.persona ?? {};
  const persona = {
    chatty: clamp(Number(p.chatty ?? fromText.chatty) || 0, -1, 1),
    adds: [...new Set([...(p.adds ?? []), ...fromText.adds].map(String))].slice(0, 12),
    removes: [...new Set([...(p.removes ?? []), ...fromText.removes].map(String))].slice(0, 12),
  };
  const color = /^#[0-9a-f]{6}$/i.test(raw.appearance?.color ?? "") ? raw.appearance.color : PALETTE[index % PALETTE.length];
  const schedule = {};
  for (const [time, place] of Object.entries(raw.schedule ?? {})) {
    if (/^\d\d:\d0$/.test(time) && world.places?.[place]) schedule[time] = place;
  }
  const start = raw.start && world.isWalkable(raw.start.x, raw.start.y) ? { x: raw.start.x, y: raw.start.y } : startFor(world, index, taken);
  taken.add(`${start.x},${start.y}`);
  return {
    id: raw.id,
    name: String(raw.name ?? raw.id).slice(0, 40),
    meta: { provider: raw.provider ?? null, model: raw.model ?? null },
    persona,
    color,
    sprite: typeof raw.appearance?.sprite === "string" ? raw.appearance.sprite : null,
    schedule: Object.keys(schedule).length ? schedule : defaultSchedule(world, index),
    pet: !!raw.pet,
    start,
  };
}

/** Normalise a whole session: drops invalid/duplicate agents (never throws for one bad entry). */
export function normalizeSession(session, world, { onError = () => {} } = {}) {
  const seen = new Set(), taken = new Set(), out = [];
  (session?.agents ?? []).forEach((raw) => {
    try {
      if (seen.has(raw?.id)) throw new Error(`duplicate agent id ${raw.id}`);
      const a = normalizeAgent(raw, world, out.length, taken);
      seen.add(a.id);
      out.push(a);
    } catch (e) { onError(e, raw); }
  });
  return out;
}
