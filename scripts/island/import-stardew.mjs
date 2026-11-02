#!/usr/bin/env node
// import-stardew.mjs — turns YOUR OWN copy of the game into the art folder the Harvis island can use.
//
//   cd scripts/island && npm install        (once; installs the xnb reader, LGPL-3.0)
//   node import-stardew.mjs [--out <dir>] [path/to/Stardew Valley]
//
// WARNING: the output is your own game files. It is written outside this repo
// (default ~/.local/share/harvis/stardew-assets) and must never be committed, uploaded or shared.
// Harvis ships and serves no game files. After running this, open the island in Harvis, choose
// "Use my game art" and pick the output folder: the files stay in your browser.
//
// Only .png (sprite sheets) and .tbin (maps) are written; the island ignores everything else.
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, parse, resolve } from "node:path";
import { parseTbin } from "../../front_end/hermes-desktop-ui/src/island/engine/stardew/tbin.js";

let xnb;
try {
  xnb = await import("xnb/dist/xnb.module.js");
} catch {
  console.error("The xnb reader is not installed. Run: cd scripts/island && npm install");
  process.exit(1);
}
const { bufferToXnb, xnbDataToContent } = xnb;

const args = process.argv.slice(2);
const outIdx = args.indexOf("--out");
const OUT = resolve(outIdx >= 0 ? args.splice(outIdx, 2)[1] ?? "" : join(homedir(), ".local", "share", "harvis", "stardew-assets"));
const home = homedir();
const GAME_DEFAULTS = [
  join(home, ".local/share/Steam/steamapps/common/Stardew Valley"),
  join(home, "Library/Application Support/Steam/steamapps/common/Stardew Valley/Contents/MacOS"),
  "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Stardew Valley",
];
const GAME = args[0] ?? GAME_DEFAULTS.find((d) => existsSync(join(d, "Content"))) ?? GAME_DEFAULTS[0];
const CONTENT = join(GAME, "Content");
if (!existsSync(CONTENT)) {
  console.error(`No Content folder at ${CONTENT}. Pass the game's folder as the last argument.`);
  process.exit(1);
}

// These are copyrighted game files: refuse to put them anywhere a git commit could pick them up.
// A checkout has .git/HEAD, or a .git file (worktrees, submodules); a bare leftover .git folder is not one.
const isCheckout = (d) => existsSync(join(d, ".git", "HEAD")) || (existsSync(join(d, ".git")) && statSync(join(d, ".git")).isFile());
function insideGitCheckout(dir) {
  for (let d = dir; ; d = dirname(d)) {
    if (isCheckout(d)) return d;
    if (d === parse(d).root) return null;
  }
}
const checkout = insideGitCheckout(OUT);
if (checkout) {
  console.error(`Refusing to write game files inside a git checkout (${checkout}). Choose --out outside it.`);
  process.exit(1);
}

const list = (dir, re) => readdirSync(join(CONTENT, dir)).filter((f) => re.test(f)).map((f) => `${dir}/${f}`);
const want = [
  ...list("Characters", /^[A-Z][A-Za-z]+\.xnb$/),
  ...list("Portraits", /^[A-Z][A-Za-z]+\.xnb$/),
  "Animals/cat.xnb", "Animals/dog.xnb",
  "TileSheets/emotes.xnb",
  "LooseSprites/Cursors.xnb", "Maps/MenuTiles.xnb", "LooseSprites/font_bold.xnb",
  "Maps/Town.xnb",
  ...list("Maps", /^Island_(S|N|E|W|SE|Resort|Shrine|Hut)\.xnb$/i),
];

const log = [];
async function exportOne(rel) {
  const buf = readFileSync(join(CONTENT, rel));
  const quiet = console.log; console.log = () => {}; // the reader is chatty
  let c;
  try { c = xnbDataToContent(bufferToXnb(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength))); }
  finally { console.log = quiet; }
  const ext = c.type === "Texture2D" ? ".png" : c.type === "TBin" ? ".tbin" : null;
  if (!ext || !(c.content instanceof Blob)) { log.push(`${rel} skipped (${c.type})`); return c.type; }
  const target = join(OUT, rel.replace(/\.xnb$/, ext));
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, Buffer.from(await c.content.arrayBuffer()));
  log.push(`${rel} -> ${c.type}`);
  return c.type;
}

mkdirSync(OUT, { recursive: true });
const queue = [...new Set(want)];
const tilesheetsSeen = new Set();
let ok = 0, fail = 0;
while (queue.length) {
  const rel = queue.shift();
  try {
    const type = await exportOne(rel);
    ok++;
    // Maps name their tilesheets; pull those in too.
    if (type === "TBin") {
      const tb = parseTbin(readFileSync(join(OUT, rel.replace(/\.xnb$/, ".tbin"))));
      for (const sh of tb.tilesheets) {
        const p = `Maps/${sh.image.replace(/\\/g, "/")}.xnb`;
        if (!existsSync(join(CONTENT, p))) log.push(`missing tilesheet ${p}`);
        else if (!tilesheetsSeen.has(p)) { tilesheetsSeen.add(p); queue.push(p); }
      }
    }
  } catch (e) { fail++; log.push(`${rel} FAILED ${e.message}`); }
}
writeFileSync(
  join(OUT, "IMPORT_LOG.txt"),
  `These are your own game files. Do not commit, upload or share them.\nsource: ${GAME}\n${new Date().toISOString()}\n\n${log.join("\n")}\n`,
);
console.log(`imported ${ok} assets (${fail} failed) into ${OUT}`);
console.log("Do not commit or share this folder. In Harvis: island -> Use my game art -> pick it.");
