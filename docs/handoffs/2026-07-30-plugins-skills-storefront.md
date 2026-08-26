# Handoff — 2026-07-30: Engines reorder, the Kimi merge, and the Plugins/Skills storefront

**Branch:** `harvis1.2` (main tree at `/home/user/Harvis`, working tree
dirty) · **rig:** the dev box itself, `http://localhost:9000` · **everything below is built,
deployed, and verified live in the browser.**

**Nothing is committed and nothing is pushed.** 18 modified files + 1 new file are sitting in the
working tree waiting on your verification pass. See "Commit plan" at the bottom.

Read the top entry of `changes.md` for the per-change detail. This document is the state of play,
the decisions I made without asking, and what's next.

---

## What this session did

Three phases, all driven by the ChatGPT/Claude screenshots you pasted: make the integrations area
look and behave like a real storefront, fold the two Kimi products into one tile, and give Plugins a
backend that sends people somewhere real instead of nowhere.

### Phase A — Engines: renamed, moved, reskinned, and Kimi merged

- The sidebar's footer row **"Providers" is now "Engines"** and moved from the footer cluster up
  into the chat-mode tools cluster, because it's the first thing a fresh install needs. New order:
  **Engines → Connectors → Artifacts → Schedules**. Customize and Settings stay in the footer.
- The `/harvis/integrations` page got the storefront chrome: sectioned rows instead of a card grid,
  real brand marks, and a detail drawer.
- **The two Kimi products are now one tile with a variant toggle.** They are genuinely different
  products with different credentials, and the old UI shipped them as two unrelated cards:

  | variant | credential | what it drives |
  |---|---|---|
  | Kimi Code (membership) | `engine_api_key` → `owui_compat/engine_auth.py` row | the Claude Code sidecar's tool loop |
  | Moonshot platform | `user_api_key` → `/api/user/api-keys` provider `moonshot` | pay-as-you-go cloud chat |

  `IntegrationVariant` in `lib/integrations/catalog.ts` is the new type. The detail drawer renders a
  radio toggle, and every downstream section — engine-support tone, permissions, auth, links — reads
  from `viewDef` (the merge of the definition and the chosen variant) rather than the definition, so
  switching variants changes the whole drawer, not just the label. An **empty** `permissions` array
  is meaningful and hides the section: a cloud chat key must not advertise shell + repo access.
- Real vendor logos. `simple-icons` 16.27.1 (CC0-1.0) generated into
  `lib/agent-studio/customize/brandMarks.ts` — **50 of the 63 brands the directory names**. The
  other 13 (adobe, canva, salesforce, slack, twilio, teams, outlook, monday, amplitude, consensus,
  descript, gamma, ramp) were dropped from simple-icons over trademark takedowns and fall back to a
  hash-colored lettermark tile; Slack has a hand-tuned multi-color entry in `ConnectorLogo.svelte`.
  Near-black marks carry `dim: true` and get a theme-following gray instead of their own hex, or
  they vanish on dark backgrounds.

### Phase B — Plugins: a storefront with a real backend

`/harvis/agent-studio/mcp-shop` (surface key unchanged, label now **Plugins**) is a sectioned
directory of **71 cards** across 10 sections, up from the 14 installable servers it had before.

The load-bearing decision is the **`connect` taxonomy** in `python_back_end/owui_compat/mcp_catalog.py`.
Every card declares how it can actually be connected, and the UI never offers a button that can't work:

| `connect` | count | UI behavior |
|---|---|---|
| `install` | 14 | Harvis runs the server itself. Connect works, writes an `mcp_servers` row. |
| `remote_oauth` | 15 | Real vendor MCP endpoint, but **Harvis has no OAuth 2.1 + PKCE client** — so no Connect button. The card shows the publisher, the endpoint, and a link to the vendor's own page. |
| `external` | 42 | Directory entry only. Vendor link, no endpoint claim. |

This is what "a proper backend so it takes the user to the official page" means in practice: the
honest answer for 57 of 71 cards is a link, and the card says which kind of link it is instead of
dressing a dead end up as a Connect button. **When an OAuth client lands, the 15 `remote_oauth`
rows become connectable without touching this data** — the taxonomy is the seam.

Per the MCP research you pasted: no new wire protocol was invented. MCP already won; the
contribution here is the catalog and install UX on top of it.

### Phase C — Skills: the same storefront treatment

`SkillsPanel.svelte` now has two mounts off one `mode` prop:

- `mode="full"` (the `/harvis/agent-studio/skills` route) — the centered `Plugins | Skills` pill,
  a "Skills" h1 + tagline, a "Search skills" pill input, refresh, a round `+`, and a
  `Your skills | Directory` segmented control. Rows are an icon tile + name + one-line description
  + a `···` overflow menu (Edit / Audit & verdict / Delete).
- `mode="dock"` (Customize, and the Settings modal) — the old compact header, unchanged.

`mode === 'full'` is a sufficient gate here because there are only two mounts. `ConnectorsPanel`
needed `$page.url.pathname` for the same job because it has three.

The `···` menu replaces hover-only icon buttons, which were unreachable on touch. The Directory tab
mounts the existing `SkillsBrowse.svelte` with a new `showBack={false}` prop — it was rendering its
own "← Skills" button directly under our tabs, two ways back to the same place.

