# Handoff: Cookbook + Deep Research backends — state + tomorrow (2026-06-03)

Companion to `2026-06-02-odysseus-features.md` (the design/spec). This file = where we stopped + what's next. Nothing committed or pushed.

## What shipped today (backend only — frontend is a separate agent)

### Cookbook ✅ built + deployed + E2E PASSED (2026-06-03)
- New module `python_back_end/cookbook/` (`__init__.py`, `config.py`, `client.py`, `router.py`) — thin proxy over per-node `llmfit serve` + Ollama download. Registered at `/api/cookbook/*` (`nodes, system, recommend, models, download`).
- Wired: `main.py` (registration, try/except), `docker-compose.yaml` (bind-mount `./python_back_end/cookbook:/app/cookbook:ro`).
- Verified: py_compile clean; `/api/cookbook/nodes` → 401 (registered + auth-gated); in-container `health()` runs against both nodes (alive:false — nothing up yet); llmfit's real REST API confirmed to match the proxy exactly (`/health`, `/api/v1/system`, `/api/v1/models/top`, `/api/v1/models`, params `limit/min_fit/use_case/runtime/sort/max_context/force_runtime`).
- Node registry default (env `COOKBOOK_NODES` or per-node envs): rig `http://192.168.20.58:8787` + ollama `192.168.20.58:11434`; laptop `host.docker.internal:8787` + `ollama:11434`.
- **E2E PASSED 2026-06-03:** rig runs `llmfit 0.9.30` (installed via `uv tool install llmfit==0.9.30`, nohup'd — NOT reboot-proof; a Windows scheduled-task auto-start is available on request). Backend container reaches it (health 61ms; the Windows-firewall rule add failed for lack of admin, but cross-machine access works anyway — only add `New-NetFirewallRule ... -LocalPort 8787` if another machine can't connect). `/api/v1/system` → RTX 5080 + 15.92GB + CUDA. `/api/v1/models/top` → `{node, system, total_models:170, returned_models, filters, models:[...]}`.
- **⚠ DOWNLOAD BRIDGE (the flagged HF→Ollama question, resolved):** llmfit model records are HF/llama.cpp-shaped — fields: `name` (HF repo, e.g. `NVFP4/Qwen3-Coder-30B-A3B-Instruct-FP4`), `provider`, `best_quant` (e.g. `Q6_K`), `runtime: llamacpp`, `gguf_sources`, `params_b`, `fit_level`, `score`, `score_components{quality,speed,fit,context}`, `estimated_tps`, `memory_required_gb`. **No Ollama tag exists.** So `/api/cookbook/download` (pull into Ollama) can't use llmfit's `name` directly. Backend `/download` is correct (takes explicit `ollama_tag`, rejects raw HF names). Resolution options for the download step (DECISION NEEDED — likely frontend/UX): (a) **recommend-only v1** (ship system+recommend+browse; the core "what fits my 5080" value — download deferred); (b) `ollama pull hf.co/<name>:<best_quant>` for GGUF-bearing repos (clean when `gguf_sources` non-empty; fails for FP4/non-GGUF); (c) a registry-tag heuristic map (fragile). Endpoints `nodes/system/recommend/models` are DONE + proven.
- **DOWNLOAD RESOLVED + IMPLEMENTED (2026-06-03) — hf.co GGUF bridge + capability gate:** `/recommend` + `/models` now tag each model `downloadable` (true iff `gguf_sources` non-empty) + a `reason` when false (non-GGUF stay listed, not filtered). `/download` accepts `repo`+`quant` → builds `hf.co/<repo>:<best_quant>` → `ollama pull` on the node's Ollama; explicit `ollama_tag` still wins; bare HF repos rejected (no registry-tag guessing). Verified live vs rig: 2/12 coding recs downloadable (DeepSeek-Coder-V2-Lite Base/Instruct have GGUF; FP4/AWQ/GPTQ/FP8 don't); `hf.co/...:Q6_K` construction + rejection logic correct. **Remaining:** one deliberate live `hf.co` pull of a chosen small GGUF model to confirm the rig's Ollama accepts hf.co pulls end-to-end (the 2 downloadable recs are ~16B = big — pick a small one). Quant-picker UI + Ollama-registry mapping are explicitly OUT of v1.

