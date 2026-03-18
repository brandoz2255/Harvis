---
name: harvis-vibecoding
description: >
  Coding agent skill. Activate for: writing code, editing files, fixing bugs,
  adding features, refactoring, running tests, opening PRs, reading the repo,
  vibe coding, any task that touches source files or the terminal.
metadata: {"openclaw": {"emoji": "💻"}}
---

# Harvis Vibe Coding Skill

You are a senior engineer. Read this whole skill before touching a single file.

---

## 0. Before You Do Anything — Memory + Scan First

```
memory_search: "harvis repo patterns"
memory_search: "python_back_end main.py"
```

If memory has relevant context, use it. Then scan the repo:
```bash
exec: find /home/node/.openclaw/workspace/Harvis -maxdepth 3 -type f -name "*.py" -o -name "*.ts" -o -name "*.tsx" | grep -v node_modules | grep -v __pycache__ | head -50
exec: grep -rn "target_function_or_keyword" /home/node/.openclaw/workspace/Harvis/python_back_end/ | head -20
```

Your workspace root: `/home/node/.openclaw/workspace/Harvis/`

---

## 1. `read` — Read files (always before editing)

```
read python_back_end/main.py
read python_back_end/main.py offset=140 limit=25    ← lines 140–165 only
```

- Use `offset`+`limit` for large files — don't read 500 lines when you need 20
- Read returns line numbers — copy the exact text INCLUDING indentation for `edit`

---

## 2. `write` — Create new files or full rewrites only

```
write python_back_end/new_module.py
<complete file content here>
```

Never use `write` to modify an existing file. Use `edit` instead.

---

## 3. `edit` — Modify existing files (THE MOST IMPORTANT TOOL)

Does a **literal exact string replace**. Whitespace, tabs, newlines must match exactly.

### Workflow — never skip step 1:
```
Step 1: Read the exact lines
  exec: grep -n "def target_function" python_back_end/main.py
  read: python_back_end/main.py offset=<line-from-grep> limit=15

Step 2: Copy text verbatim from read output → paste as old_string
  edit python_back_end/main.py
  old_string: <exact text from read, character for character>
  new_string: <your replacement>
```

### When edit fails ("Could not find the exact text"):
1. The file may have changed since you last read it — re-read
2. Your old_string has wrong whitespace — copy again from read output
3. Try a shorter, more unique old_string (just the key line + 1–2 lines of context)
4. Fall back to `apply_patch` (see below)

**Never write old_string from memory. Always copy from read output.**

---

## 4. `apply_patch` — Unified diff edits (fallback when edit keeps failing)

Use when edit fails repeatedly OR when making changes in multiple places at once.

```
apply_patch python_back_end/main.py
--- a/python_back_end/main.py
+++ b/python_back_end/main.py
@@ -142,6 +142,7 @@
 def my_function(x):
-    return x
+    return x * 2
+    # doubled for local kimi
```

Rules:
- Context lines (no `+`/`-`) must also match exactly
- The `@@ -old_line,count +new_line,count @@` numbers tell it where to look
- Include 2–3 context lines around each change for reliable matching

---

## 5. `exec` — Shell commands

```bash
# Find things
exec: grep -n "keyword" python_back_end/main.py
exec: grep -rn "function_name" python_back_end/ | head -20
exec: find . -name "*.py" -newer python_back_end/main.py | head -10

# Git
exec: cd /home/node/.openclaw/workspace/Harvis && git status
exec: cd /home/node/.openclaw/workspace/Harvis && git diff python_back_end/main.py
exec: cd /home/node/.openclaw/workspace/Harvis && git log --oneline -5

# Run/test
exec: cd /home/node/.openclaw/workspace/Harvis && python3 -m pytest python_back_end/tests/ -x -q
exec: cd /home/node/.openclaw/workspace/Harvis && python3 -c "import main; print('ok')"
exec: pip show python-docx

# GitHub
exec: cd /home/node/.openclaw/workspace/Harvis && gh pr list --state open
exec: cd /home/node/.openclaw/workspace/Harvis && gh pr create --title "fix: desc" --body "## What\n- change"
```

---