**The Skills SAFETY CONTRACT is untouched.** Browsing is free. Installing imports **only the
SKILL.md text**, as an unaudited DRAFT, via `createNewSkill`. Scripts in a bundle are never
downloaded and never executed, and the backend strips a client-sent `meta.audit`. Only a human
`'supported'` verdict lets a skill inject into chats or publish to OpenClaw, and editing the body
invalidates the verdict.

---

## The one thing standing in the way

**There is no MCP OAuth 2.1 + PKCE client in Harvis.** That single missing piece is what keeps 15
real, live vendor MCP endpoints — Sentry, Linear, Atlassian, Vercel, Supabase, Cloudflare, Asana and
the rest — as link-outs instead of connections. The catalog is already shaped for it: implement the
client, flip nothing in the data, and those cards light up. Worth its own task.

## Two defects found and fixed while building Phase B

1. **`visiblePlugins` was stale after a keystroke.** The filter read `plugins` and `query` through a
   helper function, which hid them from Svelte's reactive tracking. Both are now read directly
   inside the `$:` statement. The same discipline applies to `visibleSkills` in Phase C — don't
   route those reads through a helper.
2. **The embedded Directory had two back buttons** (see `showBack` above). No compile gate could
   have caught this; it took looking at the page.

## Gotchas worth keeping

- **`svelte-check` is unusable on this tree** — 9,729 pre-existing errors drown anything new. The
  working compile gate is a throwaway `svelte/compiler` script that **must live inside
  `front_end/owui/`** (Node can't resolve `svelte` from anywhere else), and **`svelte-preprocess`
  is not installed** — so the script has to blank the TypeScript `<script>` block *and* re-declare
  every name it declared, or store references like `$i18n` fail with "illegal variable name". The
  second gate is a full `npm run build`.
- This is **Svelte 5 in legacy mode**. `$:` reactivity works; `{#snippet}` was not used. Repeated
  row markup in `SkillsPanel` is a `skillSections` array instead.
- Deploy is **rebuild owui, then `docker compose restart nginx`** — `npm run build` does
  `rm -rf build`, which replaces the inode the bind mount pinned.

---

## Verified live (not inferred from a clean build)

At `http://localhost:9000`:

- **Skills surface** — pill navigates both ways (Skills ⇄ Plugins); "Installed" section with three
  tiled rows and a "Turned off" section; `unaudited` verdict chips; On/Off pills; the `···` menu
  opens and closes and "Audit & verdict" expands the governance panel inline; search `pirate`
  narrows to 1 row and drops the empty section; the Directory tab fetches **Anthropic's real live
  skill list** (not just "the tab mounts"); the OpenClaw sync card is unchanged.
- **Dock mount** at `/harvis/agent-studio/customize` keeps its compact header — no pill, no search.
- **Forced light theme** — the hashed tile colors, white letters, chips and pills are all legible.
  A dark-only screenshot can't prove this, which is why it was checked separately.
- **Plugins surface** — sections render, collapse state works, the detail drawer shows publisher,
  endpoint and vendor link for `remote_oauth`, and the `install` rows still connect.
- **Engines** — the Kimi tile's variant toggle swaps the whole drawer, not just the label.

Both edit rounds compiled `OK`, each followed by `npm run build` → exit 0, `docker compose restart
nginx`, nginx → 200.

---

## Commit plan (nothing done yet — awaiting your verification)

Roughly five logical commits over the 19 files:

1. Engines rename + sidebar reorder (`Sidebar.svelte`, `translation.json`)
2. Engines page reskin (`integrations/+page.svelte`, `ControlCard.svelte`, `BrandGlyph.svelte`,
   `status.ts`)
3. Kimi merge — variants (`catalog.ts`, `IntegrationDetailModal.svelte`, `ConnectionPanel.svelte`)
4. Plugins storefront + backend (`mcp_catalog.py`, `mcp_wizard.py`, `ConnectorsPanel.svelte`,
   `ConnectorLogo.svelte`, `brandMarks.ts`, `surfaces.ts`)
5. Skills storefront (`SkillsPanel.svelte`, `SkillsBrowse.svelte`)

## IA decisions I made without asking (all trivially revertible)

- The **sidebar row is still labelled "Connectors"** while the surface it opens is titled
  **"Plugins"**. Deliberate — "Connectors" is the word already in the product's vocabulary, and the
  screenshots you gave were of a page titled Plugins. Say the word and either name wins.
- Inner tabs: `Directory | MCP registry` on Plugins, `Your skills | Directory` on Skills.
- A new **"Your connectors"** section at the top of the Plugins directory.
- Skills rows lost their hover icons in favor of the `···` menu.

## Open, unchanged from yesterday

- **The HTTPS decision** — no TLS means voice only works from `localhost:9000` on the Docker host.
- Restart `harvis-mcp` (stale inode-pinned modules).
- Task #96 — `run_tests` missing from `TOOL_SCHEMA`, phantom `dir_list`, `max_steps` 12.
- Tasks #65 / #66 / #67, and #94 (OpenClaw — needs the symptom first).
- Whether `origin/main`'s 206 older K8s/ArgoCD commits fold into `harvis1.2`.
