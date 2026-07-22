---
name: harvis-swarm
description: >
  Adaptive multi-agent orchestration via sessions_spawn. Use when a task
  splits into independent sub-tasks that can run in parallel, when a
  cheaper model is enough for parts of the work, or when you need the
  orchestrator pattern (plan → fan-out → synthesize).
metadata:
  openclaw:
    emoji: "\U0001f41d"
    always: false
---

# Harvis Swarm — adaptive sub-agent orchestration

**You can spawn as many sub-agents as the task actually needs.** There
is no hard cap you need to respect in your own head — the gateway has
defensive ceilings (see "Gateway limits" below) but those are not
guidance, they're safety rails. If a user asks you to compare 10
libraries, spawn 10 children. If they ask you to audit 30 files, split
them into a handful of batched children. Don't self-limit.

Spawn via `sessions_spawn` when it makes the user's outcome arrive
faster or better. Each sub-agent has its own context and token budget
though, so you don't gain anything by delegating work you could do in
two tool calls yourself.

## Decision rule

Spawn one or more sub-agents when **any** of these is true:

1. The task splits into **independent** sub-tasks that can run in
   parallel (≥2 things that don't depend on each other's results).
2. A part of the task would be cheaper or faster on a smaller model
   (`gemma4:e2b` for cheap extractions, leaving the main on `e4b`).
3. A sub-task needs **different context** — e.g. reading a 40-page
   doc that would blow your main context budget.
4. You want to isolate a risky or exploratory branch so a failure
   there doesn't contaminate the main conversation.

Do **not** spawn when:

- The task fits in ≤3 of your own tool calls. Just do it yourself.
- The next step depends on the previous one's output (sequential
  work doesn't parallelize).
- You'd spawn exactly 1 child for trivial delegation — that's just
  overhead. Delegate only when isolation is the point.
- The task is conversational or a direct lookup.
- **All the "sub-questions" would be answered by the same tool call
  on the same resource.** This is the most common mistake — "What
  are the dimensions AND camera make AND camera model AND date
  taken of this image?" is ONE `identify` call that returns all
  four fields. Do NOT spawn four sub-agents for four fields of one
  EXIF block. Same for "summarize these 5 sections of the same
  document" (one read, one reply) or "tell me author+title+date of
  this paper" (one metadata extraction).

### Rule of thumb

If all sub-questions share the **same input** and can be answered
from the **same output**, it's one task, not a swarm. Spawn only
when the sub-tasks have **different inputs** (different URLs,
different files, different repos) or **different operations**
(one searches, one runs tests, one writes).

### How many to spawn

As many as the task's natural decomposition calls for. Typical sizes:

| Task shape                                 | Typical spawn count |
|--------------------------------------------|---------------------|
| Compare/research N items                   | N children          |
| Audit M files, similar check on each       | Batch into groups of 3–8 files per child |
| Plan → N workers → synthesize              | 1 orchestrator + N workers |
| Map over a long list                       | Split evenly across 4–8 children |

If N is big (say 20+), prefer batching (8 children × 3 items) over
fanning-out one-per-item — you'll synthesize faster and the gateway
will queue fewer simultaneous runs.

## The tool

`sessions_spawn` params you care about:

| param               | when to set it                                                         |
|---------------------|------------------------------------------------------------------------|
| `task`              | **Required.** Full self-contained brief. The child sees nothing of your context by default. |
| `label`             | Short human tag ("research-fastapi", "scan-repo"). Shows in logs.      |
| `model`             | Override model per child. See "Model selection" below.                 |
| `runTimeoutSeconds` | Hard cap. 120-300s for small tasks, 600s for research, rare beyond.    |
| `thinking`          | Leave unset unless the child needs deeper reasoning than default.      |

The tool starts the child in the background and returns a run id
immediately. Your next step is usually `subagents` or `sessions_list`
to wait and collect — not to spawn more.

## Model selection (Harvis-local)

Pick the smallest model that can do the sub-task:

| Model                      | Use it for                                           |
|----------------------------|------------------------------------------------------|
| `harvis-proxy/gemma4:e2b`  | URL fetches, single-file reads, simple classify/extract, yes/no verdicts. Fast, cheap. |
| `harvis-proxy/gemma4:e4b`  | Default. Multi-step tool use, coding, synthesis.     |
| `harvis-proxy/qwen3.5-32k:latest` | Children that need long context (>8K tokens of input — big docs, many files). |
| `harvis-proxy/llama3.1:8b` | Fallback generalist if Gemma is struggling.          |

If you omit `model`, the child inherits the default sub-agent model
(`gemma4:e2b` in bundled mode) — fine for light lookups, usually
wrong for real synthesis. Be explicit.

## Patterns

### 1. Fan-out / gather (most common)

User asks "compare X, Y, Z". Spawn one child per item, wait, synthesize.

```
# 1. spawn (parallel)
sessions_spawn  task="Research library X: what it does, main API, 1 code sample, known pain points. Return JSON {summary, api, sample, pitfalls}." label="research-x" model="harvis-proxy/gemma4:e2b" runTimeoutSeconds=300
sessions_spawn  task="Same for Y..." label="research-y" model="harvis-proxy/gemma4:e2b" runTimeoutSeconds=300
sessions_spawn  task="Same for Z..." label="research-z" model="harvis-proxy/gemma4:e2b" runTimeoutSeconds=300

# 2. wait and collect announces (they arrive as system messages)
# 3. synthesize YOURSELF into one answer. Don't just paste the three JSONs.
```

