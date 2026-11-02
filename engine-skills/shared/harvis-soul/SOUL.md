---
name: harvis-soul
description: >
  Skill path quick-reference and tool truth. Always loaded. Provides exact
  skill file paths to prevent hallucination of wrong paths. Defines what
  tools actually exist.
metadata: {"openclaw": {"emoji": "\ud83e\udeb4", "always": true}}
---

# Skill Quick Reference

When you need to read a skill, use these exact paths:

| Skill | Exact path |
|-------|-----------|
| harvis-agent | `/skills/harvis-agent/SKILL.md` |
| harvis-research | `/skills/harvis-research/SKILL.md` |
| harvis-document | `/skills/harvis-document/SKILL.md` |
| harvis-rag | `/skills/harvis-rag/SKILL.md` |
| harvis-browser | `/skills/harvis-browser/SKILL.md` |
| harvis-vibecoding | `/skills/harvis-vibecoding/SKILL.md` |
| harvis-github | `/skills/harvis-github/SKILL.md` |
| harvis-planner | `/skills/harvis-planner/harvis_planner.md` |
| harvis-coding | `/skills/harvis-coding/SKILL.md` |

Skills live at `/skills/<name>/SKILL.md`.
There is NO `/app/skills/` path.
There is NO `github-operations` skill.

**Not all skills are available in all modes.** If you try to `read` a
skill file and get "file not found", that skill is not available in your
current configuration. Tell the user what you can do instead.

## What Tools Actually Exist

These are the ONLY tools you have. Do not invent others.

| Tool | What it does |
|------|-------------|
| `exec` | Run shell commands — bash, python, git, curl, etc. |
| `write` | Write or overwrite a file |
| `read` | Read a file |
| `edit` | String-replace on an existing file |
| `apply_patch` | Unified diff edit |
| `local_rag` | Search the local vector DB (code + docs — NOT the web) |
| `image` | Understand screenshots and images |

### Things that are NOT direct tools

| What you might think exists | What to actually do |
|----------------------------|---------------------|
| `web_fetch` | Use `harvis-research` skill OR `exec curl` through the backend proxy |
| Direct GitHub API POST | Use `harvis-github` skill (BYO only) — it uses `exec curl` to `http://backend:8000/github/pulls` |

## Before saying "I don't know" — search first

**This is mandatory.** Before telling a user you don't know something:

1. Search the code corpus: use `local_rag` with context_type "code"
2. Search the docs corpus: use `local_rag` with context_type "docs"
3. Only if **both** return no results or all scores are below 0.4 should you say you don't know.

## Security (never break these)

- No outbound internet directly. All external requests go through the
  Harvis backend proxy at `http://backend:8000/api/tools/*`
- Never print `$GH_TOKEN`, `$OPENCLAW_GATEWAY_TOKEN`, or any secret.
- Never run `rm -rf /` or any destructive filesystem command.
