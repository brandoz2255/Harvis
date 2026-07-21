# Harvis — Main Chat Redesign Spec

**Goal.** Make the Harvis chat experience calm, local-first, developer-focused, and trustworthy. The main chat area stays clean; advanced controls move into drawers and side panels; every surface is backed by real Harvis data (chats, runs, artifacts, provider status) — never fabricated. Visual inspiration comes from the Claude.ai chat shell and Manus dashboard treatment (per `DESIGN-REFERENCES.md` Refs 1 & 2), translated into Harvis's own token system so the whole redesign re-skins for free across **Midnight**, **Airy**, and **Warm**. No Claude branding is copied — Harvis keeps its robot mascot and the `.harvis-wordmark` logotype.

All paths below are relative to `front_end/owui/` unless stated otherwise. Frontend is **Svelte** (owui fork), not React.

---

## Design principles

- **Calm over clutter.** One accent element per region (the active nav pill, the Send button, the live-run chip). Everything else is gray-token monochrome. `font-medium` emphasis, `font-semibold` headings, never `font-bold`; hero copy caps at `text-3xl`.
- **Drawers for advanced.** The chat column shows messages and the composer, nothing else. Model params, artifacts, sources, skills, provider status, and style controls live in the right controls drawer; rare tools live behind the sidebar "More" flyout.
- **Token-driven, three themes for free.** Zero raw hex in components. Surfaces = `gray-*` ramp, accent = `blue-*` (re-pointed per theme: cyan in Midnight, indigo in Airy, coral in Warm), semantics = stock `red/amber/green/cyan`. Serif appears only in Warm, only on reading surfaces, via the per-theme font variable.
- **No Claude branding.** No serif wordmark, no coral ✳ mark, no Claude menu copy. We borrow interaction *shapes* (sectioned rail, Appearance submenu, grouped drawer, recent-work grid) — nothing else.
- **Truthful states, always visible.** Local-only / unverified / blocked / needs-approval states are surfaced as pills and dots on the home page, sidebar, and drawer — reusing the existing `NormStatus`/`NORM_META` vocabulary and run-status labels. Never an invented number, never a green dot that wasn't checked.
- **Real data or nothing.** Every card, pill, and count is fed by an existing store or API (`$chats`, `getWorkspaceHistory`, `getAllArtifacts`, `getIntegrationsStatus`, capabilities registry). Empty sections collapse; they never render placeholder scolds or fixed-height holes.
- **Reuse before rebuild.** The theme registry, RailCard, portal-flyout, skeleton, and chip recipes already exist in the repo. This spec re-composes them; it introduces only four genuinely new components.

---

## Information architecture

The chat shell is three columns. Left rail and right drawer are chrome; the center column is the product.

```
┌────────────┬─────────────────────────────────┬──────────────────┐
│  SIDEBAR   │        CENTER COLUMN            │  CONTROLS DRAWER │
│  (260px,   │                                 │  (Pane ≥1024px / │
│  drag      │  Empty chat → HOME DASHBOARD    │  bottom Drawer   │
│  220–480)  │   · status pill                 │  on mobile)      │
│            │   · greeting + mascot           │                  │
│ HARVIS ▸   │   · composer (centerpiece)      │  ┌─ soft card ─┐ │
│ mode pill  │   · alert banner (conditional)  │  │ Chat controls│ │
│ ────────── │   · recent-work card grid       │  │  Model       │ │
│ New chat   │                                 │  │  Artifacts   │ │
│ New build  │  Active chat → MESSAGES         │  │  Content     │ │
│ STARRED    │   · user msgs bubbled right     │  │  Skills      │ │
│ RECENT     │   · assistant full-width prose  │  │  Providers   │ │
│  CHATS     │   · composer docked bottom      │  │  Style       │ │
│ RECENT     │                                 │  │  Advanced ▸  │ │
│  BUILD     │  Navbar: live-run chips +       │  └─────────────┘ │
│  RUNS      │  Knobs toggle → drawer          │  (Build pages:   │
│ ────────── │                                 │  same shell =    │
│ Cookbook   │                                 │  "Build          │
│ Providers  │                                 │  controls")      │
│ Skills     │                                 │                  │
│ Settings   │                                 │                  │
│ ────────── │                                 │                  │
│ status ·   │                                 │                  │
│ account ▾  │← account menu → Appearance ▸ submenu (themes)      │
└────────────┴─────────────────────────────────┴──────────────────┘
```

