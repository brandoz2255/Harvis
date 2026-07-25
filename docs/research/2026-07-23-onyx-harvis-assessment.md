# Onyx → Harvis Assessment: What to Copy, What to Scrap, What to Test

**Date:** 2026-07-23  
**Branch:** `harvis1.1`  
**Scope:** Deployment tiering, knowledge engine, connectors, MCP integration, LLM tracing, benchmarks  
**Status:** Research / documentation — no code changes

---

## Executive Summary

Onyx's single most valuable contribution to Harvis right now is **not its code** — it is its **Lite / Standard deployment-tier architecture**. Harvis currently ships one `docker-compose.yaml` with 25 services and almost no Compose profiles. That design directly enabled the F: drive crisis, the 532 s fresh-clone build, and the "everything is mandatory" trap that makes onboarding painful.

**The right relationship:**

- **Copy immediately:** Onyx's tier-and-profile pattern, its `AGENTS.md` discipline, and its LLM-call tracing conventions.
- **Pilot externally:** Onyx Standard as an optional, isolated knowledge sidecar reachable over MCP.
- **Do not merge:** The Onyx frontend, its full Standard stack into the Windows dev box, or Onyx into Harvis as a monolith.

Harvis should remain the command-and-execution workspace. Onyx can become the optional indexed-knowledge layer behind it.

---

## 1. Grounded Harvis State (what actually exists today)

### 1.1 Docker Compose has no product-tier split

| File | Purpose | Services |
|------|---------|----------|
| `docker-compose.yaml` | Main stack | **25 services** — backend, frontend, nginx, pgsql, ollama, openclaw, document-worker, tts-service, open-notebook, harvis-mcp, browser-runner, owui-builder, surrealdb, engine sidecars (opencode, codex, claude-code, hermes-agent), cad-engine, etc. |
| `docker-compose.dev.yml` | Hot-reload dev | nginx, backend, frontend, pgsql, ollama, n8n |
| `docker-compose.cpu.yml` / `amd.yml` | GPU backend override | Drops NVIDIA runtime for CPU/AMD |
| `docker-compose.prebuilt.yml` | Prebuilt image variant | Slimmer: no browser-runner, owui-builder, tts, messaging, engine sidecars, cad-engine |
| `docker-compose.override.yml` | Gitignored local override | BYO OpenClaw, 8 GB GPU tuning |
| `embedding/docker-compose.yml` | Standalone embedding service | `embedding-service` + its own pgsql reference |

**Key finding:** only one service uses a Compose profile today — `harvis-messaging-gateway` has `profiles: ["messaging"]` (`docker-compose.yaml:991`). The engine sidecars and `cad-engine` are **not** behind profiles; they are gated only by backend env flags like `HARVIS_OWUI_EXTERNAL_ENGINES` and `HARVIS_ADAPTIVE_CAD_ENABLED`.

`install.sh` selects only the **inference backend** (`nvidia|amd|cpu`) — it does not ask the user whether they want a minimal chat stack, a full workspace stack, or a knowledge-heavy stack (`install.sh:79-112`).

### 1.2 Fresh-clone deployment pain is well documented

The Windows E2E handoff (`docs/handoffs/2026-07-21-post-windows-e2e.md`) and the fix list (`docs/reports/ISSUES-FOR-FIX-2026-07-22.md`) show the current stack is far from "one command out of the box":

| Blocker | Root cause | File evidence |
|---------|------------|---------------|
| OpenClaw crashloops on fresh clone | `openclaw/config/` is gitignored and never ships; Docker creates empty directories for bind mounts | `ISSUES-FOR-FIX-2026-07-22.md:15`, `:163-170` |
| `docker compose up -d` fails without `--build` | 7 services declare `image: harvis-*:local` but no `pull_policy: build` | `ISSUES-FOR-FIX-2026-07-22.md:158-161` |
| Missing migrations | `cron_jobs`, `workspace_jobs`, `workspace_runs` tables never created on fresh volume | `ISSUES-FOR-FIX-2026-07-22.md:153-156` |
| Workspace + Build dead | OpenClaw `v2026.5.22` does not honor `skipPairingForOperatorSharedAuth` | `ISSUES-FOR-FIX-2026-07-22.md:41-53` |
| Web search returns 0 sources | Research uses SearXNG but no SearXNG service exists | `ISSUES-FOR-FIX-2026-07-22.md:93-98` |
| 532 s cold build, 24 GB context | Missing `.dockerignore` | `docs/handoffs/2026-07-21-post-windows-e2e.md:63`, `:72-73` |

