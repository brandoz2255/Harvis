## 2026-04-24: Agent ran tools but produced empty answers / wrong answers in workspaces

### Problem
Discord-launched (and direct) workspace tasks showed the agent writing Python
scripts and running them, but failing with a cascade of:
- `sh: 1: cd: can't cd to /home/node/workspaces/bundled/2/discord-…`
- `python3: can't open file … No such file or directory`
- `Permission denied` when writing files outside `.openclaw/workspace`
- `Obfuscated command detected. Approval required` → then agent proceeded as if success
- `UnicodeDecodeError`, `SyntaxError`, `NameError` inside hand-rolled `python3 -c '…'`
- Final summary arriving empty (`"summary": ""`), so the UI just said "Workspace complete"
- Earlier runs hallucinated a made-up flag (`FLAG{HARDSHIP_IS_NOT_THE_BUG}`)

### Root cause
Three bugs compounded:
1. **Workspace path lie.** The directive told the agent its workdir was
   `/home/node/workspaces/bundled/<uid>/<session>/`. But the OpenClaw `exec`
   and `write` tools actually use `/home/node/.openclaw/workspace/` as their
   CWD/root. `write` silently wrote to the real root while the agent kept
   `cd`-ing into an empty legacy dir and losing its own files.
2. **Obfuscation sandbox phantom successes.** OpenClaw flags `python3 -c '…'`
   containing `decode|base64|b64decode|exec|system|eval` and returns an
   `Approval required` string with `success=true`. The agent treated that as
   a successful result and plowed forward on commands that never ran.
3. **Empty final summary not surfaced.** The sub-agent completed with an empty
   message and the parent emitted `done` with `summary: ""`, so the user saw
   nothing — no answer, no error hint.

### Solution
- `python_back_end/workspace/openclaw_client.py`
  - Moved `workdir` to a sub-directory of the real exec CWD:
    `/home/node/.openclaw/workspace/session-<prefix><session>`.
    Also passes a `workdir_rel` (`session-…`) to the model so the `write`
    tool (which treats relative paths as rooted at the exec CWD) and `exec`
    (which needs absolute paths) both land in the same place.
  - Rewrote the directive block with explicit "FILESYSTEM LAYOUT",
    "PYTHON EXECUTION RULES" (no `python3 -c` with decode/base64/exec/eval —
    always write then run), and "ANSWER CONTRACT" (no acknowledgement-only
    replies, no hallucinated answers, report uncertainty instead).
  - In `_handle_agent_event`, when a tool_result output contains
    `Approval required`, `Obfuscated command detected`, or `approval-pending`,
    re-classify as `success=false` and emit a visible log line so the agent
    sees the failure and retries differently.
  - In the `state == "final"` branch, synthesize a fallback summary when
    text is empty so the UI never ships a blank "Workspace complete".
- `openclaw/config/bundled/AGENT.md`, `openclaw/config/AGENT.md`,
  `openclaw/config/bundled/USER.md`, `openclaw/skills/bundled/harvis-agent/SKILL.md`
  - Rewrote the "Workspace scope" sections to match the real CWD + relative/absolute
    path rules, added the Python + obfuscation sandbox guidance, and added the
    "Answer contract" rules (no "Copy that." / "Standing by." / guessed flags).

### Files Modified
- `python_back_end/workspace/openclaw_client.py`
- `openclaw/config/bundled/AGENT.md`
- `openclaw/config/AGENT.md`
- `openclaw/config/bundled/USER.md`
- `openclaw/skills/bundled/harvis-agent/SKILL.md`

### Verification
Reproduced the same XOR CTF task after restarting `harvis-backend` and
`harvis-openclaw`. Run `f9a7ad9f` produced:
- First tool call: `mkdir -p /home/node/.openclaw/workspace/session-bundled-2-fix-verify-xor && cd … && pwd`
- `write` succeeded at `session-bundled-2-fix-verify-xor/decode_xor.py`
- `python3 /home/node/.openclaw/workspace/session-bundled-2-fix-verify-xor/decode_xor.py` actually ran
- `tool_calls=15`, `event_count=46`, `status=done`
- Non-empty final summary that honestly reports the decoded bytes, admits
  that most bytes are non-printable, and refuses to fabricate a flag

### Status
Resolved — workspace agent now uses the correct filesystem, avoids the
sandbox obfuscation trap, surfaces blocked commands as failures, and always
produces a human-readable final answer.

---

## 2026-05-04 10:31 PDT - OpenClaw workspace memory and callback guidance

### Problem
OpenClaw workspace runs for conversational follow-ups could misuse workspace paths as memory/session identifiers. In workspace `91a26d67`, the model tried to read `AGENTS.md` from the per-session filesystem directory and then called `sessions_history` with `session-bundled-...`, which is a filesystem slug, not an OpenClaw session key. Both tools failed, and the final answer fell back to generic Harvis identity text instead of answering from Discord context.

### Root Cause
The backend appended recent conversation under a vague context heading and did not expose the valid OpenClaw callback/session key clearly. The static bundled agent docs also described workspace filesystem scope but did not distinguish filesystem slugs from callback/session keys or explain that recent Discord context is injected as memory.

