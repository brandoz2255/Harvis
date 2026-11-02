// Scoped in-page island for trusted hosts (the Harvis React app). Unlike the standalone
// page (main.js, bundled into public/island/), this mounts inside a caller-owned element:
// every DOM lookup is scoped to that root, it sets NO window globals, it installs no
// message listener, and dispose() tears down the loop, listeners and custom art so an
// account switch leaves nothing of the previous account running.
//
// Because the island shares the app's own origin and process, the host hands over
// account bots and the user's own game art by direct calls — there is no cross-context
// channel to authenticate and none of the opaque-iframe WindowProxy risks apply.
import { ISLAND_MAP, parseMap } from "./engine/world.js";
import { Sim, TICK_MS } from "./engine/sim.js";
import { normalizeSession } from "./engine/agents.js";
import { applyEvent } from "./engine/events.js";
import { Renderer } from "./engine/render.js";
import { startIsland } from "./engine/stardew/stardew-app.js";
import { worldFromTbin } from "./engine/stardew/stardew-world.js";
import { ArtError, loadArtScene } from "./engine/stardew/byo.js";
import { hudTheme } from "./engine/stardew/hud.js";

// All rules sit under .hi-root so the island's look cannot leak into the app (nor the
// app's into it beyond inheritance). One <style> per mount, removed by dispose().
const CSS = `
.hi-root { --bg: #0d1117; --panel: #161b22; --line: #30363d; --fg: #e6edf3; --muted: #7d8590; --accent: #4a84fe; --accent-fg: #161616;
  position: absolute; inset: 0; background: var(--bg); color: var(--fg);
  font: 13px/1.4 "Segoe UI", -apple-system, BlinkMacSystemFont, system-ui, sans-serif; display: flex; overflow: hidden; }
.hi-root.island-faded { background: transparent; }
.hi-root.island-faded .hi-aside { display: none; }
.hi-root.island-faded .hi-stage { padding: 0; }
.hi-root * { box-sizing: border-box; }
.hi-stage { flex: 1; display: grid; place-items: center; padding: 16px; overflow: auto; }
.hi-canvas { image-rendering: pixelated; border: 2px solid var(--line); border-radius: 6px; cursor: crosshair; max-width: 100%; }
.hi-aside { width: 300px; background: var(--panel); border-left: 1px solid var(--line); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.hi-aside h1 { font-size: 14px; margin: 0; letter-spacing: .5px; }
.hi-clock { font: 600 28px/1 ui-monospace, "JetBrains Mono", monospace; color: var(--fg); }
.hi-row { display: flex; gap: 6px; flex-wrap: wrap; }
.hi-root button { background: color-mix(in srgb, var(--panel) 70%, var(--line)); color: var(--fg); border: 1px solid var(--line); border-radius: 5px; padding: 4px 8px; font: inherit; cursor: pointer; }
.hi-root button:hover { border-color: var(--accent); }
.hi-root button.on { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
.hi-agents { display: flex; flex-direction: column; gap: 4px; }
.hi-agent { display: grid; grid-template-columns: 10px 1fr auto; gap: 8px; align-items: center; padding: 5px 7px; border-radius: 5px; cursor: pointer; border: 1px solid transparent; }
.hi-agent:hover { border-color: var(--line); }
.hi-agent.hi-sel { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
.hi-dot { width: 10px; height: 10px; border-radius: 2px; }
.hi-st { color: var(--muted); font-size: 11px; }
.hi-log { flex: 1; min-height: 100px; overflow: auto; font-size: 11px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 8px; }
.hi-log b { color: var(--fg); font-weight: normal; }
.hi-perf { font-size: 11px; color: var(--muted); }
.hi-hint { font-size: 11px; color: var(--muted); }
/* The user's own game art draws on its own canvas that covers the whole mount. */
.hi-byo { display: none; position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; image-rendering: pixelated; }
.hi-root.byo .hi-stage, .hi-root.byo .hi-aside { display: none; }
.hi-root.byo .hi-byo { display: block; }
.hi-root[data-compact] .hi-aside { display: none; }
`;

