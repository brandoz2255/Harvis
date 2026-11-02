// Built-in town art. Everything is drawn in code on 16 px tiles (no game files, no images).
// The look is Stardew-ish and light: warm brick paving, soft greens, wooden shopfronts with
// striped awnings, a stone fountain. Back (ground + props) is cached once by the renderer;
// Front (canopies, awnings, lamp heads) is drawn over the characters; the fountain and the
// night lights are separate pieces so the cached Back never has to be rebuilt.

export const TILE = 16;

export const PAL = {
  grass: "#6dbb4f", grassHi: "#86d064", grassLo: "#58a03f",
  pave: ["#cdb897", "#c4ad8a", "#d6c3a3"], paveMortar: "#a39068",
  plaza: ["#d9a984", "#cf9c76", "#e2b794"], plazaMortar: "#a7785a",
  road: "#5f5a68", roadHi: "#6c6776", roadLo: "#504b59", curb: "#bfb095", curbLo: "#8f8068", dash: "#e8c860", stripe: "#efe8d8",
  trunk: "#7a4e2d", leaf: "#3e8a3a", leafHi: "#57a84d", leafLo: "#2e6e2c",
  hedge: "#35763a", hedgeHi: "#4a9347", hedgeLo: "#265a2d",
  wood: "#8b5e3a", woodHi: "#a87a52", woodLo: "#6b4428",
  floor: "#d9b07a", floorLo: "#c49a64", checkA: "#efe0c0", checkB: "#d9bf94", plank: "#dcae78", plankLo: "#c79864",
  stone: "#b9b3a6", stoneHi: "#dcd7ca", stoneLo: "#8f897d",
  water: "#4aa3d8", waterHi: "#8fd0f0", waterLo: "#3687bd", spray: "#e8f6ff",
  iron: "#2f3a3d", glass: "#a9d8ea", glassLo: "#7fb4cc", lamp: "#f3e3b0",
  planter: "#8a5a36", soil: "#4a3020",
  outline: "#2a1e1a",
};

// One look per building, picked by x: apartment 0-9, cafe 10-19, shop 20-31.
const BUILDINGS = [
  { siding: "#b4573f", sidingLo: "#8e4130", sidingHi: "#cc7050", paper: "#e8c9a8", paperLo: "#dcb78f", awning: null },
  { siding: "#5f9a8c", sidingLo: "#477a6e", sidingHi: "#7ab5a6", paper: "#d9e3cf", paperLo: "#c4d3b8", awning: "#c8503c" },
  { siding: "#d6a249", sidingLo: "#b0802f", sidingHi: "#e8bd68", paper: "#f0dcae", paperLo: "#e2c88f", awning: "#3f8f5c" },
];
const building = (x) => BUILDINGS[Math.min(2, Math.floor(x / 10))];

export const hash = (x, y) => {
  let h = (x * 374761393 + y * 668265263) ^ 0x5bd1e995;
  h = (h ^ (h >>> 13)) * 1274126177;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
};
export function px(g, x, y, w, h, c) { g.fillStyle = c; g.fillRect(x, y, w, h); }

const INTERIOR = "_wbcts";
const isFacade = (world, x, y) => !"#".includes(world.charAt(x, y + 1)) && !INTERIOR.includes(world.charAt(x, y + 1));
/** Shopfront wall tiles (not the door, not the building's corner pillars) get a display window. */
export const isWindow = (world, x, y) =>
  world.charAt(x, y) === "#" && isFacade(world, x, y) && [2, 3, 7, 8].includes(x % 10);
/** What a prop stands on: grass in the park, else the paving next to it. */
function under(world, x, y) {
  for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
    const c = world.charAt(x + dx, y + dy);
    if (c === "," || c === "f") return ",";
    if (c === "=" || c === ":") return c;
  }
  return "=";
}

