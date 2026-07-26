# Harvis modularization — capability packs, adapter boundaries, and a 3-container core

**Date:** 2026-07-25
**Branch:** `harvis1.1` (nothing implemented yet — this is the plan)
**Supersedes/extends:** `docs/plans/2026-07-22-*` (fresh-clone fixes), the 2026-07-23 Docker
footprint audit (measured, in Obsidian at `code/harvis/2026-07-23-docker-footprint-audit-and-opt-in-tiering`)
**Status:** DOCUMENTED, NOT STARTED. No code changes. Work order at the bottom.

---

## The goal in one sentence

Harvis should boot as a **small control plane** — nginx, backend, Postgres — and activate everything
else only when the user turns on a capability, adopting whatever the user already has (an existing
Ollama, an API key) instead of reinstalling it.

Target shape:

```
Harvis Core            nginx · backend · postgres
Optional runtime       Ollama (local) | Claude/OpenAI/Moonshot (external) | OpenClaw
Capability packs       Build · Browser · Notebooks · Voice · Messaging · Experimental
```

Ollama is **not** core. A user on Claude or Moonshot should not run or store a local inference
server.

---

## Part 1 — Verified findings

Everything below was checked against the `harvis1.1` tree on 2026-07-25, not inferred. The Windows
sweep that prompted this was mostly right; the corrections are marked.

### Service graph

| Finding | Evidence |
|---|---|
| 25 services, exactly one profile-gated (`harvis-messaging-gateway`) | `docker-compose.yaml` |
| `backend` hard-depends on `openclaw` + `browser-runner` | `depends_on` — optional services in the boot path |
| `nginx` hard-depends on `frontend` | same |
| `backend` has **no memory limit** — the only always-on torch process without one | ollama 30G, openclaw 4G, frontend 1512M, pgsql 512M, nginx 64M |
| `llmfit` reserves a **full GPU** (`count: 1` + `NVIDIA_VISIBLE_DEVICES=all`) to be a hardware scanner | contends with ollama/tts/backend on a single-GPU box |
| GPU is touched by 4 services | `ollama`, `backend` (`runtime: nvidia`), `tts-service`, `llmfit` |
| 8 services carry `pull_policy: build` | the local-tag ones; correct as-is |

### The `frontend` service is dead weight — stronger than reported

- 1512 MB limit, full Next.js build, sits in `nginx`'s `depends_on`.
- `nginx.conf` routes **exactly one** location to it: `/api/ai-chat` (line 271).
- **Nothing in `front_end/owui/src` or `python_back_end` calls `/api/ai-chat`.** Zero references.

So a whole service is built, started, and depended upon to serve one route no client requests.

### Migrations — six never run, not one

`main.py` applies a hardcoded list (`010`–`015`, plus the podcast trio `005`–`007` added 2026-07-25).
`run_migrations.py` exists and **nothing invokes it**.

| Migration | Runs at boot? | In `all_schemas_safe.sql`? | Code references |
|---|---|---|---|
| `000_extensions.sql` | initdb mount only (fresh volumes) | — | — |
| `001_create_vibe_sessions.sql` | **no** | no | 4 files |
| `002_create_user_prefs.sql` | **no** | no | created at runtime in `main.py` (covered) |
| `008` / `009` (rvc_voice_models) | **no** | no | **zero** — dead |
| `add_ide_chat_tables.sql` | **no** | no | **zero** — dead |

### `vibecoding_sessions` does not exist on *any* deploy

Including this working dev box. `vibecoding/sessions.py` is mounted at `/api/vibecode/sessions`
(`main.py:1467`) and every query in it targets that missing table. Live Build uses `agent_runs`
instead. Its schema file `vibecoding_sessions_schema.sql` has no invoker — `init_vibecode_db.py` is
imported by nothing.

**This is mounted dead code exposing routes that can only fail.** Not a fresh-clone blocker.

### Installer

- `install.sh` **does** offer a chat-model pull (`offer_model_pull`, line 393, `llama3.2:3b`).
  Earlier reports said it didn't. *(correction)*
