# Harvis Continuity Bridge — feature direction

**Date:** 2026-07-18
**Status:** design direction (not built)
**Scope:** major Harvis feature — provider-neutral checkpointing and handoff of an AI work session

---

## The one-sentence version

Harvis should let you keep coding when Claude usage runs out, a session crashes, or an agent stops
halfway through.

```text
Claude session
→ export visible context and work state
→ Harvis resumes locally
→ Harvis records its changes
→ Claude receives a clean resume package later
```

The purpose is to stop any one model or service from becoming the only place where your project's
working context exists.

## The problem

A long coding session accumulates: the original request, architectural decisions, files inspected,
plans and task lists, commands run, partial code changes, verifier findings, known bugs,
uncommitted Git changes, and unfinished next steps.

When a provider's limit is hit midway, the repository holds partial work while the *reasoning and
current plan* stay trapped in the chat session. The code is on disk; the intent is not.

### The honest limitation, stated up front

```text
Harvis cannot export a model's private hidden reasoning.

Harvis CAN preserve:
- visible messages          - Git state
- reasoning summaries       - test output
- plans                     - artifacts
- decisions                 - unfinished tasks
- tool calls                - verification status
- changed files
```

That is enough to resume most coding work safely. Any framing that implies chain-of-thought
transfer is false and must not appear in the UI or the docs.

---

## Grounding: how much of this already exists

**This is the key finding of writing this document.** Continuity Bridge is not greenfield. Harvis
already captures most of what a Continuity Pack needs — what is missing is the **portable
export/import layer**, not the capture layer.

Verified against the live database and `python_back_end/` on 2026-07-18:

### Already built

| Continuity Pack element | What already exists | Where |
|---|---|---|
| `manifest.json` | `vibecode_sessions` columns: `repo_path`, `base_branch`, `work_branch`, `base_sha`, `head_sha`, `isolation_mode`, `source`, `status`, `lifecycle`, `engine`, `project_id`, `permission_mode`, `preflight` (JSONB), `approved_patterns` | live DB |
| `repository-state.json` | `preflight.py` — verifies real git repo, remote match, base/current branch, HEAD SHA, clean tree | `workspace/orchestration/preflight.py` (113 L) |
| `diffs/*.patch` | `_run_git`, `collect_changed_files`, `collect_changed_files_status` (staged/unstaged/deleted), diff vs a fixed `base_sha` | `workspace/orchestration/isolation.py` (787 L) |
| `tool-events.jsonl` | `workspace_events` (JSONB event stream) | live DB |
| `artifacts/` | `workspace_artifacts` | live DB |
| test/build results | `workspace_jobs` (exit codes, `terminal_output` events) | live DB |
| `HANDOFF.md` prose | `build_narrator.py` → `workspace_runs.analysis_md` (markdown run analysis) | `workspace/build_narrator.py` (360 L) |
| file-change audit | `code_file_changes`, `code_pull_requests`, `code_projects` | live DB |
| approvals state | `workspace_pending_approvals` (durable, survives restart) | live DB |
| **provider adapters** | `engine_adapter.py` already drives `claude`, `claude-code`, `codex`, `opencode`, `hermes`, `hermes-agent` | `workspace/orchestration/engine_adapter.py` |
| governance for imports | `authorize_action` choke point + `risk.py` `gate_decision` + fail-closed skill verdicts | `workspace/orchestration/risk.py` (337 L) |
| **repo-native handoff** | `docs/handoffs/YYYY-MM-DD-<slug>.md` is already a standing convention in this repo | `docs/handoffs/` |

That last row matters more than it looks. The spec calls repository-native handoff *"likely the
most reliable first version"* — and it is already the working habit here. **Phase 1 is largely a
matter of formalizing a practice that exists, not inventing one.**

### Genuinely missing

