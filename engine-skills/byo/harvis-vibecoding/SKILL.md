---
name: harvis-vibecoding
description: >
  Coding agent skill. Activate for: writing code, editing files, fixing bugs,
  adding features, refactoring, running tests, reading the repo. BYO only.
metadata: {"openclaw": {"emoji": "\ud83d\udcbb"}}
---

# Harvis Vibe Coding Skill

You are a senior engineer. Read this whole skill before touching a single file.

---

## 0. Before You Do Anything — Scan First

Scan the repo to understand what you're working with:
```bash
exec: find /home/node/projects -maxdepth 4 -type f -name "*.py" -o -name "*.ts" -o -name "*.tsx" | grep -v node_modules | grep -v __pycache__ | head -50
exec: grep -rn "target_function_or_keyword" /home/node/projects/ | head -20
```

Project directories: `/home/node/projects/{owner}/{repo}/`
Workspace root: `/home/node/.openclaw/workspace/`

---

## 1. `read` — Read files (always before editing)

```
read /home/node/projects/owner/repo/path/to/file.py
read /home/node/projects/owner/repo/path/to/file.py offset=140 limit=25
```

- Use `offset`+`limit` for large files
- Read returns line numbers — copy the exact text for `edit`

---

## 2. `write` — Create new files or full rewrites only

```
write /home/node/projects/owner/repo/new_module.py
<complete file content here>
```

Never use `write` to modify an existing file. Use `edit` instead.

---

## 3. `edit` — Modify existing files (THE MOST IMPORTANT TOOL)

Does a **literal exact string replace**. Whitespace must match exactly.

### Workflow — never skip step 1:
```
Step 1: Read the exact lines
  exec: grep -n "def target_function" file.py
  read: file.py offset=<line> limit=15

Step 2: Copy text verbatim from read output -> paste as old_string
  edit file.py
  old_string: <exact text from read>
  new_string: <your replacement>
```

### When edit fails:
1. Re-read the file — it may have changed
2. Copy old_string again from read output
3. Try a shorter, more unique old_string
4. Fall back to `apply_patch`

**Never write old_string from memory. Always copy from read output.**

---

## 4. `apply_patch` — Fallback when edit keeps failing

```
apply_patch file.py
--- a/file.py
+++ b/file.py
@@ -142,6 +142,7 @@
 def my_function(x):
-    return x
+    return x * 2
```

Include 2-3 context lines around each change.

---

## 5. `exec` — Shell commands

```bash
exec: grep -rn "function_name" python_back_end/ | head -20
exec: cd /home/node/projects/owner/repo && git status
exec: cd /home/node/projects/owner/repo && python3 -m pytest tests/ -x -q
```

---

## 6. `process` — Background processes

```
process action=start name="test-watcher" command="python3 -m pytest -x -q -f"
process action=output name="test-watcher"
process action=stop name="test-watcher"
```

---

## Git Workflow

### Commit (always specific files):
```bash
exec: cd /home/node/projects/owner/repo && \
  git add specific_file.py && \
  git commit -m "fix: what you fixed and why

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
```

Conventional commit prefixes: `fix:` `feat:` `chore:` `docs:` `refactor:`

---

## The Rules (never break these)

| Rule | Why |
|------|-----|
| Always `read` before `edit` | edit needs exact text — memory is wrong |
| Copy old_string from read output | Whitespace errors kill the match |
| Re-read and retry on edit failure | Don't give up after one miss |
| `process` for background tasks | Don't block on long waits |
| Stage specific files in git | Never accidentally commit .env or secrets |
| PR only for K8s changes | User applies after review |
| Co-author trailer on every commit | brandoz2255 gets credit |