- `--yes` explicitly **skips** the pull (line 331) → unattended install reports healthy, first chat fails.
- **No embedding model is ever pulled.** `nomic-embed-text` appears nowhere. This is exactly what
  broke notebooks on the rig.
- It does not detect or adopt an existing host Ollama.

### Footprint — read the *unique* column, not the total

The 07-23 audit already measured this with `docker system df -v`, and the shared-layer caveat is
real: `backend`, `model-downloader`, and `harvis-mcp` share one 16.9 GB ML base counted **once**.
Adding their displayed sizes triple-counts it.

What actually reclaims space:

| Item | Size | Note |
|---|---|---|
| **Build cache** | 237.5 GB total, **149.2 GB reclaimable** | dwarfs every image discussion |
| Local volumes | 102.3 GB (494 volumes, 33 active) | needs a careful audit — user data lives here |
| `tts-service` | 20.3 GB, **32 bytes shared** | a second complete PyTorch stack |
| `comfyui-nvidia-docker` | 18.7 GB unique | image-gen, not wired up |
| ML base (backend + downloader + mcp) | 16.9 GB **once** | correctly shared |

The single biggest disk win available today is `docker builder prune`, not any code change.

### UI

- `default_prompt_suggestions: []` — `owui_compat/config.py:51`. Blank chat grid on first run.
- `+error.svelte` is 274 bytes: status + message, no way back.
- `/home` is a 0-byte `+page.svelte` (with a layout) — an orphan route.
- SSH is a 501 stub (`remote/ssh_manager.py`), honestly labeled but still navigable.
- NVIDIA is per-user for chat (`user_api_keys.provider_name`) but **env-only for Build**
  (`workspace_router.py`, `model_proxy.py` read `os.getenv`).

---

## Part 2 — Target architecture

### Adapter boundaries, not service dependencies

The prerequisite for everything else. Today the backend depends on *containers*; it should depend on
*interfaces* that report availability.

```
Backend
├── Model adapter    → ollama | claude | openai | moonshot | custom OpenAI-compatible
├── OpenClaw adapter → available / unavailable
└── Browser adapter  → available / unavailable
```

A disabled capability returns a structured answer, never a 500 and never a boot failure:

```json
{
  "available": false,
  "reason": "browser capability is not installed",
  "setup_action": "/settings/modules/browser"
}
```

**Do this before profile-gating** — profiles can't shrink anything while optional services sit in
`depends_on`.

### Capability packs, not 20 container toggles

A user enables **Voice**, not four containers.

| Capability | Services | Models |
|---|---|---|
| Core | nginx, backend, pgsql | — |
| Local AI | ollama, model-downloader | 1 chat model |
| Build | selected coding engine + sandbox | engine-dependent |
| Browser | browser-runner | — |
| OpenClaw | openclaw, openclaw-db-init | — |
| Notebooks | open-notebook, surrealdb, open-notebook-ui | **embedding model (required)** |
| Voice | tts-service (+ RVC assets) | TTS/STT weights |
| Messaging | harvis-messaging-gateway | — |
| Experimental | Agent Studio, Neural Map, SSH | — |

**Limitation to respect:** compose profiles only reduce *boot*. They reduce *disk* only if the
installer also builds and pulls selectively:

```
resolve enabled modules → resolve their services → build only those
                        → pull only their models → start only those
```

### Module registry (the long-term target)

One declaration drives service selection, migrations, model installation, route registration,
navigation, health, and uninstall:

```yaml
id: notebooks
name: Research Notebooks
stability: beta
services: [open-notebook, surrealdb, open-notebook-ui]
dependencies: [core]
models:
  - role: embedding
    model: nomic-embed-text
    required: true
migrations: migrations/optional/notebooks
routes: [/notebooks, /onb, /onb-api]
resource_estimate: {disk_gb: 12, memory_gb: 4, gpu: optional}
```

### Migration runner — ledger, not glob

A blind glob would create tables for dead features (rvc, ide_chat). Restructure:

```
migrations/
├── active/          core, always applied
├── optional/{voice,notebooks,legacy-vibecode}/   applied when the module is enabled
└── retired/         dead, never applied
```