// ---------------------------------------------------------------- ground
function bricks(g, X, Y, x, y, tones, mortar) {
  px(g, X, Y, TILE, TILE, mortar);
  for (let i = 0; i < 4; i++) for (let k = -1; k < 2; k++) {
    const x0 = (i & 1) * 4 + k * 8, a = Math.max(0, x0), b = Math.min(TILE, x0 + 7);
    if (b > a) px(g, X + a, Y + i * 4, b - a, 3, tones[Math.floor(hash(x * 3 + k + i * 7, y * 5 + i) * 3)]);
  }
}

function grass(g, X, Y, x, y) {
  px(g, X, Y, TILE, TILE, PAL.grass);
  for (let i = 0; i < 4; i++) {
    px(g, X + Math.floor(hash(x * 7 + i, y * 3 + i) * 14), Y + Math.floor(hash(x + i, y * 5) * 14), 1, 2, i % 2 ? PAL.grassHi : PAL.grassLo);
  }
}

function floor(g, ch, X, Y, x, y) {
  if (ch === "_" || ch === "b" || ch === "c" || ch === "d") {
    px(g, X, Y, TILE, TILE, PAL.floor);
    for (let i = 0; i < 4; i++) px(g, X, Y + i * 4 + 3, TILE, 1, PAL.floorLo);
  } else if (x < 20) { // cafe: checkerboard
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) px(g, X + j * 4, Y + i * 4, 4, 4, (i + j + x + y) & 1 ? PAL.checkB : PAL.checkA);
  } else { // shop: planks
    px(g, X, Y, TILE, TILE, PAL.plank);
    for (let i = 0; i < 4; i++) px(g, X, Y + i * 4 + 3, TILE, 1, PAL.plankLo);
    px(g, X + ((y * 5 + 3) & 15), Y, 1, TILE, PAL.plankLo);
  }
}

function road(g, X, Y, world, x, y, crosswalk) {
  px(g, X, Y, TILE, TILE, PAL.road);
  for (let i = 0; i < 3; i++) px(g, X + Math.floor(hash(x + i * 5, y) * 15), Y + Math.floor(hash(x, y + i * 3) * 15), 2, 1, i & 1 ? PAL.roadHi : PAL.roadLo);
  if (crosswalk) {
    for (const y0 of [1, 6, 11]) px(g, X, Y + y0, TILE, 3, PAL.stripe);
    return;
  }
  const walk = (c) => c === "=" || c === ":";
  const up = world.charAt(x, y - 1), down = world.charAt(x, y + 1);
  if (walk(up)) { px(g, X, Y, TILE, 2, PAL.curb); px(g, X, Y + 2, TILE, 1, PAL.roadLo); }
  if (walk(down)) { px(g, X, Y + 14, TILE, 2, PAL.curb); px(g, X, Y + 13, TILE, 1, PAL.roadLo); }
  // dashed centre line along the seam between the two lanes
  if (!(x & 1)) {
    if (walk(up)) px(g, X + 2, Y + 14, 12, 2, PAL.dash);
    else if (walk(down)) px(g, X + 2, Y, 12, 2, PAL.dash);
  }
}

export function drawGround(g, ch, x, y, world) {
  const X = x * TILE, Y = y * TILE;
  switch (ch) {
    case ",": case "f": case "h": grass(g, X, Y, x, y); break;
    case "=": bricks(g, X, Y, x, y, PAL.pave, PAL.paveMortar); break;
    case ":": bricks(g, X, Y, x, y, PAL.plaza, PAL.plazaMortar); break;
    case "r": road(g, X, Y, world, x, y, false); break;
    case "x": road(g, X, Y, world, x, y, true); break;
    case "_": case "b": case "c": case "d": case "w": case "t": case "s": floor(g, ch, X, Y, x, y); break;
    case "T": case "B": case "p": case "L": case "S": case "F": {
      const u = under(world, x, y);
      if (u === ",") grass(g, X, Y, x, y);
      else bricks(g, X, Y, x, y, u === ":" ? PAL.plaza : PAL.pave, u === ":" ? PAL.plazaMortar : PAL.paveMortar);
      break;
    }
  }
}

