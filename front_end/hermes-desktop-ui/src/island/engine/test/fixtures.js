// Synthetic stand-ins for imported game files: a tiny tBIN10 map and PNG-shaped byte strings.
// They contain no game data, so the tests that use them run anywhere.

class Writer {
  constructor() { this.bytes = []; }
  u8(v) { this.bytes.push(v & 255); }
  i32(v) { for (let i = 0; i < 4; i++) this.bytes.push((v >>> (8 * i)) & 255); }
  raw(s) { for (const ch of s) this.bytes.push(ch.charCodeAt(0)); }
  str(s) { this.i32(s.length); this.raw(s); }
  size(w, h) { this.i32(w); this.i32(h); }
  props(o = {}) {
    const entries = Object.entries(o);
    this.i32(entries.length);
    for (const [k, v] of entries) { this.str(k); this.u8(3); this.str(String(v)); }
  }
}

/**
 * layers: [{id, w, h, tiles}] with tiles[y*w+x] = tile index in the sheet, or -1 for no tile.
 * sheets: [{id, image, props}]. Every tile uses the first sheet.
 */
export function buildTbin({ sheets, layers }) {
  const w = new Writer();
  w.raw("tBIN10"); w.str("fixture"); w.str(""); w.props();
  w.i32(sheets.length);
  for (const s of sheets) {
    w.str(s.id); w.str(""); w.str(s.image); w.size(4, 4); w.size(16, 16); w.size(0, 0); w.size(0, 0); w.props(s.props);
  }
  w.i32(layers.length);
  for (const L of layers) {
    w.str(L.id); w.u8(1); w.str(""); w.size(L.w, L.h); w.size(16, 16); w.props();
    for (let y = 0; y < L.h; y++) {
      let x = 0;
      while (x < L.w) {
        if (L.tiles[y * L.w + x] < 0) {
          let n = 0;
          while (x + n < L.w && L.tiles[y * L.w + x + n] < 0) n++;
          w.u8("N".charCodeAt(0)); w.i32(n); x += n;
        } else {
          w.u8("T".charCodeAt(0)); w.str(sheets[0].id);
          w.u8("S".charCodeAt(0)); w.i32(L.tiles[y * L.w + x]); w.u8(0); w.props();
          x++;
        }
      }
    }
  }
  return Uint8Array.from(w.bytes).buffer;
}

/** A w x h map: water at (0,0), a wall at (3,1), everything else walkable ground. */
export function tinyMap(W = 6, H = 4) {
  const back = new Array(W * H).fill(0); back[0] = 1;
  const bld = new Array(W * H).fill(-1); bld[1 * W + 3] = 2;
  return buildTbin({
    sheets: [{ id: "ground", image: "tiny_sheet", props: { "@TileIndex@1@Water": "T" } }],
    layers: [
      { id: "Back", w: W, h: H, tiles: back },
      { id: "Buildings", w: W, h: H, tiles: bld },
      { id: "Front", w: W, h: H, tiles: new Array(W * H).fill(-1) },
    ],
  });
}

export const TINY_PRESET = {
  map: "Tiny",
  places: { plaza: { x: 1, y: 1 }, work: { x: 4, y: 2 } },
  homeDoors: [{ x: 1, y: 0 }],
  view: { x: 0, y: 0, w: 6, h: 4 },
};

/** Bytes that start like a PNG (all the island checks before decoding). */
export function fakePng(extra = 4) {
  const u = new Uint8Array(8 + extra);
  u.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return u.buffer;
}

/** Everything the island needs for a map called `map`, as the host would post it. */
export function tinyFiles(map = "Tiny", w = 6, h = 4) {
  return {
    "LooseSprites/Cursors.png": fakePng(),
    "Maps/MenuTiles.png": fakePng(),
    "TileSheets/emotes.png": fakePng(),
    "LooseSprites/font_bold.png": fakePng(),
    [`Maps/${map}.tbin`]: tinyMap(w, h),
    "Maps/tiny_sheet.png": fakePng(),
  };
}
