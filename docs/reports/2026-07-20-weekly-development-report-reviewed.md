# Harvis Weekly Development Report

**Reporting period:** 2026-07-14 through 2026-07-20  
*(Dates were blank in the request; inferred from commit timestamps as the calendar week ending at HEAD. Same window as the companion Claude draft.)*  
**Author:** Cursor agent (Auto), with cross-check of Claude’s draft at `docs/reports/2026-07-20-weekly-development-report.md` (uncommitted at review time)  
**Repository path:** `/home/user/Harvis`  
**Repository branch:** `harvis1.1`  
**Ending commit:** `797d84f1` — `fix(honesty): mark unreadable pasted URLs; stop faking durable cookie_secure`  
**Deploy mirror:** `origin/harvis1.1-deploy-test` @ `797d84f1` (46 commits relative to `origin/harvis1.1`, which was **not** advanced)

---

## 1. Executive Summary

This week concentrated on making Harvis **honest and claimable on first run**: an installer that reports observed health rather than assumed success, a one-time setup-code gate so the first network visitor cannot silently become admin (T2), and a `/setup` web wizard that walks the operator through admin claim, model readiness, and verification. That work sits on top of a server-side `require_admin` gate (T1), a Settings/Build “honesty pass,” progressive Build streaming, and a new animated mascot.

The security core of first-signup was **adversarially verified** in a separate Claude-led pass (no-code rejection, concurrent race → one admin, replay rejection, constant-time compare). That same pass found a **HIGH** installer bug: after `/api/setup/status` gained a second JSON key, `install.sh` failed to parse the body and never printed the setup code — defeating the handoff. That bug and two honesty gaps (silent URL-fetch failures; a non-durable cookie toggle documented as durable) were fixed before push to the deploy-test branch.

Current state: the week’s work is **committed and pushed to `origin/harvis1.1-deploy-test`**. Local stack checks (health, setup status, config flags, OWUI static rebuild, `/setup` HTTP 200) succeed on the development host. The **primary unfinished proof** remains a clean-clone `./install.sh` plus a full browser walkthrough of `/setup` on an isolated host — designed and component-verified, not yet proven end-to-end as a stranger would experience it.

---

## 2. Weekly Goals

Goals are inferred from `docs/plans/2026-07-18-plan-of-action.md`, the standing T1–T5 security order, commit history, and session notes. Explicit session goals are marked.

| Goal | Origin | Status |
|------|--------|--------|
| First-run setup (installer + `/setup` wizard) | Explicit / Phase 7 | **Completed** (code + deploy-test push); clean-clone E2E and full wizard click-through still pending |
| Close T2 — no silent first-signup admin | Standing security order | **Completed and verified** (adversarial + live on claimed instance) |
| T1 — server-side `require_admin` | Standing security order | **Completed and verified** (12 unit tests) |
| Settings + Build honesty pass | Roadmap 1a / 1c | **Completed**, limited verification (local build + eyeball) |
| Progressive Build streaming (Cursor-like) | Roadmap / operator preference | **Completed**, limited verification (code + local deploy; not load-tested under heavy runs) |
| Animated mascot | Roadmap Phase 3 | **Completed and verified** (asset audits + HTTP serve) |
| Push to separate remote for deploy testing | Standing D1 rule | **Completed** — `origin/harvis1.1-deploy-test` |
| T3 hide Share · T4 Clone · T5 nav flags | Standing security order | **Not completed** |
| Phase 5 full 3-theme deploy checklist | Roadmap | **Partially completed** (local rebuilds; not a formal console-open matrix writeup) |

---

## 3. Major Changes

### 3.1 First-run setup system (`install.sh` + `/setup`)

**Status:** Complete, limited verification  
**Area:** Configuration · Infrastructure · Authentication · API · UI  

**Problem addressed:** The prior installer (~107 lines) could print success after `docker compose up` without proving services were healthy, without generating all needed secrets, and without a safe way to claim the first admin. Fresh-volume Postgres init could abort when schemas referenced `users` before that table existed.

