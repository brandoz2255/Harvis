# E4B.0 — Full Hermes Agent Runtime Integration: feasibility report (2026-06-28)

**Branch:** `harvis1.1` · **Method:** 3-agent recon (filesystem + git + docker + upstream web) **then live empirical smoke** on this box · **Scope:** prove the REAL NousResearch Hermes Agent *application* (not an Ollama model) can be driven by Harvis to edit a clone + produce a diff.

## VERDICT: **A — Feasible now (empirically verified).**

The real Hermes Agent app is present, runs headless on local Ollama with **no cloud key**, **edited a file in a throwaway git clone using its own tools**, and the **git diff captured it** — on the **first try with a 4B model** (Hermes's own tool-calling middleware made the small model reliable where Harvis's native runner was flaky). Its OpenAI-compatible API server also starts and serves `/health` + `/v1/models`. The earlier "no gateway / single-session CLI" conclusion was wrong — it read a verification report pinned to an **April snapshot that predates the API server**.

---

## What was EMPIRICALLY proven on this box (not paper)

| E4B.0 step | Result | Evidence |
|---|---|---|
| App obtainable & runnable | ✅ | `hermes` CLI v0.11.0 installed (`~/.local/bin/hermes`); source at `~/.hermes/hermes-agent/`; image `dulc3/hermes:v0.11.5` pullable; official `nousresearch/hermes-agent` (calver tags). |
| Headless, no setup wizard | ✅ | fresh throwaway `HERMES_HOME` → `hermes status` runs clean, no secrets, provider Auto. |
| Local Ollama provider, **no cloud key** | ✅ | `config set model.provider=custom · base_url=http://localhost:11434/v1 · default=qwen3:4b`. |
| **Full app runtime edits a mounted clone** | ✅ | `cd <clone> && hermes -z "create hello.py = print('hi')" --yolo` → Hermes tool output **"File hello.py created successfully (11 bytes written)"**; `cat hello.py` = `print("hi")`. |
| **Diff captured via existing Harvis path** | ✅ | `git diff --cached --stat` → `hello.py | 1 +  1 file changed, 1 insertion(+)`. |
| Workspace control | ✅ | `-z`/`-w` operate in **CWD** ("AGENTS.md in the CWD loaded as normal"); `-w` = isolated git worktree. |
| OpenAI-compatible API server starts | ✅ | `API_SERVER_ENABLED=true hermes gateway run` → `/health` `{"status":"ok","platform":"hermes-agent"}`; `/v1/models` (Bearer) → `hermes-agent`. Port 8642. |
| Security (throwaway) | ✅ | isolated `HERMES_HOME`, no `.env`/keys written, file ops scoped to CWD; never touched the real `~/.hermes`. |

---

## The Hermes Agent app — confirmed facts

