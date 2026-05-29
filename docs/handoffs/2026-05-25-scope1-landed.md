# Session handoff — Scope 1 landed, gemma diagnostic deferred (2026-05-25, late)

## Goal

Land Scope 1 (failure-driven model escalation in the Discord bot) on `feat/hermes-integration` and then turn to the real underlying problem: gemma4:e4b narrates "Executing the cracker..." on hash tasks instead of emitting the `exec` tool call. Scope 1 is the safety net. Fixing gemma is the actual work, deferred to tomorrow.

## State at handoff

### Code in flight (UNCOMMITTED — working tree only)

- **`python_back_end/integrations/discord_workspace_bot.py`** — +179/−2 lines, syntax-clean, dark-landed behind `HARVIS_ESCALATE_ON_FAILURE` env flag (default `false`). Four logical blocks:
  1. Module-level state (lines ~107–129): env flag + `_ESCALATION_PAIRS` (`qwen3:14b ↔ gemma4:e4b`, symmetric) + `_ESCALATION_FAILURE_PATTERNS` (4 fabrication-banner substrings).
  2. Helper at ~line 1288: `_looks_like_escalation_worthy_failure(status, summary, err) → (bool, reason)`. Pure output-side detection — never inspects task brief.
  3. Hook at ~line 2120 (between `progress_msg.delete()` and `if status == "done":`): single-attempt retry with `chat_history=[]` + fresh `session_id` (`f"{session_id}-esc-{workspace_id}"`). For `pref_agent_id == "main"`, calls `_apply_model_to_native_openclaw(alternate)` (OpenClaw restart + ready-wait, ~5–22s).
  4. Delivery merge (`if status == "done"` / failure branches): appends `escalation_note` to the user-visible message.

Run `git diff python_back_end/integrations/discord_workspace_bot.py` in the main worktree to re-eyeball before committing.

### Reviewed and noted (not blockers)

- **No-chaining guarantee is structural**, not gated by an explicit flag. Flat sequence inside `on_message`, no loop, `launch_workspace_internal` doesn't recurse. Correct but reader has to follow control flow to see it. Could add a defensive `local _escalation_consumed = True` toggle if you'd rather have belt+suspenders — currently theatre because there's no re-entry to protect against.
- **Block 3 (the hook) is ~125 lines.** Could be factored into `async def _escalate_to_alternate(...)` to compress the on_message hook to ~30 lines. Readability win, not correctness.
- **`pref_agent_id == "local"` coverage gap.** When user has done `@bot set-model X`, route goes through `stream_local_ollama_workspace` which bypasses OpenClaw / model_proxy / the fabrication validators. No banner = no escalation trigger on hash-narration failures. Escalation only catches `status == "error"` on that route. Real fix is making validators also run on the local route — separate problem, not introduced by Scope 1.
- **session_id rewrite** `f"{session_id}-esc-{workspace_id}"`. Unique per channel+user (8-char uuid suffix). The `-esc-` infix is the "escalation session marker" if you ever want to filter escalation workspaces out of `/workspace/history`.

### NOT done

- No git commit. User said "hold off, eyeball the diff" → reviewed → "i'll run the tests i guess" → redirected to gemma → "work on it tomorrow." Last instruction was stop-for-tonight, so the code sits as a working-tree change. Decide tomorrow whether to commit as-is or refactor block 3 first.
- No smoke tests run. The two tests below are the gating checks before flipping `HARVIS_ESCALATE_ON_FAILURE=true`.
- **No push** (standing rule `feedback_no_push_until_verified`).

## Tomorrow's agenda — three blocks, in order

### Block A — Decide what to do with the Scope 1 code (~10 min)

Pick one:

1. **Commit as-is** on `feat/hermes-integration` (no push). Cleanest if you don't care about the block-3 size. Commit message draft:
   ```
   feat(discord): failure-driven model escalation between paired models

   Scope 1 from docs/handoffs/2026-05-25-phase3-scopes.md. Dark behind
   HARVIS_ESCALATE_ON_FAILURE (default false). When the active model's
   workspace fails AND the model is in {qwen3:14b ↔ gemma4:e4b} AND the
   summary contains a fabrication banner from the hash/CTF validators,
   the bot re-launches with the alternate, fresh session, dropped history.
   Single attempt, no chaining. Surfaces the swap inline to the user.

   Pure output-side detection — never inspects the task brief. Rolls back
   by flipping the env flag off.
   ```
2. **Refactor block 3 into `_escalate_to_alternate(...)` helper, then commit.** ~20 min extra. Slightly cleaner diff for future readers; behavior identical.
3. **Throw it out.** If the gemma diagnostic in Block C reveals an obvious fix and you decide escalation is overkill, `git checkout -- python_back_end/integrations/discord_workspace_bot.py` and move on.

Default recommendation: commit as-is (option 1) so the dark code is preserved in history regardless of whether you flip the flag tomorrow.

### Block B — Smoke-test Scope 1 (~15 min, only if committing)

Setup: same as migration suite (OpenClaw `main` route, no `set-model` active). Set `HARVIS_ESCALATE_ON_FAILURE=true` in the backend env, restart backend.

