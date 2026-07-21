# Recon #2 honesty fixes — SHIPPED, DEPLOYED, runtime-verified

**Date:** 2026-07-18
**Branch:** `harvis1.1` (main tree `/home/user/Harvis`)
**Status:** built · deployed to `localhost:9000` · runtime-verified · **NOT pushed**
**Diff:** 10 files, +365 / −95

---

## What this was

[Recon #2](../research/2026-07-18-recon2-gap-hunt.md) hunted bug *classes* systematically, on the
theory that the day's serious bugs had all been found by accident. It found one data-loss bug, one
regression introduced that same morning, and a spread of "error presented as confident success or
confident empty state" across eight surfaces.

This document records the fixes for the S-effort subset, and — more importantly — **how they were
verified**, because the verification technique is reusable and the previous batches did not have it.

Two Fable-5 workflows ran back to back:

| Workflow | Scope | Verifier verdict |
|---|---|---|
| `wgh2gzhrp` | 6 critical Recon #2 findings | 7/7 PASS |
| `w889ohrk6` | the 4 residual flags that verifier raised | 4/4 PASS |

## The governing principle

> The UI must never present a failure as a confident success or a confident empty state.
> A failed GET must not render as "you have nothing." A failed mutation must not render as "done."

Every fix below is an instance of that one rule.

---

## Fixes

### 1. `workspace/Models.svelte` — skeleton that shimmered forever *(regression, self-inflicted)*

The skeleton added earlier that same day sat behind `loaded`, which was set *after* an uncaught
`await getGroups(...)`. `getGroups` throws on a non-ok response, so any failure meant `loaded`
never became true and the skeleton animated indefinitely — **impersonating incoming content**.
That is strictly worse than the spinner it replaced, because a spinner promises nothing while a
skeleton promises a specific shape of content that is never coming.

Fixed with a `loadGroups()` helper whose `.catch` sets `loadError` and returns null,
`(groups ?? []).map(...)` for the null body, and `loaded = true` reached unconditionally.
Template order is now `{#if loadError}` → `{:else if loaded}` → cold skeleton. A second
`listError` branch covers the inner model-list fetch.

### 2. `Settings/Account/UpdatePassword.svelte` — dead form, honestly gated

The password form posted to `POST /api/v1/auths/update/password`, which does not exist.

**Premise independently re-verified** (not taken from the agent's report): `owui_compat`
registers only `signin` (router.py:100), `signup` (:119), `GET /auths/` (:137), `signout` (:158),
plus an `update/timezone` stub (stubs.py:39). A repo-wide grep found no `update/password` or
`update/profile` anywhere in `python_back_end/`.

Gated behind `PASSWORD_CHANGE_AVAILABLE = false` using the same single-flip pattern as
`Account.svelte`: handler early-returns with an honest toast, submit button disabled, inline note.
The form and handler are intact — flipping the const re-enables it when the route lands.

### 3. `agent-studio/Customize.svelte` — the DATA LOSS bug

The worst finding in Recon #2. A failed orchestration-pool GET was laundered into an empty pool
with `poolLoaded = true`. The next toggle then PUT `{active:false, models:[]}` over the user's
**real server-side pool** — silently destroying configuration the client had never successfully read.

`poolLoaded` is now set only inside the verified-200 branch, which makes every mutator's
`if (!poolLoaded) return` guard actually load-bearing. A failed load renders a dedicated error card
with Retry instead of the editing UI, and the toggle is `disabled` while unloaded. `savePool`
checks the PUT response and, on failure, **restores the last server-confirmed snapshot** rather
than leaving the optimistic change on screen.

Snapshot-and-restore was chosen over re-fetch deliberately: a failed PUT usually means the backend
is down, so a recovery GET would likely fail too and would drop the user into the load-error branch
while we still hold known-good state.

### 4. GitHub disconnect — fabricated success *(security-flavored)*

`disconnectGithub` swallowed all errors, so callers could not know whether the credential was
actually revoked. It now returns `Promise<boolean>` (`res.ok`, `false` on throw).

Both call sites now honor it — `integrations/ConnectionPanel.svelte` and
`agent-studio/GitHubRepoModal.svelte`. The second was missed in the first pass and caught by the
verifier. This one matters more than the others: telling a user their GitHub access is revoked
when it may still be live is a false security assurance.

### 5. Skill / plugin mutations and loads

`SkillsPanel` and `PluginsPanel` removed rows and refreshed lists *before* confirming the server
call. Both now mutate local state only after the await resolves, and toast on failure.

Their `loadSkills` also swallowed a failed GET into `[]` — so a successful toggle followed by a
failed refresh blanked the panel, reading as "your skills were deleted." Both now distinguish
loaded-with-items / genuinely-empty / load-failed, with Retry on the last.

### 6. Knowledge-base indexing poll — never terminated

The bail-out and `clearInterval` sat *inside* `if (s)`, so a failing status endpoint polled every
3s forever while the card claimed "Ingesting…". The terminal check now runs every tick regardless
of whether the read succeeded, and a fast-bail after 3 consecutive null reads (~9s) flips the card
to an honest `unknown` + Retry. A single transient blip cannot abort a healthy ingest — the counter
resets on any success.

### 7. `common/Dropdown.svelte` — Escape closed the whole modal

App-wide: pressing Escape to dismiss a dropdown inside any modal closed the entire modal. Fixed
with a capture-phase handler that calls `stopPropagation()` **only while the dropdown is open**, so
the closed case remains a strict no-op and every other Escape consumer is untouched. The verifier
enumerated all twelve other Escape listeners to confirm none regressed.

### 8. `SkillsPanel` initial-load gap *(introduced by fix 5, caught by the verifier, fixed by hand)*

With the three-branch rewrite, the in-flight initial GET matched no branch and rendered nothing.
Added a `Loading skills…` branch. The genuinely-empty copy still shows only after a confirmed load.

---

## Verification — the part worth reusing

Compiler checks cannot validate a fix for "the UI lies when the backend fails," because the failure
never occurs during a normal load. So the failure was **manufactured** against the deployed app.

`window.fetch` was patched in the live page to return 503 for the pool and skills GETs, then
Customize was opened:

```
poolPUTsAfterFailedGET: []      ← the data-loss bug, dead
poolErrorShown:         true
skillsErrorShown:       true
falseEmptyClaim:        false
retryButtons:           2
toggleDisabled:         1
```

The empty array is the result that matters: under a real 503 the component fires **no PUT at all**.

Then only the *first* GET was failed and Retry clicked — errors cleared, real controls returned,
toggle re-enabled, nothing stuck loading. Full failure → honesty → recovery loop.

The Escape fix was checked in the direction that could cause harm: with no dropdown open, Escape
still closes the Settings modal. An over-suppressing capture handler would have made every modal in
the app un-closable by Escape.

**Recommendation: use fetch interception for all future honesty work.** A healthy-backend page load
proves nothing about error-path behavior.

### Not verified at runtime (stated plainly)

- **`Models.svelte`** — the route redirects before the component mounts (see below).
- **Dropdown-open Escape** — no dropdown trigger was locatable inside the Settings modal. The
  verifier confirmed it structurally, and the closed-case test corroborates the reasoning, but it
  was not observed.

### Process mistake, recorded so it isn't repeated

To test whether the pool guard held under interaction, *every* button on the page was clicked. A
"Create PR" control was on that page. A database check confirmed no harm — 0 sessions and 0 PRs
created in the preceding 30 minutes — but it only came out clean because the skills list was in its
error state, so the per-skill Delete buttons were not rendered.

**Test a guard by clicking the specific control. Never hammer the DOM on a page with outward-facing
actions.**

---

## Live finding: `/workspace/*` is unreachable for the real user

`/workspace/models` redirected to `/`. The logged-in user `cisco` is `role=user` with:

```json
"permissions": { "workspace": { "knowledge": false, "models": false, "prompts": false, "tools": false } }
```

The guard is `routes/(app)/workspace/+layout.svelte:23-39`.

So the `Models.svelte` skeleton hang — introduced and fixed the same day — sits on a surface this
user cannot reach at all. The fix remains correct (an admin hits it), but this is Recon #2's Tier-2
finding (~150 unbacked functions across `/admin` and `/workspace`) confirmed in the flesh.

**Product decision required:** grant the permissions, implement the surfaces, or stop advertising
them in the nav. Currently the nav promises pages that redirect.

---

## Known residual (flagged, none blocking)

1. **`getGithubStatus` swallows errors into `{connected:false}`** — so a failed disconnect *plus* a
   failed status re-sync still renders "disconnected." This shared helper is the deeper root and
   undermines two of the fixes above; it deserves its own pass.
2. **Out-of-order PUT race in `savePool`** — two rapid mutations, responses arriving out of order,
   can leave display ≠ snapshot until the next mutation or reload.
3. **No busy guard on the modal's Disconnect** — double-click double-fires.
4. **`listUserGithubRepos` returns `[]` on failure** — same error-as-empty-state class, in
   `GitHubRepoModal`.

## Deploy

```bash
npm --prefix front_end/owui run build      # exit 0, 1m13s
docker restart nginx-proxy
curl -s -o /dev/null -w "%{http_code}" http://localhost:9000/    # 200
```

All fix strings were confirmed present in the minified bundle, which also proves the edits landed
in the main tree rather than the stale worktree.

**Nothing pushed.** `harvis1.1` remains ~25 commits ahead pending explicit E2E sign-off.