### Solution Applied
1. Added a `WORKSPACE MEMORY + CALLBACKS` section to the runtime OpenClaw directive.
2. Exposed the exact current OpenClaw callback/session key (`agent:<agent>:<session>`) for `sessions_history`.
3. Labeled the filesystem slug as legacy path-only scope, not a session history key.
4. Reframed the recent chat block as `WORKSPACE MEMORY` and instructed models to answer user-memory follow-ups from it before trying tools.
5. Updated bundled/generic OpenClaw agent docs and the bundled Harvis agent skill with the same memory/callback rules.

### Files Modified
- `python_back_end/workspace/openclaw_client.py`
- `openclaw/config/bundled/AGENT.md`
- `openclaw/config/AGENT.md`
- `openclaw/skills/bundled/harvis-agent/SKILL.md`
- `front_end/newjfrontend/changes.md`

### Result / Status
- Restarted `backend` and `openclaw`.
- Verified with workspace `67138185`: the model answered `You're a firefighter.` from provided workspace memory with no failed `read` or `sessions_history` calls.

---

## 2026-05-04 10:12 PDT - Discord memory questions routed to chat instead of workspace

### Problem
Discord questions like `what is my job` and `how far back can you see` were sometimes answered with generic Harvis identity text or unrelated topic pivots instead of using recent Discord context. Example failure: the bot responded with its own identity when asked for the user's job, even though the user had recently said they were a fire fighter.

### Root Cause
`DISCORD_PREFER_WORKSPACE=true` made the Discord bot route most non-tiny prompts through OpenClaw. The generic `_WORKSPACE_SIGNALS` regex also matched `what is...` questions, so personal-memory questions entered the workspace path where the Harvis identity/system prompt could overpower the actual question.

### Solution Applied
1. Added Discord memory/meta detection for questions like `what is my job`, `what am I`, `who am I`, `what did I tell you`, `do you remember`, and `how far back can you see`.
2. Added a direct recent-history answer path for job/identity questions, including normalization of `fire fighter` to `firefighter`.
3. Added a direct capability answer for `how far back can you see`, based on the configured recent Discord history window.
4. Updated the fast-chat system prompt so memory/capability questions answer from recent Discord context and do not pivot to prior topics.

### Files Modified
- `python_back_end/integrations/discord_workspace_bot.py`
- `front_end/newjfrontend/changes.md`

### Result / Status
- Verified helper output for the provided conversation: `Based on what you told me previously, you are a firefighter.`
- Backend restarted so the Discord bot is running the updated handler.

---

## 2026-04-27 11:45 PDT - OpenClaw terminal tasks pasted code instead of executing it

### Problem
Discord/OpenClaw terminal tasks for encoded password dumps could complete with a Python script and a `python3 /home/node/.../decode_p.py` command pasted into the final answer, but with `tool_calls = 0`. The file did not exist in the OpenClaw container, so the command the user saw was never actually executed.

### Root Cause
The model treated the terminal request as a code-writing answer instead of an execution task. Harvis accepted the final text as `done` because it was non-empty, even though there were no `write` or `exec` tool events.

### Solution Applied
1. Added terminal-task detection for run/execute/stdout/Python/decode/base64/number-base prompts.
2. Added detection for no-tool final answers that contain pasted code fences, Python imports, `python3` commands, or OpenClaw workspace paths.
3. Added a one-time corrective retry that tells the agent the previous code/command was plain text and forces real `write` + `exec` tool calls.
4. Strengthened the runtime directive: commands included in final text without a successful tool call are now explicitly classified as incomplete.

### Files Modified
- `python_back_end/workspace/openclaw_client.py`
- `front_end/newjfrontend/changes.md`

### Result / Status
- Verified with workspace `63ac9c07`: the retest completed with `tool_calls = 2` (`write` + `exec`) and decoded the values from actual stdout.
- Observed decoded outputs: `scorpion`, `scribble`, and `securelybG9sbGlwb3A=`.

---

## 2026-04-22: Sync OpenClaw Main Agent Model with Global Discord Model

### Problem
Workspace runs on the OpenClaw `main` route could fail with model-not-found errors (example: `gemma4:4b`) when OpenClaw retained a stale default model that did not match current global/user Discord model selection.

### Root Cause
Discord workspace launches could route to `agent_id=main` while OpenClaw default agent model in native config remained outdated. This produced upstream 404 errors even though Discord had a different active model.

### Solution Applied
Before launching a Discord workspace with `agent_id=main`, the bot now synchronizes OpenClaw native default model to the effective global/user model (`_model_override` or user preference) using existing `_apply_model_to_native_openclaw()`.

### Files Modified
- `python_back_end/integrations/discord_workspace_bot.py`

### Result
Discord workspace runs adapt to the currently selected global model for OpenClaw `main`, avoiding stale hardcoded-model failures.

---

## 2026-04-22: Force Discord Screenshot Tasks Through OpenClaw Main Agent

### Problem
Discord screenshot requests were sometimes routed to non-OpenClaw workspace agents (`local`/`kimi`) via user model preferences, producing text-only responses instead of real screenshot artifacts.

### Root Cause
`discord_workspace_bot.py` resolved `pref_agent_id` from DB-backed model preferences and could override `DISCORD_WORKSPACE_AGENT_ID=main`. Visual/screenshot tasks then bypassed OpenClaw browser tooling.

