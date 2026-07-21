# Plan of Action — 2026-07-18+ (user-ordered goal list, grounded in code)

> Companion to `docs/handoffs/2026-07-17-eod-launcher-prototype-tomorrow-list.md`. Every claim below comes
> from a 3-agent code-mapping pass over the real owui tree (Settings / Notebook / Build+loading), not recall.
> Standing rules: work on `harvis1.1` MAIN tree; each build phase = one Fable-5 build→verify workflow;
> deploy = owui `npm run build` → restart nginx-proxy (hard refresh); backend = `docker restart harvis-backend`;
> **no push until David verifies E2E**; never fabricate data; dangerous actions stay approval-gated.

---

## Phase 1 — Functionality pass: Settings · Notebook · Code/Build

**Goal:** everything reachable works or is honestly hidden. Fix real bugs; kill dead controls.

### 1a. Settings (SettingsModal.svelte + 10 panels)
- **BUG (silent data corruption):** `General.svelte:84-85` saves `presence_penalty` and `repeat_penalty`
  from `params.frequency_penalty` — copy-paste bug. Fix the two lines.
- **BUG (theme divergence):** `General.svelte` applyTheme legacy branch force-sets `--color-gray-800..950`
  to neutral hexes on plain 'dark', clobbering the OKLCH blue-charcoal ramp — 'Dark' from Settings ≠ 'Dark'
  after reload. Route everything through `applyThemeById` with no inline var overrides.
- **DEAD (Account tab):** profile save POSTs `/api/v1/auths/update/profile` — not implemented in the facade
  (`owui_compat/router.py:98-156`). Either implement the facade route or disable the form. API-keys section
  defaults visible (`enable_api_keys ?? true`) but `/api/v1/auths/api_key` doesn't exist → always errors;
  gate it off. Also: raw JWT copy row in Account — consider removing (leak surface).
- **DEAD (~70% of DataControls):** export/import/archive-all/delete-all/shared-chats hit facade routes that
  don't exist (only `/chats/archived` + files work). Implement the few worth having (export at minimum) and
  hide the rest.
- **TRAP (Interface tab):** vestigial `defaultModelId` plumbing — pressing Save can silently reset the
  user's default model to the admin default (`Interface.svelte:179-184`, `:272-274`). Remove the plumbing.
- **DEAD WEIGHT:** Personalization + Connections tabs are permanently hidden by config flags but ship
  components + search keywords; About tab is upstream Open WebUI branding with external shields.io images
  (breaks offline). Remove/replace with Harvis about.
- **Verify gate:** every visible control in every tab round-trips (change → save → reload → persisted);
  hidden tabs stay hidden; no console errors.

### 1b. Notebook — LANE DECISION REQUIRED (ask David before building)
Two parallel UIs share one backend: the **iframe lane** (vendored open-notebook Next app at `/onb` — the one
actually reached everywhere) and the **native lane** (`notebooks/[id]/+page.svelte`, 652 lines, NotebookLM
3-column — **orphaned**, nothing navigates to it).
- **Option A (recommended for the calm-paper goal):** promote the native page — it's themeable; the iframe
  never will be. Requires: wire chat persistence (backend `chat/history` exists, frontend never calls it),
  stream the chat (currently blocking 30-40s POST with a static "Thinking…"), SSE source-status (backend
  exists, UI renders 'pending' forever), per-notebook Create (quiz/flashcards — only in the iframe today),
  markdown rendering, de-emoji, tokens instead of raw blue-600/gray.
- **Option B:** keep the iframe, accept Notebook can't join the 3-theme system.
- Either way: fix silent error-swallowing in `apis/notebooks/index.ts` (auth failure renders as an empty
  notebook, no toast).
- **Verify gate:** create → add source (watch status progress) → grounded chat (persists across reload) →
  note; Recents updates without a 30s wait.

### 1c. Code/Build cockpit (vibecode/+page.svelte + agent-studio/build/*)
- **Fail-soft blindness:** with the backend down everything renders as calm emptiness ('No sessions yet.',
  empty repo menu) — add a real error/degraded state; SSE 'connecting' forever (RunView/ThoughtStream) needs
  a timeout → retry affordance.
