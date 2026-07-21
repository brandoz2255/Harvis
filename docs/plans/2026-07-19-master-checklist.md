# Harvis Master Checklist

**Date:** 2026-07-19
**Branch:** `harvis1.1` (main tree), ~90 uncommitted files, nothing pushed
**Method:** 5-agent audit — 3 agents read actual code (Settings refactor · skeleton/theme/mascot ·
whole-tree half-finished sweep), 1 inventoried 11 planning docs, 1 synthesized.

> **Verification note.** I independently re-checked all four Section-A items against the working
> tree rather than trusting the audit. Three confirmed; one had the wrong file path and is
> corrected below. Items elsewhere in this document carry the auditors' confidence, not mine —
> anything they could not verify is marked UNVERIFIED.

---

# Harvis Master Checklist — post-audit, 2026-07-19

## The direct answer first

**No — the work you feared was cut off is not half-built.** Two auditors independently verified, mechanically (compiler runs, control-by-control diffs against HEAD, backend route checks — not by trusting reports), that the dying agent's Settings refactor is **structurally complete**: all 12 tabs compile, every interactive control survived (e.g. Interface 58→58 controls), no save handler lost a key, the SkillsManager swap is fully wired, and the theme system is consistent end-to-end. This audit also effectively closes the "adversarial re-verify of Phases 2/3" caveat from the autonomous-run report — that re-verify has now happened.

What the usage-limit deaths and the marathon run **did** leave behind is small and specific — four items, all small-effort:

1. **The 6 new Settings files are untracked in git** while the 13 files importing them are tracked-modified. A `git commit -a` produces a broken tree. This is the single most dangerous item on this list.
2. **Cancelled runs show an amber dot in the Build run table/rows** — the new status palette was half-applied; two files kept a stale local copy.
3. **Two store imports are missing in `+layout.svelte`** — desktop-shell events throw a ReferenceError (committed at HEAD by the marathon run; web app unaffected).
4. **~25 new i18n strings exist only as literal keys** — cosmetic; English users see correct text.

Everything else on this list is pre-existing documented debt or planned work, not damage from the cutoff.

## Total outstanding: ~71 items

| Section | Count |
|---|---|
| A. Broken / half-built right now | 4 |
| B. Decisions you owe (no code) | 10 |
| C. Known bugs outstanding | 11 |
| D. Build tasks not started | 33 |
| E. Dead code (your call) | 8 |
| F. Feature directions | 5 |

---

## A. Broken / half-built right now

All four independently re-verified against the working tree on 2026-07-19. Ranked by how badly
each bites.

- [ ] **Commit hazard — 6 untracked Settings files.** ✅ **CONFIRMED.** `git status` shows
  `SettingRow.svelte`, `SettingsSection.svelte`, and the whole `Skills/` directory as `??`, while
  **six tracked-modified files import them**: `SettingsModal.svelte:40` (SkillsManager),
  `General.svelte:14-15`, `Interface.svelte:14`, `Personalization.svelte:8`,
  `DataControls.svelte:32`, `Audio.svelte:11`. A `git commit -a` or `git add -u` ships a tree that
  does not build and a dead Settings modal. This repo already lost 7 files once to a `.gitignore`
  bug, so the failure mode is not hypothetical.
  **Fix:** `git add` the new files together with the modified set. `front_end/owui/src/lib/components/chat/Settings/` · **S**

- [ ] **Cancelled runs still render the amber "needs-you" dot.** ✅ **CONFIRMED.**
  `runFormat.ts` was deliberately changed so `cancelled` → gray, precisely so cancellation cannot be
  misread as awaiting-approval. But two files kept **local `dot()` copies** that still map
  `cancelled → 'bg-amber-500'`: [`RunTable.svelte:49-56`](../../front_end/owui/src/lib/agent-studio/RunTable.svelte)
  and [`RunRow.svelte:15-22`](../../front_end/owui/src/lib/agent-studio/RunRow.svelte).
  Both even carry a comment claiming the unified palette. This is a half-applied change of mine.
  **Fix:** delete both local copies, import the shared `statusDot`. · **S**