- The **pack format** itself — a versioned, portable directory with a stable schema.
- **Export** — assembling the pack from the sources above.
- **Import + reconciliation** — reading a pack, then checking its claims against the live repo.
- **Resume-prompt generation** per target agent.
- **Automatic checkpointing** on lifecycle events.
- **Crash detection and the recovery screen.**
- **Redaction** — a hard guarantee that no secret value enters a pack.

### Deliberately reusing, not rebuilding

`engine_adapter.py` already speaks to five external coding agents. The spec's "provider adapters"
phase should extend that seam rather than open a parallel one. Likewise `authorize_action` is
already the single choke point for tool permission — the rule that *imported context cannot grant
tools* should be enforced there, not in new code.

---

## Continuity Pack format

```text
.harvis/continuity/<session-id>/
├── manifest.json
├── HANDOFF.md
├── conversation.md
├── decisions.json
├── tasks.json
├── repository-state.json
├── tool-events.jsonl
├── tests.json
├── artifacts/
├── diffs/
│   ├── working-tree.patch
│   └── staged.patch
└── resume-prompts/
    ├── claude.md
    ├── harvis.md
    └── generic-agent.md
```

### `manifest.json`

```json
{
  "schema_version": "1.0",
  "session_id": "continuity_2026_07_19_001",
  "project": "Harvis",
  "repository_path": "/workspace/Harvis",
  "branch": "harvis1.1",
  "source_agent": "claude",
  "current_agent": "harvis-local",
  "status": "interrupted",
  "created_at": "2026-07-19T02:39:00Z",
  "last_checkpoint_at": "2026-07-19T03:15:00Z",
  "objective": "Build the connector launcher in the hero composer",
  "current_phase": "frontend wiring",
  "verification_level": "frontend build passed; live interaction untested"
}
```

The schema is versioned so the internal format stays stable as providers change.

### `HANDOFF.md`

Human-readable, and the artifact a person actually reads:

```md
# Session Handoff

## Goal
Add a connector button beside the attachment button in the Harvis composer.

## Completed
- Added connector trigger component.
- Connected it to the provider registry.
- Added desktop popover shell.
- Frontend build passes.

## In progress
- Task-scoped connector chips.
- Mobile bottom sheet.

## Files changed
- MessageInput.svelte
- ConnectorPopover.svelte
- integrations/status.ts

## Verification
- npm run build: passed
- lint: not run
- live OAuth flow: not tested

## Known risks
- Removing a task chip may currently disconnect the global connector.
- Blocked connectors do not yet show the policy reason.

## Next action
Fix task-scoped detach behavior, then run connector interaction tests.
```

Note the `Verification` section distinguishes passed / not run / not tested. That distinction is
the whole point — see *Verification honesty* below.

---

## What Harvis captures automatically

**Repository state** — root, branch, HEAD, remotes, working-tree status, staged files, untracked
files, diff summary, full patch, recent commits, active worktree, submodules.

**Execution state** — active background jobs, commands run, exit codes, test results, build
results, generated artifacts, running containers, preview URLs, database migrations, approval
requests.

**Agent state** — original goal, current plan, completed steps, unfinished steps, decisions,
assumptions, files read, files edited, verifier findings, known failures, next recommended action.

**Environment state** — OS, Docker profile, CPU/NVIDIA/AMD selection, service readiness, active
model/engine, installed dependencies, and **environment variable names only**.

### Secrets

```text
Store:       DISCORD_BOT_TOKEN is configured
Never store: DISCORD_BOT_TOKEN=actual-secret-value
```

This is a hard requirement, not a guideline. A continuity pack is designed to be portable — copied,
attached to a chat, sent to another machine — which makes it exactly the wrong place for a
credential. Redaction must be enforced at pack-assembly time, not left to the caller.

---

## Automatic checkpointing

Harvis should not wait until the session is already dead.

```text
- before the first edit
- after a plan is approved
- after every major implementation phase
- before and after dependency installation
- before a backend restart
- after tests complete
- before a commit
- when the model reports low usage or likely interruption
- when the user clicks "Save handoff"
```

