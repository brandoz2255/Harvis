// Outfit picker. Stardew's model, reimplemented (NPC.ChooseAppearance +
// CharacterAppearanceData, from the REA run and the game's shipped XML docs):
//   1. drop entries whose season / indoors / outdoors / condition don't match;
//   2. exclusive slots (Stardew: IsIslandAttire; ours: "sleepy") only ever apply
//      when that slot is asked for, and are never used outside it;
//   3. lowest precedence wins; ties are broken by weighted random;
//   4. nothing matched -> the "default" entry (Stardew: "Falling back to default sprites").

export const DEFAULT_WARDROBE = [
  { id: "default", precedence: 100 },
  { id: "casual", precedence: 0 },
  { id: "raincoat", precedence: -20, outdoors: true, condition: (c) => c.weather === "rain" },
  { id: "yukata", precedence: -50, condition: (c) => !!c.festival },
  { id: "pajamas", precedence: -100, slot: "sleepy" },
];

export function pickOutfit(entries, ctx = {}, rng = Math.random) {
  const matches = entries.filter((e) => {
    if ((e.slot ?? null) !== (ctx.slot ?? null)) return false;
    if (e.season && e.season !== ctx.season) return false;
    if (e.outdoors && !ctx.outdoors) return false;
    if (e.indoors && ctx.outdoors) return false;
    if (e.condition && !e.condition(ctx)) return false;
    return true;
  });
  if (!matches.length) return entries.find((e) => e.id === "default") ?? { id: "default", precedence: 0 };
  const best = Math.min(...matches.map((e) => e.precedence ?? 0));
  const tied = matches.filter((e) => (e.precedence ?? 0) === best);
  const total = tied.reduce((s, e) => s + (e.weight ?? 1), 0);
  let roll = rng() * total;
  for (const e of tied) {
    roll -= e.weight ?? 1;
    if (roll < 0) return e;
  }
  return tied.at(-1);
}
