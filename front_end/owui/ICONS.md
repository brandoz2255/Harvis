# Harvis icon system — house style + source libraries

The rule: **one house style, one baseline family, borrow only for missing concepts —
then normalize.** Harvis already ships 178 in-house icon components
(`src/lib/components/icons/`, Heroicons-style ports); we do NOT replace them with a new
library. New icons conform to the house style below; the backlog is extracting the
~33 agent-studio files' hand-rolled inline `<svg>` into `icons/` components
(gap item 6 in the UI polish audit).

## House style (every Harvis icon)

- `viewBox="0 0 24 24"`, outline style
- `stroke-width: 1.5` (chrome may use up to 1.8 for small sizes; never 2 — normalize borrowed Tabler icons down)
- `stroke: currentColor`, `fill: none` (solid variants only for selected/filled states)
- rounded line caps + joins (`stroke-linecap="round" stroke-linejoin="round"`)
- displayed at 16–20px in chrome (typically `size-4.5`), aligned to whole pixels — no half-pixel strokes
- one recognizable concept per icon; simplify until it reads at 16px
- `aria-hidden="true"` on the svg; the accessible name lives on the button (`aria-label` + Tooltip)

## Source libraries (priority order)

1. **Heroicons** — primary visual baseline. Closest match to the existing set (24×24
   outline, 1.5 stroke, solid variants). Use for: sidebar, toolbar, menus, settings,
   chat actions.
2. **IBM Carbon iconography guidelines** — the *rules* for drawing Harvis-only concepts
   (grid, whole-pixel alignment, clean production SVGs, review before publish). Use for:
   Adaptive Space, provider readiness, execution lanes, agent trace, sandbox, skills.
3. **Apple HIG (icons)** — the recognizability test: one familiar metaphor, highly
   simplified, consistent size/detail/stroke/perspective. Use when deciding whether an
   icon is understandable without text.
4. **Lucide** — first fallback for concepts Heroicons lacks (dev tools, terminals,
   databases, networking, AI/infra). Strict consistency, adjustable stroke — normalize
   to 1.5 on import.
5. **Phosphor** — study reference for *states/weights* (Thin→Fill, Duotone): how one
   concept changes between quiet, selected, filled, expressive. Do NOT mix duotone into
   normal toolbar rows unless an entire region deliberately uses it.
6. **Material Symbols** — reference for variable icon behavior (fill/weight/grade/optical
   size): outline when inactive → filled when selected, optical bump at small sizes.
   Use for: selected tabs, toggles, starred items, active nav.
7. **Iconify** — discovery only (300k+ icons across 200+ sets). Find the metaphor, then
   REDRAW/normalize into the house style. Never import mixed families directly.
8. **Tabler** — Svelte-friendly fallback (6k+ MIT, 24×24). Default stroke is 2px —
   always normalize to 1.5 before landing.

## Workflow for a new icon

1. Search the in-house set (`src/lib/components/icons/`) first.
2. Missing → Heroicons → Lucide → Tabler (normalize stroke) → redraw per Carbon rules.
3. Land it as a component in `src/lib/components/icons/` (same props/shape as the
   existing 178) — never as a one-off inline `<svg>` in a page/panel.
4. Check it at 16px on all three themes (Midnight/Airy/Warm) — `currentColor` only.
