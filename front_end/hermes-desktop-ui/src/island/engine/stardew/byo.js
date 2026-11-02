// Bring-your-own game art: turns the files the host page posted into a scene the tile-art
// renderer can draw. Everything stays in memory inside the sandboxed island: nothing is
// fetched, uploaded or written, and Harvis ships none of these files.
import { ANCHOR_FILE, ArtError, isBlob, readArtFiles } from "./art-files.js";
import { loadImage } from "./stardew-map.js";
import { loadStardewScene } from "./stardew-ui.js";
import { parseTbin } from "./tbin.js";
import { ISLAND_S } from "./maps/island-s.js";
import { TOWN } from "./maps/town.js";

export { ArtError, LIMITS } from "./art-files.js";
// Presets a caller can pass in place of the default (Island_S).
export { ISLAND_S, TOWN };

// Always drawn by the renderer's HUD, whatever the map.
const BASE_FILES = [ANCHOR_FILE, "Maps/MenuTiles.png", "TileSheets/emotes.png", "LooseSprites/font_bold.png"];

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const TBIN_MAGIC = [0x74, 0x42, 0x49, 0x4e, 0x31, 0x30]; // "tBIN10"
const hasMagic = (buf, magic) => buf.byteLength >= magic.length && magic.every((b, i) => new Uint8Array(buf, 0, magic.length)[i] === b);

export const requiredFiles = (preset = TOWN) => [...BASE_FILES, `Maps/${preset.map}.tbin`];

/** Read every file body into an ArrayBuffer and check it starts like a PNG or a tBIN map. */
export async function materialize(entries) {
  const files = new Map();
  for (const { path, value } of entries) {
    const buf = isBlob(value) ? await value.arrayBuffer() : value;
    if (!hasMagic(buf, path.endsWith(".png") ? PNG_MAGIC : TBIN_MAGIC)) throw new ArtError(`${path} is not a ${path.endsWith(".png") ? "PNG image" : "map file"}.`);
    files.set(path, buf);
  }
  return files;
}

/** Required files (and the map's own tilesheets) that the posted folder does not contain. */
export function missingFiles(files, preset = TOWN) {
  const missing = requiredFiles(preset).filter((p) => !files.has(p));
  const mapPath = `Maps/${preset.map}.tbin`;
  if (files.has(mapPath)) {
    let map;
    try { map = parseTbin(files.get(mapPath)); } catch (e) { throw new ArtError(`${mapPath} could not be read.`, { cause: e }); }
    for (const s of map.tilesheets) {
      const p = `Maps/${s.image.replace(/\\/g, "/")}.png`;
      if (!files.has(p) && !missing.includes(p)) missing.push(p);
    }
  }
  return missing;
}

export function describeMissing(missing) {
  const shown = missing.slice(0, 3).join(", ");
  return `Missing from the folder you picked: ${shown}${missing.length > 3 ? ` (+${missing.length - 3} more)` : ""}. Run the importer again.`;
}

async function imageFromBuffer(buf) {
  const url = URL.createObjectURL(new Blob([buf], { type: "image/png" }));
  try { return await loadImage(url); } finally { URL.revokeObjectURL(url); }
}

/** The asset source stardew-map.js reads from. Images are decoded from blob: URLs made in this frame. */
export function createAssetSource(files, { makeImage = imageFromBuffer } = {}) {
  const images = new Map();
  let disposed = false;
  return {
    has: (path) => files.has(path),
    buffer: (path) => (disposed ? undefined : files.get(path)),
    image(path) {
      if (disposed || !path.endsWith(".png") || !files.has(path)) return Promise.reject(new Error(`${path} is not available`));
      if (!images.has(path)) images.set(path, makeImage(files.get(path)));
      return images.get(path);
    },
    dispose() { disposed = true; images.clear(); files.clear(); },
  };
}

/**
 * Validate an island:stardew message and build the scene, or throw an ArtError with a short
 * plain message. The caller keeps the default renderer when this throws.
 */
export async function loadArtScene(data, preset = TOWN, { makeImage } = {}) {
  const files = await materialize(readArtFiles(data));
  const missing = missingFiles(files, preset);
  if (missing.length) throw new ArtError(describeMissing(missing));
  const source = createAssetSource(files, { makeImage });
  try {
    const { pack, mapData } = await loadStardewScene(source, preset);
    return { source, pack, mapData, preset };
  } catch (e) {
    source.dispose();
    throw new ArtError("Those files could not be read as game art. Run the importer again.", { cause: e });
  }
}
