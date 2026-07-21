# Task briefs — what each remaining item actually does

**Date:** 2026-07-19
**Companion to:** `docs/plans/2026-07-19-master-checklist.md` (the inventory)
**Purpose:** so each task has a correct, bounded goal before anyone touches code.

Every entry has the same shape:

- **Goal** — one line, what "done" means
- **Touches** — the files/systems in scope
- **Blast radius** — what else could move if this goes wrong
- **⚠ Config risk** — how it interacts with *other people's* setups (nvidia/amd/cpu, docker vs k8s, admin vs user, offline, other locales)
- **Scope boundary** — explicitly what is NOT part of this task

Harvis ships to multiple targets: docker-compose on nvidia/amd/cpu, k3s+Flux, and laptops, with
per-deployment feature flags and per-user permissions. **A change that is correct on this dev box can
be wrong on someone else's.** The config-risk line exists to catch exactly that.

---

# TIER 0 — Decisions (no code, and they gate everything else)

These cost nothing but an answer. Two of them each gate an entire work package.

### D1 · Push go/no-go
- **Goal:** decide whether `harvis1.1` (25 commits, ~130 changed files) goes to origin.
- **⚠ Config risk:** the push itself is safe; what follows is not. The 07-16 handoff flagged three
  caveats to re-check first — the force-push helper, Discord IDs sitting in compose, and a
  schema-init note. Those are exactly the "works here, breaks there" class.
- **Scope boundary:** this is a yes/no. It is not "push and also clean up history."

### D2 · Notebook lane
- **Goal:** pick ONE — promote the orphaned native page (`harvis/notebooks/[id]/+page.svelte`, 652
  lines, themeable, nothing routes to it today) **or** keep the vendored `/onb` iframe (works now,
  can never join the 3-theme system).
- **Blast radius:** gates an L-sized package (chat persistence, streaming, SSE source status,
  per-notebook Create, markdown rendering).
- **⚠ Config risk:** the iframe lane depends on the `open-notebook` container being up. Promoting
  the native lane removes a container dependency — a *simplification* for other deployments.
- **Scope boundary:** decide the lane. Do not start building either until decided.

### D3 · `WorkspaceRightRail.svelte`
- **Goal:** delete (303 lines, zero importers) or resurrect as inline approvals.
- **Note:** it is still absorbing maintenance edits despite being dead — it carries its own stale
  `cancelled=amber` copy that I deliberately left alone pending this decision.
- **Scope boundary:** if delete, delete only this file. It has no importers, so nothing else moves.

### D4 · Mascot pick · D5 · Build-restyle colour flags · D6 · Composer mode-switching home · D9 · Folders vs Projects
- Pure design calls. D4 additionally gates the website (Phase 8).

### D7 · `/workspace` + `/admin` + `/playground`
- **Goal:** decide whether these surfaces get permissions, get built, or get hidden.
- **Why it matters:** verified live — user `cisco` is `role=user` with all four
  `permissions.workspace.*` set false, so `/workspace/models` redirects to `/`. **The nav currently
  advertises pages that don't open.**
- **⚠ Config risk (high):** this is per-deployment *and* per-user. An admin sees working pages; a
  normal user sees redirects. Any fix must be driven by the real permission/flag, never hardcoded,
  or one deployment's correct behaviour becomes another's broken nav.
- **Scope boundary:** ~150 unbacked functions live behind these routes. This decision does **not**
  authorize implementing them.

### D8 · The 13 Tier-1 dead routes
- **Goal:** decide gate-all vs build-some. Recon's recommendation: gate all 13, then build only
  Share and Clone.
- **Scope boundary:** the decision. The gating work is a separate task below.

### D10 · Refero MCP OAuth — a one-time interactive auth you have to perform; not a design call.

---

# TIER 1 — Known bugs (bounded, low config risk)

### B1 · Route shadowing — `searchKnowledgeFiles`
- **Goal:** the `#` file-suggestion menu in the composer returns the right files.
- **What's wrong:** `searchKnowledgeFiles` collides with `/{kb_id}/files`, so results are **silently
  wrong today** — not empty, *wrong*, which is worse. A second shadow (`deleteAllFiles` `/files/all`
  vs `/files/{file_id}`) is a time bomb but not yet firing.