- [ ] **`models` and `appData` used but never imported.** ✅ **CONFIRMED — but the audit named the
  wrong file.** It cited `routes/(app)/+layout.svelte`, which is only 612 lines and contains
  neither symbol. The real location is **`front_end/owui/src/routes/+layout.svelte`** (root layout,
  1174 lines): `models.set(...)` at **:789** inside the `models:refresh` handler, and
  `appData.set(data)` at **:906**. The `$lib/stores` import block at **:18-41** brings in `isApp`,
  `appInfo`, `desktopEvent` and 20 others — but **not** `models` or `appData`, and there is no other
  import of either.
  **Consequence:** ReferenceError whenever those desktop-shell paths run; the model refresh silently
  never happens. **Desktop shell only — the web app at :9000 never reaches this code.** Already
  committed at HEAD (`2543b27b`), so it is not damage from the usage-limit deaths.
  **Fix:** add the two names to the existing import. · **S**

- [ ] **~25 new i18n keys missing from locale catalogs.** i18next falls back to the key text, so
  English is correct and other locales see English for these strings. Cosmetic, no functional
  breakage. Settings tabs · **S**

---

## B. Decisions you owe (blocking, cheap, no code)

Ranked by how much work each unblocks.

- [ ] **D1. Push go/no-go.** `harvis1.1` is ~25 commits ahead, nothing pushed. Blocks the push+retest task and is your standing "no push until verified" rule — only you can lift it. · start-here, plan
- [ ] **D2. Notebook lane.** Promote the orphaned 652-line native page (nothing routes to it) vs. keep the un-themeable `/onb` iframe. Blocks the entire L-sized notebook package (item in D). · plan 1b, auto-run
- [ ] **D8. The 13 Tier-1 dead routes — gate all vs. build some.** Recon recommends: gate all 13, then build only Share + Clone. Blocks two M tasks in D. · recon2
- [ ] **D7. /workspace + /admin + /playground.** Grant permissions, implement the ~150 unbacked functions (count UNVERIFIED — upper bound from recon), or stop advertising them in the nav. Nav currently promises pages that redirect. · recon2, shipped
- [ ] **D4. Mascot pick** from the 2–3 sketches (D-section task produces them). Also gates the website. · plan Phase 3
- [ ] **D9. Folders vs. Projects** — merge or coexist, before the Projects container upgrade. · ai-ux proposal 4
- [ ] **D3. WorkspaceRightRail** — delete (303 lines, zero importers, still absorbing edits) or resurrect as inline approvals. · plan 1c, halffinished audit
- [ ] **D5. Build-restyle flags (3 sub-calls):** (a) violet on orchestrate/agents — retire or sanction; (b) Discord-chip indigo — brand exception or blue; (c) mic placeholder — remove or keep muted. · restyle
- [ ] **D6. Where does composer mode-switching live** now that launcher mode-pills are gone. · plan
- [ ] **D10. Refero MCP OAuth** — one-time interactive auth; a user action, not a design choice. · tomorrow

---

## C. Known bugs outstanding (found, documented, not yet fixed)

Ranked by user-visible impact.

