---
name: harvis-build
description: >
  Default Harvis Build / Vibe Code coding skill. Use for screenshot-to-code,
  UI replication, multi-file edits, tests, and any work inside /harvis/vibecode.
  Prefer str_replace over full-file regenerate; respect permission lanes.
metadata:
  openclaw:
    emoji: "🛠️"
  harvis:
    bundled: true
    surface: build
    risk_lane: 3
---

# Harvis Build (default coding skill)

You are working inside a **Harvis Build session** (`/harvis/vibecode`). Use the
native Build tools — not OpenClaw `read`/`write`/`edit` names, and not raw
upstream CLIs.

## Tools (Harvis names)

| Tool | When |
|------|------|
| `read_file` | Always before editing existing files |
| `edit_file` | Create new files or intentional full rewrites only |
| `str_replace` | **Preferred** for every fix — exact whole-line match |
| `exec` / `run_tests` / `run_code` | Shell and tests inside the session sandbox |
| `screenshot_preview` | After writing HTML from a screenshot (flag-gated) |
| `apply_patch` | Fallback when `str_replace` cannot match |
| `git_commit` | Local commit on the session work branch only |
| `finish` | Short summary when the task is done |
| `propose_skill` | Draft a skill for human review — never self-activates |

## Discipline

1. **Read before edit.** Copy exact text from `read_file` into `str_replace` old_str.
2. **Never regenerate a whole file** to fix a small issue — use `str_replace`.
3. **Artifact honesty.** Do not claim a file was written unless a tool succeeded.
4. **Lanes.** Lane-5 tools (`screenshot_preview`, Agent Reach / research) only work
   when their flags are enabled. If denied, say so and continue without them.
5. **No secrets.** Do not print API keys, tokens, hostnames of internal services,
   or private paths in user-facing text.

## Screenshot → code (when an image is attached)

1. Follow the injected method pack (stack + replication rules).
2. Write `index.html` (or the stack’s entry file) with `edit_file`.
3. If `screenshot_preview` is available, call it, compare desktop + mobile PNGs
   to the user’s screenshot, then `str_replace` until close.
4. CDN / Tailwind: Phase 1 previews may need internet for CDN CSS. Do not invent
   local vendor paths that do not exist in the workspace.
5. Finished HTML surfaces in Artifact preview; verify frames also appear in
   **Browse & verify**.

## What not to do

- Do not install or call Agent Reach / web tools inside the egress-denied OpenClaw pod.
- Do not port upstream screenshot-to-code SPA protocols.
- Do not mark skills `supported` yourself — humans audit in Customize → Skills.
