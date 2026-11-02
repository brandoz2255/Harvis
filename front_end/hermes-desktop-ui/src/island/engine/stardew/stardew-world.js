// Build a sim World (same interface as world.js parseMap) from a real Stardew tBIN map.
// Walkability follows the game's own rules (REA: isPositionImpassableForNPCSchedule +
// tile properties): Back tile must exist and not be Water; a Buildings tile blocks unless
// it is Passable; NoPath on Back blocks. Path preference from Type (REA:
// getPreferenceValueForTerrainType: stone -7, wood -4, dirt -2).
import { key } from "../world.js";

const TYPE_COST = { stone: 0.55, wood: 0.65, dirt: 0.8, grass: 0.95 };

export function worldFromTbin(map, { places = {}, beds = [], petBeds = [], homeDoors = [] } = {}) {
  const back = map.layers.find((l) => l.id === "Back");
  const bld = map.layers.find((l) => l.id === "Buildings");
  const W = back.size.w, H = back.size.h;
  // per-sheet "@TileIndex@N@Prop" lookup
  const sheetProps = {};
  for (const s of map.tilesheets) {
    const m = new Map();
    for (const [k, v] of Object.entries(s.properties)) {
      const r = /^@TileIndex@(\d+)@(.+)$/.exec(k);
      if (!r) continue;
      if (!m.has(+r[1])) m.set(+r[1], {});
      m.get(+r[1])[r[2]] = v;
    }
    sheetProps[s.id] = m;
  }
  const propOf = (tile, name) => {
    if (!tile) return undefined;
    if (tile.props && name in tile.props) return tile.props[name];
    return sheetProps[tile.sheet]?.get(tile.index)?.[name];
  };
  const truthy = (v) => v !== undefined && v !== "F" && v !== "f" && v !== false;

  const walk = new Uint8Array(W * H), opaque = new Uint8Array(W * H), cost = new Float32Array(W * H).fill(1);
  const water = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x, b = back.tiles[i], u = bld?.tiles[i];
    const isWater = truthy(propOf(b, "Water"));
    water[i] = isWater ? 1 : 0;
    let ok = !!b && !isWater && !truthy(propOf(b, "NoPath"));
    if (u && !truthy(propOf(u, "Passable"))) { ok = false; opaque[i] = 1; }
    if (b && propOf(b, "Passable") === "F") ok = false;
    walk[i] = ok ? 1 : 0;
    const t = String(propOf(b, "Type") ?? "").toLowerCase();
    if (TYPE_COST[t]) cost[i] = TYPE_COST[t];
  }
  // auto chokepoints: 1-wide corridors (walkable with walls on both sides)
  const W_ = (x, y) => x >= 0 && y >= 0 && x < W && y < H && walk[y * W + x] === 1;
  const noStop = new Set();
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (!W_(x, y)) continue;
    const lr = !W_(x - 1, y) && !W_(x + 1, y) && (W_(x, y - 1) || W_(x, y + 1));
    const ud = !W_(x, y - 1) && !W_(x, y + 1) && (W_(x - 1, y) || W_(x + 1, y));
    if (lr || ud) noStop.add(key(x, y));
  }
  for (const h of homeDoors) noStop.add(key(h.x, h.y)); // doorways

  return {
    w: W, h: H, places, beds, petBeds, homeDoors, map,
    tileAt: (x, y) => (W_(x, y) ? { walk: true } : null),
    charAt: (x, y) => (x < 0 || y < 0 || x >= W || y >= H ? "~" : water[y * W + x] ? "~" : walk[y * W + x] ? "," : "#"),
    isWalkable: (x, y) => W_(x, y),
    isOpaque: (x, y) => x >= 0 && y >= 0 && x < W && y < H && opaque[y * W + x] === 1,
    isNoStop: (x, y) => noStop.has(key(x, y)),
    cost: (x, y) => cost[y * W + x] ?? 1,
    propAt: (layerId, x, y, name) => propOf(map.layers.find((l) => l.id === layerId)?.tiles[y * W + x], name),
  };
}