### Solution Applied
Added visual-task routing protection in Discord bot:
- Introduced `_VISUAL_TASK_SIGNALS` and `_looks_like_visual_task()`.
- If a message appears to require screenshots/browser visuals, force `pref_agent_id = "main"` before `launch_workspace_internal()`.
- Added log line when route is overridden for visibility.

### Files Modified
- `python_back_end/integrations/discord_workspace_bot.py`

### Result
Discord screenshot/website-visual tasks now stay on the OpenClaw browser-capable execution path, preventing text-only fallbacks from `local`/`kimi` routes.

---

## 2026-04-22: Harden Discord Screenshot Artifact Delivery

### Problem
Discord-triggered workspace tasks that took screenshots could finish in OpenClaw, but the Discord bot sometimes failed to attach the screenshot file in the final reply.

### Root Cause
The Discord artifact lookup logic used narrow path extraction (`browser/*.png` in limited string fields) and a single artifact root path. Valid screenshot paths embedded in nested payload data or alternate image extensions/paths were missed.

### Solution Applied
Improved screenshot artifact discovery in the Discord integration:
- Added recursive payload traversal to detect `artifact_path` in nested tool results/log structures.
- Expanded screenshot filename matching to include `.png`, `.jpg`, `.jpeg`, and `.webp`.
- Normalized absolute artifact paths into relative `browser/...` paths.
- Added fallback artifact root probing (`ARTIFACT_STORAGE_DIR`, `/data/artifacts`, `/app/data/artifacts`) while preserving path traversal safeguards.

### Files Modified
- `python_back_end/integrations/discord_workspace_bot.py`
  - Added `_extract_artifact_path_from_payload()`.
  - Expanded `_extract_artifact_path_from_text()` regex coverage.
  - Hardened `_find_latest_screenshot_file()` for nested payload parsing and multi-root file lookup.

### Result
Discord workspace runs now more reliably find and upload captured screenshots in the final bot response instead of silently returning text-only output.

---

## 2026-03-30: experimental/plugin-merge — Browser Automation, Web Research, Discord Integration, and Model Routing Overhaul

### Overview

Major feature branch merging OpenClaw browser automation (Chromium native), live web research, Discord workspace bot, local Ollama model routing, and workspace progress tracking. 28 files changed across frontend, backend, infrastructure, and skills.

---

### 1. OpenClaw Chromium Browser Integration

**Problem**: OpenClaw's native `browser/*` tools (navigate, screenshot, act) require Chromium in the container, but the base `dulc3/openclaw` image ships without a browser.

**Solution**: Created a layered Docker image `dulc3/openclaw-browser:latest` that extends the base OpenClaw image with Chromium and all required dependencies.

**Files Created/Modified**:
- `openclaw-browser/Dockerfile` (NEW) — Multi-distro Dockerfile: detects apt-get vs apk, installs Chromium + fonts + libs, sets `CHROME_BIN`/`PUPPETEER_EXECUTABLE_PATH` env vars, smoke-tests binary
- `docker-compose.yaml` — Updated openclaw service: `image: dulc3/openclaw-browser:latest`, `shm_size: 256m`, `tmpfs: [/tmp/.chromium:size=128m]`, Chromium env vars, memory 2G→3G, cpus 1.0→1.5
- `k8s-manifests/overlays/prod/openclaw.yaml` — Changed image to `dulc3/openclaw-browser:latest`, added `dshm` (256Mi emptyDir) and `chromium-tmp` (128Mi emptyDir) volumes, added Chromium env vars, bumped resources to 3Gi/1500m, fixed `bashForegroundMs` from 2000→30000 in ConfigMap, added `"browser": {"enabled": true, "headless": true}` config
- `k8s-manifests/overlays/prod/kustomization.yaml` — Changed image override from `dulc3/openclaw` to `dulc3/openclaw-browser:latest`
- `ci_openclaw_pipeline.sh` — Added browser image build step, smoke test with Chromium verification, push both base + browser images, kustomize update for both entries
- `openclaw/config/openclaw.json` — Added `"browser": {"enabled": true, "headless": true, "ssrfPolicy": {"blockPrivateIps": true}}`, bumped `bashForegroundMs` to 30000

**Critical fix**: K8s ConfigMap had `bashForegroundMs: 2000` which killed curl/browser commands in 2 seconds. Changed to 30000ms.

---

### 2. Live Web Research Mode

**Problem**: Users had no way to enable live web research from the chat UI. OpenClaw proxy endpoints lacked rate limiting, domain policies, and audit logging.

**Solution**: Added a "Web Research" toggle button in the frontend with a one-time acknowledgment dialog, and expanded the backend proxy with rate limiting, domain allowlists/denylists, SSRF protection, and full audit logging.

