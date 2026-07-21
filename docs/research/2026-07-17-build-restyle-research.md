# Build cockpit restyle — research & plan (2026-07-17)

The on-demand panel system stays exactly as-is; the work is a token-only restyle of the two loudest cockpit surfaces — the composer (`+page.svelte`) and the header (`BuildHeader.svelte`) — into the calm three-theme token system, after which we work down the remaining handoff list. The single most important finding is that the cockpit currently uses **two accents for one job**: the composer Send is blue (the accent token) while the header Create PR is sky (a HUD color), and sky/violet/indigo leak into pills, tabs, and chips — so the fix is not to recolor blue but to make everything else stop competing with it. The second is mechanical: **a theme is a token map, not a stylesheet** — every surface must be a `gray-*` / `blue-*` class with a paired `dark:` variant, because any raw hex (`bg-[#…]`) opts the element out of Midnight/Airy/Warm entirely; staying token-driven is what keeps a theme a config swap rather than a rewrite. The third, from the leading coding-agent cockpits (Cursor, Claude Code, Codex, Vercel/Linear), is a convergent grammar: one bordered composer card with quiet text-caret pickers docked inside it, exactly one saturated element (Send), and run-state shown as small dots — never background fills. The theme picker itself already ships and works (Warm / Airy / Midnight are all selectable, and the theme-divergence bug is already fixed in current code); the real gap is that the Build cockpit is still hardcoded dark, so Airy/Warm render a dark slab there — a Phase-4 tokenization job that these surgical composer/header edits are the leading slice of.

## Design contract

The authoritative style contract for a Build-cockpit restyle. Every value below is quoted from `front_end/owui/src/lib/themes.ts`, `src/tailwind.css`, `DESIGN.md`, and `DESIGN-REFERENCES.md` (main tree). The overriding law: **a theme is a token map, not a stylesheet.** Components only ever reference the semantic `gray-*` / `blue-*` token classes; the theme registry rewrites the CSS variables behind them. A restyle that hardcodes color defeats the entire system.

---

### 1. The three primary target themes

All three drive the *same* component classes. They differ only in the CSS-variable values assigned to the shared `--color-gray-*` ramp, the `--color-blue-*` accent, and (Warm only) `--theme-font-body`. The ramp's **roles are invariant across every theme**: `gray-800` = raised surface, `gray-850` = panel, `gray-900` = shell/page, `gray-950` = deepest; light-end `gray-50/100/200` = canvas / hover-fill / border. A theme may move the whole ramp lighter/darker/warmer but must never change what a step *means*.

#### Midnight (`id: 'dark'`, `base: 'dark'`) — the default identity

The near-black blue-charcoal ramp defined directly in the `@theme` block of `tailwind.css`; Midnight applies **no overrides** (empty `vars`), so these OKLCH values are the literal tokens.

| Token | Value | Hex ≈ | Role |
|---|---|---|---|
| `--color-gray-50` | `oklch(0.98 0.004 255)` | `#f7f9fb` | (unused in dark; light-mode canvas) |
| `--color-gray-100` | `oklch(0.94 0.006 255)` | `#e8ebef` | light hairline / hover |
| `--color-gray-200` | `oklch(0.92 0.008 255)` | `#e1e5ea` | **default border** (forced globally via `@layer base { border-color: var(--color-gray-200) }`) |
| `--color-gray-500` | `oklch(0.69 0.014 255)` | `#969ca4` | secondary text |
| `--color-gray-600` | `oklch(0.51 0.018 255)` | `#5f6771` | tertiary text / dark border |
| `--color-gray-700` | `oklch(0.42 0.022 257)` | `#464e59` | body text on light |
| `--color-gray-800` | `oklch(0.2 0.026 258)` | `#0f1622` | **raised** surface (cards, inputs) |
| `--color-gray-850` | `oklch(0.14 0.028 259)` | `#040915` | **panel** — the workhorse dark bg (362× `dark:bg-gray-850`) |
| `--color-gray-900` | `oklch(0.095 0.03 260)` | `#00030b` | **shell / page** background |
| `--color-gray-950` | `oklch(0.055 0.03 262)` | `#000004` | deepest (sidebar scrim, overlays) |
| `--color-blue-400` | `oklch(0.79 0.12 230)` | `#5cc9f9` | accent on dark (≈ prototype `#38bdf8`) |
| `--color-blue-500` | `oklch(0.72 0.135 233)` | `#31b2eb` | focus rings |
| `--color-blue-600` | `oklch(0.64 0.145 235)` | `#0098d7` | **primary buttons**, checked fills |
| `--color-blue-700` | `oklch(0.55 0.13 237)` | `#007bb3` | pressed / hover-darkened |

`metaColor: '#00030b'`. Note the non-standard **`gray-850`** step — panels use it, not `gray-800`/`gray-900`. The gray hue deliberately drifts 255→262 as it darkens (darker = *more* blue), chroma rising 0.004→0.03.

**Personality:** cool cyan-on-near-black, dark-first, sans (Inter body / Archivo display). A JARVIS-style operator's console — calm, competent, ambient. Status via small pulsing dots and quiet heartbeat lines, never confetti or gradients. Cyan glow is a *signature*, concentrated in the Adaptive Space HUD; the rest stays near-black and matter-of-fact. **This is the console the Build cockpit lives in by default.**

#### Airy (`id: 'airy'`, `base: 'light'`) — the Build / data theme

Cool light-gray canvas; white cards come from components' `bg-white` in light mode; the pastel-KPI treatment is applied per-page.

| Token | Value | Role |
|---|---|---|
| `--color-gray-50` | `#f4f6f8` | cool light-gray **page canvas** |
| `--color-gray-100` | `#eef1f5` | hover / subtle fill |
| `--color-gray-200` | `#e3e8ee` | hairline **border** |
| `--color-blue-400` | `#8b8ef7` | soft indigo accent (light) |
| `--color-blue-500` | `#6d70f0` | indigo |
| `--color-blue-600` | `#5457e6` | **primary indigo** |
| `--color-blue-700` | `#4143c9` | pressed indigo |

`metaColor: '#f4f6f8'`. Only the light-end grays + accent are overridden; the dark-end steps (`gray-700`–`gray-950`) fall through to the `@theme` OKLCH values, where they serve as text colors in light mode.

**Personality:** clean, airy, data-first Scandinavian-minimal dashboard (Ref 1 · MetricFlow). Pure-white cards on a cool light-gray page, soft diffuse shadows, generous whitespace, `rounded-xl/2xl`, **pastel-tinted KPI cards** (mint / lavender / peach / sky, ~5–12% saturation), cards **lift on hover**. Signature move: a **tinted-top-over-white-footer** stat card — pastel upper block (uppercase colored label + big bold metric in the matching hue + circular icon) over a white footer holding a delta chip (green ↑ / red ↓ + "vs last month"). Sectioned sidebar with an active soft-blue pill, status/tier pills (Enterprise purple / Pro blue / Starter amber), pill-dropdown toolbars, dual-series charts with a floating hover tooltip card. **This is the primary reference the Build cockpit restyle should borrow layout, rhythm, and card grammar from** — adopt the structure, keep Harvis's accent (cyan in dark, indigo optional only in the Airy light theme).

#### Warm (`id: 'warm'`, `base: 'light'`) — the Chat / Notebook theme

Cream paper + coral accent + a serif reading font. Overrides the dark-end grays too, because in light mode those tokens *are* the text color.

| Token | Value | Role |
|---|---|---|
| `--color-gray-50` | `#f5f1e8` | cream **paper canvas** |
| `--color-gray-100` | `#efe9dc` | warm hover / subtle fill |
| `--color-gray-200` | `#e6ddcc` | warm hairline **border** |
| `--color-gray-700` | `#3a352c` | warm body text |
| `--color-gray-800` | `#2b2a26` | warm near-black text / raised |
| `--color-gray-900` | `#211f1b` | deepest warm text |
| `--color-blue-400` | `#e89f86` | soft coral |
| `--color-blue-500` | `#df8365` | coral |
| `--color-blue-600` | `#d0684a` | **primary coral / terracotta** (the Anthropic clay) |
| `--color-blue-700` | `#b5543a` | pressed coral |
| `font` | `'InstrumentSerif', Georgia, 'Times New Roman', serif` | sets `--theme-font-body` |

`metaColor: '#f5f1e8'`.

