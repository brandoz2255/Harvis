# Windows / Docker Desktop — Install E2E Findings Log

**Started:** 2026-07-20
**Environment:** Windows + Docker Desktop *(details to fill in as we confirm them)*
**Branch under test:** `harvis1.1-deploy-test` @ `797d84f1`
**Why this matters:** this is the **clean-clone end-to-end test** — the single largest outstanding
verification gap. It is also the **first Windows test ever run** on Harvis; every prior verification
was on this Linux dev box. Anything found here is new information, not a regression.

**How this file works:** findings get appended as they happen, newest at the bottom of §2. Anything
in §3 is a *prediction* — an untested hypothesis about what Windows might break — and must be moved
into §2 with real evidence before it counts as a finding. Predictions are not findings.

---

## 1. Environment (fill in as confirmed)

| Item | Value | Confirmed? |
|---|---|---|
| Windows version | | ☐ |
| Docker Desktop version | | ☐ |
| Docker Compose version (`docker compose version`) | | ☐ |
| Backend (WSL2 / Hyper-V) | | ☐ |
| Shell used to run `install.sh` (Git Bash / WSL / PowerShell) | | ☐ |
| GPU present / passthrough configured | | ☐ |
| Chosen profile (nvidia / amd / cpu) | | ☐ |
| RAM / free disk | | ☐ |

---

## 2. Findings

> Format for each entry — keep it short but evidence-backed:
> **F-NN · [severity] · short title**
> *What happened:* (the actual observed behavior / error text)
> *Where:* (command, file, step)
> *Cause:* (if known — otherwise "unknown, needs investigation")
> *Fix / workaround:* (if applied)
> *Status:* observed / diagnosed / fixed / deferred

**F-01 · [HIGH] · No `.gitattributes` — Windows clones get CRLF `install.sh`, which cannot run**

*What happened:* Found pre-emptively by inspection, before the Windows run reached the installer.
The repository had **no `.gitattributes` at all**, so nothing forced LF endings on shell scripts.
Git for Windows defaults to `core.autocrlf=true`, which rewrites `install.sh` to CRLF on checkout.
`install.sh` uses **9 bash-only constructs** (`/dev/tcp`, `[[ ]]`, `<<<`, arithmetic expansion), so
it needs a real bash — and bash on a CRLF script fails with misleading errors such as
`$'\r': command not found` or a syntax error on a line that is valid.

*Where:* repository root; affects `install.sh`, `init-db.sh`, and every other `*.sh`.

*Cause:* missing `.gitattributes`; the repo relied on each user's local git configuration. Harvis is
intended to be cloned by strangers, many on Windows, so this is a real first-run blocker for that
audience — not a local misconfiguration.

*Fix applied:* added `.gitattributes` forcing `text eol=lf` on `*.sh`, `*.bash`, Dockerfiles, and the
YAML/SQL/`.env.example` files that Linux containers read verbatim.

*Workaround for a clone made BEFORE this fix* (likely the current Windows checkout):
```bash
# in Git Bash, from the repo root
git config core.autocrlf input
git rm --cached -r . && git reset --hard      # re-checkout with LF
# or, to fix just the installer without touching anything else:
dos2unix install.sh        # or:  sed -i 's/\r$//' install.sh
```
*Verify:* `file install.sh` should report a shell script **without** "with CRLF line terminators".

*Status:* **fixed at source** (`.gitattributes` added, uncommitted); the existing Windows clone still
needs the workaround above. Not yet confirmed against a fresh Windows clone — that confirmation is
the next thing to record here.

**F-02 · [MEDIUM] · First-run downloads ~7.9 GB of TTS/STT models before the backend can start, ~2 GB of it duplicate**

*What happened:* Measured during the Windows setup. The `model-downloader` service populates the
`ml-models-cache` volume and **the backend waits on it**, so this is blocking first-run cost, not a
background nicety. Sizes below came from the Hugging Face API, not estimates.

