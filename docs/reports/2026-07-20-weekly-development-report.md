# Harvis Weekly Development Report

**Reporting period:** 2026-07-14 through 2026-07-20 *(inferred from commit history — the request left the dates blank; the window is the standard week ending at the latest commit)*
**Author:** brandoz2255 *(git committer of record; a report author was not specified in the request)*
**Repository branch:** `harvis1.1`
**Ending commit:** `797d84f1` — *fix(honesty): mark unreadable pasted URLs; stop faking durable cookie_secure*
**Also pushed:** `origin/harvis1.1-deploy-test` (46 commits; `origin/harvis1.1` deliberately not advanced)

---

## 1. Executive Summary

The week's dominant work was building and verifying **Harvis's first-run setup system** — the path that takes a stranger from a fresh clone to a working, claimed instance. This replaced an installer that stopped at "containers started" (which is not the same as "Harvis works") with a two-part design: `install.sh` handles the machine (hardware profile, secrets, compose validation, health-gated startup, one-time setup code) and a new `/setup` web wizard handles the user (admin account, model provider, verification, first chat). The security core of this — a first-signup gate keyed to a one-time setup code — **closes the previously-open T2 admin-takeover item**: on a fresh install the first public signup could silently become an administrator, and now cannot without the code printed to the operator's terminal.

Alongside the setup work, the week delivered a **Settings and Build "honesty pass"** (removing UI that advertised capabilities that were not wired, and making the Build cockpit stream tokens live instead of buffering to end-of-turn), a **server-side `require_admin` authorization gate** with unit tests, and a **new animated mascot** (a reusable green-screen→WebM pipeline plus a state-driven player). A large **Build Space v1 omnibus** also landed at the start of the window (2026-07-15).

The most important quality event of the week was an **adversarial verification pass** run by an independent agent against the finished setup gate. It confirmed the security core holds (admin is unclaimable without the code; a five-way concurrent race yields exactly one admin; the code comparison is constant-time; replay is rejected) **and** it caught a HIGH-severity bug the build had introduced — the installer parsed a status endpoint whose response shape had changed, so it *always* printed "unreachable" and never printed the setup code, silently killing the handoff it exists to perform. That bug plus two honesty gaps were fixed and re-verified before the branch was pushed.

The current state: all of the above is committed, largely verified live against the running stack, and pushed to a dedicated **deploy-test branch** rather than the main working branch. The main unresolved priority is a **clean-clone end-to-end test** — a real `./install.sh` from a fresh checkout in an isolated environment — which is the one verification the local running stack could not provide (its ports collide) and which is what conclusively proves the installer produces a working instance for a new user.

---

## 2. Weekly Goals

The goals below are inferred from the commit history, the roadmap document (`docs/plans/2026-07-18-plan-of-action.md`), and the standing task list. Where a goal came from an explicit user instruction this session, it is marked as such.

| Goal | Origin | Status |
|---|---|---|
| Build a real first-run setup flow (installer bootstrap + web onboarding) | Explicit user spec this week | **Completed**, pushed to deploy-test; clean-clone E2E still pending |
| Close T2 — fresh install must not silently make the first signup an admin | Standing security order (T1–T5) | **Completed and verified** (subsumed by the setup-code gate) |
| Add a server-side `require_admin` gate (T1) | Standing security order | **Completed and verified** (12 unit tests) |
| Settings + Build "honesty pass" — stop showing unwired capabilities | Roadmap phases 1a/1c | **Completed**, deployed and eyeballed locally |
| Progressive token streaming in the Build cockpit | Roadmap phase 1c | **Completed**, deployed locally |
| New animated mascot (design + pipeline + player) | Roadmap phase 3 | **Completed and verified**; deploys on merge |
| Push verified work to a separate remote branch for deploy testing | Standing rule (D1) | **Completed** — `origin/harvis1.1-deploy-test` |
| T3 (hide Share), T4 (Clone chat), T5 (nav flags) | Standing security order | **Not started** — deferred behind the push gate |

---

## 3. Major Changes

### 3.1 First-Run Setup System (installer bootstrap + `/setup` web wizard)

**Status:** Complete, limited verification (backend and installer verified live; the full wizard click-through and a clean-clone E2E are not yet done)
**Area:** Configuration · Infrastructure · Authentication · API and backend · User interface

**Problem addressed:** The prior `install.sh` (107 lines) detected hardware, wrote a compose profile and a JWT secret, and optionally ran `docker compose up`. It stopped there. A successful `up` does not mean the model provider works, that Ollama has a model, that a normal chat succeeds, or that the operator knows how to claim the instance. Separately, the fresh-install path had no admin-claim protection at all.

**What changed:** The setup experience was split into two parts along a machine/user boundary. `install.sh` now owns only what must happen before Harvis can start; a new web page at `/setup` owns everything that needs a running backend and a human decision.

