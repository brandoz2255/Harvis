# sentrysearch — research + integration plan (2026-07-30)

Candidate: https://github.com/ssrajadh/sentrysearch
Researched from primary sources only: the cloned repo (git history, LICENSE, pyproject, source, tests, CI), the GitHub API, and PyPI wheel metadata. Every number below was measured, not recalled.

## 0. The headline correction

**The name is a false flag.** "Sentry" here is **Tesla Sentry Mode**, not security/threat-intel and not Sentry-the-error-tracker. SentrySearch is **natural-language semantic search over video files** (dashcam/security-cam/any mp4/mov): chunk the video with ffmpeg, embed each chunk *as video* with Gemini Embedding 2 / Alibaba DashScope / a local Qwen3-VL model, store vectors in a local ChromaDB, then match text or image queries against them and auto-trim the winning clip. It has **zero** connection to threat intelligence, CVEs, OSINT, or NCL/CTF work. The security-search angle this research was scoped around does not exist in this repo.

Sources: README.md L1–48 ("Semantic search over video footage"), pyproject description "Search video footage using natural language queries", `sentrysearch/chunker.py`, `store.py` (ChromaDB, collection `dashcam_chunks`), `gemini_embedder.py`, `local_embedder.py`.

## 1. What it actually is — license and maturity up front

- **License: Apache-2.0.** Full standard text in `LICENSE`; confirmed by GitHub's license detection (`spdx_id: Apache-2.0`). No AGPL, no non-commercial rider. Clean for Harvis.
- **Stars/forks:** 4,396 stars, 420 forks, 18 watchers (GitHub API, 2026-07-30).
- **History:** 174 commits, first commit 2026-03-17, last commit 2026-07-22 (8 days ago). Actively maintained.
- **Contributors:** effectively a one-person project — Soham Rajadhyaksha (ssrajadh@ucsc.edu) authored 158/174 commits; ~8 drive-by contributors with 1–2 commits each (git shortlog).
- **Releases:** one tag only (`benchmark-clip-v1`); **no versioned releases, version pinned at 0.1.0** in pyproject. Distributed by `git clone` + `uv tool install`, not PyPI.
- **Tests & CI:** genuinely good for its size — 17 test files (~4,000 LOC of tests vs ~5,171 LOC package, biggest module `cli.py` at 1,495 LOC), GitHub Actions CI on ubuntu/macos/windows × Python 3.11/3.12 with coverage, plus a separate job that smoke-installs the torch `local` extra (`.github/workflows/ci.yml`).
- **Structure:** single Python package, Click CLI (`sentrysearch` entry point). Modules: chunker, store (ChromaDB), three embedder backends (Gemini cloud / DashScope qwen-cloud / local Qwen3-VL via transformers), two rerankers (Gemini 2.5 Flash / local Qwen3-VL-Instruct), highlights (kNN/centroid/LOF anomaly ranking), trimmer, Tesla-telemetry overlay (protobuf SEI parsing + Nominatim reverse geocoding), dead-letter queue for failed chunks.
- **Ecosystem:** part of a 3-tool pipeline with sibling repos SentryMerge (multi-cam stitching) and SentryBlur (redaction), coordinated through `~/.sentrysearch/last_search.json` / `last_clip.json`.
- **Notably:** it ships an **OpenClaw skill** — `docs/natural-language-video-search/SKILL.md` with clawdbot frontmatter (requires `GEMINI_API_KEY`, python3, uv, ffmpeg). It is **not** an MCP server and mentions MCP nowhere in the codebase (grepped).

Honest maturity read: a real, well-tested, actively developed personal project with unusual traction for four months — but single-maintainer, unversioned, and young. Not vaporware, not abandonware; "promising v0.1".

## 2. What problem it would solve for Harvis — and overlap analysis