- [ ] **Error-as-empty-state / stranded-skeleton sweep — 7 surfaces remain.** The exact fixed-in-Models bug still lives in: **Knowledge** (`workspace/Knowledge.svelte:93` — backend hiccup → skeleton shimmers forever, or a server error impersonates "No knowledge found") and **Notes** (`notes/Notes.svelte:215` — identical shape), plus Dev Console, Projects, SubAgents, Webhooks, MCP count (recon2 #6 residue). One pattern fixes all: add a `loadError` flag + error branch with Retry, as Models and SkillsManager already do. **M** · skeleton audit + recon2 + inventory
- [ ] **Mascot waves over finished/cancelled runs.** `RunView.svelte:232` and `WorkspaceRunCard.svelte:491` map done/cancelled to `'idle'`, whose internal cycle waves every ~12s — implying live activity over a dead run. **S** · skeleton audit, recon2 #5
- [ ] **Mascot rAF loops run every frame forever, ignoring `prefers-reduced-motion`.** `HarvisMascot.svelte:67-85`, `HarvisClawMascot.svelte:67-93`. Constant CPU drain on the 8GB target; WCAG violation. (Skeleton/Placeholder animations already honor reduced-motion — the mascots are the stragglers.) Best folded into the "mascot as run-state instrument" build task — same files. **M** · skeleton audit, recon2 #5
- [ ] **Route shadowing:** `searchKnowledgeFiles` vs `/{kb_id}/files` is a **live** bug — the `#` composer file-suggestions are silently wrong; `deleteAllFiles`/`{file_id}` shadow is a time bomb. **S** · recon2 #12
- [ ] **GitHub-status residual quartet:** `getGithubStatus` swallows errors into `{connected:false}` (undermines two shipped fixes), `savePool` out-of-order PUT race, no busy-guard on modal Disconnect, `listUserGithubRepos` returns `[]` on failure. **S** · shipped doc
- [ ] **Integrations panel presents frozen data as live** when the 7s poll fails — needs a staleness indicator. **S** · recon2 #14
- [ ] **`stopTask` latent bug** — stub returns no task ids, so stop handlers never fire; bites the moment real ids are emitted. **S** · recon2
- [ ] **Tier-3 flag gaps** — direct URLs to Channels/Notes/Calendar/vanilla-automations render fully broken pages; add the missing `config.py` flags. **S** · recon2
- [ ] **Skills imports arrive `enabled`** (should land toggled off — needs a backend create field); `github.com/<o>/<r>/raw/` URL variant unparsed. **S** · eod-0717
- [ ] **Multi-model compare columns all read "HARVIS"** instead of the real model per column. **S** · eod-0717
- [ ] **Theme cosmetics (grouped, all low-stakes):** `open-notebook/src/lib/theme-script.ts:11` maps `her` to dark while `themes.ts:73` says light (the /onb iframe goes dark under the egg theme); `app.html:56` `her` pre-hydration frame lacks the light class (splash covers it); pre-existing invalid space-containing id in `Interface.svelte`. **S** · skeleton + halffinished audits

---

## D. Build tasks (not started unless marked)

Ranked by user-visible impact within rough clusters.

**Honesty & correctness**
- [ ] **Honesty-gate the 13 Tier-1 dead routes** (Share, Clone, Set-status, memories, `/` prompts menu, changelog, Gravatar, user-info, archived export/unarchive-all, OAuth-session disconnect, stats export, usage row) with the established `*_AVAILABLE` pattern. Blocked on D8's exact split. **M** · recon2 #9
- [ ] **Implement Share + Clone chat backend routes** — the two worth building; unblocks the dead `/s/[id]` public page. **M** · recon2 #10
- [ ] **Build cockpit degraded/error states — remainder.** PARTIAL: auto-run wired error props and hardened the poll loop, but the SSE "connecting forever" timeout→retry and an honest backend-down state are **UNVERIFIED** — confirm before assuming done. **S–M** · plan 1c, auto-run
- [ ] **Build dead affordances** — permanent "No preview available yet." tab, mic placeholder (D5c), "SSH soon" item, unreachable Connect-GitHub CTA, hardcoded-localhost quick-links in BrowserPanel. Hide or fix each. **S** · plan 1c, restyle
- [ ] **Settings dead-weight removal** — flag-hidden-but-shipped Personalization + Connections tabs, About tab rebrand off upstream OWUI + shields.io (breaks offline), raw JWT copy row (leak surface). **S–M** · plan 1a

**Accessibility**
- [ ] **Global reduced-motion sweep** — 89 animation-class uses vs 1 `motion-safe:`; infinite offenders across ~14 files (run-card ring/ping, shimmer, CallOverlay visualizers). **M** · recon2
- [ ] **aria-label sweep** — ~12 unlabeled controls; 9 surfaces fixed by one ellipsis-menu pattern change. **S** · recon2 #11
- [ ] **Six custom overlays → `common/Modal`** (or add Escape + focus trap + `role="dialog"`), PrDrawer first. **M** · recon2 #13
- [ ] **Contrast sweep** — `dark:text-gray-600` visible text, tiny gray-on-dark type, measured per all three themes; includes AdaptiveSpaceShell 8.5px micro-type. **M** · recon2 #15
- [ ] **Heading/label semantics pass** — chat home has no heading; `aria-busy` absent from RunView/ThoughtStream; ~295 unlabeled inputs (upper bound, UNVERIFIED precision). **M** · recon2

**AI-UX proposals (all 9 unbuilt; ai-ux doc)**
- [ ] **Mascot as run-state instrument** — pose vocabulary mapped 1:1 to `runStages.ts`; implement the currently-dead `'talking'` state; one-shot wave then static on done. Subsumes both mascot bugs in C. Recommended first of the nine. **S**
- [ ] **Command palette** — actions + navigation + settings tabs + SearchModal as a mode. **M**
- [ ] **Notify-on-done + ambient sidebar mark** — logo breathes on any-run-active; browser Notification on background completion (**verify existing wiring first**). **S–M**
- [ ] **Projects container upgrade** — scoped chats + knowledge + per-project instructions; audit `harvis/projects/[id]` depth first; blocked on D9. **M–L**
- [ ] **Local/cloud usage page** — split free-local vs paid-cloud; needs a backend endpoint; never fabricate quota bars. **M**
- [ ] **@-mention engine mid-thread** — extend composer Models command (verify current behavior first). **S–M**
- [ ] **Run replay** — **verify server-side event persistence exists before committing**. **M**
- [ ] **Selection-targeted edit in artifacts/canvas** — highest uncertainty; do last. **M**
- [ ] **Guided empty states** — do opportunistically alongside the Projects upgrade. **S**
- (For the record, the explicit do-NOT-build list stands: real-time collab, mobile app, hosted publishing, cloud push/email, keybindings, mascot cameo toasts.)

**Build cockpit & visual system**
- [ ] **Composer/header token restyle (Steps 1–2)** — the 12+7-edit punch-list (canonical Send recipe, retire sky, one border pair, chip convergence, etc.). ⚠ The composer split already shipped, so **the doc's line numbers have drifted — re-locate before editing**. Carries D5. **S** · restyle
- [x] ~~**Cockpit full tokenization**~~ — ✅ **ALREADY DONE (corrected 2026-07-19).** The checklist inherited this from the 2026-07-18 plan, which predates the Build restyle. Verified: **zero raw hex** across all 9 `lib/agent-studio/build/*.svelte` files and the vibecode page. Airy/Warm no longer get a dark slab.
- [ ] **Raw-hex debt MOVED, not gone** — 8 other files still carry `[#rrggbb]`: `ArtifactPreview.svelte`, `IntegrationCard.svelte`, `WorkflowInspector.svelte`, `adaptive/AdaptiveSpaceShell.svelte`, `ConnectionPanel.svelte`, `customize/ConnectorLogo.svelte`, `adaptive/PrototypeTestPanel.svelte`, `CommandBlock.svelte`. **M** · verified 2026-07-19
- [ ] **Cockpit micro-type lift** — outstanding and now measured: **50× `text-[10px]` + 77× `text-[11px]`** across the build cockpit, to lift to the readable scale. **M** · plan Phase 4, verified 2026-07-19
- [ ] **New mascot design sketches** — 2–3 themeable variants in all 3 themes → produces D4. Distinct from the run-state-instrument task (that's behavior; this is a new design). **S–M** · plan Phase 3
- [ ] **Icon normalization** — agent-studio inline SVGs → `icons/` components per `front_end/owui/ICONS.md`. **S–M** · eod-0717
- [ ] **`Folder.svelte` chat-mode section-label parity.** **S** · eod-0717
- [ ] **Launcher functional wiring** — connect-tools tray → real per-chip links to `/harvis/integrations`; capabilities carousel → real redirects. (Third TODO, explore-ideas branching, is moot — block deleted.) **S** · eod-0717

**Verification & shipping**
- [ ] **Full 3-theme cache-busted deploy test** — Chat/Settings/Notebook/Build on :9000 in Midnight/Airy/Warm. Subsumes the auto-run caveats that settings tabs, skeletons, and per-theme splash were **never visually eyeballed** — the code-level audits are done, the eyeball pass is not. **S** · plan Phase 5
- [ ] **Push + retest** — blocked on D1; carries the 07-16 caveats (force-push helper, Discord IDs in compose, schema-init note). **S** · plan Phase 6
- [ ] **install.sh help/UX pass** — `--help`, preflight, `.env` scaffolding with generated secrets, idempotent re-runs, fresh-clone smoke test. Hardening, not greenfield. **M** · plan Phase 7

**Larger queued builds**
- [ ] **Notebook native-lane package** (if D2 = promote): chat persistence, streaming, SSE source-status, per-notebook Create, markdown/de-emoji/tokens; either lane: fix the silent error-swallow in `apis/notebooks/index.ts`. **L** · plan 1b
- [ ] **Main website** — static landing, Warm-paper + new mascot; blocked on D4. **L** · plan Phase 8
- [ ] **Adaptive Space resume** — ringed-HUD at `b0963d3a`; next was gated sandbox run + preview; re-scope after the above. **L** · plan Phase 9
- [ ] **"Harvis Code" settings page** — blocked: backend flags don't exist; don't fabricate controls. **M** · eod-0717
- [ ] **Prototype parallel track** (non-blocking): Build-cockpit prototype mirror, `harvis-ui-craft` SKILL.md (research cached, authoring died mid-run — resume), official brand SVGs for the connect strip. **S–M each** · tomorrow, plan

---

## E. Dead code — remove or resurrect (your call)

- [ ] **Orphaned 652-line native notebook page** at `routes/(app)/harvis/notebooks/[id]/+page.svelte` — nothing links to it, but it's a live route if typed. This IS decision D2. **S** to delete · halffinished audit
- [ ] **`WorkspaceRightRail.svelte`** — zero importers, yet still absorbing maintenance edits (including its own stale cancelled=amber `dot()`). This IS decision D3. **S** to delete · halffinished audit
- [ ] **`Placeholder.svelte` orphans** from the explore-ideas deletion — `Suggestions` import never rendered, ~10 unused imports, dead `onSelect` prop, unused `models`/`selectedModelIdx`/`studioEnabled`. **S** · skeleton audit
- [ ] **42 caller-less frontend API functions** (recon2 census) + vestigial `themes` array at `General.svelte:18`. **S** · recon2, restyle
- [ ] **`bgDot`/`bgStatusLabel`** in `vibecode/+page.svelte:262-276` — superseded by `runFormat` helpers, never called. **S** · halffinished audit
- [ ] **`defaultModelId` dead state** in `Interface.svelte:39,192-194,286-290` — no UI control exists; the save-guard is deliberate and harmless. Keep the guard, or remove the state entirely. **S** · halffinished audit
- [ ] **Mascot `'talking'` state** — in the type union, no rendering branch, zero call sites. Implement it via the run-state-instrument task, or drop it from the union (trivial). · skeleton audit
- [ ] **Junk comment** `Knowledge.svelte:247` ("The Aleph dreams itself into being…") — committed at HEAD, the only one in the repo. **S** · halffinished audit

---

## F. Feature directions (large, documented, not started)

- [ ] **Continuity Bridge — Phase 1 (Manual Continuity Pack)** — pack format, export assembly, HANDOFF.md, redaction guarantee; ~60% of the capture layer already exists, so this is mostly assembly. **M** · design/2026-07-18-continuity-bridge.md
- [ ] **Continuity Bridge — Phases 2–5** — local resume/reconciliation, automatic checkpoints + crash-recovery screen, provider adapters, browser/desktop capture. Prompt-injection boundary designed in from Phase 1. **L** · same doc
- [ ] **OmniRoute evaluation** — read the proxy + key-handling code, confirm the no-client-key invariant survives behind `model_proxy`, weigh dependency load. Adopt-candidate; supersedes building OmniRouter. **M** · research/2026-07-18-omniroute-tinker-inkling.md
- [ ] **Tinker** — check private-beta availability; best fine-tune target named: tool-call formatting. **S** · same doc
- [ ] **Inkling** — hosted evaluation only (cannot run on 8GB); test calibration inside the agent loop. **S–M** · same doc

---

## If you only do five things

1. **`git add` the 6 untracked Settings files and commit the working set** (A1). Ten seconds of work prevents the only realistic way the finished Settings refactor becomes broken.
2. **Fix the two half-applied leftovers** — cancelled-amber dots in RunTable/RunRow and the missing `models`/`appData` imports in `+layout.svelte` (A2 + A3). Both are one-line-class fixes.
3. **Run the error-as-empty-state sweep** across Knowledge, Notes, and the other five surfaces (C1). It's one established pattern applied seven times, and it kills the worst live user-facing bug class: infinite skeletons and false empty states.
4. **Do the mascot bundle as one job** — stop-on-done, reduced-motion gate, and the run-state-instrument upgrade (C2 + C3 + the first ai-ux proposal). Same files, ~1 day, fixes a WCAG violation and a battery drain while shipping the most-recommended UX feature.
5. **Resolve D1 and D2.** They cost you nothing but a decision and are the two biggest blockers: the push (~25 commits sitting local) and the L-sized notebook package.
---

# ▮ PROGRESS — 2026-07-19 working session

Built, deployed to `localhost:9000`, and runtime-verified. **Still not pushed.**

## Section A — all 4 CLOSED

- [x] **A1 Commit hazard** — and it was **bigger than documented**. The audit found 6 untracked
  Settings files; a systematic sweep found **11 untracked source files**, including
  **`lib/themes.ts`** — imported by 7 files including `app.html` and `routes/+layout.svelte`, i.e.
  the entire theme system. Committing without it would have broken the build outright, not just the
  Settings modal. Also `Skeleton.svelte` (12 importers), `HarvisLogoMark`, `Swatch`,
  `ChatItemSkeleton`. All staged; **zero untracked source files remain.**
- [x] **A2 cancelled=amber** — and this was bigger too. The audit named 2 files; the real count was
  **8**. Worse, four of them also mapped **`done` → blue** (blue means *running*), and
  `ResearchRunCard` showed a *running* research as **amber**, which reads as "needs you." All live
  sites now match the canonical palette. The only remaining `cancelled→amber` is in the dead
  `WorkspaceRightRail.svelte` (zero importers, pending decision D3).
- [x] **A3 missing store imports** — `appData` + `models` added to `routes/+layout.svelte`. Swept
  every other store referenced in that file for the same bug: none missing.
- [x] **A4 i18n keys** — the audit estimated ~25, the verifier found 11 more. A tree-wide scan found
  **1,142 unregistered keys** across all of `src/`. All registered in `en-US` per the repo's
  empty-string convention (2,318 → 3,597).

## Section C — the recurring bug class, fixed at the ROOT

- [x] **C1 error-as-empty-state** — the checklist said "7 surfaces." The root cause turned out to be
  **310 sites across 26 API helper files**: `error = err.detail` leaves `error` undefined when the
  rejection has no `.detail` (a fetch `TypeError` when the backend is down, or a `SyntaxError` when
  nginx returns 502 HTML), so `if (error) throw error` never fires and the helper **silently returns
  `null`**. An entire failure class was invisible.
  **261 sites fixed** to the codebase's own established fallback; 49 were already safe and left
  alone. Plus honest error states with Retry on: Knowledge, Notes, Dev Console, Projects, SubAgents,
  Webhooks, and the MCP count/list.
  **Blast radius was measured, not assumed** — an adversarial verifier sampled 12+ call sites for
  unhandled rejections and confirmed no caller goes from "never throws" to "throws" (backend-JSON
  errors already threw); three caller-side guards were added where a null return was load-bearing.
- [x] **C2 mascot waves over finished runs** — new `idleCycle` prop; both run-status call sites pass
  `idleCycle={running}`, so a completed or cancelled run holds still. The chat-home greeting mascot
  keeps its ambient cycle, which is correct there.
- [x] **C3 mascot rAF / reduced-motion** — both mascots now honour `prefers-reduced-motion` (WCAG
  2.3.3) live via `matchMedia`, hold a static pose when it's set, and **stop the rAF loop entirely
  when the tab is hidden**.
- [x] **Multi-model Compare showed "HARVIS" in every column** — defeating the feature's whole point.
  Now shows the real model name when `selectedModels.length > 1`; single chat keeps the wordmark.
- [x] **`Valves.svelte` blank panel** (found by the verifier, unflagged by all three fix agents) — a
  throw stranded `loading = true`, so `{#if show && !loading}` rendered nothing at all: no content,
  no error, no way out. Now try/finally + an honest error branch with Retry.

## Section E — dead code removed

- [x] `Placeholder.svelte` orphans from the explore-ideas deletion — unused `Suggestions` import,
  the write-only `models`/`selectedModelIdx` cluster, unread `studioEnabled`.
  **Correction:** the audit called `onSelect` dead; it is **not** — `Chat.svelte:3581` passes it.
  Left in place.
- [x] `bgDot`/`bgStatusLabel` in the vibecode page — dead *and* carrying a stale cancelled=amber.
- [x] The stray "Aleph" junk comment in `Knowledge.svelte`.

## Runtime verification

Same forced-failure technique as before, against the deployed app:

```
forced 503 → showsHonestError: true · falseEmptyState: false · hasRetry: true
clean load → real content ("Pirate Project ⚓ · 2 chats"), no false error, nothing stuck
```

## Deliberately NOT done, with reasons

- **`getTools` / `getBanners` still swallow to `[]`.** The verifier correctly refuted the fix
  agent's "0 exceptions" claim — these two have `if (error) return []` downstream, so the bug class
  survives in them. Left alone: it is **pre-existing fail-soft, not a regression**, and changing
  banner/tool-loading semantics immediately before a deploy is scope creep with real caller risk.
- **The raw JWT copy row in Account.** It is masked behind a `SensitiveInput` with reveal and is a
  legitimate developer affordance. The plan said "consider removing" — that is a decision, not a bug.
- **`WorkspaceRightRail.svelte`** — left intact pending decision D3.
- **`git push`** — decision D1, unchanged. Nothing was pushed.

## Second pass — 2026-07-19 (post-decisions)

- [x] **B2 · `getGithubStatus` no longer swallows errors.** It returned `{connected:false}` on any
  failure, indistinguishable from a genuine "not connected" — and it undermined two fixes already
  shipped. Now returns `null` for "couldn't check", and **all four call sites** handle that
  distinctly: the two panels keep the last known state and offer Retry instead of claiming
  disconnection, and both OAuth poll loops keep polling on a failed check rather than concluding
  "not connected yet" (their attempt caps still bound the loop).
  *Config risk: none — GitHub credentials are per-user, not per-deployment.*

- [x] **H3 · Global reduced-motion (WCAG 2.3.3).** 86 infinite animations (`animate-pulse` ×49,
  `spin` ×23, `ping` ×14) across 62 files, with exactly **one** `motion-safe:` guard and **no global
  rule**. Rather than tag 86 class uses across 62 files — churny, easy to miss one, and no help for
  future code — added **one rule to `app.css`** covering everything now and later.
  Uses `0.01ms` rather than `animation: none` deliberately: `none` would strand any element whose
  animation *reveals* it (starting at opacity 0), leaving it permanently invisible. Collapsing the
  duration lets the animation reach its end state instantly.
  **Verified both directions:** the rule is in the live cascade, and with the preference OFF
  `animate-pulse` still computes `2s / infinite` — normal motion is untouched for everyone else.
  *Config risk: none — it keys off an OS-level user preference; the default path is unchanged.*
  *Note: the mascots read the same media query in their own JS, because CSS can't reach a rAF loop.*
