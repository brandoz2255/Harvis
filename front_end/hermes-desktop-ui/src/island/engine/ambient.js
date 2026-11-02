// Ambient critters: butterflies by day, fireflies at night, birds crossing,
// pigeons pecking about on the paving. Motion updates every 4 ticks (15 fps) so the
// render signature only changes at that cadence. All positions in pixels.
const TYPES = {
  butterfly: { speed: 0.35, ttl: 60 * 40, day: true,  n: 3 },
  firefly:   { speed: 0.2,  ttl: 60 * 90, day: false, n: 6 },
  bird:      { speed: 2.2,  ttl: 60 * 12, day: true,  n: 1 },
  pigeon:    { speed: 0.12, ttl: 60 * 25, day: true,  n: 2 }, // hops along walkable ground
};

export class Ambient {
  /** `area` ({x, y, w, h} in pixels) keeps critters where the camera can go; default: the whole map. */
  constructor(world, area = null) { this.world = world; this.area = area; this.critters = []; this.rng = 1; }
  rand() { this.rng = (this.rng * 1103515245 + 12345) & 0x7fffffff; return this.rng / 0x7fffffff; }

  tick(sim) {
    if (sim.ticks % 4) return; // 15 fps cadence
    const hour = (sim.minutes % 1440) / 60, day = hour >= 6.5 && hour < 19;
    const { x: X0, y: Y0, w: W, h: H } = this.area ?? { x: 0, y: 0, w: (sim.world.width ?? sim.world.w) * 16, h: (sim.world.height ?? sim.world.h) * 16 };
    for (const [type, t] of Object.entries(TYPES)) {
      if (t.day !== day) continue;
      const have = this.critters.filter((c) => c.type === type).length;
      if (have < t.n && this.rand() < 0.02) {
        if (type === "bird") this.critters.push({ type, x: X0 - 20, y: Y0 + 40 + this.rand() * (H * 0.4), vx: t.speed * 4, vy: (this.rand() - 0.5) * 0.4, ttl: t.ttl, ph: 0 });
        else if (type === "pigeon") {
          // land on a random free walkable tile; a few tries, then wait for the next roll
          for (let k = 0; k < 6; k++) {
            const tx = Math.floor((X0 + this.rand() * W) / 16), ty = Math.floor((Y0 + this.rand() * H) / 16);
            if (this.onGround(tx * 16 + 8, ty * 16 + 12)) { this.critters.push({ type, x: tx * 16 + 8, y: ty * 16 + 12, vx: 0, vy: 0, ttl: t.ttl, ph: this.rand() * 7 }); break; }
          }
        } else this.critters.push({ type, x: X0 + this.rand() * W, y: Y0 + this.rand() * H, vx: 0, vy: 0, ttl: t.ttl, ph: this.rand() * 7 });
      }
    }
    for (const c of this.critters) {
      c.ph += 0.25;
      if (c.type === "butterfly" || c.type === "firefly") {
        if (this.rand() < 0.08 || !c.vx) { const a = this.rand() * Math.PI * 2, s = TYPES[c.type].speed; c.vx = Math.cos(a) * s * 4; c.vy = Math.sin(a) * s * 4; }
        c.x += c.vx; c.y += c.vy;
        c.x = Math.max(X0 + 8, Math.min(X0 + W - 8, c.x)); c.y = Math.max(Y0 + 8, Math.min(Y0 + H - 8, c.y));
      } else if (c.type === "bird") { c.x += c.vx; c.y += c.vy + Math.sin(c.ph) * 0.6; }
      else if (c.type === "pigeon") {
        if (this.rand() < 0.04) c.vx = (this.rand() - 0.5) * 3; // peck, then shuffle on
        const nx = c.x + c.vx;
        if (nx > X0 && nx < X0 + W && this.onGround(nx, c.y)) c.x = nx; else c.vx = -c.vx;
      }
      c.ttl -= 4;
    }
    this.critters = this.critters.filter((c) => c.ttl > 0 && c.x > X0 - 30 && c.x < X0 + W + 30);
  }

  /** True when a pixel position is on a tile people can walk on (always true if the world can't say). */
  onGround(px, py) {
    const w = this.world;
    return !w.isWalkable || w.isWalkable(Math.floor(px / 16), Math.floor(py / 16));
  }

  /** Coarse signature so redraws only happen when critters actually moved. */
  sig() { return this.critters.map((c) => `${c.type[0]}${c.x >> 3},${c.y >> 3},${c.ph | 0}`).join("|"); }