Existing plumbing is kept: sidebar width persistence, `ModeSwitcher` (Chat | Notebook | Code), paneforge `PaneGroup` in `Chat.svelte`, `showControls`/`showArtifacts` stores, `common/Drawer.svelte` on mobile. Build pages (`src/routes/(app)/harvis/vibecode/+page.svelte`) keep their own dock but adopt the shared drawer shell for identity.

---

## 1. Sidebar

**Files:** `src/lib/components/layout/Sidebar.svelte` (chat-mode block, lines ~1133–1612), `Sidebar/ChatItem.svelte`, `Sidebar/VibeCodeNav.svelte`, `Sidebar/SidebarMore.svelte`, `Sidebar/UserMenu.svelte`, plus two new: `Sidebar/SidebarSectionLabel.svelte`, `Sidebar/SidebarBuildRuns.svelte`.

### Layout & sections (top → bottom, chat mode)

Header (logo + `.harvis-wordmark` + collapse) and the `ModeSwitcher` pill stay **exactly as-is**. Below them, the flat hover-only action list is replaced by a sectioned rail:

1. **New chat** — existing row + Search icon button. This is the *one accented row* in the rail (Ref 2's pattern): `flex items-center gap-2 px-[11px] py-[6px] rounded-xl text-sm font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-500/10 transition`. Reads cyan/indigo/coral per theme automatically.
2. **New build** — NEW row routing to `/harvis/vibecode` with the Code icon. Kills today's detour of flipping the ModeSwitcher to Code just to reach "New session".
3. **STARRED** — the existing "Pinned" chats `Folder` renamed, affordance swapped to a `size-3.5` star (new `Star.svelte` in the icon set, 24-grid/currentColor template). Rows stay `ChatItem.svelte`.
4. **RECENT CHATS** — the current Recents Folder unchanged (ChatItem + `ChatItemSkeleton` + pagination).
5. **RECENT BUILD RUNS** — extract VibeCodeNav's session list (load/poll + blue unviewed-dot logic, `VibeCodeNav.svelte` lines ~20–58 and 150–226) into `Sidebar/SidebarBuildRuns.svelte`. Chat mode renders the 5 most recent + a quiet "View all →" (`text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300`); Code mode's `VibeCodeNav` reuses the same component — one implementation.
6. **Bottom nav cluster** (above the footer): **Cookbook** (`/harvis/agent-studio/cookbook`, icon lifted from SidebarMore) · **Providers** (`/harvis/integrations`, relabeled from "Integrations", existing plug icon) · **Skills** (`showSettings.set('skills')`, renamed from "Customize") · **Settings** (`showSettings.set(true)`) — Settings finally a first-class row instead of hiding in two menus.

**Triage of surplus rows:** Agent Studio, Neural Map, Model Comparison stay in the shrunken `SidebarMore` flyout; Schedules/Artifacts/Projects move under More; Channels / pinned Models / pinned Notes folders stay flag-gated as today. While touching SidebarMore, fix its `dark:bg-[#0c111d]` → `dark:bg-gray-900` (raw-hex violation that breaks OLED/Slate).

### Row & label recipes (one recipe everywhere)

- **Row (default):** `group flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition`. This replaces today's mixed `rounded-2xl`/`rounded-xl` (DESIGN.md: rows/menus = `rounded-xl`).
- **Active (nav destinations only):** the calm accent pill — `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium`, route-matched the way the Integrations footer link already does (`$page.url.pathname.startsWith(...)`). Chat rows in `ChatItem.svelte` **keep** their neutral `bg-gray-100 dark:bg-gray-900` active — a colored pill on every open chat would be loud.
- **Section labels:** promote VibeCodeNav's micro-label into `SidebarSectionLabel.svelte`: `px-2.5 pt-3 pb-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500`.

### Footer + account area & switcher

Keep the footer: status line, then the avatar+name trigger opening `UserMenu.svelte` (the existing 240px `rounded-2xl … bg-white dark:bg-gray-850 shadow-lg` panel via `common/Dropdown.svelte`).

**Account switcher (new section in UserMenu, below the profile header):** each account row = `flex items-center gap-2.5 rounded-xl py-1.5 px-3 hover:bg-gray-50 dark:hover:bg-gray-800` — `size-6 rounded-full` avatar, name (`text-sm`) over email (`text-xs text-gray-500 dark:text-gray-400`), active account marked with the canonical `<Check className="size-4 text-blue-500" />`. An "Add account" row (Plus icon) routes to `/auth`. **Ship the UI now with the current single account rendered checked**; the multi-token store (localStorage token ring keyed by user id, swap → `location.reload()`) is a small follow-up since auth is backend-JWT.

### Acceptance (sidebar)

- All 9 brief items reachable from chat mode without flipping the ModeSwitcher.
- Exactly one row/active recipe across the rail; no `rounded-2xl` nav rows remain; no raw hex in SidebarMore.
- Active pill re-hues cyan → indigo → coral when switching Midnight/Airy/Warm with zero component edits.
- `SidebarBuildRuns` is the single source for build-run rows in both chat and Code mode; unviewed blue dot and polling behavior preserved.
- UserMenu shows the accounts section with the current account checked; "Add account" routes to `/auth`.

---

## 2. Appearance submenu

**Files:** new `src/lib/components/layout/Sidebar/AppearanceSubmenu.svelte`; `Sidebar/UserMenu.svelte` (trigger row); `src/lib/themes.ts` (new `selectTheme(id)` helper); `src/lib/components/chat/Settings/General.svelte` (delegates; dead array at line 18 deleted).

### Behavior

- **Trigger:** a row in UserMenu between Settings and Archived Chats — moon/sun icon + "Appearance" + current theme label right-aligned (`text-xs text-gray-500`) + chevron-right.
- **Flyout:** `common/Dropdown.svelte` is a hand-rolled portal with no submenu primitive, so the flyout reuses **SidebarMore's proven portal-to-body + fixed-position pattern** (anchored `left: rect.right + 8`), entering with `flyAndScale`. Panel = the canonical popover: `rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1 w-56 text-sm`.
- **Contents are a pure projection of the registry** — `THEMES.filter(t => !t.eggOnly || $config?.features?.enable_easter_eggs)` grouped by `t.group`: "System" first, then group headers "Dark" / "Light" (`px-2.5 pt-1 pb-1 text-[10px] uppercase tracking-wide text-gray-400`). So the brief's "System · Midnight · Airy · Warm" renders as: System / Dark: Midnight · Slate · OLED / Light: Light · Airy · Warm. A new registry entry appears automatically; nothing is hardcoded.
- **Theme row:** `flex items-center gap-2 px-2.5 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800` — a `size-3 rounded-full border border-gray-200 dark:border-gray-700` swatch dot painted from `t.metaColor` (the theme's own declared color — the one legitimate non-token fill) + `t.label`; active = `<Check className="size-4 text-blue-500" />` when `$theme === t.id`.
- **One code path:** new exported `selectTheme(id)` in `themes.ts` wraps the existing `theme.set(id)` + `localStorage.setItem('theme', id)` + `applyThemeById(id)` trio. The submenu and `Settings/General.svelte` both call it; General's native `<select>` is replaced by (or delegates to) the same component. `applyThemeById` is idempotent → clicking gives instant live preview with zero new theme logic.
- Escape and click-away close the flyout (SidebarMore already models both).

### Acceptance (appearance)

- Submenu list is generated from `THEMES[]`; adding a registry entry surfaces it with no component edit.
- Active theme shows the blue check; selection applies instantly and persists across reload.
- Panel legible in OLED (`bg-gray-900` → near-black) and Warm (light panel, dark text via remapped ramp).
- `General.svelte` line-18 dead `themes` array deleted; General and submenu share `selectTheme()`.

---

## 3. Home dashboard

**Files:** `src/lib/components/chat/Placeholder.svelte` (rebuilt), `ChatPlaceholder.svelte` (copy unified), `Suggestions.svelte` (empty-state fix), `MessageInput.svelte` (unchanged, rendered inside). **Data (all existing):** `$chats` store (`src/lib/apis/chats/index.ts` `getChatList` — title/updated_at/time_range); `getWorkspaceHistory(limit)` + `getActiveWorkspace()` (`src/lib/apis/agent-runs/index.ts`); `getAllArtifacts(limit)` (same file); capabilities via `src/lib/integrations/registry.ts` normalized by `src/lib/integrations/status.ts` (`NormStatus` + `NORM_META` dot/text/ring classes).

Layout: a single calm centered column (`max-w-3xl → max-w-4xl`, generous vertical air), top → bottom:

**[A] Status pill** (above the greeting): `flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-gray-100 dark:border-gray-850 text-gray-500` + `size-1.5 rounded-full` dot. Content is real: green dot + "All systems ready" when every capability normalizes to ready/connected; amber dot + "N integrations need attention" otherwise (reuse `NORM_META` dot classes verbatim). If a run is live (`getActiveWorkspace()`), the pill becomes the existing blue live-activity chip (`bg-blue-500/10 text-blue-600 dark:text-blue-400` + ping dot, `motion-reduce:animate-none`) linking to the run.

**[B] Greeting** — keep the randomized copy list and the `HarvisMascot` robot, **retire the raw-hex hero**: today's inline `#38bdf8→#bae6fd` gradient, `rgba(56,189,248,.1)` glow, and raw-hex reduced-motion fallback all violate the no-raw-hex rule and read wrong in Warm. New: `text-3xl font-medium font-primary text-gray-800 dark:text-gray-100`; any sheen is expressed through `var(--color-blue-400)` so themes re-hue it (Warm gets serif/coral via its token+font map; Airy stays quiet ink); reduced-motion fallback is plain gray-token text. Delete the dead `starters` array (Placeholder.svelte:107–128) or resurrect it as real chips using `icons/` components — never pasted inline SVGs.

**[C] Composer** — the existing `MessageInput` at `@md:max-w-3xl`, unchanged. It is already the correct centerpiece.

**[D] Alert banner** (conditional, max one, below the composer) — only when `status.ts` yields error/unavailable/needs_setup: `rounded-2xl border border-amber-200/40 dark:border-amber-500/20 bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 px-4 py-3 text-sm` (red twin for error). Icon + one-line reason + "Fix in Providers →" text link. Dismissible per session.

**[E] Recent-work card grid** — `grid grid-cols-1 @md:grid-cols-2 gap-2.5` under a quiet label (`text-xs font-medium uppercase tracking-wide text-gray-400`, "Recent") with a per-group "View all →" link. Card recipe (Manus treatment, tokenized): `rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-850 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-900 transition` — border-first elevation, no pastel hex. Per-type tint = a low-alpha icon chip (`size-8 rounded-lg`): `bg-blue-500/10 text-blue-500` chats · `bg-cyan-500/10 text-cyan-400` builds · `bg-green-500/10 text-green-500` artifacts · `bg-amber-500/10 text-amber-500` provider issues. Body: `text-sm font-medium line-clamp-2` title + `text-xs text-gray-500` relative time.

Data per card type: **chats** = first 4–6 of `$chats` (already loaded); **builds** = `getWorkspaceHistory(6)` rows with a status dot from run status (reuse existing run-status verb labels — this is where *running / finished / failed / local-only* states surface on home); **artifacts** = `getAllArtifacts(6)` (name + task_brief → existing artifact preview route); **provider issues** = rendered only when non-ready capabilities exist (never an empty scold).

**Loading & empty:** skeletons follow the `ChatItemSkeleton` pattern (same card geometry, `bg-black/5 dark:bg-white/5 animate-pulse motion-reduce:animate-none`, staggered ~90ms, `sr-only` status). Genuinely-empty sections collapse entirely. Fix `Suggestions.svelte`'s fixed `h-40` hole — render nothing when empty; Suggestions demotes below the grid (or folds into the chats group as "Suggested"). Unify `ChatPlaceholder.svelte`'s greeting copy with Placeholder's list so the two empty states stop drifting.

### Acceptance (home)

- Status pill reflects live capability state; flips to the blue live-run chip when a workspace run is active.
- No raw hex remains in Placeholder.svelte; hero renders correctly in all three themes and under `prefers-reduced-motion`.
- Grid shows only real rows; each card navigates to its chat/run/artifact/providers destination; empty groups collapse; no fixed-height holes.
- Alert banner appears only on error/unavailable/needs_setup and links to Providers.

---

## 4. Chat controls drawer

**Files:** `src/lib/components/chat/ChatControls.svelte` (restyled interior), new shared `src/lib/components/chat/ChatControls/ControlsDrawerShell.svelte`, panels `ChatControls/{OverviewPanel,ArtifactsPanel,SourcesPanel,ViewPanel}.svelte`, revived `Controls/Controls.svelte` content, `common/RailCard.svelte`, `common/Drawer.svelte` (mobile), `Navbar.svelte` (Knobs toggle, unchanged), `src/routes/(app)/harvis/vibecode/+page.svelte` (build context mount).

### Shell

Keep the existing Pane/Drawer plumbing, stores (`showControls`, `showArtifacts`, `artifactCode`), width persistence, and permission gates. Restyle the interior as a **floating soft card**: Pane background goes page-colored (`bg-gray-50 dark:bg-gray-900`); inside it one card `m-2 ml-0 rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-850 shadow-sm flex flex-col overflow-hidden`.

- **Header:** `flex items-center justify-between px-4 pt-3 pb-2` — title `text-sm font-medium font-primary text-gray-800 dark:text-gray-100` reading **"Chat controls"** or **"Build controls"** via a new `context: 'chat' | 'build'` prop; close = `<XMark className="size-4" />` in the standard `p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition` recipe (kills the inline-SVG X).
- **Body:** one scroll column `overflow-y-auto px-3 pb-3 space-y-2` of `RailCard` sections (collapsible + `persistKey` — `Controls/Controls.svelte` proves the pattern).
- **Extract into `ControlsDrawerShell.svelte`** used by *both* the mobile Drawer branch and the desktop Pane branch — this erases the wholesale mobile/desktop copy-paste inside ChatControls.svelte (lines ~343–449 vs ~514–625).
- **Two top-level pills max** — "Controls" and "Activity" (Activity = the process rail `ViewPanel` + terminal Files) — replacing today's four tabs. Sources/Artifacts data folds into the sections below.
- The `$showArtifacts` full-pane artifact view gains the same card header with a **back** control instead of hijacking the pane with no context.

### Sections (chat context, top → bottom)

1. **MODEL** (non-collapsible): current model `text-sm font-medium` + mode chip reusing the composer's `CHAT_MODE_META` tint classes and `size-1.5` dot + one-line descriptor `text-xs text-gray-500 dark:text-gray-400`; a "Change" text button focuses the composer model menu. Data already client-side (`selectedModels` + `$models`) — zero new API.
2. **ARTIFACTS:** fold `ArtifactsPanel` in as a RailCard with count badge; items become cards using the recipe SourcesPanel already ships (`rounded-xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-2.5 hover:…`), icon + name + `text-[11px] text-gray-400` meta ("Click to open · N versions"). Clicks keep setting `showArtifacts`/`artifactCode`. Empty state: `text-xs text-gray-400 leading-relaxed py-8 text-center` helper.
3. **CONTENT:** merge chat-attached files (revive the dead FileItem list from `Controls/Controls.svelte:142–174` — currently unreachable because ChatControls:114 redirects the 'controls' tab) with SourcesPanel's deduped citation cards, under one RailCard with count; sub-labels use the `text-[10px] uppercase tracking-wide text-gray-400` recipe. This un-deadens shipped functionality.
4. **SKILLS:** attached skills as toggle chips in the existing sky-tinted ON recipe (`text-sky-500 dark:text-sky-300 bg-sky-50 dark:bg-sky-400/10 border-sky-200/40 dark:border-sky-500/20`) + a quiet "Manage" link to the Skills builder. Render only when skill data exists for the session (fail-hidden, no fake counts). Toggling a gated skill goes through the existing approval-gated skill path — the drawer never bypasses the gate.
5. **PROVIDERS:** readiness rows — `size-1.5 rounded-full` dot (green-500 ok / amber-500 degraded / red-500 down) + name `text-xs font-medium` + status pill — fed by the existing `getIntegrationsStatus` (`src/lib/apis/integrations/index.ts` → GET `/api/owui/integrations/status`); poll only while the drawer is open (mirror the Integrations page's 7s cadence).
6. **STYLE** (the Claude "Chat styles" analog): inline existing settings — `chatBubble` toggle, `widescreenMode` toggle, the `textScale` slider (`utils/text-scale.ts` + `Settings/Interface.svelte` are the source of truth), and an "Appearance" shortcut opening the theme submenu. All writes via the existing settings store; no new persistence.
7. **ADVANCED** (collapsed, `persistKey: chatControls.advanced`): re-home Controls.svelte's system prompt, Temperature, AdvancedParams, Valves RailCards — restored, not rebuilt.

### Build context

Mount the same `ControlsDrawerShell` in the vibecode right dock header (`src/routes/(app)/harvis/vibecode/+page.svelte`) titled "Build controls": sections = engine/model (workspace-model sync), run artifacts, repo/files, skills, providers — same recipes, no new palette. The Build dock's existing panels (WorkspaceFileRail/PlanPanel/ShellTab/BrowserPanel) are untouched; the shell gives the two lanes one drawer identity.

### Acceptance (drawer)

- One shell component serves mobile Drawer + desktop Pane + build dock; the duplicated tab/panel markup in ChatControls.svelte is gone.
- Drawer shows Model, Artifacts, Content, Skills, Providers, Style, Advanced; system prompt/temperature/Valves are reachable again.
- Provider rows poll only while open; dots match `/api/owui/integrations/status`.
- Artifact full-view has a header + back control; close button is the `XMark` icon component.
- On build pages the same shell reads "Build controls".

---

## 5. Chat surface & composer

**Files:** `src/lib/components/chat/MessageInput.svelte`, `Messages/Message.svelte`, `Messages/UserMessage.svelte`, `Messages/ResponseMessage.svelte`, `ChatControls/SourcesPanel.svelte`.

**Message layout — keep the current split; it is already the Claude-like shape:**
- Only **user** messages bubble: `rounded-3xl max-w-[90%] px-4 py-1.5 bg-gray-50 dark:bg-gray-850`, right-aligned, gated by `$settings?.chatBubble ?? true` (UserMessage.svelte:370–376).
- **Assistant** stays full-width `markdown-prose`, no bubble, no avatar gutter (ResponseMessage.svelte — "the AI's domain"). The Warm theme's token remap (cream ramp + per-theme serif via the `.markdown-prose` font hook) restyles both without touching component classes.
- Action rows keep `p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg invisible group-hover:visible`.

**Composer — light polish only; the glassy `rounded-3xl` shell with border-state focus already matches the calm brief:**
- Keep `#message-input-container` exactly as-is (glassy border-state, dashed for temporary chat), the `+` InputMenu, mic dropdown, Deep Research amber toggle, mode/model pill (`CHAT_MODE_META`/`CHAT_MODE_DOT`), Send button.
- Normalize the pending-OAuth chips (`px-2 py-[5px]`) to the sibling toggle-chip geometry (`p-[7px]`) — geometry drift fix.
- Replace the mic/mode dropdowns' inline chevron/check SVGs with `icons/` components per the icon rule.
- Amber pending-OAuth chips remain the *blocked-until-approved* signal in the composer; Stop remains instantly reachable while a run streams.
- Fix `SourcesPanel.svelte:88`'s Google-favicon fetch (external call — off-brand for a self-hosted, local-first app): local letter-glyph or cached favicon fallback.

**Reading measure:** the chat column stays `max-w-6xl` for now; a narrower per-theme prose measure for Warm is surfaced as an explicit open decision in P6 of the reference contract — decide before Warm body-serif ships, don't improvise.

### Acceptance (surface & composer)

- User-bubble/assistant-full-width behavior unchanged and correct in all three themes.
- No inline SVGs remain in composer dropdown chrome; chip geometry consistent.
- No external favicon fetches from SourcesPanel.
- No focus rings introduced; `motion-reduce` honored on any pulse dots.

---

## Theme-token guidance

The entire redesign is expressed in the existing token vocabulary so Midnight/Airy/Warm are automatic:

| Element | Token approach | Midnight | Airy | Warm |
|---|---|---|---|---|
| Surfaces (rail, cards, drawer) | `gray-*` ramp only; roles fixed: gray-800 raised / 850 panel / 900 shell / 950 deepest | near-black blue-charcoal | light gray shell, white cards | cream/paper ramp (full warm gray-* token map — the current ramp is hue-locked cool, so Warm is a *map*, not a tweak) |
| Accent (active pill, New chat, live chip, checks) | `blue-*` classes; themes re-point the blue-* variables | cyan | indigo | coral/terracotta |
| Status semantics (dots, pills, banner) | stock `green/amber/red/cyan` — never overridden per theme | same hues everywhere (truthful status must not re-hue) | | |
| Soft washes (icon chips, active pill, skill chips) | always `*-500/10` alpha tints of a semantic ramp — never fixed pastel hex | subtle wash on dark | reads pastel | wash on cream |
| Serif | per-theme font variable (`--theme-font-body`, consumed by `.markdown-prose` + display headings); components never hardcode a serif class | sans (Inter/Archivo) | sans | serif on reading surfaces only; chrome stays sans. **Blocker:** a body-legible text serif must be chosen and self-hosted (`font-display: swap` in `src/app.css`) — InstrumentSerif is display-only. Flag, don't improvise. |
| Swatch dots (Appearance submenu) | painted from `THEMES[].metaColor` — the one legitimate non-token fill | | | |

Hard rules: **no raw hex in components** (the reference palettes #F0EBE0 / #D97757 / #6366F1 are *token values* set in the `app.html`/`themes.ts` maps, never classes); no purple gradients/CTAs; elevation is border-first (hover = border-shift, at most `shadow-sm`→`shadow-lg` on cards); `applyThemeById()` in `themes.ts` remains the single runtime entry point. Mechanism gap to close: the runtime script currently only re-assigns `--color-gray-*` — Warm/Airy accents require the theme maps to also override `--color-blue-*` (DESIGN.md already permits this; no theme does it yet).

---

## Svelte components likely affected

**New (4):** `Sidebar/SidebarSectionLabel.svelte` · `Sidebar/SidebarBuildRuns.svelte` · `Sidebar/AppearanceSubmenu.svelte` · `ChatControls/ControlsDrawerShell.svelte` (+ `icons/Star.svelte`).

| File | Change |
|---|---|
| `src/lib/components/layout/Sidebar.svelte` | Re-section the chat-mode block (lines ~1133–1612); unified row/active recipes; Providers/Skills/Settings rows |
| `src/lib/components/layout/Sidebar/ChatItem.svelte` | Unchanged geometry; neutral active kept |
| `src/lib/components/layout/Sidebar/VibeCodeNav.svelte` | Session list extracted to `SidebarBuildRuns.svelte`; consumes it |
| `src/lib/components/layout/Sidebar/SidebarMore.svelte` | Shrinks to rare tools; `dark:bg-[#0c111d]` → `dark:bg-gray-900` |
| `src/lib/components/layout/Sidebar/UserMenu.svelte` | Accounts section + Appearance trigger row |
| `src/lib/themes.ts` | New `selectTheme(id)` helper; Warm/Airy accent + font token maps |
| `src/lib/components/chat/Settings/General.svelte` | Delegates to `selectTheme()`; dead line-18 array deleted |
| `src/app.html` / `src/app.css` | Runtime script recognizes new theme ids + accent/font vars; Warm serif `@font-face` |
| `src/lib/components/chat/Placeholder.svelte` | Rebuilt as home dashboard; raw-hex hero + dead `starters` removed |
| `src/lib/components/chat/ChatPlaceholder.svelte` | Greeting copy unified with Placeholder |
| `src/lib/components/chat/Suggestions.svelte` | `h-40` empty hole fixed; demoted below grid |
| `src/lib/components/chat/Chat.svelte` | Empty-state branch feeds new Placeholder; pane plumbing unchanged |
| `src/lib/components/chat/ChatControls.svelte` | Interior → soft card via shared shell; mobile/desktop duplication removed |
| `src/lib/components/chat/ChatControls/{ArtifactsPanel,SourcesPanel,OverviewPanel,ViewPanel}.svelte` | Folded into drawer sections / Activity pill |
| `src/lib/components/chat/Controls/Controls.svelte` (+ `Valves.svelte`) | Content re-homed into Advanced/Content sections (currently unreachable) |
| `src/lib/components/chat/MessageInput.svelte` | Chip geometry + icon-component polish only |
| `src/lib/components/chat/Messages/{Message,UserMessage,ResponseMessage}.svelte` | Untouched layout; verify under Warm tokens |
| `src/lib/components/chat/Navbar.svelte` | Knobs toggle + live chips unchanged |
| `src/lib/components/common/{RailCard,Dropdown,Drawer,Folder}.svelte` | Reused as-is |
| `src/routes/(app)/harvis/vibecode/+page.svelte` | Mounts `ControlsDrawerShell` as "Build controls" |
| Data (no API changes): `src/lib/apis/chats/index.ts`, `src/lib/apis/agent-runs/index.ts`, `src/lib/apis/integrations/index.ts`, `src/lib/integrations/{registry,status}.ts`, `src/lib/stores/index.ts` | Consumed by home + drawer |

---

## Interaction & behavior

- **Trace events:** the redesign is UI recomposition — every action routes through *existing* traced endpoints (`/api/harvis/*` trace lane, `workspace_events`). New surfaces (home cards, drawer sections) are read-only consumers; skill toggles and model changes go through the same stores/endpoints the composer already uses, so trace coverage is inherited, not reimplemented.
- **Approval gating:** nothing in the sidebar, home, or drawer triggers a dangerous action directly. Gated skills stay human-gated (drawer Skills section only toggles what the gate already permits); build actions keep their approval flow; **push/deploy never appears as a one-click affordance anywhere in the chat shell** — local commit after approval is the ceiling, per project rules.
- **Local-only / unverified / blocked states:** home status pill (green/amber via `NORM_META`), alert banner (amber/red), build-run cards and sidebar run rows carry run-status verb labels and dots; pending-OAuth amber chips in the composer signal blocked tools; provider rows in the drawer show green/amber/red. These semantic hues are theme-invariant by design.
- **Drawer open/close:** Navbar Knobs button flips `showControls` (unchanged); mobile keeps the bottom-sheet Drawer with its overlay; desktop stays an in-pane card (no new z-tiers). `showArtifacts` view gets a back control instead of a dead end.
- **Keyboard:** Escape closes the Appearance flyout, SidebarMore, UserMenu, and the drawer (focus returns to the trigger); flyouts also close on click-away (SidebarMore is the in-repo precedent). Menu rows are focusable buttons with visible `:focus-visible` states from the existing recipes — no custom focus rings.
- **Motion:** all pulses/pings carry `motion-reduce:animate-none`; flyouts use the existing `flyAndScale`; skeletons stagger ≤ ~90ms.

---

## Acceptance criteria (whole redesign)

1. Sidebar chat mode shows, in order: New chat · New build · STARRED · RECENT CHATS · RECENT BUILD RUNS · Cookbook · Providers · Skills · Settings — all reachable without switching modes.
2. Every nav destination row uses the single row recipe and the `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium` active pill; chat rows keep neutral active; zero `rounded-2xl` nav rows.
3. Switching Midnight → Airy → Warm re-hues every accent (active pill, New chat row, checks, live chips) with **zero component edits**, and no raw hex remains in Sidebar, SidebarMore, or Placeholder (grep-verifiable: no `#[0-9a-f]` classes / inline styles outside theme maps and `metaColor` swatches).
4. UserMenu contains an Accounts section (current account checked, "Add account" → `/auth`) and an Appearance row opening a portal flyout.
5. The Appearance flyout is generated from `THEMES[]` (grouped System/Dark/Light), marks the active theme with the size-4 blue check, applies instantly via `selectTheme()`, persists, closes on Escape/click-away, and is legible in OLED and Warm.
6. `Settings/General.svelte` shares `selectTheme()` with the submenu; its dead theme array is gone.
7. Home shows: real status pill (or blue live-run chip when a run is active) · de-hexed greeting + mascot · composer · conditional alert banner · recent-work grid fed by `$chats`, `getWorkspaceHistory`, `getAllArtifacts`, and capability status — each card navigates correctly; empty groups collapse; skeletons honor reduced-motion; Suggestions no longer reserves `h-40` when empty.
8. The controls drawer renders as a rounded soft card with a titled header ("Chat controls" / "Build controls") and an `XMark` close; one `ControlsDrawerShell` serves mobile, desktop, and the vibecode dock; the mobile/desktop duplication in ChatControls.svelte is deleted.
9. Drawer sections Model / Artifacts / Content / Skills / Providers / Style / Advanced all render with real data; system prompt, Temperature, AdvancedParams, and Valves are reachable again; provider polling runs only while the drawer is open; the artifact full-view has a back control.
10. Skills toggles in the drawer cannot enable anything the approval gate hasn't permitted; no push/deploy affordance exists anywhere in the chat shell.
11. User messages bubble right, assistant stays full-width prose, in all three themes; composer shell unchanged; pending-OAuth chips match toggle-chip geometry; no inline SVGs in composer dropdown chrome; no external favicon fetches.
12. Serif appears only in Warm, only on reading surfaces (`.markdown-prose` + display headings) via the per-theme font variable; sidebar/menus/buttons stay sans in Warm. (Blocked on choosing + self-hosting a body serif — ship Warm's color map first if the font isn't picked.)
13. Keyboard: Escape closes every new flyout/drawer with focus return; all rows reachable by Tab.
14. `npm run build` and `npm run lint` pass; manual smoke in all three themes at 1280px and mobile width.

---

## Build order

Phased so each lands independently and the scaffold-ready pieces go first:

1. **Phase 1 — Sidebar + Appearance submenu** (scaffold already exists: SidebarMore's portal flyout, VibeCodeNav's label + session list, the ready `THEMES[]` registry). Deliver: sectioned rail, unified recipes, `SidebarSectionLabel` + `SidebarBuildRuns` + `Star` icon, SidebarMore hex fix, `selectTheme()` + `AppearanceSubmenu` + General.svelte delegation, UserMenu accounts section (single-account UI). Highest visibility, lowest risk.
   - *1b (parallel, tokens):* Warm/Airy accent-variable support in `app.html`/`themes.ts` maps so Phase 1's pill re-hue gate can be verified.
2. **Phase 2 — Home dashboard.** Rebuild Placeholder.svelte (status pill, de-hexed greeting, alert banner, recent-work grid, skeletons), Suggestions empty fix, ChatPlaceholder copy unification. All four data sources already exist — no backend work.
3. **Phase 3 — Controls drawer.** `ControlsDrawerShell`, section fold-in (revive Controls.svelte content), Providers polling, two-pill Controls/Activity, artifact-view back control; then mount in the vibecode dock as "Build controls".
4. **Phase 4 — Surface & composer polish.** Chip geometry, icon components, SourcesPanel favicon fix; verify message layout under Warm tokens.
5. **Phase 5 — Warm reading pass (gated).** Choose + self-host the body serif, wire `--theme-font-body`, decide the Warm prose measure (vs. the current `max-w-6xl`). Explicitly last: it blocks on a font decision, and everything before it ships without it.

Per phase: verify the three-theme gates (accent re-hue, OLED legibility, Warm panel contrast) before moving on; multi-account token ring is a follow-up after Phase 1's UI lands.
