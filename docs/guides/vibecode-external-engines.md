# VibeCode External Code Engines — OpenCode (E1) + Codex / Claude Code (E2)

Harvis Build (VibeCode) normally runs its own native agent on the OpenClaw runtime.
**External engines** let a Build session run a third-party coding CLI instead:

| Engine | Models | Auth | Notes |
|---|---|---|---|
| **OpenCode** (E1) | local Ollama | none | zero cloud credentials; sidecar CLI |
| **Codex** (E2) | cloud GPT/Codex | **your OpenAI key** | per-user, encrypted; sidecar CLI |
| **Claude Code** (E2) | cloud Claude | **your Anthropic key** | per-user, encrypted; sidecar CLI |
| **Hermes** (E4) | local Hermes models | none | **native runner** + your SOUL persona; own flag |

The **sidecar** engines (OpenCode/Codex/Claude Code) are **off by default** behind
`HARVIS_OWUI_EXTERNAL_ENGINES`. **Hermes** is a *native* engine (the in-process Harvis
runner, not a sidecar) behind its **own** flag `HARVIS_OWUI_HERMES_ENGINE` — enable it
independently. All engines are **clone-mode only**, and the **git diff is the only gate**
(the agent runs autonomously inside a throwaway clone — your real repo is never touched).
The cloud engines bill **your** vendor account, so the operator pays nothing.

---

## Hermes — the native persona engine (E4)

Hermes is **not** a sidecar CLI like the others. It runs Harvis's own in-process agent
runner (`SubAgentRunner`, the same engine as **Native**) but specialized two ways:

1. **Defaults to a local Hermes model** — if the selected model isn't a `hermes` tag, the
   turn uses `HARVIS_HERMES_DEFAULT_MODEL` (default `hermes3:3b`). The model actually used
   is recorded on the run row **and** logged into the run stream when it overrode a
   selection.
2. **Carries your SOUL persona** — it prepends your per-user `SOUL.md`
   (`plugins/soul/loader.build_persona_block`, with the neutral `DEFAULT_SOUL_MD` when you
   haven't set one) to the Build system prompt. This is what makes Hermes a *distinct*
   engine versus "pick a hermes model on Native", and it activates the SOUL machinery that
   was otherwise chat-only. The raw persona/prompt is **never logged** — only a length +
   truncated SHA-256 marker.

Everything else is the standard native pipeline: RunView, **Stop**, the cumulative diff,
artifacts, and the clone-safety model. No sidecar, no credentials, no new tables (it reuses
the `user_soul` table). In v1 the composer hides the Plan/Agents controls for Hermes (same
as the other non-native engines).

```bash
# enable + pull a Hermes model
ollama pull hermes3:3b
HARVIS_OWUI_HERMES_ENGINE=1 HARVIS_HERMES_DEFAULT_MODEL=hermes3:3b docker restart harvis-backend
# Build → new clone session → engine selector shows "Hermes" (ready iff flag + a hermes model)
```

**Readiness** (`/api/owui/capabilities` → `engine_readiness.hermes`): `ready` iff the flag
is on AND a Hermes model is installed; otherwise `reason: "disabled"` (flag off) or
`reason: "no_hermes_model"` (flag on, none pulled — surfaced as a hint in the composer).

---

## Cloud engines (Codex, Claude Code) — connecting a key

The cloud engines need **your own API key**, connected per-user through the encrypted
**Connect panel** (Integrations → Codex / Claude Code → "Connect & verify"). The key is
stored **encrypted** (Fernet, same as OpenClaw BYO), is **write-only** (the UI never shows
it back), and is decrypted only at run time and injected into the sidecar **per-exec** —
never baked in the image, never logged. **User A's key is never visible or usable by user B.**

A cloud engine only becomes selectable in Build once its credential is **verified** (the
registry reports `engine_readiness.<engine>.ready` only when the sidecar is up AND the user
has a verified credential; otherwise `reason: "missing_auth"`).

```bash
# enable + bring up all three sidecars
HARVIS_OWUI_EXTERNAL_ENGINES=1 docker compose up -d --build opencode codex claude-code backend
# then connect a credential in the UI: Integrations → Codex (or Claude Code) → Connect & verify
```

### Claude Code — two auth modes (Phase E4B)

Claude Code accepts **either** of two per-user credentials — the user picks the mode in the
Connect panel (Codex is API-key-only):

| Mode | What you provide | Stored | Runtime env | Verify |
|------|------------------|--------|-------------|--------|
| **API key** | an Anthropic API key | encrypted (`auth_mode='api_key'`) | `ANTHROPIC_API_KEY` | `max_tokens:1` Messages call |
| **Claude subscription** | the token from `claude setup-token` (needs Pro/Max/Team/Enterprise) | encrypted (`auth_mode='oauth_token'`) | `CLAUDE_CODE_OAUTH_TOKEN` | a `claude -p` CLI smoke in the sidecar |

**Subscription users don't need API credits.** Exactly **one** credential env var is injected
per run — never both (`ANTHROPIC_API_KEY` officially takes precedence, so a stray one would
shadow the OAuth token). Secrets are write-only + encrypted, decrypted only at run time,
never logged. The `user_engine_auth` table carries `auth_mode`.

⚠️ **Sidecar gotcha:** the `claude-code` image bakes `CLAUDE_CODE_SIMPLE=1` (simple/bare mode),
which reads auth **strictly** from `ANTHROPIC_API_KEY` and **ignores `CLAUDE_CODE_OAUTH_TOKEN`**
(a valid token → "Not logged in"). Harvis therefore sets `CLAUDE_CODE_SIMPLE=` (off) per-exec
for subscription-token mode (and `=1` for API-key mode). Same reason Harvis never uses
`--bare`. Verified end-to-end with a real subscription token (Build run → diff, no API credits).

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