**Technical implementation:**

- **Installer (`install.sh`, now ~460 lines changed):** refactored into functions with a `--check-only` preflight that changes nothing and exits non-zero on failure. It adds a **behavioral compose-merge gate** — rather than parsing the Docker Compose *version* (which is unreliable; the installed version is 5.x), it renders `docker compose config --format json` for the selected profile and asserts on the result: the CPU and AMD profiles must contain **zero** NVIDIA device reservations, the NVIDIA profile must retain them. This directly detects the case where an old Compose silently ignores the `!reset` tag the override files rely on (empirically, releases below 2.19). It also adds host-port preflight, generates a one-time `HARVIS_SETUP_CODE` and the shared `OPENCLAW_GATEWAY_TOKEN` (generate-if-absent, never regenerated on re-run), and replaces the old unconditional "✓ Harvis is starting" line with a **timed poll of `/api/health/services` and a real per-service status table** — printing the setup URL and code only on observed success.
- **Setup-state signal:** `/api/config` now emits an `onboarding` key (true only while no admin exists), and a new unauthenticated `GET /api/setup/status` returns `{needs_setup, setup_complete}`. The frontend already contained dead branches keyed on `onboarding`; emitting the key activated them.
- **Setup verification router (`python_back_end/setup_flow.py`, new, ~300 lines):** `GET /api/setup/verify` returns per-service readiness objects of the form `{ready, reason, probe}` where each is backed by a real probe (a `SELECT 1` on the pool, a TTS `/health` call, an artifact-directory write/read/unlink, etc.), and `POST /api/setup/test-model` performs a real Ollama generation — the only honest "the model actually answers" check, since a listed model can still fail to load.
- **Frontend wizard (`front_end/owui/src/routes/setup/+page.svelte`, new, 517 lines):** a step-based onboarding shell with a tri-state API client (modeled on the throws-to-caller config probe rather than the return-null pattern that renders failures as confident empty states), plus a shared `publicRoutes` constant so the layout guards exempt `/setup` at all three client-side redirect sites.
- **Secrets and template:** `install.sh` also generates `FERNET_KEY` (previously empty, which silently disabled GitHub OAuth) and re-appends `docker-compose.override.yml` to `COMPOSE_FILE` (Compose stops auto-loading it once `COMPOSE_FILE` is set). A root `.env.example` was added — blank placeholders only — documenting the vars that matter for a first install.

**User or system impact:** A new operator can run `./install.sh`, follow a printed URL to `/setup`, and claim the instance with a code only they possess. Administrators get honest readiness signals instead of optimistic ones. The installer now reports what actually happened rather than asserting success.

**Testing and verification:** The health endpoint, both signup routes, the setup-status endpoint, and `install.sh --check-only` were verified live against the running stack (see §5). The setup-code gate was independently adversarially verified. **Not yet done:** a full browser click-through of the wizard, and a clean-clone `./install.sh` in an isolated environment.

**Remaining work:** clean-clone E2E; exercise the wizard UI end-to-end; six LOW findings (see §8); the `/setup` model/provider/exposure steps are wired to existing backend endpoints but were not exercised live this session.

---

### 3.2 T2 — First-Signup Setup Code and Server-Side Signup Enforcement

**Status:** Complete and verified
**Area:** Authentication · Security

**Problem addressed:** Public signup was fully open by default, and on a fresh install nothing prevented the first person who reached the instance from creating an account — which, on an internet-exposed deployment, is an admin-takeover risk. Separately, the `HARVIS_OWUI_ENABLE_SIGNUP` flag existed but was read **only** by the frontend config builder; disabling signup hid the form while `POST /api/auth/signup` kept working.

**What changed:** A gate was placed **inside `_signup_with_connection`** — the single code path that both `/api/auth/signup` and the OWUI facade `/api/v1/auths/signup` funnel through, so route-level gating (which would have missed the facade) was avoided. When the users table is empty, signup now requires a one-time `X-Setup-Code` header compared in constant time (`hmac.compare_digest`); the count and insert run in one transaction under a Postgres advisory lock so two concurrent first-signups cannot race for the admin row. The created admin's id is persisted to a new `instance_settings` table and unioned into the admin-resolution set. `HARVIS_OWUI_ENABLE_SIGNUP` is now enforced server-side and, per an explicit product decision this week, defaults to disabled once an admin exists.

**Technical implementation:** `python_back_end/main.py` (`_signup_with_connection`, `instance_settings` creation in the startup ensure block), `owui_compat/translate.py` (admin-id union), `nginx.conf` (a `limit_req` zone on the auth routes), and a refuse-when-empty guard added to `create_test_user.py`.

**User or system impact:** A fresh instance cannot be claimed by an anonymous network visitor; the operator holds the only key. "Disable signup" now actually disables signup, on both routes.

