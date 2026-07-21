# Prototype → owui merge + sidebar restyle — implementation plan (2026-07-17)

## Executive summary

Bring the MAIN-tree prototype look into two owui surfaces, **blue accent throughout, token-only, structure-preserving**. (A) The home launcher merges into `Placeholder.svelte` — mascot hero, prototype composer polish, a new connect-tools shadow tray, a restyled explore-ideas chip row, and a new capabilities carousel — all wired onto owui's existing `MessageInput` send path with zero changes to submit/socket/binds. (B) The three sidebars (`Sidebar.svelte` + `ModeSwitcher.svelte`, `NotebookNav.svelte`, `VibeCodeNav.svelte` + `SidebarMore.svelte`) converge on one row/label/hover/radius recipe with the blue accent applied only where the prototype uses accent. The prototype's semantic tokens (`--accent` clay/indigo, `--card`, `--panel`…) are **translated 1:1 onto owui's `gray-*` / `blue-*` Tailwind ramps with `dark:` pairs**, so Warm/Airy/Midnight all re-skin through the existing token map — no raw hex, and the coral/indigo of the prototype never appears (blue-only). **Nav logic, routes, `href`/`goto`, stores, and event wiring stay exactly as-is — this is look-and-structure only.**

---

## Global token discipline (applies to every edit below)

Translate the prototype's semantic-token layer onto owui utilities. Never emit a raw hex except the one sanctioned inline gradient (greeting). Every color is a `gray-*` or `blue-*` utility with a `dark:` pair so the theme changer inherits.

| Prototype token | Role | owui utility (light / dark) |
|---|---|---|
| `--shell` | app background, arrow glow | `bg-gray-50` / `dark:bg-gray-950` |
| `--panel` | sidebar background | (owui sidebar keeps its own panel classes — untouched) |
| `--card` | composer card, chips, menus, nav buttons | `bg-white` / `dark:bg-gray-850` |
| `--card` mixed toward black (tray/carousel grey) | tray + carousel surface | `bg-gray-50` / `dark:bg-gray-900` |
| `--hover` | row / iconbtn hover, switch track | `hover:bg-gray-100` / `dark:hover:bg-gray-850` |
| `--border` | hairlines, chip outlines, dots base | `border-gray-200` / `dark:border-gray-800` |
| `--text` | headings, active ink, card titles | `text-gray-900` / `dark:text-gray-50` |
| `--text-muted` | icons, descriptions, inactive segments | `text-gray-600` / `dark:text-gray-400` |
| `--text-faint` | placeholders, section labels, dismiss | `text-gray-400` / `dark:text-gray-500` |
| `--accent` | active dot, live dot | `bg-blue-500` / `dark:bg-blue-400` |
| `--accent-text` | wordmark, new-chat, nav-active, carousel glyph, avatar ink | `text-blue-600` / `dark:text-blue-400` |
| `--accent-weak` | accent wash, nav-active fill, avatar bg, carousel-icon bg | `bg-blue-500/10` |
| `--accent-fill` | send-button bg | `bg-blue-600` / `dark:bg-blue-500` (owui already uses this) |
| `--accent-fg` | glyph on fill | `text-white` |

