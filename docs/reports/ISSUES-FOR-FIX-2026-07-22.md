# Harvis — testing bug report for fix pass (2026-07-22)

> **Provenance:** authored on the Windows/WSL deploy tree during a full manual test pass, captured
> here in the canonical tree (`/home/user/Harvis`) so it survives a Windows
> working-tree wipe. Section 0's "local deltas" describe the **Windows deployment**, not this tree.
> Companion doc with the install-mechanics findings: `docs/reports/2026-07-20-windows-install-e2e-findings.md`.

Branch: `harvis1.1-deploy-test`. Deploying/testing on Windows (Docker Desktop + WSL2 Ubuntu, RTX 5080
rig). Stack is **up and login/chat/inference work**. This doc is a prioritized, root-caused list of
everything found in a full manual test pass, for another agent to fix in the repo → repush → retest.

Evidence is cited as `path:line`. "Fix" = suggested direction, not necessarily the only one.

---

## 0. Deploy-state deltas already applied locally (NOT yet in the repo)

The running Windows deployment differs from a clean checkout. Fold the good ones into the repo
properly; they are quick local hacks right now.

- **`docker-compose.yaml`: `ollama` service → `alpine/socat` forwarder** to native Windows Ollama
  (`TCP:host.docker.internal:11434`). Rig-specific; the real repo should keep the GPU ollama container.
  Kept the service *name* so all `http://ollama:11434` refs work. **All inference in this deployment
  rides the native Ollama's 8 models.**
- **`docker-compose.yaml`: `pull_policy: build` added to 7 services** (`owui-builder`,
  `messaging-gateway`, `opencode`, `codex`, `claude-code`, `hermes-agent`, `cad-engine`). Issue 14 —
  **this one belongs upstream.**
- **`docker-compose.yaml`: added `DEEP_RESEARCH_MODEL` to backend `environment:`** (Issue 4).
- **`.env` additions**: `HARVIS_OWUI_ENABLE_SIGNUP=true`, `HARVIS_OWUI_IMAGE_GENERATION=true`,
  `DEEP_RESEARCH_MODEL=gemma4:e4b`, `WORKSPACE_DETECTOR_OLLAMA_MODEL=granite4.1:8b`,
  `MESSAGING_GATEWAY_TOKEN=<set>`.
- **`openclaw/config/{bundled,shared}/*` seeded by hand** — gitignored (`.gitignore:134`), never
  committed. Issue 15. On a fresh clone the backend crashloops without these.
- **3 DB migrations applied manually** (Issue 13).
- **`harvis-messaging-gateway` stopped** (Issue 8).

---

## P0 — BLOCKERS

### 1. OpenClaw device pairing fails → workspace + build dead
**Symptom:** Workspace panel: `OpenClaw connect handshake failed: pairing required: device is not
approved yet`. Because build depends on workspace, build is also dead.
**Root cause:** NOT a token/config error. Tokens match (backend & gateway both `858c…`). Backend
requests `role: operator` + `scopes:["operator.admin"]` (`python_back_end/workspace/openclaw_client.py:172,807`),
exactly what should trigger OpenClaw's `skipPairingForOperatorSharedAuth` auto-bypass (documented in
that file's own docstring, lines 22-38). **The pinned OpenClaw `v2026.5.22` does not honor it** — the
gateway logs `update available: v2026.7.1-2`. Version mismatch between the client code's expectation and
the container's OpenClaw.
**Fix:** Bump `openclaw@2026.5.22` → `2026.7.1-2` in `openclaw-browser/Dockerfile`, rebuild, retest the
handshake. If the newer version still rejects, fall back to explicit `openclaw devices approve` on first
connect (backend persists its device key at `/data/artifacts/openclaw-device-key.pem`, so approval
sticks across restarts).
**Also requested:** OpenClaw should use the Ollama models by default — it already routes via provider
`harvis-proxy` → `http://backend:8000/v1` in the seeded `openclaw.json`, so once pairing works it uses
Ollama through the backend proxy. Verify the model list matches installed models.