**Testing and verification:** Independently adversarially verified (see §5 and §7): admin was unclaimable without the code via every enumerated insert path; five concurrent first-signups with the correct code produced exactly one admin; replay after claim was rejected; the comparison is constant-time. Live, on the running (already-claimed) instance, both signup routes returned 403 with signup disabled and zero probe accounts reached the database.

**Remaining work:** The nginx rate limit does not protect the directly-exposed backend port (see §7 and §8); the `enable_signup` toggle in the wizard is currently a no-op (LOW, fails closed).

---

### 3.3 Server-Side `require_admin` Authorization Gate (T1)

**Status:** Complete and verified
**Area:** Authorization · Security · API and backend

**Problem addressed:** Admin/config mutation endpoints relied on client-side route guards, which do not protect the API itself.

**What changed:** A real `require_admin` FastAPI dependency was added (`python_back_end/owui_compat/authz.py`) via a factory pattern (the compat routers receive `get_current_user` as a parameter), and applied to admin/config mutation endpoints — including a previously-unauthenticated `/api/rag` router and the audio-config update endpoint. It fails closed and returns 403 rather than leaking whether a resource exists.

**Technical implementation:** `owui_compat/authz.py` (`make_require_admin`, `is_admin`, `user_id_of` handling both dict and object user shapes), wired in `main.py` and `rag_corpus/routes.py`.

**User or system impact:** Server-enforced administrator boundary across configuration mutations.

**Testing and verification:** **12 unit tests** in `python_back_end/tests/test_require_admin.py` (158 lines) covering both user shapes, fail-closed behavior, 401-vs-403 ordering, and source-level assertions that each listed mutation declares the gate.

**Remaining work:** None identified for the gate itself.

---

### 3.4 Settings and Build Cockpit "Honesty Pass" + Progressive Streaming

**Status:** Complete, limited verification (deployed and eyeballed locally by the operator across themes; no automated tests)
**Area:** User interface · Agent workspace · Chat and conversations · API and backend

**Problem addressed:** The Settings modal and the Build cockpit surfaced affordances that were not wired to anything (Connections/Personalization panels, a JWT copy row, a Preview tab, a microphone control, "SSH soon" and Connect-GitHub/CLI calls-to-action), and the Build "ThoughtStream" buffered model output until end-of-turn instead of showing it live.

**What changed:** Unwired Settings panels were unhooked from the modal; the About panel now shows Harvis identity without third-party badges; `enable_api_keys` and `enable_memories` default to false on `/api/config` so the UI does not advertise capabilities that are not present. In Build, the dead affordances were hidden, browser quick-links now use the current origin instead of a hardcoded host, the ThoughtStream renders live token text with a 20-second Connecting→Retry state, and the backend flushes token/tool deltas immediately (`owui_compat/chat_completion.py`) rather than buffering.

**Technical implementation:** ~110 frontend files under `front_end/owui/src` (cross-cutting, committed as one coherent verified body), plus new Settings sub-components; backend `chat_completion.py` (+144 lines) and `config.py`. A design-system foundation (`themes.ts`, `Skeleton`, `ChatItemSkeleton`, `UnderConstruction`, `HarvisLogoMark`, `DESIGN.md`, `ICONS.md`) landed alongside.

**User or system impact:** The UI now shows only what actually works, and Build output appears as it is generated. This directly serves the operator's standing principle that the interface must never present a failure or an unwired feature as a confident success.

**Testing and verification:** Deployed locally and visually reviewed by the operator across the three themes ("it looks good"). No automated UI tests were added.

**Remaining work:** A micro-typography lift and raw hex-color cleanup in eight non-cockpit files remain, explicitly non-blocking.

---

### 3.5 Animated Mascot (pipeline + startup/idle clips + player)

**Status:** Complete and verified
**Area:** User interface · Developer experience

**Problem addressed:** Harvis had no product mascot; the prior SVG mascot had run-state bugs (it animated over finished runs, ignored reduced-motion).

**What changed:** A charcoal cube-headed "gentleman terminal" mascot was produced via a reusable **green-screen MP4 → transparent WebM** pipeline (`assets/mascot/scripts/convert_mascot.py`) with HSV keying, background-mask dilation, a de-spill step, and a per-frame audit that fails the conversion rather than shipping a halo. A state-driven Svelte player (`HarvisAnimatedMascot.svelte`) plays a one-shot **startup** boot clip that hands over to a looping **idle** clip; one-shots physically cannot loop, the boot fires once per browser session, and the component honors reduced-motion and pauses on hidden tabs.

**Technical implementation:** `assets/mascot/`, `front_end/owui/src/lib/components/mascot/HarvisAnimatedMascot.svelte`; a bare `mascot/` `.gitignore` pattern that was silently blocking the new directories was removed.