**Files Modified**:
- `front_end/newjfrontend/components/SearchToggle.tsx` — Complete rewrite: new `ResearchMode` type (`'off' | 'live'`), warning dialog with acknowledgment flow, amber Globe icon when active, session-level acknowledgment state
- `front_end/newjfrontend/components/chat-input.tsx` — Updated to pass `researchMode` to SearchToggle, wire mode changes to chat request headers
- `front_end/newjfrontend/app/page.tsx` — Updated workspace model reference from stale `qwen3:latest` to `qwen3.5-32k:latest`
- `python_back_end/tools/openclaw_proxy.py` — Major expansion (~594 lines added): `browser_proxy_router` for browser tool proxying, `openclaw_tool_audit` table for all tool call auditing, in-memory rate limiting (configurable via env vars), domain allowlist/denylist (`OPENCLAW_WEB_ALLOWLIST`/`OPENCLAW_WEB_DENYLIST`), `_MAX_FETCH_BYTES` limit (2MB), relaxed limits when `X-Live-Web: true` header present (30 searches, 60 fetches per 60s), private-IP/SSRF blocking always enforced
- `python_back_end/tools/__init__.py` — Added `browser_proxy_router` export
- `python_back_end/main.py` — Imported and mounted `browser_proxy_router`, added `openclaw_tool_audit` table auto-creation at startup
- `nginx.conf` — Added proxy routes for `/api/tools/browser/` endpoints
- `skills/Harvis/harvis-research/SKILL.md` — Updated skill definition for web research agent with proxy endpoint usage

---

### 3. Workspace Progress Tracking & Agent Lifecycle Events

**Problem**: Workspace runs showed no intermediate progress — users saw "Starting workspace" then only the final result, with no visibility into tool calls, sub-agent spawning, or errors.

**Solution**: Enhanced the workspace event system with sub-agent tracking fields, agent lifecycle events, and richer DB persistence.

**Files Modified**:
- `python_back_end/workspace/workspace_router.py` — Added `_looks_like_browser_task()` heuristic for auto-enabling browser mode (detects URLs, domains, screenshot keywords), added `_db_enable_interactive()` for Tier 3 capability tokens, expanded `_db_save_event()` to persist `run_id`, `agent_label`, `model`, `parent_run_id` fields, added `InteractiveEnableRequest` model, added `enable_interactive`/`live_web` fields to `LaunchRequest`
- `python_back_end/workspace/openclaw_client.py` — Enhanced WebSocket client with browser hint injection, sub-agent tracking, enriched event parsing
- `front_end/newjfrontend/stores/openclawStore.ts` — Added `run_id`, `agent_label` fields to `WorkspaceLogEvent` type
- `front_end/newjfrontend/hooks/useWorkspaceAgentGraph.ts` — Added agent graph tracking from workspace events
- `front_end/newjfrontend/components/workspace/WorkspacePanel.tsx` — Enhanced timeline rendering with agent lifecycle markers and tool call display
- `front_end/newjfrontend/components/workspace/WorkspaceSuggestionBanner.tsx` — Added SSE reconnection logic
- `python_back_end/workspace/workspace_schema.sql` (NEW) — SQL schema for `workspace_web_caps` table (Tier 3 capability tokens)
- `python_back_end/all_schemas_safe.sql` — Added `workspace_web_caps` and `openclaw_tool_audit` table definitions

---

### 4. Discord Workspace Bot

**Problem**: No Discord integration for workspace tasks. Users couldn't trigger Harvis workspaces from Discord or receive live progress.

**Solution**: Created a Discord bot that bridges workspace launches with live progress updates via DB polling.

**Files Created/Modified**:
- `python_back_end/integrations/discord_workspace_bot.py` (NEW) — Discord bot with `_TOOL_LABELS` mapping for human-readable progress, `_format_progress_line()` for tool/agent event formatting, `_wait_with_progress()` that polls `workspace_events` from DB and edits Discord message every 2.5s (rate-limit safe), cleans up progress message on completion and sends final result
- `openclaw/config/openclaw.json` — Channels config for Discord (currently empty, configured in K8s)
- `openclaw/config/exec-approvals.json` — Updated exec approval rules
- `docker-compose.yaml` — Added OpenClaw Discord channel configuration in environment

---

### 5. Model Proxy & Local Ollama Routing

**Problem**: Model proxy only routed to Kimi/NVIDIA/external Ollama. Local Ollama models (qwen3.5-32k) couldn't be used, and Ollama's `/v1` endpoint choked on non-standard OpenAI fields (`store`, `reasoning_effort`, `stream_options`).

**Solution**: Added local Ollama fallback routing and request sanitization.

**Files Modified**:
- `python_back_end/workspace/model_proxy.py` — Added `LOCAL_OLLAMA_URL` env var, local Ollama fallback route (any unmatched model → local Ollama), `OLLAMA_ALLOWED_KEYS` whitelist to strip non-standard fields, `max_completion_tokens → max_tokens` conversion, auto-set `num_ctx: 32768`, enhanced logging with tool names
- `python_back_end/workspace/kimi_workspace.py` — Added `"reasoning_effort": "none"` to local Ollama payloads so qwen3.5 puts output in `content` field instead of thinking tags
- `front_end/newjfrontend/components/workspace/ModelSelectorDropdown.tsx` — Updated model selector to show local Ollama models from provider discovery endpoint

---

### 6. Browser Runner Service

**Problem**: Needed a standalone browser automation service for fallback/parallel screenshot tasks.

**Solution**: Created a lightweight Flask/Selenium service with Firefox.

**Files Created**:
- `browser_runner/app.py` (NEW) — Flask app with `/screenshot` endpoint, Selenium WebDriver with Firefox headless
- `browser_runner/Dockerfile` (NEW) — Python + Firefox + geckodriver container
- `browser_runner/requirements.txt` (NEW) — Flask, Selenium, Pillow dependencies

---

### 7. Infrastructure & Backend