**Personality:** warm, editorial, literary, calm (Ref 2 · Claude.ai). A cream/paper canvas (not white, not cool gray), a **serif reading face** for body and display, coral/terracotta accent, warm-gray hairline borders, book-like measure and generous line-height. Opposite of Harvis's cool blue-charcoal. This is the reading/writing surface, not a data grid. **Not the Build cockpit's theme** — but the cockpit must render correctly under it (paper canvas, serif body, coral accent) without any component edits, which is the proof that the restyle stayed token-driven.

> Additional registered themes (must not break under a restyle): **Slate** (`harvis-dark`, blue-charcoal lift: `gray-800:#1a1f2e / gray-850:#141823 / gray-900:#0e111a / gray-950:#090b12`), **OLED** (`oled-dark`, true black: `gray-850:#050505 / gray-900:#000000 / gray-950:#000000`), plain **Light**, **System**, and egg-only **Her**. `MANAGED_VARS` (the 12 gray steps + 4 blue steps + `--theme-font-body`) are cleared on every switch so nothing leaks between themes.

---

### 2. Canonical semantic tokens + the no-raw-hex rule

Components MUST express color exclusively through these token classes:

- **Surfaces / borders / text:** the `gray-*` ramp (`gray-50`–`gray-950`, including the custom **`gray-850`**). Always paired light + dark: e.g. `bg-gray-50 dark:bg-gray-950`, `bg-white dark:bg-gray-900`, panels `dark:bg-gray-850`.
- **Accent / primary action / active state:** the `blue-*` ramp (`blue-400`–`blue-700`; steps outside 400–700 fall back to stock Tailwind blue). Primary buttons `bg-blue-600`; dark accent `dark:bg-blue-500 / dark:hover:bg-blue-400`; focus ring `focus:ring-blue-500`; selected-menu check `text-blue-500`. `sky-*` is the interchangeable light-accent twin for toggle chips.
- **Semantic state palettes (stock Tailwind, deliberately NOT overridden by themes — so they read consistently in every theme):**
  - **Danger / error:** `red-*` (`text-red-500`, `bg-red-500`; dark error surface `bg-red-950 text-red-200`).
  - **Warning / live / attention:** `amber-*` (`bg-amber-500`, `text-amber-300/400/500`; light `bg-amber-50 text-amber-700`, dark `bg-amber-950`). `yellow-*` is a minority variant.
  - **Success / healthy:** `green-*` and `emerald-*`, interchangeable (`bg-green-500`, `text-emerald-400`).
  - **Info / HUD signature:** `cyan-*` / `sky-*` (`text-cyan-300`, `border-cyan-400`) — concentrated in the Adaptive Space HUD only.
  - Color-role summary: **blue/sky = active & primary**, **amber = live/attention**, **red = danger**, **green/emerald = success**, **cyan = HUD signature**.
- **State fills use translucent tints, not solid colors:** `*-500/10`, `*-400/10`, `black/5`, `white/5` are the convention for hover and active backgrounds — not opaque fills.

**Hard rule — no raw hex/rgb in components.** Any `bg-[#…]`, inline hex, or rgb color opts the element *out of every theme override* (Midnight/Slate/OLED/Airy/Warm and every future theme), because theming works purely by rewriting `--color-gray-*` / `--color-blue-*`. That is the mechanical reason a restyle must stay token-driven. Stock semantic palettes (red/amber/green/cyan) are the *only* acceptable non-token color, and only because themes deliberately leave them alone. Existing raw-hex stragglers (`chat/FileNav/*` viewers, `admin/Evaluations/ModelActivityChart.svelte`, e.g. `#6b7280`, `#9ca3af`) are **debt, not precedent** — do not copy them.

---

### 3. Type scale · fonts · radius · spacing · shadow

**Font families** (self-hosted, `@font-face` in `app.css`; body is theme-swappable via `--theme-font-body`):
- **Inter** (variable) — body/UI text; base stack (behind platform `-apple-system`/`BlinkMacSystemFont`).
- **Archivo** (variable) — display via `.font-primary` (modal titles, onboarding, sidebar headers).
- **InstrumentSerif** — editorial via `.font-secondary`; also the Warm theme's body font.
- Mono: Tailwind's default `font-mono` (ui-monospace) is the workhorse for code (132×). `JetBrainsMono` is *referenced but has no font file* — falls to `ui-monospace`.
- The wordmark `.harvis-wordmark`: Inter 700, `0.8125rem`, `letter-spacing: 0.26em`, uppercase — the **only** place `font-bold` weight is used.

**Type scale — this is a small-type system** (`text-xs`/`text-sm` dominate ~15:1):

| Class | Size | Usage |
|---|---|---|
| `text-xs` | 0.75rem | metadata, chips, labels, sidebar, tooltips (1,861×) |
| `text-sm` | 0.875rem | **default control/body** (1,360×) |
| `text-base` | 1rem | chat/message body (67×) |
| `text-lg` | 1.125rem | section/modal titles (95×) |
| `text-xl` | 1.25rem | page headings (33×) |
| `text-2xl` | 1.5rem | large headings (29×) — **ceiling outside heroes/empty-states** |
| `text-3xl` | 1.875rem | hero/empty-state (18×) |

Below `text-xs` there is a real micro tier of arbitrary values — `text-[11px]` (315×) and `text-[10px]` (209×) for dense chips/badges/timestamps. Caveat: this px micro-tier does **not** scale with `--app-text-scale`, so prefer rem-based `text-*` for anything that should participate in UI scaling.

**Weight scale (restrained):** `font-medium` (1,213×) = the default emphasis; `font-semibold` (162×) = headings; `font-normal` (49×) = de-emphasis resets; `font-bold`+ effectively unused (reserved for the wordmark). **Rule: medium for emphasis, semibold for headings, never bold.**

**Line height:** Tailwind defaults carry most text. AI prose gets deliberate rhythm via `.markdown-prose` (`prose-p:leading-7 prose-p:my-3`, `prose-headings:mt-5 mb-2.5`). `leading-relaxed` for long copy; `leading-none` for stat numerals/chips.

**UI scale:** the whole document multiplies through one property — `html { font-size: calc(1rem * var(--app-text-scale, 1)) }`. Prefer rem/`text-*` over px so components scale.

**Radius scale** — soft throughout; radius grows with prominence:

| Class | px | Use |
|---|---|---|
| `rounded-lg` | 8 | buttons, small controls, inline previews (445×) |
| `rounded-xl` | 12 | **list rows, dropdown menus, panel sections** (402×) — default for interactive rows/menus |
| `rounded-2xl` | 16 | **cards, popovers, modal shells** (147×) — default for containers |
| `rounded-3xl` | — | hero surfaces only + composer + user chat bubble (35×) |
| `rounded-full` | — | pills, status dots, count badges, avatars (376×) |
| `rounded-sm` / `rounded-md` | 2/6 | tiny inline elements, skeleton bars |

Default new surfaces to `rounded-xl` (rows/menus) or `rounded-2xl` (containers).

**Spacing rhythm** — Tailwind 4pt scale used **tight and half-stepped** (heavy on `0.5`/`1.5`/`2.5` suffixes):
- Controls: `px-3 py-1.5` (the signature "slim control" height).
- Chips: `px-2.5 py-0.5`–`py-1`.
- Flex rows: `gap-2` (8px, the default); icon clusters `gap-1.5`; dense metadata `gap-1`.
- Section rhythm inside panels: `space-y-3` (12px).
- Large paddings (`p-4`+, `gap-4`+) are rare — reserved for empty states and modal bodies. New code prefers `gap-*` over legacy `space-x/y-*`.

**Elevation — border-first, shadow-second:**
- Canonical hairline pair: **`border-gray-100 dark:border-gray-850`** (secondary dark: `border-gray-800`). A bare `border` is already a subtle hairline (default border color forced to `gray-200`).
- Build/HUD dark surfaces use white-alpha hairlines: `border-white/8`; Adaptive Space `.hud-panel`s use cyan-alpha `rgba(56,189,248,0.16)`.
- Shadows are sparse and reserved for floating layers: `shadow-lg` (dropdowns/popovers, composer), `shadow-xl` (larger overlays, tooltips), `shadow-2xl shadow-black/50` (run-card modal only). Rings are nearly absent (focus only). Frosted layers: `backdrop-blur-sm` / `backdrop-blur-xl` over translucent bg.
- **Motion:** bare `transition` (~150ms) on nearly every interactive element; explicit `duration-200`/`duration-300`; overlays enter via `flyAndScale` (`y:-8, start:0.95, 200ms, cubicOut`); loaders use `animate-pulse`/`animate-spin`/`animate-ping`; honor `prefers-reduced-motion` on anything that loops (`motion-reduce:animate-none`).
- **Z-index tiers:** `z-50` = sidebar + standard in-page overlays; `z-9999` = modal scrim. Don't invent intermediate mega-values.