  draw(g, ticks) {
    for (const c of this.critters) {
      if (c.type === "butterfly") {
        g.fillStyle = c.ph % 2 < 1 ? "#ffb0d0" : "#ffd0e0";
        const w = Math.abs(Math.sin(c.ph * 2)) * 3 + 1;
        g.fillRect(c.x - w, c.y - 2, w, 4); g.fillRect(c.x, c.y - 2, w, 4);
      } else if (c.type === "firefly") {
        const on = Math.sin(c.ph) > 0.2;
        g.fillStyle = on ? "rgba(220,255,120,0.95)" : "rgba(120,140,60,0.5)";
        g.fillRect(c.x - 1, c.y - 1, on ? 3 : 2, on ? 3 : 2);
        if (on) { g.fillStyle = "rgba(220,255,120,0.15)"; g.beginPath(); g.arc(c.x, c.y, 7, 0, 7); g.fill(); }
      } else if (c.type === "bird") {
        const f = Math.sin(c.ph * 2.4) > 0 ? 0 : 3;
        g.fillStyle = "rgba(40,40,55,0.9)";
        g.fillRect(c.x - 7, c.y - 2 + f, 6, 2); g.fillRect(c.x - 1, c.y - 1, 3, 3); g.fillRect(c.x + 2, c.y - 2 + f, 6, 2);
      } else if (c.type === "pigeon") {
        const peck = Math.sin(c.ph * 1.3) > 0.5, dir = c.vx < 0 ? -1 : 1;
        g.fillStyle = "#00000030"; g.fillRect(c.x - 4, c.y - 1, 8, 2);
        g.fillStyle = "#8d93a1"; g.fillRect(c.x - 4, c.y - 5, 8, 4); // body
        g.fillStyle = "#6b7183"; g.fillRect(c.x - dir * 4 - (dir > 0 ? 1 : 0), c.y - 4, 1, 3); // tail
        g.fillStyle = "#5d8f86"; g.fillRect(c.x + dir * 3 - 1, c.y - 8 + (peck ? 3 : 0), 3, 3); // head with a green-ish neck
        g.fillStyle = "#e8b04a"; g.fillRect(c.x + dir * 5 - (dir < 0 ? 1 : 0), c.y - 7 + (peck ? 3 : 0), 1, 1); // beak
      }
    }
  }
}

const LAMP_GLOW = [[36, "rgba(255,200,110,0.05)"], [26, "rgba(255,200,110,0.07)"], [16, "rgba(255,200,110,0.1)"]];

/** Session-persistent decorative objects built by agents. */
export function drawObject(g, o, sim) {
  const x = o.x * 16, y = o.y * 16;
  switch (o.kind) {
    case "lamp": {
      g.fillStyle = "#2f3a3d"; g.fillRect(x + 7, y + 2, 2, 12); g.fillRect(x + 5, y + 13, 6, 3);
      g.fillRect(x + 3, y - 6, 10, 2); g.fillRect(x + 4, y - 5, 8, 7);
      const night = (sim.minutes % 1440) / 60 >= 19 || (sim.minutes % 1440) / 60 < 6.5;
      g.fillStyle = night ? "#ffe9a0" : "#f3e3b0"; g.fillRect(x + 5, y - 4, 6, 5);
      if (night) { // stacked discs instead of a gradient: nothing is allocated per frame
        for (const [r, c] of LAMP_GLOW) { g.fillStyle = c; g.beginPath(); g.arc(x + 8, y - 2, r, 0, 7); g.fill(); }
      }
      break;
    }
    case "garden": {
      g.fillStyle = "#6a4a2a"; g.fillRect(x + 1, y + 4, 14, 10);
      g.fillStyle = "#4a7a3a";
      for (let i = 0; i < 3; i++) { g.fillRect(x + 3 + i * 4, y + 6, 2, 3); g.fillRect(x + 3 + i * 4, y + 4, 1, 2); }
      break;
    }
    case "foodcart": {
      g.fillStyle = "#00000030"; g.fillRect(x + 1, y + 14, 14, 2);
      g.fillStyle = "#b5703f"; g.fillRect(x + 1, y + 7, 14, 6);
      g.fillStyle = "#8a5230"; g.fillRect(x + 1, y + 11, 14, 2);
      g.fillStyle = "#f4ead0"; g.fillRect(x + 3, y + 8, 10, 2); // serving counter
      for (let i = 0; i < 7; i++) { g.fillStyle = i & 1 ? "#f4ead0" : "#c8503c"; g.fillRect(x + 1 + i * 2, y + 1, 2, 5); } // striped canopy
      g.fillStyle = "#2a1e1a"; g.fillRect(x + 3, y + 13, 3, 3); g.fillRect(x + 10, y + 13, 3, 3); // wheels
      break;
    }
    case "signpost": {
      g.fillStyle = "#7a5a30"; g.fillRect(x + 7, y + 2, 2, 12); g.fillRect(x + 2, y + 3, 12, 5);
      g.fillStyle = "#e8d8a8"; g.fillRect(x + 3, y + 4, 10, 3);
      break;
    }
    case "stall": {
      g.fillStyle = "#00000030"; g.fillRect(x + 1, y + 14, 14, 2);
      g.fillStyle = "#7a5a30"; g.fillRect(x + 1, y + 3, 2, 11); g.fillRect(x + 13, y + 3, 2, 11);
      g.fillStyle = "#a87a52"; g.fillRect(x + 2, y + 9, 12, 4);
      const goods = ["#c8503c", "#e8b04a", "#6aa84f"];
      for (let i = 0; i < 5; i++) { g.fillStyle = goods[i % 3]; g.fillRect(x + 3 + i * 2, y + 7 + (i & 1), 2, 2); }
      for (let i = 0; i < 8; i++) { g.fillStyle = i & 1 ? "#f4ead0" : "#3f8f5c"; g.fillRect(x + i * 2, y + 1, 2, 4); } // striped awning
      break;
    }
    case "bench": {
      g.fillStyle = "#8a6a3a"; g.fillRect(x + 1, y + 6, 14, 3); g.fillRect(x + 1, y + 2, 14, 2);
      g.fillStyle = "#2f3a3d"; g.fillRect(x + 2, y + 9, 2, 4); g.fillRect(x + 12, y + 9, 2, 4);
      break;
    }
  }
}