| Item | Purpose | Size |
|---|---|---|
| Whisper `base` (OpenAI) | Speech-to-text | ~0.14 GB |
| `Qwen/Qwen3-TTS-Tokenizer-12Hz` | Standalone speech tokenizer | 0.68 GB |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | Primary TTS (GPU) | 4.54 GB |
| `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | CPU fallback, used only if the 1.7B OOMs | 2.52 GB |
| **Total** | | **~7.9 GB** |

*Where:* `docker-compose.yaml` `model-downloader` service (defaults `DOWNLOAD_QWEN_TTS: "true"`,
`DOWNLOAD_CHATTERBOX_TTS: "false"`); `python_back_end/download_models.py`. Lands in the Docker data
root — on this Windows host that is the relocated `F:` drive, not `C:`.

*Verified against the code:* service, volume, both env defaults, and all three Qwen repo IDs
(`download_models.py:20-22`) match exactly. Whisper defaults to `base` (`:39`, `:62`).

**Sub-finding (a) — ~2 GB of genuinely duplicated bytes.** The 682 MB speech-tokenizer weights are
pulled **three times**: once as the standalone tokenizer repo, and again bundled inside each of the
1.7B and 0.6B repos, which each ship their own copy rather than referencing the shared one. This is
how the upstream HF repos are packaged; `download_models.py` does not dedupe across repos. Not a
Harvis bug, but it is ~25% of the first-run download.

**Sub-finding (b) — the CPU fallback cannot be skipped separately.** There is one switch
(`DOWNLOAD_QWEN_TTS`, `download_models.py:426`). Setting it `true` always pulls **both** the 1.7B and
the 0.6B, even on a machine that will never use CPU fallback — 2.52 GB that many users cannot benefit
from. A second flag (or "download the fallback only when no GPU is detected") would cut the default
first-run by roughly a third.

**Sub-finding (c) — NEW, not in the original report: the safe ChatterboxTTS default exists only in
compose.** `download_models.py:428` defaults `DOWNLOAD_CHATTERBOX_TTS` to **`"true"`**; only
`docker-compose.yaml` overrides it to `"false"`. So the script is safe *when run through compose* and
unsafe otherwise — a k8s deployment, a manual `python3 download_models.py`, or any compose file that
omits the var will attempt `chatterboxai/chatterbox-tts`, which is **gated on Hugging Face** and
requires a token. Expect a confusing auth failure rather than a clear "this is optional" message.
This is the same "works here, breaks elsewhere" class as the earlier untracked-module bug.

*Fix / workaround:* none applied yet. Candidates, in value order:
1. Flip the script's own `DOWNLOAD_CHATTERBOX_TTS` default to `"false"` so safety does not depend on
   the compose file (sub-finding c) — smallest change, removes a real failure mode.
2. Add a separate switch for the 0.6B fallback, or gate it on GPU detection (sub-finding b) — saves
   2.52 GB on the common path.
3. Surface the total download size in `install.sh`'s plan output before it starts pulling. The
   installer currently gives no warning that ~8 GB is about to be fetched. *(Note: the weekly report
   flagged "estimated download" as something not to invent — but these figures are HF-API-sourced and
   the model set is fixed, so this one can be stated honestly.)*

*Impact on the product goal:* the north-star includes mid-range-hardware accessibility. An unannounced
~8 GB blocking download — a quarter of it duplicate, a third of it an unusable fallback on GPU boxes —
is a meaningful first-run barrier for exactly that audience.

*Status:* **observed and code-verified; no fix applied.** Sub-finding (c) is the one I would fix first.

**F-03 · [HIGH] · Build takes up to 532s — no `.dockerignore`, so a 24 GB build context ships twice**

*What happened:* Observed on Windows / Docker Desktop: the stack takes **up to 532 seconds (~8m 52s)**
to start.

*Diagnosis (code-verified, not guessed):*
- **16 services build from source** — backend, model-downloader, document-worker, harvis-mcp,
  browser-runner, frontend, owui-builder, open-notebook-ui, openclaw, tts-service, messaging-gateway,
  opencode, codex, claude-code, hermes-agent, cad-engine.
- **There is no `.dockerignore` anywhere in the repo.**
- **Two of those services use `context: .` — the entire repository:**
  `openclaw` (dockerfile `openclaw-browser/Dockerfile`) and `tts-service`
  (dockerfile `docker/tts-service/Dockerfile`).
- **The repository is 24 GB.** Breakdown of the biggest contributors:

  | Directory | Size | Needed in a build context? |
  |---|---|---|
  | `image-comfy/` | **13 GB** | **No** — no Dockerfile references it |
  | `image-models/` | **4.0 GB** | **No** — no Dockerfile references it |
  | `front_end/` | 3.4 GB | partially (2.8 GB of that is `node_modules` across 5 dirs) |
  | `.claude/` | 3.1 GB | **No** — contains git worktrees, i.e. whole extra copies of the repo |
  | `.git/` | 154 MB | **No** |
  | `assets/` | 106 MB | possibly (mascot media) — left alone pending a check |

  Verified: `grep -r "image-comfy\|image-models" --include='Dockerfile*'` returns **nothing**, so
  **17 GB of model weights are shipped to the Docker daemon and then discarded — twice.**

*Why Windows makes it worse:* Docker Desktop runs the daemon inside a VM, so the whole context is
transferred across the host↔VM boundary. The same repo on native Linux pays a much smaller penalty,
which is why this never showed up on the Linux dev box — **this is a Windows-first discovery, and it
would hit every Docker Desktop user (Windows and macOS) equally.**

*Fix applied:* added a root `.dockerignore` excluding the verified non-inputs — `image-comfy/`,
`image-models/`, all `node_modules`, `.claude/`, `.git/`, Python caches, and build outputs. This cuts
the context from ~24 GB to well under 1 GB for the two `context: .` services, and also trims every
other build that would otherwise sweep in `node_modules`.

*Expected effect:* the context-transfer portion of build time should drop by roughly an order of
magnitude. **Not yet measured** — the next Windows rebuild is the measurement, and the before/after
numbers belong in this entry.

*If a build breaks after this:* the fix is a single new file at the repo root. `rm .dockerignore`
reverts it completely. The most likely culprit would be a Dockerfile doing `COPY . .` and depending on
something excluded; `assets/` was deliberately **not** excluded for that reason.

*Separately worth noting:* 16 build-from-source services is itself a lot for a first run. Most users
do not need `opencode`, `codex`, `claude-code`, `hermes-agent`, or `cad-engine` — these are optional
engines. A compose profile that builds only the core stack by default would cut first-run time
further, independent of the context fix. Filed as a follow-up, not done here.

*Status:* **diagnosed; `.dockerignore` fix applied, effect not yet measured.**

**F-04 · [CRITICAL] · The OpenClaw config tree never ships — every fresh clone, every OS, cannot start**

*What happened:* `.gitignore:134` ignores `openclaw/` wholesale, and `openclaw/config/bundled/` +
`openclaw/config/shared/` were **never committed on any branch**. Compose bind-mounts **six files**
from those paths. When a bind-mount source does not exist, Docker silently creates an empty
**directory** in its place. OpenClaw then tries to read a directory as its config file and crashloops.
Because `backend` declares `depends_on: openclaw`, **nothing starts.**

*Scope:* every fresh clone on every operating system. This is the single "one command out of the box"
killer — not Windows-specific.

*My earlier under-rating of this:* during the pre-push integrity scan I found exactly these paths
(`IDENTITY.md`, `SOUL.md`, `plugins/`, `skills/shared`) flagged as "gitignored but bind-mounted," and I
classified them as *"pre-existing, a separate concern, not introduced by this work."* That was correct
about provenance and **wrong about severity** — it is a total first-run blocker. Noting it so the
misjudgement is on the record, not just the finding.

*Fix direction (not applied):* either force-add a template config tree past `.gitignore`, or have
`install.sh` generate it during preflight. The generate-it path is probably better, since these files
hold instance identity.

*Status:* diagnosed, not fixed.

---

**F-05 · [HIGH] · Double lockout — signup button hidden AND setup code closed, with no error and no way in**

*What happened:* On a stack with a **carried-over database**, the tester could not create an account by
any route:
- `HARVIS_OWUI_ENABLE_SIGNUP` defaults to `false` (this is **our T2 change**), so `/api/config` reports
  `enable_signup: false` and the UI correctly hides the Sign-up button.
- The setup-code path was **also** closed, because two users survived in the carried-over DB, so
  `/api/setup/status` reports `needs_setup: false` and the first-signup branch is never entered.

Both doors locked simultaneously, with **no message explaining why** and no recovery path.

*Root cause, and it is ours:* T2 assumed exactly two states — a *fresh* install (empty users table →
setup code opens the door) or an *established* install (admin exists → they log in). It has **no answer
for the third state: a non-empty database whose credentials the operator does not have.** That is
precisely the upgrade path — old DB, new code — and it is the most likely real-world scenario for
existing users pulling this branch.

*Workaround used by the tester:* set `HARVIS_OWUI_ENABLE_SIGNUP=true` in `.env` and recreate the
backend. **This is a local test setting and must be reverted before this instance faces a network** —
`.env.example` says to leave it `false` once an admin exists.

*Fix direction (not applied):* the recovery path needs to exist and be discoverable. Options worth
weighing: a CLI admin-creation/password-reset command; having the setup code work whenever *no admin*
exists (rather than when *no users* exist); or at minimum an honest UI message on the login page
explaining that signup is disabled and how to recover. Silent double-lockout is the worst outcome and
is itself an honesty failure.

*Status:* diagnosed, not fixed. **This is a direct consequence of today's T2 work and should be
resolved before the branch is merged.**

---

**F-06 · [HIGH] · Post-login redirect never fires — a successful login renders a client-side 404**

*What happened:* Login succeeds — 200 + a real JWT, and every subsequent API call (`/api/v1/auths/`,
`/api/v1/users/user/settings`) returns 200. But the browser stays on `/login` and SvelteKit renders
`404: Not Found` in the body. The SPA shell (head, theme) loads correctly.

*Diagnosis:* nginx is **not** at fault — `try_files` is correct, and `/` and `/login` serve an
identical `index.html` (same md5) with no "404" text in the served HTML. The 404 is rendered
**client-side after hydration**, because the post-login navigation never fires.

*Impact:* this makes a **fully working install look completely broken**. The user concludes sign-in
failed when it actually succeeded. Combined with F-05, this is why "we can't get in" felt fatal.

*Workaround:* after logging in, manually navigate to `http://localhost:9000/`.