**Test B1 (positive):** Discord post the 5 pokemon MD5 hashes with gemma4:e4b as the OpenClaw default.
- Expected: gemma narrates → validator emits "Could not determine plaintext" → bot sends "⤴ Default model `gemma4:e4b` couldn't complete… retrying on `qwen3:14b`…" → qwen3 launches with fresh session → 5/5 verified → final reply with escalation note.
- Watch for: `_debug_log` entry with `runId=run_escalation, hypothesisId=H_scope1` in `/tmp/debug-d007eb.log`.

**Test B2 (negative):** Discord post MCQ #1 (OWASP prompt-injection) with qwen3:14b as default.
- Expected: qwen3 answers wrong ("API Gateway") → NO escalation fires (no fabrication banner on a wrong-but-honest MCQ answer) → user sees the wrong answer as normal output.
- This is the false-positive guard. If escalation DOES fire here, the failure-pattern matcher is too eager.

If both pass, leave the flag on. If B1 passes but B2 escalates, narrow the patterns. If B1 doesn't escalate, the OpenClaw route isn't surfacing the banner — likely a `pref_agent_id == "local"` situation (see coverage gap above).

### Block C — Real work: gemma hash tool-call diagnostic (~45 min)

This is what the user actually wants — making gemma DO the exec call instead of narrating it.

**Step 1 — Capture what gemma is emitting.** Discord: post one hash brief on gemma4:e4b through the OpenClaw main route. Then:

```bash
docker compose logs backend 2>&1 | grep -E "BUDGET|ACTUAL|tool_calls=|finish_reason|content_len|markdown.tool|rescue" | tail -40
```

**Step 2 — Match the symptom to the lever:**

| What the log shows | Likely cause | Lever to pull |
|---|---|---|
| `tool_calls=0, finish_reason=stop`, content has full heredoc text | Gemma wrote the script into the response instead of into an `exec` arg. Few-shot pattern-matched as "describe approach" not "emit tool call" | Re-shape `hash_hint` for gemma: lead with the tool-call schema example first, then the heredoc body. Or test a different few-shot framing ("Your next message MUST be a tool_call. Example:") |
| `tool_calls=0, finish_reason=stop`, content is one narration line | Gemma stopped after narrating. Could be `num_predict` cap or template eating the second emission | Check per-model defaults in `model_proxy.py`. Bump `num_predict` or remove early-stop sequences |
| `tool_calls=0, finish_reason=length` | Cut off mid-emission | Bump `num_predict` higher for gemma on hash tasks |
| `markdown tool_call rescue` fires | Gemma emitted the call as markdown JSON, rescue caught it | Adjust schema or system prompt; the rescue already saves the run, but the right fix is making gemma use the agent channel |
| `content_len > 1000` with no tool_call | Gemma generating prose response — the schema's tool definitions aren't being chosen | Check `tool_choice` value; `auto` may not be enough. Try schema shape changes |

**Step 3 — One change at a time.** Whatever lever you pick, change it, restart backend, retest the same hash brief. Don't bundle multiple interventions or you can't tell which one helped.

**Step 4 — Acceptance.** Gemma passes when one workspace run on the same 5 pokemon MD5s shows `tool_calls=1` (the heredoc one-shot exec) and 5/5 verified plaintexts, no escalation triggered.

## Rejected for tonight (deferred / killed)

- **Scope 2 — reasoning-override investigation:** explicitly rejected in `2026-05-25-phase3-scopes.md`. "Best-case outcome is 'now I know,' not 'now Harvis works better.' Phase 2A's single data point is enough to act on: reasoning-override accepted as best-effort for high-prior MCQs."
- **Phase 2B Hermes4 higher-quant retest:** blocked on rig terminal access. Documented unblock commands in `2026-05-25-b7-v4-closeout.md` (Phase 2 section). Defer until you're at the rig.
- **Per-task-shape keyword routing:** killed by `feedback_no_keyword_model_routing`. If you find yourself wanting to "detect hash tasks → route to qwen3," stop. That's the failure mode the no-keyword-routing rule exists to prevent. Scope 1 is the correct shape (failure-driven, not capability-detection).

## Memory edits already landed this session (yesterday's commits, NOT pushed)

- `project_openclaw_b7_blocked.md` → replaced "blocked" with "shipped, commit 774f8dd"
- `project_model_task_pairing.md` → new, qwen3/gemma4/hermes4 task-shape table
- `feedback_ollama_tool_choice_ceiling.md` → new, don't build forcing logic that assumes Ollama enforcement
- `MEMORY.md` index updated

No new memory edits tonight — handoff captures what's worth recalling.

## Quick resume tomorrow

1. Read this doc + `2026-05-25-phase3-scopes.md` + `2026-05-25-b7-v4-closeout.md` (the three handoffs from today).
2. Decide Block A: commit, refactor+commit, or discard.
3. Decide Block B: smoke-test (if committing) or skip.
4. Block C is the actual goal: gemma tool-call diagnostic, one lever at a time.

Branch state: `feat/hermes-integration`, 4 commits ahead of where this session opened (B7 plugin + v4 push-through + MCQ-force revert + 2 handoff docs), `discord_workspace_bot.py` is uncommitted working-tree state. No push.