### 2. Orchestrator (depth-2, when enabled)

Main spawns one depth-1 "orchestrator" that plans the sub-tasks itself
and spawns depth-2 workers. Use when:

- The decomposition itself is non-trivial (the main shouldn't waste
  context on it).
- You want the plan → fan-out → synthesize loop isolated from the
  user-facing conversation.

Requires `agents.defaults.subagents.maxSpawnDepth: 2` in `openclaw.json`.
Only the orchestrator (depth 1) can spawn; depth-2 workers cannot.

### 3. Specialist routing

One-off delegation when a sub-task needs a different model/skill:

- "Summarize this 40-page PDF" → spawn with `qwen3.5-32k:latest`.
- "Scan these 12 files for TODOs" → spawn with `gemma4:e2b` — cheap
  batch work.

A single delegation like this is often worth it even though it's only
one child — because the main agent avoids loading 40 pages into its
own context.

## Synthesis — your job after the children return

When the announces come back:

1. Quote or extract only the parts you'll actually use. Don't forward
   raw JSON to the user.
2. Call out disagreements between children explicitly. Two children
   saying different things is a **finding**, not noise.
3. If any child failed or timed out, say so in your final answer —
   don't silently drop it. Name the label and the symptom.
4. Then produce the one consolidated answer the user asked for.

## Gateway limits (ceilings, not guidance)

The gateway enforces these defensive caps. Treat them as "ask me why
if you're bumping into it", not as a budget:

- `maxSpawnDepth`: 3 — depth 0 is main, depth 1 is your direct
  children, depth 2 is an orchestrator's children, depth 3 is
  rare-but-allowed nesting. Leaves at depth 3 cannot spawn further.
- `maxChildrenPerAgent`: 12 — a single agent session can have up to
  12 active children at once.
- `maxConcurrent`: 8 — total live sub-agents (across all depths,
  globally). Queues beyond that.

If you genuinely need more than 12 parallel children, batch items
into fewer children (e.g. "scan files 1-5" per child instead of one
child per file). That's usually better anyway — smaller fan-out,
fewer announces to synthesize.

## Hardware reality check

On the local 8 GB VRAM Harvis box, running many `e4b`-class children
*at the same time* will partial-offload to CPU and slow everything
down. This is a throughput consideration, not a rule:

- If spawning 6+ children and results aren't latency-critical,
  override `model` to `harvis-proxy/gemma4:e2b` on the children that
  do simple extraction/classification. Keep the main on `e4b`.
- If one child needs long context (40-page doc), give it
  `harvis-proxy/qwen3.5-32k:latest` and let the others be e2b — the
  big-context child dominates VRAM anyway.
- For cloud/beefy hosts, just use the default `e4b` everywhere.

Pick the smallest model per child that can still do its sub-task.
That's the real "limit" — total aggregate VRAM, not a spawn count.

## Failure modes — how to recover

- **Child timed out**: check `subagents log <id>` for the last tool
  call. If it was stuck on a fetch, retry with a tighter brief. If it
  looped, lower `runTimeoutSeconds` next time and split the task more.
- **Child returned nothing useful**: its task was too vague. Rewrite
  it as a specific deliverable ("Return a JSON array of {file, line,
  symbol}"), not an open question.
- **Child violated scope**: rare but possible — include explicit
  "do not" clauses in the brief ("do not modify files", "do not
  commit").

## Propagating context to children (CRITICAL)

Sub-agents inherit **nothing** from your conversation. Not the user's
original message, not attachments, not prior tool results, not the
session key. If a child needs it, it must be **verbatim** in the
`task` string you pass to `sessions_spawn`.

The one that breaks people most: **if the parent task has an
`[Attached files from the user]` block (image URLs, file paths,
file_ids), copy that block verbatim into every child's `task`
string.** Otherwise children will say "please provide an image"
because they genuinely don't have it.

Example — correct spawn brief for a sub-task about an uploaded image:

```
task: """
[Attached files from the user]
1. Meta.jpg — image/jpeg — url=https://cdn.discordapp.com/attachments/.../Meta.jpg

[Task]
Download the image at the URL above, then run:
  identify -format '%[EXIF:Make]|%[EXIF:Model]' /tmp/img.jpg
Return only the two pipe-separated values.
"""
```

Other things to always include in a spawn brief when relevant:

- File paths the child must read (full absolute path).
- Session key from your task message, when the child needs to hit
  a backend API (`/api/tools/search`, `/api/tools/vision-query`, etc.).
- Any previously-fetched data the child would otherwise re-fetch.
- The child's expected output shape ("Return JSON with keys
  {x, y, z}" or "Return exactly one line: make|model").

## Rules

- **Spawn freely** when the task decomposes into parallel work.
  Don't ration sub-agents below what the user's task warrants.
- **Never** spawn when all sub-questions share the same input/output
  — collapse them into one tool call in the main agent instead.
- **Always** copy the `[Attached files…]` block into every child's
  `task` that needs the attachment. Every child. Every time.
- **Never** let children do destructive actions (commits, deletes,
  pushes) — keep those in the main agent so the user sees them.
- **Always** synthesize. The user expects one answer, not a wall of
  child announcements stitched together.
- **Always** name the children with a useful `label` — makes logs
  readable for the user when something goes wrong.
- Sub-agents inherit no memory from the main. If the child needs a
  file path, session key, or API token, put it in the `task` string.
- If you're about to spawn exactly 1 child with no isolation need,
  stop and do it yourself instead.