---

### 4. Design direction — "Claude paper shell + Manus workspace"

The calm target is a two-layer feeling: a **Claude-style paper shell** — warm, quiet, editorial chrome with a clean Appearance submenu (System / Light / Dark, extended to named themes), hairline borders, lots of air, restrained small type, and reading-comfortable surfaces — wrapped around a **Manus-style workspace**: airy, glanceable, data-first panels built from pastel-tinted stat cards (tinted top over a white/`/5` delta footer), a sectioned sidebar with a single active pill, status/tier pills, pill-dropdown toolbars, and soft charts with a floating hover-tooltip card. The Build cockpit is the workspace half rendered inside the calm shell: it should read like an operator's console that is *quiet by default* — near-black blue-charcoal in Midnight, cool light-gray in Airy — with the cyan signature concentrated in HUD/live surfaces and everything else matter-of-fact. The unifying discipline across both layers is the anti-"vibecoded" rule: character comes from consistency (one gray ramp, one accent, one icon grammar, one border pair, one radius logic), never from per-page invention — which is exactly what lets Warm/Airy/Midnight stay a config swap rather than a rewrite.

---

### 5. Do / Don't for restyling a component

**Do**
- Use `gray-*` / `blue-*` token classes for **every** surface, border, and text color, always with paired `dark:` variants — these are what the theme registry rewrites.
- Use `dark:bg-gray-850` for dark panels; `border-gray-100 dark:border-gray-850` for hairlines; trust that a bare `border` is already correct.
- Keep the ramp's *roles* intact: `gray-800` raised, `gray-850` panel, `gray-900` shell, `gray-950` deepest — so the component survives every theme (Midnight/Slate/OLED/Airy/Warm) untouched.
- Keep type small and weights restrained: `text-sm`/`text-xs` bodies, `font-medium` emphasis, `font-semibold` headings; rem-based sizes so they scale with `--app-text-scale`.
- Default surfaces to `rounded-xl` (rows/menus) / `rounded-2xl` (containers); pills and dots `rounded-full`.
- Express hover/active with translucent tints (`*-500/10`, `black/5`, `white/5`) and border changes; keep elevation border-first, reserve shadows for popovers/overlays.
- Reuse the in-house icon set (`src/lib/components/icons/`, 178 components): 24-grid `viewBox`, `stroke="currentColor"`, `strokeWidth` 1.5 default, `aria-hidden` on the svg, `aria-label` on the wrapping button, Tooltip-wrapped.
- Use stock semantic palettes for state color only: `red` danger, `amber` live/attention, `green`/`emerald` success, `cyan`/`sky` HUD.
- Build content-shaped skeletons (same geometry as the real row, `bg-black/5 dark:bg-white/5`, staggered `animate-pulse`, `motion-reduce:animate-none`, `sr-only` status) — not bare spinners.
- Verify the component renders correctly under Midnight, Airy, AND Warm (paper + serif + coral) before calling it done — that's the token-discipline proof.

**Don't**
- Don't hardcode hex/rgb/`bg-[#…]` in a component — it opts out of every theme override. The `FileNav/*` and `ModelActivityChart.svelte` stragglers are debt, not precedent.
- Don't invent a new gray step, accent, radius, or border pair when an existing recipe fits — reuse is the brand.
- Don't reach for purple/violet/indigo gradients, glassmorphism-everywhere, or glow effects outside the Adaptive Space HUD — cyan-on-near-black *is* the brand; purple-gradient slop is the tell of vibecoded UI. (Indigo is allowed **only** as the Airy light-theme accent token, never hardcoded.)
- Don't use `font-bold`+ (reserved for the wordmark) or scale headings past `text-2xl` outside heroes/empty states.
- Don't paste one-off inline SVGs — add/reuse an icon component.
- Don't add a visible focus ring where the system uses border-state (`outline-hidden`); high-contrast mode handles the opt-in.
- Don't add solid fills where a `/10` tint is the convention, or invent z-index mega-values (`z-50` in-page, `z-9999` modals).
- Don't fabricate data in UI — no invented benchmarks, meters, or usage bars (established project rule; the cost/usage meters must reflect real values).

Sources: `/home/user/Harvis/front_end/owui/DESIGN.md`, `/home/user/Harvis/front_end/owui/DESIGN-REFERENCES.md`, `/home/user/Harvis/front_end/owui/src/lib/themes.ts`, `/home/user/Harvis/front_end/owui/src/tailwind.css`.

## Build cockpit — current state + restyle punch-list

Read-only audit of the two surfaces we're about to restyle. Files:
- Composer: `/home/user/Harvis/front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte` (island `1820`–`2368`)
- Header: `/home/user/Harvis/front_end/owui/src/lib/agent-studio/build/BuildHeader.svelte` (bar `46`–`281`)
- Baseline: `/home/user/Harvis/front_end/owui/DESIGN.md`

### Design-system baseline (what "on-token" means here)

Per DESIGN.md the system is deliberately narrow: **one gray ramp** (custom OKLCH `gray-*`, with `gray-850` as the workhorse dark-panel token), **one accent** (the re-hued cyan-leaning `blue-*` ramp — `bg-blue-600` light / `blue-500` dark *is* the primary-action token; sky/cyan is reserved for the Adaptive HUD, not Build CTAs), **one border pair** (`border-gray-200 dark:border-white/10`), soft `rounded-xl`/`rounded-2xl` geometry, **hairline borders preferred over shadows**, and semi-transparent state tints on the **/10 · /20** scale. The canonical Send button recipe (MessageInput) is `bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400 transition rounded-full p-1.5`. Measured against that, both surfaces drift on accent hue, border pair, radii, and opacity scale.

---

### 1. Composer — sub-element inventory (`+page.svelte`)

| Element | Line | Current classes (key parts) |
|---|---|---|
| Island wrapper | `1820`–`1821` | `w-full max-w-4xl mx-auto rounded-2xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-gray-900 p-2.5 shadow-lg shadow-black/30` |
| Image chip (img) | `1831` | `h-14 w-14 object-cover rounded-lg border border-gray-200 dark:border-gray-800` |
| Image chip (file) | `1834` | `rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-850` |
| Image remove ✕ | `1840` | `size-4 rounded-full bg-gray-700 text-white text-[10px]` |
| Exec-target chip | `1852`–`1853` | `text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800` |
| Exec dropdown | `1882`–`1883` | `rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-lg` |
| Repo chip | `1917`–`1918` | `text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 …` |
| Repo dropdown | `1940`–`1941` | `rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800` |
| Seeding/writeback status | `2003`–`2005` | `text-[11px] text-gray-500 dark:text-gray-400` |
| Reconnect banner | `2015`–`2016` | `text-[11px] px-2.5 py-1.5 border border-amber-500/20 bg-amber-500/10 text-amber-300` — **no `rounded-*`** |
| Orchestrate "sizing" banner | `2032` | `px-2.5 py-1.5 rounded-lg bg-amber-500/8 border border-amber-500/20 text-amber-300` |
| Orchestrate "split?" banner | `2037` | `px-3 py-2 rounded-lg bg-violet-500/8 border border-violet-500/25` |
| ↳ "Keep single" btn | `2044` | `text-[11px] px-2.5 py-1 rounded-md text-gray-400 hover:text-gray-700 …` |
| ↳ "Split" btn | `2045` | `rounded-md border border-violet-500/30 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25` |
| Textarea | `2052`–`2054` | `text-sm bg-transparent py-2 pl-2 pr-10 …text-gray-800 dark:text-gray-100 placeholder:text-gray-500` |
| **Send button** | `2068`–`2071` | armed: `size-7 rounded-lg bg-blue-600 hover:bg-blue-500 text-white shadow-sm`; disabled: `bg-black/[0.03] dark:bg-white/[0.05] text-gray-500` |
| Run-mode pill | `2104`–`2111` | `text-xs px-2.5 py-1 rounded-full border`; plan=`border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-600`; full-auto=`border-amber-500/20 bg-amber-500/10 text-amber-300`; else=`border-sky-500/20 bg-sky-500/10 text-sky-300` |
| Run-mode dropdown | `2138`–`2139` | `rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800` |
| Agents toggle | `2185`–`2191` | `text-xs px-2.5 py-1 rounded-full border`; on=`border-violet-500/30 bg-violet-500/12 text-violet-300`; auto=`border-amber-500/30 bg-amber-500/12 text-amber-300`; off=`border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-400` |
| Attach "+" btn | `2218`–`2219` | `text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 p-1.5` |
| Attach menu | `2226`–`2227` | `rounded-2xl bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-800 shadow-lg` |
| Mic (placeholder) | `2275`–`2276` | `text-gray-600 p-1.5 cursor-default` (dead control, always shown) |
| Model selector chip | `2297`–`2298` | `text-[11px] px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-600 hover:bg-black/[0.06] dark:hover:bg-white/10` |
| Model menu | `2306` | `rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-xl` |
| Model menu check | `2315` | literal `✓` char, `text-blue-500` |
| Usage gauge btn | `2326`–`2327` | `text-[10px] text-gray-500 px-1.5 py-1 hover:bg-black/[0.04] dark:hover:bg-white/[0.06]` |
| Usage bar | `2335`–`2336` | `w-14 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800`; fill `{ctxPct>85 ? 'bg-red-500' : 'bg-blue-500'}` |
| Usage popover | `2340` | `rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-xl` |
| Send error | `2366` | `text-[11px] text-red-500 mt-1` |