These are deployment-tier problems. A Core / Standard split would not fix every one, but it would make the "minimum viable Harvis" small enough that fresh-clone debugging is no longer a 25-service fire drill.

### 1.3 Knowledge / RAG infrastructure already exists but is immature

Harvis has **four** knowledge-like systems sharing one PostgreSQL + pgvector database:

| Component | Location | What it indexes | Maturity |
|-----------|----------|-----------------|----------|
| **Local RAG corpus** | `python_back_end/rag_corpus/` | Web docs, GitHub repos, Stack Overflow, security sources | Has `SourceConfig`, fetchers, chunker, embedding adapter, vectordb adapter, job manager (`source_config.py`, `source_fetchers.py`, `vectordb_adapter.py`, `job_manager.py`) |
| **Notebook RAG** | `python_back_end/notebooks/` | Per-notebook PDFs, URLs, markdown, audio transcripts | `notebook_chunks` table with vector embedding |
| **n8n workflow embeddings** | `embedding/` | Local n8n workflow JSON files | Standalone compose file; uses `langchain_postgres.PGVector` |
| **User memory** | `python_back_end/plugins/memory/` | Manual memory entries | `harvis_user_memory` table |

The RAG corpus design is ambitious: it uses two collections (`local_rag_corpus_docs` for 768-dim nomic-embed-text and `local_rag_corpus_code` for 2560-dim qwen3-embedding) and a `MultiCollectionRetriever` to blend them (`docs/RAG_ARCHITECTURE_DESIGN.md`).

**What it lacks vs. Onyx:**

- Persistent refresh schedules, incremental polling, and pruning.
- Credential management per source.
- Source-specific connector configuration UI/API.
- Connector health/status dashboard.
- Permission-aware retrieval.
- A clean connector interface contract.

The current `SourceConfig` dataclass (`python_back_end/rag_corpus/source_config.py:50-99`) is a good start, but it is doc-source-centric (base_url, sitemap_url, max_pages) rather than connector-lifecycle-centric (credentials, scope, refresh frequency, prune frequency, last sync, error state, document count).

### 1.4 No LLM-call tracing or cost accounting

Harvis routes to many models (Ollama, Kimi/Moonshot, NVIDIA NIM, OpenAI Codex, Anthropic Claude Code, Hermes) but there is no central tracing surface. The model proxy (`python_back_end/workspace/model_proxy.py`) resolves routes, yet there is no record of:

- Which flow requested the call (chat, research, workspace plan, code generation, etc.).
- Latency, input/output tokens, cost.
- Tool-call counts and errors.
- Which engine was actually used.

This makes it impossible to answer "why is this workflow expensive?" or "which engine performs best?" with data.

### 1.5 No `AGENTS.md`; `CLAUDE.md` is broad

Harvis has `CLAUDE.md` at repo root, plus OpenClaw-specific identity files (`openclaw/config/shared/SOUL.md`, `AGENT.md`, etc.). It does **not** have a concise, repo-level `AGENTS.md` aimed at coding agents — the kind Onyx maintains — that describes architecture, build/test commands, database rules, volume preservation, and security boundaries in one place.

---

## 2. Onyx Value Analysis

### 2.1 The biggest lesson: Onyx solved the deployment-tier problem

Onyx Lite and Standard are **not separate codebases**. They use the same images with a Compose override that pushes nonessential services into profiles, replaces Redis/object storage with PostgreSQL-backed alternatives, and disables the vector DB, connectors, model servers, and dedicated workers.

```text
Onyx Lite
├── API server
├── Web server
├── PostgreSQL
└── Nginx

Onyx Standard
├── Everything in Lite
├── Search/vector database
├── Background workers
├── Indexing and inference servers
├── Redis
└── Object storage
```

This maps cleanly onto Harvis:

```text
Harvis Core
├── nginx
├── frontend
├── backend-slim
├── PostgreSQL
└── artifact storage

Harvis Workspace
├── Repo Runner
├── OpenClaw
└── browser tools

Harvis Standard
├── notebooks
├── search/indexing
└── additional workspace services

Optional profiles
├── voice
├── local models
├── coding engines
├── CAD
├── document processing
└── evaluation tools
```

Onyx Lite runs only four services with a baseline under 1 GB of memory; Onyx Standard requires substantially more because it adds indexing, background workers, and model servers. That is exactly the trade-off Harvis needs to make explicit.

### 2.2 Connector architecture Harvis should borrow

Onyx connectors declare:

```text
Source
Credentials
Scope
Refresh frequency
Prune frequency
Last successful synchronization
Document count
Error state
Access policy
```

