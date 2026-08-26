# Handoff — 2026-08-11 · a Claude subscription can author CAD parts

Branch `harvis1.2`. Backend restarted and verified live. **Nothing committed.**

## The one-line version

Picking Opus 5 in CAD chat used to silently hand the job to `qwen3:4b`. It no longer does — the
selected Claude model authors the part through the Claude Code sidecar, and a model that genuinely
cannot run now says so instead of being quietly replaced.

## What was actually wrong

`cad_agent.resolve_lane()` knew two Anthropic doors and this account has neither:

1. an OpenAI-compatible provider row → no Anthropic row exists
2. the direct Messages API, which needs a stored **API key** → this account has an **OAuth
   subscription token**

Both missed, `resolve_lane` returned `None`, and `None` meant "local model, use `cad_generate`".
The backend said so in the log, twice, once per attempt:

```
cad_agent: anthropic/claude-opus-5 is a Claude model with no stored Anthropic api_key
cad_bridge: 'anthropic/claude-opus-5' is not installed on any inference host — designing with qwen3:4b
```

The credential state, read live from Postgres (`user_engine_auth`, user 2):

| engine | auth_mode | has_secret | verified_at |
|---|---|---|---|
| `claude-code` | `oauth_token` | t | 2026-08-12 01:21:27+00 |
| `gemini` | `api_key` | t | 2026-08-01 19:55:14+00 |

There is no Anthropic API key and there is not going to be one — a subscription token is not an API
credential. The repo already said this out loud, at `engine_auth.py:146`, in
`_verify_oauth_token_via_cli`'s docstring: *"We do NOT hit the Anthropic Messages API: a
subscription token is for Claude Code, not normal API requests."* That closed the design question.
I had earlier measured a `429` rather than a `401` on the OAuth → `/v1/messages` path and called it
inconclusive; the codebase's own note settles it against that route regardless of what the status
code implied.

## The fix — a third lane

`Lane.kind` was `"openai_compatible" | "anthropic"`. It is now three, and the new one is
`"claude_code"`: the real `claude` CLI inside `harvis-claude-code`, driving the **same nine CAD
tools** over MCP, through the **same `cad_tools.dispatch`**. Ownership, quota, proposal state and
DesignSpec grading are untouched — only the dialer changed.

### `owui_compat/cad_agent.py` (untracked — new file, extended today)

- `Lane.__init__` gains `engine=`, naming which `user_engine_auth` row serves a lane that runs a
  CLI rather than calling an HTTP API.
- `resolve_lane()` branch 3: an Anthropic model with any verified `claude-code` credential →
  `Lane("claude_code", "anthropic", model_name, engine="claude-code")`. Checked with
  `get_verified_auth_mode`, which reads the mode without decrypting the secret.
- `unavailable_reason(model_name, pool, user_id)` — new. `resolve_lane` returning `None` had two
  unrelated meanings and only the caller can tell them apart. This answers the second (a cloud
  model with no usable credential) and stays silent on the first (a genuine local pick), so a local
  model is still a local model.
- `_author_via_sidecar()` — the runner. Returns the identical dict shape `author()` returns, so
  `cad_bridge._native_lane` renders the card with no change.
- `author()` dispatches to it when `lane.kind == "claude_code"`.

### `owui_compat/cad_mcp.py` (untracked — new file, extended today)

`sidecar_mcp_config()` now emits an `x-harvis-cad-context` header (base64 JSON) beside the bearer
token, carrying `conversation_id`, `user_text`, `model_provider`, `model_name`.

**Why this exists.** A sidecar cannot know the conversation it belongs to or what the person
actually typed. Without server injection those arrive — if at all — as `_meta` the *model* wrote,
and the DesignSpec answer key would then be extracted from the model's paraphrase of the request.
Putting them in the header makes them exactly as trustworthy as the token they sit next to: both
are written by Harvis into one launch, and a process that could forge one could equally have stolen
the other. The model is never asked for them and no tool accepts them. This is the Gate 7C rule —
*"Harvis injects authenticated user/session context server-side; models receive opaque IDs"* —
applied to the sidecar case.

`_injected_context(request)` reads it and never raises; the route's `ctx_for` prefers it over
`_meta` in every field, and takes `model_provider`/`model_name` **only** from the header.

### `workspace/orchestration/engine_adapter.py`

`_cad_mcp_args(user_id, **context)` forwards the context. All three pre-existing call sites pass
only `user_id` and are behaviourally unchanged.

### `owui_compat/cad_bridge.py` — the honesty half

- Where `resolve_lane` returns `None`, call `cad_agent.unavailable_reason()` and emit that notice
  instead of designing locally.
- `_local_model()` now returns `(model, missing)`. `missing` is `True` only when the catalogue was
  readable and genuinely lacked the selection — the caller refuses rather than substituting
  `HARVIS_CAD_MODEL`. An **unreadable** catalogue is still not grounds to override the user; that
  path is unchanged and the generate call fails on its own terms.