### 2. Header — sub-element inventory (`BuildHeader.svelte`)

| Element | Line | Current classes (key parts) |
|---|---|---|
| Header bar | `46`–`47` | `h-11 px-4 border-b border-gray-200 dark:border-white/10 bg-gray-100 dark:bg-gray-950` |
| "Build" label | `52` | `text-gray-500` (no dark variant) |
| "/" separator | `54` | `text-gray-700` (no dark variant) |
| Project name | `55` | `text-gray-800 dark:text-gray-100 font-medium` |
| Meta status dot | `65`–`66`, `74`–`75` | running=`bg-blue-500 animate-pulse`, idle=`bg-emerald-500` |
| Meta strip wrap | `84` | `text-[10px] text-gray-400` |
| Repo chip | `86`–`88` | `px-1.5 py-0.5 rounded border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05]` |
| Branch chip | `92`–`98` | same shell; base=`text-gray-500`, arrow=`text-gray-600`, work=`text-gray-600 dark:text-gray-300` |
| SHA chip | `102` | same shell + `font-mono text-gray-500` |
| Clean chip | `108`–`109` | `rounded border border-emerald-500/15 bg-emerald-500/8 text-emerald-400/90` |
| Dirty chip | `113`–`114` | `rounded border border-amber-500/15 bg-amber-500/8 text-amber-400/90` |
| Lifecycle chip | `119`–`132` | blocked=`border-amber-500/15 bg-amber-500/8 text-amber-400/90`, else=`border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-400`; dot running=`bg-emerald-400 animate-pulse`, ready=`bg-emerald-500`, blocked=`bg-amber-500`, else=`bg-gray-500` |
| Discord chip | `149`–`150` | `text-xs px-2.5 py-1 rounded-lg text-indigo-200 border border-indigo-400/25 bg-indigo-500/12 hover:bg-indigo-500/20` |
| **Stop button** | `164`–`165` | `text-xs px-2.5 py-1 rounded-lg text-red-400 border border-red-500/20 bg-red-500/8 hover:bg-red-500/14` |
| **Create PR button** | `172`–`173` | `text-xs px-2.5 py-1 rounded-lg text-white border border-sky-400/20 bg-sky-500/80 hover:bg-sky-500` |
| ⋯ menu btn | `184`–`187` | `p-1.5 rounded-lg hover:bg-black/[0.04] dark:hover:bg-white/[0.06]` |
| Panels dropdown | `204`–`205` | `rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-white/10 shadow-xl` |
| Panel checkbox | `215`–`218` | checked=`bg-blue-600 border-blue-600`, unchecked=`border-gray-600` |
| Settings btn | `254`–`255` | `p-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-black/[0.04] dark:hover:bg-white/[0.06]` |

---

### 3. Styling inconsistencies vs a calm token system

**A. Two accents for "primary action" (the loudest problem).** The composer Send is blue (`bg-blue-600`, the accent token) but the header Create PR is sky (`bg-sky-500/80`, a HUD color). The two most prominent buttons in the cockpit are different hues. Sky also leaks into the run-mode pill's default state (`bg-sky-500/10 text-sky-300`, `2111`) and the dock's active-tab underline (`bg-sky-400`, `2408`), while everything else "active" is blue (`bg-blue-500`, PaneResizer `2372`, usage bar `2336`, model check `2315`, run-mode current dot `2164`). **Pick one: blue = primary action, sky retired from Build.**

**B. Send button diverges from the canonical Send recipe** (`2069`–`2071`). Three deviations: `rounded-lg` instead of `rounded-full`; `hover:bg-blue-500` *lightens* the fill in light mode instead of the canonical `hover:bg-blue-700` darken; and it has **no dark-mode variant** (`dark:bg-blue-500 dark:hover:bg-blue-400`), so in dark mode it sits at the too-dark light-mode value. Plus `shadow-sm` on the button contradicts the "hairline over shadows" rule.

**C. Three different border pairs inside one composer.** Canonical is `border-gray-200 dark:border-white/10` (island `1821`, model chip `2298`, run-mode/agents off states). But image chips use `border-gray-200 dark:border-gray-800` (`1831`, `1834`), and every dropdown uses `border-gray-100 dark:border-gray-800` (`1883`, `1941`, `2139`, `2227`, `2306`, `2340`). The header itself is clean on this (`dark:border-white/10` throughout) — so the composer is the outlier.

**D. Chips don't match each other.** The exec and repo chips are solid-fill `bg-gray-100 dark:bg-gray-850` (`1853`, `1918`); the model chip is translucent `bg-black/[0.03] dark:bg-white/[0.05]` (`2298`); the run-mode and agents chips are tinted-border `rounded-full` pills (`2106`, `2187`). Four visual treatments for what are all "context selectors" in one composer. The header meta chips are a fifth treatment (`rounded` — 4px — vs the composer's `rounded-lg`/`rounded-full`).

**E. Radius soup.** Composer alone spans `rounded-lg` (chips, send, image chips), `rounded-full` (pills, remove-✕, usage bar), `rounded-xl` (dropdowns), `rounded-2xl` (island, attach menu, usage popover), `rounded-md` (orchestrate buttons). Dropdown surfaces are `rounded-xl` in the composer but `rounded-lg` in the header (`205`). Header meta chips are bare `rounded`.

**F. Off-scale opacity tints everywhere.** DESIGN prefers `/10` fills, `/20` borders. Actual values in use: `/8` (`165` red, `109`/`114`/`122` emerald+amber, `2032` amber), `/12` (`150` indigo, `2188` violet, `2190` amber), `/14` (`165` red hover), `/15` (`109`/`114`/`122` borders). These `/8 · /12 · /14 · /15` steps read as accidental precision, not a system.

**G. Two different "running" colors in the same header.** The meta status dot uses `bg-blue-500 animate-pulse` for running (`66`/`75`), but the lifecycle chip dot uses `bg-emerald-400 animate-pulse` for running (`127`) — and its "ready" state is `bg-emerald-500` (`131`), so running vs ready are two nearly-identical greens while a third element calls running blue.

**H. Reconnect banner has no radius** (`2015`) — sharp corners in a fully-rounded composer. A visible break.

**I. Hardcoded / off-token grays.** Image remove-✕ is `bg-gray-700` (`1840`, a flat mid-gray bubble, not a token tint). Panel-checkbox unchecked border is `border-gray-600` with no light/dark pair (`218`) — heavy on a light dropdown. Dropdown dark surfaces split between `dark:bg-gray-900` (most menus) and `dark:bg-gray-850` (attach menu `2227`) with no reason.

