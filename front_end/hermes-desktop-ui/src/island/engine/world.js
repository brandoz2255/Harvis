// Town world: tile grid, walkability, line of sight, named places.
// Layer idea from Stardew's documented map format (Back / Buildings / Front):
// tiles here carry their gameplay properties; the renderer draws tree canopies,
// shop awnings and lamp heads in a Front layer so characters can walk "behind" them.

/** Tile legend. walk = can stand on it, opaque = blocks line of sight. */
export const TILES = {
  "#": { name: "wall", walk: false, opaque: true },
  _: { name: "floor", walk: true }, // home: pets sleep on it
  w: { name: "boards", walk: true }, // cafe and shop floor
  b: { name: "bed", walk: true, cost: 6 },
  c: { name: "cushion", walk: true, cost: 6 },
  d: { name: "door", walk: true, noStop: true },
  t: { name: "counter", walk: false, opaque: false },
  s: { name: "shelf", walk: false, opaque: false },
  "=": { name: "sidewalk", walk: true, cost: 0.7 },
  ":": { name: "plaza", walk: true, cost: 0.7 }, // cobbles around the fountain
  r: { name: "road", walk: true },
  x: { name: "crosswalk", walk: true, cost: 0.8 },
  ",": { name: "grass", walk: true },
  f: { name: "flowers", walk: true },
  B: { name: "bench", walk: true },
  T: { name: "tree", walk: false, opaque: true }, // tree in a planter
  p: { name: "planter", walk: false, opaque: false },
  L: { name: "lamp", walk: false, opaque: false },
  F: { name: "fountain", walk: false, opaque: false },
  S: { name: "busSign", walk: false, opaque: false },
  h: { name: "hedge", walk: false, opaque: false }, // hedge and iron fence: the town's edge
};

export const ISLAND_MAP = {
  rows: [
    "################################", //  0
    "#_b_b_b_b_#wtttttttw#wssssssssw#", //  1
    "#_________#wwwwwwwww#wwwwwwwwww#", //  2
    "#_________#wtwwwwwtw#wsswwwwssw#", //  3
    "#________c#wwwwwwwww#wwwwwwwwww#", //  4
    "#_________#wwwwwwwww#wwwwwwtttw#", //  5
    "#####d#########d#########d######", //  6
    "h==============================h", //  7
    "h=p=====T=L=======T=L=======T=ph", //  8
    "hrrrrxxrrrrrrrrxxrrrrrrrrxxrrrrh", //  9
    "hrrrrxxrrrrrrrrxxrrrrrrrrxxrrrrh", // 10
    "h==L======L=========L=======L==h", // 11
    "h=p===p=:p::::::::::::phhhhhhhhh", // 12
    "h=======::T::L::::L::T:h,T,,,T,h", // 13
    "h=p====T::::::FFFF:::::h,,f,,,,h", // 14
    "hhhh=hhh::::B:FFFF:B:::=,f,,,,,h", // 15
    "hhhS=Bhh::::::FFFF:::::h,,B,ff,h", // 16
    "hhh===hh::T::L::::L::T:hT,,fff,h", // 17
    "hhh===hh:p::::::::::::ph,,,,ff,h", // 18
    "hhhhhhhhhhhhhhhhhhhhhhhhhhhhhhhh", // 19
  ],
  // Single-file chokepoints beyond doors: nobody idles or chats here.
  noStop: [
    [23, 15], // park gate
    [4, 15], // bus stop nook entrance
  ],
  places: {
    plaza: { x: 15, y: 12 },
    benchW: { x: 12, y: 15 },
    benchE: { x: 19, y: 15 },
    fountain: { x: 15, y: 17 },
    cafe: { x: 15, y: 4 },
    shop: { x: 25, y: 4 },
    busstop: { x: 4, y: 17 },
    garden: { x: 28, y: 17 },
    park: { x: 26, y: 17 },
    home: { x: 5, y: 3 },
    north: { x: 22, y: 8 },
  },
  // Bed spots are anonymous; the sim assigns them to whichever agents the session has.
  beds: [{ x: 2, y: 1 }, { x: 4, y: 1 }, { x: 6, y: 1 }, { x: 8, y: 1 }],
  petBeds: [{ x: 9, y: 4 }],
};

export const key = (x, y) => y * 1000 + x;

/** Build a queryable world from a map definition. */
export function parseMap(def) {
  const h = def.rows.length;
  const w = def.rows[0].length;
  const noStop = new Set((def.noStop ?? []).map(([x, y]) => key(x, y)));
  const tileAt = (x, y) =>
    x < 0 || y < 0 || x >= w || y >= h ? null : TILES[def.rows[y][x]] ?? null;
  return {
    w,
    h,
    rows: def.rows,
    places: def.places ?? {},
    beds: def.beds ?? [],
    petBeds: def.petBeds ?? [],
    homeDoors: def.homeDoors ?? [],
    tileAt,
    charAt: (x, y) => def.rows[y]?.[x] ?? "h",
    isWalkable: (x, y) => tileAt(x, y)?.walk === true,
    isOpaque: (x, y) => tileAt(x, y)?.opaque === true,
    isNoStop: (x, y) => tileAt(x, y)?.noStop === true || noStop.has(key(x, y)),
    cost: (x, y) => tileAt(x, y)?.cost ?? 1,
  };
}

/** Bresenham walk between tile centres; opaque tiles strictly between block sight. */
export function lineOfSight(world, a, b) {
  let x0 = a.x, y0 = a.y;
  const dx = Math.abs(b.x - x0), dy = -Math.abs(b.y - y0);
  const sx = x0 < b.x ? 1 : -1, sy = y0 < b.y ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    if (x0 === b.x && y0 === b.y) return true;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
    if ((x0 !== b.x || y0 !== b.y) && world.isOpaque(x0, y0)) return false;
  }
}
