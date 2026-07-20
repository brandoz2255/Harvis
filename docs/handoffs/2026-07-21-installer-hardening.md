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

`docker-compose.amd.yml` and `docker-compose.cpu.yml` both exist. **Database init is already
handled** — six schema files mount into `docker-entrypoint-initdb.d` in `docker-compose.yaml:583-588`,
so Postgres self-initialises on first boot. That is *not* a gap; I checked before listing it as one.

So this is a **hardening pass on working code**, not a rewrite.

---

## The five gaps (verified today, most severe first)

### 1. 🔴 `COMPOSE_FILE` silently disables `docker-compose.override.yml` — and yours is load-bearing

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

**Fix:** append `:docker-compose.override.yml` to `COMPOSE_FILE` when the file exists. It's already
last in precedence, so behaviour matches today's default for everyone else, and clean installs are
unaffected because they don't have the file.

```bash
[ -f docker-compose.override.yml ] && COMPOSE_FILE="${COMPOSE_FILE}:docker-compose.override.yml"
```

Then say so in the output — "including your local override" — so it's visible either way.

---

### 2. 🔴 `FERNET_KEY` is never generated → GitHub OAuth silently dead

`docker-compose.yaml` defaults it to **empty** (`${FERNET_KEY:-}`). The backend's response
(`vibecoding/auth_github.py:51`):

```python
logger.warning("⚠️ FERNET_KEY not set - GitHub OAuth will not work")
```

A log line nobody reads. GitHub connect then fails in a way that looks like a broken button.

This directly undercuts the **locked** "Web Harvis = GitHub-first" decision — the primary repo path
is off by default on every fresh install.

**`python_back_end/generate_fernet_key.py` already exists.** Generate it alongside `JWT_SECRET`,
same preserve-if-present pattern. Fernet needs a **32-byte url-safe base64** key, not hex — so
`openssl rand -base64 32 | tr '+/' '-_'`, or shell out to the existing script.

Worth a follow-up (not tomorrow): that warning should surface in the UI's GitHub panel, not just
logs. Same honesty principle as the Recon #2 work — a disabled integration should say it's disabled.

---

### 3. 🟠 No root `.env.example`

`.env.example` exists for `front_end/owui/` and `python_back_end/`, but **not at the repo root** —
which is the one Compose actually reads. A fresh clone gets no template, so the ~99 optional vars
are invisible unless you read `docker-compose.yaml`.

`.env` itself is correctly gitignored (`.gitignore:14`).

**Fix:** commit a root `.env.example` — commented, secrets blank, grouped by concern (core /
engines / integrations / Discord / OpenClaw). It doubles as the config documentation that doesn't
exist yet. **Blank placeholders only — never a real value.**

---

### 4. 🟠 No model pull → first chat fails on a clean box

`install.sh` never pulls an Ollama model, and nothing else does either. A fresh install brings up a
healthy-looking stack whose first message fails, because Ollama has no models.

**Fix:** after a successful `up`, offer to pull one small default. Sizing matters —
[[project_hardware_gpu]] notes this box is 8 GB, and a stranger's may be smaller. Pick a modest
default, name the download size before starting, and make it skippable.

Note the k8s DNS caveat if relevant: `K8S_DNS_WORKAROUND.md` documents `registry.ollama.ai` being
blocked on the campus network. Docker installs are unaffected, but the failure is confusing if hit.

---

### 5. 🟡 No post-up verification — the installer's own honesty gap

It prints `✓ Harvis is starting → http://localhost:9000` and exits. That `✓` is a **claim, not an
observation** — it prints identically whether the stack came up or crashed on boot.

That's precisely the failure mode the whole Recon #2 pass was about, sitting in the first thing a new
user runs.

**Fix:** poll `http://localhost:9000` for ~60s. Report what actually happened; on failure print the
`docker compose ps` line and the log command. Never claim success you didn't observe.

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