*Status:* diagnosed, not fixed.

---

**F-07 · [HIGH] · `install.sh --check-only` reports ports free that are actually occupied**

*What happened:* Preflight reported **"11 ports free"** while Cursor held **9000** and native Ollama
held **11434**. The failure then surfaced later as a cryptic `/forwards/expose returned 500` at runtime.

*Cause:* the port probe uses `/dev/tcp/127.0.0.1/$port` **from inside WSL**, which cannot see listeners
bound on the Windows host. The check is structurally incapable of seeing the conflict it exists to
catch, yet it prints `PASS`.

*Why this one stings:* this is **new code from today**, and it is the exact bug class this whole effort
has been eliminating — a check that reports confident success for something it cannot actually observe.
The behavioral compose gate was written specifically to avoid this trap; the port check fell into it.

*Fix direction (not applied):* probe from the host rather than inside WSL, or detect the WSL case and
**downgrade the row to a warning that says it cannot see host listeners** — never a green PASS. Also
catch the `/forwards/expose 500` at runtime and translate it into a plain-language port-conflict message.

*Status:* diagnosed, not fixed.

---

**F-08 · [MEDIUM] · Three migrations never run on any deployment path**

*What happened:* `cron_jobs`, `workspace_jobs`, and `workspace_runs` have SQL committed in the repo,
but **nothing applies it** — `init-db.sh` does not create them even on a fresh database. Result:
continuous error spam and broken workspace/cron features.

