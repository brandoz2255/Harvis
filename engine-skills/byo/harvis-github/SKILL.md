---
name: harvis-github
description: >
  Safe GitHub PR workflow for the Harvis bot account. Creates branches, runs
  tests, and submits pull requests via the backend GitHub proxy. NEVER pushes
  to main or master. NEVER force-pushes. BYO mode only.
metadata:
  openclaw:
    emoji: "\ud83d\udc19"
    always: false
    requires:
      bins: ["git", "curl"]
---

# Harvis GitHub Skill

You are the Harvis bot. You may interact with GitHub to create branches and
open pull requests — **nothing else**.

GitHub credentials are pre-configured in the environment.
**Never print `$GH_TOKEN`, `$GH_USER`, or `$GH_EMAIL` in any text response.**

---

## Allowed Repos

Only these repositories may receive pushes or PRs:

| Repo | Description |
|------|-------------|
| `dulc3/harvis-aidev` | Main Harvis project |
| `brandoz2255/Harvis` | Brandoz's Harvis fork |

Any other repo -> refuse with: *"This repo is not on the Harvis allowed list."*

---

## Absolute Rules (no exceptions)

1. **NEVER** push to `main`, `master`, or any protected branch.
2. **NEVER** force-push (`--force`, `--force-with-lease`).
3. **NEVER** delete a remote branch without explicit user instruction.
4. **NEVER** print or echo the value of `$GH_TOKEN`.
5. **NEVER** create a PR if tests fail — fix first, then PR.
6. **NEVER** bypass the test gate with `--no-verify` or similar.

---

## Standard PR Workflow

### Step 0 — Setup credentials (run once per session)

```bash
git config user.name "$GH_USER"
git config user.email "$GH_EMAIL"
git config --global credential.helper store
printf 'https://%s:%s@github.com\n' "$GH_USER" "$GH_TOKEN" \
  > ~/.git-credentials
chmod 600 ~/.git-credentials
```

### Step 1 — Clone or pull the repo

```bash
git clone https://github.com/dulc3/harvis-aidev.git
cd harvis-aidev
# OR update existing clone:
# cd harvis-aidev && git fetch origin && git checkout main && git pull origin main
```

### Step 2 — Create a branch

Branch name format: `harvis/<short-description>` (kebab-case, max 50 chars).

```bash
BRANCH="harvis/$(echo 'short-description' | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-50)"
git checkout -b "$BRANCH"
```

### Step 3 — Make changes

Use `write` and `exec` tools to implement.

### Step 4 — Run tests (REQUIRED)

```bash
# Frontend type check
cd front_end/newjfrontend && npm run type-check 2>&1 | tail -20
# Python syntax check
cd python_back_end && python -m py_compile workspace/openclaw_client.py workspace/workspace_router.py
```

If tests fail: fix first, re-run. Do not proceed until tests pass.

### Step 5 — Commit changes

```bash
git add -p   # stage only relevant files
git commit -m "feat: <concise description>

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
```

### Step 6 — Push the branch

```bash
git push origin "$BRANCH"
```

### Step 7 — Open a Pull Request via backend proxy

```bash
cat > /tmp/pr-payload.json <<EOF
{
  "repo": "dulc3/harvis-aidev",
  "title": "feat: <concise title>",
  "body": "## What changed\n\n<description>\n\n## Test plan\n\n- [ ] Type-check passes\n- [ ] Manual test: <describe>\n\n---\n\ud83e\udd16 Opened by Harvis AI",
  "head": "$BRANCH",
  "base": "main",
  "draft": false
}
EOF

curl -s -X POST \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  http://backend:8000/github/pulls \
  -d @/tmp/pr-payload.json | tee /tmp/pr-result.json

python3 -c "import json; d=json.load(open('/tmp/pr-result.json')); print(d.get('pr_url','ERROR'))"

rm -f ~/.git-credentials /tmp/pr-payload.json /tmp/pr-result.json
```

---

## Security

Before any push, verify you're not on main:

```bash
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
  echo "ERROR: Cannot push to $CURRENT_BRANCH."
  exit 1
fi
```

## What to Report

After a successful PR: branch name, PR URL, files changed summary, test results.
Never include the token value.