## 6. `process` — Background processes (long-running tasks)

Use when you need to run something and keep doing other work simultaneously:

```
# Start a background process
process action=start name="test-watcher" command="cd /home/node/.openclaw/workspace/Harvis && python3 -m pytest -x -q --tb=short -f"

# Check its output
process action=output name="test-watcher"

# Kill it when done
process action=stop name="test-watcher"

# List running processes
process action=list
```

Use cases: running a dev server while coding, watching test output, long installs.

---

## 7. `memory_search` + `memory_get` — Persistent knowledge

```
# Before coding anything, search for relevant context
memory_search: "python_back_end model proxy"
memory_search: "how to add a route to main.py"
memory_search: "harvis frontend api pattern"

# Pull specific memory file content
memory_get: "project-notes"
memory_get: "MEMORY.md"
```

After solving a tricky problem or discovering a pattern, save it:
```
memory_get: "MEMORY.md"   ← read first
# then write an updated version with your new knowledge
```

---

## 8. `sessions_spawn` — Spawn a sub-agent for a parallel task

```
sessions_spawn:
  agentId: "main"
  sessionKey: "harvis-task-scan-backend"
  message: "Read python_back_end/main.py and list all API routes defined with @app.get or @app.post"
```

- Each spawned agent has 600s (10 min)
- Don't spawn for tasks under 30s — do them inline
- After spawning, continue your own work; check results with `subagents`

---

## 9. `subagents` — Manage spawned sub-agents

```
# See all running sub-agents and their status
subagents action=list

# Read a sub-agent's output / steer it
subagents action=steer sessionKey="harvis-task-scan-backend" message="focus only on POST routes"

# Kill a sub-agent that's stuck
subagents action=kill sessionKey="harvis-task-scan-backend"
```

---

## 10. `image` — Vision (read screenshots, diagrams, UI mockups)

```
image path="/home/node/.openclaw/workspace/Harvis/screenshot.png"
```

Use when the user shares a screenshot of a UI bug, error, or design mockup.
Describe what you see, then write code to match it.

---

## Repo Structure

```
/home/node/.openclaw/workspace/Harvis/
├── python_back_end/
│   ├── main.py                    ← ALL routes registered here (@app.get/post)
│   ├── workspace/
│   │   ├── model_proxy.py         ← Kimi/NVIDIA NIM proxy (httpx, streaming)
│   │   └── openclaw_client.py     ← OpenClaw WebSocket client
│   ├── requirements.txt
│   └── research/                  ← Research agent code
├── front_end/jfrontend/
│   ├── app/                       ← Next.js 14 app router pages + API routes
│   ├── components/                ← React components (UI, chat, voice)
│   └── lib/                       ← Auth, DB, utilities
├── k8s-manifests/overlays/prod/
│   ├── openclaw.yaml              ← OpenClaw pod config (ConfigMaps, timeouts, skills)
│   └── skills/                    ← Skill SKILL.md source files
└── scripts/                       ← CI/CD: build-push.sh, deploy.sh
```

---

## Git Workflow

### Commit (always specific files, never git add .):
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git add python_back_end/specific_file.py front_end/jfrontend/components/Thing.tsx && \
  git commit -m "fix: what you fixed and why

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
```

Conventional commit prefixes: `fix:` `feat:` `chore:` `docs:` `refactor:`

### Open a PR:
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git push origin HEAD && \
  gh pr create \
    --title "fix: short description under 70 chars" \
    --body "## What changed
- bullet one
- bullet two

## Why
- reason"
```

**K8s manifest changes: open PR only. Never kubectl apply directly.**

---

## The Rules (never break these)

| Rule | Why |
|------|-----|
| Always `read` before `edit` | edit needs exact text — memory is wrong |
| Copy old_string from read output | Whitespace errors kill the match |
| Re-read and retry on edit failure | Don't give up after one miss |
| `process` for background tasks | Don't block the main agent on long waits |
| `memory_search` before starting | Prior patterns save time |
| Stage specific files in git | Never accidentally commit .env or secrets |
| PR only for K8s changes | User applies after review |
| Co-author trailer on every commit | brandoz2255 gets credit |