*Relationship to today's work:* `ca7a8070` fixed the `users` table bootstrap specifically. This is the
same class of gap, wider than what that fix covered — there is no general migration runner, just an
init script that has to be remembered.

*Fix direction (not applied):* a real migration runner, or fold these into `init-db.sh` alongside the
users schema.

*Status:* diagnosed, not fixed.

---

**F-09 · [MEDIUM] · Port 11434 collides with native Ollama (very common on a Windows dev box)**

*What happened:* Native Ollama already held 11434. The tester's resolution was to reuse the host
instance via a socat forwarder, which then worked end to end.

*Fix direction (not applied):* detect an existing Ollama on 11434 during preflight and **offer to reuse
it** rather than failing or silently colliding. This is likely the common case on Windows and macOS dev
machines, not an edge case.

*Status:* diagnosed, worked around manually, not fixed in the installer.

---

**F-10 · [LOW] · `docker compose up -d` without `--build` fails with "pull access denied"**

*What happened:* Running compose by hand without `--build` tries to *pull* the 7 locally-built images
and fails with `pull access denied`, which reads like an auth problem rather than a missing local build.

*Note:* `install.sh` gets this right (it uses `--build`). This only bites someone running compose
manually — but that is a very common thing to do while debugging.

*Status:* diagnosed; installer already correct; a README note or a clearer error would help.

