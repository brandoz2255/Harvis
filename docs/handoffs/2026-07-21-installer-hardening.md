# Handoff — 2026-07-21: installer hardening (Phase 7)

**Tomorrow's job:** make `./install.sh` good enough that a stranger can clone Harvis and get a
working stack, on nvidia / amd / cpu, without reading the source.

**You said you have files for this** — bring them first. This document is the *gap list* the
installer has to close; your files may already cover several. Reconcile before writing code.

**Do not push.** Standing rule: no push until you verify E2E, then ask. Phase 6 (push to a
separate remote branch) stays last.

---

## Where things stand

`install.sh` is **107 lines** and already does the hard structural part correctly:

| Covered | Detail |
|---|---|
| Prereq check | docker + compose v2, exits with a clear message |
| Backend detect | `nvidia-smi` → nvidia, `/dev/kfd`\|`rocminfo` → amd, else cpu |
| macOS note | explains Docker can't reach the Mac GPU, points at native Ollama |
| Backend → compose map | writes `COMPOSE_FILE` so plain `docker compose up` works afterwards |
| JWT_SECRET | generates via `openssl rand -hex 32`, `/dev/urandom` fallback |
| Idempotent | re-runnable, preserves existing `.env` values, `--backend X --yes` for CI |
| Network | creates `ollama-n8n-network` if absent |

`docker-compose.amd.yml` and `docker-compose.cpu.yml` both exist.

> ### ⚠️ CORRECTION (2026-07-20) — the claim below was WRONG, then settled empirically
>
> This document originally asserted: *"Database init is already handled — six schema files mount into
> `docker-entrypoint-initdb.d`, so Postgres self-initialises on first boot. That is not a gap; I checked
> before listing it as one."*
>
> **That was inference from seeing the mounts, not a test, and it was stated as fact.** A later recon
> found that two of those mounted files FK-reference a `users` table which **nothing in the mount set
> created** (`001_add_document_jobs.sql:9-11`, `artifacts_schema.sql:9`), and that `init-db.sh`'s
> pgvector extension sorted **last** alphabetically.
>
> **Empirical result (throwaway container, 2026-07-20):** a fresh volume **did abort** —
> `Exited (3)` with `relation "users" does not exist` while applying `001_add_document_jobs.sql`.
>
> **Fix shipped** (`ca7a8070`): mount `000_extensions.sql` + `all_schemas_safe.sql` as
> `000_schemas.sql` (sorts before `001_…`), and apply `all_schemas_safe.sql` idempotently from the
> backend startup-ensure block so existing volumes self-heal too. Verified: throwaway comes up with
> `users` / `chat_sessions` / `chat_messages` present.
>
> The lesson worth keeping: *"I checked"* meant "I looked at the mounts", which is not the same as
> running it.

So this is a **hardening pass on working code**, not a rewrite.

---

## The five gaps (verified 2026-07-20; status updated after hardening)

### 1. 🔴 ~~`COMPOSE_FILE` silently disables `docker-compose.override.yml`~~ — ✅ fixed in `install.sh`

Compose auto-loads `docker-compose.override.yml` **only when `COMPOSE_FILE` is unset**. The moment
`install.sh` writes `COMPOSE_FILE=docker-compose.yaml`, the override stops applying.

**Proven** in an isolated scratch dir (not inferred from docs):

```
A) COMPOSE_FILE unset          → BASE: "yes"   OVERRIDE_APPLIED: "yes"
B) COMPOSE_FILE=docker-compose.yaml → BASE: "yes"        (override silently dropped)
```

**Why this bites you personally.** Your `docker-compose.override.yml` is gitignored and carries two
things you rely on:
- `openclaw` bundled → **byo**, backend routed to `ws://host.docker.internal:18790` (your host
  install at `~/.openclaw`)
- **8 GB GPU tuning** for Ollama — flash attention, `q8_0` KV cache, `NUM_PARALLEL=1`,
  `MAX_LOADED_MODELS=1`, 512 MB GPU overhead

Running `./install.sh` on this dev box **turns all of that off**, with no message. Your host OpenClaw
would go quiet and Ollama would silently lose its 8 GB tuning — and the symptom (slow/OOM inference,
dead OpenClaw) looks nothing like the cause.

**Fix (shipped):** append `:docker-compose.override.yml` to `COMPOSE_FILE` when the file exists, and
print "including your local override".

---

### 2. 🔴 ~~`FERNET_KEY` is never generated~~ — ✅ fixed in `install.sh`

`docker-compose.yaml` defaults it to **empty** (`${FERNET_KEY:-}`). The backend's response
(`vibecoding/auth_github.py:51`):

```python
logger.warning("⚠️ FERNET_KEY not set - GitHub OAuth will not work")
```

