# 2026-08-02 — The 500-char clip, honest run verdicts, and credentials out of the event log

**Branch:** `harvis1.2` @ `095678a5` · **Deployed and live-verified · nothing committed.**

Five files changed, all backend, all bind-mounted (a `docker compose restart backend` deploys them):

| File | Change |
|---|---|
| `python_back_end/workspace/orchestration/runner.py` | Tool-result budget, duplicate-call guard, forced-answer round, `answered` success term, honest error text |
| `python_back_end/workspace/orchestration/orchestrator.py` | Root `done` event now carries `success` |
| `python_back_end/workspace/workspace_router.py` | Downgrades a `done` whose agents all failed; redacts every payload before persist |
| `python_back_end/workspace/build_narrator.py` | Failed runs keep the partial work they produced |
| `python_back_end/workspace/secret_redaction.py` | **New.** Shared credential scrubber |

---

## 1. The agent wasn't looping. It was being starved.

The reported symptom was an agent that ran 409 seconds, read the same README seven times, timed out,
and then printed **"Build complete"** over the wreckage. The obvious diagnosis — a missing loop guard —
was wrong, or at least it was the third-most-important thing.

`runner.py` builds a `results_text` list, and that list is the **only** channel by which a tool's
output reaches the model's conversation. Both places that appended to it clipped the result to 400 or
500 characters. Five hundred characters is a sensible cap for `"wrote 3 files"`. It is destructive for
a fetched page: a 24,000-character README arrived as its first 500 characters, so the agent went
looking for a hardware section it had never been shown, fetched the same URL again, got the same 500
characters, and repeated.

Everything downstream followed from that one line: the repeated reads, the context bloat, the
`httpx.ReadTimeout`, and the blank `error:` card. It also means the coder agent had never once seen
more than 500 characters of any file it called `read_file` on.

The fix is a `fit()` closure with three budgets:

```python
_TOOL_RESULT_CHARS = 500     # status-shaped tools, unchanged
_READ_RESULT_CHARS = 12000   # per content-tool result (agent_reach.*, read_file)
_READ_TOTAL_CHARS  = 36000   # run-wide ceiling, so three long pages can't crowd out the context
```

A truncated result now says so in the text, so *"I don't have the rest"* is a claim the model can make
honestly instead of assuming the page simply ended.

**Measured, same prompt** (*"read the README of openai/gpt-oss and tell me what hardware it needs"*):

| Model | Before | After |
|---|---|---|
| `gemma4:12b` | 240s timeout, no answer | **17.6s, correct answer** |
| `gpt-oss:20b` | 7 re-reads, 409s | **1 fetch, correct answer, 63s** |

Both now return the real numbers (80 GB single GPU for gpt-oss-120b, 16 GB for gpt-oss-20b, 4×H100 for
the unoptimized PyTorch reference).

### The four smaller runner fixes

- **Duplicate-call guard** — a ledger keyed on `name|sorted-args`; the third identical call gets
  `ALREADY DONE at step N` instead of executing. It fired twice before the budget fix and **zero times
  after**. It is a backstop now, not the cure.
- **Forced-answer round** — when the guard trips, the current step's results are carried into a
  tool-less final round so the run ends with an answer rather than a truncation.
- **`answered` success term** — the no-tool-calls branch set a summary but never marked success, so a
  model that answers in prose (and therefore never calls `finish()`) was flagged **failed** while
  returning a correct answer. Now `answered = bool(content) and not edit_attempted` — a run that tried
  to *change* something and merely stopped talking is still a failure.
- **Honest error text** — `str(exc)` with a fallback to the exception class name, and a human sentence
  for timeouts. The blank `error:` card is gone.

## 2. "Build complete" over a failed run — the narrator was innocent

`build_narrator.compose_build_analysis` has a correct `status == "error"` branch. It was never called
with `"error"`. `orchestrator.py` emitted an unconditional `yield root_ev("done", …)`: every child
could die and the run row still said `done`.

Three coordinated changes:

1. The orchestrator's `done` payload now carries `success: all(child.ok)`. `all()` over an empty list
   is `True`, so a zero-children run keeps its old behavior — deliberately conservative.
2. `workspace_router` downgrades `terminal_status` to `error` when that flag is `False`. The event
   type stays `done` so the summary still renders; only the verdict changes.
3. The narrator's error branch now keeps whatever the run produced before it died, under
   **"What I got before it stopped"** — a bare error with the work thrown away leaves nothing to act on.

Verified by calling `compose_build_analysis(status="error", …)` directly: the headline reads
*"**Build failed** — agent-native hit an error before finishing."* with the partial summary intact.
Regression check: a build-style run (read `notes.txt`, write `SUMMARY.md`) still completes green with
the file on disk.

## 3. Credentials no longer reach the event log

A Build run once executed `env | grep -iE "api|host|url|port|file"` and the tool result was persisted
verbatim into `workspace_events` — a live API key in plaintext in Postgres, readable by anything that
reads run history, including the SkillOpt miner and every database backup.

**Three redaction implementations already existed** (`owui_compat/integration_logs.py`,
`workspace/kubectl_proxy.py`, `skills_training/trajectories.py`) and **every one of them would have
caught this string.** None of them ran on the path that stored it. This was never a pattern gap. It
was a missing application point.