**J. Off-palette one-off.** The Discord chip is indigo (`text-indigo-200 border-indigo-400/25 bg-indigo-500/12`, `150`) — indigo appears nowhere in the DESIGN palette summary (blue/sky/amber/red/emerald/cyan). It's the only indigo in either surface.

**K. Mixed check glyphs.** The model menu uses a literal `✓` text character (`2315`); the repo and exec menus use SVG checkmarks (`1961`, `1896`). Different weights/baselines for the same affordance.

**L. Busy/dead elements.** The mic button (`2275`) is a permanently-disabled "coming soon" control taking toolbar space with no hover and a distinct `text-gray-600` (vs the attach "+" beside it at `text-gray-500`, `2219`) — two adjacent icon buttons at different grays, one of them inert.

**M. Header separator/label have no dark variants.** `text-gray-500` (`52`) and `text-gray-700` (`54`) — the `/` at gray-700 is a low-contrast smudge in dark mode next to the `dark:text-gray-100` project name.

---

### 4. Prioritized restyle punch-list (per element → change)

**P0 — accent unification (highest visual payoff)**

1. `BuildHeader.svelte:173` — Create PR: replace `border-sky-400/20 bg-sky-500/80 hover:bg-sky-500` with the accent token `bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400 border-blue-600/20`. Makes the header CTA match the composer Send hue.
2. `+page.svelte:2069-2071` — Send: change `rounded-lg` → `rounded-full`, `hover:bg-blue-500` → `hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400`, drop `shadow-sm`. Adopt the canonical Send recipe exactly.
3. `+page.svelte:2111` — run-mode default (Ask/Accept/Auto) state: replace `border-sky-500/20 bg-sky-500/10 text-sky-300` with the blue accent tint (`border-blue-500/20 bg-blue-500/10 text-blue-400`), retiring sky from the composer.
4. `+page.svelte:2408` — dock active-tab underline `bg-sky-400` → `bg-blue-500`, matching the PaneResizer hover (`2372`) and usage bar.

**P1 — border pair + radius normalization**

5. `+page.svelte:1831, 1834` — image chips: `dark:border-gray-800` → `dark:border-white/10` (canonical pair).
6. `+page.svelte:1883, 1941, 2139, 2227, 2306, 2340` — all composer dropdown/menu surfaces: `border-gray-100 dark:border-gray-800` → `border-gray-200 dark:border-white/10`; standardize radius (all menus `rounded-xl`) and dark surface (`dark:bg-gray-900`) so the attach menu at `2227` (`rounded-2xl`, `dark:bg-gray-850`) stops being the odd one.
7. `BuildHeader.svelte:205` — panels dropdown `rounded-lg` → `rounded-xl` to match composer menus.
8. `BuildHeader.svelte:87, 93, 102, 109, 114, 121` — meta chips: bump bare `rounded` → `rounded-md` so header chips aren't sharper than composer chips.

**P1 — chip treatment convergence**

9. `+page.svelte:1853, 1918` — exec + repo chips: move off solid `bg-gray-100 dark:bg-gray-850` onto the same translucent token as the model chip (`bg-black/[0.03] dark:bg-white/[0.05]` + `border border-gray-200 dark:border-white/10`, `2298`) so the three context selectors read as one family. (Decide one radius for all three — `rounded-lg`.)
10. `+page.svelte:2298` — model chip: already the reference; leave as the canonical chip recipe the others adopt.

**P2 — opacity scale + state colors**

11. Normalize off-scale tints to `/10` fill · `/20` border: `BuildHeader.svelte:165` (`bg-red-500/8`, `hover:bg-red-500/14`), `109`/`114`/`122` (`/15` borders + `/8` fills → `/20` + `/10`), `150` (`bg-indigo-500/12`); `+page.svelte:2032` (`bg-amber-500/8`), `2188` (`bg-violet-500/12`), `2190` (`bg-amber-500/12`).
12. `BuildHeader.svelte:127` — lifecycle "running" dot `bg-emerald-400 animate-pulse` → `bg-blue-500 animate-pulse` so running (blue) is distinct from ready (`bg-emerald-500`, `131`) and consistent with the meta dot (`66`/`75`).

**P2 — one-offs & dead chrome**

13. `+page.svelte:2015` — reconnect banner: add `rounded-lg` (matches the orchestrate banners at `2032`/`2037`).
14. `+page.svelte:1840` — image remove-✕: `bg-gray-700` → a token bubble (`bg-gray-800/80 dark:bg-white/15` or an accent-neutral tint) so it isn't a flat mid-gray.
15. `BuildHeader.svelte:218` — checkbox unchecked border `border-gray-600` → `border-gray-300 dark:border-gray-600` (light/dark pair; DESIGN checkbox recipe).
16. `+page.svelte:2315` — model-menu check: replace literal `✓` with the same SVG check used at `1896`/`1961`, `size-4 text-blue-500`.
17. `+page.svelte:2275-2291` — mic placeholder: either remove until wired, or drop to `text-gray-400` and align padding/hover with the attach "+" (`2219`) so two adjacent icon buttons don't differ.
18. `BuildHeader.svelte:150` — Discord chip indigo is the only off-palette hue; if kept for brand recognition, leave it, but flag it as the single sanctioned exception (otherwise move to blue accent).

**P3 — polish**

19. `BuildHeader.svelte:52, 54` — add dark variants: `text-gray-500` and the `/` `text-gray-700` → `text-gray-700 dark:text-gray-400` so the breadcrumb reads in dark mode.
20. `+page.svelte:1821` — island `shadow-lg shadow-black/30` is heavier than the "hairline over shadows" guideline; soften to `shadow-md shadow-black/20` (and mirror on the dock panel at `2385`, outside strict scope but the same pattern).

Note: `bg-blue-600` on the Send button (`2071`) and panel checkbox (`217`) is **on-token** per DESIGN (the blue ramp is the accent), so despite the "blue vs accent?" phrasing in the brief, the fix is not to recolor blue — it's to make everything *else* stop competing with it (sky, indigo) and to correct the Send button's hover direction / missing dark variant / radius.

## Reference patterns

Distilled from the Harvis reference library (`front_end/owui/DESIGN-REFERENCES.md` — Ref 2 Claude.ai "Warm/paper" is the anchor for the Build composer/header restyle) plus how the strongest coding-agent cockpits actually style their composer and session header (Cursor 2.x, Claude Code desktop, OpenAI Codex app, Vercel/Linear as the "quiet-pro" north star). Everything below is adoptable against Harvis's calm-paper direction — cream/warm-charcoal canvas, one accent (coral in Warm / cyan in Midnight), hairline borders, air over chrome.

### Composer chrome (the prompt input)

- **One bordered "card", controls docked inside it — not floating around it.** Cursor, Claude Code, and Codex all put the model picker, mode, and attach *inside the same rounded input surface* as the textarea, in a thin control strip along the bottom edge. The send button is the only thing on the right. This reads as a single instrument, not a toolbar + a box. For Harvis: one `rounded-xl` cream panel with a hairline warm border, textarea on top, a low bottom strip holding the pickers. Do not scatter pill buttons above/beside the input.
- **Pickers are quiet text-with-caret, not filled buttons.** In Cursor the model name lives as plain text at the bottom-left of the prompt input; clicking it opens the picker. The resting state is label-only (e.g. `qwen2.5-coder ▾`), muted foreground, no fill, no border — border/tint appears only on hover/open. This is the single biggest "pro not busy" lever: a composer with four filled/colored pill buttons looks vibecoded; the same four as muted text-carets looks like a tool. Apply to Harvis's model / engine / mode / repo selectors.
- **Mode selector as a named, explicit control with safety semantics.** Cursor's Agent / Plan / Ask and Codex's approval profiles are first-class, and the *ordering carries meaning* (read-only → planning → acting). Harvis already has an Auto|Plan pill (VibeCode) and lane governance — surface mode as one small segmented control in the strip, with Plan/read-only visually calmer (no accent) and the acting mode carrying the single accent. Never use red/green fills for modes; reserve semantic color.
- **Attach / repo as leading-edge icon affordances.** A paperclip (attach) and a repo/branch chip sit at the bottom-left before the pickers. Keep the repo chip as *text* (`owner/repo` + branch caret), not a boxed badge — it's context, not an action.
- **Send affordance: single accent, disabled-until-content, ⌘↵ hinted.** The send button is the *only* saturated element in the whole composer — this is what makes the accent mean "the primary action." Circular or small rounded, accent fill (coral/cyan), arrow or ↑ glyph. Disabled (muted, no fill) when the textarea is empty. Show the `⌘↵` / `Ctrl↵` hint as faint text near it rather than a tooltip-only secret. When a run is active, this same button becomes **Stop** (square glyph, neutral or muted-danger) — one button, two states, no second button appearing.
- **Voice/mic as an inline icon, opt-in.** Cursor docks a mic in the input for dictation. Harvis is voice-first, so a mic belongs in the strip — but as a quiet line icon, not an accented CTA competing with send.
- **Let the box breathe and grow.** Generous internal padding, comfortable line-height, auto-grow to a few lines then scroll. Claude.ai's calm comes largely from *air inside the input*. Placeholder is a real sentence in muted foreground ("Describe a change, or ask about this repo"), not "Type a message…".