A log line nobody reads. GitHub connect then fails in a way that looks like a broken button.

This directly undercuts the **locked** "Web Harvis = GitHub-first" decision — the primary repo path
is off by default on every fresh install.

**Fix (shipped):** generate url-safe base64 Fernet key alongside JWT (preserve-if-present).

Worth a follow-up (not tomorrow): that warning should surface in the UI's GitHub panel, not just
logs. Same honesty principle as the Recon #2 work — a disabled integration should say it's disabled.

---

### 3. 🟠 ~~No root `.env.example`~~ — ✅ added at repo root

`.env.example` exists for `front_end/owui/` and `python_back_end/`, but **not at the repo root** —
which is the one Compose actually reads. A fresh clone gets no template, so the ~99 optional vars
are invisible unless you read `docker-compose.yaml`.

`.env` itself is correctly gitignored (`.gitignore:14`).

**Fix (shipped):** root `.env.example` — commented, secrets blank, grouped by concern.

---

### 4. 🟠 ~~No model pull~~ — ✅ skippable offer in `install.sh`

`install.sh` never pulls an Ollama model, and nothing else does either. A fresh install brings up a
healthy-looking stack whose first message fails, because Ollama has no models.

**Fix (shipped):** after a healthy stack, if Ollama has zero models, offer to pull
`llama3.2:3b` (~2 GB approx; override via `HARVIS_DEFAULT_OLLAMA_MODEL`). Skippable; `--yes` does
**not** auto-download (prints the manual command instead).

Note the k8s DNS caveat if relevant: `K8S_DNS_WORKAROUND.md` documents `registry.ollama.ai` being
blocked on the campus network. Docker installs are unaffected, but the failure is confusing if hit.

---

### 5. 🟡 ~~No post-up verification~~ — ✅ fixed (`poll_health`)

It prints `✓ Harvis is starting → http://localhost:9000` and exits. That `✓` is a **claim, not an
observation** — it prints identically whether the stack came up or crashed on boot.

That's precisely the failure mode the whole Recon #2 pass was about, sitting in the first thing a new
user runs.

**Fix (shipped):** poll `/api/health/services` for ~180s; print per-service table; exit 1 on failure;
print setup code only when `needs_setup` is true.

---

## Also noted, decide but probably don't fix tomorrow

- **`HARVIS_HERMES_API_SERVER_KEY` defaults to the hardcoded string `harvis-hermes-local-dev`.**
  Fine on a laptop, a shared default secret if ever exposed. Real fix belongs with **T2**
  (fresh-install hardening), which is still open — not the installer.
- **`OPENCLAW_GATEWAY_TOKEN` is the only bare `${VAR}`** with no default in the whole compose file.
  Falls back through `OPENCLAW_GATEWAY_TOKEN_BUNDLED`, so it may be intentional — **check before
  changing.**
- **`JWT_SECRET` uses `${JWT_SECRET:?...}`** — fails loudly with a clear message if unset. This is
  the pattern the other secrets should follow. Leave it alone; copy it.

**Env surface, measured:** 101 vars referenced by `docker-compose.yaml`; **94 have defaults**. The
config burden is genuinely small — which is why a root `.env.example` is cheap and high-value.

---

## Suggested order

1. Reconcile **your files** against gaps 1-5 — some may already be solved.
2. Gap 1 (override) — one line, and it's actively mis-serving you right now.
3. Gap 2 (FERNET_KEY) — generator already exists.
4. Gap 3 (root `.env.example`) — mechanical, unblocks documentation.
5. Gap 4 + 5 (model pull, health check) — the "does it actually work" pass.
6. **Test all three backends.** `cpu` is testable here; `amd` likely needs a real ROCm box — if you
   can't test it, say so in the README rather than implying it's verified.

## Then

**Phase 5** — your hands-on 3-theme deploy pass. Genuinely yours: I can't judge skeletons or splash
timing from code, and the mascot episode is a concrete reminder that measurement missed what your
eye caught immediately.

**Phase 6** — push to a **separate remote branch**, not `origin/harvis1.1`. Currently **28 commits
and ~135 dirty files** exist only on this disk.

---

## Context you'll want

- Roadmap: `docs/plans/2026-07-18-plan-of-action.md` — the checklist (Phase 3 mascot now ✅, Phase 8
  website unblocked by it)
- Still open from the security order: **T2** (fresh-install signup/admin) · T3 (hide Share) ·
  T4 (Clone chat) · T5 (hide `/workspace` + `/admin` behind reversible flags). T1 shipped as `3c8616b2`.
- Mascot: shipped `3c7917da`, deploys on the next push. Eyeball it at 96px when the app is up.
- Standing rules: one commit per task · backend auth tests + frontend build after each change ·
  never commit secrets · gate UI behind a flippable const rather than deleting it.