Each connector implements lifecycle methods: initial load, poll changes, delete missing content, health check. Harvis's `rag_corpus` fetchers are close to this but lack the lifecycle and status layer.

A Harvis connector interface could look like:

```python
class HarvisConnector:
    source_type: str

    def initial_load(self): ...
    def poll_changes(self, start_time, end_time): ...
    def delete_missing_content(self): ...
    def health_check(self): ...
```

Connector modes should be explicit:

| Mode | Behavior |
|------|----------|
| `external` | Search data where it already lives |
| `indexed` | Copy normalized content into Harvis search |
| `managed_sidecar` | Let Onyx perform the indexing |
| `live_tool` | Query the source through MCP when needed |

### 2.3 MCP is the cleanest integration path

Onyx can expose its knowledge base as an MCP server. MCP-compatible clients can search indexed documents, perform web searches, and fetch URLs using an authenticated HTTP endpoint.

Harvis already has an MCP bridge (`harvis-mcp` service, `python_back_end/mcp.server.app`). Consuming an external Onyx MCP server is a small addition compared to merging codebases.

This would let Harvis ask questions like:

- "Find the original decision that introduced the OpenClaw pairing flow."
- "Which documents mention the Docker VHDX failure?"
- "Compare the current Repo Runner security notes with the implementation."

Harvis receives ranked chunks, source metadata, and citations without adopting the Onyx frontend.

### 2.4 Agent + Knowledge + Actions model is useful framing

Onyx defines an agent as:

```text
Instructions
+ knowledge sources
+ actions
```

Actions can be built-in or added through MCP and OpenAPI. Harvis already goes further with engines, workspaces, task-specific surfaces, and execution environments, but the Onyx framing is cleaner for the user-facing model.

A Harvis agent card could be formalized as:

```text
Identity
├── Name
├── Purpose
└── Instructions

Knowledge
├── Project files
├── Indexed collections
├── Connected sources
└── Session memory

Engines
├── Claude
├── Kimi
├── OpenCode
├── Codex
└── Local models

Capabilities
├── Search
├── Browser
├── Repo Runner
├── Terminal
├── Documents
└── MCP actions

Permissions
├── Read
├── Write
├── Execute
└── Requires approval
```

### 2.5 Development practices worth copying

Onyx maintains an `AGENTS.md` that describes architecture, build commands, database rules, logs, testing assumptions, security practices, and where code belongs. Harvis should have the same, focused on:

- Product definition
- Architecture map
- Service ownership
- Build and test commands
- Safe Docker workflow
- Volume preservation rules
- Frontend deployment rules
- Migration conventions
- Engine integration rules
- Security boundaries
- Definition of done

Onyx also requires LLM, embedding, reranking, image, voice, and classification calls to be tagged with a registered flow identifier. Harvis should adopt equivalent flow IDs:

```text
CHAT
DEEP_RESEARCH
WORKSPACE_PLAN
REPO_INSPECTION
CODE_GENERATION
WEB_SEARCH
DOCUMENT_ANALYSIS
ENGINE_ROUTING
VOICE
SUMMARIZATION
```

Each call should record engine, model, flow, latency, input/output tokens, cost, tool calls, errors, and workspace/run ID.

### 2.6 Benchmarking: EnterpriseRAG-Bench

The Onyx organization publishes `EnterpriseRAG-Bench` with roughly 500,000 synthetic enterprise documents across GitHub, Gmail, Slack, Drive, Jira, Confluence, HubSpot, Linear, and meeting transcripts. It tests retrieval, conflicting information, multi-document reasoning, constrained search, and absent-answer handling.

Harvis could use a reduced version to evaluate its future Continuity Bridge instead of relying on "the search seems better."

### 2.7 Code execution vs. Repo Runner

Onyx has a restricted Python sandbox for data analysis, charts, and short-lived computation. It does **not** replace Harvis Repo Runner. They solve different problems:

| Onyx code execution | Harvis Repo Runner |
|---------------------|--------------------|
| Analyze files | Clone full repositories |
| Run Python calculations | Install project dependencies |
| Generate charts | Start application servers |
| Restricted sandbox | Interactive dev sandbox |
| No general network | Controlled network access |
| Short-lived | Full project lifecycle |

Harvis could borrow Onyx's narrow Python sandbox for spreadsheet/document analysis while keeping Repo Runner for full application execution.

---

## 3. Cross-Reference: Onyx vs. Harvis Gaps

