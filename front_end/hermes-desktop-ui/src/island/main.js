// The island page's own code. Bundled into public/island/island.js by
// scripts/bundle-island.mjs: the page runs in a sandboxed (opaque-origin) iframe,
// where module imports are CORS requests that most servers would refuse.
import { ISLAND_MAP, parseMap } from "./engine/world.js";
import { Sim, TICK_MS } from "./engine/sim.js";
import { normalizeSession } from "./engine/agents.js";
import { applyEvent } from "./engine/events.js";
import { DEMO_SESSION } from "./examples/demo-session.js";
import { Renderer } from "./engine/render.js";
import { startIsland } from "./engine/stardew/stardew-app.js";
import { worldFromTbin } from "./engine/stardew/stardew-world.js";
import { ArtError, loadArtScene } from "./engine/stardew/byo.js";
import { hudTheme } from "./engine/stardew/hud.js";

const params = new URLSearchParams(location.search);
const world = parseMap(ISLAND_MAP);
// Session agents come from the Harvis host page (postMessage) — the demo session is only a fallback.
const sim = new Sim({ world, wander: true, agents: normalizeSession(DEMO_SESSION, world), weather: params.get("weather") ?? "sun" });
if (params.get("t")) sim.setTime(params.get("t"));
const canvas = document.getElementById("c");
const zoom = Number(params.get("zoom") ?? (innerWidth > 1500 ? 3 : 2));
const r = new Renderer(canvas, sim, { zoom });
const art = { state: "builtin", message: "" }; // what the host last heard about the user's own game art
let custom = null; // {app, canvas, source} while the island is drawn with the user's own game art
let artSeq = 0; // bumped by every pick and clear, so a slow load that was superseded can tell
window.__island = { sim, r, art, get custom() { return custom; } }; // debug / test hook

const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const log = (html) => { const d = document.createElement("div"); d.innerHTML = `<span>${sim.timeString()}</span> ${html}`; $("log").prepend(d); while ($("log").children.length > 60) $("log").lastChild.remove(); };

const nm = (id) => esc(sim.agent(id)?.name ?? id);
sim.on("chatStart", (e) => log(`<b>${nm(e.a)}</b> ↔ <b>${nm(e.b)}</b> · ${esc(e.topic)}`));
sim.on("bubble", (e) => log(`<b>${nm(e.id)}</b>: “${esc(e.text)}”`));
sim.on("sleep", (e) => log(`<b>${nm(e.id)}</b> went home`));
sim.on("wake", (e) => log(`<b>${nm(e.id)}</b> is up`));
sim.on("activity", (e) => e.activity && log(`<b>${nm(e.id)}</b> started: ${esc(e.activity.label)}`));

// ---- Harvis host bridge ----
// Host -> island: {type:"island:session", session} replaces the agents; {type:"island:event", event} drives them.
// Island -> host: {type:"island:select", agentId} when a resident is clicked (open that agent's chat).
// Host -> island: {type:"island:stardew", files:{relpath: ArrayBuffer|Blob}} switches to the user's own game art,
// {type:"island:stardew-clear"} goes back to the built-in art. Island -> host: {type:"island:stardew-status", state, message}.
const HOST_ORIGIN = params.get("host"); // e.g. https://harvis.example — required to accept messages
const toHost = (message) => { if (HOST_ORIGIN && window.parent !== window) window.parent.postMessage(message, HOST_ORIGIN); };
let currentSession = DEMO_SESSION;
const onBadAgent = (err) => console.warn("island: bad agent", err.message);
function replaceAgents(s, w) {
  for (const a of [...s.agents]) s.removeAgent(a.id);
  for (const a of normalizeSession(currentSession, w, { onError: onBadAgent })) s.addAgent(a);
}
// Host -> island: {type:"island:pause"} stops ticking and drawing; {type:"island:resume"} redraws;
// {type:"island:lowfx", on} thins the effects and drops the draw rate (mirrors the Stardew build's perf governor).
let paused = false, lowFx = false;
function setPaused(on) {
  paused = on;
  if (custom) on ? custom.app.pause() : custom.app.resume();
  else if (!on) { last = performance.now(); r.draw(true); }
}
function setLowFx(on) { lowFx = on; r.lowFx = on; r.lastSig = ""; custom?.app.setLowFx(on); }
// Host -> island: {type:"island:theme", mode, colors} is the app's own look; the HUD and this page wear it.
let theme = hudTheme(null);
function setTheme(msg) {
  theme = hudTheme(msg);
  const st = document.documentElement.style;
  for (const [k, v] of [["--bg", theme.panel], ["--panel", theme.raised], ["--line", theme.line], ["--fg", theme.fg], ["--muted", theme.muted], ["--accent", theme.accent], ["--accent-fg", theme.accentFg]]) st.setProperty(k, v);
  document.documentElement.dataset.mode = theme.mode;
  custom?.app.r.setTheme(theme);
}

