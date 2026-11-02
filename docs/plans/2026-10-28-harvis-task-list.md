# Harvis task list (started 2026-10-28)

Claude's running list for David's October push. Read it first after an interruption and resume
the first item that is not done. Update the status line of an item the moment it changes.

Where the work lives: worktree `.claude/worktrees/integration-october`, branch `integration/october`
(from `ae5fd20d`). Everything is uncommitted until David reviews the diff and says to commit.

Standing rules for every item: no commits or pushes without David's yes; never touch the live
backend, DB or cluster in tests (throwaway containers only); never read `.env` values or
`config/presets/`; no Stardew or other game files in the repo; no SSH or remote access to the 4090
or other LAN PCs (hand David one paste instead).

## Order David gave

1. **Merge the four October branches.** Status: done. Merged: shared-host-hardening,
   shared-host-terms, retire-openclaw and personal-layer. The 5 conflicts are resolved, and
   `024_user_mods` was renamed to `025_user_mods`.
2. **Rename (Phase B).** Status: done in repo files.
   - `HARVIS_GATEWAY_TOKEN` is the primary name, with `OPENCLAW_GATEWAY_TOKEN` as the fallback.
   - The prod overlay no longer has `openclaw.yaml`.
   - Nothing was applied live.
3. **Stardew "bring your own art" in the island.** Status: done. The user's own files stay in their browser only.
4. **Install-size tracking.** Status: done.
   - Script: `scripts/install-size.py`.
   - Each run of `verify-fresh-install.sh` appends one line to `~/.local/share/harvis/install-size-history.jsonl`.
   - The default set estimates 8.31 GB against a 7.0 GB budget.
5. **Review fixes from the merge workflow.** Status: done.
   - Clear the island art from IndexedDB on sign-out. Done, with 2 tests.
   - Replace a real home-network IP in the test fixtures with a neutral one. Done.
   - Messaging link tests rewritten for the kept rule (a non-admin can only edit a link they hold,
     new links come from pairing, local install too). 11 of 11 pass.
   - `025_user_mods.sql` header now says 025.
   - The 5 merged files still show as unmerged (`UU`) in the index; `git reset -q` before David's review clears that.
6. **Refine setup.** Status: done. Check 2a now expects 13 services; image trims proposed below, not applied.
   - Run the installer's `--check-only` path and the fresh-install verifier read-only.
   - Fix Check 2a: it expects 12 default services, compose renders 13 (`harvis-messaging-gateway`).
   - Polish the first-run `/setup` wizard where it is rough.
   - List image trims that would bring the default install under 7 GB. Propose them; do not apply.
7. **Landing page for Harvis.** Status: done. `front_end/landing/` with real screenshots (`assets/harvis-app.png`, `assets/island.png`, built-in art only); `node --test front_end/landing/landing.test.mjs` 9/9.
   - A static site in `front_end/landing/` (no build step) covering: what Harvis is, features, install, the island, and links.
   - Uses Harvis's own art and brand only, never Stardew art.
8. **Terms and usage, as a general thing.** Status: done. Readable from sign-in, Settings and the landing page.
   - Write general Terms of Use and an Acceptable Use policy for any Harvis, not only shared hosts.
   - Readable from the sign-in screen and Settings at any time.
   - Mirrored on the landing page.
   - Keep the existing sign-up house rules (`plugins/people/terms.py`, migration 024) as the shared-host checkbox.
9. **Make systems work consistently.** Status: done, apart from the known baseline failures listed below.
   - Backend: full suite in a throwaway pg.
   - Frontend: vitest, `tsc`, a production build, and an island rebundle.
   - Fix what fails. Known baseline failures:
     - `test_hermes_ui_settings::test_every_catalog_platform_is_listed_and_secrets_are_masked`.
     - 3 people tests that need `owui_chats` / `workspace_runs.prompt_tokens`.
10. **Mods work end to end.** Status: done in a throwaway stack. Island switch toggles and survives a reload; `/api/plugins/mods/` answers 200; the island renders. Fixed: the island frame loaded `/island/` instead of `/harvis/island/` (now uses `import.meta.env.BASE_URL`).
    - Run a throwaway backend and pg, and the Vite dev UI pointed at it.
    - In the browser, check: sign up, turn the island mod on and off, the island renders, mod settings persist after a reload.
    - Screenshot as proof.
