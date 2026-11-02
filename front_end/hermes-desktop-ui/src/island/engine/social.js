// Social layer: chat chance, topic pools, and line picking.
// Our own design. The REA runs informed the numbers:
//   Stardew (performTenMinuteUpdate/sayHiTo): roll on the 10-min tick, base 0.3
//     shifted by personality, partner replies 66% after 1000 + 0..500 ms, 3 s bubbles.
//   Terraria: topics come from a context pool, and personality adds or removes topics.

/** Base 0.3, shifted ±0.25 per unit of chattiness, clamped to [0, 1]. */
export function chatChance(persona = {}) {
  const p = 0.3 + 0.25 * (persona.chatty ?? 0);
  return Math.max(0, Math.min(1, p));
}

/** Build the list of things worth talking about right now. */
export function buildTopicPool(ctx, persona = {}) {
  const pool = ["greeting", "gossip", "work"];
  if (ctx.weather) pool.push(`weather:${ctx.weather}`);
  if (ctx.hour >= 20) pool.push("late");
  if (ctx.hour < 9) pool.push("morning");
  if (ctx.place) pool.push(`place:${ctx.place}`);
  for (const id of ctx.nearby ?? []) pool.push(`about:${id}`);
  if (ctx.festival) pool.push(`festival:${ctx.festival}`);
  for (const t of persona.adds ?? []) pool.push(t);
  const removes = new Set(persona.removes ?? []);
  return pool.filter((t) => !removes.has(t) && !removes.has(t.split(":")[0]));
}

const OPENERS = {
  greeting: ["Hey!", "Oh, hi!", "Yo."],
  gossip: ["Heard the news?", "You won't believe this..."],
  work: ["Shipped anything today?", "Busy day?"],
  "weather:rain": ["Rain again...", "Love the rain sound."],
  "weather:sun": ["Nice out, huh?", "Sun's out!"],
  "weather:storm": ["Thunder's loud!"],
  late: ["Getting late, huh?", "Sleepy yet?"],
  morning: ["Morning!", "Coffee first."],
  code: ["Tests are green!", "Found the bug!"],
  "place:fountain": ["Love the sound of the fountain."],
  "place:cafe": ["That cafe smells amazing."],
  "place:shop": ["Did you see what's in the shop?"],
  "place:busstop": ["Bus is late again."],
  "place:plaza": ["Busy plaza today."],
  "place:garden": ["Flowers are blooming."],
  "place:park": ["Nice day for the park."],
  "place:bridge": ["Good view of the river from here."],
  "place:riverside": ["Think the fish are biting?"],
  "place:saloon": ["Saloon later?"],
  "place:manor": ["Wonder what the mayor's up to."],
};
const REPLIES = ["Ha, yeah.", "Totally.", "Mm-hm!", "No way!", "For real?", "Same."];

/** Pick the opening line for a topic. `about:<id>` and unknown topics get templated lines. */
export function openerFor(topic, rng) {
  if (topic.startsWith("about:")) return `Seen ${capitalise(topic.slice(6))} today?`;
  if (topic.startsWith("festival:")) return `Ready for ${topic.slice(9)}?`;
  const lines = OPENERS[topic] ?? OPENERS[topic.split(":")[0]] ?? OPENERS.greeting;
  return lines[Math.floor(rng() * lines.length)];
}

export function replyFor(rng) {
  return REPLIES[Math.floor(rng() * REPLIES.length)];
}

const capitalise = (s) => s.charAt(0).toUpperCase() + s.slice(1);
