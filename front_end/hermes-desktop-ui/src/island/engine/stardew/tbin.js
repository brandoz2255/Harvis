// xTile tBIN10 map parser (format used by Stardew maps). Works in browser and Node.
// Layout: "tBIN10", id, description, properties, tilesheets[], layers[]; layer tiles are
// row-run-length encoded: 'N' nulls, 'T' set tilesheet, 'S' static tile, 'A' animated tile.

// Real Stardew maps are at most 130x110 tiles; these bounds only stop a crafted file from allocating gigabytes.
export const MAX_LAYER_SIDE = 1000;
export const MAX_LAYER_TILES = 1_000_000;
// The per-layer cap alone still lets a few hundred KB of run-length rows ask for hundreds of layers of that size.
// The largest real map has 8 layers, 6 tilesheets and about 114k tiles in total.
export const MAX_MAP_TILES = 4_000_000;
export const MAX_LAYERS = 32;
export const MAX_TILESHEETS = 64;

export function parseTbin(buf) {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  const td = new TextDecoder();
  let p = 0;
  const need = (n) => { if (p + n > u8.length) throw new Error(`tBIN map is truncated (needs ${n} bytes at ${p}, file has ${u8.length})`); };
  const i32 = () => { need(4); const v = dv.getInt32(p, true); p += 4; return v; };
  const u8r = () => { need(1); return u8[p++]; };
  const f32 = () => { need(4); const v = dv.getFloat32(p, true); p += 4; return v; };
  const str = () => {
    const n = i32();
    if (n < 0 || n > u8.length - p) throw new Error(`tBIN string length ${n} is out of range at ${p - 4}`);
    const s = td.decode(u8.subarray(p, p + n)); p += n; return s;
  };
  const size = () => ({ w: i32(), h: i32() });
  const props = () => {
    const n = i32(), o = {};
    for (let i = 0; i < n; i++) {
      const k = str(), t = u8r();
      o[k] = t === 0 ? u8r() !== 0 : t === 1 ? i32() : t === 2 ? f32() : str();
    }
    return o;
  };

  const magic = td.decode(u8.subarray(0, 6)); p = 6;
  if (magic !== "tBIN10") throw new Error(`not a tBIN10 map (${magic})`);
  const map = { id: str(), description: str(), properties: props(), tilesheets: [], layers: [] };

  const nSheets = i32();
  if (nSheets < 0 || nSheets > MAX_TILESHEETS) throw new Error(`tBIN tilesheet count ${nSheets} is out of range`);
  for (let i = 0; i < nSheets; i++) {
    map.tilesheets.push({
      id: str(), description: str(), image: str(),
      sheetSize: size(), tileSize: size(), margin: size(), spacing: size(), properties: props(),
    });
  }

  const nLayers = i32();
  if (nLayers < 0 || nLayers > MAX_LAYERS) throw new Error(`tBIN layer count ${nLayers} is out of range`);
  let totalTiles = 0;
  for (let i = 0; i < nLayers; i++) {
    const layer = { id: str(), visible: u8r() !== 0, description: str(), size: size(), tileSize: size(), properties: props() };
    const W = layer.size.w, H = layer.size.h;
    if (W < 0 || H < 0 || W > MAX_LAYER_SIDE || H > MAX_LAYER_SIDE || W * H > MAX_LAYER_TILES) {
      throw new Error(`tBIN layer ${layer.id} size ${W}x${H} is out of range`);
    }
    totalTiles += W * H;
    if (totalTiles > MAX_MAP_TILES) throw new Error(`tBIN map has more than ${MAX_MAP_TILES} tiles across its layers (layer ${layer.id}, ${W}x${H}) and is out of range`);
    // tiles[y*W+x] = null | { sheet, index, props? } | { sheet, frames:[{sheet,index}], interval, props? }
    layer.tiles = new Array(W * H).fill(null);
    let sheet = null;
    for (let y = 0; y < H; y++) {
      let x = 0;
      while (x < W) {
        const c = String.fromCharCode(u8r());
        if (c === "N") {
          const run = i32();
          if (run < 0 || run > W - x) throw new Error(`bad null run ${run} at ${p - 4} layer ${layer.id} y=${y} x=${x}`);
          x += run;
        }
        else if (c === "T") { sheet = str(); }
        else if (c === "S") {
          const index = i32(); u8r(); // blend mode
          const pr = props();
          layer.tiles[y * W + x] = Object.keys(pr).length ? { sheet, index, props: pr } : { sheet, index };
          x++;
        } else if (c === "A") {
          const interval = i32(), count = i32();
          if (count < 1) throw new Error(`bad animation frame count ${count} at ${p - 4}`);
          const frames = [];
          let fs = sheet;
          while (frames.length < count) {
            const fc = String.fromCharCode(u8r());
            if (fc === "T") fs = str();
            else if (fc === "S") { const index = i32(); u8r(); props(); frames.push({ sheet: fs, index }); }
            else throw new Error(`bad anim frame tag ${fc} at ${p}`);
          }
          const pr = props();
          layer.tiles[y * W + x] = { sheet: frames[0].sheet, index: frames[0].index, frames, interval, ...(Object.keys(pr).length ? { props: pr } : {}) };
          x++;
        } else throw new Error(`bad tile tag '${c}' (0x${c.charCodeAt(0).toString(16)}) at ${p - 1} layer ${layer.id} y=${y} x=${x}`);
      }
    }
    map.layers.push(layer);
  }
  return map;
}

/** Convenience: layer by id. */
export const layerOf = (map, id) => map.layers.find((l) => l.id === id);