### 2. Cannot switch chat model off `llama3.1:8b`
**Symptom:** User can't change the active chat model; features hard-fail on `llama3.1:8b` which isn't
pulled.
**Root cause:** Needs frontend investigation — the model selector isn't changing the model the backend
uses for these flows. Related to Issue 4. Likely the frontend isn't sending the chosen model to the
relevant endpoints, and several backends fall back to a hardcoded `llama3.1:8b` default.
**Fix:** Trace the chat model selector → which field it sets → whether backend endpoints read it. Make
`llama3.1:8b` defaults resolve to an installed model or the user's selection.

---

## P1 — OUT-OF-BOX CONFIG (should work by default)

### 3. Image generation (two symptoms, same gap)
**Symptoms:** (a) `Image generation is disabled on this deployment (enable_image_generation flag off)`.
(b) With the flag on, the model hallucinates a fake `dalle.text2im` action and no image appears.
**Root cause:** (a) `HARVIS_OWUI_IMAGE_GENERATION` defaults `false` (`docker-compose.yaml:287`, read at
`python_back_end/owui_compat/config.py:59`). (b) **There is no image-generation backend wired** (no
ComfyUI/SD service). The flag only enables the UI path; nothing actually generates.
**Fix:** Decide the default image backend (ComfyUI service?), wire it, and default the flag `true` only
once a backend exists. Otherwise "on" produces the hallucinated DALL-E output — worse than an honest
"disabled." *(Cross-ref: the image backend code exists at `python_back_end/image/{comfyui,a1111,provider}.py`
— it is not started as a service in compose.)*

### 4. Deep research: 404 on `llama3.1:8b`, and ignores selected model
**Symptoms:** `Cannot reach model 'llama3.1:8b' at http://ollama:11434 … 404 … /api/chat`, and research
doesn't adapt to the chat-selected model.
**Root cause:** `DEFAULT_RESEARCH_MODEL = os.getenv("DEEP_RESEARCH_MODEL", "llama3.1:8b")`
(`python_back_end/deep_research/router.py:54`). Not pulled. Also the var was **not in the compose
backend `environment:` block**, so `.env` never reached the container. `router.py:123` accepts
`body.model` per request, but the frontend doesn't send it.
**Fix (partly applied locally):** Added `DEEP_RESEARCH_MODEL` to compose env (now `gemma4:e4b`) — kills
the 404. **Remaining:** frontend should pass the selected chat model as `body.model` to `/api/research`.

### 5. Web search returns 0 sources
**Symptom:** Web search / research retrieves nothing.
**Root cause:** Research uses **SearXNG** (`python_back_end/deep_research/researcher.py:169`) and there
is **no SearXNG service running**. Error path at `researcher.py:310`. Brave/Tavily are alternatives but
need keys.
**Fix:** Add a self-hosted SearXNG service to compose (no key needed) and point the researcher at it by
default, or document a provider-key path.

### 6. llmfit "device offline" + hardcoded "rig" node
**Symptoms:** Models tab says the device is offline; llmfit doesn't auto-list models; a node named
**"rig"** appears next to **main-host**.
**Root cause:** (a) The **`llmfit` service is not running** — the container doesn't exist in this
deployment; backend can't reach `http://llmfit:8787` → "offline." (b) **"rig" is a hardcoded example
subhost** in `python_back_end/cookbook/config.py:41` (alongside `"main-host"` at :33).
**Fix:** (a) Ensure `llmfit` starts with the stack (GPU-passthrough; verify it comes up). (b) Remove the
baked-in "rig" node from `cookbook/config.py` default; make extra nodes opt-in via `COOKBOOK_NODES` /
`COOKBOOK_<NAME>_LLMFIT` env (mechanism exists per the comment at `config.py:40`).

---

## P2 — NEEDS A SERVICE / BUILD FIX

### 7. Open Notebook unreachable (`/onb` → 502)
**Root cause:** The **`open-notebook-ui` image failed to build** — `npm run build` fails, module not
found `./src/lib/hooks/use-credentials.ts` (`front_end/open-notebook/Dockerfile:15`). nginx's `/onb`
upstream has nothing behind it.
**Fix:** Repair the missing/broken import in the open-notebook frontend source, rebuild.

