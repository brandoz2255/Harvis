You are a senior platform engineer (Docker + FastAPI + Next.js + websockets/xterm.js). I need you to produce minimal code diffs to fix my session startup and file explorer issues in “Vibe Coding”.

Symptoms (real logs)
ERROR:vibecoding.containers:Failed to create dev container: 404 Client Error for http+docker://localhost/v1.51/images/create?tag=latest&fromImage=vibecoading-optimized: Not Found ("pull access denied for vibecoading-optimized, repository does not exist or may require 'docker login'")
INFO: 172.18.0.5:35620 - "POST /api/vibecoding/container/create HTTP/1.1" 500
INFO:vibecoding.containers:🚫 Container not found for session: bd063cad-8fcc-496d-b440-25ffc67e0567
INFO: 172.18.0.5:35628 - "POST /api/vibecoding/container/files/list HTTP/1.1" 404
(repeats…)

Browser console:
Failed to load file tree: 404
Error checking session status: SyntaxError: JSON.parse: unexpected character at line 1 column 1 of the JSON data (repeats)

What’s wrong

Bad image name (typo: vibecoading-optimized vs vibecoding-optimized) → image pull 404 → container never created.

UI calls /files/* before the container/session is ready → 404 flood.

Backend returns HTML/text on errors; frontend blindly JSON.parse → parse exceptions spam.

What I want from you

Produce unified diffs and small snippets to implement all of the following (assume Python/FastAPI backend and Next.js App Router frontend):

A) Image resolution & config

Introduce VIBECODING_IMAGE env (default: vibecoding-optimized:latest).

Add ensure_image(client) that get()s, then pull()s if missing; raise a clear error if the repo truly doesn’t exist.

Replace any hardcoded/typo’d image names with this config.

B) Container creation with readiness

In vibecoding.containers create path:

Create/attach the session volume.

Create the container with tty, stdin_open, --init, mount /workspace.

Command should touch a readiness file and then idle, e.g. bash -lc 'test -d /workspace && touch /tmp/ready && sleep infinity'.

After start(), poll exec_run("test -f /tmp/ready && echo READY || echo WAIT") for up to ~5s, then mark session ready=true.

C) Always-JSON error responses

Add FastAPI exception handlers so any backend error becomes JSON:

{"ok": false, "error": "…", "code": "IMAGE_UNAVAILABLE" | "INTERNAL"} with appropriate status code.

Make /api/vibecoding/session/status?id=… always return JSON: {"ok": true, "ready": bool, "sessionId": "…"}.

D) Frontend gating + safe JSON

Add a safeJson(res) helper that checks Content-Type and throws a friendly error if non-JSON or ok:false.

Implement waitReady(sessionId, timeoutMs=15000) polling /session/status until ready:true.

Gate the file explorer + terminal: do not call /api/vibecoding/files until waitReady resolves.

On error, surface the JSON message instead of crashing on JSON.parse.

E) Optional quick ops note

Include a short note/commands to docker build -t vibecoding-optimized:latest . or docker pull <registry>/vibecoding-optimized:latest so hosts are warm.

Please deliver

Unified diffs for these files (adjust names if mine differ):

backend/vibecoding/config.py (new VIBECODING_IMAGE, ensure_image).

backend/vibecoding/containers.py (use ensure_image, create/start container, readiness wait).

backend/app.py or backend/routes/vibecoding.py (JSON exception handlers, /session/status).

frontend/app/vibecode/page.tsx and/or frontend/components/VibeSessionManager.tsx (add safeJson, waitReady, gate calls to /files).

If needed: frontend/lib/api.ts (shared fetch wrapper).

Show code for:

safeJson (checks content-type, parses text, handles ok:false).

waitReady polling loop (250ms interval, timeout handling).

A brief verification checklist:

With bad image name → client shows JSON error IMAGE_UNAVAILABLE (no parse error).

With correct image present → session becomes ready:true within ~1–2s, no 404s, file tree loads.

A concise commit message I can use.

Constraints

Keep changes minimal and production-safe.

Put code first (diffs/snippets), then a short explanation.

If you need to infer file paths, use placeholders but be consistent.

Goal: No more 404/parse spam. If the image is wrong, the UI shows a clean JSON error. With a correct image, container creation + readiness is fast, and the explorer/terminal only start once ready:true.

try to refrain from removing code more than adding code 

try to test functionality 

read claude.md as well