- **It is the real app**, not a model: terminal/file/web tools, persistent memory (SQLite FTS5 + 8 pluggable providers), Skills, MCP, plugins (16 hooks), cron/Jobs, sub-agents, SOUL.md identity, profiles. MIT license. Entry points: `hermes` (CLI), `hermes-agent` (`run_agent:main`), `hermes-acp` (editor ACP).
- **OpenAI-compatible API server** (`gateway/platforms/api_server.py`, port 8642, gated by `API_SERVER_ENABLED=true` [+ `API_SERVER_KEY`]): `POST /v1/chat/completions`, `POST /v1/responses`, **Runs API** (`POST /v1/runs`, `GET /v1/runs/{id}`, **`GET /v1/runs/{id}/events`** SSE, **`POST /v1/runs/{id}/stop`**), `/v1/models`, `/v1/capabilities`, `/health`. Streams `event: hermes.tool.progress`. Documented as "connect a frontend (Open WebUI etc.) to Hermes as a backend."
- **Provider = local Ollama, zero cloud key** (`provider=custom`, `base_url=…:11434/v1`). Cloud providers (OpenAI/Anthropic/OpenRouter/Kimi/…) are optional drop-ins with their own key.
- **Profiles / memory are PER-PROFILE** (a profile = a separate `HERMES_HOME`). Single-OS-user, multi-instance — **not multi-tenant**. Multi-user ⇒ one profile (HERMES_HOME) per user, or one shared profile with `session_id` scoping.
- **Image/version:** `dulc3/hermes:v0.11.5` (project owner's fork, what k8s prod overlay deploys as `harvis-ai-hermes`, port 8642, `args:["gateway"]`); official `nousresearch/hermes-agent` uses **calver** tags (`v2026.6.19`…) — **no `v0.11.5` tag upstream**; on-disk CLI is v0.11.0. (All three work; pick one for the sidecar.)

---

## THE load-bearing finding (resolves the connector design)

**The HTTP API has no per-request workspace/cwd field.** `POST /v1/runs` body = `{input, instructions, session_id, conversation_history}` — confirmed no `cwd`/`workspace`/`workdir`. Worktree/working-dir scoping is **CLI/config-level** (`hermes -z`/`-w` in CWD; `terminal.cwd`).

➡ **Therefore Build (clone-scoped) uses the CLI-subprocess path, NOT the API server** — and that path maps **1:1 onto Harvis's existing `engine_adapter` pattern** (`docker exec -w <clone> harvis-hermes-agent hermes -z "<task>" --yolo`), exactly like OpenCode/Codex/Claude. The API server is the **complementary Chat backend** (point `owui_compat` at `:8642/v1`), not the Build driver. This answers the user's E4B.2 question ("client/resolver, not `engine_adapter` unless the API shape makes that the best path") — **the API shape makes `engine_adapter` the best path for Build.**

- **Tool progress for RunView:** `hermes chat -q -v` emits verbose tool-progress text (parse → `tool_call`/`log` events, like OpenCode's adapter); floor = final-response + diff (acceptable). The API server's `/v1/runs/{id}/events` SSE is richer but cwd-less (Chat only).
- **Cancel:** CLI = kill the specific run process (`pkill -f <clone>`, the proven OpenCode mechanism); API = `POST /v1/runs/{id}/stop`.

---

## Recommended implementation (E4B.1–E4B.6), reusing E1/E2 infra

| Phase | Plan (engine = **`hermes-agent`**, native E4 renamed **`hermes-native`** fallback) |
|---|---|
| **E4B.1 sidecar** | `harvis-hermes-agent` compose service (image: official `nousresearch/hermes-agent:latest` *or* `dulc3/hermes:v0.11.5`), idle entrypoint, mounts the shared `artifact_data` volume (same clone paths the backend sees) + a persistent `hermes-home` volume; `config.yaml` → `provider=custom, base_url=http://ollama:11434/v1`; on internal net only; **no keys baked.** |
| **E4B.2 connector** | Extend `engine_adapter.py` (or `hermes_agent_runner.py`): `docker exec -w <clone> harvis-hermes-agent hermes -z "<task>" --yolo` (+ `-m <model>`), parse `-v` output → `log`/`tool_call`/`tool_result`/`done`/`error`; reuse `collect_diff` for artifacts; per-run kill for cancel; fail-soft if sidecar down. |
| **E4B.3 routing** | New engine id `hermes-agent` → connector; rename E4's `engine="hermes"` → `hermes-native` (experimental fallback); clone-only; in-place/orchestrate force native. |
| **E4B.4 readiness** | NEW flag `HARVIS_OWUI_HERMES_AGENT_ENGINE=1`; `engine_readiness.hermes-agent.ready` iff flag + sidecar reachable + `docker exec … hermes status` healthy (NOT "an ollama hermes model exists"). `hermes-native` = experimental/disabled. |
| **E4B.5 frontend** | Selector: Native · OpenCode · Codex · Claude Code · **Hermes Agent** (full app) [· Hermes Native (experimental)]. Catalog card: "full Hermes app/runtime when the service is connected — not a local model." |
| **E4B.6 verify** | The user's 15-point matrix; **no commit until the full E2E passes or you approve an infra-only commit.** |

---

## Exact commands / ports / env / volumes (from the smoke)

```bash
# provider (local Ollama, no key):
hermes config set model.provider custom
hermes config set model.base_url http://localhost:11434/v1   # sidecar: http://ollama:11434/v1
hermes config set model.default qwen3:4b
# Build (clone-scoped, headless):  cd <clone> && hermes -z "<task>" --yolo [-m <model>]
# API server (Chat):  API_SERVER_ENABLED=true API_SERVER_KEY=<tok> hermes gateway run   # :8642 /v1/*
# official docker:  docker run -d -v <home>:/opt/data -p 8642:8642 nousresearch/hermes-agent gateway run
```
Ports: **8642** (API server). Volumes: `hermes-home`(profile/memory) + shared `artifact_data`(clones). Env: `HERMES_HOME`, `API_SERVER_ENABLED`, `API_SERVER_KEY`, `OLLAMA`/`model.base_url`.

---

## ADDENDUM — official **v0.17 container** smoke (2026-06-28, decisive)

Pulled `nousresearch/hermes-agent:v2026.6.19` (5.28 GB), ran it on `ollama-n8n-network` with a clone bind-mounted at `/work` + per-user home at `/opt/data`. Findings:

- **Chat API ✓** — `/health` → `{"status":"ok","platform":"hermes-agent","version":"0.17.0"}`; `/v1/models` (Bearer) → `hermes-agent`. Config schema unchanged (`model.provider/base_url/default` read fine on v0.17).
- **v0.17 added sandbox hardening** (good, not a bug): (a) `terminal.docker_mount_cwd_to_workspace` defaults **OFF** — a mounted CWD is not a writable workspace unless opted in (`TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true` + `TERMINAL_CWD=<clone>`); (b) **`HERMES_WRITE_SAFE_ROOT`** (default `/opt/data`) — `write_file` **denies any path outside it** (`agent/file_safety.py:is_write_denied`). That's why `/work` writes were initially denied.
- **The clean recipe (write_file works + confinement):** per Build run set `HERMES_WRITE_SAFE_ROOT=<clone>` + `TERMINAL_CWD=<clone>` + `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true`. → `write_file` created `/work/note2.txt` directly ✓.
- **Confinement VERIFIED (security win):** with `HERMES_WRITE_SAFE_ROOT=/work`, a write to `/tmp/escape.txt` was **DENIED** and the file never appeared — **Hermes itself refuses to write outside the clone**, layered on top of the container. Exactly Harvis's containment model.
- **uid detail → thin wrapper warranted:** the image runs as root; files it writes aren't readable by Harvis's backend (**uid 1001**, the `artifact_data` owner). So the sidecar must run as **uid 1001** with `/opt/data` set up for it → build a **thin `harvis-hermes-agent` Dockerfile FROM `nousresearch/hermes-agent:v2026.6.19`** (USER 1001 + baked Ollama config + the safe-root/workspace env defaults). This is the user's "thin wrapper only if it needs Harvis defaults" trigger — it does.

**Sidecar per-Build-run exec (the E4B.2 connector command):**
```bash
docker exec -u 1001 -w <clone> \
  -e HERMES_WRITE_SAFE_ROOT=<clone> -e TERMINAL_CWD=<clone> -e TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true \
  harvis-hermes-agent hermes -z "<task>" --yolo [-m <model>]
# then Harvis collect_diff(<clone>) as today → artifacts
```

## Failure modes
- No provider in `config.yaml` → `RuntimeError: No LLM provider configured` (must set provider/base_url/default, not just `--provider`).
- API server cwd-less → don't drive Build through `/v1/runs`; use the CLI in the clone.
- `dulc3/hermes:v0.11.5` is a fork tag; official upstream is calver — a `v0.11.5` pull against `nousresearch/*` fails.
- Per-profile memory → multi-tenant needs a profile-per-user or session_id design (decision below).

## Genuine open decisions (gate the build)
1. **Multi-tenancy:** v1 single shared Hermes profile (dev/single-user, simplest, local-Ollama needs no per-user keys) vs per-user `HERMES_HOME`. 
2. **Image:** official `nousresearch/hermes-agent:latest` (upstream-maintained) vs `dulc3/hermes:v0.11.5` (your fork, already in k8s).
3. **Keep E4 Hermes-Native** as `hermes-native` experimental fallback (recommended: yes, rename) vs remove.

## Security posture (carry into E4B.1)
Per-exec, no keys in image/compose (local-Ollama needs none); throwaway/per-user `HERMES_HOME`; clone-only (container + mounted clone is the confinement, like OpenCode); never log raw prompt/SOUL/profile/keys; `--yolo` is acceptable **because the clone is the sandbox** (same posture as the other external engines). No new DB tables required for v1.
