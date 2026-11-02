// Bootstrap: wires a Sim + StardewRenderer to a canvas. Fixed 60 Hz sim step,
// redraw only when the picture changed, pause on hidden tab, catch up on return.
// Perf governor: watches draw cost + quietness and steps quality down so the
// island stays a light background thing. app.pause() freezes sim + render.
// It listens to no host messages: island/main.js checks the host origin once and calls
// app.pause / resume / setLowFx. app.dispose() stops the loop and removes every listener.
import { Sim, TICK_MS } from "../sim.js";
import { StardewRenderer, loadStardewScene } from "./stardew-ui.js";
import { startBuild, tickBuilds, tickHappenings, BUILDABLES } from "../island-life.js";

export async function startIsland({ canvas, world, agents, pack, mapData, preset, opts = {}, onSelect }) {
  const sim = new Sim({ world, wander: true, agents, ...opts });
  const r = new StardewRenderer(canvas, sim, pack, mapData, { zoom: Number(opts.zoom) || 3, view: preset.view });
  if (opts.time) sim.setTime(opts.time);
  if (opts.weather) sim.weather = opts.weather;
  const happenings = preset.happenings ?? opts.happenings ?? [];
  const firedHappenings = new Set();
  let prevMinutes = sim.minutes;
  sim.on("tenMinutes", () => {
    if (sim.minutes < prevMinutes) firedHappenings.clear(); // day wrapped
    prevMinutes = sim.minutes;
    tickHappenings(sim, happenings, firedHappenings);
  });

  const ro = new ResizeObserver(() => r.resize());
  ro.observe(canvas.parentElement ?? canvas);
  r.resize();

  // ---- input ----
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, moved: false }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    if (drag && (Math.abs(e.clientX - drag.x) > 4 || Math.abs(e.clientY - drag.y) > 4)) {
      r.pan(e.clientX - drag.x, e.clientY - drag.y);
      drag.x = e.clientX; drag.y = e.clientY; drag.moved = true;
    }
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!drag || drag.moved) { drag = null; return; }
    drag = null;
    const rect = canvas.getBoundingClientRect();
    const hit = r.hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (hit.kind === "agent") {
      const a = sim.agent(hit.id);
      if (a?.pet) { sim.emote(a.id, "heart"); sim.say(a, "*purrs*"); }
      else if (a && hit.id === r.selected) { sim.emote(a.id, "happy"); sim.say(a, "Hey!"); }
      r.selected = hit.id; r.manualCam = false; onSelect?.(hit.id);
    } else if (hit.kind === "button") handleAction(hit.action);
    else if (hit.kind === "tile" && r.selected && world.isWalkable(hit.tile.x, hit.tile.y)) {
      sim.orderMove(r.selected, hit.tile);
    } else if (hit.kind === "tile") r.selected = null;
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    r.zoom = Math.max(2, Math.min(5, r.zoom + (e.deltaY < 0 ? 1 : -1)));
    r.resize(); r.lastSig = "";
  }, { passive: false });

  const kinds = Object.keys(BUILDABLES); let ki = 0;
  const onKeydown = (e) => {
    if (!app.interactive) return; // the host enables keys only while the island has focus (Explore)
    if (e.key === "p" || e.key === "P") app.paused ? app.resume() : app.pause();
    if ((e.key === "b" || e.key === "B") && r.selected) {
      const a = sim.agent(r.selected);
      if (a && !a.inside) startBuild(sim, a.id, { x: Math.round(a.pos.x) + 1, y: Math.round(a.pos.y) + 1 }, kinds[(ki++) % kinds.length]);
    }
  };
  window.addEventListener("keydown", onKeydown);

  function handleAction(action) {
    if (action.startsWith("speed:")) { speed = Number(action.split(":")[1]); r.speed = speed; }
    else if (action.startsWith("time:")) sim.setTime(action.slice(5));
    else if (action === "rain") { sim.weather = sim.weather === "rain" ? "sun" : "rain"; for (const a of sim.agents) sim.dressFor(a); }
    if (action.startsWith("time:") || action === "rain") r.flashHud();
    lastChange = performance.now(); // a click wakes the draw loop from its quiet cadence
  }

  // ---- perf governor ----
  const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  let lowFx = !!(opts.lowPower ?? reduced);
  r.lowFx = lowFx; r.reducedMotion = !!reduced;
  // The BatteryManager outlives the island, so dispose() must detach this handler or it pins the art pack.
  let battery = null, onBattery = null;
  navigator.getBattery?.().then((b) => {
    if (stopped) return;
    onBattery = () => { if (!b.charging && b.level < 0.25 && opts.autoBattery !== false) setLowFx(true); };
    battery = b;
    onBattery(); b.addEventListener?.("levelchange", onBattery);
  }).catch(() => {});
  function setLowFx(on) { lowFx = on; r.lowFx = on; r.lastSig = ""; }
  let drawCost = 0, lastChange = performance.now(), paused = false, gateAcc = 0, raf = 0, stopped = false;

  // ---- pause API (keybind or direct call) ----
  const app = {
    sim, r, perf: { drawsPerSec: 0 },
    // Keys apply only while the host says the island is focused (the standalone page leaves it on).
    interactive: opts.interactive ?? true,
    get paused() { return paused; },
    pause() { paused = true; },
    resume() { paused = false; last = performance.now(); r.draw(true); },
    setInteractive(on) { app.interactive = !!on; },
    setLowFx,
    dispose() {
      stopped = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      battery?.removeEventListener?.("levelchange", onBattery);
      battery = onBattery = null;
      window.removeEventListener("keydown", onKeydown);
      document.removeEventListener("visibilitychange", onVisibility);
    },
    build: (id, spot, kind) => startBuild(sim, id, spot, kind),
    life: { startBuild, tickBuilds, tickHappenings, BUILDABLES },
  };

  // ---- loop ----
  let speed = Number(opts.speed) || 1; r.speed = speed;
  let acc = 0, last = performance.now(), drawsAtLastSec = r.draws, secT = last;
  function frame(now) {
    if (stopped) return;
    const dt = Math.min(250, now - last); last = now;
    if (!paused) {
      acc += dt * speed;
      let n = 0;
      while (acc >= TICK_MS && n < 600) { sim.tick(); tickBuilds(sim); acc -= TICK_MS; n++; }
      if (n === 600) acc = 0;
      // draw-check cadence: normal every frame, lowFx ~12fps, quiet 30s+ -> 4fps
      const gate = lowFx ? 80 : now - lastChange > 30_000 ? 250 : 0;
      gateAcc += dt;
      if (gateAcc >= gate) {
        gateAcc = 0;
        const t0 = performance.now();
        if (r.draw()) lastChange = now;
        drawCost = drawCost * 0.9 + (performance.now() - t0) * 0.1;
        if (drawCost > 14 && !lowFx && opts.autoThrottle !== false) setLowFx(true);
      }
    }
    if (now - secT >= 1000) { app.perf.drawsPerSec = r.draws - drawsAtLastSec; drawsAtLastSec = r.draws; secT = now; }
    raf = requestAnimationFrame(frame);
  }
  let hiddenAt = 0; // when the tab went hidden, for the catch-up on return (scoped: no window globals)
  function onVisibility() {
    if (document.hidden) { hiddenAt = performance.now(); return; }
    const away = performance.now() - hiddenAt;
    if (!paused) {
      const ticks = Math.min(Math.floor((away * speed) / TICK_MS), 60 * 7 * 12);
      for (let i = 0; i < ticks; i++) { sim.tick(); }
    }
    last = performance.now(); r.draw(true);
  }
  document.addEventListener("visibilitychange", onVisibility);
  raf = requestAnimationFrame(frame);
  return app;
}