**User or system impact:** Harvis has a mascot that can carry run state (the recon ranked "mascot as run-state instrument" the highest value-per-effort UI idea). It deploys on merge of the deploy-test branch.

**Testing and verification:** Both clips are audit-clean across 97 frames each; the startup→idle handoff measured 97.2% silhouette IoU; both serve HTTP 200 from nginx at `/mascot/`. The operator visually confirmed the design.

**Remaining work:** Six additional mascot states remain optional; a look at the mascot at its real 96px render size in the running app is recommended before generating more.

---

### 3.6 Build Space v1 Omnibus (landed 2026-07-15 — prior in the window)

**Status:** Complete, limited verification *(reported from commit metadata; not exercised hands-on this session)*
**Area:** Agent workspace · Repository automation · Integrations · Repo Runner

**Problem addressed / what changed:** A single large commit (`3fd5d0a5`) titled "agent review + Build Space v1 + Discord code + run UI" landed at the start of the window. By its diff it touches the agent-review flow (`workspace/orchestration/review.py`, +543), the Build PR drawer (`PrDrawer.svelte`, +517), the Discord workspace bot (+1324), the workspace router (+859), the vibecode page (+888), and the three hardware compose files. It is the single largest churn source in the window.

**Verification:** This report characterizes `3fd5d0a5` from its commit message and diffstat only. It was not re-verified in this session, and its internals are not independently confirmed here (see §14).

---

## 4. Bug Fixes and Smaller Improvements

- **Health endpoint read the wrong pool attribute (`main.py`).** `GET /api/health/services` read `app.state.pool` while the pool is assigned to `app.state.pg_pool`, so the database check *structurally could never* report healthy — it returned a permanent "degraded / no connection pool" while the database was fine. Fixed to read `pg_pool` and actually run `SELECT 1`; a TTS probe was added and `/api/auth/stats` was gated behind auth. **Practical effect:** the endpoint that the installer's health poll and the wizard's verification depend on can now report the truth.
- **Fresh-volume database bootstrap (`main.py`, `init-db.sh`, `migrations/000_extensions.sql`).** Mounted init files reference a `users` table nothing in the mount set created, and the pgvector extension sorted last; a fresh volume could abort init. The schema is now applied idempotently from the startup ensure block (which also heals existing volumes) and the extension moved to an explicit `000_extensions.sql`. *(Note: the abort was argued statically; settling it definitively is part of the pending clean-clone E2E.)*
- **Installer status-parse bug (HIGH) — `install.sh`.** After the status endpoint gained a second key, the installer's anchored regex always matched empty and always printed "unreachable," so the first-admin setup code was never printed. Fixed to extract the single field it needs and to distinguish "no response" from "unrecognized response."
- **Silently-dropped pasted URLs (`owui_compat/chat_completion.py`).** A URL a user pasted that failed to fetch or was SSRF-blocked was skipped with no marker, so the model could answer confidently about content it never received. Now each failure appends an in-band "### Could not read `<url>`" block.
- **Faked-durable cookie preference (`setup_flow.py`).** The setup wizard's `cookie_secure` toggle wrote a DB row nothing read and claimed durability in its docstring; on restart the value silently reverted. Made honest (process-level only, response says `cookie_secure_durable:false` and points at the `.env` var), and two dead helper functions were removed.
- **Committed-but-untracked module (`setup_flow.py`).** An earlier commit wired `from setup_flow import ...` into `main.py` and mounted the file, but the module and its mount line were never staged — a clean checkout would have failed to import. Corrected so the tree is coherent.
- **Compose override silently disabled + missing `FERNET_KEY`.** `COMPOSE_FILE` re-append and `FERNET_KEY` generation added to `install.sh` (details in §3.1).
- **Documentation.** Handoff notes, roadmap status, a corrected earlier "DB init is already handled" claim (which had been stated from inference, not a test), and `changes.md` updates.

---

## 5. Testing and Verification

