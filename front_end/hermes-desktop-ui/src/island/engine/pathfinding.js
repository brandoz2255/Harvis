// 4-neighbour A* over the tile grid. Our own design: the REA run showed
// Terraria uses local steering, not path search, so it is not copied here.
import { key } from "./world.js";

const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];

/** Minimal binary min-heap keyed on f. */
class Heap {
  constructor() { this.a = []; }
  get size() { return this.a.length; }
  push(n) {
    const a = this.a; a.push(n);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p].f <= a[i].f) break;
      [a[p], a[i]] = [a[i], a[p]]; i = p;
    }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l].f < a[m].f) m = l;
        if (r < a.length && a[r].f < a[m].f) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]]; i = m;
      }
    }
    return top;
  }
}

/**
 * Find a path from start to goal. Returns the steps after `start` up to and
 * including `goal`, [] when start === goal, or null when unreachable.
 * opts.blocked: Set of tile keys treated as walls (other characters' tiles).
 */
export function findPath(world, start, goal, opts = {}) {
  const blocked = opts.blocked ?? new Set();
  const maxNodes = opts.maxNodes ?? 4000;
  if (start.x === goal.x && start.y === goal.y) return [];
  if (!world.isWalkable(goal.x, goal.y) || blocked.has(key(goal.x, goal.y))) return null;

  const h = (x, y) => (Math.abs(x - goal.x) + Math.abs(y - goal.y)) * 0.7; // admissible: min tile cost
  const g = new Map([[key(start.x, start.y), 0]]);
  const parent = new Map();
  const closed = new Set();
  const open = new Heap();
  open.push({ x: start.x, y: start.y, f: h(start.x, start.y) });
  let expanded = 0;

  while (open.size) {
    const cur = open.pop();
    const ck = key(cur.x, cur.y);
    if (closed.has(ck)) continue;
    if (cur.x === goal.x && cur.y === goal.y) {
      const path = [];
      for (let k = ck; parent.has(k); k = parent.get(k).k) {
        const n = parent.get(k);
        path.push({ x: n.x, y: n.y });
      }
      return path.reverse();
    }
    closed.add(ck);
    if (++expanded > maxNodes) return null;
    for (const [dx, dy] of DIRS) {
      const nx = cur.x + dx, ny = cur.y + dy, nk = key(nx, ny);
      if (closed.has(nk) || !world.isWalkable(nx, ny) || blocked.has(nk)) continue;
      const ng = g.get(ck) + world.cost(nx, ny);
      if (ng < (g.get(nk) ?? Infinity)) {
        g.set(nk, ng);
        parent.set(nk, { k: ck, x: nx, y: ny });
        open.push({ x: nx, y: ny, f: ng + h(nx, ny) });
      }
    }
  }
  return null;
}
