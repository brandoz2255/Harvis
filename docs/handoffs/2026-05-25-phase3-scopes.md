# Phase 3 scopes — gate before implement (2026-05-25)

Two scopes, each held to the 4-question gate plus a hard kill criterion. Per session directive, neither implementation starts until the user signs off on the scope as-written. Drift signals (e.g. "we'll figure it out during implementation," tests without pass/fail, time estimates with "depends on what we find") = scope hasn't been written; pause and rewrite.

---

## Scope 1 — Model-routing architecture

### 1. What's the specific problem?

`@bot set-model qwen3:14b` and `@bot set-model gemma4:e4b` are manual per-conversation overrides. Tonight's migration-suite results show **clear model-task pairing**: qwen3 handles hash CodeAct; gemma4 handles MCQ/decode/crypto/conversational. A user posting a hash brief on the gemma4 default gets failure (model narrates, no exec); the inverse on MCQ gets training-data recall instead of web_search. Manual `set-model` puts that selection burden on the user, who has to know the task taxonomy ahead of time. The system has the information to route correctly — it just doesn't use it.

### 2. What does the solution look like in shape?

**Pick: failure-driven escalation, NOT capability-detection.** Reasoning: capability-detection (route on the same regex / hint-attachment that already detects hash/decode/etc) reuses the existing detector but functionally creates the keyword-routing pattern killed in `feedback_no_keyword_model_routing`. The fact that the regex is "already there for hints" doesn't change what we're DOING with it — still routing models off keywords. Failure-driven is the only pattern that respects the no-detector rule.

Concrete shape:
- Start every workspace on the user's `set-model` choice OR the configured default (`gemma4:e4b` is the current candidate based on broader coverage)
- After `Background task finished`, evaluate a small set of failure signals: `status=error`, `Hash-claim fabrication caught`, `CTF process-claim fabrication caught`, `tool_calls=0 AND task_brief_matched_a_skill_hint` (i.e. model emitted no tools on a task that explicitly required them)
- On failure → spawn ONE escalation retry on the alternate model with `reset-context` semantics (drop history, fresh session, re-post the original task). NOT a new corrective prompt — fresh start.
- Surface the escalation to the user: "Default model couldn't complete; retrying on `<alternate>`."
- One escalation max. If alternate also fails → return the alternate's output with a "neither model succeeded" wrapper. Do not chain further.

### 3. What does done look like?

Three observable pass criteria, ANDed:
1. Hash brief on gemma4 default → fails → auto-escalates to qwen3 → 5/5 verified in the same Discord message thread, with an inline "Escalated to qwen3:14b" log line visible to the user
2. MCQ #1 on qwen3 default → wrong API Gateway answer NOT caught by validator → no escalation (correct — escalation triggers only on detectable failure)
3. Decode/crypto/conversational on either default → completes first try, no escalation log line

Negative test (must NOT happen):
- Escalation triggering on a successful run because some unrelated log line tripped the detector
- Infinite escalation loops (chain limit = 1)

### 4. What's the rollback if it doesn't work?

Single-file change in `python_back_end/workspace/openclaw_client.py` (or `workspace_router.py`) adding an `escalate_to_alternate_on_failure` flag. Default flag = `False` to land the code dark, flip to `True` only after smoke tests pass. Rollback = flip flag off, ship. No schema changes, no infra changes, no config changes outside the flag.

### Kill criterion

If implementation reveals **any of the following**, kill the work and revert:
- The failure-detection requires regex/keyword inspection of the user task (i.e. we end up reintroducing the killed detector pattern through the back door)
- Escalation latency (extra workspace launch + new model load) pushes typical hash-task completion from ~30s to >2 min
- More than 2 attempts needed in tests to verify the 5/5 hash escalation works deterministically (suggests retry mechanism itself is flaky on top of the model issue)
- The escalation logic ends up implementing per-task-shape behavior internally to decide WHICH model to escalate TO (again, detector by another name)

Estimate: 60-90 min implementation + 30 min smoke. Total 90-120 min. NOT including the scope review iteration.

---

## Scope 2 — Reasoning-override investigation

### 1. What's the specific problem?

MCQ #1 Run 3 (2026-05-25): gemma4 voluntarily called web_search, integrated OWASP results that named LLM Agent, then **derived its own threat-modeling reasoning** ("the API Gateway is where the data leak actually happens") and answered API Gateway despite the contradicting evidence. The model can read source material correctly and still prefer self-derived logic. This is a model-class property, not a Harvis bug.

