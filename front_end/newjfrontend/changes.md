## 2026-03-31: Enable Vision for Qwen3.5 27B (llama.cpp)

### Problem
Image upload/paste/screenshare UI was disabled when "Qwen3.5 27B (llama.cpp Local)" was selected. The `isVisionModel()` gate in `types/message.ts` pattern-matched against `VL_MODEL_PATTERNS` but `'qwen3.5'` was not in the list, so the image controls stayed grayed out. On the backend, `stream_vision_chat()` had no llama.cpp routing branch — it only handled NVIDIA, Moonshot, and Ollama, so even if the frontend allowed image upload, the backend would have sent the request to Ollama with the wrong payload format.

### Root Cause
1. `VL_MODEL_PATTERNS` in `front_end/newjfrontend/types/message.ts` lacked `'qwen3.5'`
2. `stream_vision_chat()` in `python_back_end/main.py` had no `elif` branch for llama.cpp models before the Ollama `else` fallback

### Solution

**Frontend** (`front_end/newjfrontend/types/message.ts`, line 167):
- Added `'qwen3.5'` to `VL_MODEL_PATTERNS`
- `isVisionModel('qwen3.5:27b')` now returns `true`, enabling image upload/paste/screenshare buttons

**Backend** (`python_back_end/main.py`, around line 4388):
- Added `elif req.model.lower().startswith("qwen3.5") or req.model.lower().startswith("qwen3")` branch before the Ollama `else` in `stream_vision_chat()`
- Builds an OpenAI-compatible `image_url` content block payload
- POSTs to `LLAMA_URL/chat/completions` (non-streaming, 300s timeout)
- Logs `🖼️ VISION: Using llama.cpp (...)` for observability

### Files Modified
- `front_end/newjfrontend/types/message.ts`
- `python_back_end/main.py`

### Result
Selecting Qwen3.5 27B unlocks image controls in the UI. Pasting/uploading an image and asking a question routes to llama.cpp via `LLAMA_URL/chat/completions` with the `image_url` multimodal payload that llama.cpp + mmproj expects. Requires rebuild + redeploy of frontend and backend images.

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