| Test or verification | Area tested | Result | Evidence or notes |
|---|---|---|---|
| `test_require_admin.py` unit tests | Authorization (T1) | **Pass** | 12 tests, 158 lines; both user shapes, fail-closed, 401-vs-403 |
| Health endpoint honesty | API / DB | **Pass** | Live `curl` → `overall: healthy`, `database: up`; stopping pgsql flips it to "down" with a real error string |
| Signup enforcement (both routes) | Auth / Security | **Pass** | Live `curl` on `/api/auth/signup` and `/api/v1/auths/signup` → 403 each; 0 probe accounts in DB |
| Setup-code gate — no-code / correct-code | Auth / Security | **Pass** | Adversarial pass on throwaway DB: 403 without code, admin created with code |
| Setup-code gate — concurrency race | Auth / Security | **Pass** | 5 concurrent first-signups → exactly one admin |
| Setup-code — replay after claim | Auth / Security | **Pass** | Second signup after claim rejected |
| Setup-code — constant-time compare | Security | **Pass** | `hmac.compare_digest` confirmed by code + adversarial review |
| `install.sh --check-only` | Installer | **Pass** | Real preflight table (docker, compose, compose-merge, ports, memory, disk); exits 0 on this host |
| Setup-status parse fix | Installer | **Pass** | Verified against all three real bodies (`needs_setup` true/false/empty) |
| `setup_flow.py` load | API | **Pass** | AST-parse clean; backend restarted healthy in ~3s; router mounted; `/api/setup/status` responds |
| Regression: existing login + chat | Auth / Chat | **Pass** | Adversarial pass: existing user login 200 + JWT; normal chat completed end-to-end and persisted |
| Mascot clips | UI asset | **Pass** | Audit-clean 97 frames each; 97.2% handoff IoU; serve 200 at `/mascot/` |
| Push to deploy-test branch | Deployment | **Pass** | `origin/harvis1.1-deploy-test` created at `797d84f1`; `origin/harvis1.1` unchanged |
| **Clean-clone `./install.sh` E2E** | Installer / Deploy | **Not run** | Blocked locally by port collision with the running stack; the key pending verification |
| **`/setup` wizard full click-through** | UI flow | **Not run** | Backend endpoints and status verified; the full browser wizard flow was not exercised |
| Frontend production build | Build | **Not run this session** | Operator reports the Settings/Build work was built and deployed locally |
| macOS / AMD install paths | Installer | **Not evaluated** | No Apple or ROCm hardware available; documented as untested |

---

## 6. Architecture and Technical Decisions

**Two-part setup: machine (Bash) vs. user (web).** *Decision:* `install.sh` handles only what must precede startup; `/setup` handles account, provider, and verification. *Reason:* the entire Harvis configuration surface cannot live in a shell script, and a web page cannot install Docker. *Benefit:* each layer does what it is suited to; the installer stays honest and small. *Tradeoff:* two codebases to keep in sync (the parse bug in §4 was exactly a sync failure). *Consequence:* the status contract between them must be treated as an interface.

**Security-gate-first sequencing.** *Decision:* the setup-code gate and the honest health endpoint were built and verified *before* the wizard UI. *Reason:* the installer's honest handoff must poll an endpoint that can actually report healthy and hand over a code something actually consumes; building the UI first would have produced a more elaborate way to lie. *Benefit:* every later step rested on a verified foundation.

**Behavioral compose gate rather than version parsing.** *Decision:* assert on the rendered `docker compose config` output, not on the Compose version string. *Reason:* the `!reset` behavior floor is empirical (2.19), and the installed version is 5.x, so version parsing is both unreliable and brittle. *Benefit:* detects the actual failure (surviving NVIDIA reservations in a CPU profile) regardless of version numbering.

**Gate inside the shared function, not on the routes.** *Decision:* the signup gate lives in `_signup_with_connection`, the one path both signup routes share. *Reason:* route-level gating would have left the facade route open. *Benefit:* one choke point; the adversarial pass confirmed no route bypasses it.

**Honest readiness probes as a contract.** *Decision:* every `/api/setup/verify` tick returns `{ready, reason, probe}` backed by a real probe, and the model check performs a real generation. *Reason:* the operator's hardest standing rule is that the UI must never present a failure as a confident success or empty state. *Tradeoff:* real probes cost a little latency; accepted.

**Push to a separate branch.** *Decision:* verified work went to `origin/harvis1.1-deploy-test`, not the main working branch. *Reason:* standing rule; the deploy-test branch is the vehicle for the clean-clone E2E on a clean environment.

---

## 7. Security and Reliability Review

| Concern | Classification | Notes |
|---|---|---|
| First-signup admin takeover (T2) | **Resolved** | Setup-code gate; adversarially verified — unclaimable without the code, race-safe, replay-rejected, constant-time compare |
| Server-side admin authorization (T1) | **Resolved** | `require_admin` dependency; 12 unit tests; fails closed |
| "Disable signup" not enforced server-side | **Resolved** | `HARVIS_OWUI_ENABLE_SIGNUP` now enforced in the shared signup path; defaults disabled after admin exists |
| Backend published on host `:8000` bypasses nginx | **Open (accepted this week)** | The signup rate limit lives only in nginx; a direct `:8000` caller bypasses it. Not a break — the setup code is 48-bit with a constant-time compare, so online brute force is infeasible — but it erodes defense-in-depth, and the "cannot be brute-forced" phrasing in an earlier commit is only true via the front door. The operator chose to keep `:8000` exposed for direct backend debugging. |
| Secrets generated, not committed | **Resolved** | `install.sh` generates `JWT_SECRET`, `FERNET_KEY`, `HARVIS_SETUP_CODE`, `OPENCLAW_GATEWAY_TOKEN` (generate-if-absent); `.env.example` holds only blank placeholders; the setup code is kept out of `deployment.log` |
| Unauthenticated reconnaissance surface | **Open (LOW)** | `/api/setup/status`, `/api/config` (`onboarding`), and `/api/health/services` reveal setup state and the internal service map to anonymous callers. No credential or user-data leak. |
| `/api/research/health` fabricates availability and is unauthenticated | **Open (pre-existing)** | Hard-codes components as "available" without probing. Must never back a readiness tick; flagged for a future honesty cleanup. |
| SSRF on user-pasted URLs | **Mitigated** | `_validate_url` rejects private/localhost/non-http(s); failures are now surfaced in-band rather than silently dropped |
| Restart behavior / stale state | **Mitigated** | The setup admin id persists to `instance_settings`; the process-only `cookie_secure` is now honestly labeled as non-durable |
| Clean-install runtime correctness | **Needs investigation** | The fresh-volume DB bootstrap fix is not yet proven on a scratch volume; part of the pending clean-clone E2E |