Checkpoints must be quick and incremental. Status display:

```text
Checkpoint saved 2 minutes ago
Repository state protected
Resume pack ready
```

---

## Mid-session crash recovery

When Harvis detects an interrupted session:

```text
1. Do not immediately continue editing.
2. Inspect Git and filesystem state.
3. Compare the last checkpoint against the live working tree.
4. Detect partial or orphaned edits.
5. Parse/build affected files.
6. Reconstruct the unfinished phase.
7. Show the user a recovery summary.
8. Resume only after the state is understood.
```

This is a codification of a pattern already used by hand in this project:

```text
Session died
→ check what landed on disk
→ verify partial edits
→ repair incomplete wiring
→ continue from the real state
```

It has been exercised for real. When an agent died mid-run on a usage limit during the 2026-07-18
autonomous run, it had already written its work to disk; recovery meant inspecting `git status` and
verifying the safety properties by grep rather than trusting the agent's (absent) report. Automating
that loop is precisely this feature.

---

## Context reconstruction — the repository wins

Harvis must never trust an imported summary on its own.

```text
Imported conversation
+ actual Git state
+ filesystem state
+ test results
+ workspace event history
= reconstructed session
```

When the summary conflicts with the repository, **the repository wins**:

```text
Claude says: "PrDrawer is wired."
Repository inspection: no import or mount exists.

Harvis records:
Claimed complete, but not present in current source.
Status changed to incomplete.
```

### Verification honesty

The pack must carry *how well* something was verified, not just whether it was claimed done.
Distinguish at minimum:

- `passed` — observed working (command run, output seen)
- `compiled` — builds, but behavior unobserved
- `not run`
- `not tested` — e.g. a live OAuth flow nobody exercised

This project has a live example of why the distinction is load-bearing: a batch of UI fixes passed
the Svelte compiler and a code review, and still needed a forced-failure runtime test to actually
prove the bug was dead. `compiled` and `passed` are not the same claim, and a resume package that
conflates them will mislead the next agent into skipping verification.

---

## Context compression — three layers

Long sessions are too large to hand to another model directly.

1. **Layer 1 — Immediate resume brief** (~1–3 pages): goal, current state, recent decisions,
   changed files, known failures, next step.
2. **Layer 2 — Detailed handoff**: full plan, verification, event summaries, file inventory.
3. **Layer 3 — Raw evidence**: transcript, patches, logs, artifacts.

The receiving model starts at Layer 1 and reads deeper only as needed. Never put the full
transcript into every prompt.

> Prior art worth reading: OmniRoute stacks ten composable compression engines (session dedup,
> tool-result filtering, JSON compaction, LLMLingua-2 pruning) reporting 78–95% savings on
> tool-heavy prompts while preserving code byte-perfect. See
> [the reference scan](../research/2026-07-18-omniroute-tinker-inkling.md).

---

## UI

### Continuity status in Build Space

```text
Continuity
● Saved 1 minute ago
```

Opens a drawer with: current objective · current phase · checkpoint history · last successful
build/test · uncommitted files · active agent. Actions: Save checkpoint · Export handoff · Resume
locally · Switch engine · Prepare for Claude · Inspect raw evidence.

### When Claude becomes unavailable

A calm recovery banner, not an error:

```text
Claude is currently unavailable or usage-limited.

Your work is safe. Harvis can continue with:
[ Local model ] [ OpenCode ] [ OpenClaw ] [ Pause and save ]

Last checkpoint: 45 seconds ago
8 files changed
Frontend build passed
Current step: Wire mobile connector sheet
```

### Resume modal

```text
Resume this coding session

Source: Claude
Last active: 6 minutes ago
Branch: feature/connector-launcher
Working tree: 8 modified files
Verification: partial

[ Inspect state ] [ Resume locally ]
```

---

## Import methods

