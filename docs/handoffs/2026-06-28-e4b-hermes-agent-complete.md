# Phase E4B — Full Hermes Agent Runtime Integration (COMPLETE + verified)

**Date:** 2026-06-28 · **Branch:** `harvis1.1` · **Status:** built, deployed locally, E2E-verified.
**Standing rule:** uncommitted — no commit/push until the user approves.

This report explains, in detail, **what was built**, **how it works internally**, and **how a user
interacts with it**. It supersedes the E4 "Hermes as a native model" work, which is preserved as an
experimental fallback (`hermes-native`) — see the scope-correction note at the bottom.

---

## 1. What this is (one paragraph)

Harvis now runs the **real, open-source NousResearch Hermes Agent application** as a first-class
**Build engine** *and* a **Chat model**. The actual Hermes app — with its own tools, memory, skills,
profile system and OpenAI-compatible API server — runs as an isolated sidecar container
(`harvis-hermes-agent`). When you pick **"Hermes Agent"** as your Build engine, a coding session
dispatches to it: Hermes edits a private clone of your repo using *its own* file tools, and Harvis
captures the diff, drives RunView, and owns Stop. When you pick **"Hermes Agent"** as a Chat model,
your messages are proxied straight to its API server and you converse with the live agent runtime.
Everything runs on **local Ollama** — no cloud credentials.

This is the corrected scope. The earlier E4 work integrated a *Hermes-flavoured model* on Harvis's
own runner; the user clarified the target was **the application itself**. That's now what ships.

---

## 2. Architecture

```
                                   ┌──────────────────────────────────────────────┐
  User (browser, :9000)            │  harvis-hermes-agent  (the REAL Hermes app)   │
        │                          │  ─ s6 init → gateway run (ROOT)               │
        ▼                          │  ─ OpenAI API server on :8642 (Chat)          │
  OWUI frontend ──► nginx ──► Harvis backend (FastAPI, uid 1001)                   │
        │                          │  ─ `hermes` CLI for Build (docker exec -u1001)│
        │                          │  ─ per-user HERMES_HOME=/data/hermes-homes/<u>│
        ├─ BUILD: engine="hermes-agent"                                            │
        │     workspace_router → engine_adapter._build_hermes_command              │
        │     → docker exec -u 1001 -w <clone> harvis-hermes-agent hermes -z "…"   │
        │     → Hermes edits the clone with its own tools ───────────────┐         │
        │     ← Harvis collect_diff(<clone>) → diff/file/changed_files   │         │
        │                                                                 ▼         │
        └─ CHAT: model="hermes-agent"                          (shared volume:      │
              owui_compat.run_chat_completion                   artifact_data —     │
              → hermes_chat.proxy_hermes_chat                    clones live here,   │
              → http://harvis-hermes-agent:8642/v1/chat/...      both see same path) │
              ← OpenAI-shaped SSE/JSON                          └────────────────────┘
                          (local Ollama  http://ollama:11434/v1  — no cloud keys)
```

**Role split (unchanged Harvis philosophy):** Harvis owns session/clone safety, RunView, Stop,
artifacts and diff capture. Hermes owns the agent loop (its tools, memory, skills, profile).

---

## 3. The two surfaces in detail

### 3a. Build engine (`engine = "hermes-agent"`) — the headline

A VibeCode/Build session can select **Hermes Agent** as its engine (clone-mode only). Each turn:

1. **Dispatch.** `workspace_router.py` reads `engine` from the session row. `hermes-agent` is in
   `EXTERNAL_ENGINE_IDS`, gated by its **own** flag via `_engine_enabled()` (returns
   `_hermes_agent_engine_enabled()` for hermes-agent; the external-engines flag for
   opencode/codex/claude-code). It is **not** in `CLOUD_ENGINE_IDS`, so it skips the per-user
   API-key check (local Ollama needs none). The turn routes to `agent_id="engine-adapter"`.

2. **Per-user profile.** Before the run, `engine_adapter._ensure_hermes_home(container, user_id)`
   idempotently writes a `config.yaml` into `HERMES_HOME=/data/hermes-homes/<user_id>` (provider
   `custom`, `base_url=http://ollama:11434/v1`, default model = `HARVIS_HERMES_AGENT_DEFAULT_MODEL`).
   Each user gets an isolated Hermes home (memory/SOUL) on the `hermes_homes` volume.

3. **Run.** `_build_hermes_command` returns the docker-exec argv:
   ```
   docker exec -u 1001 -w <clone>
     -e HERMES_HOME=/data/hermes-homes/<user_id>
     -e HERMES_WRITE_SAFE_ROOT=<clone>
     -e TERMINAL_CWD=<clone>
     -e TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE=true
     harvis-hermes-agent  hermes -z "<task>" --yolo -m <model>
   ```
   Hermes runs *headlessly* (`-z … --yolo`) inside the clone, editing files with its own tools.
   The gateway runs as **root** (s6 requires it), but **Build runs as uid 1001** (the artifact_data
   owner) so the diff collector can read what Hermes wrote.