No claim is made that the system is secure overall. The setup-code path was adversarially tested and holds; the `:8000` exposure and the reconnaissance endpoints are known-open items.

---

## 8. Known Issues, Risks, and Blockers

| Issue | Severity | Current impact | Status | Recommended action |
|---|---|---|---|---|
| Clean-clone `./install.sh` E2E never run | High | Installer completeness and the fresh-volume DB fix are unproven end-to-end | Open | Run `./install.sh` from a fresh checkout in an isolated environment (or on the deploy-test branch on a clean host) |
| Backend `:8000` bypasses nginx rate limiting | Medium | Signup rate limit and other nginx protections skippable via the direct port | Open (accepted) | Remove the `8000:8000` mapping when hardening for exposure; nginx reaches the backend over the compose network regardless |
| `/setup` wizard not exercised end-to-end | Medium | The full click-through (provider, model pull, verification, test chat) is unverified live | Open | Browser-test the wizard on the deploy-test deployment |
| `/api/research/health` fabricates availability, unauthenticated | Medium | Could mislead a status surface; recon exposure | Open (pre-existing) | Make it probe for real or remove it from status surfaces |
| Unauthenticated status/health/config recon | Low | Anonymous callers learn setup state and the service map | Open | Gate per-service detail behind auth; return a minimal liveness body unauthenticated |
| `_probe_ollama` does not strip a `/v1` suffix | Low | Wizard tick could read red while `/api/health/services` reads green for the same service | Open | Copy the normalization from `health_services` |
| `setup/preferences` `enable_signup` is a no-op | Low | The wizard toggle changes nothing (fails closed) | Open | Wire it to `instance_settings` or remove the control |
| `create_test_user.py` raises on existing `testuser` | Low | Dev script unusable on a populated DB | Open | Use `INSERT ... ON CONFLICT`, or move the script out of the repo root |
| `setup_complete` reads false on a first-signup-claimed instance | Low | Cosmetic; the wizard shows "not completed" to an admin who claimed via signup | Open | Write `setup_complete` on the claim path, or document its meaning |
| `3fd5d0a5` omnibus not independently verified | Low | Large change reported from metadata only | Open | Verify its subsystems if they become load-bearing |

---

## 9. Files and Systems Most Affected

| Area | Important files or directories | Purpose of changes |
|---|---|---|
| Installer | `install.sh` (~460 lines changed), `.env.example` (new), `docker-compose.{cpu,amd}.yml` | Preflight, behavioral compose gate, secret generation, honest health-gated handoff |
| Setup backend | `python_back_end/setup_flow.py` (new), `main.py`, `owui_compat/config.py`, `owui_compat/translate.py`, `migrations/000_extensions.sql`, `init-db.sh` | Setup-code gate, honest health/verify probes, onboarding signal, fresh-volume bootstrap |
| Setup / onboarding UI | `front_end/owui/src/routes/setup/` (new), `lib/apis/setup/`, `SetupStepper.svelte`, `constants/publicRoutes.ts` | First-run wizard and its guarded, no-JWT API client |
| Settings & Build UI | ~110 files under `front_end/owui/src` incl. `Settings/Interface.svelte`, `SettingsModal.svelte`, Build cockpit components, `chat_completion.py` | Honesty pass (remove unwired affordances) + progressive streaming |
| Authorization | `owui_compat/authz.py` (new), `rag_corpus/routes.py`, `tests/test_require_admin.py` | Server-side `require_admin` gate + tests |
| Design system | `owui/DESIGN.md`, `ICONS.md`, `themes.ts`, `Skeleton`/`ChatItemSkeleton`/`UnderConstruction` | Shared token maps and primitives for the honesty/loading work |
| Mascot | `assets/mascot/`, `HarvisAnimatedMascot.svelte` | Conversion pipeline + state-driven player |
| Build Space v1 (07-15) | `workspace/orchestration/review.py`, `PrDrawer.svelte`, `discord_workspace_bot.py`, `workspace_router.py` | Agent review, PR drawer, Discord code flow (omnibus) |
| i18n | `owui/src/lib/i18n/locales/en-US/translation.json` (~5,900 lines) | Large translation churn accompanying the UI work |
| Docs | `docs/handoffs/`, `docs/plans/`, `docs/design/`, `docs/research/`, `changes.md` | Handoffs, roadmap status, design notes |