const DOM = `
<div class="hi-stage"><canvas class="hi-canvas" data-el="canvas"></canvas></div>
<aside class="hi-aside">
  <h1>ISLAND · agent hub</h1>
  <div><span class="hi-clock" data-el="clock">06:00</span> <span class="hi-st" data-el="weather">sun</span></div>
  <div class="hi-row" data-el="speed">
    <button data-speed="0">⏸</button><button data-speed="1" class="on">1×</button><button data-speed="4">4×</button><button data-speed="16">16×</button>
  </div>
  <div class="hi-row">
    <button data-time="07:00">morning</button><button data-time="12:00">noon</button>
    <button data-time="18:00">dusk</button><button data-time="21:50">bedtime</button>
    <button data-el="rain">rain</button>
  </div>
  <div class="hi-agents" data-el="agents"></div>
  <div class="hi-row" data-el="emotes">
    <button data-emote="!">!</button><button data-emote="?">?</button><button data-emote="heart">♥</button>
    <button data-emote="music">♪</button><button data-el="say">say hi</button>
  </div>
  <div class="hi-hint">Click a resident to select. Click a tile to send them there.</div>
  <div class="hi-log" data-el="log"></div>
  <div class="hi-perf" data-el="perf"></div>
</aside>
`;

/**
 * Mount an island into `root` (an element the caller sizes and positions) and return its
 * handle. The island trusts its caller completely; it is the caller's job to pass only the
 * signed-in account's own data and to dispose() on account switch.
 *
 * opts: { agents, theme, lowFx, paused, interactive, zoom, weather, onSelect }
 * handle: { sim, r, custom, setSession, setTheme, setLowFx, setInteractive, pause, resume,
 *           useArt, clearArt, applyEvent, dispose }
 */