---

## 2b. Confirmed WORKING on Windows (verified end-to-end by the tester)

This matters as much as the bug list — it establishes that the core product runs on Windows.

- **Full inference round-trip:** `gemma4:12b` replied `HARVIS INFERENCE OK` through
  nginx → backend → socat forwarder → native Ollama.
- **Auth:** login returns 200 + a valid JWT; all follow-up API calls 200.
- **Model switching** across all 8 native models; picker populated from the host Ollama.
- **Artifacts**, **document worker**, **browser-runner**.
- **OpenClaw gateway** running with 7 plugins loaded *(note: on this box the config tree exists from
  prior manual work — see F-04, which blocks this on a genuinely fresh clone).*

**Not built in this run** (opt-in services): `opencode`, `codex`, `claude-code`, `hermes-agent`,
`cad-engine`, `open-notebook-ui`, `tts-service`, `harvis-mcp`, `harvis-messaging-gateway`.

**Still untested:** the `HARVIS_SETUP_CODE` first-admin flow — the carried-over database meant
`needs_setup` was already `false`, so the real out-of-box path never ran. **This remains the single
most important unexercised path**, and it is the feature today's work was built around. Exercising it
requires wiping only `harvis_pgsql_data` (which preserves the ~8 GB model cache).

**Install time:** core services ≈ **9 minutes**, backend the long pole (PyTorch/CUDA). This measurement
predates the `.dockerignore` fix in F-03 — the post-fix number is still outstanding.

---

## 2c. The five manual fixes required to reach a working stack

**This list is the honest measure of the out-of-box gap.** The stack works on Windows — login verified,
`gemma4:12b` round-tripped a real chat — but reaching that state took five interventions, **none of
which a normal user would find**:

1. **Seeded the missing `openclaw/config/` tree by hand** (F-04).
2. **Cleaned the same broken shape out of the `openclaw-data` volume.** *Second-order effect worth
   knowing:* once Docker has created empty directories where the config files should be, the pollution
   is **persisted in the named volume**. Fixing the repo alone is therefore not enough for anyone who
   already ran a broken start — the volume has to be cleaned too, or `docker compose down -v` run.
   Any fix for F-04 must account for already-poisoned volumes, not just fresh clones.
3. **Applied 3 migrations that nothing runs automatically** (F-08).
4. **Added `pull_policy: build` to 7 services** — the durable fix for F-10. Without it, a manual
   `docker compose up -d` tries to *pull* locally-built images and fails with `pull access denied`,
   which reads like an auth error rather than "these are built locally."
5. **Flipped `HARVIS_OWUI_ENABLE_SIGNUP=true`** to get past the double lockout (F-05). **This is a
   local test setting and must be reverted before that instance faces a network.**

**Verdict on "does one command work out of the box": still no.** What today produced is not a working
install so much as a *specific, ranked list of what is in the way* — and **three of the top four
blockers are not Windows problems at all.** They would break a fresh clone on Linux identically.

## 2d. Session end state (Windows box, 2026-07-20 → handoff dated 2026-07-21)

- **Build of the remaining 9 services** got ~4 minutes in (pulling torch/CUDA wheels, incl. a 664 MB
  cuDNN wheel) before the session ended. It dies on shutdown; **BuildKit resumes from cache**, so the
  work is not lost.
- **Handoff written** on the Windows/WSL box at `HANDOFF-2026-07-21.md` (rewritten rather than appended,
  so it reads as an actionable state document rather than a diary).
- **Build loop script** at `/tmp/build_rest.sh` — `/tmp` may clear on reboot; the handoff carries the
  loop inline so it can be recreated.

**Tomorrow's order, per that handoff:**
1. Confirm **native Ollama is running first**, then `docker compose ps` (the stack self-starts via
   `restart: unless-stopped`).
2. Re-run the build loop and triage the scoreboard.
3. **Do the clean-slate `./install.sh` run** — the actual measurement of the out-of-box claim.

**Two traps flagged for tomorrow:**
- **Native Ollama must be running before anything else.** If it is not, every service still starts and
  *looks* healthy, but there is no inference — and it presents as a Harvis bug rather than a missing
  Windows process.
