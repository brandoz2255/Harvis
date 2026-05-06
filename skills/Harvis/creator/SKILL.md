---
name: creator
description: Scaffold + write + verify helper. Use when the user asks to "create a script", "write a script that…", "make me a Dockerfile/Flask app/FastAPI service/GitHub Actions workflow", or "scaffold a python CLI". Provides templates for python-cli, python-script, bash-script, dockerfile, flask-app, fastapi-app, github-action, gitignore-python. Every output flows through `verify` (py_compile / json.loads / bash -n / yaml.safe_load) so the agent reports `syntax_ok: true` only when the file actually parses. Pairs with the native `write` and `exec` tools — use creator when you want guaranteed-good outputs.
metadata:
  {
    "openclaw":
      {
        "emoji": "🛠️",
        "os": ["linux", "darwin"],
        "requires": { "bins": ["python3"] }
      }
  }
---

# 🛠️ creator

Standardize file creation: render-from-template, write, and auto-verify.
Same chokepoint pattern as the other skills — the agent doesn't claim
"created file X" until `creator.py` confirms `syntax_ok: true`.

## Hard rule: no claim without verification

If you tell the user "I created the script", that claim MUST be backed
by a JSON response from `creator.py` with `syntax_ok: true`. Don't
report success on a file that failed `verify`.

## Subcommands

```bash
# 1. Render a template to a path (best for common shapes)
python3 ~/.openclaw/workspace/skills/creator/creator.py scaffold python-cli \
    --out /home/user/.openclaw/workspace/session-X/my_tool.py \
    --vars name=my_tool description="My helper for X"

# 2. Write arbitrary content + auto-verify
python3 ~/.openclaw/workspace/skills/creator/creator.py write \
    /home/user/.openclaw/workspace/session-X/foo.py \
    --content "import sys
print('hi')"

# Or pipe via stdin (no shell-escape headaches):
cat <<'EOF' | python3 ~/.openclaw/workspace/skills/creator/creator.py write \
    /home/user/.openclaw/workspace/session-X/bar.py --stdin
import sys
print("hi")
EOF

# 3. Verify a file you wrote with the native `write` tool
python3 ~/.openclaw/workspace/skills/creator/creator.py verify path/to/file.py

# 4. List available templates
python3 ~/.openclaw/workspace/skills/creator/creator.py list-templates
```

## Returns JSON

Every command prints JSON. Example for `scaffold`:

```json
{
  "path": "/home/.../my_tool.py",
  "bytes": 518,
  "lines": 27,
  "syntax_ok": true,
  "errors": [],
  "kind": "python",
  "template": "python-cli",
  "vars": {"name": "my_tool", "description": "..."}
}
```

If `syntax_ok` is `false`, `errors` contains the parser's complaint
verbatim. The exit code is 0 (ok) / 1 (no input) / 2 (verify failed).

## Templates

| Template | Renders to | Variables |
|---|---|---|
| `python-cli` | argparse-based CLI script | `name`, `description` |
| `python-script` | minimal Python script | `name`, `description` |
| `bash-script` | bash with `set -euo pipefail` | `name`, `description` |
| `dockerfile` | minimal Dockerfile | `description`, `base` |
| `flask-app` | minimal Flask app w/ /health + /echo | `name`, `description` |
| `fastapi-app` | minimal FastAPI app | `name`, `description` |
| `github-action` | minimal CI workflow (push + PR) | `name`, `description` |
| `gitignore-python` | standard Python .gitignore | `description` |

Add new templates by dropping a file into `templates/` next to this
script. They're auto-discovered. Variables use `{{ varname }}` syntax
(no jinja dependency — simple string replacement).

## Verification by extension

| Extension | Check |
|---|---|
| `.py` | `python3 -m py_compile` |
| `.json` | `json.load` |
| `.sh` / `.bash` | `bash -n` |
| `.yaml` / `.yml` | `yaml.safe_load` (skipped silently if PyYAML missing) |
| (other) | byte sanity — flags null bytes in claimed text files |

## When to use vs the native `write` tool

| Case | Use |
|---|---|
| Need standardized scaffold (CLI, Flask, Dockerfile, etc.) | `creator scaffold <template>` |
| Want syntax-verified output before reporting "done" | `creator write` (or `creator verify` after a native `write`) |
| Quick one-liner / data file (txt, csv, log) | native `write` is fine |
| Modifying an existing file | native `edit` (creator only writes new content) |

## Anti-hallucination guidance for lightweight models

> You are running the creator skill. Every "I created the file" claim
> MUST be backed by a JSON response from `creator.py` showing
> `syntax_ok: true`. If `syntax_ok: false`, the file did not parse —
> report the error verbatim and either fix and re-write, or hand the
> failed content back to the user with the parser's complaint. Do NOT
> say "I wrote the script" without the verification stamp.
