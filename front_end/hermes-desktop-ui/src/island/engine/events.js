// Harvis event bridge: what an agent is really doing -> what it does on the island.
// Pure mapping onto Sim methods; unknown events and unknown agents are ignored.
//
//   agent.task.started  { agentId, task }      walk to a work spot, show the task
//   agent.task.finished { agentId }            celebrate, go back to its day
//   agent.message       { from, to, text }     walk over if needed, then chat with that text
//   agent.thinking      { agentId }            "?" emote
//   agent.error         { agentId, error }     sweat emote
//   agent.idle          { agentId }            clear activity
//   agent.added         { agent }              join the island (session agent shape)
//   agent.removed       { agentId }            leave the island
import { normalizeAgent } from "./agents.js";

export const BUBBLE_MAX = 60;

export function trimForBubble(text) {
  const t = String(text ?? "").replace(/\s+/g, " ").trim();
  return t.length > BUBBLE_MAX ? t.slice(0, BUBBLE_MAX - 1).trimEnd() + "…" : t;
}

function workSpot(sim, a) {
  const places = sim.world.places ?? {};
  const target = places.work ?? places.plaza ?? Object.values(places)[0];
  return target ? sim.nearestFreeTo(target, a, 4) ?? target : null;
}

export function applyEvent(sim, ev) {
  if (!ev || typeof ev.type !== "string") return false;
  const one = (id) => (typeof id === "string" ? sim.agent(id) : undefined);
  switch (ev.type) {
    case "agent.task.started": {
      const a = one(ev.agentId); if (!a || a.inside) return false;
      a.activity = { kind: "working", label: trimForBubble(ev.task ?? "working") };
      const spot = workSpot(sim, a);
      if (spot) sim.orderMove(a.id, spot);
      sim.emit("activity", { id: a.id, activity: a.activity });
      return true;
    }
    case "agent.task.finished": {
      const a = one(ev.agentId); if (!a) return false;
      a.activity = null;
      sim.emote(a.id, "music");
      sim.emit("activity", { id: a.id, activity: null });
      return true;
    }
    case "agent.idle": {
      const a = one(ev.agentId); if (!a) return false;
      a.activity = null;
      return true;
    }
    case "agent.thinking": {
      const a = one(ev.agentId); if (!a) return false;
      return sim.emote(a.id, "?");
    }
    case "agent.error": {
      const a = one(ev.agentId); if (!a) return false;
      return sim.emote(a.id, "sweat");
    }
    case "agent.message": {
      const a = one(ev.from), b = one(ev.to);
      if (!a || !b || a === b || a.inside || b.inside) return false;
      return sim.deliverMessage(a, b, trimForBubble(ev.text));
    }
    case "agent.added": {
      try {
        const taken = new Set(sim.agents.map((x) => `${x.tile.x},${x.tile.y}`));
        sim.addAgent(normalizeAgent(ev.agent, sim.world, sim.agents.length, taken));
        return true;
      } catch { return false; }
    }
    case "agent.removed":
      return sim.removeAgent(ev.agentId);
    default:
      return false;
  }
}