- **The post-login 404 is not a failure** (F-06). Auth succeeds; navigate to `/` manually. This one
  cost hours today.

## 2e. The single highest-value next fix

**Make `openclaw/config/` ship with the repository** (F-04). Nothing else matters until it is done —
every other bug is downstream of "the stack will not start." Two viable routes: force-add a sanitized
template tree past `.gitignore` (`git add -f`), or have `install.sh` generate the files. Committing a
template is simpler and self-documenting; generating it is better if the files carry instance identity.
**Whichever is chosen must also handle the poisoned-volume case from §2c item 2.**

Runner-up, once that lands: **the clean-slate run** — fresh clone, `./install.sh`, touch nothing. That
converts this document from one tester's findings into a verified bug list, and gives an honest number
for how close the one-command claim actually is.

---

## 2f. Round 2 (2026-07-22) — deeper Windows pass, net-new discoveries

A second, fuller manual test pass on the Windows rig (RTX 5080) got the whole stack up (8 of 9 optional
services built) and tested features, not just install. **The actionable, root-caused fix list is
`docs/reports/ISSUES-FOR-FIX-2026-07-22.md`** — 15 issues with `file:line` evidence. Only the
*net-new* discoveries beyond F-01…F-10 are summarised here:

- **A SECOND OpenClaw P0 — pairing is a VERSION MISMATCH (ISSUES #1).** Distinct from F-04 (config not
  shipping). Even with the config present, workspace + build stay dead: the backend correctly requests
  `role: operator` + `operator.admin`, which *should* trigger OpenClaw's `skipPairingForOperatorSharedAuth`
  auto-bypass, but the pinned **`openclaw v2026.5.22` does not honor it** (gateway logs `v2026.7.1-2`
  available). Fix = bump the version in `openclaw-browser/Dockerfile`, rebuild, retest. **This is now the
  keystone: it blocks both workspace and build, the two features flagged most important.**
- **Windows host-prep, none of it documented in the repo:** move Docker's disk to a drive with 50 GB+
  (C: had 32 GB), `.wslconfig` `memory=24GB` + a *full* reboot (WSL defaults to 50% RAM ≈ 15.5 GB, too
  tight for 25 services), clone into WSL's own filesystem not `/mnt/c` (9p is brutal for node_modules/pip),
  `git config core.autocrlf input`. → these belong in a `WINDOWS-BRINGUP.md`.
