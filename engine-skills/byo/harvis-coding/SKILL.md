---
name: harvis-coding
description: >
  Coding tasks delegated to OpenCode. OpenCode uses Kimi K2.5 internally and
  returns compact JSON summaries — saving 5-10x tokens per task. BYO only.
metadata:
  openclaw:
    emoji: "\u2699\ufe0f"
---

# Harvis Coding Skill (OpenCode-Powered)

**All coding tasks are delegated to OpenCode** which runs Kimi K2.5 and returns
compact JSON summaries instead of raw terminal output. This saves 5-10x tokens.

## The Tool: opencode

Use the `opencode` tool for ALL coding tasks:

```
opencode({
  prompt: "Your coding task here. Be specific: what files, goal, constraints.",
  session_id: "optional - from previous call to continue same session"
})
```

## Workflow

1. **Delegate to OpenCode** — Call `opencode` with a specific prompt
2. **Read the result** — You'll get compact JSON with:
   - `files_changed`: list of files modified
   - `commands_run`: list of commands executed
   - `tests_passed`: boolean
   - `summary`: one sentence summary
   - `status`: "ok" | "error" | "needs_review"
3. **Report to user** — Summarize what was done based on the JSON

## Continuing a Session

Pass `session_id` from the previous result to continue:

```
opencode({
  prompt: "Continue working on the same task...",
  session_id: "abc123-from-previous-result"
})
```

## Example

User: "Create a new API endpoint for user authentication"

```
opencode({
  prompt: "Create POST /api/auth/login in python_back_end/main.py that accepts email/password, validates against the database, and returns a JWT token. Include proper error handling.",
})
```

Then read the JSON result and report:
- "Created POST /api/auth/login endpoint in main.py with JWT auth"
- Files changed: ["python_back_end/main.py"]
- Tests passed: true/false

## Why OpenCode?

| Before (raw bash) | After (OpenCode tool) |
|-------------------|----------------------|
| 500-2000 tokens/step | 50-100 tokens/step |
| Full terminal output in context | Compact JSON only |

OpenCode is configured with Kimi K2.5 and compact output mode.