- **SSE regression risk:** `PlanPanel.svelte:37` opens its OWN stream instead of the shared `runStream`
  store (re-approaches the 6-connection cap Debt-D1 fixed). Port it to `subscribeRun`.
- **DEAD CODE DECISION (ask David):** `WorkspaceRightRail.svelte` (303 lines, zero importers) + unconsumed
  reactives — delete, or resurrect as the calm inline-approvals card replacing the blocking full-screen
  approval modal? (The spec's drawer direction favors resurrect-as-inline.)
- Dead affordances visible to users: permanent 'No preview available yet.' Preview tab, mic placeholder,
  'SSH soon' disabled item, unreachable Connect-GitHub CTA, hardcoded localhost quick-links in BrowserPanel.
  Hide or fix each.
- Status-color drift: 'done' is blue in PlanPanel, emerald in BackgroundTaskCard, blue in RunView — one
  semantic color everywhere (green per the spec).
- **Verify gate:** full Build run E2E on gemma4:12b (plan → steps → diff → approval → local commit offer);
  backend-down shows an honest error; only one SSE per run.

## Phase 2 — Settings UI redesign
After 1a, restyle to the calm direction: replace the 9 hand-duplicated ~25-line nav buttons (ternary class
soup) with one row recipe; sidebar-nav rail styled like the app sidebar (quiet labels, soft active pill);
panels adopt the drawer section language (RailCard-ish groups, roomy rows). Fold the Theme `<select>` into
the Appearance submenu component (one `selectTheme()` path). Keep search. Restyle mobile pill row without
the hand-rolled `getElementById` wheel listener.
**Verify:** all tabs re-skinned in Warm/Airy/Midnight, no raw hex, functionality from 1a intact.

## Phase 3 — New mascot
Design a second Harvis robot variant (pose/expression set) as a themeable component like `HarvisMark`
(accent-driven gradients, no hardcoded blue). Candidates: a "working" pose for Build/loading states and/or
a flat mark for the website. Get David's pick from 2-3 sketches BEFORE wiring it in.

## Phase 4 — Loading + workspace polish
- **Splash:** `app.html` — fix the `html.harvis-dark #splash-screen` rule that never matches (boot adds
  `theme-harvis-dark`, rule expects `harvis-dark`) causing a #000→#0e111a flash; give airy/warm their paper
  splash colors (today they flash #fff); keep the logo circle but add motion + hand off to skeletons.
- **Skeletons (generalize ChatItemSkeleton):** chat-history open (bare centered spinner, `Chat.svelte:3626`),
  VibeCodeNav + NotebookNav first-fetch ('No X yet.' lies during load), Build model menu, notebooks iframe
  (no shim at all), ThoughtStream first frame ('Connecting…' → content-shaped shimmer rows).
- **Workspace (Build) theming:** the cockpit is hardcoded dark (`bg-[#080c16]`, `bg-[#0b101b]`, etc. across
  BuildHeader/+page/WorkspaceMainPanel/BrowserPanel/ShellTab) — tokenize so Airy/Warm don't get a dark slab.
  Micro-type (text-[10px]/[11px]) lifted to the readable scale.
- **Verify:** cold load in all 3 themes = correct splash tone → skeletons → content; no 'No X yet.' flash.

## Phase 5 — Deploy test
Full-stack rebuild + restart (owui build → nginx restart, backend restart), cache-busted browser pass over
Chat / Settings / Notebook / Build in all 3 themes on :9000. Console-clean gate. David does a hands-on pass.

## Phase 6 — Push (gated) + retest
**ASK first** (standing rule): `harvis1.1` is ~25 ahead incl. `3fd5d0a5`. After David's explicit go:
push, re-pull sanity check, redeploy from the pushed ref, retest the Phase-5 checklist. Mention the known
push-caveats from the 07-16 handoff (force-push helper, Discord IDs in compose, schema-init note).

## Phase 7 — install.sh help/UX pass (new item 9)
`install.sh` EXISTS at repo root (README routes users through it). Harden for open-source onboarding:
`--help` with real usage, preflight checks (docker/compose/GPU/ports/DNS), `.env` scaffolding with generated
secrets (JWT_SECRET, OPENCLAW_GATEWAY_TOKEN — never committed), backend/engine choice, idempotent re-runs,
clear failure messages, and a post-install smoke check (curl :9000). Test from a clean clone.
**Verify:** fresh-clone → `./install.sh` → working stack, no manual edits.

## Phase 8 — Main website
Marketing/landing site for the open-source project (separate from the app). Reuse the Warm-paper design
language + new mascot; sections: what Harvis is (local-first OpenWebUI replacement / open Claude option),
quick-start (`./install.sh`), feature tour (Chat/Build/Notebook/providers/skills), GitHub link. Static site
(no backend) — hostable on Pages. Design-first with the prototype workflow (David reviews before build).

## Phase 9 — Adaptive Space
Resume the ringed-HUD adaptive workspace (`b0963d3a` base): next steps were gated sandbox run + preview
surfaces. Re-scope AFTER phases 1-8 land; fold into the new Build/preview toolbar language from the spec.

---

# ▮ THE ROADMAP — status + running order

> **Naming, set by the user 2026-07-19:** *"the checklist"* and *"the roadmap"* both mean **this
> document**. `2026-07-19-master-checklist.md` is the 71-item *inventory* — refer to that one by
> name. This one is the *sequence*.
>
> Statuses below were re-verified against the working tree, not read back from an earlier snapshot.
> This section replaces the two earlier status blocks; keep it as the single source of truth.

## All 9 phases

| Phase | Status | Where it stands |
|---|---|---|
| **1a** Settings functionality | 🟢 **DONE (2026-07-20)** | Dead-weight Connections/Personalization removed from Settings modal; About rebranded (no shields.io); JWT copy row removed; `enable_api_keys`/`enable_memories` default false in facade config. |
| **1b** Notebook | 🟢 **CLOSED** | Decided: keep the current lane as-is. Podcast + NotebookLM features later, as their own work. Native package off the list; the orphaned 652-line page **stays** as its base. Accepted: `/onb` can't join the 3-theme system. |
| **1c** Build cockpit | 🟢 **~95% (2026-07-20)** | Dead affordances hidden (Preview tab, mic, SSH soon, unwired Connect-GitHub CTAs); BrowserPanel quick-links use this origin; ThoughtStream token streaming + 20s stall retry; runStream immediate flush for tokens/tools. |
| **2** Settings UI redesign | 🟢 **DONE** | 12 tabs on `SettingsSection`/`SettingRow`. Independently audited: compiles, every control survived, no save handler lost a key. |
| **3** New mascot | 🟢 **DONE (2026-07-20)** | Charcoal cube terminal w/ hat, moustache, bow tie, amber H, deployable hover vanes. `harvis-startup.webm` (one-shot) → `harvis-idle.webm` (loop), handoff 97.2% IoU. Reusable green-screen pipeline + player. Committed `3c7917da`. **This UNBLOCKS Phase 8.** |
| **4** Loading + workspace polish | 🟡 **~90%** | Splash/skeletons/cockpit tokens/reduced-motion done. **2026-07-20:** progressive Build stream (token + tool flush). **Left:** micro-type lift (50×10px / 77×11px); raw hex in 8 non-cockpit files. |
| **5** Deploy test | 🟡 **NEXT — hands-on before push** | Built + deployed + specific fixes runtime-verified many times. **Left: the hands-on 3-theme pass over Chat/Settings/Notebook/Build with the console open.** This is yours; skeletons and per-theme splash are transient and can't be checked from code. |
| **6** Push | 🔴 **AFTER Phase 5** | Decided: goes to a **separate remote branch**, not `origin/harvis1.1`. Currently 36+ commits ahead + dirty tree (installer wizard + this polish). |


> **Setup-flow build (2026-07-20):** Phase-7 groundwork landed as 7 commits (a1d44602..9a278715). Backend honesty foundation done + **verified live** — health endpoint now reports real DB/TTS status (was permanently 'degraded'); server-side signup enforcement works on BOTH routes (403, 0 leak) which **closes T2**; setup-code first-signup gate, fresh-volume DB bootstrap, `/api/setup/*` probe router, and `install.sh --check-only` behavioral compose gate all built. ⚠️ **The adversarial pass (pen-test/honesty/regression) died on a session limit and has NOT run** — first-signup-race, nginx-429, and fresh-volume-abort repro are agent-claimed, not independently verified. UI steps 8–10 (the `/setup` wizard) not started.

| **7** install.sh UX | 🟢 **DONE in code (uncommitted leftovers)** | Preflight, secrets, health poll, setup code, `.env.example`, skippable model pull, `/setup` wizard. **Left:** commit remaining files; clean-clone E2E; honest amd note if untested. |
| **8** Main website | ⚪ **not started — UNBLOCKED** | Static, no backend. Was waiting on the mascot; that landed 2026-07-20. |
| **9** Adaptive Space | ⚪ **not started — LATER** | Base `b0963d3a`; next was gated sandbox run + preview. Re-scope when reached. |

## Running order — confirmed by the user 2026-07-19 · updated 2026-07-20

**NOW:**

1. ~~Finish the in-flight 5-task security/cleanup order~~ — T1+T2 done; **T3–T5 still open**.
2. ~~Phase 7 — install.sh hardening~~ — code complete; **commit + clean-clone verify**.
3. **Phase 5 — the deploy test.** Full 3-theme hands-on pass. *Your* step; it gates the push.
4. **Phase 6 — push.** To a separate remote branch, after 3 passes.

**LATER, explicitly deferred:**

- **Phase 8** — main website (mascot unblocked it)
- **Phase 9** — Adaptive Space
- Phase 4 remainder (micro-type / raw-hex outside cockpit)

## The in-flight 5-task order (security + cleanup)

Not part of the original 9 phases — it came out of the `/workspace` + `/admin` investigation.

| # | Task | Status |
|---|---|---|
| T1 | Server-side `require_admin` on every admin/config mutation | ✅ **committed `3c8616b2`** — uncovered that the whole `/api/rag` router was unauthenticated. Verified live: anon 401, non-admin 403. Suite 57 passed / 3 skipped. |
| T2 | Harden fresh-install signup/admin (no silent first-signup admin) | ✅ **committed `783cbada`** + `/setup` wizard (uncommitted) |
| T3 | Hide Share actions everywhere (not building sharing) | ⬜ |
| T4 | Implement Clone (existing create/retrieve fns, no schema redesign) | ⬜ |
| T5 | Remove `/workspace` + `/admin` from nav via reversible flags | ⬜ — user: *"im sure the workspace is also fine as well"* |

Standing constraints on this order: keep `/harvis/knowledge` as the Knowledge interface and
Settings → Customize as the Skills interface; do **not** implement Workspace Models/Prompts/Tools,
multi-tenant Admin, or Audio settings; one commit per task; backend auth tests + frontend build
after each relevant change.

## Work that maps onto no phase

Stated plainly rather than retrofitted. Since these 9 phases were written: Recon #2 and the AI-UX
recon; ~14 shipped honesty fixes including a data-loss bug and a **310-site root cause** in the API
layer (failures returned `null` without throwing); the `require_admin` gate; Agent Studio + Neural
Map marked under construction; and two documented feature directions (Continuity Bridge, OmniRoute).

## Against the older north-star roadmap

`project_roadmap_multiplatform_cli` (2026-06-29) sequences the project as
**(1) multi-platform + multi-config → (2) Harvis CLI → (3) new features.**

Most of this session is genuinely item 1, and **Phase 7 *is* that item** — which is why it sits
ahead of the push here.

**Honest gap: the Harvis CLI (item 2) has had no work and appears in neither this roadmap nor the
71-item inventory.** If that sequencing still holds, it is a missing entry, not a finished one.
