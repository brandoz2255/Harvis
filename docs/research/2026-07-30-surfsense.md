# SurfSense — integration research (2026-07-30)

Candidate: https://github.com/MODSetter/SurfSense
Method: shallow clone of `main` at commit `4e9225b1` (2026-07-31), read of LICENSE, `surfsense_backend/pyproject.toml`, `surfsense_backend/Dockerfile`, `docker/docker-compose.yml`, source tree, plus GitHub API and ghcr.io registry manifests. All numbers below say how they were obtained.

---

## 1. What it actually is

**LICENSE — hybrid, and the headline feature is NOT open source.** The root `LICENSE` declares: everything is **Apache-2.0** *except* `surfsense_backend/app/proprietary/**`, which is **Business Source License 1.1** (Change License Apache-2.0, Change Date 4 years after each version's release, licensor "SurfSense"). GitHub's API reports the license as `Other / NOASSERTION` for this reason. The BUSL "Additional Use Grant" permits production use **only if you do not offer the Licensed Work, or any product whose value derives substantially from it, to third parties as a commercial product or hosted/managed service.** What lives in that BUSL directory (verified by listing it): the entire "live data" scraping stack — the stealth web crawler (captcha handling, fingerprint evasion, Xvfb headful mode) and platform scrapers for **google_search, google_maps, youtube, reddit, instagram, tiktok, amazon, walmart, indeed_jobs**. That is exactly the feature set SurfSense markets ("Research the open web with live data"). The knowledge-base/notebook/connector side is Apache-2.0.

**What it is.** SurfSense started (repo created 2024-07-30, per GitHub API) as an "open-source NotebookLM alternative" and has pivoted into a commercial **live-web-data-for-agents platform** (surfsense.com, pay-as-you-go billing via Stripe; the README states "Self-hosted installs ship with billing off"). The self-hostable product is: a knowledge base with 20+ SaaS connectors, a chat/research UI, scheduled agent automations, podcast/TTS generation, and the BUSL scraper API exposed over REST and an MCP server.

**Activity/maturity** (GitHub API, fetched 2026-07-30): 15,651 stars, 1,492 forks, 114 open issues, pushed_at 2026-07-31. Latest release v0.0.35 (2026-07-25); releases roughly weekly. Three dominant contributors (CREDO23 ~2,576 commits, AnishSarkar22 ~2,546, MODSetter ~2,260) — active but a small core team, and the 0.0.x version numbering is honest: schema and APIs move fast (e.g. the HEAD commit is a revert of a "kb-git-mvp" feature).

**Architecture** (from `docker/docker-compose.yml`, verified): **nine services** —
- `db`: `pgvector/pgvector:pg17` with a custom `postgresql.conf` requiring **`wal_level = logical`**, 10 replication slots, 10 WAL senders (verified in `docker/postgresql.conf`)
- `migrations`: one-shot Alembic runner that also verifies a `zero_publication` logical-replication publication
- `redis:8-alpine`: Celery broker + app cache
- `backend`: FastAPI (`SERVICE_ROLE=api`)
- `celery_worker` + `celery_beat`: same image, background indexing/automations
- `zero-cache`: `rocicorp/zero:1.6.0` — a client-side sync engine that tails Postgres logical replication to push live data to the frontend
- `frontend`: Next.js (`surfsense-web`)
- `proxy`: Caddy 2
Optional profiles: WhatsApp bridge (Baileys), OTel collector.

**Embeddings/LLM.** Chunking via `chonkie`, embeddings via chonkie `AutoEmbeddings` — the Dockerfile bakes **`sentence-transformers/all-MiniLM-L6-v2`** into the image (verified in Dockerfile ARG `EMBEDDING_MODEL`), i.e. local torch-based embeddings by default; a `litellm://` embedding model string can point at a remote endpoint instead (`app/config/embedding_settings.py`). LLM access is **litellm** throughout, so Ollama/any provider works. Vector store: **pgvector**, with a genuinely good hybrid retriever — pgvector similarity + Postgres `ts_rank_cd` full-text fused with **Reciprocal Rank Fusion in SQL** (`app/retriever/chunks_hybrid_search.py`), optional flashrank reranking.

**Connector surface** (verified by listing `app/connectors/` and `app/routes/`): Airtable, BookStack, ClickUp, Confluence, Discord, Dropbox, Elasticsearch, GitHub, Google Calendar/Drive/Gmail, Jira, Linear, Luma, Notion, OneDrive, Slack, Teams, Obsidian plugin, WhatsApp (self-hosted Baileys bridge), Telegram, Circleback webhooks, plus **Composio** (a third-party SaaS that provides managed OAuth for many toolkits — an external cloud dependency when used). Auth per connector: Google connectors need your own Google OAuth app (google-auth-oauthlib); Slack/Notion/Linear-style connectors use tokens or OAuth via a shared `oauth_connector_base.py`; Composio outsources OAuth entirely to Composio's cloud.

**The MCP OAuth client — the important discovery.** `app/routes/mcp_oauth_route.py` (676 lines) + `app/services/mcp_oauth/` (discovery 123 lines, registry 297 lines) + `app/utils/oauth_security.py` (231 lines) implement a complete **MCP OAuth 2.1 client: `.well-known` metadata discovery, Dynamic Client Registration, PKCE S256 (`generate_pkce_pair`, `code_challenge_method: "S256"`), token exchange** — with an origin-override for servers whose OAuth host differs from the MCP host (their example: Airtable). All of it is **outside `proprietary/` → Apache-2.0**. ~2,300 lines total including the reusable `oauth_connector_base.py` (625 lines), dependencies essentially just httpx.

**Browser extension** (verified: `surfsense_browser_extension/`, Apache-2.0, Plasmo framework, v0.0.35): captures browsing history and page snapshots in the background (`background/messages/savedata.ts`, `savesnapshot.ts`), converts pages with `dom-to-semantic-markdown`, and POSTs them to the SurfSense backend with the user's key. It is a **continuous history collector** ("Extension to collect Browsing History for SurfSense" — its own package.json description), not just a save-this-page clipper.

**MCP server** (`surfsense_mcp/`, explicitly `license = Apache-2.0` in its pyproject): a thin ~4-dependency (mcp, httpx, starlette, uvicorn) proxy exposing scrapers + knowledge base + workspaces as MCP tools against the REST API, authed by `SURFSENSE_API_KEY`.

**Telemetry:** PostHog is **opt-in** — no key set means the wrapper is a no-op (verified in `app/config/__init__.py` ~line 1185 and `app/observability/analytics.py`); an AI-privacy mode defaulting TRUE suppresses prompt/completion bodies. Stripe code exists but billing is off self-hosted. OTel optional.

## 2. What problem it solves for Harvis — overlap analysis

| SurfSense capability | Harvis already has | Is SurfSense's better? |
|---|---|---|
| NotebookLM-style knowledge base + chat with citations | Vendored open-notebook at `/onb` + K3 Knowledge Bases | Functionally duplicative. SurfSense's is more polished and more actively developed than lfnovo/open-notebook, but adopting it means replacing an already-integrated surface with a 9-service stack. |
| Web research (search + fetch + synthesize) | `python_back_end/research/` (DuckDuckGo/Tavily/newspaper3k, fixed and 55/55 live-verified 2026-07-24) | SurfSense's BUSL scrapers are far more capable (structured Reddit/YouTube/TikTok/Amazon data, stealth crawling) — but they are **not open source** and are the commercial core of their business. Not adoptable for an open project. |
| Hybrid retrieval (pgvector + FTS + RRF in SQL) | pgvector similarity search in K3/onb | **Yes, better** — and it's Apache, torch-free at the SQL layer, and portable onto Harvis's existing pgvector with no new dependencies. |
| SaaS connectors (Notion, Slack, GitHub, Google, …) | Storefront cards exist; 15 `remote_oauth` cards **blocked on missing MCP OAuth 2.1 + PKCE client** (task #97) | SurfSense has exactly the missing piece, Apache-licensed, ~2,300 lines, httpx-only. |
| Browser extension page capture | Nothing (browser-runner is server-side automation, not capture) | Net-new capability; the extension is Apache and re-pointable, though its always-on history collection posture needs softening for Harvis. |
| Podcast/TTS, STT | Chatterbox TTS, Whisper STT already in Harvis | Duplicate; SurfSense's kokoro/faster-whisper add torch weight for nothing Harvis lacks. |
| Local embeddings | fastembed/ONNX, deliberately torch-free | SurfSense defaults to sentence-transformers → **torch**. Worse for Harvis by policy. |

Net: the *product* duplicates open-notebook + K3 + research/. The *parts worth having* are the Apache-licensed connective tissue: the MCP OAuth client, the connector base pattern, the RRF hybrid retriever, and (optionally) the extension.

## 3. Verdict

**HARVEST-IDEAS.** Adopting SurfSense whole is disqualified three ways at once: its backend image alone (2.20 GB compressed → est. 5.5–7 GB on disk) plus five extra services would blow Harvis's entire 7 GB budget; its flagship live-data feature is BUSL 1.1 (not open source, precedent: PyMuPDF was removed for less); and its knowledge-base core duplicates open-notebook/K3. Its Apache-licensed MCP OAuth 2.1 + PKCE client, however, is precisely the one component blocking 15 storefront connector cards (task #97), and it plus the RRF hybrid retriever are cheap, torch-free ports.

## 4. Integration plan (harvest, phased)

**Phase 1 — MCP OAuth 2.1 client (unblocks task #97).**
- Port `surfsense_backend/app/services/mcp_oauth/{discovery,registry}.py`, `app/utils/oauth_security.py`, and the flow logic of `app/routes/mcp_oauth_route.py` into a new `python_back_end/integrations/mcp_oauth/` package (keep Apache-2.0 headers + NOTICE attribution per Apache §4).
- New tables for client registrations + token storage (encrypted at rest) in Harvis Postgres; new routes under `/api/integrations/mcp-oauth/*` in `python_back_end/main.py`, JWT-gated.
- Wire the 15 `remote_oauth` storefront cards in `front_end/owui/src/lib/` connect flow to the new endpoints.
- **Gate:** lane 5 (external services), per-connector capability flag, default OFF. Every outbound token-bearing call passes `authorize_action()` in `python_back_end/workspace/orchestration/authz.py`.
- Estimated effort: 1–2 sessions; dependency cost: zero new packages (httpx already available).

**Phase 2 — RRF hybrid search for K3.**
- Re-implement the pattern from `app/retriever/chunks_hybrid_search.py` (pgvector CTE + `ts_rank_cd` CTE + FULL OUTER JOIN RRF) against Harvis's existing pgvector tables; add a tsvector column + GIN index via a safe migration (backup first per repo policy).
- No new services, no new deps, no flag needed (lane 2 data, existing surfaces). Effort: ~1 session + evaluation against current retrieval.

**Phase 3 (optional, ask user first) — "Save to Harvis" browser extension.**
- Fork `surfsense_browser_extension/` (Apache, Plasmo), strip the continuous-history collector, keep explicit save-page/save-snapshot → POST to a new `/api/kb/capture` endpoint feeding K3/onb ingestion.
- Gate: lane 5 flag for the capture endpoint; extension is user-installed, off by default. Effort: 2–3 sessions (extension build chain + endpoint + ingestion).

**Explicitly NOT ported:** anything under `app/proprietary/` (BUSL), zero-cache/Rocicorp sync, Celery/Redis, sentence-transformers embeddings, kokoro/faster-whisper, Composio.

## 5. Size cost

- **Full adoption (rejected):** backend image `ghcr.io/modsetter/surfsense-backend:latest` = **2.20 GB compressed across 21 layers** (measured directly from the ghcr.io registry manifest, amd64). On-disk uncompressed size unverified without pulling; torch+model stacks typically inflate 2.5–3×, so estimate **~5.5–7 GB on disk**. The image bakes in: torch 2.11 CPU (or CUDA variant), sentence-transformers + all-MiniLM-L6-v2, EasyOCR models, Docling models, a patchright Chromium (`scrapling install`), Pandoc 3.9, ffmpeg, espeak-ng. Frontend image = **0.34 GB compressed** (measured, ~1 GB on disk est.). Plus `pgvector:pg17`, `redis:8`, `rocicorp/zero:1.6.0`, `caddy:2` and five persistent volumes (postgres, redis, zero replica, object store, shared temp). **This single candidate exceeds the entire 7 GB fresh-install budget; the CI guard at 7.5 GB would fail immediately.**
- **Torch:** yes — `sentence-transformers>=3.4.1` is a *mandatory* dependency in `surfsense_backend/pyproject.toml`; the cpu/cu126/cu128 extras only choose which torch index, the Dockerfile always installs one. Close to disqualifying on its own, per Harvis policy.
- **Harvest path (chosen):** ~2,300 lines of Python + a tsvector migration. **Zero image growth, zero new services, zero new dependencies.** DEFAULT service set unaffected.
- **DB sharing (if anyone revisits adoption):** SurfSense could technically point at Harvis's Postgres, but it requires pg17-era pgvector image, `wal_level = logical`, replication slots, its own Alembic migration chain, and a `zero_publication` — invasive changes to Harvis's shared pg15 database. Not recommended.

## 6. Distro notes (for the harvest path)

- **Linux/compose:** Phase 1–2 are pure backend code + one migration; restart `harvis-backend` (bind-mount inode trap applies — restart, don't trust live edits on root-level files).
- **Windows/WSL2:** OAuth callback URLs must resolve to the browser-reachable origin (`http://localhost:9000` via nginx), not an internal Docker name — same rule as Linux since Harvis fronts everything with nginx; no `host.docker.internal` needed for this feature. Extension (Phase 3) is host-browser software, identical on all OSes.
- **K8s:** token-storage table lives in the existing pgsql; outbound OAuth/token-exchange calls need egress from the backend pod to the identity providers — note the campus cluster blocks outbound UDP/53, so provider hostnames may need CoreDNS entries (see `K8S_DNS_WORKAROUND.md`). NetworkPolicy: OAuth egress is backend-pod-only, never OpenClaw.

## 7. Risks, license and ToS traps

- **BUSL 1.1 on `app/proprietary/**`** — not open source (BUSL's own Notice says so). Harvis must never vendor, wrap, or ship anything from that directory. Even self-hosting it is constrained: the Additional Use Grant forbids offering it as a commercial/hosted service, which conflicts with Harvis's "anyone can deploy this" posture.
- **The BUSL boundary can move.** The split is one paragraph in the root LICENSE; the maintainers can (and given the commercial pivot, may) move more code under `proprietary/` in future versions. Any harvested code must be pinned to commit `4e9225b1` (or earlier) with its Apache license header and a NOTICE entry recording origin + commit.
- **Scraper ToS exposure:** the BUSL scrapers exist to evade bot protection on Reddit/TikTok/Instagram/Amazon/Google (stealth, captcha handling, fake-useragent, DoH). Endorsing or bundling that would import platform-ToS risk Harvis doesn't need — one more reason the harvest excludes them.
- **Verify before trusting the ported OAuth code:** (a) run it against at least two real MCP OAuth servers (e.g. Notion, Airtable) end-to-end — this repo's own history (research pipeline "worked" for months without ever running) says live verification only; (b) audit token storage encryption and redirect-URI validation in `oauth_security.py` rather than assuming it; (c) check `registry.py` for any callbacks to surfsense.com infrastructure before porting.
- **Maturity risk:** 0.0.x versioning, weekly breaking releases, HEAD is a feature revert. Fine for harvesting frozen code; bad for tracking upstream.
- **Composio, Daytona, Stripe, PostHog** are all cloud-service integrations in their stack — none come along in the harvest, but anyone later widening the port should treat each as an external-egress flag decision.

## 8. Open questions (user only)

1. Priority call: does the MCP OAuth port (Phase 1) jump the queue given it unblocks the 15 `remote_oauth` storefront cards from task #97, or does it wait behind the current Adaptive Space work?
2. Phase 3 (browser extension): do you want Harvis to ship a capture extension at all? It's net-new surface area and a privacy-posture decision (even stripped to explicit-save).
3. Attribution style: NOTICE file at repo root vs. per-file headers for the ported Apache code — any preference?
