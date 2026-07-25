# Handoff — 2026-07-24: the research pipeline had never run, and Kimi stopped leaking its thinking

## One-line state

Three commits sit on local `harvis1.1`, **all deployed live and verified (55/55), none pushed**:
`5335baaf` (credential honesty, prior session), `1d140c41` (research pipeline), `e272ac14` (Kimi
thinking gate + `changes.md`). Push target when authorized is `harvis1.1-deploy-test`.
**Two API keys still need rotating by a human.**

## How this session started and where it went

The user reported one bug: *"sent hello but also showed the think."* Fixing it took twenty minutes.
Chasing why the research lane looked wrong in the same logs took the rest of the session and turned
up the largest silent-success defect found in this codebase so far.

## Finding: the "enhanced research pipeline" had never once run

Every research request reported `research_depth: "enhanced"` and logged
`🚀 USING ENHANCED PIPELINE with BM25 ranking and map/reduce synthesis`. None of it ran. The answer
came from a single direct-LLM call over page **titles** — and one layer below that, from a stub that
never contacted a model at all.

It only became visible because `5335baaf` (last session) made the streaming path report its failures
instead of swallowing them. **That is the pattern: each honesty fix exposes the next lie.**

### Six defects, stacked — each masked by the next fallback

| # | Where | What |
|---|---|---|
| 1 | `agent_research.py` | called `advanced_agent._generate_queries()`; the method is `_planning_stage`. `AttributeError` every time → research ran on the single verbatim query |
| 2 | `agent_research.py` | `_ranking_stage(query, List[Dict])` builds its own `DocChunk`s from `content["url"]`; it was handed already-built `DocChunk`s → `TypeError: 'DocChunk' object is not subscriptable` |
| 3 | `agent_research.py` | read the article body from `content`; `extract_content_from_url` returns it under **`text`** (`research/web_search.py:213`) → every chunk was `""` while `success` stayed `True` |
| 4 | `research/rank/bm25.py` | textbook IDF `log((N-df+0.5)/(df+0.5))` goes **negative** past 50% document frequency → ranking returned nothing even when it "succeeded" |
| 5 | `research/synth/map_reduce.py` | read `chunk.chunk.chunk_id` and `.chunk.content`; `DocChunk` has neither → MAP failed 100% of the time |
| 6 | `research/llm/ollama_client.py` | **never called Ollama.** Slept 0.1s, returned `f"Response to '{prompt[:50]}...' using model {attempt_model}"` with `success=True` |

Defect 6 is the one to remember. A live run confirmed that template string *was* the research
synthesis: `Response to 'You are a research synthesizer combining informati...' using model gemma3:12b`.

### Why the BM25 bug is subtle and worth keeping in mind

The negative-IDF form is textbook-correct and harmless on a web-scale index. It is fatal *here*
because this ranker only ever sees the handful of pages fetched **for that query** — so every query
term appears in nearly every document, every term contributes a negative score, and totals land
below `min_score`. Fixed with the non-negative `log(1 + x)` variant. If a ranker is ever added
elsewhere over a small query-local corpus, it will have the same bug.

### Also fixed along the way

- **The user's model pick was ignored.** A run selected as `gemma3:12b` was answered by `qwen2.5:3b`
  because the task-policy default was applied unconditionally. Only visible because `5335baaf`
  started reporting `answered_by` honestly.
- **The MAP phase discarded every result on timeout** despite a comment claiming it returned partial
  ones — the phase-wide `wait_for` returned `[]`. Timeout is now per-chunk.
- **Timeouts were sized for a 0.1s stub** (30s/60s). Now 180s, sized for real local inference.

## The reported bug: Kimi's chain-of-thought

`_stream_anthropic()` wrapped every `thinking_delta` in `<think>…</think>` unconditionally. Correct
for Claude, where a thinking block exists only because the request set `payload["thinking"]`. Kimi
Code's k3 emits one on **every** turn, and that lane deliberately never requests thinking (the
parameter is rejected on `api.kimi.com/coding`).

Reasoning is now shown only when `"thinking" in payload`. Otherwise it is buffered and dropped —
**except** when the model produced no text at all, where the buffer is surfaced instead, so a
thinking-only turn never renders as silence. That exception preserves the invariant established by
last session's SSE fix: *the chat lane must never return an empty message.* The non-streaming
`_anthropic_msg_to_openai()` follows the same rule via a `show_thinking` argument.

## Verification — all live, none stubbed

| Suite | Result | What it proves |
|---|---|---|
| `t_pipeline.py` | 28/28 | real `PONG` from Ollama; ranking keeps 6/7 on a homogeneous corpus and still drops the off-topic doc; MAP 9/9; REDUCE ok; a live run names Macron in 3694 chars with `model_used: gemma3:12b` and no fallback in the logs |
| `t_think.py` | 10/10 | unrequested reasoning dropped, requested reasoning kept, thinking-only turns non-empty, on both stream and non-stream paths |
| `t_honesty.py` | 12/12 | prior credential-honesty work not regressed |
| `t_regress.py` | 5/5 | local research still works; **answer grew 1840 → 4250 chars** — direct evidence the pipeline now contributes |

Tests live in the session scratchpad, not the repo. The pattern: write to scratchpad →
`docker cp` into `harvis-backend` → `docker exec python3 /tmp/<test>.py`.

## Deploy mechanism (matters for the next person)

`docker-compose.yaml` bind-mounts the backend's Python **individually**: `main.py`,
`agent_research.py`, `model_manager.py`, and the `research/`, `owui_compat/`, `workspace/`, … dirs
(lines 352–378). Everything touched this session is mounted, so **`docker restart harvis-backend`
deploys it** — confirmed in-container. A *new* mount needs `docker compose up -d backend`, not
`restart`. Root-level modules that are not individually listed are baked into the image and live
edits will not apply.

## What needs a human

1. **Rotate two keys.** The bad Moonshot key is in Docker logs in plaintext; the live Kimi Code key
   was printed by an earlier debug probe. Both must be rotated regardless of what else happens.
2. **Authorize the push** of `5335baaf`, `1d140c41`, `e272ac14` to `harvis1.1-deploy-test`.

## Still open in this area

- **`research/pipeline/research_agent.py::_extraction_stage` fabricates content** — returns
  `"This is the extracted content for {title}."`. Reached only via `ResearchAgent.research()`, not
  the streaming lane fixed here. Same stub-reports-success shape; not fixed.
- **The sync research lane is still unguarded.** `research_agent`, `fact_check_agent`, and
  `comparative_research_agent` have generic handlers; `async_query_llm`/`query_llm` return failures
  as **prose strings that become the answer** (`research/research_agent.py:267,305`).
- **`OllamaClient.get_available_models()` and `stream_generate()` are still stubs.** Neither is on a
  path exercised here, but both will lie if something starts calling them.

## Process note

The code edits belong to the **main tree** (`/home/user/Harvis`, branch
`harvis1.1`), not the worktree — the worktree's `changes.md` is stale and an entry written there
would have been lost. Check which tree a file actually lives in before editing.

## Wider lesson

Every fix this session peeled back another layer of the same defect shape: **an operation reports
success while having done nothing, or having been done by something other than what it reports.**
Query expansion, extraction, ranking, MAP, REDUCE, and the LLM client each announced success. The
only reason any of it surfaced is that someone made one layer stop lying. Assume the next layer down
is lying too, and check it against a live run rather than a stub.