// ---------------------------------------------------------------- props
function wall(g, X, Y, world, x, y) {
  const b = building(x), below = world.charAt(x, y + 1);
  if (INTERIOR.includes(below)) { // back wall, seen from inside: wallpaper over a wooden baseboard
    px(g, X, Y, TILE, 12, b.paper);
    for (let i = 1; i < TILE; i += 4) px(g, X + i, Y, 1, 12, b.paperLo);
    px(g, X, Y + 12, TILE, 4, PAL.woodLo); px(g, X, Y + 12, TILE, 1, PAL.wood);
    if (hash(x, y) > 0.72) { px(g, X + 4, Y + 2, 8, 7, PAL.outline); px(g, X + 5, Y + 3, 6, 5, PAL.glass); px(g, X + 5, Y + 5, 6, 1, PAL.glassLo); }
  } else if (isFacade(world, x, y)) { // shopfront seen from the street
    px(g, X, Y, TILE, TILE, b.siding);
    for (let i = 3; i < TILE; i += 4) px(g, X, Y + i, TILE, 1, b.sidingLo);
    px(g, X, Y, TILE, 1, b.sidingHi);
    px(g, X, Y + 13, TILE, 3, b.sidingLo); // foundation
    if (isWindow(world, x, y)) {
      px(g, X + 2, Y + 4, 12, 9, PAL.outline); px(g, X + 3, Y + 5, 10, 7, PAL.glass);
      px(g, X + 3, Y + 5, 10, 2, "#c6e6f2"); px(g, X + 7, Y + 5, 1, 7, PAL.outline);
      px(g, X + 2, Y + 12, 12, 2, PAL.woodHi);
    }
  } else { // side wall between rooms
    px(g, X, Y, TILE, TILE, PAL.woodLo);
    px(g, X + 4, Y, 8, TILE, PAL.wood); px(g, X + 4, Y, 8, 1, PAL.woodHi);
  }
}

function door(g, X, Y, world, x) {
  const b = building(x);
  px(g, X, Y, TILE, TILE, b.siding);
  px(g, X + 1, Y + 2, 14, 14, PAL.outline);
  px(g, X + 2, Y + 3, 12, 13, "#9a5f38");
  px(g, X + 2, Y + 3, 12, 1, PAL.woodHi);
  px(g, X + 4, Y + 5, 8, 4, PAL.glass); // door glass
  px(g, X + 11, Y + 10, 2, 2, "#e8c860"); // handle
  px(g, X + 2, Y + 14, 12, 2, "#b0473a"); // doormat
}

function counter(g, X, Y, world, x, y) {
  const side = world.charAt(x - 1, y) === "t" || world.charAt(x + 1, y) === "t";
  if (!side) { // lone tile: a small round cafe table with a cup
    px(g, X + 3, Y + 4, 10, 8, PAL.outline); px(g, X + 4, Y + 4, 8, 7, PAL.woodHi); px(g, X + 4, Y + 4, 8, 1, "#c79a6c");
    px(g, X + 7, Y + 6, 3, 3, "#f4f1ea"); px(g, X + 8, Y + 7, 1, 1, "#7a4a2a");
    px(g, X + 1, Y + 11, 3, 3, PAL.woodLo); px(g, X + 12, Y + 11, 3, 3, PAL.woodLo); // stools
    return;
  }
  px(g, X, Y + 2, TILE, 12, PAL.woodLo); px(g, X, Y + 2, TILE, 4, PAL.woodHi); px(g, X, Y + 2, TILE, 1, "#c79a6c");
  const r = hash(x, y);
  if (r > 0.3) px(g, X + 3 + Math.floor(r * 6), Y - 1, 3, 4, r > 0.6 ? "#f4f1ea" : "#c8503c"); // cup, jar
  if (r > 0.8) px(g, X + 9, Y - 2, 5, 5, "#aab4b8"); // espresso machine
}