4. **Stream → events.** The adapter reads Hermes's stdout line-by-line. JSON lines route through the
   mapper; plain text becomes `log` events and is also captured into a small `text_tail` buffer
   (cap 16) used as the run summary fallback. RunView renders these like any other engine's run.

5. **Diff capture.** On exit, the shared loop runs `iso.collect_diff(<clone>)` /
   `collect_changed_files` / `collect_file_contents` against the session's fixed `base_sha`, and
   saves `diff` / `changed_files` / `file` artifacts. Stop kills only that run (`pkill -f <clone>`).

**Verified E2E:** a `hermes-agent` session asked to create `hello.py` →
`status=done`, artifacts = a real `diff --git a/hello.py … +print("hi")`, `changed_files=hello.py`,
and the file contents. The real Hermes app did the edit; Harvis captured the diff.

### 3b. Chat model (`model = "hermes-agent"`)

The sidecar runs Hermes's OpenAI-compatible API server on `:8642` (`API_SERVER_ENABLED=true`,
`API_SERVER_KEY` required). The facade surfaces this as a single chat model:

- `owui_compat/hermes_chat.py::hermes_chat_model_entry()` adds **"Hermes Agent"** to `/api/models`
  **only when** the engine flag is on **and** the sidecar `/health` responds (fail-closed).
- `run_chat_completion` intercepts `model == "hermes-agent"` *before* the native router and calls
  `proxy_hermes_chat`, which forwards the OpenAI body (stream or non-stream) to
  `http://harvis-hermes-agent:8642/v1/chat/completions` with the API-server key. **It never enters
  `model_proxy`'s routing brain** — fully isolated, fail-soft (502/SSE-error on sidecar trouble).

Talking to this model = a real conversation with the Hermes runtime (its full system prompt, tools,
memory), so a turn runs the **agent loop** and is heavier/slower than a plain Ollama completion
(~30 s for a trivial prompt on this box, because Hermes loads a ~13 K-token system prompt). That's
the genuine Hermes experience, not a thin LLM call.

**Verified E2E:** `hermes-agent` lists in `/api/models` as "Hermes Agent"; a facade
`/api/chat/completions` with that model returned a clean `chat.completion` (`content: "PONG"`).

---

## 4. How the user interacts with it

### Enabling it (operator, once)
Set the flag and recreate the stack:
```
HARVIS_OWUI_HERMES_AGENT_ENGINE=1   docker compose up -d backend hermes-agent
```
(Default OFF. Build the sidecar image first: `docker build -t harvis-hermes-agent:local hermes-agent/`.)

### In the UI (end user)
- **Build:** open **Build / VibeCode** → start a **clone** session → the engine selector now offers
  **Native · OpenCode · … · Hermes Agent · Hermes Native** (each shown only when *ready*). Pick
  **Hermes Agent**, type a coding task, send. RunView streams Hermes's work; the **Changes** tab
  shows the diff; **Stop** cancels; reload replays from the DB. (Plan/Agents are hidden for external
  engines, same as OpenCode/Codex.)
- **Chat:** in the model picker, choose **Hermes Agent** and chat normally. Responses come from the
  live agent runtime. Expect a noticeable first-token delay (the agent loop).
- **Integrations:** the **Hermes Agent** card now reads honestly — "the full NousResearch Hermes
  Agent app … runs as a Harvis Build engine (isolated sidecar, local Ollama, no credentials)."
- **Brain readiness / engine_readiness:** `hermes-agent` shows **ready** when the flag is on and the
  sidecar is up; **needs_setup** ("disabled" / "Sidecar not running") otherwise.

---

## 5. Security model

- **No provider keys anywhere in the image or compose** for Hermes (local Ollama). The only secret
  is the sidecar's **own** API-server key (`API_SERVER_KEY`, compose default
  `harvis-hermes-local-dev`); the backend holds the matching `HARVIS_HERMES_API_SERVER_KEY` to auth
  the Chat proxy. **Never logged.**
- **Write confinement (defense in depth).** `HERMES_WRITE_SAFE_ROOT=<clone>` makes Hermes's own
  `write_file` *refuse* to write outside the clone (verified in E4B.0: `/tmp/escape.txt` write
  DENIED + file absent). On top of the throwaway clone, Hermes itself enforces the boundary.
- **Per-user isolation.** Each user gets `HERMES_HOME=/data/hermes-homes/<user_id>` (own memory/
  profile); the homes-dir volume root is chowned to uid 1001 at sidecar startup so the uid-1001
  Build exec can create its home.
- **Never logged:** user prompts, persona/SOUL, profile secrets, API keys, tool env. The connector
  logs only run id / engine / model / counts.
- **Clone-only.** In-place / orchestrate force the native runner; the external CLI is never pointed
  at a real repo.

---

## 6. Files & config

**New:**
- `hermes-agent/Dockerfile` — thin wrapper `FROM nousresearch/hermes-agent:v2026.6.19`; creates a
  uid-1001 `builder` user; `ENTRYPOINT harvis-entrypoint.sh`.
- `hermes-agent/harvis-entrypoint.sh` — (root) chowns `/data/hermes-homes` to 1001; injects a
  local-Ollama gateway `config.yaml` if absent; hands off to the official s6 init `gateway run`.
