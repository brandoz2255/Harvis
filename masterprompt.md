You are coding inside the Harvis AI monorepo.

Stack

Frontend: Next.js 14 (App Router) + Tailwind + Monaco editor + xterm.js.

Backend: Python FastAPI.

DB: PostgreSQL.

AI runtime (local): Ollama.

Reverse proxy: Nginx fronts everything; the browser only talks to Nginx.

Docker: All services run in Docker.

Backend: http://backend:8000

Frontend: http://frontend:3000

Ollama: http://ollama:11434

Postgres: postgresql://pguser:pgpassword@pgsql:5432/database

User entrypoint: http://localhost:9000.

Networking rule (avoid CORS)

Always call APIs from the browser with relative paths:

✅ fetch("/api/...")

❌ fetch("http://localhost:8000/...")

Auth

JWT is issued/verified in the backend. Everything persistent is user‑scoped by JWT.

Repo hygiene

Check fixes/ before coding.

Append an entry to front_end/jfrontend/changes.md after changes.

🚨 Non‑Negotiable Deliverables (must be fully working)

Working Sessions (Docker‑backed)

Create, open, suspend, and resume sessions via API.

Each session = a Docker container + persistent workspace volume.

Fast start/resume; no heavy new Dockerfiles (reuse a single runner image).

Working Terminal (inside each session)

Real interactive Linux shell via WebSocket/PTY attached to the session container.

Stable input/output streaming in the UI (xterm.js), with history preserved per session.

Working File Explorer (left sidebar)

VSCode‑style Explorer with tree, CRUD (new/rename/move/delete), drag‑and‑drop move, and live refresh.

File content edits in Monaco persist to the session’s workspace volume.

VSCode‑style Look & Frontend

Layout, spacing, and interactions that feel like VSCode (not Google Colab).

Use Monaco for the editor, xterm.js for terminal, Codicons (MIT) or Lucide for icons.

Light/Dark themes consistent with VSCode tones (e.g., vs-light / vs-dark).

🎯 Objective

Build VibeCode so it works like a slim browser IDE with sessions and persistence—inspired by VSCode’s layout and UX, not by Colab. No “Google Colab files” anywhere; use Vibe naming consistently.

🧭 UX Flow
Outside (entering the VibeCode tab)

On clicking VibeCode tab: show a picker to Create New Session or Open Existing.

Sessions are backed by Docker:

New → create container + persistent workspace volume (e.g., /workspace).

Open → resume container if stopped or attach if running.

Inside a session (VSCode‑style layout)

Left: File Explorer (tree, drag‑drop, right‑click menu: New File/Folder, Rename, Delete).

Center: Monaco Editor bound to the selected file. Debounced saves to disk.

Bottom‑left: Terminal (xterm.js) attached to container shell (/bin/bash -l).

Right pane (tabs):

AI Assistant: chooses local Ollama or configured cloud LLMs; helps coding (like VSCode Copilot UX).

Code Execution: structured stdout / stderr / exit_code for explicit runs (e.g., run current file).
Rule: Execution/terminal output never appears in AI Assistant.

Persistence:

Files live on the session volume; user preferences (theme/layout) persisted per user.

On reload and re‑login, everything restores.

🧰 Implementation Plan
Backend — FastAPI (session orchestration + persistence)

Concepts

Vibe session = DB row + container + persistent volume.

Container name: vibecode-{user_id}-{session_id}

Volume name: vibecode-{user_id}-{session_id}-ws

Labels: app=vibecode, user_id=…, session_id=…

Workspace path: /workspace

Runner image: reuse a single base image (e.g., harvis/vibecode-runner:latest).

If missing, minimally derive from python:3.11-bullseye with bash & coreutils.

Do not proliferate Dockerfiles; reuse.