**What changed:** Machine bootstrap stays in Bash; human onboarding moves to `/setup`. The installer grew to ~460 lines with `--check-only`, port/memory/disk preflight, a **behavioral** compose-merge gate (`docker compose config` assertions for CPU/AMD vs NVIDIA device reservations), generate-if-absent secrets (`JWT_SECRET`, `FERNET_KEY`, `HARVIS_SETUP_CODE`, `OPENCLAW_GATEWAY_TOKEN`), override re-append into `COMPOSE_FILE`, health polling of `/api/health/services`, and printing of the setup URL/code only when `needs_setup` parses correctly. Backend adds `setup_flow.py` (status / verify / test-model / preferences / complete), onboarding on `/api/config`, and compose mount of `setup_flow.py`. Frontend adds `/setup`, setup API helpers, `PUBLIC_ROUTES`, and layout/auth redirects that prefer `/setup` during onboarding.

**Technical implementation:** `install.sh`, `.env.example`, `docker-compose.yaml` (mount), `python_back_end/setup_flow.py`, `main.py` (router include **after** `app = FastAPI`), `owui_compat/config.py` / `router.py`, `front_end/owui/src/routes/setup/+page.svelte`, `lib/apis/setup/`, `lib/constants/publicRoutes.ts`, `routes/+layout.svelte`, `routes/auth/+page.svelte`, DB `instance_settings` + startup ensure / `000_extensions.sql` + `all_schemas_safe.sql`.

**User or system impact:** An operator can install, open `/setup`, and claim the instance with a code only they have. Readiness ticks are probe-backed (`{ready, reason, probe}`), not optimistic booleans.

**Testing and verification:** Live `/api/setup/status`, `/api/health/services`, `install.sh --check-only`, backend recreate after mount/import fixes, OWUI `vite build` + nginx recreate (`/setup` → 200). Adversarial verification of the signup gate (Claude pass). **Not done:** clean-clone E2E; full wizard browser path (model pull → verify → test chat → complete).

**Remaining work:** Clean-clone E2E; wizard click-through; LOW items in §8 (Ollama `/v1` probe normalization, `enable_signup` preference semantics, `setup_complete` after claim-only signup).

---

### 3.2 T2 — First-signup setup code (shared signup path)

**Status:** Complete and verified  
**Area:** Authentication · Security  

**Problem addressed:** First visitor could become admin; `HARVIS_OWUI_ENABLE_SIGNUP` was effectively UI-only.

**What changed:** Gate lives in `_signup_with_connection` (both `/api/auth/signup` and `/api/v1/auths/signup`). Empty users table requires `X-Setup-Code` via `hmac.compare_digest`; advisory lock serializes first claim; admin id stored in `instance_settings`; signup defaults closed after admin exists. Nginx `limit_req` on signup paths.

**Technical implementation:** `main.py`, `owui_compat/router.py` / `translate.py`, `nginx.conf`, OWUI auth `userSignUp(..., setupCode?)`, Create Admin / `/setup` claim UI.

**User or system impact:** Fresh instances are not anonymously claimable; “disable signup” is enforced server-side.

**Testing and verification:** Claude adversarial pass (no-code / race / replay / constant-time). Live claimed-instance: signup routes 403 with signup disabled. **Cursor session did not re-run the throwaway-DB adversarial suite.**

**Remaining work:** Direct `:8000` bypasses nginx rate limit (accepted for local debug — §7).

---

### 3.3 T1 — Server-side `require_admin`

**Status:** Complete and verified  
**Area:** Authorization · Security · API  

**Problem addressed:** Admin/config mutations trusted client route guards.

**What changed:** `make_require_admin` / `is_admin` in `owui_compat/authz.py`, applied to admin-shaped mutations including previously open RAG routes; fails closed with 403.

**Technical implementation:** `owui_compat/authz.py`, `main.py`, `rag_corpus/routes.py`, `tests/test_require_admin.py` (12 tests).

