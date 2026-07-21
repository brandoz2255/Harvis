# Harvis UI — Reference Library

Liked UIs and directions the user is collecting to steer the Harvis redesign. **Append new
references here** (the user is sending more). `DESIGN.md` distills the agreed direction from these;
this file keeps the raw captures. Each reference = source + overall vibe + what to borrow + palette
+ how it maps to Harvis (which is dark/cyan today, with a planned theme changer).

---

## Ref 1 — Manus "MetricFlow Analytics Dashboard" (Airy / Scandinavian Minimal)

**Source:** a Manus agent session the user liked (5 screenshots, captured 2026-07-16). Manus explored
three directions ("Soft Office / Neo-Brutalist Pastels", "Airy Dashboard / Scandinavian Minimal", …)
and shipped the **Airy** one. The user likes the shipped result.

**Overall vibe:** clean, **light**, airy, **data-first** dashboard. Pure-white cards on a cool
light-gray page, soft diffuse shadows, generous whitespace, `rounded-xl/2xl` corners, **pastel-tinted
accent cards**. Reads calm, glanceable, trustworthy — the opposite of cramped or "vibecoded".

### What to borrow (patterns — most are theme-agnostic)

- **KPI cards** — a 4-column row of stat cards, each with a **soft pastel tint** (mint/green,
  lavender/purple, peach, sky/cyan), a small icon top-right, a big bold metric, and a **delta chip**
  with an up/down arrow (green up / red down) + "vs last month". This is the signature element.
- **Sidebar** — light, ~240px: brand lockup (rounded-square icon + name + "Analytics" subtitle) at
  top; **sectioned nav** with uppercase group labels (ANALYTICS / BUSINESS / SETTINGS); the **active
  item is a soft-blue pill** (tinted bg + blue icon/text); inline status badge ("Live" green pill on
  Real-time); a **user card** (avatar + name + role) pinned to the bottom.
- **Header / toolbar** — page title + muted subtitle ("Overview" / "Last 30 days · All Segments"),
  a rounded **search** field, notification bell, avatar; a filter row of **pill dropdowns**
  ("Last 30 days", "All Segments") + a "Refresh" pill button.
- **Charts** — soft and uncluttered: a line chart with **dual series (solid + dashed)** and a floating
  **hover tooltip card** showing exact values; a bar chart with muted purple bars; faint gridlines,
  legend below, rounded card container.
- **Data table** — avatar (colored initials circle) + name/email, an action label, a **status/tier
  pill** (Enterprise = purple, Pro = blue, Starter = amber), right-aligned amount; generous row
  height, hairline dividers.
- **Type** — **Plus Jakarta Sans** (clean geometric humanist sans; friendly but professional).
- **Shape/depth** — `rounded-xl/2xl`, soft diffuse shadows, cards **lift on hover**.

### Palette (approximate, from the screenshots)

- Page background: cool light-gray (~`#F5F6F8`); cards: pure white.
- Text: near-black charcoal (~`#1C1C1E`); muted labels in cool gray.
- Interactive/active accent: **indigo/blue** (~`#6366F1`); chart lines in purple + cyan.
- Pastel KPI tints: mint/green · lavender · peach · sky/cyan (each very light, ~5–12% saturation).
- Semantic: green (positive delta), red (negative delta); tier pills purple / blue / amber.

### How it maps to Harvis

- **Best fit = a new LIGHT theme** for the planned **theme changer**: call it **"Airy" / "Daylight"** —
  light-gray canvas, white cards, indigo accent, pastel stat tints. This gives Harvis a credible
  light mode with real personality (not just an inverted dark theme).
- **Borrow the structure into the current DARK theme too** (theme-agnostic): the pastel-tinted-KPI
  pattern (tints become low-alpha color washes on dark cards), the **sectioned sidebar + active-pill**,
  **status/tier pills**, the **breathable spacing**, and the **chart tooltip-card** treatment.
- **Watch-outs for Harvis:** Harvis is dark-first with a **cyan** accent (not indigo) and a **robot
  mascot** brand — keep the brand identity; adopt the *layout/rhythm/components*, adapt the *hue*
  (cyan in dark, indigo optional in the Airy light theme). Type stays Harvis's Inter/Archivo unless
  we deliberately adopt Plus Jakarta Sans.

