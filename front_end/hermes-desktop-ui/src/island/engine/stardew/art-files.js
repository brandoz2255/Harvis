// Message shape and size limits for "bring your own game art".
//
// The user imports their own game files on their machine (scripts/island/import-stardew.mjs),
// picks the output folder in the Harvis host UI, and the host page posts the files into the
// island: {type:"island:stardew", files:{"Maps/Town.tbin": ArrayBuffer, ...}}.
// Harvis ships none of these files. This module has no dependencies so the host page can share
// the exact same limits and path rule the island enforces.

const MiB = 1024 * 1024;

export const LIMITS = Object.freeze({
  maxFiles: 1000,
  maxPathLength: 160,
  maxFileBytes: 8 * MiB,
  maxTotalBytes: 64 * MiB,
});

/** A file every import has; the host uses it to find where the game folders start inside a picked folder. */
export const ANCHOR_FILE = "LooseSprites/Cursors.png";

export class ArtError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "ArtError";
  }
}

// Folders of letters, digits, _ - . and spaces; a segment never starts with "." so ".." cannot occur.
const SEGMENT = "[A-Za-z0-9_-][A-Za-z0-9_. -]*";
const PATH_RE = new RegExp(`^${SEGMENT}(?:/${SEGMENT})*\\.(?:png|tbin)$`);

/** A relative path the island will keep: only .png and .tbin, no traversal, no absolute paths. */
export const isArtPath = (path) => typeof path === "string" && path.length <= LIMITS.maxPathLength && PATH_RE.test(path);

const tag = (v) => Object.prototype.toString.call(v);
export const isArrayBuffer = (v) => tag(v) === "[object ArrayBuffer]";
export const isBlob = (v) => tag(v) === "[object Blob]";

/**
 * Validate an island:stardew message without reading any file body.
 * Returns [{path, value, size}] (value is an ArrayBuffer or a Blob) or throws an ArtError
 * whose message is safe to show the user.
 */
export function readArtFiles(data) {
  const files = data?.files;
  if (!files || typeof files !== "object" || tag(files) !== "[object Object]") throw new ArtError("The game files arrived in an unexpected shape.");
  const paths = Object.keys(files);
  if (paths.length === 0) throw new ArtError("No game files were selected.");
  if (paths.length > LIMITS.maxFiles) throw new ArtError(`Too many files (${paths.length}; the limit is ${LIMITS.maxFiles}).`);

  const entries = [];
  let total = 0;
  for (const path of paths) {
    if (!isArtPath(path)) throw new ArtError(`Unexpected file name: ${String(path).slice(0, 60)}`);
    const value = files[path];
    const size = isArrayBuffer(value) ? value.byteLength : isBlob(value) ? value.size : -1;
    if (size < 0) throw new ArtError(`${path} is not file data.`);
    if (size === 0) throw new ArtError(`${path} is empty.`);
    if (size > LIMITS.maxFileBytes) throw new ArtError(`${path} is too large (over ${LIMITS.maxFileBytes / MiB} MB).`);
    total += size;
    if (total > LIMITS.maxTotalBytes) throw new ArtError(`The files add up to more than ${LIMITS.maxTotalBytes / MiB} MB.`);
    entries.push({ path, value, size });
  }
  return entries;
}
