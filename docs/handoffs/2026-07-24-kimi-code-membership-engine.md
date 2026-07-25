# Handoff — 2026-07-24: Kimi Code membership engine + Moonshot platform verification

## One-line state

Two separate Kimi products are now separately wired and live-verified end-to-end **except** for the
one thing that needs a human: a real Kimi Code Console key. Nothing is committed.

## The distinction that drove everything

| | Moonshot developer platform | Kimi Code |
|---|---|---|
| Endpoint | `api.moonshot.ai/v1` or `api.moonshot.cn/v1` | `api.kimi.com/coding/v1/messages` |
| Console | `platform.moonshot.{ai,cn}` | `kimi.com/coding` |
| Wire format | OpenAI-compatible | **Anthropic-compatible** |
| Billing | pay-as-you-go balance | membership allowance |
| Harvis store | `user_api_keys` (provider `moonshot`) | `user_engine_auth` (engine `kimi-code`) |
| Harvis engine id | `kimi` | `kimi-code` |
| Harvis lane | `stream_kimi_workspace` (chat) | Claude Code sidecar (**full tool loop**) |

They are not interchangeable. A key from one 401s against the other. Everything in this change
exists to keep them apart.

## Why Kimi now behaves like Claude in Build

Not a model change. Claude Code supplies the loop — execute commands, read/write files, feed tool
results back, track permissions, collect diffs, handle cancellation. Kimi supplies reasoning inside
it. Because Kimi Code serves an Anthropic-compatible Messages API, repointing `ANTHROPIC_BASE_URL`
at it lets the **real** CLI drive Kimi, unchanged.

Running the real CLI is a compliance requirement, not convenience: Kimi's terms require third-party
coding tools to preserve their true client identity, so Harvis injects only documented env vars and
never imitates the client.

## Post-key update — the first real run found a third gotcha

The user connected a real key and reported "kimi provided no text back when asked hello — it does
create a script in workspace though." Two separate things:

1. **Chat was genuinely broken, now fixed.** `_stream_anthropic` required `data: ` *with a space*;
   Kimi Code sends `data:{…}` without one (the SSE spec makes the space optional). Every event was
   dropped, so the stream finished 200 with zero content deltas and the UI showed an empty message.
   Fixed to `startswith("data:")` + `line[5:].lstrip()`. Verified live 6/6, including an Anthropic
   regression guard. Also learned: **k3 always emits a `thinking` block first**, even for "hello" —
   it is wrapped in `<think>…</think>` so the UI collapses it.
2. **The workspace half was not a Kimi failure.** Run `bca294a8` finished `status=done` with a
   complete `final_summary` that opens *"in this environment I only have a **Read** tool
   available"*, matching the log line `auto launch bca294a8 — Tier-3 interactive withheld`. The
   Phase-D offer-time tool policy grants auto-launched runs Read only, so the model *described* a
   script. Engine-agnostic and pre-existing; whether auto-launch should grant write/exec is a
   product decision.

## Two gotchas worth remembering

1. **Every model slot must be pinned.** Claude Code resolves its own aliases internally (sonnet for
   the main loop, haiku for cheap side calls, a subagent model for `Task`). Pin only
   `ANTHROPIC_MODEL` and the run dies partway through with model-not-found instead of at the first
   token. All five slots + `CLAUDE_CODE_SUBAGENT_MODEL` are set.
2. **`kimi-code` must be matched before `kimi`/`moonshot` everywhere.** It shares the prefix. Both
   `workspace_bridge._resolve_engine` and the frontend `engineForOwner()` had (or would have had)
   this bug — a membership model routed to the pay-as-you-go lane: wrong credential, wrong bill, no
   tool loop.

## Verification already done

- Endpoint reality proven with two controls, not one 401: `/coding/v1/messages` → 401 in the coding
  app's own Anthropic envelope · `/nonexistent-xyz/…` → raw nginx HTML 404 · `/coding/v1/bogus` →
  `resource_not_found_error`. Three distinct layers ⇒ `/coding/` is a real, separate upstream.
- Sidecar reachability: 516 ms via `node -e fetch` (the image has no curl).
- 20/20 constants+routing, 13/13 engine-auth HTTP, 5/5 readiness, 10/10 store-isolation,
  7 existing regression tests. owui built + deployed; all new strings confirmed in served bundles.
- Auth-header question is moot: `x-api-key`, `Authorization: Bearer`, and *no header at all* return
  the identical 401, so verify sends both forms and cannot distinguish missing-vs-invalid.

## What is left

1. ~~User enters a real Kimi Code Console key~~ **DONE** — key connected and verified; chat answers.
   **Rotate it**: a debug probe of mine printed it to the terminal in plaintext.
2. **The 10-point E2E proof** against a fixture repo (`app.py` + `test_app.py`, task: "Change the
   greeting in app.py, run the tests, and report the files modified"): session engine is `kimi-code`;
   execution in `harvis-claude-code`; process receives `ANTHROPIC_BASE_URL=https://api.kimi.com/coding`;
   no Anthropic credential injected; CLI invokes file + shell tools; file actually modified; tests
   actually executed; diff collection reports it; membership quota consumed; no fallback to
   Gemma/Ollama/Anthropic. Plus the error paths: bad key → auth error · quota reached → quota status ·
   network error → temporary provider error · unsupported model → model-access error · cancel → the
   Claude process terminates.
3. **Commit** (one per task) then ask before pushing. Target `harvis1.1-deploy-test`;
   `origin/harvis1.1` stays untouched.
4. **Rotate the bad Moonshot key** — it is in Docker logs in plaintext.

## Deliberately not done

- **No second sidecar.** Engine id `kimi-code`, runtime container `harvis-claude-code`. A
  `harvis-kimi-code` image would duplicate ~1GB for an env-var difference. A `kimi-native` CLI
  sidecar can come later if Kimi ships its own CLI worth running.
- **`CLAUDE_CODE_EFFORT_LEVEL=high`** — in the spec, omitted here: not verified as supported by the
  installed CLI (2.1.195), and an unrecognised env var is a silent no-op at best.
- **No `.ai`/`.cn` choice for the subscription product.** That probe belongs to the Moonshot
  platform key only; Kimi Code has one endpoint.

## Files touched (all uncommitted)

Backend — `owui_compat/{engine_auth,cloud_chat,workspace_bridge,capabilities,integration_logs,moonshot_api}.py`,
`workspace/workspace_router.py`, `workspace/orchestration/engine_adapter.py`, `main.py`
Frontend — `lib/integrations/{catalog.ts,ConnectionPanel.svelte,status.ts}`,
`routes/(app)/harvis/vibecode/+page.svelte`, `lib/components/chat/Messages/WorkspaceRunCard.svelte`

Note: backend edits live in the **main tree** (`python_back_end/`), bind-mounted into
`harvis-backend` — `docker restart harvis-backend` deploys them. Root-level `python_back_end/*.py`
must be bind-mounted or live edits don't apply.