---

## 10. Commit Summary

*22 commits in the window; the 19-commit burst on 2026-07-20 is grouped below by work item rather than listed individually.*

| Commit | Date | Description | Related work item |
|---|---|---|---|
| `3fd5d0a5` | 07-15 | Build Space v1 omnibus (agent review, PR drawer, Discord code, run UI) | §3.6 |
| `8defacab` | 07-19 | Mascot green-screen conversion pipeline + player | §3.5 |
| `3c8616b2` | 07-19 | Server-side `require_admin` gate for admin/config mutations | §3.3 (T1) |
| `3c7917da` | 07-20 | Mascot startup boot clip + hover idle loop, keyed and wired | §3.5 |
| `016b33c1` | 07-20 | Keep local compose override; generate `FERNET_KEY` | §3.1 |
| `a1d44602` | 07-20 | Health endpoint reads real `pg_pool`; TTS probe; gate `/api/auth/stats` | §4 / §3.1 |
| `ca7a8070` | 07-20 | Fresh-volume DB bootstrap no longer aborts on missing users table | §4 / §3.1 |
| `783cbada` | 07-20 | First-signup setup code + server-side signup gate (closes T2) | §3.2 |
| `ab98e2fd` | 07-20 | Onboarding signal in `/api/config` + `GET /api/setup/status` | §3.1 |
| `87eeaceb` | 07-20 | install.sh preflight refactor + `--check-only` + behavioral compose gate | §3.1 |
| `b0fcdc1f` | 07-20 | Generated setup secrets + observed startup handoff | §3.1 |
| `9a278715` | 07-20 | Track `setup_flow.py` + its compose mount (forgotten in git add) | §4 |
| `c066b430` | 07-20 | Backend progressive stream flush + config honesty defaults | §3.4 |
| `8d5356b8` | 07-20 | Design-system foundation + shared components | §3.4 |
| `8ccad5b7` | 07-20 | First-run `/setup` wizard shell + tri-state setup API client | §3.1 |
| `89737633` | 07-20 | Settings + Build cockpit honesty pass + progressive streaming | §3.4 |
| `47444bff` | 07-20 | open-notebook theme sync to Harvis tokens | §3.4 |
| `499e4c15` | 07-20 | Root `.env.example` + install.sh polish | §3.1 |
| `d6c8469b` | 07-20 | Docs: setup-flow + Settings/Build writeups, roadmap, handoffs | §4 |
| `6323cb06` | 07-20 | Installer-hardening handoff; mark mascot done on roadmap | §4 |
| `2527a0cd` | 07-20 | Parse `/api/setup/status`'s two-key body (HIGH — was dead handoff) | §4 |
| `797d84f1` | 07-20 | Mark unreadable pasted URLs; stop faking durable cookie_secure | §4 |

---

## 11. Incomplete and Uncommitted Work

At the time of writing, the working tree is **clean** — all work described above is committed, and the branch is pushed to `origin/harvis1.1-deploy-test`. There are no uncommitted or stray changes to preserve, and no generated files or secrets were committed (the frontend `build/` directory and OpenClaw config paths remain gitignored by design).

Work that is committed but **not yet fully verified** (as opposed to uncommitted):
- The `/setup` wizard's provider/model/exposure/verification/test-chat steps are wired to verified backend endpoints but were not exercised end-to-end in a browser this session.
- The fresh-volume DB bootstrap fix (`ca7a8070`) addresses a failure that was argued statically; it is not yet reproduced-and-confirmed on a scratch volume.
- A clean-clone `./install.sh` has not been run; it is the primary outstanding verification.

---

## 12. Next-Week Priorities

1. **Clean-clone end-to-end installer test.**
   *Objective:* prove a fresh clone reaches a working, claimed instance. *Why it matters:* it is the one verification the local stack could not provide and the conclusive proof the installer works for a new user; it also proves commit completeness. *Work:* clone to an isolated environment (or deploy the deploy-test branch on a clean host), run `./install.sh`, complete `/setup`, send one test chat; confirm the build step generates `owui/build` and the gitignored OpenClaw config paths are handled. *Done when:* a stranger-equivalent run ends in a successful test chat with no manual fix-ups.

