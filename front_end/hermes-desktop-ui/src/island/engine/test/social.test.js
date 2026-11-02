import { test } from "node:test";
import assert from "node:assert/strict";
import { ISLAND_MAP, parseMap } from "../world.js";
import { Sim, TICKS_PER_10MIN, CHAT_TICKS, BUBBLE_TICKS } from "../sim.js";
import { buildTopicPool, chatChance } from "../social.js";

const world = parseMap(ISLAND_MAP);
const always = () => 0; // every roll succeeds, every random pick takes the first option

function facingEachOther(a, b) {
  const dx = b.tile.x - a.tile.x, dy = b.tile.y - a.tile.y;
  const want = Math.abs(dx) >= Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
  return a.facing === want;
}
const runTicks = (sim, n) => { for (let i = 0; i < n; i++) { sim.tick(); sim.checkInvariants(); } };

test("clock: 10 game minutes every 7 real seconds, day starts 06:00", () => {
  const sim = new Sim({ world, agents: [], autonomy: false });
  assert.equal(TICKS_PER_10MIN, 420);
  assert.equal(sim.timeString(), "06:00");
  runTicks(sim, TICKS_PER_10MIN * 6);
  assert.equal(sim.timeString(), "07:00");
});

test("a chat starts on the 10-minute tick between nearby agents, who halt and face each other", () => {
  const sim = new Sim({ world, rng: always, agents: [
    { id: "cy", start: { x: 14, y: 11 } }, { id: "bo", start: { x: 17, y: 11 } }] });
  runTicks(sim, TICKS_PER_10MIN - 1);
  assert.equal(sim.agent("cy").chat, null, "nothing before the tick");
  runTicks(sim, 1);
  const a = sim.agent("cy"), c = sim.agent("bo");
  assert.ok(a.chat && c.chat, "both in a chat");
  assert.equal(a.chat.with, "bo");
  assert.ok(facingEachOther(a, c) && facingEachOther(c, a), "turned to face each other");
  assert.ok(a.bubble && a.bubble.text.length > 0, "initiator speaks");
});

test("the partner replies after 1.0-1.5 s; bubbles last 3 s; the chat ends after ~7 s", () => {
  const sim = new Sim({ world, rng: always, agents: [
    { id: "cy", start: { x: 14, y: 11 } }, { id: "bo", start: { x: 17, y: 11 } }] });
  runTicks(sim, TICKS_PER_10MIN);
  const start = sim.ticks;
  assert.equal(BUBBLE_TICKS, 180);
  runTicks(sim, 59);
  assert.equal(sim.agent("bo").bubble, null, "no reply before 1 s");
  runTicks(sim, 31);
  assert.ok(sim.agent("bo").bubble, "reply by 1.5 s");
  runTicks(sim, CHAT_TICKS - (sim.ticks - start));
  assert.equal(sim.agent("cy").chat, null, "chat over");
  assert.equal(sim.agent("bo").chat, null);
});

test("chatting agents resume the trip they were on", () => {
  const sim = new Sim({ world, rng: always, agents: [
    { id: "cy", start: { x: 14, y: 11 } }, { id: "bo", start: { x: 17, y: 11 } }] });
  runTicks(sim, TICKS_PER_10MIN - 2);
  sim.orderMove("cy", world.places.busstop);
  runTicks(sim, 2);
  assert.ok(sim.agent("cy").chat, "chat interrupted the trip");
  runTicks(sim, CHAT_TICKS + 600);
  const a = sim.agent("cy");
  assert.deepEqual(a.tile, world.places.busstop, "arrived after the chat");
});

test("no chats through walls or while standing in a chokepoint", () => {
  const walled = new Sim({ world, rng: always, agents: [
    { id: "a", start: { x: 9, y: 3 } }, { id: "b", start: { x: 11, y: 3 } }] });
  runTicks(walled, TICKS_PER_10MIN);
  assert.equal(walled.agent("a").chat, null, "the wall between apartment and cafe blocks sight");
  const open = new Sim({ world, rng: always, agents: [
    { id: "a", start: { x: 11, y: 3 } }, { id: "b", start: { x: 13, y: 3 } }] });
  runTicks(open, TICKS_PER_10MIN);
  assert.ok(open.agent("a").chat, "the same distance inside the cafe does chat");
  const door = new Sim({ world, rng: always, agents: [
    { id: "a", start: { x: 5, y: 6 } }, { id: "b", start: { x: 5, y: 8 } }] });
  runTicks(door, TICKS_PER_10MIN);
  assert.equal(door.agent("a").chat, null, "door is no-stop");
});

test("chat chance: 0.3 base, chatty raises it, shy lowers it, never outside 0..1", () => {
  assert.equal(chatChance({}), 0.3);
  assert.ok(chatChance({ chatty: 1 }) > 0.5);
  assert.ok(chatChance({ chatty: -1 }) < 0.15);
  assert.ok(chatChance({ chatty: 5 }) <= 1 && chatChance({ chatty: -5 }) >= 0);
});

test("topic pool comes from what is going on, personality adds and removes topics", () => {
  const ctx = { weather: "rain", hour: 21, place: "fountain", nearby: ["bo"], festival: null };
  const base = buildTopicPool(ctx, {});
  assert.ok(base.includes("weather:rain"));
  assert.ok(base.includes("late"));
  assert.ok(base.includes("place:fountain"));
  const shy = buildTopicPool(ctx, { removes: ["gossip"] });
  assert.ok(!shy.includes("gossip"));
  const nerd = buildTopicPool(ctx, { adds: ["code"] });
  assert.ok(nerd.includes("code"));
});

test("emotes don't stack, and a '!' makes idle neighbours in sight turn to look", () => {
  const sim = new Sim({ world, autonomy: false, agents: [
    { id: "ada", start: { x: 16, y: 11 } }, { id: "pip", start: { x: 16, y: 13 } },
    { id: "far", start: { x: 3, y: 14 } }] });
  sim.agent("pip").facing = "down";
  sim.emote("ada", "!");
  sim.emote("ada", "heart");
  assert.equal(sim.agent("ada").emote.kind, "!", "second emote ignored while playing");
  sim.tick();
  assert.equal(sim.agent("pip").facing, "up", "pip turns to look");
  assert.notEqual(sim.agent("far").facing, "right", "far agent didn't react");
  runTicks(sim, 120);
  assert.equal(sim.agent("ada").emote, null, "emote finished");
});