function shelf(g, X, Y, x, y) {
  px(g, X, Y + 1, TILE, 14, PAL.woodLo); px(g, X + 1, Y + 2, 14, 12, PAL.outline);
  const goods = ["#c8503c", "#e8c860", "#5f9a8c", "#f4f1ea", "#8b6fe0"];
  for (const y0 of [3, 8]) {
    px(g, X + 1, Y + y0 + 4, 14, 1, PAL.wood);
    for (let i = 0; i < 4; i++) px(g, X + 2 + i * 3 + (i & 1), Y + y0, 2, 4, goods[Math.floor(hash(x * 5 + i, y + y0) * 5)]);
  }
}

function planterBox(g, X, Y, x, y) {
  px(g, X + 2, Y + 8, 12, 7, PAL.planter); px(g, X + 2, Y + 8, 12, 2, PAL.woodHi); px(g, X + 3, Y + 10, 10, 1, PAL.soil);
  px(g, X + 3, Y + 4, 10, 5, PAL.hedge); px(g, X + 4, Y + 3, 8, 3, PAL.hedgeHi);
  const cols = ["#f5d24a", "#f07ab0", "#ffffff", "#c58af0"];
  for (let i = 0; i < 3; i++) px(g, X + 4 + i * 3, Y + 3 + (i & 1), 2, 2, cols[Math.floor(hash(x + i, y * 3) * 4)]);
}

export function drawProp(g, ch, x, y, world, bedOwner) {
  const X = x * TILE, Y = y * TILE;
  switch (ch) {
    case "#": wall(g, X, Y, world, x, y); break;
    case "d": door(g, X, Y, world, x); break;
    case "b": {
      const c = bedOwner ?? "#c9c9c9";
      px(g, X + 1, Y + 1, 14, 14, PAL.outline);
      px(g, X + 2, Y + 2, 12, 4, "#f4f1ea"); // pillow
      px(g, X + 2, Y + 6, 12, 8, c);
      px(g, X + 2, Y + 6, 12, 1, "#ffffff55");
      break;
    }
    case "c":
      px(g, X + 2, Y + 7, 12, 7, "#e86f8a"); px(g, X + 3, Y + 8, 10, 5, "#f59ab0");
      break;
    case "t": counter(g, X, Y, world, x, y); break;
    case "s": shelf(g, X, Y, x, y); break;
    case "p": planterBox(g, X, Y, x, y); break;
    case "T": {
      px(g, X + 4, Y + 13, 8, 2, "#00000033");
      if (under(world, x, y) !== ",") { px(g, X + 2, Y + 9, 12, 6, PAL.planter); px(g, X + 2, Y + 9, 12, 2, PAL.woodHi); px(g, X + 3, Y + 11, 10, 1, PAL.soil); }
      px(g, X + 6, Y + 2, 4, 10, PAL.trunk);
      break;
    }
    case "h": {
      px(g, X, Y + 1, TILE, 14, PAL.hedge);
      px(g, X, Y + 14, TILE, 2, PAL.hedgeLo);
      for (let i = 0; i < 4; i++) {
        const a = hash(x * 3 + i, y * 7), b = hash(x + i * 5, y);
        px(g, X + Math.floor(a * 13), Y + 1 + Math.floor(b * 9), 3, 2, PAL.hedgeHi);
        px(g, X + Math.floor(b * 12), Y + 5 + Math.floor(a * 7), 2, 2, PAL.hedgeLo);
      }
      break;
    }
    case "L":
      px(g, X + 7, Y + 2, 2, 12, PAL.iron); px(g, X + 5, Y + 13, 6, 3, PAL.iron); px(g, X + 6, Y + 13, 4, 1, "#4d5a5e");
      break;
    case "S": { // bus stop sign
      px(g, X + 7, Y + 5, 2, 10, "#8f9aa0");
      px(g, X + 3, Y + 1, 10, 8, PAL.outline); px(g, X + 4, Y + 2, 8, 6, "#2a6fb8");
      px(g, X + 5, Y + 3, 6, 3, "#f4f1ea"); px(g, X + 6, Y + 6, 1, 1, "#f4f1ea"); px(g, X + 9, Y + 6, 1, 1, "#f4f1ea");
      break;
    }
    case "B": {
      px(g, X + 1, Y + 3, 14, 3, PAL.wood); px(g, X + 1, Y + 3, 14, 1, PAL.woodHi); // backrest
      px(g, X + 1, Y + 7, 14, 4, PAL.wood); px(g, X + 1, Y + 7, 14, 1, PAL.woodHi);
      px(g, X + 2, Y + 11, 2, 4, PAL.iron); px(g, X + 12, Y + 11, 2, 4, PAL.iron);
      break;
    }
    case "f": {
      const cols = ["#f5d24a", "#f07ab0", "#ffffff", "#c58af0"];
      for (let i = 0; i < 5; i++) {
        const fx = X + 2 + Math.floor(hash(x * 11 + i, y) * 11), fy = Y + 2 + Math.floor(hash(x, y * 13 + i) * 11);
        px(g, fx, fy + 1, 1, 2, PAL.grassLo);
        px(g, fx - 1, fy, 3, 1, cols[i % 4]); px(g, fx, fy - 1, 1, 3, cols[i % 4]);
      }
      break;
    }
  }
}

