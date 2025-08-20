You are a senior platform engineer (FastAPI + Docker + Next.js App Router + websockets/xterm.js + Nginx). I need a production-ready, reliable fix for session/container startup, JSON handling, and WebSocket stability in my “Vibe Coding” app.


Context / symptoms (real)

Frontend dev at http://localhost:9000 (Next.js). Backend FastAPI at http://localhost:8000.

Errors seen:

API Response Error: Expected JSON response but got text/html …

GET http://localhost:9000/api/vibecoding/session/status?... 404

500 Internal Server Error from /api/vibecoding/session/status

WebSocket 500 for ws://localhost:9000/api/vibecoding/container/<id>/fs-events

Image pull/name issues previously (vibecoding-optimized:latest).

Behavior: client polls status immediately; container may not exist; frontend assumes JSON; WS routed via Next rewrites; repeated error spam.

Goals

Make this production-grade and fast:

JSON-only API (never HTML) with typed errors.

Correct routing: browser calls FastAPI directly for HTTP & WS.

Robust session status + gating (no pre-ready calls).

Reliable container create/start with readiness probe.

Observability (structured logs, timings, request IDs).

Reasonable timeouts, retries with backoff, dedupe to avoid spam.

Nginx prod proxy config (HTTP + WS), CORS/auth sane defaults.

Optional warm image/volume steps to avoid cold start.

Deliverables

Produce unified diffs and/or complete files for ALL items below (use my paths; if they differ, pick clear placeholders and be consistent). Include comments where helpful. Keep changes minimal but production-safe.

1) Frontend: route to backend directly + robust fetch & WS

a) .env.local

NEXT_PUBLIC_API_BASE_URL=http://localhost:8000


b) frontend/lib/api.ts

Export API_BASE and WS_BASE (HTTP→WS transform), trimming trailing slashes.

safeJson(res): verify Content-Type includes application/json; parse .text(); if not JSON, throw NON_JSON_<status>.

waitReady(sessionId, { timeoutMs=30000, interval=300 }): poll ${API_BASE}/api/vibecoding/session/status?id=... with backoff; stop on non-retryable errors (INTERNAL, IMAGE_UNAVAILABLE, CREATE_FAILED); dedupe polling per session.

Diff: replace any fetch('/api/vibecoding/...') with ${API_BASE}/api/vibecoding/....

c) WebSocket usage (file watcher & terminal)

Use new WebSocket(\${WS_BASE}/api/vibecoding/container/${sessionId}/fs-events`)`.

Do not proxy WS through Next rewrites.

Add connection dedupe & exponential reconnect (cap 10s) with jitter.

d) Components (VibeSessionManager.tsx, MonacoVibeFileTree.tsx)

Gate file tree & WS until await waitReady(sessionId) resolves.

On error, show a single banner/toast; prevent repeated retries by using a ref/flag keyed by sessionId.

2) Backend FastAPI: JSON-only responses + status route + typed errors

a) backend/app.py

Middleware to wrap any non-JSON 5xx as JSON { ok:false, error:"INTERNAL" }.

Exception handlers for HTTPException & generic Exception → JSON only.

Include request_id per request (header X-Request-ID or generate UUID) and log it.

b) backend/routes/vibecoding.py

Router prefix /api/vibecoding.

In-memory or Redis store SESS[sessionId] = { ready: bool, error: str|null }.

GET /session/status?id=<sessionId>:

If unknown: 404 { ok:false, error:"SESSION_NOT_FOUND" }

Else: { ok:true, ready, error }

Never raise/return HTML.

c) Wire routes

from routes.vibecoding import router as vibecoding_router
app.include_router(vibecoding_router)

3) Container creation: image resolution + readiness + timings

a) backend/vibecoding/config.py

Env VIBECODING_IMAGE (default vibecoding-optimized:latest).

ensure_image(client): try get(), else pull(); on repo/auth error raise a typed exception you handle into IMAGE_UNAVAILABLE.

b) backend/vibecoding/containers.py

On session create:

Set SESS[id] = { ready:false, error:null } immediately.

Ensure volume exists (reusing existing if present).

Create container with:

tty=True, stdin_open=True, --init (tini), working dir /workspace.

Mount named volume at /workspace.

Command: bash -lc 'test -d /workspace && touch /tmp/ready && sleep infinity'.

start(), then poll exec_run("bash -lc 'test -f /tmp/ready && echo READY || echo WAIT'") every 100–200ms up to 5–10s; on success set ready:true.

On image errors: set error:"IMAGE_UNAVAILABLE".

On any other creation error: set error:"CREATE_FAILED".

Add timing logs with ms for: existing_container_check, volume_create, container_create, start, ready_wait.

c) Optional warmups (commented or flag-gated)

Pre-pull VIBECODING_IMAGE at app startup.

Template volume clone for fast workspace bootstrap.

4) Production proxy (Nginx) for one origin (HTTP + WS)

Provide a complete nginx.conf that:

Serves Next.js on / (upstream app:9000 or node:3000).

Proxies all /api/vibecoding/ HTTP requests to FastAPI (api:8000).

Proxies WebSockets /api/vibecoding/container/*/(fs-events|terminal) to FastAPI with Upgrade/Connection headers.

Sets X-Request-ID if missing; passes through to backend.

Reasonable timeouts (read 60s+, ws 24h), gzip off for WS.

5) Reliability & security hardening

Retries/backoff: Client polling backoff; server retries only for transient Docker API errors (bounded, with jitter).

Dedupe: Prevent multiple concurrent creates per session; idempotent create endpoint (if container exists, return success).

Timeouts: Client waitReady 30s default; server readiness 10s; beyond that, set error and stop.

Structured logs: JSON logs with ts, level, request_id, session_id, event, duration_ms.

CORS: If separate domains, configure FastAPI CORS for Origin with credentials true.

Auth: Preserve cookies/headers on both HTTP and WS; reject unauthenticated WS with JSON close reason where possible.

Rate-limit: Basic rate limit on create endpoint (e.g., token bucket) to avoid abuse.

SLOs: P50 session ready ≤ 2s on warm hosts, P95 ≤ 5s; terminal echo < 50ms LAN.

6) Tests & runbook

Scripts/commands:

curl -i 'http://localhost:8000/api/vibecoding/session/status?id=foo' → JSON SESSION_NOT_FOUND.

Start session (with valid image) → ready:true within target; file tree loads; WS connects.

Break image name → UI surfaces IMAGE_UNAVAILABLE once; no spam.

WS handshake test: npx wscat -c ws://localhost:8000/api/vibecoding/container/<id>/fs-events → 101 Switching Protocols.

Runbook:

If 500 with INTERNAL: check backend logs for request_id.

If WS fails: ensure client uses WS_BASE and Nginx WS proxy block present.

If slow start: check timing logs by step; pre-pull image and verify disk speed.

7) What to output

Unified diffs for:

frontend/lib/api.ts (new API_BASE, WS_BASE, safeJson, waitReady).

frontend/components/VibeSessionManager.tsx and MonacoVibeFileTree.tsx gating changes.

Any places switching to ${API_BASE} and WS_BASE.

backend/app.py (middleware + handlers + router include).

backend/routes/vibecoding.py (status route).

backend/vibecoding/config.py (VIBECODING_IMAGE, ensure_image).

backend/vibecoding/containers.py (create/start with readiness + timings).

deploy/nginx.conf (complete, HTTP + WS).

A short README ops section: environment variables, how to build/pull image, start services, and verify.

Acceptance checklist meeting the SLOs above.

Use tight, production-grade code with clear error messages and no console spam.