- **Image generation has NO backend wired (ISSUES #3).** The code exists (`python_back_end/image/`) but
  is not a running service; the flag only enables the UI path, so "on" makes the model *hallucinate* a
  DALL-E action — worse than an honest "disabled." Corrects the earlier assumption that image-gen was
  simply "off."
- **Web search returns 0 sources — SearXNG isn't running (ISSUES #5).** `researcher.py:169` expects
  SearXNG; no such service in compose.
- **llmfit never starts → "device offline"; and "rig" is a hardcoded example node** at
  `cookbook/config.py:41` (ISSUES #6). Both look like bugs; one is a missing service, one is seed data.
- **open-notebook-ui build FAILS** (`/onb` 502) — missing `use-credentials.ts` import (ISSUES #7).
- **Deep-research + workspace-detector default to `llama3.1:8b`**, which isn't pulled, and the frontend
  never sends the selected model (ISSUES #2, #4). A whole class of "hardcoded model default that isn't
  installed."
- **GitHub OAuth 500s instead of failing gracefully** when `GITHUB_CLIENT_ID` is empty (ISSUES #12).

**Reframed verdict:** `install.sh` gets you to a **crashloop, not a working stack**, because of F-04.
Fixing F-04 + the migration runner + `pull_policy` + the post-login redirect is *"an afternoon, not a
rewrite"* — after which the honest claim becomes "clone, `./install.sh`, wait ~10 minutes." The keystone
for *features* (not just startup) is the OpenClaw version bump.

---

## 3. Watch-list — PREDICTIONS, not findings

These are the Windows-specific failure modes most likely to bite, derived from how `install.sh` and
the compose stack are actually written. **None of these has been observed.** Each is listed with the
concrete symptom to look for, so we can confirm or dismiss it fast.

### 3.1 CRLF line endings break the bash script — *highest-probability issue*
`install.sh` is a bash script. If git checked it out with Windows line endings (`core.autocrlf=true`,
the Docker Desktop / Git-for-Windows default), every line ends with `\r` and bash fails with confusing
errors like `$'\r': command not found`, `syntax error near unexpected token`, or a shebang failure.
**Symptom:** nonsense syntax errors on a script that is known-good on Linux.
**Check:** `file install.sh` (should say "ASCII text", not "with CRLF line terminators").
**Fix:** `git config core.autocrlf input` and re-clone, or `dos2unix install.sh`.
**Durable fix if confirmed:** add a `.gitattributes` with `*.sh text eol=lf`.

### 3.2 `install.sh` needs a real bash — Docker Desktop alone does not provide one
The installer is bash-only. PowerShell and `cmd` cannot run it.
**Expected requirement:** Git Bash or a WSL shell.
**Open question this test answers:** is Git Bash sufficient, or does it need WSL? This determines what
the README must tell Windows users, and it is currently undocumented.

### 3.3 `openssl` for secret generation
`install.sh` generates `JWT_SECRET`, `FERNET_KEY`, `HARVIS_SETUP_CODE`, and `OPENCLAW_GATEWAY_TOKEN`
via `openssl rand`, with a `/dev/urandom` fallback.
**Symptom if missing:** empty or malformed secrets in `.env`; the stack then fails closed on
`JWT_SECRET` (which is `${JWT_SECRET:?}` — it aborts loudly, by design).
**Note:** Git Bash ships openssl; a bare WSL install may not.

### 3.4 GPU detection
`install.sh` detects NVIDIA via `nvidia-smi` and AMD via `/dev/kfd` / `rocminfo`.
- `/dev/kfd` **will not exist** on Windows → AMD is effectively undetectable; expect a CPU recommendation.
- NVIDIA through Docker Desktop requires the WSL2 backend with GPU support; `nvidia-smi` may or may
  not be on PATH in the shell running the installer.
**Watch:** whether the recommended profile matches the actual hardware, and whether the chosen
profile's containers actually start.

### 3.5 Port collisions
The stack publishes ~11 host ports (9000 nginx, 5432 postgres, 11434 ollama, 8000 backend, others).
Windows reserves dynamic port ranges (`netsh int ipv4 show excludedportrange`) and other software may
hold 5432 or 9000.
**The installer's port preflight uses `/dev/tcp`,** a bash feature — confirm it works in the chosen shell.

### 3.6 The `!reset` compose gate
The CPU and AMD profiles rely on `devices: !reset []` to clear the base file's NVIDIA reservations;
this needs Compose ≥ 2.19. Docker Desktop bundles its own Compose.
**Good news:** the installer's gate is *behavioral* — it renders the merged config and asserts zero
NVIDIA reservations — so it should catch this regardless of version numbering. **This test is the
first real exercise of that gate on a foreign Compose build.**

### 3.7 Bind-mount path translation
The compose file bind-mounts host paths (`./python_back_end/main.py:/app/main.py:ro`, `/var/run/docker.sock`,
`/tmp`). Docker Desktop translates Windows paths, but `/var/run/docker.sock` and `/tmp` are Unix paths.
**Watch:** services that mount the Docker socket (the sandbox/terminal lane) and anything mounting `/tmp`.

### 3.8 `owui/build` is gitignored and must be generated
The frontend build output is deliberately not committed. A clean clone will not have it.
**Watch:** whether the compose build step produces it, or whether nginx serves nothing / 404s.
**This is a known open question from the weekly report**, not a Windows-specific issue — but Windows
is where it gets answered first.

### 3.9 Fresh-volume database bootstrap
The fix in `ca7a8070` addresses an init failure that was argued **statically and never reproduced**.
A genuinely fresh Windows volume is the first true test of it.
**Watch:** `docker logs` on the postgres container for an `ON_ERROR_STOP` abort, and whether the
`users` table exists afterwards.

### 3.10 The setup-code handoff
After a healthy start, `install.sh` should print the URL and a one-time setup code, then `/setup`
should accept it and create the first admin.
**This is the whole point of the feature** and has never been exercised end-to-end by a real user.
The parse bug behind it was only fixed today (`2527a0cd`).

---

## 4. Confirmed working (moved here once observed)

*(nothing confirmed yet)*

---

## 5. Follow-ups generated by this test

*(to fill in — durable fixes, README additions, `.gitattributes`, etc.)*