2. **Exercise the `/setup` wizard in a browser, end-to-end.**
   *Objective:* verify the full onboarding click-through. *Why it matters:* the backend is proven but the UI flow is not. *Work:* fresh instance → visit `/`, get redirected to `/setup`, enter the printed code, create the admin, pull a small model with the progress bar, run the verification panel, complete the test chat. *Done when:* every step works live and the final verification ticks are honest (stop a service, confirm its tick goes red).

3. **Decide and act on the `:8000` exposure.**
   *Objective:* close the nginx-bypass or formally accept it with documentation. *Why it matters:* it is the one open medium security item and it makes an earlier commit's brute-force claim only partly true. *Work:* either remove the `8000:8000` mapping (nginx reaches the backend internally) or document the accepted risk and correct the claim. *Done when:* the exposure is removed, or the acceptance and its rationale are written down.

4. **Honesty cleanup of the six LOW findings.**
   *Objective:* close the recon leaks and the no-op toggles. *Why it matters:* they are small but they are exactly the "UI implies something that is not true" class the project is trying to eliminate. *Work:* minimal liveness body for unauthenticated health, `/v1` normalization in `_probe_ollama`, wire or remove the wizard `enable_signup` toggle, fix `create_test_user.py`, resolve `setup_complete` semantics. *Done when:* each is fixed or explicitly documented as intended.

5. **T3 — hide Share actions everywhere.**
   *Objective:* remove Share affordances (sharing is not being built now). *Why it matters:* next item in the standing security order; avoids advertising an unbuilt capability. *Work:* gate Share controls behind a flippable constant, do not delete source. *Done when:* no Share action is reachable and the code is preserved behind a flag.

6. **T4 — implement Clone chat.**
   *Objective:* clone a conversation into a new chat with a differentiated title. *Why it matters:* a concrete user-value feature reusing existing chat creation/retrieval. *Work:* narrowly scoped clone endpoint reusing `get_chat` + `create_chat`; no schema redesign. *Done when:* a chat can be cloned and the copy is clearly labeled.

7. **T5 — remove `/workspace` and `/admin` from navigation via reversible flags.**
   *Objective:* hide unfinished multi-tenant surfaces without deleting them. *Why it matters:* completes the standing security/cleanup order. *Work:* reversible registry flags; keep `/harvis/knowledge` and Settings → Customize as the primary interfaces. *Done when:* the routes are unreachable through normal nav and re-enablable by flipping a flag.

---

## 13. Overall Assessment

**Overall status:** A strong, security-forward week. The headline deliverable — a real first-run setup system that gets a stranger from a fresh clone to a claimed, working instance — is built, largely verified, and pushed to a deploy-test branch, with the previously-open admin-takeover risk closed and independently attacked. The Settings/Build honesty pass, progressive streaming, the `require_admin` gate, and the mascot all landed as well.

**Confidence level:** **Moderate confidence.** The backend security core and the honesty fixes were verified live and adversarially, which is high-confidence evidence. Confidence is held at moderate rather than high for two reasons: the end-to-end installer path and the full `/setup` wizard flow have not been exercised in a clean environment, and one large in-window commit (`3fd5d0a5`) is reported from metadata rather than hands-on verification.

**Most important accomplishment:** Closing T2 with an adversarially-verified first-signup setup-code gate — a fresh instance can no longer be silently claimed by whoever reaches it first.

**Most important unresolved concern:** The clean-clone installer E2E has not been run, so "a new user can install Harvis and it works" is designed and largely component-verified but not yet proven as a whole.

**Ready for the next milestone?** The deploy-test branch is ready to be deployed and exercised on a clean host. It is not yet ready to merge to the main working branch: that gate is the clean-clone E2E plus the `/setup` browser walkthrough. Once those pass, merge and the remaining T3–T5 cleanup are the natural next milestone.

---

## 14. Evidence Gaps

- **Reporting dates were not provided.** The window (2026-07-14 → 2026-07-20) was inferred from commit timestamps; it is the standard week ending at the latest commit. A different intended window would change which commits are in scope (notably `3fd5d0a5` on 07-15).
- **Report author not specified.** Attributed to the git committer of record (`brandoz2255`).
- **`3fd5d0a5` (Build Space v1 omnibus)** is reported from its commit message and diffstat only; its internals were not independently verified this session.
- **No clean-clone or deployment-log evidence.** A fresh `./install.sh` was not run; the deploy-test branch has not been deployed to a clean host. Installer correctness is inferred from `--check-only`, unit-level checks, and live checks against the already-running stack.
- **Full `/setup` wizard flow not exercised.** Backend endpoints and the status contract were verified; the browser click-through was not.
- **Frontend production build not run this session.** The Settings/Build work's build success rests on the operator's report that it was built and deployed locally.
- **macOS and AMD/ROCm install paths not evaluated** — no such hardware available; documented as untested rather than claimed working.
- **No external issue-tracker references** were available; work items are traced to commits, the roadmap document, and the standing task list.