// ---- the user's own game art (optional; the built-in renderer stays the default) ----
function reportArt(state, message = "") {
  Object.assign(art, { state, message, custom: !!custom });
  toHost({ type: "island:stardew-status", state, message, custom: !!custom });
  if (message) log(esc(message));
}
function teardown(c) { c.app.dispose(); c.canvas.remove(); c.source.dispose(); }
async function useArt(data) {
  const seq = ++artSeq;
  reportArt("loading");
  let scene, canvas, app;
  try {
    scene = await loadArtScene(data);
    if (seq !== artSeq) { scene.source.dispose(); return; } // cleared or replaced while loading
    const w = worldFromTbin(scene.mapData.map, { places: scene.preset.places, homeDoors: scene.preset.homeDoors });
    canvas = document.createElement("canvas");
    canvas.id = "sc";
    document.body.append(canvas);
    document.body.classList.add("byo"); // before startIsland: the renderer sizes itself from the laid-out canvas
    app = await startIsland({
      canvas, world: w, pack: scene.pack, mapData: scene.mapData, preset: scene.preset,
      agents: normalizeSession(currentSession, w, { onError: onBadAgent }),
      opts: { time: sim.timeString(), weather: sim.weather, lowPower: lowFx || undefined },
      onSelect: (id) => toHost({ type: "island:select", agentId: id }),
    });
    app.r.setTheme(theme);
    if (paused) app.pause();
    const prev = custom;
    custom = { app, canvas, source: scene.source };
    if (prev) teardown(prev);
    reportArt("custom");
  } catch (e) {
    app?.dispose(); canvas?.remove(); scene?.source.dispose();
    if (!custom) document.body.classList.remove("byo");
    if (!(e instanceof ArtError)) console.warn("island: game art", e);
    reportArt("error", e instanceof ArtError ? e.message : "Couldn't load those game files.");
  }
}
function clearArt() {
  artSeq++;
  if (custom) {
    teardown(custom);
    custom = null;
    document.body.classList.remove("byo");
    replaceAgents(sim, world); // the built-in island missed every session change while hidden
    last = performance.now();
    r.buildStatic(); r.draw(true); renderAgents();
  }
  reportArt("builtin");
}
window.addEventListener("message", (e) => {
  if (!HOST_ORIGIN || e.origin !== HOST_ORIGIN || typeof e.data !== "object" || !e.data) return;
  if (e.data.type === "island:pause") setPaused(true);
  else if (e.data.type === "island:resume") setPaused(false);
  else if (e.data.type === "island:lowfx") setLowFx(!!e.data.on);
  else if (e.data.type === "island:theme") setTheme(e.data);
  else if (e.data.type === "island:session") {
    currentSession = e.data.session;
    if (custom) { replaceAgents(custom.app.sim, custom.app.sim.world); custom.app.r.lastSig = ""; }
    else { replaceAgents(sim, world); r.buildStatic(); renderAgents(); }
  } else if (e.data.type === "island:event") applyEvent(custom ? custom.app.sim : sim, e.data.event);
  else if (e.data.type === "island:stardew") void useArt(e.data);
  else if (e.data.type === "island:stardew-clear") clearArt();
});
const selectAgent = (id) => {
  r.selected = id; renderAgents();
  toHost({ type: "island:select", agentId: id });
};
window.__islandEvent = (ev) => applyEvent(custom ? custom.app.sim : sim, ev); // local testing