## Details that will bite whoever touches this next

- **`CLAUDE_CODE_SIMPLE` must be cleared, not set, for OAuth.** The sidecar image bakes
  `CLAUDE_CODE_SIMPLE=1`, which reads `ANTHROPIC_API_KEY` and **ignores** the OAuth token. OAuth
  launches pass `-e CLAUDE_CODE_SIMPLE=` (empty). API-key launches pass `=1`. Copied from the
  proven shape in `run_claude_chat_workspace`.
- **`is_error` before `subtype`.** A `result` event for a 401 arrives as
  `{"subtype":"success","is_error":true,"api_error_status":401}`. Reading `subtype` first renders
  an auth failure as the model's answer.
- **Correlation comes from the tool results, not the database.** `cad_tools.as_text` is
  `json.dumps`, so every `tool_result` block in the CLI's stream carries parseable JSON with
  `project_id` / `revision_id` / `build_id` / `title` / `conformance_status`. Rejected
  alternatives: DB time-window correlation (races a second tab) and a synthetic conversation id
  (pollutes `cad_projects.conversation_id`).
- **Deliberately not `--strict-mcp-config`** — it would ignore every other MCP server the user
  already connected.
- Both containers sit on `ollama-n8n-network`, which is how the sidecar reaches
  `http://backend:8000/api/cad/mcp`.
- The scratch workdir is `rmdir`'d, not `rm -rf`'d: the CAD tools write nothing there and the CLI's
  file tools are withheld, so a non-empty directory is a surprise worth leaving intact to look at.

## Verified live, in the running stack

Two independent runs of the same request — *a 40 × 20 × 4 mm plate with a 5 mm centre hole* —
through `cad_agent.author()` with the real subscription credential.

```
LANE: ('claude_code', 'anthropic', 'anthropic/claude-opus-5', 'claude-code')

ok            true              true
build_id      302b9df2…         ae2a6468…
title         Rectangular plate with centre hole
conformance   passed            passed
rounds        6                 6
latency_ms    21231             20995
```

The tool trace, in order: `ToolSearch` ×2 (the CLI discovering the server), then
`mcp__harvis-cad__cad_get_schema` → `cad_create_project` → `cad_start_build` → `cad_get_build`, all
`ok: true`.

Provenance in Postgres for revision `318e64c5-…`:

| field | value |
|---|---|
| `conversation_id` | `probe-claude-sidecar` (from the header) |
| `model_provider` / `model_name` | `anthropic` / `anthropic/claude-opus-5` |
| `design_spec.source` | **`user_message`** |
| `design_spec.intent` | the request verbatim, not a paraphrase |

Also: `docker exec harvis-backend python -m pytest tests/test_cad_tools.py -q` → **30 passed**.
Scratch-dir cleanup confirmed — the second run left nothing in
`/data/artifacts/cad-agent` inside `harvis-claude-code`.

## What is NOT proven

- Only one part shape has run this lane. The water bottle and the humanoid figure — the two
  requests that failed originally — have not been retried on it.
- The **API-key** branch of the sidecar credential path is written but untested; there is no
  Anthropic API key on this deployment to test it with.
- Kimi Code gets the context header for free (same `_cad_mcp_args`) but nothing routes CAD to it.
- Nothing about this touched the CAD Studio panel's own generate box, which is a separate lane.

## Commit state — read before running any script

`cad_agent.py` and `cad_mcp.py` are **untracked**. `scripts/commit-gate7bc-authoring.sh` already
names both, and its partial-commit-by-pathspec mechanism is sound.

**Done today, to both scripts:**

1. The 7bc message's closing paragraph claimed *"the provider hop … has not been demonstrated end
   to end."* It has been, twice. Replaced with a `7C-3b` section describing the subscription lane,
   the live result, and what genuinely remains unproven.
2. `python_back_end/workspace/orchestration/engine_adapter.py` is **double-claimed** — the file
   holds `_cad_mcp_args` (this work) *and* the attachment staging from the 08-01 arc, and
   `scripts/commit-groups-2026-08-01.sh` group 11 already names it. Git commits a file once. It is
   deliberately **left out** of the CAD script; group 11's message now names the CAD rider
   explicitly, which is the convention that script's own group 10 already uses. Order therefore
   matters: **run `commit-groups-2026-08-01.sh` before `commit-gate7bc-authoring.sh`.**

**Still an open decision, not resolved:** `python_back_end/owui_compat/cloud_chat.py`. Same
double-arc problem — the free-tier provider work and the Opus 5 model entry added for this work sit
in one file — but unlike `engine_adapter.py` neither arc is obviously the host. It is named by no
CAD script. Deciding where it lands is a call for whoever owns the repo.

## Next

Retry the water bottle on Opus 5 in the CAD chat. That is the request that failed before, and it is
a harder test than a plate.