- **Touches:** the knowledge API routes (frontend + the matching backend route order).
- **⚠ Config risk:** route ORDER matters in FastAPI. Reordering to fix the shadow can change which
  handler wins for other paths. Verify against the live route table, not by reading.
- **Scope boundary:** fix the shadowing. Do **not** redesign the knowledge file API.

### B2 · `getGithubStatus` swallows errors
- **Goal:** distinguish "not connected" from "couldn't check."
- **What's wrong:** it returns `{connected:false}` on any failure, so a transient network blip
  renders as a disconnected account — and it undermines two fixes already shipped (the disconnect
  honesty work), because a failed disconnect followed by a failed status re-sync still shows
  "disconnected."
- **⚠ Config risk:** low. GitHub connectivity is per-user credential, not per-deployment.
- **Scope boundary:** this one helper and its two callers. Not a general integrations refactor.

### B3 · Integrations panel presents frozen data as live
- **Goal:** when the 7s poll fails, say so rather than showing stale state as current.
- **Scope boundary:** add a staleness indicator. Do not change the poll interval or the card layout.

### B4 · Tier-3 flag gaps
- **Goal:** a direct URL to Channels / Notes / Calendar / vanilla-automations should not render a
  fully broken page when that feature is off.
- **⚠ Config risk (high — this IS a multi-config bug).** These surfaces are feature-flagged, so the
  breakage only appears in deployments where the flag is off. It is invisible here if our flags are
  on. **Test with the flags actually off.**
- **Scope boundary:** add the missing `config.py` flags and gate the routes. Do not build the
  features.

### B5 · Skills import arrives enabled
- **Goal:** an imported community skill lands **disabled** and unaudited, per the governance model.
- **Why it matters:** this is the security-relevant one. The whole skills design is fail-closed —
  only a human `supported` verdict lets a skill inject. A skill arriving pre-enabled weakens that.
- **Touches:** needs a backend create field; the frontend then respects it.
- **Scope boundary:** default-off on import. Do **not** touch the verdict/injection gate itself —
  that gate is working and is the thing protecting you.

---

# TIER 2 — Honesty + accessibility sweeps (repetitive, low risk, high user value)

### H1 · Honesty-gate the 13 Tier-1 dead routes
- **Goal:** every control that hits a non-existent backend route is visibly disabled with
  "Not available in this deployment" instead of silently failing or 404-ing into a toast.
- **The 13:** Share chat, Clone chat, Set-status, Personalization memories, the `/` prompts menu,
  changelog, Gravatar, user-info, archived export, unarchive-all, OAuth-session disconnect, stats
  export, usage row.
- **⚠ Config risk (this is the crux):** "doesn't exist" is true *for this deployment*. Use the
  established single-flip `*_AVAILABLE` const pattern so a deployment that later gains the route
  re-enables it by flipping one value. **Never delete the UI** — deleting it means another
  deployment that has the route loses the feature.
- **Scope boundary:** gate them. Do not implement any of them here.

### H2 · Implement Share + Clone chat backend routes
- **Goal:** the two worth actually building; Share also unblocks the dead `/s/[id]` public page.
- **⚠ Config risk:** Share creates a **publicly reachable** URL. That is an outward-facing surface —
  it needs its own auth/permission decision before it ships, not after.
- **Scope boundary:** these two routes only.

### H3 · Global reduced-motion sweep
- **Goal:** honour `prefers-reduced-motion` across the app. Currently 89 animation-class uses vs a
  single `motion-safe:`. The mascots are already done; the rest are not — run-card ring/ping,
  shimmer, CallOverlay visualizers, ~14 files.
- **⚠ Config risk:** none. It's an OS-level user preference; the default path is unchanged.

### H4 · aria-label sweep · H5 · Six custom overlays → shared `Modal` · H6 · Contrast sweep · H7 · Heading/label semantics
- Accessibility. H5 is the one with real blast radius: moving overlays onto `common/Modal` changes
  Escape and focus-trap behaviour. Do **PrDrawer first**, verify, then continue — and remember the
  Escape layering fix already shipped, so any new modal must not re-break it.
- H6 must be measured **per theme** — Midnight, Airy, and Warm have different grounds, so a contrast
  fix for one can fail another.

---

# TIER 3 — Build / visual work