---

### Higher-fidelity detail (2nd screenshot batch)

**The prompt that generated it** (verbatim — this IS the intent to preserve):
> "Build a simple analytics dashboard for a fictional SaaS tool called *MetricFlow*. Purpose: show
> KPIs and charts in a **clean, glanceable** layout. Core Features — KPI cards (Revenue, Active Users,
> Conversions) · Line chart + bar chart sections · Filter bar (date range, segment) · Data table of
> recent activity · Sidebar navigation. **Visual Vibes: Minimal, rounded corners. Colors: white and
> pastel colours.**"

**The three directions Manus brainstormed** (chosen = "Airy"; the others are useful alternates):
- **"Soft Office" — Neo-Brutalist Pastels** (not chosen, but a strong alt): **display serif** headings +
  **mono** for all metric values, flat cards with a **thick 4px pastel left-border** instead of shadow,
  strict **8px grid**, numbers-as-hero, warm off-white `#FAFAF8` canvas, text `#1C1C1E`, accent soft
  indigo `#6366F1`, sidebar 240px, pill filter chips, hover lifts cards, active sidebar item = pastel
  bg fill. → a bolder, more editorial option if we ever want one.
- **"Airy Dashboard" — Scandinavian Minimal** (CHOSEN, described above).

**KPI card anatomy (now clear at hi-res):** each card = a **pastel-tinted upper block** (uppercase
colored label + a **big bold metric in the matching hue** — green `$128,450`, purple `24,891`, coral
`3,742`, cyan `2.4%` — + a circular icon top-right) sitting over a **white footer** that holds the
**delta chip** (green ↑ / red ↓ + "vs last month"). `rounded-2xl`, soft diffuse shadow. This
tinted-top-over-white-footer split is the signature move.

**Charts (precise):** line chart has a **dual Y-axis** ($ left, count right), Revenue = solid purple
with dots, Active Users = **cyan dashed** with dots, faint dashed gridlines, legend dots below; bar
chart = **grouped pairs** per segment (Target = light lavender, Conversions = purple), legend below.

**Table:** colored-initials avatar · name over muted email · action label · **tier pill** (Enterprise
purple / Pro blue / Starter amber) · right-aligned amount · hairline row dividers.

**Tech under the hood (relevant to us):** React + TS + **TailwindCSS**, **OKLCH color tokens**
(e.g. borders `oklch(0.905 …)`) — **same OKLCH approach Harvis already uses** — and a **ThemeProvider**
in `App.tsx`. Manus's own suggested follow-up was *"add a dark-mode toggle to the header for theme
switching"* → this look is explicitly **light+dark theme-ready**, so it slots cleanly into our theme
changer as the **"Airy" light theme** without fighting the token system.

## Ref 2 — Claude.ai (Anthropic) — Warm editorial / literary chat UI

**Source:** the actual Claude.ai web app (2 screenshots: home + a chat with the Chat-controls rail),
captured 2026-07-16. This is the **reading/chat surface** counterpoint to Ref 1's data dashboard.

**Overall vibe:** **warm, editorial, literary, calm.** A **cream/paper** canvas (not white, not cool
gray), a **serif display face** for headings/titles, a **coral/terracotta** accent, generous
whitespace, soft rounded cards with hairline warm borders. Feels like a beautifully-set reading app,
not a SaaS dashboard. Where MetricFlow is *glanceable data*, this is *comfortable reading*.

### What to borrow

- **Warm-paper palette.** Cream/off-white canvas; cards a touch lighter with hairline warm-gray
  borders; text a warm near-black/umber. Accent = **coral/terracotta** (the ✳ sparkle mark, the coral
  "Start new chat" link). Secondary CTA = **soft purple/lavender** (Upgrade/Pro). A genuinely WARM
  system — opposite of Harvis's cool blue-charcoal and Ref 1's cool gray.
