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