### 8. messaging-gateway crash loop
**Root cause:** First `MESSAGING_GATEWAY_TOKEN is not set — refusing to start`; after setting it, `no
adapters enabled; exiting` (Discord/Slack bridge with no platform configured). Currently stopped locally.
**Fix:** Profile-gate this service so it doesn't start (or crash) unless a messaging platform is
configured.

---

## P2 — FRONTEND (prebuilt OWUI SPA — needs source rebuild)

### 9. Providers menu: sidebar overlaps/blurs content
**Fix:** CSS/layout — content area should offset by the sidebar width, not sit under it.

### 10. Projects menu: same overlap bug as Providers (Issue 9).

### 11. Chat sessions not saved properly
**Status:** Partial — `owui_chats` table has rows (4), so *some* saving happens. Needs deeper repro: is
it the save call, the list/reload, or per-session? Check `/api/v1/chats*` + `owui_chats` writes.

---

## P2 — NEEDS PER-DEPLOY CREDENTIALS (inherently not "out of box")

### 12. GitHub OAuth / Connectors
**Symptoms:** "Connect GitHub" broken; `XHR GET /api/vibecode/github/start → 500`; Connectors: "Could
not load your connections."
**Root cause:** `GITHUB_CLIENT_ID` and `HARVIS_GITHUB_APP_ID` empty. `vibecoding/auth_github.py:132`
errors when unset → 500. Connectors list hits `/api/owui/mcp/connections`
(`owui_compat/connections.py:72`).
**Fix:** GitHub OAuth needs a real OAuth App per deployment. Streamline: (a) hide/grey the Connect button
when unconfigured with a clear hint instead of a 500; (b) document a one-time OAuth setup, or use device
flow to avoid a callback URL.

### 13. Missing DB migrations (applied manually — fold into init)
**Symptom:** Backend spams `relation "cron_jobs"/"workspace_jobs"/"workspace_runs" does not exist`.
**Fix:** Add a migration runner, or fold `migrations/014_cron_jobs.sql`, `workspace/workspace_schema.sql`,
`front_end/newjfrontend/db/migrations/002_add_workspace_jobs.sql` into `init-db.sh`.

### 14. `docker compose up -d` fails without `--build` (FIX BELONGS UPSTREAM)
**Symptom:** `pull access denied for harvis-owui-builder / -codex / …`.
**Root cause:** Services declaring `image: harvis-*:local` make Compose treat the tag as a registry ref.
**Fix (applied locally):** `pull_policy: build` on the 7 tagged services.

### 15. openclaw config tree not shipped (FRESH-CLONE KILLER)
**Symptom:** On a clean clone, `backend` never starts because `openclaw` crashloops (`EISDIR` reading
`openclaw.json`).
**Root cause:** `.gitignore:134` ignores `openclaw/` wholesale; `openclaw/config/bundled/` and `shared/`
were never committed. Compose bind-mounts six files → Docker creates empty **directories** → OpenClaw
reads a dir as config → crashloop → `backend depends_on: openclaw` → nothing starts. The
`harvis_openclaw-data` **volume** caches the same broken shape; clean inside the volume too.
**Fix:** Commit a sanitized `openclaw/config/` template tree (`git add -f`), or have `install.sh`
generate it.

---

## Works (verified) — do not regress
- Model comparison · Video transcript · Schedule · Core chat + inference (native Ollama via forwarder),
  login, signup (flag on).

## Feature request
- **Intro / tutorial guide**: an onboarding walkthrough (chat, workspace/build, research, connectors).
  Nice-to-have after P0/P1.

---

## Fresh-clone repro summary (for retest after fixes)
On a clean checkout, expect, in order: #15 (openclaw config missing) → stack won't start → #14
(pull_policy) if not using `--build` → #13 (missing migrations) → #1 (openclaw pairing) → the
config/service issues above. Fixing #15, #14, #13 first gets you a running stack; #1 unblocks
workspace+build; the rest are feature-level.