We don't know whether it's **fixable** (temperature, prompting, reranking) or **fundamental** (small-model reasoning calibration just does this). The Phase 2A CVE hardness test produced ONE data point suggesting reasoning-override is scoped to high-prior questions, but a single data point doesn't make a pattern.

### 2. What does the solution look like in shape?

**Pick: temperature sweep + targeted-replay only.** Reasoning: this is the most BOUNDED of the candidate experiments. Doesn't change any code in the agent stack. Doesn't introduce new prompts. Just measures the same prompt across temperature 0.0, 0.3, 0.7, 1.0 and counts how often the override pattern reproduces.

Concrete shape:
- Replay the exact MCQ #1 prompt on gemma4:e4b at temperatures [0.0, 0.3, 0.7, 1.0] via direct Ollama API (not through Harvis — control the variable)
- Replay 5 times per temperature setting = 20 total runs (~30 min wall-clock)
- Capture: did web_search fire (substrate probe — gemma4 doesn't reliably honor `tool_choice=auto` at the bare-Ollama layer, so we simulate the OpenClaw harness with `tools.allow=[web_search]` only), what did the model conclude, did it cite OWASP, did it override
- Two ADDITIONAL hard MCQs at different prior-strength levels (per advisor's "establish the pattern needs 2-3 more tests"):
  - Partial coverage + contradicting evidence: a security MCQ where the model's training has weak priors and our local search corpus has a clear answer
  - Full coverage + agreeing evidence (sanity): something the model knows AND search confirms (MCQ #2 Excessive Data Exposure — already passed)

### 3. What does done look like?

Outcome A — Reasoning-override is **scoped to high-confidence priors**: ≤1/5 override at temp=0.0 on MCQ #1, AND the partial-coverage MCQ shows 0/5 override. → Document as known scoped property. Recommendation in handoff: "for high-prior MCQ scenarios, accept best-effort." No code change.

Outcome B — Reasoning-override is **temperature-sensitive**: monotonic decrease in override rate as temp drops, hits 0/5 at temp=0.0. → Recommendation in handoff: "for MCQ workflows, set per-task temperature=0.0 via model_proxy per-model defaults." Small `model_proxy.py` edit if user accepts.

Outcome C — Reasoning-override is **temperature-invariant** (constant ~30% across all temps): → Document as fundamental small-model property. Accept and move on. No code change.

Outcome D — Override rate INCREASES with lower temperature (sampling makes it worse): → Unexpected. Note as anomaly and stop here. Don't try to fix something we don't understand.

### 4. What's the rollback if it doesn't work?

The investigation itself doesn't change any code. Pure measurement. Rollback = throw away the data, write nothing, no edits to revert. Recommendations born from the data may produce a config change (per-model temperature default) — that's a single-line edit in `model_proxy.py:_resolve_route` per-model defaults block, easily reverted.

### Kill criterion

If during the investigation any of the following surface, stop the work and document:
- The substrate probe (direct Ollama, no Harvis) doesn't reproduce the override pattern at all → original Run 3 failure was Harvis-context-specific, scope needs rewriting before more measurement
- The temperature sweep shows non-monotonic or random results across 5x runs per setting → measurement noise is dominating signal, can't conclude anything from this experimental design
- The investigation discovers we'd be "patching prompts to nudge model reasoning" (e.g. adding "trust your search results over your prior beliefs" to the system prompt) → that's outside the agreed scope (no prompt nudges), kill and revisit later
- Any urge to ship a "result-weighting prompt" or "trust sources over reasoning" middleware patch mid-investigation → that's the implement-first-validate-later anti-pattern; kill and force a fresh scope

Estimate: 30 min substrate sweep + 30 min two additional MCQs + 30 min analysis = 90 min. NO implementation in this scope. Implementation, if warranted by Outcome B, gets its own separate scope after.

---

## Gate

Both scopes are now drafted. User reads, accepts, modifies, or rejects EACH independently. Neither implementation begins until the corresponding scope has explicit go.

If you want to modify a scope: name the specific question (1/2/3/4) and the change. Do not start implementing under "I'll figure out X in flight" — that's the failure mode the gate exists to prevent.