**Files Modified**:
- `python_back_end/Dockerfile` — Added system dependencies for new features
- `python_back_end/requirements.txt` — Added `trafilatura`, `httpx` dependencies
- `python_back_end/research/extract/html_trafilatura.py` — Updated HTML extraction with trafilatura library
- `python_back_end/vibecoding/user_prefs.py` — Added user preferences table columns at startup
- `python_back_end/main.py` — Auto-creates `user_prefs`, `openclaw_tool_audit`, `workspace_web_caps` tables at startup, fixed default DATABASE_URL from `pgsql-db` to `pgsql`
- `python_back_end/masterprompt5.md` — Updated system prompt for workspace agent

---

### 8. Skills

**Files Created/Modified**:
- `skills/Harvis/harvis-research/SKILL.md` — Updated research skill with proxy endpoint instructions and web research workflow
- `skills/Harvis/harvis-browser/SKILL.md` (NEW) — Browser automation skill definition for OpenClaw agent
- `python_back_end/Openclaw-files-guide.md` (NEW) — Developer guide for OpenClaw file structure

---

### Status

All changes on `experimental/plugin-merge` branch. Ready for testing and merge review.

---

## 2026-02-24: Fix OpenClaw K8s Deployment — Full Debug Session

### Problems Addressed

1. **Pod back-off restart loop** — `harvis-ai-openclaw` was crash-looping in the `ai-agents` namespace
2. **CI pipeline clobbering openclaw image tag** — `ci_pipeline.sh` overwrote the openclaw `newTag` every harvis build
3. **CI pipeline ordering bug** — `ci_openclaw_pipeline.sh` pushed kustomize to git before pushing the image to Docker Hub, so ArgoCD would pull a tag that didn't exist yet
4. **Wrong nodeSelector hostname** — Pod had `Rockyvm2.local` (AI-generated typo); actual node is `rocky2vm.local`
5. **PVC on wrong node** — `local-path` StorageClass scheduled the PVC on `dulc3-os` (control plane); OpenClaw's nodeSelector pointed to `rocky2vm.local` — PV/pod node mismatch
6. **openclaw.json used JSON5 syntax** — Unquoted keys and `//` comments; newer OpenClaw builds require strict `JSON.parse()`
7. **Config schema validation failures** (Zod):
   - `models.providers.ollama.models` was missing (required array of `{id, name}`)
   - `agents.defaults` had unknown key `skills` (schema is `.strict()`)
   - `session.reset.mode: "never"` is not a valid value (only `"daily"` or `"idle"`)
8. **Control UI startup error** — Gateway binding to `lan` required `controlUi.allowedOrigins` or explicit disable
9. **Wrong health probe type** — K8s probes used `httpGet: /health` but OpenClaw only exposes `health` as a WebSocket RPC method, not an HTTP route — always returned 404

### Root Cause Analysis

The crash loop was a cascade: wrong nodeSelector → wrong node for PVC → pod couldn't schedule → after nodeSelector fix, config schema errors → Zod validation failures prevented gateway start → after config fixes, Control UI error → after that fix, `httpGet /health` returned 404 → probes killed pod repeatedly.

The kustomize clobbering was a global `sed "s/newTag: .*/..."` in `ci_pipeline.sh` line 172 that replaced ALL `newTag:` entries including openclaw's on every harvis build.

The PVC issue: k3s `local-path` provisioner pins the PVC to whichever node the pod first schedules on. Since openclaw had the wrong nodeSelector initially, the PVC was bound to `dulc3-os` (control plane). After fixing the nodeSelector, the pod and PVC were on different nodes.

### Solutions Applied

#### 1. `ci_pipeline.sh` — Targeted per-image kustomize replacement
Replaced the global `sed` with a Python regex that only updates harvis images, leaving the openclaw `newTag` untouched.

#### 2. `ci_openclaw_pipeline.sh` — Fixed push ordering
Reordered: Docker Hub push first → kustomize update → git commit → git push. ArgoCD now always finds the image before syncing.

#### 3. `k8s-manifests/overlays/prod/openclaw.yaml` — Static PV on rocky2vm.local
Deleted the `local-path` PVC. Created a static PersistentVolume (`openclaw-data-rocky2`) with explicit `nodeAffinity` for `rocky2vm.local`, `Retain` reclaim policy, and `local.path: /var/lib/openclaw-data`. Updated PVC to use `storageClassName: ""` + `volumeName: openclaw-data-rocky2` for a forced 1:1 bind. Fixed `nodeSelector` typo.

#### 4. `openclaw.json` ConfigMap — Full schema-compliant strict JSON config
```json
{
  "gateway": {
    "bind": "lan", "port": 18789,
    "auth": {"mode": "token"},
    "controlUi": {"enabled": false}
  },
  "session": {
    "scope": "per-sender",
    "maintenance": {"pruneAfter": "90d", "maxEntries": 2000}
  },
  "models": {
    "mode": "replace",
    "providers": {
      "ollama": {
        "baseUrl": "http://harvis-ai-merged-backend:11434",
        "apiKey": "ollama-local",
        "models": [{"id": "gpt-oss:latest", "name": "GPT-OSS"}]
      }
    }
  },
  "agents": {"defaults": {"model": {"primary": "ollama/gpt-oss:latest"}}},
  "skills": {"load": {"extraDirs": ["/skills"]}},
  "channels": {}
}
```