// ---------------------------------------------------------------- fountain (a block of "F" tiles)
/** Bounding boxes {x, y, w, h} (in tiles) of every fountain basin, found once per build. */
export function fountainBoxes(world) {
  const out = [];
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++) {
    if (world.charAt(x, y) !== "F" || world.charAt(x - 1, y) === "F" || world.charAt(x, y - 1) === "F") continue;
    let w = 1, h = 1;
    while (world.charAt(x + w, y) === "F") w++;
    while (world.charAt(x, y + h) === "F") h++;
    out.push({ x, y, w, h });
  }
  return out;
}

/** Static basin: stone rim, still water, central stone column. The jets are drawn by fountainFx. */
export function drawFountain(g, b) {
  const X = b.x * TILE, Y = b.y * TILE, W = b.w * TILE, H = b.h * TILE;
  px(g, X + 1, Y + 1, W - 2, H - 1, PAL.stoneLo); // basin wall + soft shadow below
  px(g, X + 1, Y + 1, W - 2, H - 5, PAL.stoneHi);
  px(g, X + 3, Y + 3, W - 6, H - 9, PAL.waterLo);
  px(g, X + 3, Y + 3, W - 6, H - 11, PAL.water);
  for (let i = 0; i < 6; i++) px(g, X + 5 + Math.floor(hash(i, b.x) * (W - 14)), Y + 5 + Math.floor(hash(b.y, i) * (H - 16)), 4, 1, PAL.waterHi);
  const cx = X + W / 2, cy = Y + H / 2 - 2;
  px(g, cx - 4, cy - 3, 8, 8, PAL.stoneLo); px(g, cx - 3, cy - 4, 6, 7, PAL.stone); px(g, cx - 3, cy - 4, 6, 1, PAL.stoneHi); // column
}