### Session / run header meta (branch · SHA · status)

- **Header is a single hairline-bottomed strip of muted metadata, not a banner.** Codex's `/status` model is the template: model + working directory shown compactly. For Harvis Build: `repo · branch · short-SHA · model` as one line of muted text with hairline separators (middot or thin vertical rules), left-aligned. No card, no fill, no shadow — it's a caption, not a hero.
- **Status is a dot, never a fill.** This is the sharpest Vercel/Linear rule: "status indicators exist in small dot-sized badges, never as background fills or large swaths." A 6–8px colored dot + one word (`● Running`, `● Idle`, `● Needs review`) reads pro; a full amber/green pill background reads busy/dashboardy. Use the semantic hue on the *dot only*; keep the label text in normal muted foreground. Reserve motion (a soft pulse) for the running state only.
- **Branch/SHA are monospace, and lock state is legible.** Show the branch and short-SHA in the mono face (mono earns its place here — it signals "real git state"). Harvis's branch-lock header already exists; render the lock as a small line icon before the branch name, not a colored badge. If on `main` and writes are refused, that guardrail should read as a quiet muted note, not an alarm.
- **Git identity is context, actions are elsewhere.** The header states *where you are* (branch, SHA, dirty/clean). Actions (Create PR, commit, open run) live as their own restrained buttons in a right-aligned cluster or a drawer — don't mix "state you're reading" with "buttons you press" in the same visual weight. At most one of those actions carries the accent at a time.
- **Progressive disclosure over a wall of meta.** Show `repo · branch · SHA · model · ● status` at rest; tuck token/cost, run-id, and timings behind a hover or an expand. Codex/Claude-Code keep the resting header sparse and let `/status`-style detail be on demand.

### Calm/quiet styling (what makes it feel "pro" not "busy")

- **Color only where it must appear: one accent for the primary action + focus rings, semantic hues only as dots.** Vercel's rule verbatim — "color appears only when it must: blue marks interactive elements and focus states." For Harvis calm-paper: coral (Warm) / cyan (Midnight) is the *single* accent, spent on send + focus + the one active mode. Everything else is warm-charcoal text on cream with hairline borders. A composer/header with three or four competing colors is the tell of generic AI UI.
- **Hairlines and whitespace instead of shadows and fills.** Ref 2 (Claude.ai) and Ref 1 both lean on hairline borders + low-contrast dividers + air. Separate the composer from the transcript with a hairline and spacing, not a drop-shadow or a filled bar.
- **Density is fine — noise is not.** Linear/Vercel are *dense* yet calm because the density is information (git state, tokens, mode) laid on a strict grid with restrained color, not decorative chrome. Pack the meta tightly on an 8px rhythm; don't pad it into a big empty banner, but don't let any of it shout.
- **Muted-by-default, one focal point.** Bold/hero weight is spent only on the thing you want looked at first (the empty-state prompt, or the active run title). Meta, pickers, hints all sit in muted foreground. "Eliminate flat visual weight" cuts both ways — nothing decorative should be as loud as the primary action.
- **Icons: single-weight quiet line icons.** Consistent stroke, muted color, accent only on the active/primary one. Mixed icon styles or filled colored icons in the strip is a busy-tell.
- **Warm mono for code-adjacent bits.** In the paper direction, the composer/header's git tokens and code hints can use a warm-toned mono so they feel native to a coding cockpit without breaking the editorial calm of the surrounding sans/serif.

### Pitfalls to avoid

- **Filled/colored pill buttons for model, mode, engine, repo.** The #1 vibecoded tell. Make them muted text-carets; tint only on hover/open.
- **More than one accent-colored element in view at once.** If send *and* a mode chip *and* a status badge are all saturated, nothing is primary. One accent at a time.
- **Status as a full-background pill (amber/green/red fills).** Use a dot + word. Fills belong on dashboards, not on a coding-agent header.
- **A separate Stop button that appears next to Send during a run.** Toggle the one button's state — avoid layout shift and a second CTA.
- **A hero/banner header with a shadowed card and big title.** The session header is a caption strip; keep it hairline-bottomed and muted. Save serif/display weight for the empty-state greeting, not the running header.
- **`Type a message…` placeholder + generic icons + Inter.** The named-defaults trap. Give the placeholder a real sentence, use one deliberate type voice per theme (Warm = editorial serif/humanist sans, mono for git), and a consistent line-icon set.
- **Even, timid 16px-everywhere spacing.** Adopt the 8px rhythm so the strip reads as engineered, not floated.
- **Semantic color used decoratively** (green/red for non-status things like modes or accents). Green/amber/red must mean run-state only, or they stop meaning anything.
- **Cramming every meta value into the resting header.** Show identity + status at rest; hide tokens/cost/run-id/timings behind hover or expand.
- **Losing the Harvis brand while chasing calm.** Keep the robot mascot + wordmark and the accent hue per theme; adopt the *rhythm, restraint, and component grammar* from the references — not their exact palette or a wholesale serif-body switch outside the Warm theme.

