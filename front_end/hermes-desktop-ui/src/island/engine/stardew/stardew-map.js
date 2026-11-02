// Tile map renderer: draws a parsed tBIN map with its tilesheets, using art from the user's own
// game files. Layer order: Back, Back2, Buildings, Paths(hidden), [characters], Front, AlwaysFront.
//
// Nothing here fetches. Files come from an "asset source" (see byo.js): the host page posts the
// user's imported files into the island, which keeps them in memory.
//   source.buffer(path) -> ArrayBuffer | undefined      (a .tbin map)
//   source.image(path)  -> Promise<CanvasImageSource>   (a .png; rejects when the file is missing)
import { parseTbin } from "./tbin.js";

export async function loadImage(src) {
  const img = new Image();
  img.src = src;
  await img.decode();
  return img;
}

export async function loadStardewMap(source, name) {
  const buf = source.buffer(`Maps/${name}.tbin`);
  if (!buf) throw new Error(`Map ${name} is not in your imported files`);
  const map = parseTbin(buf);
  const sheets = {};
  await Promise.all(map.tilesheets.map(async (s) => {
    sheets[s.id] = { ...s, img: await source.image(`Maps/${s.image.replace(/\\/g, "/")}.png`) };
  }));
  return { map, sheets, name };
}

export function drawTile(g, sheets, tile, dx, dy, ms = 0) {
  if (!tile) return;
  let t = tile;
  if (tile.frames) t = tile.frames[Math.floor(ms / Math.max(1, tile.interval)) % tile.frames.length];
  const s = sheets[t.sheet];
  if (!s) return;
  const tw = s.tileSize.w, th = s.tileSize.h, cols = s.sheetSize.w;
  const sx = (t.index % cols) * tw, sy = Math.floor(t.index / cols) * th;
  g.drawImage(s.img, sx, sy, tw, th, dx, dy, tw, th);
}

/** Draw the named layers of the whole map into a canvas context (1 px per map pixel). */
export function drawLayers(g, { map, sheets }, layerIds, ms = 0) {
  for (const id of layerIds) {
    const L = map.layers.find((l) => l.id === id);
    if (!L) continue;
    const { w, h } = L.size, tw = L.tileSize.w, th = L.tileSize.h;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) drawTile(g, sheets, L.tiles[y * w + x], x * tw, y * th, ms);
  }
}

export const BELOW = ["Back", "Back2", "Buildings"];
export const ABOVE = ["Front", "AlwaysFront"];