The prototype's coral (`#c47250`) / indigo (`#7679c9`) accent resolves to owui's cyan-leaning `blue-*` ramp (`blue-500` ≈ `#38bdf8`, defined in `tailwind.css @theme`). **Use `blue-*` utilities — never hardcode `#38bdf8`** (the sole exception is the greeting's `background-clip:text` gradient, which the minifier strips from CSS files and so must stay inline; see `Placeholder.svelte:229–232`).

### Canonical "one look" recipes (referenced by every step)

- **Row base:** `group flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-gray-700 dark:text-gray-300 transition outline-none`
- **Row hover:** `hover:bg-gray-100 dark:hover:bg-gray-850`
- **Route / nav-active (blue):** `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium` (its icon → `text-blue-600 dark:text-blue-400`)
- **List-selection active (neutral):** `bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-50 font-medium` — mirrors the prototype's `row--active` ("never an accent pill")
- **Accent action row (the one blue "New …" row per mode):** `text-blue-600 dark:text-blue-400 font-medium hover:bg-blue-500/10` (icon → same blue) — mirrors the prototype `.newchat`
- **Section label:** `px-2.5 pt-3 pb-1 text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500`
- **Live / unviewed dot:** `bg-blue-500 dark:bg-blue-400`
- **Focus ring:** `focus-visible:ring-2 focus-visible:ring-blue-500/40`
- **Radius:** rows `rounded-xl`; micro-buttons `rounded-lg`; floating islands / cards `rounded-2xl`
- **Gap:** `gap-3` everywhere (retire `space-x-3`)
- **Inactive text:** `text-gray-700 dark:text-gray-300`

### Active-state policy (the load-bearing design decision — Decision 1)

The two provided specs disagree on how "active" fills. The prototype uses **two tiers** (route/nav-active = accent wash; list selection = neutral inset), while the owui restyle audit proposes a **single blue-tint** for both. This plan defaults to the **prototype's two-tier system** because "keep the theme blue by default" governs the *accent hue*, not "fill every selected row blue," and a long recents list rendered all-blue is noisy:

- **Route/nav-active** (mode segment, Integrations footer, ONB nav items, bottom-nav route items, More-flyout items) → **blue-tint** recipe.
- **List selection** (recent chats, recent notebooks, sessions) → **neutral inset** recipe.

If the user prefers the audit's single blue-tint everywhere, swap the list-selection rows to the blue-tint recipe — the exact lines are called out per step. Flagged in Decisions.

---

## Step 1 — Launcher merge into owui home (`Placeholder.svelte` + light `MessageInput.svelte` polish)

**File:** `front_end/owui/src/lib/components/chat/Placeholder.svelte` (the live home/greeting component — `ChatPlaceholder.svelte` is dead for this purpose; do not touch it). Composer polish only in `MessageInput.svelte`.

Prototype block → owui target:

| Prototype block | owui target | Kind |
|---|---|---|
| a. Hero (mascot + headline) | `:148` mascot, `:149–155` greeting | edit in place |
| b. Composer (`.lc-card`) | `MessageInput` at `:172–201` (styled in `MessageInput.svelte`) | verify / minimal |
| c. Connect-tools shadow tray (`.connstrip`) | **new block** after `:201`, inside `.home-stage` | additive |
| d. Explore-ideas chips (`.idea-pill` row) | restyle/replace `Suggestions` `:213–223` | edit or replace |
| e. Capabilities carousel | **new block** after the folder/suggestions `{#if}` closes at `:225` | additive |

### 1a. Hero

- **Mascot** `:148` — keep `<HarvisMascot size={56} className="mb-3" interactive={true} />`. owui's `HarvisMascot.svelte` already renders in the app palette; it does **not** take an `accent` prop (props are `size`/`className`/`interactive`/`state`), so leave it — its existing cyan reads as the blue accent. Bump `size` to `56` if not already, wrap in a centered hero container if the headline needs tighter grouping. The radial glow already exists at `.home-stage::before` (`:238–250`) — leave it (it's cyan/blue).
- **Greeting** `:149–155` — keep the `.home-greeting text-3xl font-medium` element and its **inline** `background-image:linear-gradient(100deg,#38bdf8…)` + `background-clip:text` (this literal must stay inline — a CSS-file version is stripped by the minifier). Decision 2: keep owui's random `_greetings` array (`:83–101`) or replace with the prototype's fixed *"What do you want to explore?"*. Recommend the fixed prototype line for fidelity (set the element's text to a constant, leave `_greetings` unused) — flagged. Do **not** introduce the prototype's Warm-only serif (`--font-read`); owui's blue default is sans, keep the current font.

### 1b. Composer (mostly verify — no structural edit)

owui's `#message-input-container` (`MessageInput.svelte:1486–1490`) already matches the prototype `.lc-card`: `rounded-3xl border … shadow-lg backdrop-blur-sm bg-white/5 dark:bg-gray-500/5`. The send button (`:2411–2417`) is already the blue accent-fill (`bg-blue-600 … dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-400`, disabled `bg-gray-200 dark:bg-gray-700`) — **leave it**. Optional token-only polish, none touching wiring:
- Toolbar row `:1811` — confirm `justify-between`; left cluster `+`/mic/pills (`:1878`, `:1896`, `:2085–2330`), right cluster voice/send. No change required.
- `+` button `:1878` and iconbtns — already `hover:bg-gray-100 … rounded-full`; leave.
- **One required edit for the tray overlap:** add `relative z-10` to the div that wraps `MessageInput` at `Placeholder.svelte:172` so the new tray (`z-0`, negative top margin) slides *under* the composer. This does not touch any `MessageInput` internals.

### 1c. Connect-tools shadow tray (new, additive, dismissible)

Insert **after the `</div>` closing the MessageInput wrapper at `:201`, still inside `.home-stage`.** Gate on a local `connectDismissed` boolean (client-only state — no store). Prototype geometry translated to owui:

```svelte
{#if !connectDismissed}
  <div class="relative z-0 -mt-3.5 mx-[17px] w-[calc(100%-34px)]
              rounded-b-2xl border border-t-0 border-gray-200 dark:border-gray-800
              bg-gray-50 dark:bg-gray-900 shadow-sm
              px-4 pt-[22px] pb-3 flex items-center justify-between gap-2.5">
    <span class="inline-flex items-center gap-1.5 text-[0.8125rem] text-gray-600 dark:text-gray-400">
      <!-- puzzle icon, size 14 --> Connect your tools to Harvis
    </span>
    <div class="flex items-center gap-1.5">
      <!-- 6 brand chips: github, discord, notion, slack, drive, gmail -->
      <span class="inline-flex items-center justify-center size-[26px] rounded-lg
                   text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-850
                   border border-gray-200 dark:border-gray-800"><Brand size={16}/></span>
      <!-- … ×6 … -->
      <button class="size-6 ml-0.5 rounded-lg text-gray-400 dark:text-gray-500
                     hover:text-gray-700 dark:hover:text-gray-200
                     hover:bg-gray-100 dark:hover:bg-gray-850"
              on:click={() => connectDismissed = true}><!-- x icon, size 14 --></button>
    </div>
  </div>
{/if}
```

The `-mt-3.5` (−14px) pull, `border-t-0`, and `rounded-b-2xl` reproduce the "tray slid out from under the composer" read; the composer's `z-10` covers the seam. Brand marks are inline SVG (order github/discord/notion/slack/drive/gmail); the prototype's `brands.tsx` paths are swappable for owui's own icon set or official assets. **Blue accent note:** the tray carries no accent — chips are neutral, matching the prototype.

### 1d. Explore-ideas chips

Decision 3 — two options, both preserving the `onSelect` select→prompt flow (`onSelect` is passed in from `Chat.svelte:3581`):
- **Option A (recommended, higher fidelity):** replace the `Suggestions` block `:213–223` with a horizontal-scroll prototype chip row driven by the **ready-made, currently-unrendered `starters` array (`:107–128`)** (each has `label`, `route`/`seed`, inline `icon`). Wire seeds via `onSelect` and routes via `goto` (both already available). Chip recipe (`.idea-pill`):

  ```
  flex-none inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
  text-[0.8125rem] font-medium whitespace-nowrap
  border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850
  text-gray-600 dark:text-gray-400
  hover:bg-gray-100 dark:hover:bg-gray-850 hover:text-gray-900 dark:hover:text-gray-100
  ```
  Trailing `chevronRight` (size 13). Row wrapper `flex flex-nowrap gap-1.5 overflow-x-auto pr-[30px] [scrollbar-width:none]`; right-edge `.scroll-arrow` `absolute right-[-4px] top-1/2 -translate-y-1/2 size-7 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 text-gray-500 dark:text-gray-400`. Section label "Explore ideas" via the canonical section-label recipe. Keep the `in:fade` entrance used at `:208`/`:213`.
- **Option B (minimal):** keep `<Suggestions>` and only restyle its chips to the recipe above (edits live in `Suggestions.svelte`, outside the given anchors).

No blue on the idea chips (prototype keeps them neutral); the accent lives on the send button and carousel.

### 1e. Capabilities carousel (new, additive)

Insert **after the folder/suggestions `{#if $selectedFolder}…{:else}…{/if}` closes at `:225`, before the root wrapper closes at `:226`**, wrapped in `in:fade`. Auto-advance every 4500 ms across 6 items with a clickable 3-dot pager (local component state; no store). Recipe:

- Card: `flex-1 flex items-center gap-3.5 min-h-[88px] px-4.5 py-4 rounded-2xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900`
- **Icon cell (the accent):** `size-[38px] inline-flex items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400` (glyph size 18)
- Title `text-[0.9rem] font-semibold text-gray-900 dark:text-gray-50`; desc `text-[0.8125rem] leading-relaxed text-gray-600 dark:text-gray-400`
- Nav buttons ×2: `size-... w-[34px] inline-flex items-center justify-center rounded-xl border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850`
- Mini preview bars: `h-2.5 rounded-[5px] bg-gray-100 dark:bg-gray-850` (hidden `<640px`)
- Dots: base `size-1.5 rounded-full bg-gray-300 dark:bg-gray-700`; **active `w-[18px] bg-blue-500`** (animated width/color)

### Must-NOT-change in Step 1

`MessageInput.svelte:35` `dispatch('submit', prompt)`, form handler `:1448–1454`, `RichTextInput id="chat-input"` `:1645–1647` + its `onChange` `:1649–1653` + the `setText('')` clear `:32`; all two-way binds threaded `Placeholder → MessageInput` `:173–200` and the `on:submit`/`on:research` forwards; `Chat.svelte:3437` home gate and `Chat.svelte:3561–3596` `<Placeholder>` invocation. Restyle only classes/markup around these anchors.

### Deploy + verify (Step 1)

Rebuild owui → restart nginx → load `:9000` in the default blue theme. Confirm: greeting gradient renders blue; mascot animates; tray sits behind the composer with the overlap seam hidden and dismisses on `x`; explore chips scroll and seed/route on click; carousel auto-advances with a blue active dot and blue icon cells; **send still works** (type + submit clears the input). Toggle Airy/Midnight to confirm every surface re-skins (no stuck light/dark colors, no coral/indigo).

---

## Step 2 — Chat sidebar restyle (`Sidebar.svelte` + `ModeSwitcher.svelte`)

**File:** `front_end/owui/src/lib/components/layout/Sidebar.svelte` and `ModeSwitcher.svelte`. Structure/markup only; no `href`/`goto`/store/`Folder` logic changes.

### 2a. `ModeSwitcher.svelte` (the Chat|Notebook|Code segmented control)

| Line | Change |
|---|---|
| 25 | Container `inline-flex w-full items-center gap-1 rounded-full p-1 bg-gray-100 dark:bg-gray-850` — keep (matches prototype `.modeswitch` track). |
| 38 | Active segment: `dark:bg-gray-700` → **`dark:bg-gray-800`** (on-ramp raised surface); **drop `shadow-sm`** (hairline-over-shadow); **add blue accent `text-blue-600 dark:text-blue-400`** so the selected mode reads as the accent. Keep `grow gap-1.5 px-3 bg-white … text-…-50` structure and the revealed text label (43). |
| 39 | Inactive hover `dark:hover:bg-gray-800/40` → **`dark:hover:bg-gray-850`** (collapse the 4th hover shade into the shared set); keep muted `text-gray-500 dark:text-gray-400`. |

Decision 5: the prototype keeps its active mode segment *neutral* (accent only on wordmark/new-chat/nav). This plan adds blue text to honor "blue everywhere" and the owui audit's note that the switcher "reads colorless." Alternative if the user wants restraint: neutral card + `ring-1 ring-blue-500/20` instead of blue text. Icons stay `size-4 strokeWidth="1.8"`; bind active via the selected-mode class (don't rely on `[aria-pressed]`).

