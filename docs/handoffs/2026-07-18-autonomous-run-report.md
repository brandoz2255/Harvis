# Autonomous run report — 2026-07-18

User left with four asks: (1) finish item-#1 functionality, (2) finish the Settings UI,
(3) build skeletons properly, (4) recon other AI products → propose UI options + a session
mascot. "Don't ask me, I'll review when I'm back." This is what happened.

**Nothing pushed.** All work is uncommitted on `harvis1.1` in the MAIN tree.

---

## ✅ Phase 1 — functionality (SHIPPED, deployed, E2E-verified)

Fable-5 build→verify, all PASS. It found materially more than the plan predicted.

**Two real user-facing bugs**
- `General.svelte:85-86` — `presence_penalty` AND `repeat_penalty` were both saving
  `params.frequency_penalty`. Anyone who tuned those silently wrote the wrong value into all
  three. Fixed; repo-wide grep confirms no other instance.
- `Interface.svelte` — `defaultModelId` reset trap, worse than described: saving an unrelated
  interface toggle wrote `models:[defaultModelId]`, AND `$config.default_models` overwrote the
  user's saved model on mount which then got persisted back. Now only writes `models` when the
  value actually changed, and the user's saved model wins over the server default.

**9 dead backend routes found → honestly disabled** (each verified against
`python_back_end/owui_compat/router.py`, not guessed): profile update, API-key create, chat
import / export-all / shared / archive-all / delete-all, files search. Some 404'd into a toast;
several were *silent unhandled rejections* (clicking did literally nothing). Now visibly
disabled with "Not available in this deployment", behind single-flip `*_AVAILABLE` consts.
**`chats/archived` genuinely exists → left enabled** (verified live: dimmed vs bright).

**Build cockpit** — PlanPanel ported off its private `createWorkspaceStream` onto the shared
refcounted `subscribeRun`; rendered plan output byte-identical. `getVibecodeSessionFiles` now
returns `null` on failure (was `{entries:[]}` — indistinguishable from "no files"). Poll loop
wrapped `try/finally{schedule()}` so one throw can't kill the refresh loop. Several error props
that existed but were never rendered are now wired.

**Status colors unified** (`runFormat.ts`): running=blue-pulse · done=emerald · failed=red ·
waiting/approval=amber · cancelled=gray · idle=gray.

**Notebook** — bounded pre-flight (8s probes of `/onb-api/notebooks` + `/onb`, 20s iframe
watchdog) → 4 honest error kinds (auth/backend/app/frame-timeout) with Retry, replacing the
blank frame / infinite spinner. Verified live: the iframe still mounts and renders normally.

**Two inconsistencies I resolved myself** (verifier flagged them for a decision): PlanPanel's
done-dot was still blue while everything else went emerald → emerald; and `cancelled` shared
amber with awaiting-approval → gray, because amber should mean "needs YOU".

## ✅ Phase 2 — Settings UI (SHIPPED, deployed, spot-verified)

⚠️ The agent **died mid-run on a session usage limit** (resets 9:30pm PT) and returned `null` —
but it had already written its work to disk. I verified what landed rather than trusting it:

- New shared `SettingsSection.svelte` + `SettingRow.svelte`; 12 tabs refactored onto them
  (General, Interface, Audio, DataControls, Personalization, Account, About, Connections,
  Integrations, Terminals, WorkspaceSettings, UpdatePassword).
- Verified live: rows are now title + truthful description left / control right with subtle
  separators — the desktop pattern, no cards.
- **I re-verified every Phase-1 safety property survived the refactor**: penalty keys still
  correct, `initialDefaultModelId` guard present, all 8 disable gates still `false`, zero raw hex.
- Build exit 0.

## ✅ Phase 3 — skeletons (SHIPPED, deployed, verified)

- New `lib/components/common/Skeleton.svelte` primitive — token-driven
  (`bg-gray-100 dark:bg-gray-850`, shimmer from `var(--color-gray-*)` so it re-tints per theme),
  `prefers-reduced-motion` drops the sweep, `aria-hidden` bars + `aria-busy` containers.
- Wired into **6 real cold-load surfaces** (all confirmed present with `aria-busy`):
  SkillsManager, Cookbook (3 states), Knowledge, Models, Notes, Build page.
  Content-SHAPED — each mirrors that surface's real row/card geometry.
- Spinners deliberately kept where more honest (in-progress actions, infinite-scroll load-more).
- **Splash flash fixed**: the loader sets `theme-<id>` but the CSS targeted `html.harvis-dark`
  (never matched) and airy/warm had no rule → white flash. Added `html.theme-harvis-dark`,
  `theme-oled-dark`, `theme-airy`, `theme-warm`; `html.dark` corrected to `#00030b`.
  (Hex is correct here — it paints before any token CSS exists.)

## ✅ Phase 4 — recon (COMPLETE)

`docs/research/2026-07-18-ai-ux-recon-and-proposals.md` (22k, fully sourced).
Headline: the gaps are **connective tissue**, not missing features. Top proposals ranked by
value-per-effort; **#1 = mascot as run-state instrument** (~1 day, pure FE).

It also caught **real defects** worth fixing regardless: both mascots' rAF loops ignore
`prefers-reduced-motion`; `RunView` auto-waves every ~12s over FINISHED output; the mascot's
`talking` state is declared but never implemented; `runStages.ts` already computes granular
stages that `RunView` throws away.

Honest negatives it recommends NOT building: real-time collab, mobile-native app, hosted
artifact publishing, cloud notifications.

---

## ⚠️ Caveats / not done

1. **The Phase-2/3 verify agent never ran** (same session limit). I verified both myself by code
   inspection + live screenshots, which is thinner than the adversarial Fable review the other
   phases got. Worth a second look.
2. **Settings tabs were not individually eyeballed** — I checked General live and verified the
   safety properties across all tabs by grep. Other tabs are compile-clean and use the shared
   components, but their visual rhythm is unconfirmed.
3. **Skeletons not visually confirmed** — they're transient by nature; verified by code +
   geometry review, not by catching them mid-load.
4. **Splash fix not visually confirmed** per theme (needs a hard reload in each).
5. **Left alone deliberately, your call:** orphaned native notebook page
   (`harvis/notebooks/[id]/+page.svelte`, 652L), `WorkspaceRightRail.svelte` (dead),
   dead `bgDot`/`bgStatusLabel` in vibecode, now-dead `defaultModelId` state in Interface.
   Nothing was deleted anywhere.
6. Stray junk comment found in `Knowledge.svelte:247` ("The Aleph dreams itself into being…") —
   left in place, flagged.
7. New i18n keys fall back to English until added to locale JSONs.

## Suggested next

Per the recon: **mascot as run-state instrument** — it's ~1 day of pure frontend, fixes the
verified accessibility/correctness defects above, and delivers the "mascot in every session"
idea you asked about. Then the command palette.