11. **4090 retest.** Status: waiting on David (commit + push `integration/october` first, then one paste).
    - The branch is not on GitHub yet. It carries migrations 024-027; 027 (session cutoff) signs everyone out once.
    - Before `--expose lan`: sign-up off, admin already claimed, `HARVIS_SETUP_CODE` 16+ characters,
      `POSTGRES_PASSWORD` set, no `HARVIS_BIND_ADDR`, engines off, David's id in `HARVIS_OWUI_ADMIN_USER_IDS`,
      `TTS_INTERNAL_TOKEN` set if RVC voices are used.
    - After install: `scripts/enable-https.sh` (sets `HARVIS_COOKIE_SECURE`; on k8s re-run it after `harvis-start.sh`),
      then `sudo scripts/browser-egress-lock.sh apply` and `sudo scripts/ollama-lan-lock.sh apply`, but only once the
      recreated backend's `/proc/net/route` is off the old 10.213.84.x subnet. Recreate `harvis_repo-sandbox` if its subnet is stale.
    - Clean-up on the box: old root-owned `harvis-ws-term-*` containers, the old :3000 frontend, Ollama on `*:11434`, PAIR.
    - Proof: from another LAN machine only 9000 and 9443 answer; `/robots.txt` answers on both.
12. **Re-add the cookbook to Harvis.** Status: done. Node card shows real hardware, fit-ranked list with Download, builtin node has no Remove. Fixed: an Ollama outage was reported as "llmfit unreachable" (now names the service).
    - The backend still exists: `python_back_end/cookbook`, which uses llmfit.
    - The Hermes UI only has the Settings → Models download list.
    - Bring back the full Cookbook page: nodes and their hardware, the fit-ranked model list, download, and add/remove GPU node (the old OWUI "+" button).
13. **Each user's own bot is its own space.** Status: done (workflow `wf_9c217574-ccd`, 2 Opus reviews, fixes applied).
    - A message to a user's own bot answers only as that user, never as whoever else paired that person.
    - The same Discord person can pair with several users' own bots. The house bot keeps one owner per person.
    - Migration `026_messaging_bot_scope.sql`. Existing links stay on the house bot, except pairings a user
      approved on their own bot (reconciled from their saved pairing list). WhatsApp legacy rows are not
      reconciled (catalog id `whatsapp` vs platform `whatsapp_cloud`), so they stay house.
    - 011 no longer creates the global unique index (it re-runs every boot).
    - Fixed in passing: a WhatsApp webhook went to the first adapter that accepted it, so one user could
      take another's WhatsApp messages. Now routed by phone number id, connected adapters only, and a
      user's own WhatsApp needs `WHATSAPP_APP_SECRET`.
    - Tests: backend 149 passed, 16 skipped (DB), 1 baseline failure; gateway 37 passed. Real pgvector run of 011+026 x3.
    - Deploy: restart `harvis-messaging-gateway` with the backend. 026 is one-way once two users share an identity.
14. **Vault note and report.** Status: done. `Homelab/code/harvis/2026-10-28-october-integration.md` on vault-box, linked from index, log and `_map.md`.
    - Write the session note for this integration in the vault.
    - Link it from the vault index, log and the Harvis repo map.

15. **Island city vibe.** Status: done (workflow `wf_2117cb5b-b3d`, Opus verify). Vault note `Homelab/code/harvis/2026-10-28-island-city-vibe.md`.
    - David's direction: use the Stardew art style lightly, city or town vibe, not beach.
    - Bring-your-own art: Pelican Town downtown (`maps/town.js`) is the default map; `Island_S` stays as an alternative.
    - Built-in art (ours, shipped): the beach island becomes a city block (streets, plaza with a fountain, shopfronts, lamps); beach buildables become city ones.
    - Then rebundle and re-shoot the landing `island.png` with built-in art only. Done (1028x644).
    - Tests: node 75/75 with the user's own files (67 + 8 skipped without), vitest 127/127, landing 9/9.

16. **Island HUD in the Harvis theme.** Status: done 2026-10-28. Clock, date, day bar, rain/night/day and speed buttons, resident list and dialogue redrawn as Harvis panels (`engine/stardew/hud.js`, `stardew-ui.js`) that follow the app's dark/light theme, with the RGB glitch on time and weather changes (off under reduced motion). Our own 5x7 pixel digits replace Neuebit, so there is no font licence question. Compact layout under 640 px. Dusk, night and dawn tint blend instead of jumping. Tests: `engine/test/hud.test.js` 9/9; night frame checked at about half the day brightness.
17. **Pentest hardening + robots.txt.** Status: done 2026-10-30, uncommitted, waiting on David's review.
    - Two review-and-fix rounds (auth, authz, sandbox, edge, client), then inline fixes. Session revocation
      (migration 027 cutoff, checked on every request), decompression-bomb limits on outbound fetches, sandbox and
      terminal isolation, nginx headers and rate limits, `robots.txt` (disallow all) on every front door.
    - Inline 2026-10-30: the deep-research report page now sends a strict CSP (no outside scripts, fetches only to
      this origin); remote images in tool results and image artifacts load only after a click
      (`RemoteImageGate`), so a model-chosen URL cannot leak data on sight.
    - Verified: backend 5092 passed (33 failed + 122 errors, all known: CAD engine absent, no DB, hermes_ui_settings);
      vitest 9605 passed, 33 failed in 11 files outside this diff; tsc clean (both configs); island engine 90/90
      (8 skipped, need user art); island browser checks pass; `nginx -t` passes plain and TLS; both compose files
      validate. New tests fail against the old code: `test_research_report_csp.py`, `fallback-remote-image.test.tsx`.
