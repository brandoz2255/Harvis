# Handoff — 2026-07-25: notebook chat fixed and rig-verified, then the modularization plan written

## One-line state

Three notebook/nav commits are **pushed** to `harvis1.1-deploy-test` and **verified E2E in a browser
on the rig**. A fourth commit — the modularization plan, docs only — sits **local and unpushed** on
`harvis1.1`. No code work is in flight. One decision is blocking the next batch of work.

| Commit | What | Where it is |
|---|---|---|
| `04bf26c3` | notebooks: resolve chat + embedding models from what Ollama actually has | pushed, rig-verified |
| `ca6fb9a3` | db: apply podcast migrations 005–007 at startup | pushed, rig-verified |
| `498c25db` | owui: drop duplicate Notebooks "Customize", rename Build's to "Tune" | pushed, rig-verified |
| `9b725684` | docs(plan): modularization — capability packs, adapter boundaries, 3-container core | **local only** |

`origin/harvis1.1` is untouched, still at `bcd6005e`.

## Part 1 — the notebook fix (closed)

The rig reported notebook chat returning 404 and "no sources," and blamed the hardcoded
`llama3.1:8b` in `onb_compat/router.py`. **That was the third rig report in a row whose headline
diagnosis was wrong**, and the real chain runs the other direction:

1. `notebooks/ingestion.py::_get_embedding` tried a fixed list of five embedders and returned
   `None` when none was pulled.
2. Retrieval then matched nothing.
3. The request fell through to `_chat_without_rag`, whose prompt literally says *"I couldn't search
   them right now"* — that is the "no sources" text users were seeing.
4. **That** path called `/api/generate` with one hardcoded model and no fallback. Hence the 404.

The RAG chat lane already had a 404-aware fallback chain, so the chat default was never what failed.
The fix is adaptive resolution on both lanes: append what `/api/tags` actually reports after the
preferred list, drop embedders from chat candidates, defer reasoning models (they emit into
`thinking` and can return a blank `response`), and have `_generate_response` return the model that
actually answered so `model_used` stops naming one that never ran.

**Verified in-browser on the rig:** notebook "Google's Digital Ecosystem," 3 sources, model resolved
to `granite4.1:8b`, embedder locked to `nomic-embed-text`, real synopsis with `[1]` citations.

Worth remembering: the rig's sources had been ingested about an hour *before* the fix and needed no
re-ingestion — so the embedder was reachable at ingest time on that box, and the visible failure was
concentrated in the chat lane. Don't assume "no sources" always means ingestion never embedded.

**Still open from this:** roughly 37 other hardcoded `llama3.1:8b` sites (orchestration, discord,
cron, title-gen). Same failure class, deliberately not swept untested.

## Part 2 — verifying the Windows deployment sweep

The rig ran a four-way analysis (footprint, modularity, startup, onboarding). Checked against the
tree: **13 claims confirmed, 3 corrected, and 3 things it missed.**

### Corrections

- `install.sh` **does** offer a chat-model pull (`offer_model_pull`, line 393). The real gap is
  narrower: `--yes` deliberately skips it, and **no embedding model is pulled by anything** —
  `nomic-embed-text` appears nowhere in the installer. That is exactly what produced the notebook
  failure above.
- Image sizes double-count shared layers. `backend`, `model-downloader`, and `harvis-mcp` share one
  16.9 GB ML base counted **once**; adding their displayed sizes triple-counts it. Read the unique
  column from `docker system df -v`.
- The biggest reclaimable thing on this box isn't an image. It's **149 GB of build cache** against
  295 GB of images. `docker builder prune` beats every code change in the plan for raw disk.

### What it missed

- **Six** migrations never run at boot, not one — `001`, `002`, `008`, `009`,
  `add_ide_chat_tables.sql`. `run_migrations.py` exists in the repo with **no caller anywhere**. Two
  of them (rvc, ide_chat) have zero Python references, which is the argument against the obvious
  fix: a runner that globs every `.sql` would create tables for features that no longer exist.
- **`vibecoding_sessions` exists on no deploy, including this working dev box**, yet
  `vibecoding/sessions.py` is mounted at `/api/vibecode/sessions` (`main.py:1467`) and every query in
  it targets that missing table. Live Build uses `agent_runs`. Mounted dead code exposing routes that
  can only fail, on a machine where everything looks healthy.
- `frontend` is deader than reported: a 1512 MB Next.js build in nginx's `depends_on`, serving
  exactly one nginx location (`/api/ai-chat`, `nginx.conf:271`) that **nothing in owui or the backend
  calls.**

## Part 3 — the plan (documented, nothing implemented)

Canonical: `docs/plans/2026-07-25-harvis-modularization-plan.md`.
Narrative: Obsidian `code/harvis/2026-07-25-modularization-capability-packs`.
Memory: `project_modularization_capability_packs.md`.

Target shape:

```
Harvis Core        nginx · backend · postgres
Optional runtime   Ollama | Claude/OpenAI/Moonshot | OpenClaw
Capability packs   Build · Browser · Notebooks · Voice · Messaging · Experimental
```

**The keystone, and the reason the priority order changed:** `backend` hard-depends on `openclaw` and
`browser-runner`; `nginx` hard-depends on `frontend`. **Compose profiles cannot shrink anything while
optional services sit in `depends_on`.** So the order is dependencies → adapters → profiles, and the
migration runner / embedder pull / memory cap / starter prompts drop to batch 3 — they are real work
but they are reliability and polish, and they will not make Harvis smaller.

Ollama also leaves the core. A user already running it with a chat model should have it *detected and
adopted* — verify container→host reachability (a different question from whether it works in the
terminal), record `managed: false`, never stop it, never delete its models. That user's Harvis is
three containers.

## Where to pick up tomorrow

1. **Answer the open decision** (below) — it's the only thing blocking batch 1.
2. Then batch 1 items 2, 4, 5 are the cheapest with the highest leverage and carry no design
   decisions: drop `nginx`→`frontend`, stop `llmfit` reserving a full GPU to be a hardware scanner,
   cap `backend` memory (it's the only always-on torch process without a limit).
3. `docker builder prune` any time — 149 GB, no code change, independent of everything else.
4. Push `9b725684` when authorized.

**Open decision, blocking:** does `frontend` get deleted outright, or profiled behind `legacy` for one
transition release while we log whether anything ever hits `/api/ai-chat`?

## Older items still open

- ~37 hardcoded `llama3.1:8b` sites (see part 1).
- `research/pipeline/research_agent.py::_extraction_stage` fabricates content.
- `showEngineMenu` dead state; `CLAUDE.md` points documentation at the nonexistent
  `front_end/jfrontend/changes.md`; `analysis_md` turns hide the actions row during type-out.
- Rotate `HARVIS_SETUP_CODE`; enter the Kimi Code membership key on the Windows box.
- GitHub OAuth still reports `configured:false`; NVIDIA NIM tile (B3); image-gen last mile.
