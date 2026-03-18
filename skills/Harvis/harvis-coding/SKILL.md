---
name: harvis-coding
description: >
  Coding tasks delegated to OpenCode. OpenCode uses Kimi K2.5 internally and returns
  compact JSON summaries (not raw terminal output) - saving 5-10x tokens per task.
read_when:
  - User asks for a coding task, bug fix, feature, or code review
  - Working on multi-file changes or architectural refactors
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

If working on the same codebase across multiple calls, pass `session_id` from
the previous result to continue the same OpenCode session:

```
opencode({
  prompt: "Continue working on the same task...",
  session_id: "abc123-from-previous-result"
})
```

## Example

User: "Create a new API endpoint for user authentication"

You:
```
opencode({
  prompt: "Create a new API endpoint for user authentication in python_back_end/main.py. Add POST /api/auth/login that accepts email/password, validates against the database, and returns a JWT token. Include proper error handling for invalid credentials.",
})
```

Then read the JSON result and report:
- "Created POST /api/auth/login endpoint in main.py with JWT authentication"
- Files changed: ["python_back_end/main.py"]
- Tests passed: true/false

## Why OpenCode?

| Before (raw bash) | After (OpenCode tool) |
|-------------------|----------------------|
| 500-2000 tokens/step | 50-100 tokens/step |
| Full terminal output in context | Compact JSON only |

OpenCode is already configured with:
- Model: Kimi K2.5
- Agent: harvis-coder (compact output mode)
- Server: localhost:4096 (in same pod)