| Onyx area | Value to Harvis | Grounded Harvis gap | Recommendation |
|-----------|-----------------|---------------------|----------------|
| Lite/Standard deployment design | Extremely high | 25 services, 1 profile, no tier choice | **Copy now** |
| Compose overrides + profiles | Extremely high | Optional engines not profiled; messaging is the only profile | **Use for optimization** |
| Connector architecture | High | `rag_corpus` has fetchers but no lifecycle/status/credentials | **Adapt the interface** |
| RAG and internal search | High | Existing dual-collection RAG; no enterprise connectors | **Test Onyx as external sidecar** |
| MCP server | High | `harvis-mcp` exists; could consume Onyx MCP | **Best initial integration** |
| LLM tracing conventions | High | No flow IDs, no cost/token tracking | **Implement natively** |
| EnterpriseRAG benchmark | High | No RAG benchmark | **Use for evaluation** |
| Python sandbox | Medium | Repo Runner exists; no doc-analysis sandbox | **Optional specialist service** |
| Full Onyx UI | Low | Harvis has own chat, workspace, build, notebooks | **Do not merge** |
| Full Onyx Standard on Windows dev box | Negative | F: drive crisis; 8 GB laptop GPU | **Do not install there** |
| Replacing Harvis with Onyx | Wrong direction | Harvis execution layer is the differentiator | **Do not do it** |

---

## 4. Other Repositories / Tools Harvis Could Use

This section is not about replacing Harvis components — it is about plugging specific gaps with focused, self-hosted tools.

### 4.1 SearXNG — fix web search out-of-the-box

**Problem:** Harvis research uses SearXNG (`python_back_end/deep_research/researcher.py:169`) but no SearXNG service is defined in compose, so web search returns 0 sources (`ISSUES-FOR-FIX-2026-07-22.md:93-98`).