### 2b. `Sidebar.svelte` (container + Chat-mode nav)

| Line | Change |
|---|---|
| 1137 (New Chat) | **Make this the one accent action row** (prototype `.newchat`): `rounded-2xl`→`rounded-xl`, text→`text-blue-600 dark:text-blue-400 font-medium`, hover→`hover:bg-blue-500/10`, icon → blue. (Decision 6 — alternative: keep neutral `text-gray-700 dark:text-gray-300`, hover `dark:hover:bg-gray-850`.) |
| 1159, 1173 (Projects / Search) | Row → base recipe; `rounded-2xl`→`rounded-xl`; `space-x-3`→`gap-3`; hover→`dark:hover:bg-gray-850`; text→`text-gray-700 dark:text-gray-300`. |
| 1190, 1206, 1220 (Schedules / Artifacts / Customize) | Drop per-row `mx-[0.4375rem]`; wrap the three in one `px-[0.4375rem]` container (structure-only, matching the New Chat/Projects inset mechanism). Rows → base recipe; `rounded-2xl`→`rounded-xl`; `space-x-3`→`gap-3`; hover→`dark:hover:bg-gray-850`. When a route is active, adopt the **route/nav-active blue-tint** recipe. |
| 1368 (pinned-note rows via Folder) | Keep `rounded-xl`; align gap `gap-2.5`→`gap-3` and hover→`dark:hover:bg-gray-850`. |
| 1626–1627 (footer status) | Keep the **green** dot `bg-green-500` (semantic "ready", theme-invariant `--ok` in the prototype). Decision 4: swap to `bg-blue-500 dark:bg-blue-400` only if the team wants a single-accent rail. |
| 1632–1634 (Integrations, the only chat-mode active row) | Active `bg-gray-100 dark:bg-gray-850 …` → **route/nav-active blue-tint** `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium`; `gap-3` already correct — unifies with the other navs' active. |
| 852, 1068, 1094 (collapsed rail / header buttons) | Already `dark:hover:bg-gray-850` — leave as the canonical dark-hover shade; pull the body rows *up to* it (done above), not the reverse. |