- `python_back_end/owui_compat/hermes_chat.py` — Chat model entry + isolated SSE/JSON proxy.

**Edited:**
- `docker-compose.yaml` — `hermes-agent` service (root, API server on :8642, volumes
  `artifact_data` + `hermes_gateway_home` + `hermes_homes`, internal net, **no host port**) +
  backend env (`HARVIS_OWUI_HERMES_AGENT_ENGINE`, `HARVIS_HERMES_AGENT_CONTAINER`,
  `HARVIS_HERMES_OLLAMA_URL`, `HARVIS_HERMES_AGENT_DEFAULT_MODEL`, `HARVIS_HERMES_API_SERVER_KEY`,
  `HARVIS_HERMES_AGENT_CHAT_URL`).
- `python_back_end/workspace/orchestration/engine_adapter.py` — `hermes-agent` builder/mapper,
  `_ensure_hermes_home`, text_tail summary, `user_id` threaded.
- `python_back_end/workspace/workspace_router.py` — `hermes-agent` ∈ `EXTERNAL_ENGINE_IDS`;
  `_hermes_agent_engine_enabled()` + per-engine `_engine_enabled()`; E4 `"hermes"` renamed to
  `"hermes-native"` (NATIVE_ENGINE_IDS, session-create, dispatch, persona-engine value).
- `python_back_end/workspace/orchestration/session_turn.py` — `persona_engine == "hermes-native"`.
- `python_back_end/owui_compat/integrations_status.py` — `hermes-agent` readiness (flag + sidecar).
- `python_back_end/owui_compat/capabilities.py` — `engine_readiness` maps `hermes-agent` +
  `hermes-native`.
- `python_back_end/owui_compat/router.py` — `/api/models` appends the Hermes-Agent chat model.
- `python_back_end/owui_compat/chat_completion.py` — intercept → `proxy_hermes_chat`.
- `front_end/owui/.../vibecode/+page.svelte` — selector labels (`hermes-agent` / `hermes-native`).
- `front_end/owui/src/lib/integrations/catalog.ts` — honest "Hermes Agent" copy.

**Flags / env (defaults):** `HARVIS_OWUI_HERMES_AGENT_ENGINE=` (OFF) ·
`HARVIS_HERMES_AGENT_DEFAULT_MODEL=qwen3:4b` · `HARVIS_HERMES_API_SERVER_KEY=harvis-hermes-local-dev`
· image `nousresearch/hermes-agent:v2026.6.19` (the `dulc3/hermes:v0.11.5` fork stays in k8s; not
updated).

---

## 7. Verification results (this session)

| Check | Result |
|---|---|
| Readiness | `engine_readiness.hermes-agent.ready=true` (flag+sidecar); `hermes-native.ready=true`; opencode/codex/claude unchanged ✅ |
| Build E2E | `hermes-agent` session → real Hermes app created `hello.py` → `diff`+`changed_files`+`file` artifacts captured, `status=done` ✅ |
| Chat E2E | `hermes-agent` lists in `/api/models` as "Hermes Agent"; facade completion returned `PONG` ✅ |
| Opencode regression | `session.engine=opencode` persisted; `engine_adapter … engine=opencode … 1 files` — routed through engine-adapter, diff captured ✅ |
| Write confinement | (E4B.0) write outside the clone DENIED by Hermes ✅ |
| Frontend | `npm run build` exit 0; selector + catalog compile; deployed to nginx ✅ |
| Secrets | per-user homes; no keys/prompts/persona logged ✅ |

**Bugs fixed during integration:** (1) `Permission denied: /data/hermes-homes/<uid>` — the homes
volume root was root-owned; fixed by chowning it to 1001 in the entrypoint. (2) test-harness
"changed=''" was a false alarm — the artifacts list endpoint doesn't inline `content`; the DB had
the real diff.

---

## 8. Deferred / known limitations

- **Chat latency.** The Hermes Chat model runs the full agent loop (~30 s first response on this
  8 GB box). Acceptable for "talk to the agent," not for snappy chat — documented, not a bug.
- **`hermes-native` (E4)** is kept as an experimental fallback engine under
  `HARVIS_OWUI_HERMES_ENGINE` (in-process runner + SOUL persona on a local Hermes model). Not the
  primary integration.
- **k8s.** This is docker-compose-only (the engine-adapter uses `docker exec`). A k8s exec model
  (Job-per-turn or a sidecar-pod HTTP API) is a later phase, same as the other external engines.
- **Cleanup.** A few throwaway test sessions remain in the Build sidebar (E4B build v1/v2, opencode
  regression) — harmless; delete from the UI if desired.

## 9. Scope-correction note (why this exists)

E4 originally built "Hermes as a specialized native model" — the wrong target. The user corrected:
"it was supposed to be the application hermes." E4B is the real application, plugged in as a Build
engine + Chat model, with Harvis owning the safety/RunView/diff envelope. The earlier "no runnable
gateway" conclusion was wrong — it read a verification report pinned to a commit that predated
Hermes's API server; the live app has one.
