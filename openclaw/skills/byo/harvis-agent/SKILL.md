---
name: harvis-agent
description: >
  Harvis task execution skill — BYO mode. Full capability routing table.
  Always loaded. Routes incoming tasks to the right skill including GitHub,
  vibecoding, planner, and coding delegation.
metadata: {"openclaw": {"emoji": "\ud83e\udd16", "always": true}}
---

# Task Execution — BYO Mode

## Skill Routing

Route tasks to the right skill — don't try to do everything yourself:

| Task type | Action |
|-----------|--------|
| Write/edit code, fix bugs, refactor | `read /skills/harvis-vibecoding/SKILL.md` |
| Coding via OpenCode (Kimi K2.5) | `read /skills/harvis-coding/SKILL.md` |
| GitHub PRs, commits, repo operations | `read /skills/harvis-github/SKILL.md` |
| Research, docs, web lookup, fact-check | `read /skills/harvis-research/SKILL.md` |
| Write a document, report, README | `read /skills/harvis-document/SKILL.md` |
| Plan multi-step web app tasks | `read /skills/harvis-planner/harvis_planner.md` |
| Interactive browser automation | `read /skills/harvis-browser/SKILL.md` |
| Search the codebase / local docs | Use `local_rag` tool directly |
| General conversation | Respond directly, no skill needed |

## How to Handle a Task

1. Identify task type -> route to skill if applicable (table above)
2. Read relevant files for context (`read`)
3. Do the work using tools (`exec`, `write`, `read`, `edit`)
4. Verify the result (`exec` to run tests or check output)
5. Report what you actually did — be specific about what changed

## Parallel work (`sessions_spawn`)

When the user asks for multiple **independent** things at once (e.g.
"search X and also check file Y", several unrelated URLs, or a research
pass plus a code pass), prefer spawning sub-agents so work runs in
parallel, then synthesize one answer for the user.

## Project Files

User projects may be cloned to `/home/node/projects/{owner}/{repo}/`.
The Harvis workspace root is `/home/node/.openclaw/workspace/`.

## Task Type Hints

- "fix", "bug", "error", "add feature", "refactor", "code", "implement"
  -> vibecoding skill
- "research", "look up", "find out", "investigate", "what is"
  -> research skill
- "write a doc", "report", "summary", "changelog", "README", "proposal"
  -> document skill
- "commit", "push", "PR", "pull request", "branch", "merge"
  -> github skill
- "plan", "architect", "design", multi-step web app task
  -> planner skill
- "open", "browse", "screenshot", URL in message
  -> browser skill
- Conversational or simple -> respond directly, no skill needed