- **Serif-forward typography.** A **serif display** face for the greeting ("Good evening, Robert"),
  chat-card titles, and the "Claude" wordmark; **chat body text is also serif** (comfortable measure,
  generous line-height) → an editorial, book-like reading feel. UI chrome (labels, menus) stays a
  quiet sans. (Claude uses a Tiempos/Copernicus-style serif.)
- **Home layout.** Centered **big serif greeting** with the coral ✳ mark; a slim status pill ("Using
  limited free plan · Upgrade"); a rounded alert card; a **"Your recent chats" grid** of cards (icon +
  serif 2-line title + relative timestamp + hairline border) with "View all →".
- **Sidebar.** Warm cream, serif "Claude" wordmark, **coral "Start new chat"** (+ icon), "Starred" and
  "Recents" sections (each row = chat-bubble icon + title), an account chip at the bottom. Minimal, quiet.
- **⭐ The account menu = the theme-switcher pattern to copy directly.** Account popover → **Appearance
  → submenu (System ✓ / Light / Dark)**. This is *exactly* the UX for Harvis's planned theme changer —
  a clean Appearance submenu; we extend it to **named themes**.
- **Right controls rail ("Chat controls").** A slide-in right panel: model line ("Claude 3.5 Sonnet ·
  Most intelligent model · Learn more"), **Artifacts** (cards: icon + "Click to open · N versions"),
  **Content** (empty state + helper), **Chat styles** (Font: dropdown). Mirrors Harvis's controls/
  artifacts rail — a reference for grouping, empty states, and a "Chat styles / Font" control.
- **Chrome.** Soft rounded (rounded-lg/xl), hairline warm borders, low-contrast dividers, lots of air;
  simple quiet line icons.

### Palette (approx, from the screenshots)

- Canvas: warm cream (~`#F0EBE0` / `#F5F1E8`); cards a touch lighter with hairline warm-gray borders.
- Text: warm near-black / umber (~`#2B2A26`); muted warm-gray for timestamps/labels.
- Accent: **coral / terracotta** (~`#D97757`, the Anthropic clay) for the mark + primary links.
- Secondary: soft purple/lavender (~`#6B5BD6` tint) for Pro/upgrade CTAs.

### How it maps to Harvis

- **This is THE reference for Harvis's Chat + Notebook (reading/writing) surfaces.** The editorial /
  serif / warm treatment fits reading and composition far better than a data-grid look.
- **Becomes a "Warm / Editorial" theme** in the theme changer (with light + a warm-dark variant): cream
  + coral light, warm-charcoal + coral dark. Harvis keeps its cool cyan-on-near-black as the default
  **"Midnight"** theme; Ref 1 becomes **"Airy"**; this becomes **"Warm."**
- **Build the theme changer as Claude's Appearance submenu does it** (System/Light/Dark → extend to
  named themes). Put it in Harvis's Settings/account area.
- **Watch-outs:** serif *body* text is a real shift for Harvis (currently Inter/Archivo sans) — make it
  a **per-theme font** (the "Warm" theme swaps in a serif reading face; other themes stay sans). Keep
  the Harvis robot mascot + wordmark; adopt the calm rhythm + the Appearance-menu theme UX.

---

## Emerging direction (after Ref 1 + Ref 2)

Two references, two surface personalities — and that's the insight, not a conflict:

| Surface | Reference | Feel | Theme it seeds |
|---|---|---|---|
| **Build / data / analytics** | Ref 1 — MetricFlow | cool, airy, pastel, glanceable, sans | **"Airy"** (light) |
| **Chat / Notebook (reading & writing)** | Ref 2 — Claude.ai | warm, editorial, serif, calm | **"Warm"** (light + dark) |
| **Current Harvis (default)** | — | cool cyan-on-near-black, dark-first, sans | **"Midnight"** (dark) |

This is the strongest possible argument for the **theme changer**: rather than pick one look, ship
**Midnight / Airy / Warm** as selectable themes (each a token map, per-theme font allowed), built via
the **Appearance-submenu** UX from Ref 2. Per-page redesign then leans on the matching reference —
Chat/Notebook toward Warm-editorial patterns, Build toward Airy-dashboard patterns — while all three
themes stay swappable. `DESIGN.md` will fold this in as the target direction.

<!-- Ref 3 — (append next reference here) -->