### V1 · Build composer + header token restyle
- **Goal:** retire sky/violet, unify on the accent, one border pair, canonical Send recipe.
- **⚠ Warning:** the composer split already shipped, so the restyle doc's **line numbers have
  drifted**. Re-locate before editing.
- **Scope boundary:** composer + header. The cockpit is already fully tokenized (verified: zero raw
  hex) — don't redo it.

### V2 · Cockpit micro-type lift
- **Goal:** raise 50× `text-[10px]` and 77× `text-[11px]` to the readable scale.
- **⚠ Risk:** this is a *density* change. Larger type reflows the cockpit; check it doesn't overflow
  on smaller screens.

### V3 · New mascot sketches → produces D4. · V4 · Icon normalization (agent-studio inline SVGs → `icons/` per `ICONS.md`). · V5 · `Folder.svelte` section-label parity.

### V6 · Launcher functional wiring
- **Goal:** the connect-tools tray chips link to `/harvis/integrations`; the capability carousel
  redirects somewhere real. Both are decorative flags today.
- **Scope boundary:** wire the two. The third original TODO (explore-ideas branching) is **moot** —
  that block was deleted at your request.

### V7 · Settings dead-weight removal
- **Goal:** stop shipping permanently-hidden Personalization + Connections tabs; replace the About
  tab (still upstream OpenWebUI branding, and its shields.io images **break offline**).
- **⚠ Config risk:** "permanently hidden" is per-deployment flag state. Confirm the flags can't be
  turned on anywhere before removing, or you delete a working tab for someone else.

---

# TIER 4 — The 9 AI-UX proposals (none built)

Ranked by value-per-effort in `docs/research/2026-07-18-ai-ux-recon-and-proposals.md`.

1. **Mascot as run-state instrument** — poses mapped 1:1 to `runStages.ts`; implements the currently
   dead `talking` state. *Partly done already*: the reduced-motion gate and stop-on-done shipped
   today, so this is now smaller than the doc says.
2. **Command palette** — actions + navigation + settings tabs, with SearchModal as a mode.
3. **Notify-on-done + ambient sidebar mark** — ⚠ *verify the existing notification wiring first*;
   some of it may already exist.
4. **Projects container upgrade** — blocked on D9.
5. **Local/cloud usage page** — needs a new backend endpoint. **Never fabricate quota bars** — if
   the number isn't real, don't draw it.
6. **@-mention engine mid-thread** — verify current composer behaviour first.
7. **Run replay** — ⚠ **verify server-side event persistence exists before committing to this.**
8. **Selection-targeted edit in artifacts/canvas** — highest uncertainty; do last.
9. **Guided empty states** — do opportunistically alongside #4.

**Explicitly do NOT build** (the recon's own negative list): real-time collab, a mobile-native app,
hosted artifact publishing, cloud push/email notifications, custom keybindings, mascot cameo toasts.

---

# TIER 5 — Shipping + platform (highest config risk on the whole list)

### S1 · Full 3-theme cache-busted deploy test
- **Goal:** hands-on pass over Chat / Settings / Notebook / Build in Midnight, Airy, and Warm, with
  a console-clean gate.
- **Why it's still open:** the code-level audits are done; the *eyeball* pass is not. Skeletons and
  the per-theme splash have never been visually confirmed — they're transient by nature.

### S2 · Push + retest — blocked on D1; carries the three 07-16 caveats.

### S3 · `install.sh` hardening — **the most config-sensitive task on the list**
- **Goal:** a stranger clones the repo, runs `./install.sh`, and gets a working stack with no manual
  edits.
- **Current state (verified):** it exists, 107 lines, executable, and the nvidia/amd/cpu backend
  picker works. What's missing is the onboarding hardening — a real `--help`, preflight checks
  (docker/compose/GPU/ports/DNS), `.env` scaffolding with **generated** secrets, idempotent re-runs,
  clear failure messages, and a post-install smoke check.
- **⚠ Config risk (maximum):** this file *is* the multi-config surface. Every change must be tested
  on more than one backend path, and **secrets must be generated, never committed**.
- **Scope boundary:** harden the existing script. Do not rewrite the compose topology.

### S4 · Notebook native package (L) — only if D2 = promote.
### S5 · Main website (L) — static, no backend, blocked on D4.
### S6 · Adaptive Space resume (L) — base `b0963d3a`; next was gated sandbox run + preview. Re-scope after the above.
### S7 · "Harvis Code" settings page — **blocked**: the backend flags don't exist. Do not fabricate controls for them.

---

# TIER 6 — Feature directions

### F1 · Continuity Bridge Phase 1 — manual Continuity Pack
- **Goal:** a `Save handoff` button producing a portable pack (manifest, HANDOFF.md, git capture,
  diffs, test summary, a generated Claude resume prompt).
- **Why it's tractable:** ~60% of the capture layer already exists (`preflight.py`, `isolation.py`,
  `workspace_events`, `build_narrator.py`, `engine_adapter.py`). Phase 1 is mostly assembly.