`secret_redaction.py` consolidates the patterns and `_db_save_event` — the single funnel every
workspace event passes through — now calls `redact_payload()` immediately before the INSERT.
Redaction happens at **persist** time, not at tool-output time: the operator still sees their own
shell output live, which is the point of running `env`; only the durable copy is scrubbed.

Covered shapes: `SCREAMING_CASE_KEY=value` env assignments, JSON/YAML `"api_key": "…"`, credentials
inside connection URLs (`postgresql://user:pass@host` — the env pattern misses these because
`DATABASE_URL` doesn't end in a credential word), `sk-` / `ghp_` / `xox*` / `AKIA` literals, JWTs, PEM
private key blocks, and whole values under credential-named payload keys.

Two traps worth knowing about, both found by testing rather than reading:

- **The patterns cannibalized each other.** The env pattern produced `API_KEY=[REDACTED]`; the prose
  pattern then matched that same `API_KEY=` and re-redacted the placeholder up to its own bracket,
  yielding `[REDACTED]]`. Every value group now carries `(?!\[REDACTED)`.
- **The JSON form didn't match** because the pattern required `key\s*[=:]` and JSON puts a quote
  between them.

**Verification** — 9 credential shapes redact, 6 benign strings survive untouched (`OLLAMA_URL=…`,
`PATH=…`, `HARVIS_ORCH_TOOL_RESULT_CHARS=500`, ordinary prose). Then end-to-end through the real
persist path with the live pool: a synthetic sentinel written via `_db_save_event`, read back out of
the jsonb column, **absent**; the placeholder present; the benign env lines intact; test rows cleaned
up.

### The historical rows

Scanned **all 86,731** events. A broad pattern matched 180 rows, but **178 of those are web-fetch text
and assistant prose that merely mention key-shaped strings** — documentation, blog posts, a model
explaining how to set an env var. Exactly **2 rows hold a genuinely assigned credential**, and they are
**two different secrets**:

| Row | Run | Date | Secret |
|---|---|---|---|
| 72952 | `33261075` | 2026-05-20 | `OPENCLAW_GATEWAY_TOKEN` |
| 86549 | `67155356` | 2026-08-02 | `ANTHROPIC_API_KEY` (the Kimi key) |

Both were scrubbed in place with the same `redact_text` that now guards the write path — the
surrounding content is preserved, only the credential is replaced. Re-checked after: no credential
shape remains, placeholder present in both.

**Both need rotating, not just the Kimi one.**

## 4. SkillOpt — assessed, then parked

Re-ran the offline job with no `--publish-draft`: 254 trajectories, 91.3% success. Agent Reach appears
in the corpus for the first time. Per-tool failure rates: `read` **50%**, `web_fetch` 40%,
`str_replace` 28%; `exec` and `bash` stable. The 20 reach failures decompose as 12 Jina 403 / 4
`gh_view` 415 / 3 bare `owner/repo` / 1 not-found.

**The finding that matters: the candidate it produced would have banned the Agent Reach tools shipped
the same day**, instructing the agent not to use `agent_reach.web_read`, `web_search`, or `gh_view` on
the false claim that they "are not available in the Harvis Build environment." It passed **all 10
structural gates.**

The gates have an inverse hole. `no_invented_tools` catches a candidate *inventing* a tool absent from
`WIRE_TOOL_SCHEMA`; nothing catches a candidate *banning* a tool that is present. Draft `6dee2773` is
live-but-inert (`enabled=f`, empty audit) and benign. There is still no held-out eval.

Parked at the user's direction. Task #120.

---

## State

- **87 dirty files** on `harvis1.2`. Scanned for real credentials: **one hit, and it's a deliberate
  fixture** inside `test_leaked_secret_is_rejected` in `python_back_end/tests/test_skillopt_gate.py`.
  Safe to commit.
- `scripts/commit-groups-2026-08-01.sh` still matches **zero** pathspecs for `chat_reach.py`,
  `provider_route.py`, `workspace_bridge.py`, `chat_completion.py`, `model_router.py`,
  `orchestrator.py`, `build_narrator.py`, and now `secret_redaction.py`. `workspace_router.py` and
  `runner.py` match once each but inside unrelated groups. **Task #124 — extend it before running it.**
- Safe deletions staged: `python_back_end/api/__init__.py`, `api/tts_routes.py` (336 lines, zero
  importers verified).

## Open

- **Rotate both credentials** — the Kimi/Anthropic key and `OPENCLAW_GATEWAY_TOKEN`.
- `gh_view` returns **415 Unsupported Media Type** on 4 runs. Unfixed.
- Jina 403 direct-fetch + HTML-to-text fallback — still the largest reach failure at 12 of 20.
- No HTTPS → voice only works on the Docker host.
- screenshot-to-code: spec at `docs/design/2026-07-31-screenshot-to-code-build-spec.md`, nothing built.
- #106 free-provider live E2E · #110 paid cloud models declare no usage capability · #97 MCP OAuth 2.1
  + PKCE · #102 provider fallback chain.
