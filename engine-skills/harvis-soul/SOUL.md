---
name: harvis-soul
description: >
  Skill path quick-reference. Always loaded. Provides exact skill file
  paths to prevent hallucination of wrong paths.
metadata: {"openclaw": {"emoji": "🫀", "always": true}}
---

# Skill Quick Reference

When you need to read a skill, use these exact paths:

| Skill | Exact path |
|-------|-----------|
| harvis-vibecoding | `/skills/harvis-vibecoding/SKILL.md` |
| harvis-github | `/skills/harvis-github/SKILL.md` |
| harvis-research | `/skills/harvis-research/SKILL.md` |
| harvis-document | `/skills/harvis-document/SKILL.md` |
| harvis-rag | `/skills/harvis-rag/SKILL.md` |
| harvis-agent | `/skills/harvis-agent/SKILL.md` |
| harvis-planner | `/skills/harvis-planner/harvis_planner.md` |

Skills live at `/skills/<name>/SKILL.md`.
There is NO `/app/skills/` path.
There is NO `github-operations` skill.

GitHub specifically: `read /skills/harvis-github/SKILL.md` and follow
every step. Credentials: `$GH_TOKEN`, `$GH_USER`, `$GH_EMAIL`.

local_rag searches the local vector DB only — NOT the web.

For **web** research (docs, GitHub, Claude/Anthropic sites, assignments): read
`/skills/harvis-research/SKILL.md` and use Harvis `/api/tools/search` and
`/api/tools/web-fetch` (Tier 2). Do not refuse for “no internet.”
