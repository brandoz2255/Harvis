import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim, TICKS_PER_10MIN, BUBBLE_TICKS } from "../sim.js";
import { normalizeAgent, normalizeSession, personaFromText } from "../agents.js";
import { applyEvent } from "../events.js";

const world = parseMap(ISLAND_MAP);
const runTicks = (sim, n) => { for (let i = 0; i < n; i++) { sim.tick(); sim.checkInvariants(); } };

test("normalizeAgent: a minimal Harvis session agent becomes a sim agent", () => {
  const a = normalizeAgent({ id: "agt_1", name: "Researcher", provider: "ollama", model: "qwen3:8b" }, world, 0);
  assert.equal(a.id, "agt_1");
  assert.equal(a.name, "Researcher");
  assert.deepEqual(a.meta, { provider: "ollama", model: "qwen3:8b" });
  assert.ok(world.isWalkable(a.start.x, a.start.y), "got a walkable start spot");
  assert.match(a.color, /^#[0-9a-f]{6}$/i);
  assert.equal(typeof a.persona.chatty, "number");
});

test("normalizeAgent: rejects junk ids and clamps persona numbers", () => {
  assert.throws(() => normalizeAgent({ name: "no id" }, world, 0), /id/);
  assert.throws(() => normalizeAgent({ id: "<script>" }, world, 0), /id/);
  const a = normalizeAgent({ id: "x", persona: { chatty: 99 } }, world, 0);
  assert.equal(a.persona.chatty, 1);
});

test("personality text maps to chattiness and topics", () => {
  assert.ok(personaFromText("Outgoing, talkative and friendly").chatty > 0.3);
  assert.ok(personaFromText("Quiet, shy, keeps to itself").chatty < -0.3);
  assert.ok(personaFromText("A meticulous coding assistant").adds.includes("code"));
  assert.ok(personaFromText("Never gossips").removes.includes("gossip"));
});

test("normalizeSession: unique ids, spread-out starts, schedule places that exist on the map", () => {
  const agents = normalizeSession({ agents: [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "a" }] }, world);
  assert.equal(agents.length, 3, "duplicate id dropped");
  const starts = new Set(agents.map((a) => `${a.start.x},${a.start.y}`));
  assert.equal(starts.size, 3, "no two agents start on one tile");
  for (const a of agents) for (const place of Object.values(a.schedule)) assert.ok(world.places[place], `place ${place}`);
});

test("event agent.task.started walks the agent to a work spot and shows what it is doing", () => {
  const sim = new Sim({ world, autonomy: false, agents: normalizeSession({ agents: [{ id: "a" }] }, world) });
  applyEvent(sim, { type: "agent.task.started", agentId: "a", task: "Summarise the PDF" });
  const a = sim.agent("a");
  assert.equal(a.activity.kind, "working");
  assert.equal(a.activity.label, "Summarise the PDF");
  assert.ok(a.goal || a.next || a.path.length || sim.world.places.work, "heading to work");
  runTicks(sim, 1200);
  applyEvent(sim, { type: "agent.task.finished", agentId: "a" });
  assert.equal(a.activity, null);
  assert.ok(a.emote, "celebrates");
});

test("event agent.message: nearby agents chat with the real text; far ones walk over first", () => {
  const sim = new Sim({ world, autonomy: false, agents: [
    { id: "a", start: { x: 14, y: 11 } }, { id: "b", start: { x: 16, y: 11 } }, { id: "far", start: { x: 3, y: 14 } }] });
  applyEvent(sim, { type: "agent.message", from: "a", to: "b", text: "Can you check the citations?" });
  assert.equal(sim.agent("a").bubble.text, "Can you check the citations?");
  assert.equal(sim.agent("a").chat.with, "b");
  applyEvent(sim, { type: "agent.message", from: "far", to: "b", text: "Done with the draft" });
  assert.equal(sim.agent("far").bubble, null, "doesn't shout across the island");
  runTicks(sim, 900);
  assert.equal(sim.agent("far").lastSaid, "Done with the draft", "said it on arrival");
});

test("long message text is trimmed for the bubble", () => {
  const sim = new Sim({ world, autonomy: false, agents: [{ id: "a", start: { x: 14, y: 11 } }, { id: "b", start: { x: 16, y: 11 } }] });
  applyEvent(sim, { type: "agent.message", from: "a", to: "b", text: "x".repeat(300) });
  assert.ok(sim.agent("a").bubble.text.length <= 60);
  assert.ok(sim.agent("a").bubble.text.endsWith("…"));
});

test("events: thinking / error emotes, agent.added / agent.removed, unknown events ignored", () => {
  const sim = new Sim({ world, autonomy: false, agents: normalizeSession({ agents: [{ id: "a" }] }, world) });
  applyEvent(sim, { type: "agent.thinking", agentId: "a" });
  assert.equal(sim.agent("a").emote.kind, "?");
  runTicks(sim, 200);
  applyEvent(sim, { type: "agent.error", agentId: "a", error: "timeout" });
  assert.equal(sim.agent("a").emote.kind, "sweat");
  applyEvent(sim, { type: "agent.added", agent: { id: "new", name: "New" } });
  assert.ok(sim.agent("new"), "joined the island");
  sim.checkInvariants();
  applyEvent(sim, { type: "agent.removed", agentId: "new" });
  assert.equal(sim.agent("new"), undefined);
  sim.checkInvariants();
  assert.doesNotThrow(() => applyEvent(sim, { type: "something.else" }));
  assert.doesNotThrow(() => applyEvent(sim, { type: "agent.thinking", agentId: "ghost" }));
});