#### 5. Harvis Agent SKILL.md ConfigMap
Created `harvis-agent-skill` ConfigMap with a full OpenClaw skill prompt (`/skills/harvis-agent/SKILL.md`). The skill defines the agent's identity, task routing table (`coder`/`researcher`/`writer`/`planner`), JSON response format, and security guardrails. Mounted via `subPath` into the OpenClaw pod at `/skills/harvis-agent/SKILL.md` (read-only).

#### 6. Health probes — `tcpSocket` instead of `httpGet`
OpenClaw's `health` is a WebSocket JSON-RPC method, not an HTTP GET route. The HTTP server returns 404 for `/health`. Switched both `livenessProbe` and `readinessProbe` to `tcpSocket: port: 18789`.

### Files Modified

- `ci_pipeline.sh` — Targeted Python regex for per-image kustomize update
- `ci_openclaw_pipeline.sh` — Push ordering: Docker Hub first, then kustomize
- `k8s-manifests/overlays/prod/openclaw.yaml` — Static PV, corrected nodeSelector, schema-compliant config, Harvis Agent SKILL.md ConfigMap, tcpSocket probes

### Final State

```
harvis-ai-openclaw-56fc97f8d6-wt25k   1/1   Running   0   stable
[gateway] agent model: ollama/gpt-oss:latest
[gateway] listening on ws://0.0.0.0:18789 (PID 13)
[heartbeat] started
[health-monitor] started
```

---

## 2026-02-16: Add Ansible Playbooks to RAG VectorDB with Qwen3 Embedding

### Problem
The RAG corpus system supported various documentation sources (Kubernetes, Docker, Python, etc.) but lacked support for Ansible playbooks. Ansible playbooks are complex YAML files with Jinja2 templating, role hierarchies, and variable structures that require high-dimensional embeddings for semantic understanding.

### Root Cause
No fetcher existed to parse and index Ansible playbook content. The RAG system needed a specialized fetcher that could handle:
- YAML with Jinja2 templates (`{{ variable }}`)
- Role directory structures (tasks/, handlers/, vars/, defaults/, meta/)
- Module invocations with complex parameters
- Variable files and inventories
- Playbook structural analysis

### Solution Applied
Implemented full Ansible playbook support using the high-tier `qwen3-embedding` model (4096 dimensions) for complex technical content.

#### Files Modified:

1. **Backend Fetcher** (`python_back_end/rag_corpus/source_fetchers.py`)
   - Added `AnsiblePlaybookFetcher` class (~300 lines)
   - Recursively scans directories for `.yml`/`.yaml` files
   - Detects file types: tasks, handlers, variables, templates, inventories, playbooks
   - Extracts role names from directory structure
   - Parses YAML to identify modules used
   - Enriches content with structural metadata for better embedding
   - Updated `get_fetcher_for_config()` to handle "ansible" fetcher type
   - Updated `get_fetcher()` to support "ansible_playbooks" source

2. **Backend Routes** (`python_back_end/rag_corpus/routes.py`)
   - Added `ansible_playbooks` to `SOURCE_EMBEDDING_MODELS` with `qwen3-embedding`
   - Added `ansible_paths` field to `UpdateRagRequest` model
   - Updated job creation to pass `ansible_paths` parameter

3. **Job Manager** (`python_back_end/rag_corpus/job_manager.py`)
   - Added `ansible_paths` field to `Job` dataclass
   - Updated `create_job()` to accept `ansible_paths` parameter
   - Updated `_get_fetcher()` to handle ansible_playbooks source

4. **Frontend Settings** (`front_end/newjfrontend/app/settings/page.tsx`)
   - Added `ansible_playbooks` to `SOURCE_CONFIG` in "devops" group
   - Added state variables for ansible paths input
   - Added `addAnsiblePath`/`removeAnsiblePath` handler functions
   - Added Ansible paths input UI section (red-themed to match branding)
   - Updated `handleStartUpdate` to include `ansible_paths`

5. **TypeScript Types** (`front_end/newjfrontend/lib/rag.ts`)
   - Added `ansible_paths?: string[]` to `RagUpdateRequest` interface

### Features:
- Uses `qwen3-embedding` (4096 dims) for high-fidelity semantic search
- Parses YAML structure to extract playbook metadata
- Detects Jinja2 templates and marks content accordingly
- Identifies Ansible modules used in playbooks
- Supports role directory structures (`roles/<name>/tasks/main.yml`, etc.)
- UI input for specifying local playbook directories
- Works with complex playbooks containing nested structures

### Result
Users can now:
1. Go to Settings page
2. Select "Ansible Playbooks" source (in DevOps section)
3. Enter paths to local directories containing Ansible content
4. Click "Start Update" to index playbooks into the VectorDB
5. Query the RAG corpus for Ansible-related questions

The system uses Qwen3's high-dimensional embeddings to capture nuanced relationships in complex Ansible configurations, including Jinja2 templating patterns, module parameters, and role dependencies.

---

## 2026-02-15: Add Image Copy/Paste Support to Chat Input

### Problem
Users needed to manually select images from file system. They couldn't simply copy and paste images directly into the chat interface.

### Root Cause
The chat input textarea component didn't have any paste event handling for image files.

### Solution Applied
Added clipboard paste event handling to the chat input component that detects and processes pasted images.

