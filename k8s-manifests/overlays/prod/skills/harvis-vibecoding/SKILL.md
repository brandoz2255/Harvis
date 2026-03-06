# harvis-vibecoding skill

You are Harvis, a powerful AI coding agent. This skill teaches you exactly how to
use your tools to write, edit, and ship code correctly every time.

---

## Your Coding Tools (and how to use each one)

### 1. `read` — Read a file
Always read before you edit. Never guess at file contents.
```
read path/to/file.py
read path/to/file.py offset=50 limit=30   ← read lines 50–80 only
```
- If the file is large, use `offset` + `limit` to read just the section you need
- After reading, quote the exact text you see before using `edit`

### 2. `write` — Create or fully overwrite a file
Use for new files or complete rewrites only.
```
write path/to/newfile.py
<full file contents>
```
- Never use `write` to make a small change — use `edit` instead
- Always include the complete file contents, not just the changed part

### 3. `edit` — Make precise in-place edits (USE THIS FOR CHANGES)
This is your primary tool for modifying existing files.

**How it works**: You provide the exact text to find (`old_string`) and the exact
replacement (`new_string`). The tool does a literal string search — whitespace,
indentation, and newlines must match exactly.

**The golden rule**: Always `read` the exact lines first, copy them verbatim, then
use that as `old_string`. Never write `old_string` from memory.

```
Step 1: read the file or the specific section
  exec: grep -n "def my_function" python_back_end/main.py
  read: python_back_end/main.py offset=142 limit=10

Step 2: copy the exact text you see, paste as old_string
  edit python_back_end/main.py
  old_string:
    def my_function(x):
        return x
  new_string:
    def my_function(x: int) -> int:
        return x * 2
```

**Why edits fail**:
- `old_string` contains a typo or different whitespace than the file
- The file was already modified by a previous edit in this session
- You wrote the `old_string` from memory instead of copying from `read` output

**When edit fails**: Re-read the exact lines, copy the text, try again. Do not
give up after one failure — just read and retry with the correct text.

### 4. `apply_patch` — Patch using unified diff format (alternative to edit)
Use this when `edit` keeps failing on a complex multi-location change, or when
you want to make several edits across a file atomically.

```
apply_patch path/to/file.py
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -142,7 +142,7 @@
 def my_function(x):
-    return x
+    return x * 2
```

The `@@ -line,count +line,count @@` header tells the tool where to look.
Context lines (no `+`/`-` prefix) must also match exactly.

### 5. `exec` — Run shell commands
Use for: grep, git, running tests, installing packages, checking status.
```
exec: grep -n "def send_message" python_back_end/main.py
exec: git diff python_back_end/main.py
exec: cd /home/node/.openclaw/workspace/Harvis && git status
exec: python3 -m pytest python_back_end/tests/ -x -q
exec: pip show python-docx
```

**IMPORTANT**: Your workspace is at `/home/node/.openclaw/workspace/Harvis/`
All file paths are relative to that directory unless you use an absolute path.

### 6. `sessions_spawn` / `subagents` — Spawn parallel sub-agents
Use to parallelize independent work. Each sub-agent gets a task and runs concurrently.
```
subagents:
  - id: "scan-backend"
    message: "Read python_back_end/main.py and list all API routes"
  - id: "scan-frontend"
    message: "Read front_end/jfrontend/app/page.tsx and describe the UI structure"
```
Wait for results, then synthesize in the main agent.

**Sub-agent timeout**: Each sub-agent has 600s (10 min). Do not spawn sub-agents
for tasks that take less than 30s — just do those inline.

### 7. `memory_search` / `memory_get` — Search and read persistent memory
Use to look up things you've learned across sessions.
```
memory_search: "model proxy timeout"
memory_get: "project-notes"
```

---

## Coding Workflow — Do This Every Time

### Before touching any file:
1. `exec: find . -maxdepth 3 -type f -name "*.py" | head -30` — understand structure
2. `exec: grep -rn "keyword" python_back_end/ | head -20` — find where things live
3. `read` the specific file before editing it

### Making a code change:
1. Read the exact lines you'll change
2. Make the edit with `edit` using copied text as `old_string`
3. `read` the file again to verify the change looks right
4. Run tests or a quick sanity check with `exec`

### Committing changes:
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git add <specific files> && \
  git commit -m "fix: description of what you fixed

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
```

Always use conventional commits: `fix:`, `feat:`, `chore:`, `docs:`
Always include the co-author trailer for brandoz2255.

### Opening a PR:
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git push origin HEAD && \
  gh pr create \
    --title "fix: short description" \
    --body "## What\n- bullet of changes\n\n## Why\n- reason"
```

---

## Common Mistakes — Never Do These

| Wrong | Right |
|-------|-------|
| Edit from memory | Always `read` first, copy exact text |
| `write` to make a small change | Use `edit` for modifications |
| Spawn 5 sub-agents for tiny tasks | Do small tasks inline |
| Give up after one `edit` failure | Re-read the exact lines, retry |
| Commit everything with `git add .` | Stage specific files by name |
| Write long `old_string` from scratch | Copy from `read` output verbatim |

---

## Harvis Repo Structure (know this before scanning)

```
/home/node/.openclaw/workspace/Harvis/
├── python_back_end/          ← Python FastAPI backend
│   ├── main.py               ← All API routes registered here
│   ├── workspace/
│   │   ├── model_proxy.py    ← Kimi/NVIDIA NIM proxy (httpx timeouts)
│   │   └── openclaw_client.py
│   └── requirements.txt
├── front_end/jfrontend/      ← Next.js 14 frontend
│   ├── app/                  ← App router pages + API routes
│   ├── components/           ← React components
│   └── lib/                  ← Auth, DB utilities
├── k8s-manifests/
│   └── overlays/prod/
│       ├── openclaw.yaml     ← OpenClaw config (your pod config)
│       └── skills/           ← Skill SKILL.md files
└── scripts/                  ← CI/CD scripts
```

All changes go in PRs. Do NOT apply K8s manifests directly — the user merges and applies.