Endpoints (all JWT‑scoped; all under /api/vibecode/*)

Sessions

POST /api/vibecode/sessions/create → { name?, template? } → create DB + volume + container (detached, idle).

GET /api/vibecode/sessions → list user’s sessions with live status.

POST /api/vibecode/sessions/open → { session_id } → start/resume & return attach info.

POST /api/vibecode/sessions/suspend → stop container, keep volume.

POST /api/vibecode/sessions/delete → soft delete DB row; keep volume unless force=true.

Files (operate on the filesystem under /workspace, not DB blobs)

POST /api/vibecode/files/tree → { session_id }

POST /api/vibecode/files/create → { session_id, path, type: "file"|"folder" }

POST /api/vibecode/files/save → { session_id, path, content }

POST /api/vibecode/files/rename → { session_id, old_path, new_path }

POST /api/vibecode/files/move → { session_id, source_path, target_dir }

POST /api/vibecode/files/delete → { session_id, path } (soft delete → .vibe_trash/)

Execution (structured, separate from terminal)

POST /api/vibecode/exec → { session_id, cmd?, file?, lang?, args? }

If lang="python" and file, run python /workspace/<file>.

Return { stdout, stderr, exit_code, started_at, finished_at }.

Must show “hello world” correctly when appropriate (no more “no output”).

Terminal (WebSocket)

GET /api/vibecode/ws/terminal?session_id=... → upgrades to WS, bridges to a PTY in the same container.

User prefs

GET /api/user/prefs / POST /api/user/prefs for theme & layout.

DB schema

vibe_sessions (id uuid PK, user_id uuid, name text, status text, created_at, updated_at, deleted_at)

user_prefs (id uuid PK, user_id uuid, theme text, updated_at)

Security & resources

JWT scope on every endpoint.

Path sanitation: forbid .., absolute paths, and symlinks escaping /workspace.

Resource limits per container (e.g., mem_limit, nano_cpus, pids_limit, no-new-privileges).

Nginx must support WebSockets on /api/ (set Upgrade/Connection headers).

Frontend — Next.js 14 (App Router)

Top‑level route: /vibecode.

Session Picker first (New / Existing).

Layout (VSCode‑style):

Left fixed sidebar: Explorer (drag‑drop via react-dnd or native HTML DnD).

Center: Monaco Editor; debounced save (~500ms) to /api/vibecode/files/save.

Bottom‑left: xterm.js Terminal attached to /api/vibecode/ws/terminal?session_id=....

Right: Tabs → AI Assistant | Code Execution. Execution results only in the latter.

VSCode look & feel

Use Monaco themes vs-dark / vs-light; mirror VSCode spacing/panels/splitters.

Use Codicons for familiar iconography (MIT).

Keyboard shortcuts: Ctrl/Cmd+S (save), Ctrl/Cmd+Enter (run).

Global Theme toggle persists via /api/user/prefs.

Provider detection (Assistant)

Prefer local Ollama (backend-proxied).

Optionally support cloud (keys via env).

Never show terminal/exec output in Assistant.

🏷 Naming & Migration (no Colab artifacts)

Replace any “Colab” labels/dirs with Vibe names: “Vibe Session”, “Vibe Files”.

If legacy Colab files exist, move them once to /workspace/vibe_legacy/ to avoid collisions.

Do not generate “Google Colab files” or notebook artifacts.

✅ Testing & Acceptance Criteria

How I will test

Frontend:

cd front_end/jfrontend

npm run type-check

npm run dev

Backend: started in Docker as usual (you can assume I’ll bring it up; I’ll verify endpoints).

Pass conditions

Working Sessions: create/open/suspend/delete; containers & volumes labeled and discoverable.

Working Terminal: interactive bash in the session container; stable streaming both ways.

Working File Explorer: VSCode‑style sidebar; CRUD + drag‑drop move; tree updates instantly; changes persist.

Execution Output Correct: print("hello world") or echo "hello world" → visible in Code Execution with exit_code=0.

Tabs Separation: execution/terminal output never appears in AI Assistant.

VSCode‑style UI: Monaco + xterm.js + Codicons; panel layout & theming feel like VSCode.

Persistence: files on session volume; theme/preference restored per user.

No Colab: no “Google Colab files” created; Vibe naming only.

No CORS: all browser calls use /api/....

🔒 Guardrails

Reuse a single runner image; avoid creating more Dockerfiles.

Prefer reusing/editing existing files over deletion.

Sanitize all filesystem operations to remain under /workspace.

Keep JWT secrets & algorithms consistent; never log sensitive data.

📝 Deliverables

Frontend PR implementing Session Picker, VSCode‑style layout, Explorer, Monaco, Terminal, Assistant & Code Execution tabs.

Backend PR adding /api/vibecode/* and WS terminal attach.

CHANGELOG entry in front_end/jfrontend/changes.md (timestamp, problem, root cause, solution, files, status).

Now implement these changes. If anything is underspecified, make safe, conventional choices consistent with the stack above.