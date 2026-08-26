# Why Harvis CAD lids come out shallow — and what Zoo actually does

Date: 2026-08-18

Zoo's Zookeeper is not a one-shot "prompt → mesh". From
[their research note](https://zoo.dev/research/zookeeper):

1. **Research** — it searches and reads documentation / datasheets as it works.
2. **Plan** — constraints and a design plan before geometry.
3. **Act** — write KCL incrementally (feature by feature, not the whole part once).
4. **Observe** — execute on their kernel, take **multi-view snapshots**, measure
   mass / volume / CoM / surface area.
5. **Iterate** until the snapshots and measurements match intent.

Harvis already had the kernel half of that (CadIR → build123d, conformance,
`cad_render_views`, experiment/repair). What was missing for a request like
**"a lid on a jar"** is the *research + mating-pair intent* half: the authoring
prompt taught CadIR grammar, few-shots were all one-piece parts, and
"lid on a jar" did not even emit a two-body check unless the user said
"removable" / "concentric".

## What we added (local, no Zoo cloud)

| Zoo behaviour | Harvis analogue |
|---|---|
| Read docs / datasheets | `cad_lookup_pattern` + `owui_compat/cad_patterns.py` (offline catalog) |
| Plan a mating interface | Pattern brief injected into `cad_generate` prompts; v2 spec infers two bodies + coaxial |
| Visual snapshots | already `cad_render_views` (user viewport; model still cannot see pixels) |
| Measure / iterate | already `cad_get_build` conformance + experiment repair |

A fused disk on the rim is now the *wrong* part on purpose: two components,
skirt over the neck, diametral slip clearance in the pattern (0.3 mm default,
**not graded** unless the user stated a gap). CadIR still cannot cut threads;
the pattern says so in assumptions.

Zoo cloud Text-to-CAD remains a wrap-only side lane (`docs/research/2026-07-30-zoo-dev.md`).
This change does not call api.zoo.dev.