**User or system impact:** Configuration mutations require server-recognized admin identity.

**Testing and verification:** Unit suite present (12 tests). Claude report cites live anon 401 / non-admin 403; not re-executed in this Cursor review session.

**Remaining work:** None identified for the gate itself.

---

### 3.4 Settings + Build honesty pass + progressive streaming

**Status:** Complete, limited verification  
**Area:** UI · Agent workspace · Configuration  

**Problem addressed:** Settings and Build advertised unwired capabilities; ThoughtStream ignored live `token` events and batched UI updates, so Build felt “dump at end” rather than progressive.

**What changed:** Connections/Personalization unhooked from Settings modal; About rebranded without shields.io; JWT copy row removed; `enable_api_keys` / `enable_memories` default false. Build: hide Preview tab, mic placeholder, SSH-soon; remove unwired Connect-GitHub/CLI CTAs; BrowserPanel quick-links use current origin. Streaming: ThoughtStream accumulates `token` events; 20s Connecting→Retry; `runStream.ts` **immediate flush** for token/tool/`agent_message` (frontend shared SSE store). Related honesty work also landed in `chat_completion.py` (pasted-URL failure markers).

**Technical implementation:** `SettingsModal.svelte`, `Settings/About.svelte`, `Settings/Account.svelte`, `owui_compat/config.py`, `WorkspaceMainPanel.svelte`, `BrowserPanel.svelte`, `vibecode/+page.svelte`, `ThoughtStream.svelte`, `runStream.ts`, `RunView.svelte`, plus broader OWUI design-system commit (`8d5356b8`) and notebook theme sync (`47444bff`).

**Correction vs Claude draft:** Progressive Build streaming’s primary mechanism in this pass is **frontend** `runStream.ts` / `ThoughtStream.svelte`, not solely backend `chat_completion.py`. Backend chat_completion changes are real but address related honesty/streaming concerns (including unreadable URLs).

**User or system impact:** UI shows fewer false affordances; Build text and tool steps paint as they arrive.

**Testing and verification:** Local `vite build` succeeded; nginx recreated; `/api/config` showed `enable_api_keys: false`, `enable_memories: false`, `enable_direct_connections: false`. Operator/session eyeball of themes. No automated UI tests.

**Remaining work:** Micro-type lift; raw hex in ~8 non-cockpit files; formal Phase 5 matrix.

---

### 3.5 Animated mascot

**Status:** Complete and verified  
**Area:** UI · Developer experience  

**Problem addressed:** No product mascot; prior SVG mascot had run-state / reduced-motion issues.

**What changed:** Green-screen → transparent WebM pipeline; startup one-shot + idle loop player; reduced-motion and hidden-tab pause.

**Technical implementation:** `assets/mascot/`, `HarvisAnimatedMascot.svelte`; commits `8defacab`, `3c7917da`.

**User or system impact:** Brand presence and a path to future run-state instrumentation.

**Testing and verification:** Per Claude draft: frame audits, 97.2% handoff IoU, `/mascot/` HTTP 200. Not re-measured in this Cursor review.

**Remaining work:** Optional additional poses; confirm at real ~96px UI size before more generation.

---

### 3.6 Build Space v1 omnibus (`3fd5d0a5`, 2026-07-15)

**Status:** Complete, limited verification *(metadata / diffstat only in this review)*  
**Area:** Agent workspace · Integrations · Repo automation  

**What changed:** Large landing of agent review, PR drawer, Discord workspace bot expansion, workspace router, vibecode UI, compose profile touch-ups (~27k insertions across the week’s first→HEAD window when measured from this commit’s parent).

**Testing and verification:** Not re-verified hands-on in this report session. Treat subsystems as **in-tree and load-bearing** but not independently certified here.

**Remaining work:** Targeted verification if those surfaces become the next deploy focus.

---

## 4. Bug Fixes and Smaller Improvements