### Deep Research ✅ built + deployed + E2E PASSED
- New module `python_back_end/deep_research/`: `researcher.py` (Odysseus DeepResearcher, verbatim except seams), `visual_report.py` (full styled HTML, reskinned Harvis), `handler.py` (trimmed task-registry + JSON persist + SSE), `router.py` (14 endpoints `/api/research/*`, Harvis auth + owner-scoped), `research_utils.py`, `goal_based_extractor.py`, `__init__.py`.
- Seams rewired Odysseus→Harvis: LLM → `research.research_agent.async_make_ollama_request` (`/api/chat`); search → `research.web_search.WebSearchAgent.search_web`; fetch → `research.extract.router.extract_url`.
- Wired: `main.py` (registration), `docker-compose.yaml` (bind-mount `deep_research:/app/deep_research:ro`), `requirements.txt` (+`markdown`).
- Verified: py_compile clean; all 14 routes registered (`/api/research/active` → 401); module imports clean in-container; **real 1-round E2E produced a 4,899-char report** from a live web query (web search + extract + synthesis + final report + category auto-detect all fired).
- Default model `llama3.1:8b` (env `DEEP_RESEARCH_MODEL`) — `qwen3:14b` is NOT pulled; available: llama3.1:8b, gpt-oss:latest, granite4.1:8b, gemma4:e4b, batiai/qwen3.5-9b, hermes3:3b, qwen3:4b, etc.
- Persistence: `/data/artifacts/deep_research` (the `/data` root is root-owned; this volume is writable by uid 1001 + persistent). Override env `DEEP_RESEARCH_DATA_DIR`.

## ⚠ Loose ends to clean up
- **`markdown` is installed EPHEMERALLY** in the running backend (`pip install` in-container). Survives `docker restart`, but a `docker compose up -d backend` (recreate) DROPS it → visual report endpoint breaks until reinstalled. It's in `requirements.txt` now → **`docker compose build backend` bakes it durably.** Do that tomorrow (or re-pip after any recreate).
- **Deep Research is slow (~8.5 min/round).** Causes seen in the E2E log: `async_make_ollama_request` tries CLOUD Ollama first (`EXTERNAL_OLLAMA_URL=your-ollama.example.com`) → 404 → falls back to local (wasted round-trips per call); plus some extractions failed under concurrency on llama3.1:8b. Tuning, not correctness.
- **Persistence not fully exercised:** the E2E used `call_research_service` (no save). The `/api/research/start` → `_save_result` → `/library` → `/report` flow is unproven (but the dir is writable). Confirm tomorrow.
- **Uncommitted (no push — your rule):** 6 OWUI files (Wave 2 dock-router, unverified) + new `cookbook/` (4) + `deep_research/` (7) + `main.py` + `docker-compose.yaml` + `requirements.txt` + 2 handoff docs.

## TOMORROW — prioritized

### P1 · Cookbook E2E (you + me)
1. **YOU (rig, no SSH from me):** install + run `llmfit serve` on the rig:
   ```bash
   # on 192.168.20.58 — native is simplest (sees the 5080 directly):
   curl -fsSL https://llmfit.axjns.dev/install.sh | sh
   llmfit serve --host 0.0.0.0 --port 8787
   curl -s http://localhost:8787/api/v1/system   # must show RTX 5080 + ~16GB
   ```
   (Docker alt: `docker run -d --gpus all -e NVIDIA_DRIVER_CAPABILITIES=utility,compute -p 8787:8787 ghcr.io/alexsjones/llmfit serve --host 0.0.0.0 --port 8787`. Confirm port 8787 not firewalled — Ollama:11434 already reaches, so the LAN path is open.)
2. **ME:** once it's up — curl `192.168.20.58:8787/api/v1/system` from the backend; then E2E `/api/cookbook/{nodes,system,recommend,download}`; resolve the **HF→Ollama tag mapping** (check if `/api/v1/models/top` carries an ollama-tag field, else map before `/api/pull`); confirm a small-model download lands in the rig's `ollama list`.

### P2 · Deep Research finish (me)
3. Exercise the full `/api/research/start` → SSE stream → persist → `/library` → `/report` (visual HTML) flow with a real JWT.
4. **Perf tune:** stop the cloud-Ollama-404 fallback for research (point straight at local `ollama:11434`, or unset EXTERNAL_OLLAMA for this path), and/or pick a faster/larger model + lower extraction concurrency to cut the ~8.5 min/round. Reduce extraction failures.
5. (Then frontend = separate agent: a research surface + wire the cosmetic Research pill to `/api/research/start`.)

### P3 · Open Notebook image ingestion (me)
6. Implement IMAGE handling in `notebooks/ingestion.py::_extract_text()` via **BLIP caption (`screen_analyzer.py`) + Tesseract OCR** → unblocks Notes + Images → Open Notebook relay. Smoke with `meta.jpg`.

### Housekeeping
7. **Run the Wave 2 OWUI regression gate** (workspace run→card→stream→persist→done; chat persist; "View activity" dock) and **commit a clean checkpoint** (OWUI Wave 2 + Cookbook + Deep Research) once you've verified. No push until you say.
8. **`docker compose build backend`** to bake `markdown` (and any future deps) durably.

## Standing constraints
No push until verified · never commit secrets/.env · never `docker compose down -v` · no keyword-based model routing · Cookbook = proxy over llmfit (don't reimplement scoring / build a serve engine).
