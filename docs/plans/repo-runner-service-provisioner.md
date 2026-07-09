# Repo Runner — Trusted Service Provisioner (Phase C design)

Status: **DESIGN ONLY** — nothing in this document is built this pass. Phases A+B (polyglot
sandbox, runtime detection, requirement graph, honest capability check) ship first; this doc
specifies what Phase C adds so multi-service repos like `lfnovo/open-notebook` can be fully
OPENED, not just diagnosed.

## 1. Goal

Today the Adaptive Workspace Repo Runner runs single-process web apps (Node, and with Phase A,
Python) inside one sandbox container. Multi-service repos — an API plus a worker plus a frontend
plus a database — are detected and explained but not run. Phase C closes that gap by letting the
Harvis backend provision **trusted service sidecars** and supervise multiple app processes inside
one space.

The product rule stands: **Harvis should not pretend every repo is runnable, but it should
understand why it is or is not.** Phase C never lowers that bar — it raises `runnable_now` for
repos whose service needs are satisfiable from our own catalog, and keeps a truthful
`blocked_reason` for everything else.

## 2. The nine tools

| # | Tool | A+B delivers | C adds |
|---|------|--------------|--------|
| 1 | **Runtime Detector** — node/python/python+node, package manager | ✅ `fab_repo.detect_stack` → `requirements.runtime`, `package_manager` | — |
| 2 | **Service-Graph Detector** — processes + external services + env | ✅ `requirements.processes / services / env_required` | deeper compose/Procfile parsing as catalog grows |
| 3 | **Polyglot Sandbox** — Node 20 + Python 3.11 + uv + pip + git | ✅ single image | unchanged; C reuses it as the app container |
| 4 | **Run-Plan Builder** — install/build/start + `run_plan` | ✅ single-process plans | multi-process plans (ordered steps, per-process env) |
| 5 | **Honest Capability Checker** — `runnable_now` / `blocked_reason` | ✅ | consults the catalog: "blocked" becomes "runnable with provisioning" when every service maps to a catalog entry |
| 6 | **Trusted Service Catalog** | ❌ (Phase A only names it in `provision_note`) | ✅ Harvis-controlled image list + defaults |
| 7 | **Multi-Process Supervisor** | ❌ | ✅ backend-managed process group inside the sandbox |
| 8 | **Preview Router** | ✅ host-port-per-preview for one server | ✅ picks the *frontend* port among N processes; optional secondary ports |
| 9 | **Approval Bundle** | partial (gated setup/run) | ✅ one approval screen listing sidecars, processes, synthesized env before anything starts |

## 3. Architecture

**Per-space isolated network.** Each space gets its own Docker bridge network
(`harvis-space-<id>`, `internal: true` semantics for sidecars). The app sandbox and its sidecars
join it; nothing else does. Sidecars are never published to the host — only the preview port of
the frontend process is, via the existing host-port-per-preview scheme (dev server binds
`0.0.0.0:3000` in-container, published to `127.0.0.1:<port>`, iframe at its own origin). No
base/proxy/token indirection is reintroduced.

**Sidecars started by the backend, from the catalog only.** The Python backend (not the sandbox,
never the repo) launches sidecars using images from the Trusted Service Catalog. The repo's own
`docker-compose.yaml` is treated purely as a *detection input* — it is parsed to learn "this repo
wants SurrealDB", then discarded. The image actually run is ours.

**Env synthesis.** For each catalog entry the backend synthesizes the env the app expects:
generate a random `OPEN_NOTEBOOK_ENCRYPTION_KEY` (32 bytes, base64), set
`SURREAL_URL=ws://surrealdb:8000/rpc`, `SURREAL_USER/SURREAL_PASSWORD` to per-space random
credentials, write them into the sandbox's `.env`. Secrets are per-space, never logged, never
shown raw in the UI (masked in the approval bundle).

**Multi-process supervisor.** A small supervisor (backend-driven `docker exec` process group, or
a bundled `procman.py` inside the sandbox) starts the repo's processes in dependency order with
per-process logs streamed to the existing CLONE LOG panel: api → worker → frontend. Restart-once
on crash, then surface failure honestly.

**Health checks + cleanup.** Each sidecar has a catalog-defined health probe (SurrealDB:
`/health` on 8000). App processes get a TCP-port readiness check. "Stop" tears down every
process, every sidecar, and the per-space network — cleanup is one labeled sweep
(`label=harvis.space=<id>`), so nothing leaks.

## 4. Worked example: opening open-notebook

Recon: Python 3.11–3.12 + uv, FastAPI API (uvicorn), async `surreal-commands-worker`, Next.js
frontend, SurrealDB v2 on port 8000 (client/server, **not embeddable**), and
`OPEN_NOTEBOOK_ENCRYPTION_KEY` required in `.env`.

1. Clone → detect: `runtime=python+node`, `services=[surrealdb]`, `multi_service=true`; capability
   checker sees SurrealDB in the catalog → provisioning offer.
2. Approval bundle shown: 1 sidecar (surrealdb:v2.x from catalog), 3 processes, 5 synthesized env
   vars. User approves.
3. Backend creates the space network, starts the SurrealDB sidecar, waits for health.
4. Sandbox: `uv sync` (Python deps) and `npm ci` in `frontend/`.
5. Supervisor starts `uv run uvicorn api.main:app --host 0.0.0.0 --port 5055`, waits for the port,
   then `uv run surreal-commands-worker`, then `npm run dev` (Next on 0.0.0.0:3000).
6. Preview Router picks 3000 (frontend role), publishes to `127.0.0.1:<port>`, iframe opens.

## 5. Security rules (hard)

- **NEVER run the repo's docker-compose raw.** Compose files are detection input only.
- **No privileged containers.** No `--privileged`, no added capabilities, no docker socket.
- **No host bind-mounts** into sidecars or the sandbox beyond what the current sandbox already has.
- **No arbitrary or repo-chosen service images.** Catalog entries only, pinned digests.
- **Resource caps and isolation identical to the current sandbox** apply to every sidecar
  (memory/CPU limits, no host ports except the single preview publish).
- **The sandbox↔backend trust residual is unchanged** — sidecars add no new control path.

## 6. Trusted catalog

Launch with **SurrealDB v2** (image pinned, port 8000, health `/health`, per-space credentials).
Next candidates in order of repo demand: **Postgres** (incl. pgvector), **Redis**, **MinIO**
(S3-compatible). Each entry = pinned image digest, default env template, health probe, resource
cap, and the detection aliases that map to it (e.g. `surrealdb/surrealdb`, `pgvector/pgvector`,
`postgres:*` → postgres).

## 7. Staging + open questions

Staging: C1 catalog + SurrealDB sidecar + env synthesis → C2 multi-process supervisor + log
multiplexing → C3 preview router for multi-process + approval bundle UI → C4 additional catalog
entries.

Open questions:
- **Dependency→catalog mapping:** compose image strings are messy (`postgres:16-alpine`, custom
  forks). Alias table vs. heuristic matching; what do we do on no-match (honest block) vs.
  near-match (ask the user)?
- **Env-secret synthesis:** which var names do we recognize per framework, and how do we avoid
  clobbering a committed `.env.example` value the app actually needs verbatim?
- **Multi-port preview UX:** open-notebook exposes both an API (5055) and a UI (3000) — do we
  offer a port switcher in the preview header, or frontend-only?
- **Per-space resource budget:** N containers per space needs a ceiling (e.g. 1 sandbox + 2
  sidecars, shared memory cap) so one space can't starve the host — where is that enforced and
  surfaced?