- **Overlap with `python_back_end/research/`: none.** research/ is web search + article extraction over text. SentrySearch never touches the web for content (its only network calls are embedding APIs and optional Nominatim geocoding).
- **Overlap with the web-fetch proxy: none.** Different lanes entirely — this consumes local video files.
- **Overlap with Knowledge Bases / open-notebook / pgvector+fastembed: conceptually adjacent, technically disjoint.** Harvis's RAG stack is text-only ONNX embeddings in pgvector. SentrySearch adds a *modality Harvis has zero coverage of*: video as a searchable source. But it brings its own vector store (ChromaDB, local files under `~/.sentrysearch/db/`) rather than pgvector, and its embedding models are not replaceable by fastembed — **no torch-free local video-embedding model exists in Harvis's current toolchain**. The capability is genuinely new; it is also genuinely niche for an AI-workspace product.
- **NCL/CTF angle: does not apply.** The assignment flagged the security-search hope; verified answer is no. (Marginal stretch: video-forensics CTF challenges exist, but this tool doesn't do forensics — it does semantic retrieval.)
- **Local-first tension:** the only torch-free path (Gemini or DashScope backends) **uploads the user's private footage chunks to Google or to Alibaba-managed OSS**. The only private path is the `local` extra: torch + transformers>=5.4 + a 4–16 GB Qwen3-VL model. For a local-first project with a 7 GB disk budget, both horns of that dilemma hurt.

## 3. Verdict

**MCP-WRAP — optional, flag-gated, non-default profile — and only if David actually wants video search; otherwise SKIP.** It is a real, Apache-2.0, tested tool that adds a modality Harvis lacks, and Harvis's new MCP stdio runtime makes wrapping it a sibling-container job rather than a bespoke service; but it is not the security-search capability this slot was presumably reserved for, so confirm intent before spending any effort (Open question #1).

## 4. Integration plan (phased; skip all of it if the answer to OQ1 is "wrong repo")

**Phase 1 — MCP-wrap the CLI (the only phase worth doing first).**
- New image `harvis-mcp-sentrysearch`: `python:3.12-slim` + `pip install` the default extras only (never `local`/`local-quantized`), plus a ~150-line MCP stdio shim exposing `index(dir)`, `search(query, opts)`, `img_search(path)`, `highlights(opts)`, `stats`, `remove`, `reset` by shelling out to the Click CLI (or importing `sentrysearch.search`/`store` directly — the modules are cleanly importable). Registered in the existing MCP runtime as sibling container, tools land as `mcp__sentrysearch__*`.
- Mount: a read-only footage volume (user-chosen host path) + a named volume for `~/.sentrysearch` (index + DLQ).
- **Lane 5, default OFF.** Gemini backend = outbound HTTPS to `generativelanguage.googleapis.com` with `GEMINI_API_KEY`; this is an external service AND ships user video off-box, so the flag description must say so in plain words. Egress allow only that host (K8s NetworkPolicy / firewall on the sibling network).
- Files: `docker-compose` profile entry; MCP server manifest wherever the runtime registers stdio servers; shim script in a new `mcp-servers/sentrysearch/` dir. No backend code changes required — that's the entire point of the MCP path.
- Effort: ~1–2 days including live verification with real footage.

**Phase 2 (optional) — surface in UI.** Expose results (clip path + timestamp + score) in the Adaptive Space / notebooks as a "video sources" card; trimmed clips served from the shared volume. ~2–3 days.

**Phase 3 (only on explicit demand) — private/local backend.** A separate compose profile `sentrysearch-local` with the torch extra and GPU reservation. This is a **multi-GB torch stack + 4 GB (2B) or 16 GB (8B) model download** — permanently excluded from the default install and from the CI size guard's scope. On the dev box's 8 GB GPU only the 4-bit-quantized or 2B paths fit (repo's own hardware table).

**Do NOT** integrate via the OpenClaw skill it ships, tempting as that looks: Harvis's OpenClaw pod has deny-all egress, and the skill's default backend requires the Gemini API. It would fail by design, or worse, pressure someone to punch a hole in the OpenClaw network policy.

## 5. Size cost

- **Default (Gemini-backend) MCP container:** deps are click, python-dotenv, chromadb, google-genai, imageio-ffmpeg, protobuf. Measured wheel sizes: chromadb 23.5 MB (drags onnxruntime ~19 MB, grpcio ~12 MB, numpy ~19 MB, opentelemetry, kubernetes-client), imageio-ffmpeg 31 MB (bundled static ffmpeg), google-genai 1 MB. **Estimated image: ~450–600 MB total (python:3.12-slim base + ~300–400 MB site-packages).** Estimate, not measured — I did not build the image.
- **Volume:** ChromaDB index is small (768-dim vectors, one per ~30 s chunk — order of MBs per hour of footage); trimmed clips and the user's footage dominate and are user-controlled.
- **Torch?** **Not in the default path** — torch/torchvision/bitsandbytes/nvidia-cu12 appear in `uv.lock` only via the `local`/`local-quantized` extras. The local backend is torch + a 4–16 GB model and must never be DEFAULT.
- **Classification: compose profile / MCP-on-demand only. Never in the default 7 GB install.** Even the light image is ~0.5 GB of budget for a niche capability.

## 6. Distro notes

- **Linux + compose:** straightforward sibling container; needs the footage path bind-mounted and egress to the Gemini API allowed for that container only.
- **Windows (Docker Desktop/WSL2):** works — upstream CI tests Windows natively; inside a Linux container the platform is moot. Real friction is bind-mounting footage from the Windows filesystem (`/mnt/c/...` I/O is slow for multi-GB video; advise copying footage into a WSL2/volume path). Upstream's uv config even special-cases Windows CUDA wheels, but that's irrelevant to the containerized default path.
- **K8s:** container + PVC for the index + NetworkPolicy allowing only `generativelanguage.googleapis.com` — which collides with the known campus-network UDP/53 DNS blocking; the Gemini hostname would need the same CoreDNS workaround as `registry.ollama.ai` (K8S_DNS_WORKAROUND.md). Getting user footage into a cluster PVC is awkward; K8s is honestly a poor fit for this feature.

## 7. Risks, license and ToS traps

- **License: Apache-2.0 — clean.** No trap.
- **Single-maintainer, unversioned (0.1.0, no releases).** Pin a commit SHA; expect breaking changes. The README's "official source" notice suggests the author is already fighting unofficial mirrors.
- **Privacy ≠ Harvis's local-first story:** default backend uploads footage chunks to Google; qwen-cloud uploads to DashScope-managed OSS (README states this explicitly). Must be disclosed at the flag toggle, same pattern as the Web Research acknowledgment dialog.
- **Gemini Embedding 2 is in preview** (README "Limitations") — pricing/behavior may change; indexing costs real money (~$2.84 per hour of footage at defaults, README's own math).
- **Nominatim (OpenStreetMap) geocoding** in the overlay path has a usage policy (low request rates, attribution); optional `tesla` extra only — skip it.
- **Second vector store:** ChromaDB inside the container duplicates infra Harvis already has (pgvector). Acceptable when contained in one sibling container; do not let it leak into the backend proper.
- **Prompt-injection surface: low.** Inputs are local video + user queries; no fetched web text re-enters the model as instructions. Search results (filenames, scores) returned to the agent are data, and the MCP runtime already treats them as such.

## 8. Open questions (user only)

1. **Did you mean this repo?** The name reads "security search," but this is Tesla-dashcam video search. If the intent was a security/threat-intel search capability for the NCL/CTF goal, this repo is not it and the slot should be re-scoped.
2. If video search *is* wanted: is the Gemini cloud backend acceptable (footage leaves the box, ~$2.84/hr indexed), or is this only interesting if fully local — which means a torch profile and a 4–16 GB model on an 8 GB GPU?
3. Is there an actual user story (personal dashcam/CCTV archives? meeting recordings?) or would this be a capability without a customer?