**File:** `front_end/newjfrontend/components/chat-input.tsx`

#### Changes Made:

1. **Added `handlePaste` function** (lines 140-190)
   - Intercepts paste events on the textarea
   - Checks `e.clipboardData.items` for image data (screenshots, copied from browser)
   - Checks `e.clipboardData.files` for file data (copied from file manager)
   - Filters for supported image types (png, jpeg, gif, webp)
   - Prevents image data from being pasted as text into textarea

2. **Added `processImageBlob` helper function** (lines 192-212)
   - Converts pasted image blob to base64
   - Creates ImageAttachment object with proper metadata
   - Adds to attachments state for display

3. **Attached handler to Textarea** (line 848)
   - Added `onPaste={handlePaste}` prop to the Textarea component

4. **Updated placeholder text** (line 854)
   - Changed from `"Ask anything..."` to `"Ask anything... (paste images to analyze)"`
   - Users now know paste is supported

### Features:
- ✅ Paste screenshots directly (Cmd/Ctrl+Shift+3/4 on Mac, PrintScreen on Windows)
- ✅ Paste copied images from browser/web pages
- ✅ Paste images copied from file manager
- ✅ Supports all existing image types (PNG, JPEG, GIF, WebP)
- ✅ VL model requirement check (same as file upload)
- ✅ Multiple images can be pasted at once
- ✅ Works alongside existing upload methods (file picker, drag-drop if implemented)

### Result
Users can now:
1. Take a screenshot
2. Copy any image from the web or file manager
3. Press Ctrl+V (or Cmd+V) while focused in the chat input
4. The image immediately appears as an attachment
5. Type a message and send - the AI will analyze the image

---

## 2026-04-24 10:34 PDT - OpenClaw file-analysis exec allowlist fix

### Problem
OpenClaw Discord tasks that needed to download and analyze attached files (`auth.log`, `access.log`) stalled after `Connected to OpenClaw gateway (agent: main)` and then either went silent or fabricated answers instead of extracting values from the file.

### Root Cause
Runtime evidence from the live `harvis-openclaw` container showed `exec failed: exec denied: allowlist miss`. The host-side `openclaw/config/bundled/exec-approvals.json` had been updated, but the running container was still using an older mounted copy with `"agents": {}` until it was restarted. That prevented the `main` agent from using `exec` to run `curl`, `grep`, `awk`, or even setup commands like `mkdir`.

### Solution Applied
1. Verified the live container was still reading the stale approvals file.
2. Expanded the `main` agent allowlist in `openclaw/config/bundled/exec-approvals.json` to include the file-analysis command set plus common setup/coreutils (`env`, `mkdir`, `mktemp`, `cp`, `mv`, `rm`, `touch`, `pwd`, `dirname`, `basename`, `tee`).
3. Restarted `harvis-openclaw` so the container remounted/reloaded the updated approvals file.
4. Verified inside the live container that `/home/node/.openclaw/exec-approvals.json` now contains the new `main.allowlist`.

### Files Modified
- `openclaw/config/bundled/exec-approvals.json`
- `front_end/newjfrontend/changes.md`

### Result / Status
- OpenClaw now has the live allowlist needed to run attachment download and text-file extraction commands.
- Previous `exec denied: allowlist miss` failures were confirmed in logs before the restart.
- Ready for Discord re-test to confirm the next file-analysis task completes end-to-end with concrete answers.

---

## 2026-04-24 11:09 PDT - OpenClaw attachment tasks were acknowledging instead of acting

### Problem
After the exec allowlist fix, some Discord/OpenClaw attachment tasks still completed with a useless acknowledgment like `Copy that. Standing by.` instead of actually analyzing the attached image or file. The user also reported that the agent should admit uncertainty rather than hallucinate.

### Root Cause
Runtime evidence showed the latest workspace run finished `done` with `tool_calls = 0` and final summary `Copy that. Standing by.`. That proved the failure was no longer an exec denial; the model was taking a non-executing acknowledgment path. The attachment-bearing task text was not forceful enough about "inspect the attachment first" and the bundled prompts did not explicitly ban acknowledgment-only completions.

### Solution Applied
1. Updated `python_back_end/workspace/workspace_router.py` so any task with `[Attached files from the user]` gets an `[Execution rules]` block appended that:
   - forces attachment inspection before answering
   - routes image attachments to `harvis-image`
   - routes text/log/data attachments to `harvis-file`
   - forbids `Copy that` / `Standing by` / acknowledgment-only replies
   - requires explicit uncertainty instead of guessing when the answer cannot be determined confidently
2. Added backend debug instrumentation logging the final attachment-augmented prompt preview at launch time.
3. Hardened bundled prompts/skills:
   - `openclaw/config/bundled/AGENT.md`
   - `openclaw/skills/bundled/harvis-agent/SKILL.md`
   - `openclaw/skills/shared/harvis-image/SKILL.md`
   - `openclaw/skills/shared/harvis-file/SKILL.md`
   so attachment tasks must use tools first and must report uncertainty rather than hallucinate.

### Files Modified
- `python_back_end/workspace/workspace_router.py`
- `openclaw/config/bundled/AGENT.md`
- `openclaw/skills/bundled/harvis-agent/SKILL.md`
- `openclaw/skills/shared/harvis-image/SKILL.md`
- `openclaw/skills/shared/harvis-file/SKILL.md`
- `front_end/newjfrontend/changes.md`

