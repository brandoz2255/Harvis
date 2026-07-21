# Harvis — Design System

Harvis is a self-hosted, voice-first agentic AI workspace — a forked OpenWebUI (SvelteKit + Tailwind v4) frontend on a Python orchestrator backend, built to be an open-source alternative to OpenWebUI and a full open Claude-style platform. Its visual identity: **dark-first** on a blue-charcoal OKLCH surface ramp that deepens to near-black, a **cyan-leaning blue accent** (the re-hued `blue-*` ramp targeting prototype `#38bdf8`), restrained small type (Inter body, Archivo display), soft `rounded-xl`/`rounded-2xl` geometry, hairline borders over shadows, a 178-component in-house icon set, and a glowing blue robot mascot. Everything flows through design tokens (`src/tailwind.css` + `src/app.css`); components never invent their own palette.

Repo root for all paths below: `front_end/owui/`.

## Brand & voice

- **Mascot**: `static/harvis-logo.svg` — a small robot rendered in a blue gradient (`#5B8DEF → #2F5FD8`) with a soft SVG glow filter. It appears in the sidebar header (swapping to the Sidebar icon on hover in the collapsed rail) and as the app mark. It is the one place a literal glow effect belongs.
- **Wordmark**: `.harvis-wordmark` (`src/app.css:134–140`) — Inter, `font-weight: 700`, `0.8125rem`, `letter-spacing: 0.26em`, uppercase. Used once: the sidebar "HARVIS" (`Sidebar.svelte:1084`, `text-gray-850 dark:text-white`). Bold weight is reserved for this logotype and nothing else.
- **Tone**: calm, competent, ambient. Harvis is a JARVIS-style operator's console, not a consumer toy — status is communicated with small pulsing dots, quiet heartbeat status lines ("Preparing workspace…"), and tinted chips, never with confetti, gradients-on-everything, or oversized hero type. Cyan glow is a *signature*, concentrated in the Adaptive Space HUD; the rest of the app stays near-black and matter-of-fact.
- **Anti-"vibecoded"**: the system's character comes from consistency — one gray ramp, one accent, one icon grammar, one border pair — not from per-page invention. If a new surface needs a color, weight, or radius that isn't already in this doc, that's a signal to reuse an existing recipe, not to add one.

## Color