**List selection** (Recents/Pinned chat rows via `ChatItem`) stays the **neutral inset** recipe per Decision 1 (retire the `dark:bg-gray-900` vs `dark:bg-gray-850` drift by settling on `dark:bg-gray-850`). Collapsed rail (835–1040) keeps its `rounded-xl`/`size-9`/`dark:hover:bg-gray-850` idiom — already on-recipe.

**Cross-file note (Decision 8):** chat-mode section headers render through `Folder.svelte` `name=` (1341/1354/1418/1454/1492), a different mechanism than the raw uppercase labels in Notebook/Code modes. To bring *all* section labels to the one recipe, restyle inside `Folder.svelte` — out of scope for these six files; do it in the same pass or flag as a follow-up so labels don't converge in only two of three modes.

### Untouched (Step 2)

All `href`/`goto`, `Folder` grouping logic, `ChatItem` data/handlers, collapse state (`sidebarCollapsed`), pin logic (`pinned.ts` is pure data — nothing to restyle).

### Deploy + verify (Step 2)

Rebuild → restart nginx → `:9000` blue theme. Confirm: mode switcher active segment shows blue text on the raised surface with no shadow; Integrations active row is blue-tint; New Chat is the blue accent row; recents selection is neutral; one hover shade (`gray-850`) everywhere; collapse still unmounts the panel and the center expand chevron appears.