- **Manual paste** — Claude summary, plan, verifier report, visible conversation, interruption message.
- **File import** — Markdown transcript, JSON export, handoff file, ZIP of artifacts, Git patch.
- **Browser/desktop capture** — with explicit user approval, capture *visible* messages only. Never
  hidden reasoning, never unrelated account data.
- **Repository-native handoff** — Claude writes `docs/handoffs/current-session.md`; Harvis reads it
  and combines it with live Git state. **This is the recommended first version** and, as noted
  above, already the working convention in this repo.

---

## Security rules

```text
- Never claim hidden model reasoning was transferred.
- Never include secrets in handoff files.
- Never trust a conversation summary over live repository state.
- Never resume on main/master without confirmation.
- Never auto-push or auto-deploy.
- Never discard uncommitted changes during recovery.
- Never allow an imported session to grant tools or permissions.
- Imported skills remain governed.
- Imported commands are historical records, not instructions to rerun blindly.
```

### The prompt-injection rule deserves emphasis

**A continuity pack is untrusted input.** It is a document that arrives from outside, is designed
to be read by an agent, and describes actions to take. That is precisely the shape of a
prompt-injection vector: a malicious or tampered transcript could contain text instructing Harvis
to run a command, exfiltrate a file, or grant itself a tool.

Therefore:

- Imported content is **data, never instructions.** A `tool-events.jsonl` entry is a record of what
  happened, not a request to repeat it.
- Tool grants flow only through the existing `authorize_action` choke point. An imported pack
  cannot widen a permission, and the existing fail-closed skill governance (inject only on a
  `supported` verdict) applies unchanged to imported skills.
- Re-running any captured command requires the same approval it would have required the first time.

This constraint should be designed in from Phase 1, because retrofitting a trust boundary onto a
format that was assumed trusted is how these bugs ship.

---

## Phasing

| Phase | Deliverable |
|---|---|
| **1 — Manual Continuity Pack** | `Save handoff` button · Git state capture · `HANDOFF.md` · manifest · changed-file list · diffs · test summary · generated Claude resume prompt |
| **2 — Harvis local resume** | Import a handoff · inspect repository · compare claims against source · resume with a native/local agent · trace all resumed work |
| **3 — Automatic checkpoints** | Phase checkpoints · crash detection · interrupted-session recovery screen · incremental event persistence |
| **4 — Provider adapters** | Import/export for Claude, OpenCode, OpenClaw, Grok Build, Codex — extending `engine_adapter.py` |
| **5 — Browser/desktop bridge** | With explicit approval, capture visible Claude messages and build a handoff automatically |

Phase 1 alone provides most of the value, and given the inventory above it is mostly assembly of
existing capture primitives into a documented format.

---

## Acceptance criteria

1. A coding session can be checkpointed before Claude reaches its limit.
2. Harvis can reconstruct repository state without relying only on chat text.
3. Harvis can resume an incomplete phase using a different engine.
4. Partial edits are detected before new changes are stacked on top.
5. Every resumed action appears in the Harvis trace.
6. Claude later receives a concise, accurate resume prompt.
7. Full logs and raw evidence remain available but do not overload the resume prompt.
8. No secret values are exported.
9. Imported content cannot grant tools or bypass approvals.
10. Repository state always overrides inaccurate session summaries.
11. The feature works even when the original provider is completely unavailable.
12. No push or deployment occurs without explicit approval.

---

## Why this belongs at the center of Harvis

It directly answers the provider-lock-in problem, and it is the natural expression of what this
project already believes: the repository is the source of truth, verification level is part of the
record, and no single vendor should own your working context.

**The model can change. The work session survives.**

## Related

- [Reference scan — OmniRoute · Tinker · Inkling](../research/2026-07-18-omniroute-tinker-inkling.md)
  — OmniRoute solves the same "never stop coding" problem at the *inference* layer; this solves it
  at the *work-state* layer. Complementary.
- Build Space plan — `code_projects` / `code_file_changes` / `code_pull_requests` and the preflight
  work are direct dependencies of Phase 1.