const DROPS = [[-6, -6], [-4, -10], [4, -10], [6, -6], [-7, -1], [7, -1]];
/** Animated water: a jet, falling drops and glints. `ph` steps 0..3 about three times a second. */
export function fountainFx(g, b, ph) {
  const X = b.x * TILE, Y = b.y * TILE, W = b.w * TILE, H = b.h * TILE;
  const cx = X + W / 2, cy = Y + H / 2 - 2;
  px(g, cx - 1, cy - 12 - (ph & 1) * 2, 2, 9 + (ph & 1) * 2, PAL.spray);
  for (let j = 0; j < DROPS.length; j++) {
    const [dx, dy] = DROPS[j], s = (j + ph) & 3;
    px(g, cx + dx + (s & 1), cy + dy + (s >> 1) * 2, 1, 2, PAL.spray);
  }
  for (let i = 0; i < 4; i++) {
    px(g, X + 5 + Math.floor(hash(i + ph * 4, b.x) * (W - 12)), Y + 5 + Math.floor(hash(b.y, i + ph * 3) * (H - 16)), 2, 1, PAL.spray);
  }
}

// ---------------------------------------------------------------- front layer
function awning(g, X, Y, tiles, main) {
  const W = tiles * TILE;
  for (let i = 0; i < W / 4; i++) {
    const c = i & 1 ? "#f4ead0" : main;
    px(g, X + i * 4, Y + 1, 4, 8, c);
    px(g, X + i * 4, Y + 9, 4, 2, c); // scalloped fringe
    px(g, X + i * 4 + 1, Y + 11, 2, 1, c);
  }
  px(g, X, Y, W, 1, PAL.outline);
  px(g, X, Y + 12, W, 2, "#00000022"); // shade on the paving
}

/** Drawn over characters so they walk behind canopies, awnings and lamp heads. */
export function drawFront(g, world) {
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++) {
    const ch = world.charAt(x, y), X = x * TILE, Y = y * TILE;
    if (ch === "T") {
      g.fillStyle = PAL.leafLo; g.beginPath(); g.arc(X + 8, Y - 2, 11, 0, Math.PI * 2); g.fill();
      g.fillStyle = PAL.leaf; g.beginPath(); g.arc(X + 7, Y - 4, 9, 0, Math.PI * 2); g.fill();
      g.fillStyle = PAL.leafHi; g.beginPath(); g.arc(X + 4, Y - 7, 4, 0, Math.PI * 2); g.fill();
    } else if (ch === "L") {
      px(g, X + 4, Y - 5, 8, 7, PAL.iron); px(g, X + 5, Y - 4, 6, 5, PAL.lamp); px(g, X + 5, Y - 4, 6, 1, "#ffffff88");
      px(g, X + 3, Y - 6, 10, 2, PAL.iron);
    } else if (ch === "d" && isFacade(world, x, y)) {
      const main = building(x).awning;
      if (main) awning(g, X - 2 * TILE, Y, 5, main);
      else { px(g, X - TILE, Y, 3 * TILE, 6, PAL.woodLo); px(g, X - TILE, Y, 3 * TILE, 2, PAL.woodHi); px(g, X - TILE, Y + 6, 3 * TILE, 2, "#00000022"); } // porch roof
    }
  }
}

// ---------------------------------------------------------------- night lights
/** One soft glow sprite, reused for every lamp. */
export function glowSprite() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 2, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,214,130,0.6)"); grad.addColorStop(1, "rgba(255,214,130,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return c;
}

/** Built once: lit rooms, lit shop windows and a halo round each lamp. Drawn after the night tint. */
export function drawLights(g, world, glow) {
  for (let y = 0; y < world.h; y++) for (let x = 0; x < world.w; x++) {
    const ch = world.charAt(x, y), X = x * TILE, Y = y * TILE;
    if (INTERIOR.includes(ch)) px(g, X, Y, TILE, TILE, "rgba(255,200,120,0.14)");
    else if (isWindow(world, x, y)) px(g, X + 3, Y + 5, 10, 7, "rgba(255,222,140,0.9)");
    else if (ch === "d" && isFacade(world, x, y)) px(g, X + 4, Y + 5, 8, 4, "rgba(255,222,140,0.9)");
    else if (ch === "L") g.drawImage(glow, X + 8 - 32, Y - 2 - 32);
  }
}