---

## Step 3 — Notebook sidebar restyle (`NotebookNav.svelte`)

**File:** `front_end/owui/src/lib/components/layout/NotebookNav.svelte`. Markup/classes only.

| Line | Change |
|---|---|
| 65 (New notebook) | **Accent action row** (prototype `.newchat`): `space-x-3`→`gap-3`; `rounded-2xl`→`rounded-xl`; text→`text-blue-600 dark:text-blue-400 font-medium`; hover→`hover:bg-blue-500/10`; icon → blue. (Decision 6 alt: neutral `text-gray-700 dark:text-gray-300`, hover `dark:hover:bg-gray-850`.) |
| 93 (ONB item base) | Row → base recipe; `rounded-2xl`→`rounded-xl`; hover→`dark:hover:bg-gray-850`. |
| 96 (ONB item active — route-like) | → **route/nav-active blue-tint** `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium` (replaces `bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-50`); active icon → blue. |
| 97 (ONB inactive) | text `dark:text-gray-200`→`dark:text-gray-300`; hover→`dark:hover:bg-gray-850`. |
| 119 (Customize) | Same as 93/97. |
| 138 (section label "Recents") | → canonical section-label recipe: `pb-0.5`→`pb-1`, `tracking-wider`→`tracking-wide`, `font-semibold`→`font-medium`. |
| 150–154 (recent-notebook rows — list selection) | `rounded-2xl`→`rounded-xl`; hover→`dark:hover:bg-gray-850`; active (153) → **neutral inset** `bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-50 font-medium` (Decision 1 — swap to blue-tint here if the user chooses single blue-tint). Unify gap to `gap-3`. |