### Result / Status
- Attachment tasks now carry an explicit act-first contract at launch time.
- Bundled OpenClaw prompts now classify acknowledgment-only replies as invalid completions.
- Next Discord re-test should show either real tool usage and extracted answers, or a truthful "I couldn't determine it confidently" response instead of hallucinated output.

---

## 2026-05-04: Workspace memory was overriding new tasks ("you're a firefighter" reply to a CTF prompt)

### Problem
After enabling `WORKSPACE MEMORY` for Discord, the bundled agent began
treating pinned conversation memory as the answer to whatever the user
asked next. Repro: with prior history `i am a fire fighter` /
`You're a firefighter.`, the user sent a hash-cracking task
("solve these MD5s, rockyou breach"). The agent replied:

> You're a firefighter. Yo, what's next?

with `tool_calls=0`. Subsequent turn called only `memory_search` and
echoed `You are a firefighter.` again — never engaged the new task.

### Root cause
1. The runtime directive treated `WORKSPACE MEMORY` as authoritative for
   user facts, but did not say *the current user request always
   overrides it*. The model used the most recent assistant reply as the
   template for its next answer.
2. `last_user_msg` in `openclaw_client.stream` was computed from the
   tail of `chat_history` first, not from the new `task_brief`. That
   meant the terminal-task / corrective-retry detector ran against the
   stale prior message ("what is my job") instead of the rockyou prompt,
   so `_looks_like_terminal_execution_task` returned False and the
   retry block was skipped.
3. The corrective retry guard required `not saw_tool_call`. A retrieval
   tool like `memory_search` would flip that flag, blocking the retry
   even when the model had done no real work.

### Solution
`python_back_end/workspace/openclaw_client.py`:
- Demoted `WORKSPACE MEMORY` in the directive: it is BACKGROUND CONTEXT
  ONLY. The current user request is always more important; the agent
  must not reuse a prior chat answer (e.g. "You're a firefighter.",
  "Yo, what's next?") for a new task. The `WORKSPACE MEMORY` block in
  the prompt was relabeled accordingly.
- Made `last_user_msg` prefer the explicit `task_message` (task brief)
  over the chat history tail, so terminal-task detection runs against
  the actual current request.
- Extended `_looks_like_terminal_execution_task` to recognize
  CTF/cracking prompts: `decrypt`, `crack`, `hash`, `rockyou`,
  `wordlist`, plus auto-detect 2+ lines of MD5/SHA hex strings.
- Added `_looks_like_memory_echo` to detect short stale-memory replies
  ("you're a firefighter", "yo what's next", "got it", "standing by",
  etc.) and treat them as a failure signal for the retry block.
- Tracked `saw_executing_tool_call` separately from `saw_tool_call`.
  Retrieval-only tools (`memory_search`, `memory_get`,
  `sessions_history`, `sessions_list`, `sessions_send`,
  `session_status`, `agents_list`) no longer satisfy the "agent did
  real work" check, so a memory probe followed by a stale chat reply
  now triggers the corrective retry.
- Strengthened the corrective-retry prompt to say "Ignore prior chat
  memory for this task — the user request below is the only goal."

### Result
Verified by relaunching the same rockyou prompt (workspace `8c381552`)
with the firefighter chat history pinned in memory. The agent:
1. Wrote `analyze_hashes.py` via the `write` tool.
2. Ran it via `exec` and observed the actual hex output.
3. Returned a candid summary explaining the strings are hex digests and
   that cracking them needs brute force / dictionary attacks beyond a
   single script — instead of echoing memory.

`tool_calls=2`, `event_count=10`, no failed tool calls, no memory echo.

## 2026-06-01: OWUI chat re-open infinite spinner + /api/v1 404 storm

### Problem
Leaving a chat and opening it again left the UI on an endless loading spinner.
Browser console showed many `404` on `/api/v1/*` (settings, tools, banners, folders,
tags, profile images) plus `TypeError: e is not iterable` when reloading chat
history.

### Root cause
1. Harvis OWUI facade (`owui_compat/router.py`) implemented auth, models, and chat
   CRUD but not the ancillary v1 routes the OWUI layout and `Chat.svelte` call on
   every navigation.
2. `GET /api/v1/chats/{id}/tags` was missing; tag fetch threw and broke reload.
3. `convertMessagesToHistory()` iterated `undefined` when a saved chat blob had no
   `messages` / `history` yet → `e is not iterable`.
4. `navigateHandler` set `loading = true` but only cleared it on success; any thrown
   error left the spinner forever.

### Solution
- Added `python_back_end/owui_compat/stubs.py` with safe empty/default responses for
  settings, tools, folders, banners, terminals, profile images, chat tags, etc.
- `Chat.svelte`: try/catch/finally on navigate; guard empty history; catch `setDefaults`.
- `convertMessagesToHistory`: tolerate missing/non-array `messages`.
- `getTagsById`, `getTools`, `getBanners`: return `[]` instead of throwing on 404.
- Rebuilt `front_end/owui/build` for nginx.

### Result
Stub endpoints return `200`. Chat re-open should complete or redirect home instead of
spinning indefinitely. Hard-refresh the browser after deploy (`Ctrl+Shift+R`).