All color in Harvis flows through two files: the Tailwind v4 `@theme` block in `src/tailwind.css` (which **overrides** Tailwind's stock `gray-*` and part of `blue-*` ramps with custom OKLCH values) and a runtime theme script in `src/app.html` that re-assigns the dark-end CSS variables per theme. Components never define their own palette — they use `gray-*` / `blue-*` utility classes plus stock Tailwind palettes for semantic states.

### Surface ramp — the blue-charcoal gray scale

The entire gray ramp is redefined in OKLCH with a subtle blue-charcoal cast (hue 255 at the light end, drifting to 262 at the near-black end, with chroma rising from 0.004 to 0.03 — darker surfaces are *more* blue, per the `@theme` comment: "Hue nudged 255→260 (slightly more blue)"). The intent: bridge the UI prototype's shell `#06080d` → panel `#0c1018` → raised `#131a26` stack, keeping light/mid grays for text and light mode while pulling the dark end toward near-black.

| Token | OKLCH | Hex ≈ | Role |
|---|---|---|---|
| `gray-50` | `oklch(0.98 0.004 255)` | `#f7f9fb` | Light-mode page background |
| `gray-100` | `oklch(0.94 0.006 255)` | `#e8ebef` | Light-mode hover / subtle fill |
| `gray-200` | `oklch(0.92 0.008 255)` | `#e1e5ea` | Default border color (set globally in `@layer base`: `border-color: var(--color-gray-200)`) |
| `gray-300` | `oklch(0.85 0.01 255)` | `#c9ced4` | Muted borders, disabled |
| `gray-400` | `oklch(0.77 0.012 255)` | `#afb5bc` | Placeholder text (global `input::placeholder`) |
| `gray-500` | `oklch(0.69 0.014 255)` | `#969ca4` | Secondary text |
| `gray-600` | `oklch(0.51 0.018 255)` | `#5f6771` | Tertiary text / dark-mode borders |
| `gray-700` | `oklch(0.42 0.022 257)` | `#464e59` | Body text on light |
| `gray-800` | `oklch(0.2 0.026 258)` | `#0f1622` | **Raised** dark surface (cards, inputs) |
| `gray-850` | `oklch(0.14 0.028 259)` | `#040915` | **Panel** dark surface — the most-used dark background (362 `dark:bg-gray-850` occurrences) |
| `gray-900` | `oklch(0.095 0.03 260)` | `#00030b` | **Shell / page** dark background |
| `gray-950` | `oklch(0.055 0.03 262)` | `#000004` | Deepest shell (sidebar scrim, overlays) |

Note the non-standard **`gray-850`** step — it is the workhorse dark-panel token; use it, not `gray-800` or `gray-900`, for panel backgrounds in dark mode.

### Accent — the blue ramp, re-hued to cyan

Only `blue-400`–`blue-700` are overridden; the stated goal: "prototype cyan (#38bdf8): re-hue the blue ramp toward sky/cyan so buttons, active states, and the send control read cyan, not royal blue." Steps outside 400–700 fall back to Tailwind's stock blue.

| Token | OKLCH | Hex ≈ | Role |
|---|---|---|---|
| `blue-400` | `oklch(0.79 0.12 230)` | `#5cc9f9` | Accent on dark (closest to the prototype's `#38bdf8`) |
| `blue-500` | `oklch(0.72 0.135 233)` | `#31b2eb` | Focus rings (`focus:ring-blue-500` on checkboxes) |
| `blue-600` | `oklch(0.64 0.145 235)` | `#0098d7` | Primary buttons, checked checkbox fill (`bg-blue-600`) |
| `blue-700` | `oklch(0.55 0.13 237)` | `#007bb3` | Pressed / hover-darkened accent |

### Semantic colors

There are **no custom semantic tokens** — components use stock Tailwind palettes by convention (counts from a repo-wide grep of `.svelte` files):

- **Danger / error:** `red-*` (`text-red-500` ×84, `bg-red-500` ×39; e.g. error panes in `src/lib/components/common/FileItemModal.svelte`, `PDFViewer.svelte`). Dark-mode error surfaces pair `bg-red-950` with `text-red-200`.
- **Warning / pending:** `amber-*` (`bg-amber-500` ×55, `text-amber-300/400/500`), with `yellow-*` as a minority variant. Light warning surfaces use `bg-amber-50` / `text-amber-700`; dark use `bg-amber-950`.
- **Success / running-healthy:** `green-*` and `emerald-*` interchangeably (`bg-green-500` ×28, `text-emerald-400` ×29; e.g. `src/lib/components/common/Switch.svelte`, `automations/AutomationEditor.svelte`).
- **Info / HUD accent:** `cyan-*` and `sky-*` (`text-cyan-300` ×28, `border-cyan-400` ×24) — concentrated in the Adaptive Space HUD (`src/lib/agent-studio/adaptive/*.svelte`: `ToolDock`, `ResourceBoard`, `RepoRunnerSurface`), where cyan is the JARVIS-style signature.

Color-role summary: **blue/sky = active & primary action**, **amber = live/attention**, **red = danger**, **green/emerald = success**, **cyan = HUD signature**. Semi-transparent tints (`*-500/10`, `*-400/10`, `black/5`, `white/5`) are preferred over solid fills for hover and state backgrounds.

### Rule: no raw hex in components — use tokens

Any surface, border, or text color must go through the `gray-*` / `blue-*` utility classes (i.e. the CSS variables), or it will not respond to the `oled-dark` / `harvis-dark` runtime theme overrides (see **Theming**). Stock Tailwind semantic palettes (red/amber/green/cyan) are acceptable for state colors since themes don't override them. A handful of legacy raw-hex stragglers exist (e.g. `#6b7280`, `#9ca3af` in `src/lib/components/chat/FileNav/*` viewers and `admin/Evaluations/ModelActivityChart.svelte`) — treat these as debt, not precedent.

## Typography

### Font families and roles

All fonts are self-hosted in `static/assets/fonts/` and declared with `@font-face` + `font-display: swap` in `src/app.css` (lines 3–31):

| Family | File | Role |
|---|---|---|
| **Inter** (variable) | `Inter-Variable.ttf` | Body/UI text. Part of the base `html, pre` stack and the wordmark. |
| **Archivo** (variable) | `Archivo-Variable.ttf` | Display face via `.font-primary` — modal titles, onboarding, sidebar headers (~44 uses). |
| **Mona Sans** | `Mona-Sans.woff2` | Declared but **currently unused** — the `@font-face` exists but no class or rule references it. |
| **InstrumentSerif** (Regular) | `InstrumentSerif-Regular.ttf` | Editorial accent via `.font-secondary` — used exactly once, the OnBoarding hero (`text-5xl lg:text-7xl font-secondary`). Note: `InstrumentSerif-Italic.ttf` ships in the fonts dir but has **no** `@font-face`. |
| **Vazirmatn** (variable) | `Vazirmatn-Variable.ttf` | RTL/Persian-script support — sits in both the base stack and the `.font-primary` fallback chain. |
| **JetBrainsMono** | — | Referenced by name (`.tiptap pre` in `app.css:613`, and xterm's `fontFamily` in `ShellTab.svelte:61`) but there is **no `@font-face` and no font file** — it only renders if installed locally, otherwise it falls to `monospace`/`ui-monospace`. |

**Base body stack** (`src/tailwind.css:49–56`, applied to `html, pre`):

```css
font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Vazirmatn',
  ui-sans-serif, system-ui, 'Segoe UI', Roboto, Ubuntu, Cantarell,
  'Noto Sans', sans-serif, 'Helvetica Neue', Arial,
  'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji';
```

Note the platform system font (`-apple-system`/`BlinkMacSystemFont`) is *ahead* of Inter — on macOS the UI renders in the system font; Inter is the cross-platform fallback.

**Display classes** (`src/app.css`):

```css
.font-primary   { font-family: 'Archivo', 'Vazirmatn', sans-serif; }   /* line 128 */
.font-secondary { font-family: 'InstrumentSerif', sans-serif; }        /* line 73 */
```

**Code**: Tailwind's default `font-mono` utility (ui-monospace stack) is the workhorse — 132 uses across Svelte components; inline/marked code applies `font-mono` via `@apply` in `app.css` (lines 392, 623).

### Type scale (actual usage frequency, grep of `src/**/*.svelte`)

The UI is a **small-type system** — `text-xs`/`text-sm` dominate by ~15:1 over everything larger:

| Class | Size | Count | Where it lives |
|---|---|---|---|
| `text-xs` | 0.75rem | **1,861** | Metadata, chips, labels, sidebar, tooltips |
| `text-sm` | 0.875rem | **1,360** | Default control/body text |
| `text-lg` | 1.125rem | 95 | Section/modal titles |
| `text-base` | 1rem | 67 | Chat/message body |
| `text-xl` | 1.25rem | 33 | Page headings |
| `text-2xl` | 1.5rem | 29 | Large headings |
| `text-3xl` | 1.875rem | 18 | Hero/empty-state |
| `text-4xl` | 2.25rem | 1 | — |

Below `text-xs` there is a real **micro tier** of arbitrary values: `text-[11px]` (315 uses) and `text-[10px]` (209 uses) for dense chips, badges, and timestamps, plus a scatter of `text-[13px]`, `text-[12px]`, `text-[0.65rem]`, `text-[0.6rem]`. Prose-heading sizes are set in `.input-prose-sm` (`prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg`, `app.css:102`).

### Weight scale (restrained: normal → medium → semibold)

| Class | Count | Convention |
|---|---|---|
| `font-medium` | **1,213** | The default emphasis weight — labels, buttons, titles |
| `font-semibold` | 162 | Headings (also `prose-headings:font-semibold` in `.markdown-prose` / `.input-prose`) |
| `font-normal` | 49 | De-emphasis resets (e.g. `prose-blockquote:font-normal`) |
| `font-bold` | 2 | Effectively unused — bold is reserved for the wordmark (`font-weight: 700`) |
| `font-light` | 1 | — |
| `font-extrabold` / `font-black` | 0 | Never |

Rule of thumb for new UI: **medium for emphasis, semibold for headings, never bold.**

### Line heights

- Tailwind defaults carry most text; explicit utilities are sparse: `leading-relaxed` (68 uses, longer body copy), `leading-none` (16, chips/stat numerals), `leading-snug` (11), `leading-tight` (6). `leading-normal`/`leading-loose` are unused.
- **AI-response prose** gets deliberate rhythm via `.markdown-prose` (`app.css:105–114`): `prose-p:leading-7 prose-p:my-3 prose-li:leading-7 prose-li:my-1 prose-headings:mt-5 prose-headings:mb-2.5` — a documented Harvis fix for the "wall of text" default. `.markdown-prose > :first-child` zeroes `margin-top` so the first block aligns with the avatar. Compact variants `.markdown-prose-sm` / `.markdown-prose-xs` collapse margins to near-zero at `text-sm` / `text-xs`.

### UI scale variable — `--app-text-scale`

The whole document scales through one custom property (`app.css:33–60`):

```css
:root { --app-text-scale: 1; }
html  { font-size: calc(1rem * var(--app-text-scale, 1)); }
```

- Set at runtime by `setTextScale()` in `src/lib/utils/text-scale.ts` (writes the property on `document.documentElement`), driven by the UI Scale slider in `src/lib/components/chat/Settings/Interface.svelte` (persisted as `settings.textScale`; a value of `1` is stored as `null`).
- Because it multiplies the root `font-size`, **every rem-based Tailwind size scales automatically**. Pixel-sized chrome that must stay in sync does so explicitly — `#sidebar-chat-item` multiplies its `min-height: 32px`, padding, and `line-height: 20px` by the same variable.
- Implication for new components: **prefer rem/`text-*` utilities over `px` font sizes** so they participate in UI scaling (the `text-[11px]`/`text-[10px]` micro tier does *not* scale).

## Layout, spacing & motion

### Spacing rhythm

Tailwind's default 4pt scale, used **tight and half-stepped** — the app leans on 2px granularity (`0.5`, `1.5`, `2.5`, `3.5` suffixes) far more than a typical Tailwind app. Measured frequencies across `src/lib/components` + `src/routes`:

| Utility | Count | Role |
|---|---|---|
| `gap-2` (8px) | 609 | the default flex gap — icon+label rows, chip groups |
| `gap-1` / `gap-1.5` (4/6px) | 188 each | dense icon clusters, inline metadata |
| `px-3` (12px) | 488 | default horizontal padding for buttons, inputs, rows |
| `py-1.5` (6px) | 432 | default vertical padding — the signature "slim control" height |
| `py-2` / `py-1` | 312 / 286 | slightly taller/shorter controls |
| `px-2.5` / `px-3.5` | 180 / 135 | pill and chip padding |
| `space-x-2`, `space-x-4` | 69 / 49 | legacy OWUI stacks (new code prefers `gap-*`) |
| `space-y-3` (12px) | 34 | vertical section rhythm inside panels |

**Rule of thumb:** controls are `px-3 py-1.5`, chips are `px-2.5 py-0.5`/`py-1`, flex rows are `gap-2`, icon clusters `gap-1.5`. Large paddings (`p-4`+, `gap-4`+) are rare and reserved for empty states and modal bodies.

### Border-radius scale

Soft and rounded throughout — `rounded-lg`/`rounded-xl` dominate, with `rounded-2xl` for cards/modals and `rounded-full` for pills, dots and avatars:

| Class | Count | Typical use |
|---|---|---|
| `rounded-lg` (8px) | 445 | buttons, small controls, inline previews |
| `rounded-xl` (12px) | 402 | list rows (sidebar chat items), dropdown menus, panel sections |
| `rounded-full` | 376 | pills, status dots, count badges, avatars |
| `rounded-2xl` (16px) | 147 | cards, popovers, modal shells (e.g. `WorkspaceRunCard.svelte:715`) |
| `rounded-sm` / `rounded-md` | 105 / 65 | tiny inline elements, skeleton bars |
| `rounded-3xl` | 35 | hero surfaces only (plus the composer and user chat bubble) |

New surfaces should default to `rounded-xl` (interactive rows/menus) or `rounded-2xl` (containers). Radii scale with prominence: `rounded-lg` rows → `rounded-xl` popovers/nav → `rounded-2xl`/`rounded-3xl` feature surfaces.

### Borders & elevation

- **The canonical hairline pair is `border-gray-100 dark:border-gray-850`** (300 and 238 uses respectively) — e.g. `WorkspaceRightRail.svelte:86`, `ArtifactPreview.svelte:81`. Secondary dark border: `border-gray-800` (166 uses).
- The Tailwind v4 compat layer in `src/tailwind.css` forces the **default border color to `var(--color-gray-200)`** (≈ `#e1e5ea`) on all elements, so a bare `border` is already a subtle hairline.
- Build/HUD dark surfaces use white-alpha hairlines instead: `border-white/8` (vibecode page, run cards) and cyan-alpha `rgba(56,189,248,0.16)` on Adaptive Space `.hud-panel`s.
- **Elevation is border-first, shadow-second.** Shadows are sparse: `shadow-lg` 62 uses (dropdown menus, popovers), `shadow-xl` 16 (larger overlays), `shadow-sm` 11, `shadow-2xl` 2 (the run-card modal uses `shadow-2xl shadow-black/50`). Rings are nearly absent (`ring-1`×5, `ring-2`×6 — focus states only). Frosted layers use `backdrop-blur-sm` (12) / `backdrop-blur-xl` (8) with translucent backgrounds.

### App shell layout

- **Sidebar**: width is a CSS variable — `w-[var(--sidebar-width)]` (`Sidebar.svelte:1060`), default **260px** (`lib/stores/index.ts:91`), user-draggable between **`MIN_WIDTH = 220`** and **`MAX_WIDTH = 480`** (`Sidebar.svelte:526-527`), persisted to `localStorage.sidebarWidth`. The sidebar itself sits at `z-50`. Width animation uses the custom `transition-width` property registered in `tailwind.config.js` (`transitionProperty: { width: 'width' }`).
- **Chat column**: messages and composer are both centered at **`max-w-6xl`** — `Messages/Message.svelte:52` (`max-w-6xl mx-auto`, switching to `max-w-full` when `$settings.widescreenMode`) and `MessageInput.svelte:1364` (same conditional). The empty-state greeting (`Placeholder.svelte`) uses a `max-w-6xl` outer container with an inner `md:max-w-3xl` prose column.
- **Modals** (`common/Modal.svelte`): fixed size map — `xs w-[16rem]`, `sm w-[30rem]`, `md w-[42rem]` (default), `lg w-[56rem]`, `xl w-[70rem]`, `2xl w-[84rem]`, `3xl w-[100rem]`; scrim `bg-black/30 dark:bg-black/60` at `z-9999`.
- **Build (vibecode) layout** (`routes/(app)/harvis/vibecode/+page.svelte`): a **paneforge `PaneGroup`** (line 1677) splitting a resizable left **chat `<Pane minSize={32}>`** (line 1679) from a right `<Pane>` (line 2336). Inside the right pane, the **tabbed workspace dock** is `flex: 1 1 100%` and compresses to **`flex: 0 0 38%`** (`order-last`, `border-l border-white/8`) when the `WorkflowInspector` opens beside it as the `order-first flex-1` region (lines 2342, 2450); the chat column narrows only via pane resizing, not that flex rule. The right dock swaps tabs between `WorkspaceFileRail` (files/artifacts), `PlanPanel`, `ShellTab`, `BrowserPanel`, background-task cards, and `WorkspaceMainPanel` (diff/logs hosting `RunView mode="dock"`).

### Z-index tiers

Observed tiers, lowest to highest: in-page layering `z-0 → z-10` (57 uses) `→ z-20 → z-30 → z-40`; **`z-50` = sidebar + standard overlays** (52 uses); **`z-9999` = modal scrim tier** (`Modal.svelte:124`, `EmojiPicker`, `FilesOverlay`, `ImagePreview`); above-modal escape hatches go to `z-[9999999]`/`z-99999999` (floating buttons, link previews). New overlays: use `z-50` in-page, `z-9999` for true modals; don't invent intermediate mega-values.

### Motion

- **Baseline**: the bare `transition` utility appears 849 times — nearly every interactive element transitions colors/opacity at Tailwind's default 150ms. Explicit durations cluster at **`duration-200`** (17) and `duration-300` (9), easing `ease-in-out` (18). `transition-all` (45) and `transition-colors` (22) for targeted cases; `transition-width` (11) for the sidebar/panels.
- **Overlays**: dropdowns and modals enter with the custom `flyAndScale` Svelte transition (`lib/utils/transitions/index.ts`) — defaults `y: -8, start: 0.95, duration: 200`, `cubicOut` easing.
- **Live/loading indicators**: `animate-pulse` (29) for skeletons and live dots, `animate-spin` (15) for spinners, `animate-ping` (10) for attention beacons.
- **Custom keyframes** (`src/app.css`): `.shimmer` — a background-clip:text sweep (`shimmer 1.5s cubic-bezier(0.7, 0, 1, 0.4) infinite`, light `#b4b4b4`/`#e8e8e8`, dark `#9a9a9a`/`#5e5e5e`) used for streaming status text; `.status-description` — `smoothFadeIn 0.2s` (fade + `translateY(-10px)→0`); `.fade-in-token` — `100ms ease-out` opacity fade for streamed tokens.
- **Chat-loading progression** (`chat/Chat.svelte` ~1200-1290): a "task heartbeat" status line starts the instant a message sends. Task-ish messages (matched by `_TASKISH_RE`) step through 6 stages at `0 / 1.5s / 3.5s / 7s / 13s / 22s` — "Understanding the request…" → engine check ("Checking Claude Code…"/"Choosing an engine…") → "Preparing workspace…" → engine start → "Starting the run…" → "Still working…". Plain Q&A gets a gentler 5-stage ladder at `0 / 2s / 5s / 9s / 16s`, ending in "Still working — local models can take a moment…". Both self-clear on first streamed token, completion, or the workspace-run marker.
- **Build live lineup** (`agent-studio/RunView.svelte`, `mode="stream"`): the running Build turn renders inside an `h-80 rounded-xl border border-white/8 bg-[#0b101b]` wrapper (`vibecode/+page.svelte:1723`) as a lean Cursor-style step feed — filename-aware step labels via `stepLabel()` ("Editing hello.txt", not "Using edit_file") with a `size-1.5 rounded-full bg-blue-500 dark:bg-blue-400 animate-pulse` live dot.
- **Reduced motion**: honored where animation is decorative — `motion-reduce:animate-none` on skeleton bars, and `@media (prefers-reduced-motion: reduce)` blocks in `AdaptiveSpaceShell.svelte` (lines 724, 759) disable the mic pulse and "shaping dots". This is the pattern to follow for any new looping animation; coverage elsewhere is currently sparse.

## Components

All recipes below are copied from live components under `src/lib/components/`. Grays and blues are the custom OKLCH ramp from the **Color** section.

### Icons — in-house set (`src/lib/components/icons/`, 178 components)

Every icon is a standalone Svelte component following one template (see `Check.svelte`, `ChatBubble.svelte`):

```svelte
<script lang="ts">
	export let className = 'size-4';   // 99 files; 69 older files use 'w-4 h-4'
	export let strokeWidth = '1.5';    // 144/178 default to 1.5
</script>

<svg aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none"
	viewBox="0 0 24 24" stroke-width={strokeWidth} stroke="currentColor" class={className}>
	<path stroke-linecap="round" stroke-linejoin="round" d="…" />
</svg>
```

Rules (measured across the directory):
- **Grid**: `viewBox="0 0 24 24"` (169/178 files; the rest are 16/20 grid legacy Heroicons).
- **Color**: `stroke="currentColor"` (or `fill="currentColor"` for solid variants) — 178/178. Icons inherit text color; never hardcode.
- **Stroke**: default `1.5`; callers override per density — `1` (Navbar Knobs), `1.75` (composer chips), `2`–`2.5` (small ≤`size-3.5` icons so they stay legible).
- **A11y**: `aria-hidden="true"` on the `<svg>` (174/178). The accessible name lives on the wrapping button's `aria-label`, never on the icon.
- **Sizes in practice**: `size-3.5`, `size-4`, `size-4.5`, `size-5`, `size-5.5` (Tailwind v4 fractional sizes are used freely).
- Optical nudges are idiomatic: `translate-y-[0.5px]` aligns icons with adjacent text (MessageInput, ChatItem).

### Buttons

**Primary (Send)** — `MessageInput.svelte` `#send-message-button`. Round, blue when armed, gray when empty:
```
bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400 transition rounded-full p-1.5
```
Disabled/empty state swaps to `text-white bg-gray-200 dark:text-gray-900 dark:bg-gray-700 disabled` plus the `disabled` attribute. While uploading it shows `<Spinner className="size-5" />` in place of the arrow.

**Inverted primary (Voice mode)** — black/white flip per scheme:
```
bg-black text-white hover:bg-gray-900 dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full p-1.5
```

**Text-button trio** (message-edit Save / Cancel / Save-as-copy, `ResponseMessage.svelte` + `UserMessage.svelte`) — pill shape `px-3.5 py-1.5 … transition rounded-3xl`:
- Solid: `bg-gray-900 dark:bg-white hover:bg-gray-850 text-gray-100 dark:text-gray-800`
- Ghost: `bg-white dark:bg-gray-900 hover:bg-gray-100 text-gray-800 dark:text-gray-100`
- Bordered: `bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 border border-gray-100 dark:border-gray-700 text-gray-700 dark:text-gray-200`

**Icon-only, composer** (the `+` menu, integrations, valves) — fixed 32px circle:
```
bg-transparent hover:bg-gray-100 text-gray-700 dark:text-white dark:hover:bg-gray-800 rounded-full size-8 flex justify-center items-center outline-hidden focus:outline-hidden
```

**Icon-only, navbar** (`Navbar.svelte`) — square-ish `rounded-xl`, subtler hover:
```
flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition
```

**Message action buttons** (copy/edit/regenerate rows) — translucent overlay hover, revealed on message hover:
```
p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition
```
prefixed with `{isLastMessage || highContrastMode ? 'visible' : 'invisible group-hover:visible'}`. Sibling-pager chevrons use the tighter `p-1 … rounded-md` variant with `stroke-width="2.5"` at `size-3.5`, count as `text-sm tracking-widest font-semibold`.

**Toggle chips** (Web Search / Image / Code Interpreter / filters in the composer) — the on/off pattern:
```
group p-[7px] flex gap-1.5 items-center text-sm rounded-full transition-colors duration-300 focus:outline-hidden max-w-full overflow-hidden
```
- ON: `text-sky-500 dark:text-sky-300 bg-sky-50 hover:bg-sky-100 dark:bg-sky-400/10 dark:hover:bg-sky-600/10 border border-sky-200/40 dark:border-sky-500/20`
- OFF: `bg-transparent text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800`
- A dismiss `<XMark className="size-4" strokeWidth="1.75" />` sits in `hidden group-hover:block`.

**Amber = attention** variants: pending OAuth tool chip `text-amber-600 dark:text-amber-400 bg-amber-50 hover:bg-amber-100 dark:bg-amber-400/10 dark:hover:bg-amber-600/10 border border-amber-200/40 dark:border-amber-500/20`; Deep Research toggle `bg-amber-500/15 text-amber-500 hover:bg-amber-500/25 rounded-full size-8`.

**Live-activity chips** (Navbar "Harvis on Discord is running" / "Agent review live"):
```
flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-xl bg-blue-500/10 hover:bg-blue-500/20 text-blue-600 dark:text-blue-400 transition
```
with a pulsing dot: outer `animate-ping absolute … rounded-full bg-blue-400 opacity-75` over solid `relative inline-flex rounded-full size-2 bg-blue-500`. Amber twin for reviews (`bg-amber-500/10 … bg-amber-500`).

**Mode/model pill** (dropdown trigger): `flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition` + status dot `size-1.5 rounded-full` + inline chevron svg at `size-3 opacity-70` `stroke-width="2.5"`.

### The composer (`chat/MessageInput.svelte`)

Column: `max-w-6xl px-2.5 mx-auto` (`max-w-full` in widescreen mode), wrapped in `w-full font-primary`. The shell `#message-input-container`:
```
flex-1 flex flex-col relative w-full shadow-lg rounded-3xl border
border-gray-100/30 dark:border-gray-850/30
hover:border-gray-200 focus-within:border-gray-100 hover:dark:border-gray-800 focus-within:dark:border-gray-800
transition px-1 bg-white/5 dark:bg-gray-500/5 backdrop-blur-sm dark:text-gray-100
```
Temporary chat swaps the border to `border-dashed border-gray-100 dark:border-gray-800`. Key idioms:
- `rounded-3xl` + `shadow-lg` + translucent `bg-white/5 dark:bg-gray-500/5 backdrop-blur-sm` — the composer is glassy, not solid.
- State is expressed on the **border** via `hover:` / `focus-within:` (no focus ring).
- Editor area: `RichTextInput` inside `scrollbar-hidden … bg-transparent dark:text-gray-100 outline-hidden w-full pb-1 px-1 resize-none h-fit max-h-96 overflow-auto`.
- Bottom toolbar: `flex justify-between mt-0.5 mb-2.5 mx-0.5` — left cluster (`+` menu, mic, chips), right cluster (`self-end flex space-x-1 mr-1 shrink-0`) with note/mode-pill/send. Vertical divider between clusters: `w-[1px] h-4 mx-1 bg-gray-200/50 dark:bg-gray-800/50`.
- Scroll-to-bottom FAB (floats `-top-12`): `bg-white border border-gray-100 dark:border-none dark:bg-white/20 p-1.5 rounded-full`.
- Attached-file thumbnails: `size-10 rounded-xl object-cover` with a remove button `bg-white text-black border border-white rounded-full` that is `group-hover:visible invisible transition`.

### Cards, panels, dropdown menus

**Dropdown panel** (mic menu, mode menu — the canonical popover recipe):
```
rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1 w-56 text-sm
```
Inside it: menu row `w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-gray-50 dark:hover:bg-gray-800 transition`; section header `px-2.5 pt-1 pb-1 text-[10px] uppercase tracking-wide text-gray-400`; divider `my-1 border-t border-gray-100 dark:border-gray-800`; selected item gets a `size-4 text-blue-500` check.

**Inline panels**: queued-messages tray `rounded-2xl bg-white dark:bg-gray-900/60 border border-gray-100 dark:border-gray-800/50`; message-edit card `w-full bg-gray-50 dark:bg-gray-800 rounded-3xl px-3 py-3`.

### Chat bubbles — user vs assistant

**Only USER messages are bubbled.** `UserMessage.svelte` right-aligns via `flex justify-end pb-1`, bubble:
```
rounded-3xl max-w-[90%] px-4 py-1.5 bg-gray-50 dark:bg-gray-850
```
(`rounded-tr-lg` clips the top-right corner when files are attached; the whole thing is gated by `$settings?.chatBubble ?? true` — off means plain full-width.)

**Assistant messages are full-width, no bubble, no avatar gutter** — `ResponseMessage.svelte` documents it in-code: *"the assistant response is 'the AI's domain' — no avatar gutter, so it spans the full centered conversation column."* Structure: `flex w-full` → `flex-auto w-0 relative` → content `chat-assistant w-full min-w-full markdown-prose`. Model name renders through `<Name>` with a Tooltip; timestamp is `text-xs font-medium text-gray-400 invisible group-hover:visible transition`. The action row underneath: `flex justify-start overflow-x-auto buttons text-gray-600 dark:text-gray-500 mt-0.5`. While a response is pending with no content it renders a `<Skeleton />`; task runs show a heartbeat line — `text-sm text-gray-500 dark:text-gray-400` with spinner `size-3 rounded-full border-2 border-gray-400/40 border-t-gray-500 dark:border-t-gray-300 animate-spin`.

### Tooltips (`common/Tooltip.svelte`)

A tippy.js wrapper, not CSS-only. Defaults: `placement="top"`, `offset=[0, 4]`, `arrow: false`, theme `'dark'`, `allowHTML` with content passed through `DOMPurify.sanitize`. Styling lives in `src/app.css`:
```css
.tippy-box[data-theme~='dark'] { @apply rounded-lg bg-gray-950 text-xs border border-gray-900 shadow-xl; }
.tippy-box[data-theme~='transparent'] { @apply bg-transparent p-0 m-0; }
```
Usage idiom — every icon-only control is wrapped:
```svelte
<Tooltip content={$i18n.t('Copy')} placement="bottom">
	<button aria-label={$i18n.t('Copy')} class="…">…</button>
</Tooltip>
```
The wrapper renders a `<svelte:element this={as}>` (default `div.flex`), so `className` on Tooltip controls layout (`className=" flex items-center"` is common).

### Sidebar & list rows

Sidebar (`layout/Sidebar.svelte`): translucent `bg-gray-50/70 dark:bg-gray-950/70` on desktop (solid `bg-gray-50 dark:bg-gray-950` on mobile), width `w-[var(--sidebar-width)]` (see **App shell layout**), with `transition:slide={{ duration: 250, axis: 'x' }}`. Collapsed rail keeps a hairline `border-e-[0.5px] border-gray-50 dark:border-gray-850/30` and swaps the logo for the Sidebar icon on hover (`group-hover:hidden` / `hidden group-hover:flex`).

Chat row (`Sidebar/ChatItem.svelte`) — the list-row recipe:
```
w-full flex justify-between rounded-xl px-[11px] py-[6px] whitespace-nowrap text-ellipsis
```
- Active chat: `bg-gray-100 dark:bg-gray-900 selected`
- Menu-open/selected: `bg-gray-100 dark:bg-gray-950 selected`
- Hover: `group-hover:bg-gray-100 dark:group-hover:bg-gray-950`
- Title: `h-[20px] truncate text-[13px] font-normal`; unread `text-gray-700 dark:text-gray-200`, read `text-gray-500 dark:text-gray-400`.
- The `⋯` menu is absolutely positioned at the right, `invisible group-hover:visible`, sitting on a fade mask: `pl-5 bg-linear-to-l from-80% to-transparent from-gray-100 dark:from-gray-950` so long titles fade under it instead of clipping. Shift+hover swaps it for direct Archive/Delete buttons.
- Drag ghost: `bg-black/80 backdrop-blur-2xl px-2 py-1 rounded-lg w-fit max-w-40` with `text-xs text-white`.

### Skeleton loaders

`Sidebar/ChatItemSkeleton.svelte` is the reference implementation — **content-shaped, same geometry as the real row** so rows swap in with zero layout shift:
```svelte
<div class="w-full rounded-xl px-[11px] py-[6px]">
	<div class="h-[20px] flex items-center">
		<div class="h-[13px] rounded-md bg-black/5 dark:bg-white/5 animate-pulse motion-reduce:animate-none"
			style="width: {widths[i % widths.length]}; animation-delay: {i * 90}ms;"></div>
	</div>
</div>
```
Rules it encodes: bar color `bg-black/5 dark:bg-white/5`; `animate-pulse` staggered 90 ms per row; varied widths (46–90%) so it reads like real titles; `motion-reduce:animate-none`; the whole block `aria-hidden="true"` with one `<span class="sr-only" role="status">` loading line.

### Interaction states — the shared vocabulary

| State | Recipe | Where |
|---|---|---|
| Hover (solid surface) | `hover:bg-gray-100 dark:hover:bg-gray-850` (subtle tier: `hover:bg-gray-50 dark:hover:bg-gray-800`) | navbar, sidebar, menu rows |
| Hover (over content) | `hover:bg-black/5 dark:hover:bg-white/5` | message action buttons |
| Reveal on parent hover | `invisible group-hover:visible transition` (or `hidden group-hover:block`) — forced always-visible when `$settings.highContrastMode` | message actions, chip dismiss, file remove, row menus |
| Focus | `outline-hidden focus:outline-hidden` — no visible ring by default; high-contrast mode opts back in | composer buttons, chips |
| Active/selected | tinted fill + accent text: `bg-sky-50 dark:bg-sky-400/10 text-sky-500` (chips), `bg-gray-100 dark:bg-gray-900` (rows), `text-blue-500` check (menus) | chips, sidebar, dropdowns |
| Disabled | `disabled` attr + `disabled:cursor-not-allowed`; send button swaps to `bg-gray-200 dark:bg-gray-700` | send, archive/delete |
| Transition | bare `transition` everywhere; `transition-colors duration-300` on toggle chips | universal |

## Theming

### How it works today

1. **Tailwind dark mode is class-based**: `darkMode: 'class'` in `tailwind.config.js`. Components style both modes inline (`bg-gray-50 dark:bg-gray-950`, `hover:bg-gray-100 dark:hover:bg-gray-900`, etc. — see `src/lib/components/layout/Sidebar.svelte`).
2. **A FOUC-avoiding inline script in `src/app.html`** reads `localStorage.theme` and stamps `dark` / `light` / `her` on `<html>`. Recognized themes: `system` (follows `prefers-color-scheme`, live-updates via a media-query listener), `dark`, `light`, `oled-dark`, `harvis-dark`, `her`.
3. **Themes flip tokens, not classes**: the dark-end gray variables are re-assigned at runtime via `style.setProperty`:
   - `oled-dark`: `--color-gray-800: #101010`, `--color-gray-850: #050505`, `--color-gray-900/950: #000000` (true black).
   - `harvis-dark`: `--color-gray-800: #1a1f2e`, `--color-gray-850: #141823`, `--color-gray-900: #0e111a`, `--color-gray-950: #090b12` — this lifts the near-black base ramp back to the prototype's blue-charcoal surfaces.
   - The `<meta name="theme-color">` is synced per theme (`#12151D` dark, `#ffffff` light, `#000000` oled, `#0e111a` harvis-dark).

Because themes work by rewriting `--color-gray-*`, **only gray-token-based backgrounds respond to theme switching** — this is the mechanical reason for the no-raw-hex rule. Legacy standalone theme stylesheets also sit in `static/themes/` (`rosepine.css`, `rosepine-dawn.css`).

### Adding a new theme (planned theme changer)

A theme in Harvis is **a token map, not a stylesheet**. To add one:

1. Define the theme as a set of `--color-gray-*` (and optionally `--color-blue-*`) overrides, applied the same way `oled-dark`/`harvis-dark` are — via the `app.html` runtime script (or a future data-attribute + CSS block that sets the same variables).
2. Keep the ramp's *roles* intact: `gray-800` = raised, `gray-850` = panel, `gray-900` = shell, `gray-950` = deepest. A theme may move the whole ramp lighter/darker/warmer, but components must not need edits.
3. Add the theme name to the recognized list in the `app.html` script, sync `<meta name="theme-color">`, and expose it in the theme picker.
4. Do **not** override the semantic palettes (red/amber/green/cyan) unless the theme deliberately re-tunes state colors — components rely on stock Tailwind values there.

The corollary rule for components: **stay token-driven**. Any `bg-[#...]` or inline hex opts that surface out of every theme, present and future.

Seed candidates for the theme changer:
- **Midnight** — the current default ramp (near-black blue-charcoal, `gray-900 ≈ #00030b`). Effectively what ships today.
- **Daylight** — a first-class light theme built on the existing light end (`gray-50`–`gray-200`), promoted from "the other half of `dark:`" to a named, tuned token map.
- **Ember** — a warmer, higher-contrast dark option: shift the ramp's hue off 255–262 toward warm neutrals and raise text-contrast steps, keeping the same role structure (the `harvis-dark` override is the template for how such a shift is expressed).

## Do & Don't

**Do**
- Use `gray-*` / `blue-*` token classes for every surface, border, and text color — they are what the runtime themes rewrite.
- Use `dark:bg-gray-850` for dark panels; `border-gray-100 dark:border-gray-850` for hairlines; a bare `border` is already correct.
- Reuse the in-house icon set (`src/lib/components/icons/`): 24-grid, `currentColor`, `strokeWidth` 1.5 default, `aria-hidden` on the svg, `aria-label` on the button, Tooltip-wrapped.
- Keep type small and weights restrained: `text-sm`/`text-xs` bodies, `font-medium` emphasis, `font-semibold` headings.
- Use rem-based `text-*` sizes so components participate in `--app-text-scale` UI scaling.
- Build content-shaped skeletons (`ChatItemSkeleton` pattern: same geometry as the real row, `bg-black/5 dark:bg-white/5`, staggered `animate-pulse`, `motion-reduce:animate-none`, `sr-only` status).
- Express hover/active state with translucent tints (`*-500/10`, `black/5`, `white/5`) and border changes; keep elevation border-first, shadows for popovers only.
- Animate with opacity/transform (`flyAndScale`, `animate-pulse`, token fade) at ~150–300ms, and honor `prefers-reduced-motion` on anything that loops.
- Default new surfaces to `rounded-xl` (rows/menus) or `rounded-2xl` (containers); pills and dots are `rounded-full`.

**Don't**
- Don't hardcode hex/rgb in components — it breaks `oled-dark`/`harvis-dark` and every future theme. The existing stragglers (`chat/FileNav/*`, `ModelActivityChart.svelte`) are debt, not precedent.
- Don't paste one-off inline SVGs — add a component to `src/lib/components/icons/` following the template, or reuse one.
- Don't reach for purple/violet/indigo gradients, glassmorphism-everywhere, or glow effects outside the Adaptive Space HUD — cyan-on-near-black *is* the brand; purple-gradient slop is the tell of vibecoded UI.
- Don't use `font-bold`+ — bold belongs to the wordmark alone. Don't scale headings past `text-2xl` outside heroes/empty states.
- Don't ship a bare centered spinner where a content-shaped skeleton fits, and don't leave loading states silent — use the heartbeat/status-line patterns.
- Don't invent z-index mega-values (`z-50` in-page, `z-9999` for modals), don't add solid fills where a `/10` tint is the convention, and don't add a visible focus ring where the system uses border-state (`outline-hidden`) — high-contrast mode handles the opt-in.
- Don't fake data in UI (no fabricated benchmarks, meters, or usage bars — established project rule).

## Using this doc

Before styling anything, read the sources of truth in order: `src/tailwind.css` (the `@theme` token ramps and base layer), `src/app.css` (fonts, prose, wordmark, keyframes, tooltip themes), `src/app.html` (runtime theme script), then the named reference components for the pattern you're building (`MessageInput.svelte` for composer/chips/buttons, `Sidebar/ChatItem.svelte` + `ChatItemSkeleton.svelte` for rows and skeletons, `common/Modal.svelte`/`Tooltip.svelte` for overlays, `agent-studio/adaptive/*` for HUD surfaces). New UI must be token-driven (`gray-*`/`blue-*` classes, both light and `dark:` variants), reuse the in-house icon set, and copy an existing recipe from the **Components** section rather than inventing a parallel one.


## References & target direction

The sections above document Harvis **as it is today**. This section captures **where we're taking it** —
distilled from the liked-UI captures the user is collecting in **`DESIGN-REFERENCES.md`** (a living list;
read it for the raw, per-reference detail). The throughline: rather than pick one look, Harvis ships
**selectable themes**, each a token map over the same component recipes (extends the **Theming → Adding a
new theme** section above), built with a **Claude-style Appearance submenu** (System / Light / Dark →
extended to named themes).

### The three-theme target

| Theme | Origin | Feel | Best for |
|---|---|---|---|
| **Midnight** (default) | current Harvis | cool cyan-on-near-black, dark-first, sans (Inter/Archivo) | everything; the operator's console identity |
| **Airy** (light) | Ref 1 — MetricFlow (Manus) | cool light-gray canvas, white cards, **pastel-tinted KPI cards**, soft shadows, glanceable, sans | **Build / data / analytics** surfaces |
| **Warm** (light + dark) | Ref 2 — Claude.ai | **cream/paper**, **serif** display+reading, **coral** accent, editorial, calm | **Chat / Notebook** (reading & writing) |

Themes are token maps: a theme may **swap the font** (Warm → a serif reading face; Midnight/Airy stay
sans), remap the `gray-*` surface ramp and the accent, and adjust shadow vs hairline-border emphasis —
**without touching component classes** (which stay `gray-*`/`blue-*` token-driven per the *no raw hex*
rule). That is exactly why the token discipline in this doc matters: it's what makes a theme changer a
config swap, not a rewrite.

### Per-surface direction (what each redesign borrows)

- **Chat & Notebook** → the **Warm/editorial** patterns from Ref 2: comfortable serif reading measure,
  warm quiet chrome, a calm home with a recent-chats **card grid**, the right **controls/artifacts rail**
  grouping (model · artifacts · content · chat-styles), and the Appearance-submenu theme UX.
- **Build** → the **Airy/dashboard** patterns from Ref 1: **pastel-tinted stat cards** (tinted top over a
  white/`/5` delta footer, colored metric, delta chip), a **sectioned sidebar with an active pill**,
  **status/tier pills**, pill-dropdown toolbars, and soft dual-series charts with a hover tooltip card.
- **All surfaces** keep the Harvis **robot mascot + wordmark**, the in-house **178-icon set**, and the
  **token/anti-vibecoded** discipline — the references change hue, warmth, and font per theme, never the
  component grammar.

### Build order (recommended)

1. **Theme-changer scaffold** first — the token-map indirection + the Appearance submenu — because every
   per-page redesign rides on it and lands as swappable rather than a hard replacement.
2. Then per-surface passes (**Chat / Notebook → Warm**, **Build → Airy**), each verified against its
   reference.

> Raw reference captures + palettes live in `DESIGN-REFERENCES.md`. This section is the distilled contract;
> update both as new references arrive.