Fixes the in-file drift: one gap (`gap-3`, retiring `space-x-3` at 65), one inactive text (`text-gray-700 dark:text-gray-300`), one radius (`rounded-xl`), one hover (`dark:hover:bg-gray-850`), and the label recipe now matches Code mode.

### Deploy + verify (Step 3)

Rebuild → restart nginx. Switch to Notebook mode: ONB nav (Sources/Ask&Search/Transformations) active row is blue-tint; New notebook is the blue accent row; Recents selection is neutral; "Recents" label matches the canonical recipe; theme toggle re-skins cleanly.

---

## Step 4 — Build sidebar restyle (`VibeCodeNav.svelte` + `SidebarMore.svelte`)

**Files:** `front_end/owui/src/lib/components/layout/VibeCodeNav.svelte` and `SidebarMore.svelte`. Markup/classes only; session CRUD handlers, routes, and `SidebarMore` toggle logic untouched.

### 4a. `VibeCodeNav.svelte`

| Line | Change |
|---|---|
| 100 (New session `<a>`) | **Accent action row**: `space-x-3`→`gap-3`; `rounded-2xl`→`rounded-xl`; text→`text-blue-600 dark:text-blue-400 font-medium`; hover→`hover:bg-blue-500/10`; icon → blue. (Decision 6 alt: neutral.) |
| 129, 138 (Routines / Customize) | `rounded-2xl`→`rounded-xl`; hover→`dark:hover:bg-gray-850`; text→`text-gray-700 dark:text-gray-300` (unify with 100). |
| 152 (section label "Sessions") | → canonical section-label recipe (`tracking-wider`→`tracking-wide`, `font-semibold`→`font-medium`, `pb-0.5`→`pb-1`). |
| 176–178 (session row outer — list selection) | `rounded-2xl`→`rounded-xl`; hover→`dark:hover:bg-gray-850`; active (177) → **neutral inset** `bg-gray-100 dark:bg-gray-850` (Decision 1 — blue-tint if single-tint chosen). |
| 186–187 (session row text) | active → keep neutral `text-gray-900 dark:text-gray-50 font-medium` (list selection); inactive `dark:text-gray-200`→`dark:text-gray-300`. |
| 195 (unviewed dot) | `bg-blue-500` → **canonical live-dot `bg-blue-500 dark:bg-blue-400`**; viewed pip keeps the neutral `border border-gray-300 dark:border-gray-600`. |
| 164 (rename input) | Add **`focus-visible:ring-2 focus-visible:ring-blue-500/40`** (blue focus affordance); `rounded-lg`→`rounded-xl`; keep `bg-gray-100 dark:bg-gray-850 border-0`. |
| 209, 217 (rename/delete micro-buttons) | `rounded-md`→`rounded-lg`; keep neutral / `hover:text-red-500`; hover-bg `dark:hover:bg-gray-800`→`dark:hover:bg-gray-850`. |
| 146 (`SidebarMore` inset) | Leave the `-mx-[0.4375rem]` counter-inset as-is (structural; `SidebarMore` re-adds its own `px-[0.4375rem]`). |

Collapses the four-radius zoo to two (`rounded-xl` rows / `rounded-lg` micro-buttons), one gap (`gap-3`), one inactive text, one hover shade.

### 4b. `SidebarMore.svelte` (the "More" flyout)