- **⚠ Two non-negotiables, designed in from day one:** no secret VALUES in a pack (`X is configured`,
  never `X=value`), and **an imported pack is untrusted input** — data, never instructions. Tool
  grants flow only through the existing `authorize_action` choke point.

### F2 · Continuity Bridge Phases 2–5 (L) · F3 · OmniRoute evaluation · F4 · Tinker · F5 · Inkling

- **F3 ⚠:** OmniRoute would sit behind `model_proxy` and hold every provider credential. Confirm the
  no-client-key invariant survives, and weigh the embedded Redis/Bifrost/Mux dependency load against
  our already-heavy compose.
- **F5 ⚠:** Inkling is 975B total / 41B active. It **cannot run on the 8GB dev GPU**. Hosted
  evaluation only — do not plan a local deployment.

---

# The standing rules that keep this safe

1. **Never delete a UI because *this* deployment lacks the route.** Gate it behind a single flippable
   const so a deployment that has the route keeps the feature.
2. **Feature-flag bugs are invisible when your own flags are on.** Test with the flag off.
3. **Permissions are per-user, not per-build.** `role=user` and `role=admin` see different apps.
4. **Never fabricate a number.** No quota bars, benchmarks, or counts that aren't real.
5. **Secrets are generated, never committed.**
6. **Verify before claiming.** "Done" means observed working — and for error-path fixes that means
   forcing the failure, because a healthy backend proves nothing.
7. **No push or deploy without explicit approval.**

---

# ▮ DECISIONS MADE — 2026-07-19

## D1 · Push — DEFERRED, with a safer shape agreed

**Not now.** Keep working against the current local state.

**When it happens, it goes to a SEPARATE remote branch — not `origin/harvis1.1`.** That is a
materially safer plan than the original and worth locking in: it gets ~132 files of work off this
one disk without touching the branch anyone else might pull.

Sequence agreed:
1. Visual pass (S1) — the 3-theme hands-on check
2. Final build
3. *Then* push to a separate remote branch
4. `origin/harvis1.1` stays untouched until after that

**Still gated:** no `git push` of any kind until step 3 is explicitly called. **No new commits
either** without asking — the standing rule covers commits as well as pushes. The 11 previously
untracked source files (incl. `lib/themes.ts`) remain **staged** so that whenever a commit does
happen, it cannot ship a broken tree.

## D2 · Notebook lane — DECIDED: keep the current lane, leave as-is

The notebook was only lightly changed for UI purposes. Podcast support and further NotebookLM-style
features come later, as their own piece of work.

**Consequences for the list:**
- **S4 (notebook native package, L) is OFF the list.** Not deferred — not being done.
- **The orphaned native page `harvis/notebooks/[id]/+page.svelte` (652 lines) STAYS.** Do **not**
  delete it. It is the plausible base for the later NotebookLM work, so deleting it now would just
  mean rewriting it later. Its entry under Section E is resolved as *keep*.
- **Still worth doing, small and lane-independent:** the silent error-swallow in
  `lib/apis/notebooks/index.ts` — an auth failure currently renders as an empty notebook with no
  toast. Same honesty class as everything fixed today.
- **Accepted trade-off:** the `/onb` iframe cannot join the 3-theme system. Notebook will not
  re-skin with Midnight/Airy/Warm. That is a known, chosen limitation — not a bug to file.

## Remaining open decisions

D3 (WorkspaceRightRail) · D4 (mascot pick) · D5 (3 restyle colour calls) · D6 (composer
mode-switching) · D7 (`/workspace` + `/admin`) · D8 (13 dead routes) · D9 (Folders vs Projects) ·
D10 (Refero MCP OAuth).

**D7 and D8 are now the two that gate the most work.**
