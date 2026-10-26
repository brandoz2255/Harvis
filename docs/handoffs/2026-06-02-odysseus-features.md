# Handoff: Odysseus → Harvis feature ports (Cookbook · Deep Research · Notes/Images→Open Notebook · Compare · Docs)

**Date:** 2026-06-02
**For:** the Claude Code bot (the agent that lands code) — **backend only** (a separate agent owns the OWUI frontend)
**Author:** planning/recon session (read Odysseus repo + GitHub + Harvis backend; no code changed)
**Source project:** Odysseus — `/home/ommblitz/Projects/Odysseus/odysseus` (GitHub: pewdiepie-archdaemon/odysseus, MIT, 35k★, Python/FastAPI + vanilla-JS, ChromaDB/fastembed)

---

## 0. READ FIRST — two things that will bite you

### 0.1 Cookbook architecture — DECIDED: proxy a per-node `llmfit serve`. Do NOT port Odysseus's Python.
Fork in the road the bot WILL hit if it reads the Odysseus repo: **Odysseus implements Cookbook as in-process Python** (`services/hwfit/{hardware,fit,profiles,image_models}.py` + `routes/cookbook_routes.py`) — it runs no separate service. Copying Odysseus literally means reimplementing hardware-scan + fit-scoring inside Harvis.

**Harvis is NOT doing that (user decision).** The approach is to use the upstream **`llmfit` tool itself, run as a per-node `llmfit serve` REST API**, and make Cookbook-on-Harvis a thin aggregating **proxy**. Rationale: llmfit already does hardware-scan + fit-scoring + model DB + download ranking; running its `serve` per node is far less code than porting/maintaining the Python, and it yields **correct per-node hardware detection** — each node's llmfit sees its own real hardware. (llmfit has no remote-scan mode, so SSH-ing `nvidia-smi` and faking VRAM would be wrong.) Full strategy in §2.