| Line | Change |
|---|---|
| 85 (toggle button) | `rounded-2xl`→`rounded-xl`; hover `dark:hover:bg-gray-900`→`dark:hover:bg-gray-850`. |
| 86 (toggle open) | Keep `dark:bg-gray-850`; optionally add `text-blue-600 dark:text-blue-400` when open for accent consistency (matches the route/nav-active family). |
| 132 (flyout island) | **Kill the raw hex:** `dark:bg-[#0c111d]` → **`dark:bg-gray-900`** (token). **Reduce shadow:** `shadow-xl shadow-black/40` → `shadow-lg shadow-black/20` and lean on the existing `border` hairline. Keep `rounded-2xl` (floating island). |
| 140 (flyout item active — route-like) | → **route/nav-active blue-tint** `bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium` (replaces `bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-50`). |
| 141 (flyout item hover) | `dark:hover:bg-gray-800` → `dark:hover:bg-gray-850` (collapse the third hover shade). |
| 119 (chevron) | `text-gray-400` — leave. |

### Deploy + verify (Step 4)

Rebuild → restart nginx. Build/Code mode: New session is the blue accent row; unviewed dot is the canonical blue live-dot; session selection is neutral; rename input shows a blue focus ring; open the More flyout and confirm **no raw-hex background survives** (inspect element → `gray-900` token), the shadow is lighter, and the active flyout item is blue-tint. Theme-toggle to confirm re-skin.

---

## Decisions the user must make

1. **Active-state recipe** *(defaulted: two-tier — route/nav-active blue, list selection neutral).* Alternative: single blue-tint on every active row (owui audit's literal recommendation). Swap points: `Sidebar` recents (`ChatItem`), `NotebookNav:153`, `VibeCodeNav:177`.
2. **Home greeting** *(recommend: fixed prototype "What do you want to explore?").* Alternative: keep owui's random `_greetings` (`:83–101`).
3. **Explore chips** *(recommend Option A: replace `Suggestions` with the ready-made `starters` array `:107–128`).* Alternative: restyle `Suggestions.svelte` in place (touches a file outside the given anchors).
4. **Footer status dot** *(default: keep green `--ok`).* Alternative: `bg-blue-500 dark:bg-blue-400` for a single-accent rail.
5. **Mode-switcher active segment** *(recommend blue text `text-blue-600 dark:text-blue-400`).* Alternative: neutral card + `ring-1 ring-blue-500/20`, matching the prototype's neutral active segment.
6. **"New …" action rows** *(recommend accent-blue, mirroring the prototype `.newchat`).* Alternative: neutral, per the owui restyle audit.
7. **Connect-tray + carousel** *(recommend ship — the task lists both as launcher blocks).* These are net-new markup and need six brand marks; defer either if brand assets aren't ready. Both are additive and reversible (local state, no store).
8. **`Folder.svelte` section headers** — chat-mode labels render through `Folder.svelte`, outside the six files. Restyle there in the same pass for label parity across all three modes, or take it as a follow-up.

## Reversibility

Every edit is a class/markup swap around preserved anchors; no logic, route, store, socket, or event-dispatch changes. The two new home blocks (tray, carousel) are gated on local state and can be removed by deleting their `{#if}`/block without affecting send. All token changes are `gray-*`/`blue-*` with `dark:` pairs, so a revert is a straight class diff and the theme changer keeps working throughout.

## Files touched

- `front_end/owui/src/lib/components/chat/Placeholder.svelte` (Step 1)
- `front_end/owui/src/lib/components/chat/MessageInput.svelte` (Step 1 — one `relative z-10` wrapper edit; optional token polish)
- `front_end/owui/src/lib/components/layout/Sidebar.svelte` (Step 2)
- `front_end/owui/src/lib/components/layout/ModeSwitcher.svelte` (Step 2)
- `front_end/owui/src/lib/components/layout/NotebookNav.svelte` (Step 3)
- `front_end/owui/src/lib/components/layout/VibeCodeNav.svelte` (Step 4)
- `front_end/owui/src/lib/components/layout/SidebarMore.svelte` (Step 4)
- *(follow-up, out of the six-file scope)* `front_end/owui/src/lib/components/layout/Folder.svelte` — section-label parity (Decision 8)
- *(optional, Explore-chips Option B)* `Suggestions.svelte`

Global deploy after each step: rebuild owui → `docker restart` nginx → verify on `:9000` in the default blue theme, then toggle Airy/Midnight to confirm token inheritance and that no coral/violet/sky leaks in.