**Solution:** Add an optional `searxng` profile or service. SearXNG is a self-hosted metasearch engine with a JSON API. It needs no API key and fits neatly as an optional profile.

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    profiles: ["search"]
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ./searxng:/etc/searxng:rw
```

This directly closes a documented P1 issue without building a search backend.

### 4.2 Langfuse or OpenLIT — LLM tracing and cost accounting

**Problem:** Harvis has no central LLM tracing. With Kimi, Claude Code, Codex, Ollama, Hermes, and NVIDIA NIM all in play, cost and performance are invisible.

**Options:**

| Tool | License | Strengths | Best for |
|------|---------|-----------|----------|
| **Langfuse** | MIT (core) | Full AI engineering platform: traces, evals, datasets, prompt management, OpenTelemetry endpoint | Teams that want prompt versioning, eval workflows, and detailed trace UI |
| **OpenLIT** | Apache-2.0 | OpenTelemetry-native, lightweight (UI + ClickHouse + OTel Collector), 50+ auto-instrumentations, GPU monitoring, guardrails | Teams that want vendor-neutral OTel instrumentation with minimal stack |

**Recommendation for Harvis:**

- If the priority is **prompt management + evals**, start with **Langfuse**.
- If the priority is **minimal, OpenTelemetry-native tracing** across many providers, start with **OpenLIT**.

Either can be self-hosted on the Proxmox box or a small VM, not on the Windows dev laptop.

### 4.3 RAGFlow or MiniRAG — fallback RAG options

If the Onyx sidecar pilot does not work out, Harvis should evaluate focused alternatives instead of building everything:

| Tool | License | Strengths | Best for |
|------|---------|-----------|----------|
| **RAGFlow** | Apache-2.0 | Deep document understanding, OCR, layout parsing, template-based chunking | Complex PDFs and scanned documents |
| **MiniRAG** | Research / open | Heterogeneous graph indexing, ~25% storage of LLM-based RAG, designed for small models | Low-resource, edge, or SLM deployments |
| **Vane** (formerly Perplexica) | Open source | Self-hosted AI search engine using SearXNG as backend | User-facing research search UI |

**Recommendation:** keep these as alternatives for Phase 3 evaluation; do not add them now.

### 4.4 Dify — not a fit

Dify is a full LLM application development platform. It would duplicate Harvis's chat, agent, workflow, and model-selection surfaces. **Do not merge.**

---

## 5. Recommended Phased Plan

### Phase 1 — Borrow architecture now (no Onyx deployment)

These changes improve Harvis directly and address the current disk/onboarding crisis:

1. **Split compose into tiers:**
   - `docker-compose.harvis-core.yml` — nginx, frontend, backend-slim, pgsql, artifact storage.
   - `docker-compose.harvis-standard.yml` — everything else (notebooks, search/indexing, TTS, engine sidecars, CAD, etc.).
   - Keep backend selection (`nvidia|amd|cpu`) as a second override.
2. **Add Compose profiles:** `voice`, `agents`, `local-models`, `notebooks`, `cad`, `document-processing`, `evaluation`.
3. **Update `install.sh`:** ask preset first (`core|standard|dev`) then backend (`nvidia|amd|cpu`).
4. **Add resource and free-disk preflight checks** to `install.sh`.
5. **Fix immediate fresh-clone blockers:** ship `openclaw/config/`, add `pull_policy: build`, fold missing migrations into init.
6. **Create `AGENTS.md`** at repo root.
7. **Implement LLM flow tracing** with flow IDs and per-call cost/token/logging.
8. **Add SearXNG as an optional `search` profile** to close the web-search gap.

### Phase 2 — Run an Onyx knowledge pilot externally

1. Deploy Onyx Standard **away from the Windows Harvis stack** (Proxmox VM or Docker VM).
2. Index only:
   - Harvis GitHub repository
   - Harvis documentation (`docs/`, `fixes/`, handoffs)
   - Weekly reports
   - Architecture notes
   - Issue/PR history
3. Expose Onyx to Harvis through its MCP server with a limited API key.
4. Create one Harvis capability: **Internal Project Search**. The user should not need to know Onyx exists.

### Phase 3 — Decide keep or replace

Measure:

- Search accuracy
- Citation quality
- Synchronization reliability
- Storage cost
- Memory usage
- Query latency
- Maintenance burden

Then choose:

- **Keep Onyx as the sidecar**, or
- **Port only the useful connector and retrieval patterns into Harvis**.

Do not decide before testing.

---

## 6. Final Verdict Table

| Area | Value | Recommendation |
|------|-------|----------------|
| Lite/Standard deployment design | Extremely high | **Copy the pattern now** |
| Compose overrides and profiles | Extremely high | **Use for Harvis optimization** |
| Connector architecture | High | **Adapt the interface** |
| RAG and internal search | High | **Test as external sidecar** |
| MCP server | High | **Best initial integration** |
| LLM tracing conventions | High | **Implement natively** |
| EnterpriseRAG benchmark | High | **Use for evaluation** |
| Python sandbox | Medium | **Optional specialist service** |
| SearXNG for web search | High | **Add as optional profile now** |
| Langfuse / OpenLIT tracing | High | **Self-host one as tracing backend** |
| Full Onyx UI | Low | **Do not merge** |
| Full Onyx Standard on Windows | Negative | **Do not install there** |
| Replacing Harvis with Onyx | Wrong direction | **Do not do it** |

---

## 7. Immediate Next Steps (prioritized)

1. **Confirm the tier split scope** — which services belong in Harvis Core vs Harvis Standard vs optional profiles.
2. **Decide tracing backend** — Langfuse (feature-rich) or OpenLIT (OTel-native, lighter).
3. **Add SearXNG profile** — closes a documented P1 issue with minimal work.
4. **Create `AGENTS.md`** — one-page repo guide for coding agents.
5. **Schedule Onyx sidecar pilot** — deploy on Proxmox/VM, not the dev laptop.

---

## Sources and References

- Onyx GitHub: https://github.com/onyx-dot-app/onyx
- Onyx deployment configuration: https://docs.onyx.app/deployment/configuration/configuration
- Onyx resourcing: https://docs.onyx.app/deployment/getting_started/resourcing
- Onyx connectors overview: https://docs.onyx.app/admins/connectors/overview
- Onyx GitHub connector: https://docs.onyx.app/admins/connectors/official/github
- Onyx MCP server: https://docs.onyx.app/deployment/configuration/mcp_server
- Onyx actions overview: https://docs.onyx.app/admins/actions/overview
- Onyx `AGENTS.md`: https://github.com/onyx-dot-app/onyx/blob/main/AGENTS.md
- EnterpriseRAG-Bench: https://arxiv.org/abs/2605.05253
- Onyx code interpreter: https://docs.onyx.app/overview/core_features/code_interpreter
- Onyx developers / auth overview: https://docs.onyx.app/developers/overview
- SearXNG repository: https://github.com/searxng/searxng
- Langfuse repository: https://github.com/langfuse/langfuse
- OpenLIT repository: https://github.com/openlit/openlit
- RAGFlow: https://github.com/infiniflow/ragflow
- MiniRAG: https://github.com/HKUDS/MiniRAG
- Vane (formerly Perplexica): https://github.com/ItzCrazyKns/Vane
- Top LLM observability tools 2026 comparison: https://www.confident-ai.com/knowledge-base/compare/top-7-llm-observability-tools
- Self-hosted LLM observability guide: https://urgentry.com/guides/ai-agents/self-hosted-llm-observability/
- OpenLIT docs / self-hosting: https://docs.openlit.io/latest/openlit/installation