- **Health `pg_pool`:** `/api/health/services` read the wrong attribute and could not report DB healthy; now uses `pg_pool` + real `SELECT 1`, TTS probe, `/api/auth/stats` gated.
- **Fresh-volume DB bootstrap:** Empirical abort on missing `users` (throwaway container) → `000_extensions.sql` + `all_schemas_safe.sql` ordering and startup ensure. *(Claude draft understated this as “argued statically”; handoff documents an empirical abort.)*
- **Installer status parse (HIGH):** Two-key JSON broke setup-code printing; fixed field extraction.
- **Forgotten `setup_flow.py` tracking:** Import/mount without git add would break clean checkouts; corrected.
- **Compose override + `FERNET_KEY`:** Override no longer silently dropped when `COMPOSE_FILE` is set; Fernet key generated if absent.
- **Pasted URL honesty:** Failures surface as `### Could not read <url>` blocks instead of silent omission.
- **Cookie secure preference:** Process-level only; response includes `cookie_secure_durable: false` and points at `.env`.
- **Docs/roadmap/Obsidian:** Handoffs, plan-of-action status, notes-vault checklist updates.

---

## 5. Testing and Verification

| Test or verification | Area tested | Result | Evidence or notes |
| -------------------- | ----------- | ------ | ----------------- |
| `test_require_admin.py` | Authz T1 | **Present / assumed pass** | 12 tests in tree; not re-run this Cursor session |
| Live `/api/health/services` | Health | **Pass** | Healthy services including database (session + Claude) |
| Live signup 403 (claimed instance) | Auth | **Pass** | Both signup routes with signup disabled |
| Setup-code adversarial suite | Auth T2 | **Pass (Claude)** | No-code / race / replay / compare_digest — not re-run here |
| `install.sh --check-only` | Installer | **Pass (Claude)** | Cited in Claude draft |
| Status-body parse fix | Installer | **Pass** | Commit `2527a0cd` + code review of grep extraction |
| Backend recreate + `/api/setup/status` | Setup API | **Pass** | Returns `needs_setup` + `setup_complete` |
| OWUI `vite build` + nginx | Frontend deploy | **Pass (Cursor session)** | `/` and `/setup` HTTP 200 after rebuild |
| `/api/config` honesty flags | Config | **Pass** | `api_keys`/`memories`/`direct_connections` false |
| Login + chat regression | Auth / Chat | **Pass (Claude adversarial)** | Not re-run here |
| Mascot asset serve | UI | **Pass (Claude)** | Not re-measured here |
| Push deploy-test | Deployment | **Pass** | `origin/harvis1.1-deploy-test` @ `797d84f1` |
| Clean-clone `./install.sh` E2E | Installer | **Not run** | Port collision / needs clean host |
| Full `/setup` browser E2E | Onboarding UI | **Not run** | Endpoints verified; click-through not |
| macOS / AMD install paths | Installer | **Not evaluated** | No hardware |

---

## 6. Architecture and Technical Decisions

**Bash for machine, web for human.** Keeps Docker/secrets/preflight out of the SPA and keeps claim/model/verify interactive. Tradeoff: status JSON is a contract (the HIGH parse bug was a contract break).

**Gate in `_signup_with_connection`, not per-route.** Prevents OWUI facade bypass.

**Behavioral compose gate.** Assert rendered config (no NVIDIA devices on CPU/AMD profiles) instead of fragile Compose version strings.

**Honest probe contract.** `{ready, reason, probe}` and real model generation for “model works.”

**Immediate flush for interactive stream events.** Shared `subscribeRun` store keeps one SSE connection; flushes tokens/tools immediately while still batching noisier events.

**Push to `harvis1.1-deploy-test`, not `origin/harvis1.1`.** Preserves standing “no main-line push until verified” rule while enabling remote deploy testing.

---

## 7. Security and Reliability Review

