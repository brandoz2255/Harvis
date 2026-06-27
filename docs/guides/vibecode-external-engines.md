# VibeCode External Code Engines — OpenCode (Phase E1)

Harvis Build (VibeCode) normally runs its own native agent on the OpenClaw runtime.
**Phase E1** lets a Build session run an **external coding CLI** instead — shipping
with **OpenCode**, run against your **local Ollama** models (zero cloud credentials).

The engine is **off by default**, **clone-mode only**, and the **git diff is the only
gate** (the external CLI runs autonomously inside a throwaway clone — your real repo is
never touched).

---

## How it works

```
Build turn (engine="opencode")
  → workspace_router turn dispatch → agent_id="engine-adapter"
    → orchestration/engine_adapter.py
      → docker exec -u 1001 -w <session-clone> harvis-opencode \
           opencode run "<task>" --model ollama/<model> --format json \
           --dangerously-skip-permissions --dir <session-clone>
      → maps OpenCode's NDJSON events → OpenClawEvents (log/token/tool_call/tool_result/done)
      → collect_diff vs base_sha → diff/file/changed_files artifacts
  → same persistence / SSE / RunView pipeline as the native runner
```

- **`harvis-opencode` sidecar** (compose service `opencode`): `node:20-slim` + `opencode-ai`,
  runs as uid 1001, mounts the shared `artifact_data` volume so it edits the session clone
  **in place** at the same path the backend uses.
- **Model**: the turn/session model → else the user's Integrations `default_model` → else
  `HARVIS_OPENCODE_DEFAULT_MODEL`. Resolved to `ollama/<tag>`; the sidecar's entrypoint
  regenerates the provider's model list from live Ollama tags at boot (new pulls work
  without an image rebuild).
- **The repo is the memory** — only the current turn's brief is sent to `opencode run`;
  prior turns' edits already live in the persistent clone.

---

## Enable it

1. **Turn the flag on** (backend env): `HARVIS_OWUI_EXTERNAL_ENGINES=1`.
2. **Bring up the sidecar**:
   ```bash
   docker compose up -d --build opencode
   HARVIS_OWUI_EXTERNAL_ENGINES=1 docker compose up -d --no-deps backend
   ```
   (The backend does NOT hard-depend on the sidecar — it fails soft if it's down.)
3. The Build composer shows an **Engine** control (Native | OpenCode) **only when the
   flag is on AND the sidecar is ready AND the session is clone-mode**. Selecting OpenCode
   hides the Plan/permission ladder and the Agents toggle (an external CLI runs
   autonomously; orchestrate forces native).

### Smoke test the sidecar (build-step-0)

```bash
docker exec harvis-opencode opencode --version          # 1.17.x
docker exec harvis-opencode opencode models | grep ollama   # your pulled tags as ollama/<tag>
# one real run on a throwaway dir:
docker exec harvis-opencode bash -c '
  rm -rf /tmp/t && mkdir -p /tmp/t && cd /tmp/t && git init -q
  opencode run "create hello.py that prints hi" \
    --model ollama/qwen3:4b --format json --dangerously-skip-permissions --dir /tmp/t
  cat hello.py'
```

---

## Expected UI flow (on :9000)

1. Build → **New session** → **Engine: OpenCode** (selector visible only with the flag +
   clone mode) → send *"add a function add(a,b) and a test"*.
2. RunView streams OpenCode's events (log → tool_call → tool_result → done); the **Changes**
   tab shows the diff; reload replays from the DB (events persist in `workspace_events`).
3. **Zero cloud calls** — OpenCode uses Ollama only.

---

## Testing matrix

| Case | Expected |
|---|---|
| Native session (or flag OFF) | unchanged `vibecode-turn` runner; no engine selector |
| In-place session | forced native (external CLI can't honor the permission ladder) |
| `engine=opencode` while flag OFF | server coerces to `native` on session create |
| Orchestrate (Agents) on an opencode session | routes to `orchestrated`, NOT engine-adapter |
| **Stop** mid-run | run → `cancelled`; the specific run's `opencode` killed (`pkill -f <clone>`); no orphan (`docker top harvis-opencode` clean) |
| Sidecar down | fail-soft `error` event; registry shows opencode not-ready |

---

## Honesty / scope

- OpenCode runs **when this deploy flag is on** — not "any preferred engine runs everywhere".
- **Claude Code** and **Codex** stay catalog references (`service_key: None`, not runnable)
  until **Phase E2** (they need a per-user encrypted cloud API key).
- **Clone-mode only** — never in-place. The diff is the gate; there is no per-action
  approval for the external engine.

## Kubernetes — not supported in E1

E1 uses `docker exec` into a sidecar via the backend's `/var/run/docker.sock` mount, which
is **docker-compose-only**. A K8s deployment needs a different exec model (a per-turn `Job`,
or a sidecar-pod HTTP API) — deferred.

## Reverting

Set `HARVIS_OWUI_EXTERNAL_ENGINES` empty (or unset) and recreate the backend; the engine
selector disappears and every Build turn uses the native runner. The `harvis-opencode`
service can be stopped (`docker compose stop opencode`) — it's idle when unused.