**True regardless of approach:** do NOT reimplement fit-scoring / hardware parsing / the model DB (llmfit's job), and do NOT build a serve-engine (Ollama already serves). Cookbook's backend is ~150 lines of proxy + a download trigger.

### 0.2 Pre-flight gate (standing user rule) — do this BEFORE landing Cookbook code
There is uncommitted, **user-unverified** OWUI/Agent Studio work on the frontend (Wave 2 dock-router on `ChatControls.svelte`). Standing instruction: **run the Wave 2 regression gate and commit the current OWUI work before the bot starts landing Cookbook code.** Don't stack new feature ports on an unverified spine.
- Wave 2 gate = full workspace run (auto-detect→WorkspaceRunCard→stream→persist→done) + chat persistence (send→reload→intact) + "View activity" dock opens. If any fails, the dock-router doesn't ship.
- **No push until the user verifies** (standing rule). **Never commit secrets / .env.** Never `docker compose down -v`.

---

## 1. Priority order (per user)
1. **Cookbook** (per-node `llmfit serve` proxy + Ollama download) — highest.
2. **Deep Research** (agentic multi-step research + visual reports).
3. **Notes & Tasks** + **Image Gallery** — *sidelines*, relayed **into Open Notebook** (already vendored at `python_back_end/notebooks/` + `open_notebook/`).
4. Lower: **Compare**, **Documents**, **Chat & Agents** (Chat&Agents largely already exists via OpenClaw/Agent Studio).

---

## 2. Cookbook  (PRIORITY 1) — DECIDED STRATEGY

**One line:** llmfit IS the engine (hardware scan + fit scoring + model DB + download ranking). Cookbook's backend is a thin **per-node proxy** in front of each node's `llmfit serve`, plus a download trigger to that node's Ollama. No ML logic, no hardware parsing, no reimplementation. ~150 lines of FastAPI. Backend only — a separate agent owns the OWUI frontend.

### Architecture: per-device, one llmfit per node
Cookbook is multi-node. Each machine runs its own `llmfit serve` (node-level REST API — llmfit's documented cluster/aggregator use case). The Harvis backend aggregates them into one logical Cookbook API; the frontend draws one tab per healthy node.

Nodes:
- **laptop** — `http://localhost:8787` — Docker host / main box; runs its own `llmfit serve`, scans its own hardware.
- **rig** — `http://192.168.20.58:8787` — `llmfit serve` in a **GPU-passthrough** Docker container (so it detects the real RTX 5080 / 16GB) + Ollama (already there; Harvis uses it).

Each node's llmfit detects its OWN hardware locally — no remote-scan mode exists, so per-node serve is what makes "what fits the 5080" correct. No `--memory` override fakery; the rig's container sees the real card.

### llmfit REST surface (what you proxy — confirmed in llmfit docs)
- `GET /health` — liveness
- `GET /api/v1/system` — that node's detected hardware (CPU/RAM/GPU/VRAM/backend) → your **scan**
- `GET /api/v1/models/top?limit=&min_fit=&use_case=` — top runnable models, pre-ranked → your **recommend** (the heart of Cookbook)
- `GET /api/v1/models?...` — full fit list with filters → **browse**
- `GET /api/v1/models/{search}` — search by name

Pass query params **through**, don't invent your own: `limit`, `min_fit` (perfect|good|marginal|too_tight), `use_case` (general|coding|reasoning|chat|multimodal|embedding), `runtime` (any|mlx|llamacpp), `sort`, `max_context`, `force_runtime`.

### What you build: the Harvis Cookbook router
New FastAPI router, registered in `main.py` like the existing workspace/memory routers, using the **same auth dependency they use** (`get_current_user` / `get_current_user_optimized` — match what's already there). Node registry in config (env-driven, NOT hardcoded):
```python
LLMFIT_NODES = {
  "laptop": "http://localhost:8787",
  "rig":    "http://192.168.20.58:8787",
}
```
Endpoints:
- `GET /api/cookbook/nodes` — ping each node's `/health`, return which are alive. Drives per-device tabs (laptop always; rig only if healthy). This IS the "detect another device" logic: a health check against a known registry, nothing fancier.
- `GET /api/cookbook/system?node=rig` — proxy that node's `/api/v1/system`.
- `GET /api/cookbook/recommend?node=rig&use_case=coding&min_fit=good` — proxy that node's `/api/v1/models/top`, params passed through.
- `GET /api/cookbook/models?node=...` (optional, browse/search) — proxy `/api/v1/models`.
- `POST /api/cookbook/download` — body `{node, model, provider:"ollama"}`. Pull on that node's Ollama: laptop → `localhost:11434/api/pull`, rig → `192.168.20.58:11434/api/pull`. Pull target follows the node (scoring node == download node == same tab).

### Two things to resolve while building (flag, don't guess)
1. **HF→Ollama name mapping.** llmfit's DB uses HF names (`Qwen/Qwen2.5-Coder-14B-Instruct`); Ollama wants tags (`qwen2.5-coder:14b`). Check whether `/api/v1/models/top` JSON already carries an Ollama-tag field. If yes, use it. If no, the frontend passes the exact tag, or you add a small mapping step — **never hand `/api/pull` a raw HF name** (it 404s).
2. **Download progress.** Ollama's `/api/pull` streams NDJSON progress. Decide: stream through to the frontend via **SSE** (reuse Harvis's existing workspace-stream SSE pattern) for a live bar, or fire-and-poll. SSE matches the rest of Harvis.

### Scope guards (do NOT build for v1)
- **No serve-engine management.** Odysseus also serves via llama.cpp/vLLM/tmux — skip entirely; Harvis serves through the rig's Ollama + `model_proxy`. Cookbook's job **ends at "downloaded into Ollama."**
- **No reimplementing fit-scoring / hardware detection / model DB** — that's llmfit. If you're parsing `nvidia-smi` or computing VRAM, stop.
- **No frontend** — separate agent owns OWUI.

### Deploy prerequisites (user places these; bot states them clearly)
- Laptop runs `llmfit serve --host 0.0.0.0 --port 8787` (single Rust binary / cargo release).
- Rig runs `llmfit serve` in a **GPU-passthrough container** — needs NVIDIA Container Toolkit + `--gpus all`. **Make-or-break:** without passthrough the container sees CPU only → the rig tab recommends as if there's no 5080 (Odysseus README flags this exact trap).
- Every node that gets a tab must have its own reachable `llmfit serve` — a tab with no llmfit behind it is a dead tab.

### Verify before done (hard gates)
1. `docker exec <rig-llmfit-container> nvidia-smi -L` → lists the RTX 5080. If not → it's a GPU-passthrough problem, not llmfit; fix first.
2. `curl http://192.168.20.58:8787/api/v1/system` → reports **16GB VRAM + the 5080 by name** (not CPU/no-GPU). Gates whether the rig tab is trustworthy.
3. `curl http://localhost:8787/health` AND the rig's `/health` both 200 → `/api/cookbook/nodes` returns both alive.
4. `GET /api/cookbook/recommend?node=rig&use_case=coding&min_fit=good` through Harvis (authed) → ranked list.
5. `POST /api/cookbook/download {node:"rig", model:...}` with a small model → appears in the rig's `ollama list`, and Harvis can then chat with it (proves the loop closes into the existing model path).
6. `py_compile` the new router; confirm it registers in `main.py` without breaking existing routes.

### ROADMAP-aligned (upstream help-wanted; worth feeding back as Odysseus PRs)
Cookbook reliability across machines, scan/download ranking (architecture-age + quant + VRAM-fit), error feedback (show the real failed command/output, copyable logs), SGLang serve reliability. The user's laptop+rig spread is exactly the test coverage upstream lacks.

---

## 3. Deep Research  (PRIORITY 2)

### Harvis already has a research pipeline — this is an UPGRADE, not greenfield
`python_back_end/research/` already contains `enhanced_research_agent.py`, `research_agent.py`, `web_search.py`, plus `planners/`, `rank/`, `synth/`, `extract/`, `search/`, `llm/`, `pipeline/`. `main.py` exposes `/api/research-chat`, `/api/web-search`, `/api/fact-check`, `/api/comparative-research`. **Audit `research/` first; reuse its search/extract/rank primitives.** The gap vs Odysseus is the **agentic iteration loop**, the **visual HTML report**, the **library/persistence**, and **SSE progress** — port those, don't re-port search.

### Odysseus source
- `src/deep_research.py` (~830 lines) — `DeepResearcher`. Flow: `_create_plan()` → optional `_classify_category()` → loop{`_generate_queries()` → `_search()` → `_fetch_and_extract()` → `_synthesize()` → `_should_stop()`} (min 2, max ~8 rounds, LLM decides stop) → `_final_report()` (1500+ words, auto-expand if <400) → `_format_research_report()`. Category templates: product / comparison / howto / factcheck / default.
- `src/research_handler.py` — task registry, persistence, legacy fallback, endpoint preflight ("hi" probe → detect 401/unreachable).
- `src/goal_based_extractor.py` — per-URL extraction prompt → JSON `{rational, evidence, summary}` + `{url,title,og_image}`.
- `src/visual_report.py` — self-contained styled HTML (hero image, dark/light, auto-TOC, inline OG images with hide/reroll, collapsible sources, print toolbar; local fonts only).
- `src/search/{providers,core,content}.py` — provider chain (SearXNG primary; DDG/Brave/Tavily/Serper/Google-PSE fallbacks) + BeautifulSoup fetch (15KB truncate).
- `routes/research_routes.py` — the `/api/research/*` surface. Persistence: JSON per session at `data/deep_research/{session_id}.json`.

### Odysseus endpoints to mirror (the valuable ones)
- `POST /api/research/start` → `{session_id,status,query}` (body: query, max_rounds[0=auto], search_provider?, model?, max_time[60–1800], extraction_timeout?, extraction_concurrency?, category?)
- `GET /api/research/stream/{id}` — **SSE** progress (`{phase: probing|planning|searching|reading|analyzing|writing|error, round, queries, total_sources,...}` then `{status:done,final:true}`)
- `GET /api/research/status/{id}`, `GET /api/research/active`
- `POST /api/research/result/{id}` (consume), `POST /api/research/result-peek/{id}` (non-consuming)
- `POST /api/research/cancel/{id}`
- `GET /api/research/report/{id}` — **HTML** visual report
- `GET /api/research/library` (search,sort,limit,archived), `GET /api/research/detail/{id}`, `POST /{id}/archive`, `DELETE /{id}`
- `POST /api/research/spinoff/{id}` — seed a new chat from the research

### Harvis target
- New module `python_back_end/deep_research/` (`researcher.py` = ported `DeepResearcher`, `visual_report.py`, `library.py` persistence, `router.py`). Register `/api/research/*` (distinct from existing `/api/research-chat`).
- **LLM calls** → route through Harvis `model_proxy` (`execute_chat_completion`), honoring existing routing. **No keyword-based model swapping** (standing rule).
- **Search backend** → reuse Harvis `research/search/` + `web_search.py`. Harvis has **no SearXNG** — wire `_search()` to Harvis's existing search; don't add SearXNG just for this. Content fetch → reuse `research/extract/`.
- **Persistence** → JSON files under `data/deep_research/` for v1 (matches upstream).
- **Wire the Research pill:** the OWUI top-bar Research pill is currently cosmetic (`researchEnabled` store, no backend). It becomes the Deep Research entry point (`/api/research/start` + stream into a research surface/visual report). Frontend = separate agent; backend exposes endpoints + SSE.

Deps: `httpx, beautifulsoup4, markdown` (already present). No SearXNG.

---

## 4. Notes & Tasks  (PRIORITY 3 — relay to Open Notebook)

### Open Notebook is ALREADY wired
`notebooks.router` registered in `main.py` at **`/api/notebooks`** (PostgreSQL + pgvector, 4096-dim). Entities: Notebook, NotebookSource, NotebookChunk, **NotebookNote** (user_note/ai_note/summary/highlight), NotebookChatMessage, Transformation (8 types), Podcast. Notes CRUD is fully functional.

### Plan
- **Notes → Open Notebook = READY.** Relay via `POST /api/notebooks/{id}/notes` (type=user_note). No new backend. A "notes" surface is a thin client over the existing API.
- **Tasks (scheduling) is SEPARATE** — Open Notebook has no scheduler. Odysseus's tasks half: `scheduled_tasks` + `task_runs` SQLite, croniter, task_type ∈ {llm,action,research}, event/webhook triggers, `POST /api/tasks/parse` (NLP→draft), `/api/tasks/*` CRUD+run/pause/resume. Harvis already has a cron primitive at `python_back_end/plugins/cron/` (`types.py`, `store.py`) — **extend that** rather than porting Odysseus's whole scheduler, OR port `scheduled_tasks` if you want the full task-runs/agent-action model. Keep tasks **lightweight for v1** (user flagged Notes/Tasks as a sideline). ROADMAP north star: notes the agent can read/update/summarize; todos assignable to an agent from the UI.

---

## 5. Image Gallery  (PRIORITY 3 — relay to Open Notebook; HAS A BLOCKER)

### BLOCKER: Open Notebook image ingestion is stubbed
`notebooks/ingestion.py` defines `SourceType.IMAGE` but `_extract_text()` returns `""` for it. Relaying an image as a notebook source currently produces an empty/failed source. **Fix this FIRST.**

### Plan — DECIDED extraction: BLIP caption + Tesseract OCR (local, no API cost)
1. **Unblock image ingestion** (the actual work): implement IMAGE handling in `notebooks/ingestion.py::_extract_text()` using **BLIP caption** (reuse `screen_analyzer.py`) **+ Tesseract OCR** for any text in the image. Store caption+OCR as the source `content_text` so it chunks/embeds/RAGs like any other source. Fully local — fits the privacy-first goal; no cloud call. (Audio ingestion is similarly stubbed — out of scope unless asked.)
   - Smoke-test with the **meta.jpg CTF image** (memory: baby lamb, iPhone 5, 1024×768) — the image-pipeline regression fixture.
2. **Then relay:** images flow in as `NotebookSource` (type=IMAGE) → caption/OCR → chunk → embed → searchable + citable in notebook RAG chat.
3. **Standalone gallery (optional, lower):** if a real gallery is wanted (albums, dedup, EXIF, AI-upscale/style-transfer), port Odysseus's `routes/gallery_routes.py` + `gallery_helpers.py` (`gallery_images`/`gallery_albums`, SHA-256 dedup, EXIF via Pillow, files in `data/generated_images/`). Upscale/style-transfer call an external image endpoint — Odysseus ships `scripts/diffusion_server.py` + `mcp_servers/image_gen_server.py` (local SD/SDXL); run it on the rig if the user wants generation.

---

## 6. Compare  (PRIORITY 4)
- Odysseus: `comparisons` table (model_a/b, endpoint_a/b, response_a/b, metrics, winner, is_blind, blind_mapping, voted_at). `POST /api/compare/start` (ephemeral sessions + blind shuffle), `POST /{id}/vote` (reveals models), `POST /api/compare/record` (N-model), `GET /api/compare/history`, `DELETE /{id}`. Frontend streams 2–8 panes via SSE + vote bar + scoreboard.
- Harvis already has a `ModelComparison.svelte` surface (frontend) + `$models`. Backend gap is the **comparisons table + blind A/B + voting/history**. Port `/api/compare/*` (reuse Harvis sessions + `model_proxy` for the parallel streams). Do after Cookbook + Deep Research.

## 7. Documents  (PRIORITY 4)
- Open Notebook's `NotebookSource` ingestion (PDF/DOC/TEXT/URL/MARKDOWN) already covers the **relay** of documents (READY). Odysseus's Documents feature adds a *versioned living-document editor* (`documents` + `document_versions` + `editor_drafts`, export txt/md/pdf/docx, email provenance) — that editor is an **OWUI frontend concern**, not a backend port. v1: documents → Open Notebook sources. Defer the editor.

## 8. Chat & Agents  (PRIORITY lowest — mostly already done)
- Harvis's OpenClaw + Agent Studio already provide multi-model + agent automation + tools. **No port.** Cherry-pick only Odysseus's **agent prompt/context slimming** ideas (ROADMAP "agent prompt/context bloat") — which the user already solved (hermes4 schema-cut, tool-count trim, model-task pairing). Cross-pollinate; don't re-architect.

---

## 9. Open Notebook relay-readiness summary
| Relay target | Open Notebook home | Status | Action |
|---|---|---|---|
| Notes | `NotebookNote` (`POST /api/notebooks/{id}/notes`) | ✅ READY | wire client; no backend |
| Documents | `NotebookSource` (upload/url/text) | ✅ READY | relay as sources |
| Images | `SourceType.IMAGE` ingestion | ⚠️ STUBBED | implement `_extract_text` for IMAGE via **BLIP + Tesseract OCR** FIRST |
| (Audio) | `SourceType.AUDIO` ingestion | ⚠️ STUBBED | out of scope unless asked |

Open Notebook gaps to watch: needs Ollama up (`OLLAMA_URL`) for embeddings/transformations; TTS service for podcast audio (else script-only); confirm notebook tables exist (migrations).

---

## 10. Sequencing for the bot
1. **Gate + commit** the current OWUI/Agent Studio work (Wave 2 regression gate) — DON'T skip (§0.2).
2. **Cookbook backend** (`python_back_end/cookbook/router.py`): thin proxy over per-node `llmfit serve` (laptop + rig) + Ollama download trigger; env-driven `LLMFIT_NODES`; `/api/cookbook/{nodes,system,recommend,models,download}`. Verify against the rig's real 5080 (§2 hard gates). ← biggest value.
3. **Deep Research backend** (`python_back_end/deep_research/`): port `DeepResearcher` loop + visual report + library + SSE; reuse Harvis `research/` + `model_proxy`; `/api/research/*`; wire the Research pill.
4. **Open Notebook image ingestion** unblock (BLIP + Tesseract) → then **Notes + Images relay** are trivial client wiring.
5. **Compare** backend (`/api/compare/*`), then **Documents**-as-sources.
6. Frontend surfaces for each = a separate frontend agent (this handoff is backend-focused).

## 11. Constraints (non-negotiable)
- **No push until the user verifies** end-to-end. Commit only when asked.
- **Never commit secrets / .env / API keys.** hf_token + provider keys stay in env/secrets.
- **Never `docker compose down -v`** (destroys volumes incl. OpenClaw pairing + notebook data).
- **No keyword-based auto model routing** — Deep Research / Compare LLM calls go through `model_proxy` honoring existing routing.
- **Cookbook = thin proxy over per-node `llmfit serve`.** Don't reimplement fit-scoring/hardware/model-DB; don't build a serve-engine; download ends at Ollama.
- Small, focused commits per feature (mirrors Odysseus's CONTRIBUTING norms).

## 12. Deploy notes
- Backend changes: `docker restart harvis-backend` (or `docker compose up -d --build backend`). owui_compat is bind-mounted (restart-only).
- Cookbook prereq (user): `llmfit serve` on laptop (`:8787`) + rig (GPU-passthrough container, `:8787`); both Ollamas reachable.
- OWUI frontend (if any surface lands): edit MAIN `front_end/owui/src` → rsync to worktree → `npm run build` → rsync `build/` to MAIN → `docker restart nginx-proxy`. (Frontend owned by a separate agent.)