18. **Security-use terms + legal accuracy.** Status: done 2026-10-30, uncommitted, waiting on David's site review.
    - Acceptable Use gains "Security testing and research", "Other AI providers and online services" and
      "Handle findings responsibly" (authorized pentest/red/blue/purple team work only, cloud providers may flag
      or refuse security requests, no testing other companies' AI without permission, responsible disclosure).
    - Accuracy fixes from a legal audit: chat media is click-to-load (generated-image results and `@image:` links
      now gated too), default theme font, agent-written pages can load remote files, `.env` keys are not
      encrypted. LEGAL_VERSION and house-rules VERSION are 2026-10-30 (house-rule bump only affects new sign-ups).
    - Verified: landing 9/9, test_legal + signup terms 26 passed, notebook authz 23 passed, legal/remote-image
      vitest 11 passed, tsc 0 errors.

## Parked until David decides

- **Island placement.** Status: done 2026-10-29 (direct in-page rendering). The island no longer
  runs in an opaque sandbox iframe: `src/island/mount.js` mounts it scoped inside the React tree
  (no window globals, no postMessage listener, total dispose), so the account's own bots and the
  BYO Stardew art are restored — they go by direct calls, keyed by account id. Explore is a
  fullscreen takeover with art controls ("Use my game art" / "Use built-in art"). Verified:
  vitest 132/132 in src/island + src/mods, engine node tests 84/84 with the real assets,
  tsc clean, and `scripts/island-browser/run.mjs` — 31 headless-Chromium checks (spoofed
  postMessage storms, account-switch races, sign-out teardown, navigation) with screenshots in
  `scripts/island-browser/shots/`. ~~Faded behind the Harvis logo on the new-chat screen, with an "Explore"
  fullscreen takeover and a way back, and a town that grows as agents finish work.~~ The
  town-grows-with-work part is still open.

## Things to tell David (not fixed on purpose)

- `docker-compose.prebuilt.yml` no longer has a default gateway token: it now refuses to start without
  `OPENCLAW_GATEWAY_TOKEN` and `HARVIS_GATEWAY_TOKEN`. It also has no `ws-term-net`, so terminals there run with no network.
- The OpenClaw proxy fetch still reads the whole response into memory, so a br/zstd bomb could hurt it. It is
  behind the gateway token and OpenClaw is retiring, so it was left.
- Electron follow-ups: `openPreviewInBrowser` has no file-type allowlist, there is no `will-attach-webview`
  handler, and `webviewTag` is still on.
- The revocation cutoff compares the app's token time with the DB clock; a large clock skew between them could
  sign someone out early or keep a revoked token alive for the skew.
- Upstream commit adc23f35 (env engine key) was not ported, on purpose. F9 stays deferred.
- The `install.sh` lock-retry test is weak (it checks the message, not the retry).
- `connections.test` fails 18 times on a stale mock from upstream ae5fd20d; not ours, not fixed.
- `MOONSHOT_API_KEY` and `NVIDIA_API_KEY` still come from `harvis-ai-openclaw-secret`, so that
  secret cannot be deleted yet.
- Applying the new prod overlay does not delete the old OpenClaw objects without `--prune`, and
  its PV is `Retain`.
- WhatsApp on a user's own bot now needs `WHATSAPP_APP_SECRET`; existing own-bot WhatsApp setups without it stop until one is added.
- After this lands, restart `harvis-messaging-gateway` along with the backend, or own bots act like the house bot.
- Migration 026 cannot be rolled back once two users share an identity.
- The island on/off setting is stored per browser (localStorage), not per account; another person signing in on the same browser inherits it.
- llmfit reports some large MoE models as needing about 0.5 GB; that number is llmfit's own data, not ours.
- Fresh install is about 8.4-8.8 GB against the 7.0 GB budget. Proposed trims (not applied): repo-sandbox-engine on a slim node base (about 1.48 GB), static ffmpeg in voice-onnx (about 0.36 GB), python 3.12-slim (about 0.19 GB), drop backend ffmpeg (about 0.12 GB). Together about 2.15 GB, which brings it under budget.