Sources: [Cursor Composer / agent modes / model picker](https://cursor.com/docs/agent/prompting) · [Cursor 2.0 tutorial (Composer, modes)](https://www.devshelfhub.com/articles/cursor-2-tutorial-beginners/) · [Claude Code desktop docs](https://code.claude.com/docs/en/desktop) · [Superdesign — "dense but calm" vs AI slop](https://superdesign.dev/blog/claude-code-ui-design) · [OpenAI Codex app (worktrees, project threads)](https://openai.com/index/introducing-the-codex-app/) · [Codex CLI /status header](https://developers.openai.com/codex/cli/features) · [Vercel design language — restraint, dot status, color-only-when-it-must](https://www.setproduct.com/blog/complete-guide-to-blueprint-grid-design) · [Vercel DESIGN.md capture](https://github.com/educlopez/design-bites/blob/main/design-mds/vercel.com/DESIGN.md)

## Remaining work + theme-settings status

### (1) Ordered remaining-work list

Two source docs, both live and consistent. The handoff's "TOMORROW'S LIST" is the user-dictated ordering; the plan-of-action is the code-grounded, per-phase expansion of it. Nothing on either list shows as shipped — the 2026-07-17 handoff states "Nothing committed or pushed today" and the whole list is forward work. The one exception I could verify in code is called out inline.

**TOMORROW'S LIST — verbatim from `docs/handoffs/2026-07-17-eod-launcher-prototype-tomorrow-list.md` (user-ordered):**
1. Go through **Settings, Notebook, Code/Build UI** — ensure functionality.
2. **Fix the Settings UI.**
3. Make **another mascot**.
4. Adjust the UI for **loading** (skeletons) and **workspace** stuff.
5. **Deploy test** again (owui build → restart nginx; backend restart if touched).
6. **Push** (only after user verifies E2E — standing rule), then **test again**.
7. Create the **main website**.
8. Then **Adaptive Space**.
9. **`install.sh` help / installer UX** — hardening + help pass (`--help`, preflight checks, `.env` scaffolding incl. OPENCLAW_GATEWAY_TOKEN/JWT_SECRET generation), NOT greenfield. Slots around step 5–6.

**PLAN-OF-ACTION phases — `docs/plans/2026-07-18-plan-of-action.md` (code-grounded expansion, same ordering):**
- **Phase 1 — Functionality pass: Settings · Notebook · Build**
  - *1a Settings:* fix the `presence_penalty`/`repeat_penalty` copy-paste bug (`General.svelte`); fix theme-divergence bug; kill/implement dead Account save + DataControls routes (facade gaps); remove `defaultModelId` reset trap (Interface tab); strip dead Personalization/Connections/About weight.
  - *1b Notebook — BLOCKING lane decision:* promote the orphaned native page (Option A) vs keep the un-themeable `/onb` iframe (Option B); either way fix silent error-swallowing.
  - *1c Build cockpit:* add real degraded/error states; port `PlanPanel` off its own SSE stream to shared `subscribeRun`; decide `WorkspaceRightRail` (delete vs resurrect as inline approvals); hide dead affordances; unify status colors.
- **Phase 2 — Settings UI redesign** (calm direction; fold the Theme `<select>` into an Appearance submenu — one `selectTheme()` path).
- **Phase 3 — New mascot** (themeable `HarvisMark`-style variant; David picks from 2–3 sketches first).
- **Phase 4 — Loading + workspace polish** (fix `app.html` splash `harvis-dark` rule mismatch/flash; generalize skeletons; tokenize the hardcoded-dark Build cockpit so Airy/Warm don't get a dark slab).
- **Phase 5 — Deploy test** (full rebuild, cache-busted pass over Chat/Settings/Notebook/Build in all 3 themes on :9000).
- **Phase 6 — Push (gated) + retest** (ASK first; `harvis1.1` ~25 ahead).
- **Phase 7 — install.sh help/UX pass** (= tomorrow-list item 9).
- **Phase 8 — Main website** (static landing, reuse Warm-paper + new mascot).
- **Phase 9 — Adaptive Space** (resume ringed-HUD `b0963d3a`; re-scope after 1–8).

**Blocking decisions David must make (from the plan):** (1) Notebook lane A vs B; (2) `WorkspaceRightRail` delete vs resurrect; (3) explicit push go; (4) mascot pick; (5) where composer mode-switching lives (launcher mode-pills were removed).

**Already-done note:** Within Phase 1a, the **theme-divergence bug is already fixed** in the current code (see below) — the plan's description of it reflects an earlier state. The `presence_penalty`/`repeat_penalty` bug it's grouped with is **still open**.

### (2) Theme-changer status — VERDICT: available and working

**Yes — a user can see and change themes from the shipping UI.** Verified against code, not memory.

- **Where it lives:** `/home/user/Harvis/front_end/owui/src/lib/components/chat/Settings/General.svelte` — a `<select>` dropdown (lines 146–159) that iterates the registry `THEMES` and calls `themeChangeHandler → applyThemeById`.
- **Registry / wiring:** `/home/user/Harvis/front_end/owui/src/lib/themes.ts` (`THEMES[]` + `applyThemeById`). The same `applyThemeById` is the desktop `theme:update` handler in `/home/user/Harvis/front_end/owui/src/routes/+layout.svelte:783`, and boot restores from `localStorage.theme`. One code path, correctly shared.
- **Nav path:** account/user menu → **Settings** (`UserMenu.svelte:242` → `showSettings.set(true)`), which opens `SettingsModal.svelte` on its default **General** tab; the Theme picker is the first row ("WebUI Settings → Theme"). Also reachable via the Navbar `Menu.svelte:295` and `SidebarMore.svelte`.
- **Themes exposed** (from `THEMES[]`, rendered except egg-gated): System 🖥️, **Midnight** 🌑 (`dark`), Slate 🤖 (`harvis-dark`), OLED 🌃 (`oled-dark`), Light ☀️, **Airy** 🌤️, **Warm** 📜, and Her 🌷 (hidden unless `enable_easter_eggs`). All three target themes — **Warm / Airy / Midnight — are present and selectable.**

**Confirmed fixed (was a plan headline):** the theme-divergence bug is resolved. `General.svelte:127-129` now routes through `applyThemeById` with **no** legacy inline `--color-gray-800..950` overrides, and `themes.ts:40` confirms Midnight (`dark`) leaves `vars` empty so re-selecting Dark no longer neutralizes the ramp to `#171717`. So "Dark from Settings ≠ Dark after reload" no longer applies.

**Gaps / caveats (real, verify-backed):**
1. **UI is still a plain `<select>`, not the "Appearance submenu."** The account-menu Appearance submenu described in the handoff exists only in the isolated `front_end/harvis-ui-prototype/`, NOT in the shipping owui app. Plan Phase 2 explicitly plans to fold this `<select>` into an Appearance submenu — future work.
2. **Dead vestigial array:** `General.svelte:18` still declares `let themes = ['dark','light','oled-dark','harvis-dark']`, which nothing reads anymore (the `#each` iterates `THEMES`). Harmless dead code; safe to delete.
3. **Airy/Warm don't reach everywhere.** The theme only tokenizes the app shell. The **Build cockpit is hardcoded dark** (`bg-[#080c16]`/`bg-[#0b101b]` raw hex across BuildHeader/WorkspaceMainPanel/BrowserPanel/ShellTab) so Airy/Warm show a dark slab there (Phase 4). The **Notebook `/onb` iframe cannot be themed at all** (Phase 1b Option-B limitation). And the `app.html` splash rule (`html.harvis-dark #splash-screen`) never matches boot's `theme-harvis-dark` class, causing a color flash on load, and Airy/Warm flash `#fff` (Phase 4). None of these break the picker; they're where the theme fails to propagate.
4. **Not re-verified visually in Airy/Midnight** per handoff pending item 4 — token-driven so it should inherit, but no screenshot confirmation on the launcher.

## Proposed restyle plan (sequenced, low-risk)

Every change below is a **token-only class swap** in two files — no logic, no structure, no new components, each a one-line reversible edit. Order is highest-visual-payoff first (accent unification), then normalization, then one-offs; the broader handoff list follows once the two cockpit surfaces ship and pass a three-theme deploy test. The governing token rules for all of Steps 1–2 are the Design-contract recipe: accent is `blue-*` (`bg-blue-600` light / `bg-blue-500` dark; the canonical Send button is `bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400 transition rounded-full p-1.5`); border pair is `border-gray-200 dark:border-white/10` with hairline hover `border-gray-100 dark:border-gray-850`; radii default `rounded-xl` (menus) / `rounded-2xl` (containers) / `rounded-full` (pills); state tints are `/10` fill · `/20` border; **no raw hex** so Warm/Airy/Midnight stay a config swap.

### Step 1 — Composer (`.../(app)/harvis/vibecode/+page.svelte`)

Do the accent fixes first (they carry the whole "one primary action" read), then borders/radii, then chips, then the polish one-offs.

| # | Line(s) | Edit | Rule it satisfies |
|---|---|---|---|
| 1 | `2069`–`2071` | Send: `rounded-lg`→`rounded-full`; `hover:bg-blue-500`→`hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400`; drop `shadow-sm` | Canonical Send recipe; hairline-over-shadows (P0-2, incons. B) |
| 2 | `2111` | run-mode default state `border-sky-500/20 bg-sky-500/10 text-sky-300` → `border-blue-500/20 bg-blue-500/10 text-blue-400` | Retire sky from Build; blue = active (P0-3, incons. A) |
| 3 | `2408` | dock active-tab underline `bg-sky-400` → `bg-blue-500` | Matches PaneResizer `2372` + usage bar `2336` (P0-4) |
| 4 | `1831`, `1834` | image chips `dark:border-gray-800` → `dark:border-white/10` | One border pair (P1-5, incons. C) |
| 5 | `1883`, `1941`, `2139`, `2227`, `2306`, `2340` | all menu surfaces `border-gray-100 dark:border-gray-800` → `border-gray-200 dark:border-white/10`; all `rounded-xl`; dark surface `dark:bg-gray-900` (fix attach menu `2227` off its lone `rounded-2xl`/`dark:bg-gray-850`) | One border pair + one menu radius + one dark surface (P1-6, incons. C/E/I) |
| 6 | `1853`, `1918` | exec + repo chips: solid `bg-gray-100 dark:bg-gray-850` → translucent `bg-black/[0.03] dark:bg-white/[0.05]` + `border border-gray-200 dark:border-white/10`, radius `rounded-lg` (match model chip `2298`) | Three context selectors read as one family (P1-9, incons. D) |
| 7 | `2032`, `2188`, `2190` | opacity normalize `bg-amber-500/8`, `bg-violet-500/12`, `bg-amber-500/12` → `/10` fill (borders to `/20`) | One opacity system (P2-11, incons. F) |
| 8 | `2015` | reconnect banner: add `rounded-lg` | No sharp corner in a rounded composer (P2-13, incons. H) |
| 9 | `1840` | image remove-✕ `bg-gray-700` → `bg-gray-800/80 dark:bg-white/15` | Token tint, not flat mid-gray (P2-14, incons. I) |
| 10 | `2315` | model-menu check: literal `✓` → SVG check used at `1896`/`1961`, `size-4 text-blue-500` | One check glyph (P2-16, incons. K) |
| 11 | `2275`–`2291` | mic placeholder: drop to `text-gray-400` and align padding/hover with attach "+" (`2219`) — or remove until wired (**decision below**) | No inert mismatched icon button (P2-17, incons. L) |
| 12 | `1821` (and mirror `2385`) | island `shadow-lg shadow-black/30` → `shadow-md shadow-black/20` | Hairline-over-shadows (P3-20) |

Leave `2298` (model chip) and `2071`'s `bg-blue-600` fill untouched — they are already the reference recipe.

### Step 2 — Header (`.../agent-studio/build/BuildHeader.svelte`)

| # | Line(s) | Edit | Rule it satisfies |
|---|---|---|---|
| 1 | `173` | Create PR `border-sky-400/20 bg-sky-500/80 hover:bg-sky-500` → `bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400 border-blue-600/20` | Header CTA matches composer Send hue (P0-1, incons. A) |
| 2 | `205` | panels dropdown `rounded-lg` → `rounded-xl` | Menu radius matches composer (P1-7, incons. E) |
| 3 | `87`, `93`, `102`, `109`, `114`, `121` | meta chips bare `rounded` → `rounded-md` | Header chips no sharper than composer chips (P1-8, incons. D/E) |
| 4 | `165`, `109`/`114`/`122`, `150` | opacity normalize `bg-red-500/8`+`hover:bg-red-500/14`, `/15` borders + `/8` fills, `bg-indigo-500/12` → `/10` fill · `/20` border | One opacity system (P2-11, incons. F) |
| 5 | `127` | lifecycle "running" dot `bg-emerald-400 animate-pulse` → `bg-blue-500 animate-pulse` | Running (blue) distinct from ready `bg-emerald-500` `131`; matches meta dot `66`/`75` (P2-12, incons. G) |
| 6 | `218` | checkbox unchecked border `border-gray-600` → `border-gray-300 dark:border-gray-600` | Light/dark pair (P2-15, incons. I) |
| 7 | `52`, `54` | breadcrumb `text-gray-500` and `/` `text-gray-700` → add `dark:text-gray-400` | Breadcrumb readable in dark (P3-19, incons. M) |

### Verify (after Steps 1–2, before touching the list)

1. Deploy per the standing note: **owui build → restart nginx** (no backend touched here, so no backend restart). Access via the Nginx proxy at `:9000` — not the backend directly.
2. Switch **Midnight → Airy → Warm** in Settings → General (the picker at `General.svelte:146-159`, confirmed working) and confirm for each: Send and Create PR are the *same* blue; only **one** saturated element is in view at a time (no sky/violet/indigo competing); every run-state is a **dot**, not a fill; running is blue, ready/idle green — no two near-identical greens. Under **Warm specifically**, confirm the composer + header render on the cream paper canvas with serif body and coral accent **with zero component edits** — that is the token-discipline proof that nothing regressed to raw hex.
3. Because these two surfaces are already largely token-based, they should inherit Airy/Warm correctly. The surrounding cockpit panels are **not** yet (see the list) — expect the composer/header to be correct while `WorkspaceMainPanel`/`BrowserPanel`/`ShellTab` still show a dark slab in Airy/Warm; that mismatch is the Step-6 job, not a Step-1/2 regression.

### User decisions to flag (surface before merging Steps 1–2)

1. **Violet on orchestrate + agents controls** — the "split?" banner + Split button (`2037`, `2045`) and the agents toggle on/auto states (`2185`–`2191`) use `violet-500`. The Design contract and Reference patterns both say retire purple/violet (it's the "vibecoded" tell); the punch-list only normalizes its *opacity* (edit Step-1 #7). **Decision:** retire violet to the blue accent / neutral, or keep it as a sanctioned semantic hue meaning "orchestration/split." (Edits #7 above are opacity-only and don't presuppose the answer.)
2. **Discord chip indigo** (`BuildHeader.svelte:150`) — the only off-palette hue in either surface. **Decision:** keep as the single sanctioned brand exception, or move to the blue accent. Edit Step-2 #4 only normalizes its opacity for now.
3. **Mic placeholder** (`+page.svelte:2275`) — remove until the feature is wired, or keep muted at `text-gray-400`. Edit Step-1 #11 assumes "keep muted" as the reversible default.

### Step 3+ — the remaining handoff list (after the cockpit surfaces ship + verify)

Ordered per the handoff / plan-of-action; the composer/header restyle above is the surgical leading slice of the "Build cockpit" functionality/tokenization pass (Phase 1c / Phase 4), so it lands first and de-risks the rest.

3. **Functionality pass — Settings · Notebook · Build (Phase 1).** *Settings 1a:* the `presence_penalty`/`repeat_penalty` copy-paste bug in `General.svelte` is **still open** (the theme-divergence bug grouped with it is already fixed — verified); kill/implement dead Account save + DataControls routes; remove the `defaultModelId` reset trap; delete the vestigial `let themes = […]` array (`General.svelte:18`). *Notebook 1b:* **BLOCKING** lane decision A (promote native page) vs B (keep un-themeable `/onb` iframe); fix silent error-swallowing either way. *Build 1c:* real degraded/error states; port `PlanPanel` off its own SSE stream to shared `subscribeRun`; `WorkspaceRightRail` delete-vs-resurrect decision; unify status colors — this is where Step-2 #5 (running-dot color) generalizes.
4. **Settings UI redesign (Phase 2)** — fold the Theme `<select>` into an Appearance submenu on the one `selectTheme()`/`applyThemeById` path (the submenu currently exists only in `front_end/harvis-ui-prototype/`, not shipping owui).
5. **New mascot (Phase 3)** — themeable `HarvisMark`-style variant; David picks from 2–3 sketches first.
6. **Loading + workspace polish (Phase 4)** — fix the `app.html` splash rule (`html.harvis-dark` never matches boot's `theme-harvis-dark`, so it flashes; Airy/Warm flash `#fff`); generalize skeletons; and **tokenize the hardcoded-dark Build cockpit** — replace the raw-hex `bg-[#080c16]`/`bg-[#0b101b]` across `WorkspaceMainPanel`/`BrowserPanel`/`ShellTab` (and any remaining raw hex in `BuildHeader`) with `gray-*` tokens so Airy/Warm stop showing a dark slab. This is the direct continuation of Steps 1–2 to the rest of the cockpit surfaces; keep it token-only for the same reason.
7. **Deploy test (Phase 5)** — full cache-busted rebuild, all three themes on `:9000` across Chat/Settings/Notebook/Build.
8. **Push (Phase 6)** — **gated:** ask for explicit go first (standing rule), then retest. `harvis1.1` is ~25 commits ahead.
9. **install.sh help/UX (Phase 7 / list item 9)** — `--help`, preflight checks, `.env` scaffolding (incl. `OPENCLAW_GATEWAY_TOKEN`/`JWT_SECRET` generation); hardening, not greenfield. Slots around steps 7–8.
10. **Main website (Phase 8)** — static landing, reuse Warm-paper + the new mascot.
11. **Adaptive Space (Phase 9)** — resume the ringed-HUD work at `b0963d3a`; re-scope after everything above.

**Blocking decisions David owns (carry alongside the flags in Steps 1–2):** Notebook lane A vs B; `WorkspaceRightRail` delete vs resurrect; explicit push go; mascot pick; where composer mode-switching lives now that the launcher mode-pills were removed.

**Theme-settings status, for planning:** the picker ships and works — Warm/Airy/Midnight are all selectable via `General.svelte:146-159` → `applyThemeById`, and the theme-divergence bug is already fixed (`General.svelte:127-129`, `themes.ts:40`). The only theme gap that matters to this restyle is propagation, not the picker: Airy/Warm don't yet reach the Build cockpit body (Step 6), which is exactly why the token-only discipline in Steps 1–2 is the whole point.