| Concern | Classification | Notes |
|---------|----------------|-------|
| First-signup admin takeover (T2) | **Resolved** | Setup code + advisory lock; adversarially verified (Claude) |
| Server admin mutations (T1) | **Resolved** | `require_admin` + tests |
| Signup disable server-enforced | **Resolved** | Shared path + default off after admin |
| Host `:8000` bypasses nginx limits | **Open (accepted locally)** | Defense-in-depth gap; setup code entropy still primary control |
| Unauth setup/health/config recon | **Open (LOW)** | Reveals setup state / service map, not credentials |
| `/api/research/health` fabrication | **Open (pre-existing)** | Must not back readiness ticks |
| Pasted-URL SSRF | **Mitigated** | Validation + visible failure markers |
| Cookie secure durability | **Mitigated** | Honest non-durable labeling |
| Fresh-volume DB correctness | **Mitigated / needs clean-clone proof** | Empirical abort + fix shipped; full stranger path still pending |
| Secrets in git | **Resolved** | Generated locally; `.env.example` placeholders only |

No blanket claim that Harvis is “secure.” The first-signup path was specifically attacked and held.

---

## 8. Known Issues, Risks, and Blockers

| Issue | Severity | Current impact | Status | Recommended action |
| ----- | -------- | -------------- | ------ | ------------------ |
| Clean-clone installer E2E not run | High | Stranger-path unproven | Open | Deploy `harvis1.1-deploy-test` on clean host; run `./install.sh` → `/setup` → chat |
| `/setup` wizard not fully click-tested | Medium | UI flow risk | Open | Browser E2E including stop-a-service red ticks |
| `:8000` published | Medium | Nginx controls bypassable | Open / accepted | Drop host publish for exposed deploys or document acceptance |
| T3–T5 unfinished | Medium | Share still reachable; nav may over-promise | Open | Next security-order items after E2E |
| Research health fabrication | Medium | Honesty debt | Open | Probe or remove from status surfaces |
| Ollama probe `/v1` suffix | Low | Possible verify false-red | Open | Normalize like health_services |
| Wizard `enable_signup` preference | Low | Toggle may not change live policy | Open | Wire or remove |
| `setup_complete` after claim-only | Low | Wizard may show incomplete | Open | Set on claim or document semantics |
| Omnibus `3fd5d0a5` not re-certified | Low | Large surface assumed OK | Open | Spot-verify if next deploy focus |

---

## 9. Files and Systems Most Affected

| Area | Important files or directories | Purpose of changes |
| ---- | ------------------------------ | ------------------ |
| Installer | `install.sh`, `.env.example`, compose profiles | Preflight, secrets, honest handoff |
| Setup backend | `setup_flow.py`, `main.py`, `owui_compat/*`, migrations/init | Status/verify/gate/bootstrap |
| Setup UI | `routes/setup/`, `apis/setup/`, `publicRoutes.ts`, layout/auth | Wizard + redirects |
| Settings/Build UI | Settings components, vibecode, ThoughtStream, BrowserPanel, `runStream.ts` | Honesty + progressive stream |
| Authz | `authz.py`, RAG routes, `test_require_admin.py` | T1 |
| Mascot | `assets/mascot/`, animated player | Brand / pipeline |
| Build Space v1 | workspace orchestration, Discord bot, vibecode, routers | Omnibus 07-15 |
| Docs | handoffs, plans, `changes.md`, Obsidian notes | Status truth |

Approximate week churn from first in-window commit’s parent to HEAD: **246 files, +27,294 / −6,355** (includes the 07-15 omnibus).

---

## 10. Commit Summary

22 commits in-window. Grouped by work item:

