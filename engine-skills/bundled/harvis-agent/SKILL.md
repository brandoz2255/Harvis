---
name: harvis-agent
description: >
  Harvis task execution skill — bundled mode. Routes incoming tasks to the
  right skill. Always loaded. Restricted capability set: no GitHub, no
  vibecoding, no planner, no coding delegation.
metadata: {"openclaw": {"emoji": "\ud83e\udd16", "always": true}}
---

# Task Execution — Bundled Mode

## Skill Routing

Route tasks to the right skill — don't try to do everything yourself:

| Task type | Action |
|-----------|--------|
| Research, docs, web lookup, fact-check | `read /skills-shared/harvis-research/SKILL.md` |
| Write a document, report, README, proposal | `read /skills-shared/harvis-document/SKILL.md` |
| ≥2 independent sub-tasks, parallel work | `read /skills-shared/harvis-swarm/SKILL.md` |
| Browser / screenshot automation | `read /skills-shared/harvis-browser/SKILL.md` |
| Analyze an image, photo, screenshot, scanned PDF | `read /skills-shared/harvis-image/SKILL.md` |
| Analyze a text file (.log, .txt, .csv, .json, source code) | `read /skills-shared/harvis-file/SKILL.md` |
| Search the codebase / local docs | Use `local_rag` tool directly |
| Write a standalone script or file | Use `write` tool in your scoped workspace |
| Run a command, test something | Use `exec` tool |
| General conversation | Respond directly, no skill needed |

## What's NOT available in bundled mode

If a user asks for any of these, redirect them:

| Request | Response |
|---------|----------|
| Open a PR, push to GitHub, clone a repo | "GitHub integration requires a self-hosted OpenClaw. Check the Harvis docs for BYO setup." |
| Edit the Harvis codebase, vibecoding | "Code editing on real projects requires BYO mode. I can write standalone scripts in your workspace though." |
| kubectl, deploy, infrastructure ops | "Infrastructure operations require BYO mode." |
| Interactive browser sessions | "Browser automation requires BYO mode." |

Be helpful about it — explain what BYO mode is and that they can set it up
on their own machine. Don't just say "no."

## How to Handle a Task

1. Identify task type -> route to skill if applicable (table above)
2. Read relevant files for context (`read`)
3. Do the work using tools (`exec`, `write`, `read`)
4. Verify the result (`exec` to check output)
5. Report what you actually did — be specific about what changed

## Attachment-first rule

If the task contains an `[Attached files from the user]` block, do this
before anything else:

1. Inspect the attachment names / MIME types in that block.
2. Read the matching skill immediately:
   - image/photo/screenshot/PDF image -> `/skills-shared/harvis-image/SKILL.md`
   - `.log`, `.txt`, `.csv`, `.json`, source file -> `/skills-shared/harvis-file/SKILL.md`
3. Use tools on the attachment.

Replies like `Copy that.`, `Standing by.`, `On it.`, or any
acknowledgment without tool use are invalid for attachment tasks.
If you cannot determine the answer confidently after tool use, say so
directly and briefly. Do not guess.

## Workspace Scope

`exec` and `write` share the root `/home/node/.openclaw/workspace/`.
Each task includes a `WORKSPACE DIRECTORY:` line with a per-session
sub-directory like `/home/node/.openclaw/workspace/session-<slug>/`.

- `write` expects RELATIVE paths rooted at the tool root, so pass
  `session-<slug>/<filename>`.
- `exec` / `python3` expect ABSOLUTE paths, so pass
  `/home/node/.openclaw/workspace/session-<slug>/<filename>`.
- Do NOT try to `cd` into `/home/node/workspaces/bundled/...`; that path
  is legacy scoping and the shell `cd` will fail there.

Reading files outside your session dir (like skill files at `/skills/`) is fine.

## Workspace Memory

Each Harvis launch includes `WORKSPACE MEMORY` containing recent Discord/chat
turns. Use it first for conversational follow-ups and user facts. The launch
also includes `Current OpenClaw callback/session key`; use that exact value
with `sessions_history` if you need OpenClaw chat history. Do not use the
filesystem slug (`session-...`) as a `sessions_history` key.

For memory questions like "what is my job", "what am I", "what did I just
say", or "do you understand what you just outputted", answer from
`WORKSPACE MEMORY`. Do not read `AGENTS.md`, `AGENT.md`, `USER.md`, or files
inside the workspace dir for those questions.

### Python + obfuscation sandbox

`python3 -c '...'` is BLOCKED by the sandbox when the code contains
`decode`, `base64`, `b64decode`, `exec`, `system`, or `eval`. If you see
`Approval required` or `Obfuscated command detected` in the exec result,
the command DID NOT RUN — rewrite it as:

1. `write` the code to `session-<slug>/job.py`
2. `exec` `python3 /home/node/.openclaw/workspace/session-<slug>/job.py`

For binary or unknown-encoding bytes, print via `.hex()` or
`sys.stdout.buffer.write(...)`; never blindly `.decode("utf-8")`.

## Task Type Hints

- "research", "look up", "find out", "what is" -> research skill
- "write a doc", "report", "summary", "changelog" -> document skill
- "make me a script", "write a function" -> write tool in workspace
- "run this", "test", "check" -> exec tool
- "compare X, Y, and Z", "check these 3 URLs", "for each of these" -> swarm skill
- "what's in this picture", "describe this image", "read this screenshot",
  "when was this photo taken", "what camera took this", "extract text from",
  URL ending in .jpg/.png/.heic, Discord CDN link -> image skill
- "analyze this log", "what's in this file", "find X in the attached",
  "hostname from auth.log", "top IPs", "count lines", ".log/.txt/.csv/.json
  attachment", CTF-style Q1/Q2/Q3 questions on a file -> file skill
- Conversational or simple -> respond directly, no skill needed