export function mountIsland(root, opts = {}) {
  if (!root) throw new Error("mountIsland needs a container element");
  const doc = root.ownerDocument;
  const style = doc.createElement("style");
  style.textContent = CSS;
  root.classList.add("hi-root");
  root.innerHTML = DOM;
  root.prepend(style);
  const el = (name) => root.querySelector(`[data-el="${name}"]`);

  const world = parseMap(ISLAND_MAP);
  let session = { agents: opts.agents ?? [] };
  const onBadAgent = (err) => console.warn("island: bad agent", err.message);
  const sim = new Sim({ world, wander: true, agents: normalizeSession(session, world, { onError: onBadAgent }), weather: opts.weather ?? "sun" });
  const canvas = el("canvas");
  const zoom = Number(opts.zoom) || (root.clientWidth > 1500 ? 3 : 2);
  const r = new Renderer(canvas, sim, { zoom });
  let custom = null; // {app, canvas, source} while drawn with the user's own game art
  let artSeq = 0; // bumped by every useArt/clearArt/dispose so a superseded load can tell
  let paused = !!opts.paused;
  let lowFx = !!opts.lowFx;
  let disposed = false;
  let theme = hudTheme(opts.theme ?? null);
  let hiddenAt = 0;

  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const logEl = el("log");
  const log = (html) => {
    const d = doc.createElement("div");
    d.innerHTML = `<span>${sim.timeString()}</span> ${html}`;
    logEl.prepend(d);
    while (logEl.children.length > 60) logEl.lastChild.remove();
  };
  const nm = (id) => esc(sim.agent(id)?.name ?? id);
  sim.on("chatStart", (e) => log(`<b>${nm(e.a)}</b> ↔ <b>${nm(e.b)}</b> · ${esc(e.topic)}`));
  sim.on("bubble", (e) => log(`<b>${nm(e.id)}</b>: “${esc(e.text)}”`));
  sim.on("sleep", (e) => log(`<b>${nm(e.id)}</b> went home`));
  sim.on("wake", (e) => log(`<b>${nm(e.id)}</b> is up`));
  sim.on("activity", (e) => e.activity && log(`<b>${nm(e.id)}</b> started: ${esc(e.activity.label)}`));

  function replaceAgents(s, w) {
    for (const a of [...s.agents]) s.removeAgent(a.id);
    for (const a of normalizeSession(session, w, { onError: onBadAgent })) s.addAgent(a);
  }

  function renderAgents() {
    el("agents").innerHTML = sim.agents.map((a) => {
      const st = a.sleeping ? "asleep" : a.chat ? `chatting w/ ${a.chat.with}` : a.status;
      return `<div class="hi-agent ${r.selected === a.id ? "hi-sel" : ""}" data-id="${a.id}">
        <span class="hi-dot" style="background:${a.color}"></span><span>${esc(a.name)}</span>
        <span class="hi-st">${esc(a.activity ? a.activity.label : st)}${a.meta?.model ? " · " + esc(a.meta.model) : ""}</span></div>`;
    }).join("");
  }

  const selectAgent = (id) => {
    r.selected = id;
    renderAgents();
    opts.onSelect?.(id);
  };

  el("agents").addEventListener("click", (e) => {
    const agentEl = e.target.closest(".hi-agent");
    if (agentEl) selectAgent(agentEl.dataset.id);
  });
  canvas.addEventListener("click", (e) => {
    const t = r.tileAt(e.clientX, e.clientY);
    const hit = r.agentAt(t);
    if (hit) { selectAgent(hit.id); return; }
    if (r.selected && world.isWalkable(t.x, t.y)) { sim.orderMove(r.selected, t); log(`sent <b>${nm(r.selected)}</b> to ${t.x},${t.y}`); }
  });

  let speed = 1;
  el("speed").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    speed = Number(b.dataset.speed);
    for (const x of el("speed").children) x.classList.toggle("on", x === b);
  });
  for (const b of root.querySelectorAll("[data-time]")) b.addEventListener("click", () => { sim.setTime(b.dataset.time); log(`time → ${b.dataset.time}`); });
  el("rain").addEventListener("click", () => {
    sim.weather = sim.weather === "rain" ? "sun" : "rain";
    el("rain").classList.toggle("on", sim.weather === "rain");
    for (const a of sim.agents) sim.dressFor(a);
  });
  el("emotes").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || !r.selected) return;
    if (b.dataset.el === "say") sim.say(sim.agent(r.selected), "Hi everyone!");
    else sim.emote(r.selected, b.dataset.emote);
  });

  function applyTheme() {
    const st = root.style;
    for (const [k, v] of [["--bg", theme.panel], ["--panel", theme.raised], ["--line", theme.line], ["--fg", theme.fg], ["--muted", theme.muted], ["--accent", theme.accent], ["--accent-fg", theme.accentFg]]) st.setProperty(k, v);
    root.dataset.mode = theme.mode;
    custom?.app.r.setTheme(theme);
  }
  applyTheme();

  // ---- the user's own game art (optional; the built-in renderer stays the default) ----
  const teardown = (c) => { c.app.dispose(); c.canvas.remove(); c.source.dispose(); };

  async function useArt(files) {
    if (disposed) return { custom: false, message: "The island is gone.", state: "error" };
    const seq = ++artSeq;
    let scene, byoCanvas, app;
    try {
      scene = await loadArtScene({ files, type: "island:stardew" });
      if (seq !== artSeq || disposed) { scene.source.dispose(); return { custom: !!custom, message: "", state: custom ? "custom" : "builtin" }; }
      const w = worldFromTbin(scene.mapData.map, { places: scene.preset.places, homeDoors: scene.preset.homeDoors });
      byoCanvas = doc.createElement("canvas");
      byoCanvas.className = "hi-byo";
      root.append(byoCanvas);
      root.classList.add("byo"); // before startIsland: the renderer sizes itself from the laid-out canvas
      app = await startIsland({
        canvas: byoCanvas, world: w, pack: scene.pack, mapData: scene.mapData, preset: scene.preset,
        agents: normalizeSession(session, w, { onError: onBadAgent }),
        opts: { interactive: false, lowPower: lowFx || undefined, time: sim.timeString(), weather: sim.weather },
        onSelect: (id) => opts.onSelect?.(id),
      });
      app.r.setTheme(theme);
      app.setInteractive(interactive);
      if (paused) app.pause();
      const prev = custom;
      custom = { app, canvas: byoCanvas, source: scene.source };
      if (prev) teardown(prev);
      return { custom: true, message: "", state: "custom" };
    } catch (e) {
      app?.dispose();
      byoCanvas?.remove();
      scene?.source.dispose();
      if (!custom) root.classList.remove("byo");
      if (!(e instanceof ArtError)) console.warn("island: game art", e);
      return { custom: !!custom, message: e instanceof ArtError ? e.message : "Couldn't load those game files.", state: "error" };
    }
  }

  function clearArt() {
    artSeq++;
    if (custom) {
      teardown(custom);
      custom = null;
      root.classList.remove("byo");
      replaceAgents(sim, world); // the built-in island missed every session change while hidden
      last = performance.now();
      r.buildStatic();
      r.draw(true);
      renderAgents();
    }
    return { custom: false, message: "", state: "builtin" };
  }

  // ---- loop: fixed 60 Hz sim step, draw only when the picture changed ----
  let acc = 0, last = performance.now(), frames = 0, drawsAtLastSec = 0, secT = last, simMs = 0;
  let gateAcc = 0, raf = 0;
  function frame(now) {
    if (disposed) return;
    if (paused || custom) { last = now; raf = requestAnimationFrame(frame); return; }
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
      el("perf").textContent = `${drawn} draws/s of ${frames} frames · sim ${(simMs / frames).toFixed(2)} ms/frame · tick ${sim.ticks}`;
      frames = 0; simMs = 0; secT = now;
      renderAgents();
    }
    el("clock").textContent = sim.timeString();
    el("weather").textContent = sim.weather;
    raf = requestAnimationFrame(frame);
  }

  // Hidden tab: rAF stops on its own. On return, fast-forward the missed time (capped at
  // 2 game-hours) instead of animating it.
  function onVisibility() {
    if (doc.hidden) { hiddenAt = performance.now(); return; }
    const away = performance.now() - hiddenAt;
    const ticks = paused || custom ? 0 : Math.min(Math.floor((away * speed) / TICK_MS), 60 * 7 * 12);
    for (let i = 0; i < ticks; i++) sim.tick();
    last = performance.now();
    if (!custom) r.draw(true);
  }
  doc.addEventListener("visibilitychange", onVisibility);

  let interactive = !!opts.interactive;
  renderAgents();
  r.draw(true);
  raf = requestAnimationFrame(frame);

  return {
    sim,
    r,
    get custom() { return custom; },
    /** Replace the residents (the signed-in account's own bots). Follows the live renderer. */
    setSession(agents) {
      session = { agents: agents ?? [] };
      if (disposed) return;
      if (custom) { replaceAgents(custom.app.sim, custom.app.sim.world); custom.app.r.lastSig = ""; }
      else { replaceAgents(sim, world); r.buildStatic(); renderAgents(); }
    },
    /** The app's look; only #rrggbb colours get through (hudTheme). */
    setTheme(next) {
      theme = hudTheme(next);
      if (!disposed) applyTheme();
    },
    setLowFx(on) {
      lowFx = !!on;
      r.lowFx = lowFx;
      r.lastSig = "";
      custom?.app.setLowFx(lowFx);
    },
    /** Keybinds and canvas keys apply only while interactive (Explore open). */
    setInteractive(on) {
      interactive = !!on;
      custom?.app.setInteractive(interactive);
    },
    pause() { paused = true; custom?.app.pause(); },
    resume() {
      paused = false;
      if (custom) custom.app.resume();
      else { last = performance.now(); r.draw(true); }
    },
    useArt,
    clearArt,
    applyEvent: (ev) => applyEvent(custom ? custom.app.sim : sim, ev),
    /** Stops the loop, drops every listener and removes every node the island added. */
    dispose() {
      if (disposed) return;
      disposed = true;
      artSeq++; // an in-flight useArt load discards its scene
      cancelAnimationFrame(raf);
      doc.removeEventListener("visibilitychange", onVisibility);
      if (custom) { teardown(custom); custom = null; }
      root.classList.remove("hi-root", "byo");
      root.removeAttribute("data-mode");
      root.innerHTML = ""; // style, canvases and aside go; their listeners go with them
    },
  };
}