| Commit | Date | Description | Related work item |
| ------ | ---- | ----------- | ----------------- |
| `3fd5d0a5` | 07-15 | Build Space v1 omnibus | §3.6 |
| `3c8616b2` | 07-19 | `require_admin` gate | §3.3 |
| `8defacab` | 07-19 | Mascot pipeline + player | §3.5 |
| `3c7917da` | 07-20 | Mascot clips wired | §3.5 |
| `6323cb06` | 07-20 | Installer handoff docs; mascot marked done | Docs |
| `016b33c1` … `b0fcdc1f` | 07-20 | Installer secrets, health, DB, T2, status, preflight, handoff | §3.1–3.2 |
| `9a278715` | 07-20 | Track `setup_flow.py` + mount | §4 |
| `c066b430` … `89737633` | 07-20 | Stream/config honesty, design system, `/setup` UI, Settings/Build | §3.1, §3.4 |
| `47444bff` | 07-20 | Notebook theme sync | §3.4 |
| `499e4c15` | 07-20 | `.env.example` + install polish | §3.1 |
| `d6c8469b` | 07-20 | Docs writeups | Docs |
| `2527a0cd` | 07-20 | Status parse HIGH fix | §4 |
| `797d84f1` | 07-20 | URL failure markers; honest cookie_secure | §4 |

---

## 11. Incomplete and Uncommitted Work

At review time:

- **Uncommitted:** only Claude’s draft report file `docs/reports/2026-07-20-weekly-development-report.md` (this consolidated report may replace or sit beside it).
- Working tree otherwise clean relative to HEAD `797d84f1`.
- **Committed but not fully verified:** clean-clone installer; full `/setup` click-through; omnibus `3fd5d0a5` subsystems.
- **Safe to preserve:** all committed work on `harvis1.1` / deploy-test. Commit the chosen weekly report file when ready; do not commit secrets or `front_end/owui/build/`.

---

## 12. Next-Week Priorities

1. **Clean-clone E2E on deploy-test** — Prove stranger path. Done when: fresh host, `./install.sh`, `/setup`, one chat, no manual patches.  
2. **Browser `/setup` walkthrough** — Including forced red ticks. Done when: every step exercised live.  
3. **Decide `:8000` exposure** — Remove for public deploys or document acceptance.  
4. **T3 hide Share** — Flag-gated, not deleted. Done when: unreachable in UI.  
5. **T4 Clone chat** — Narrow endpoint using existing create/retrieve.  
6. **T5 workspace/admin nav flags** — Reversible hide of unfinished surfaces.  
7. **LOW honesty cleanup** — Research health, Ollama probe normalize, signup preference, `setup_complete` semantics.

---

## 13. Overall Assessment

**Overall status:** Strong, security-forward week centered on first-run honesty and claim safety, with meaningful UI honesty and streaming upgrades, pushed to a dedicated deploy-test branch.

**Confidence level:** **Moderate confidence.**  
High confidence in: T2 gate design in code, presence of T1 tests, local health/setup/config/UI build checks performed in this Cursor session, and the committed deploy-test tip. Moderate rather than high because: adversarial suite and some live curls are taken from Claude’s draft without full re-execution here; clean-clone and full wizard E2E remain undone; the 07-15 omnibus is metadata-only in this review.

**Most important accomplishment:** Closing silent first-admin takeover (T2) behind a verified setup-code gate, with an installer that can print that code only after observed health.

**Most important unresolved concern:** Clean-clone + `/setup` E2E still unproven as a whole.

**Ready for next milestone?** Ready for **deploy-test host exercise**. Not ready to treat `origin/harvis1.1` as updated or to declare “anyone can install Harvis” until the clean-clone path passes.

---

## 14. Evidence Gaps

- Request left **dates, author name, and repo path** blank — dates inferred; author set to Cursor with Claude cross-check.  
- **Adversarial suite** not re-run in this session — cited from Claude draft / prior agents.  
- **`test_require_admin.py`** not executed in this session — suite present in tree.  
- **Clean-clone / deploy-host logs** unavailable.  
- **`3fd5d0a5` internals** not independently verified.  
- **macOS / AMD** install paths not evaluated.  
- Claude draft claimed working tree clean; at review time the draft report itself was the sole untracked file.  
- Progressive-streaming attribution in Claude draft slightly over-weighted `chat_completion.py`; corrected in §3.4.

---

*Companion draft retained for comparison: Claude’s uncommitted `docs/reports/2026-07-20-weekly-development-report.md`. Prefer this consolidated file as the reviewed weekly report unless you want both kept.*