// sidebar residents
function renderAgents() {
  $("agents").innerHTML = sim.agents.map((a) => {
    const st = a.sleeping ? "asleep" : a.chat ? `chatting w/ ${a.chat.with}` : a.status;
    return `<div class="agent ${r.selected === a.id ? "sel" : ""}" data-id="${a.id}">
      <span class="dot" style="background:${a.color}"></span><span>${esc(a.name)}</span>
      <span class="st">${esc(a.activity ? a.activity.label : st)}${a.meta?.model ? " · " + esc(a.meta.model) : ""}</span></div>`;
  }).join("");
}
$("agents").addEventListener("click", (e) => { const el = e.target.closest(".agent"); if (el) selectAgent(el.dataset.id); });

canvas.addEventListener("click", (e) => {
  const t = r.tileAt(e.clientX, e.clientY);
  const hit = r.agentAt(t);
  if (hit) { selectAgent(hit.id); return; }
  if (r.selected && world.isWalkable(t.x, t.y)) { sim.orderMove(r.selected, t); log(`sent <b>${nm(r.selected)}</b> to ${t.x},${t.y}`); }
});

let speed = Number(params.get("speed") ?? 1);
for (const x of document.getElementById("speed").children) x.classList.toggle("on", Number(x.dataset.speed) === speed);
$("speed").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  speed = Number(b.dataset.speed);
  for (const x of $("speed").children) x.classList.toggle("on", x === b);
});
document.querySelectorAll("[data-time]").forEach((b) => b.addEventListener("click", () => { sim.setTime(b.dataset.time); log(`time → ${b.dataset.time}`); }));
$("rain").addEventListener("click", () => { sim.weather = sim.weather === "rain" ? "sun" : "rain"; $("rain").classList.toggle("on", sim.weather === "rain"); for (const a of sim.agents) sim.dressFor(a); });
$("emotes").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b || !r.selected) return;
  if (b.id === "say") sim.say(sim.agent(r.selected), "Hi everyone!");
  else sim.emote(r.selected, b.dataset.emote);
});

// ---- loop: fixed 60 Hz sim step, draw only when the picture changed ----
let acc = 0, last = performance.now(), frames = 0, drawsAtLastSec = 0, secT = last, simMs = 0;
let gateAcc = 0;
function frame(now) {
  if (paused || custom) { last = now; requestAnimationFrame(frame); return; }
  const dt = Math.min(250, now - last); last = now;
  acc += dt * speed;
  const t0 = performance.now();
  let n = 0;
  while (acc >= TICK_MS && n < 600) { sim.tick(); acc -= TICK_MS; n++; }
  if (n === 600) acc = 0;
  simMs += performance.now() - t0;
  gateAcc += dt;
  if (!lowFx || gateAcc >= 80) { gateAcc = 0; r.draw(); }
  frames++;
  if (now - secT >= 1000) {
    const drawn = r.draws - drawsAtLastSec; drawsAtLastSec = r.draws;
    $("perf").textContent = `${drawn} draws/s of ${frames} frames · sim ${(simMs / frames).toFixed(2)} ms/frame · tick ${sim.ticks}`;
    frames = 0; simMs = 0; secT = now;
    renderAgents();
  }
  $("clock").textContent = sim.timeString();
  $("weather").textContent = sim.weather;
  requestAnimationFrame(frame);
}

// Hidden tab: rAF stops on its own. On return, fast-forward the missed time (capped at 2 game-hours)
// instead of animating it — like Stardew placing NPCs at their destination when nobody is watching.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { window.__hiddenAt = performance.now(); return; }
  const away = performance.now() - (window.__hiddenAt ?? performance.now());
  const ticks = paused || custom ? 0 : Math.min(Math.floor((away * speed) / TICK_MS), 60 * 7 * 12);
  for (let i = 0; i < ticks; i++) sim.tick();
  last = performance.now();
  if (!custom) r.draw(true);
});

renderAgents();
r.draw(true);
requestAnimationFrame(frame);