The runner keeps a ledger (`migration_id`, `module`, `checksum`, `applied_at`, `status`) and takes a
DB advisory lock so two backends can't migrate concurrently. `000_extensions` becomes a normal
idempotent migration so existing volumes heal.

### Surface states, not scattered `if WIP`

Each surface reports one of: `available` · `disabled` · `not installed` · `experimental` ·
`unavailable on this hardware` · `installed but unhealthy`. Navigation renders from that, and the
backend **conditionally registers routes** — a disabled feature exposes no endpoints. This is the
right home for `/api/vibecode/sessions`, SSH, Agent Studio, Neural Map.

### Adopt what the user already has

The installer's preflight should detect and reuse an existing Ollama rather than shipping a second one:

```
Checking Ollama........................ Found
Endpoint............................... http://host.docker.internal:11434
Installed models....................... llama3.2:3b
Container→host reachability............ OK
```

That last check matters — Ollama working in the host terminal does not mean a container can reach it.
Recorded as:

```yaml
model_provider:
  type: ollama
  managed: false        # Harvis may use it; must never stop it or delete its models
  endpoint: http://host.docker.internal:11434
  default_chat_model: llama3.2:3b
```

Result for that user: **3 containers**, no `harvis-ollama` build, no `model-downloader` run, no
duplicate `llama3.2:3b` download.

### `harvis doctor`

```
Database schema    Healthy      Embedding model  Missing
Selected model     Healthy      Browser runner   Disabled
GPU memory         7.2/12 GB    OpenClaw         Unreachable
Docker disk        94 GB        Build cache      149 GB reclaimable
```

Actions: repair migrations · pull missing models · restart module · view logs · disable module ·
**`cleanup --dry-run`**. Cleanup must distinguish unused images / build cache / stopped containers /
unused volumes / Ollama models from **databases, notebooks, and user workspaces, which are never
disposable.**

---

## Part 3 — Work order

### Batch 1 — structural (unblocks everything else)

1. Remove `backend`'s `depends_on` on `openclaw` + `browser-runner`; add availability adapters.
2. Remove `nginx`'s `depends_on` on `frontend`.
3. Put `frontend` behind a `legacy` profile **and log `/api/ai-chat` hits** for one release, then delete.
4. Stop `llmfit` reserving a GPU — one-shot at setup, persist the hardware profile, re-scan on change.
5. Cap `backend` memory from measured peak.
6. Conditionally unregister `/api/vibecode/sessions` and the WIP surfaces.

### Batch 2 — capability system

7. Define the capability bundles above.
8. Installer builds/pulls/starts only selected bundles.
9. Model manifests per module; deterministic `--yes` presets
   (`--preset local-small` | `--preset external-models` | `--modules core,notebooks`).
10. Make Ollama optional; detect and adopt an existing one.
11. Per-module route, migration, and health registration.

### Batch 3 — reliability & polish

12. Ledger-backed migration runner.
13. Retire or relocate dead migrations (rvc, ide_chat, legacy vibecode).
14. Pull the embedding model as part of the Notebooks bundle.
15. Starter prompts + error-page navigation.

### Image work (parallel, independent)

16. `docker builder prune` — 149 GB, no code change.
17. Audit whether `tts-service` can share the ML base (currently 32 bytes shared).
18. One shared Harvis Python base; multi-stage builds; `model-downloader` should not be a copy of
    the full 16.9 GB backend environment.

### Validation

Clean installs of: **core only** · **core + external provider** · **core + Ollama** ·
**core + Ollama + notebooks** · **full**.

---

## Sequencing note

The Windows sweep's items 1–3 and 8 (migrations, embedder pull, memory cap, starter prompts) are
real but are **reliability and polish** — they will not shrink Harvis. The size and modularity win
comes from correcting the service graph (batch 1) and capability packaging (batch 2). Batch 1 items
2, 4, and 5 are the cheapest with the highest leverage and carry no design decisions.

**Open decision for the user:** whether `frontend` is deleted outright or profiled for one
transition release. Everything else in batch 1 is mechanical.
