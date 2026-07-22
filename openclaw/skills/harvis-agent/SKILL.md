---
name: harvis-agent
description: >
  Harvis task execution skill — routing table and execution procedure.
  Always loaded. Routes incoming tasks to the right skill.
metadata: {"openclaw": {"emoji": "🤖", "always": true}}
---

# Task Execution

## Skill Routing

Route tasks to the right skill — don't try to do everything yourself:

| Task type | Action |
|-----------|--------|
| Write/edit code, fix bugs, refactor | `read /skills/harvis-vibecoding/SKILL.md` |
| Research, docs, GitHub, Claude/Anthropic pages, light web lookup | `read /skills/harvis-research/SKILL.md` |
| Write a document, report, README | `read /skills/harvis-document/SKILL.md` |
| GitHub operations (PRs, commits) | `read /skills/harvis-github/SKILL.md` |
| Search the codebase / local docs | Use `local_rag` tool directly |
| General task | Use direct tools (exec, write, read) |

## How to Handle a Task

1. Identify task type → route to skill if applicable (table above)
2. Read relevant files for context (`read`)
3. Do the work using tools (`exec`, `write`, `edit`)
4. Verify the result (`exec` to run tests or check output)
5. Report what you actually did — be specific about what changed

## Parallel work (`sessions_spawn`)

When the user asks for multiple **independent** things at once (e.g. “search X and also check file Y”, several unrelated URLs, or a research pass plus a code pass), prefer spawning sub-agents with **`sessions_spawn`** (see `/skills/harvis-vibecoding/SKILL.md` §8) so work runs in parallel, then synthesize one answer for the user.

## Task Type Hints

- If the task mentions "fix", "bug", "error", "add feature", "refactor",
  "code", "implement" → vibecoding skill
- If the task mentions "research", "look up", "find out", "investigate",
  "what is" → research skill
- If the task mentions "write a doc", "report", "summary", "changelog",
  "README", "proposal" → document skill
- If the task mentions "commit", "push", "PR", "pull request", "branch",
  "merge" → github skill
- If the task is conversational or simple → respond directly, no skill needed
