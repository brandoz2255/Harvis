---
name: harvis-github
description: >
  Safe GitHub PR workflow for the Harvis bot account (harvisai-dulc3-cmd).
  Creates branches, runs tests, and submits pull requests via the GitHub API.
  NEVER pushes to main or master. NEVER force-pushes. Only works with the
  allowed public repo list.
metadata:
  openclaw:
    emoji: "🐙"
    always: false
    os: ["linux"]
    requires:
      bins: ["git", "curl"]
---

# Harvis GitHub Skill

You are the Harvis bot (`harvisai-dulc3-cmd`). You may interact with GitHub
to create branches and open pull requests — **nothing else**.

GitHub credentials are pre-configured in the environment.
**Never print `$GH_TOKEN`, `$GH_USER`, or `$GH_EMAIL` in any text response or tool output.**

---

## Allowed Repos

Only these repositories may receive pushes or PRs from this skill:

| Repo | Description |
|------|-------------|
| `dulc3/harvis-aidev` | Main Harvis project (public) |
| `brandoz2255/Harvis` | Brandoz's Harvis fork (public) |

Any other repo → refuse with: *"This repo is not on the Harvis allowed list."*

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

Follow this exact sequence for every GitHub task:

### Step 0 — Setup credentials (run once per session)

```bash
# Configure git identity from env
git config user.name "$GH_USER"
git config user.email "$GH_EMAIL"

# Wire the credential store so git push uses GH_TOKEN automatically.
# The token is read from env — it never appears in this command's output.
git config --global credential.helper store
printf 'https://%s:%s@github.com\n' "$GH_USER" "$GH_TOKEN" \
  > ~/.git-credentials
chmod 600 ~/.git-credentials
```

### Step 1 — Clone or pull the repo

```bash
# Clone (first time)
git clone https://github.com/dulc3/harvis-aidev.git
cd harvis-aidev

# OR update existing clone
cd harvis-aidev && git fetch origin && git checkout main && git pull origin main
```

### Step 2 — Create a branch

Branch name format: `harvis/<short-description>` (kebab-case, max 50 chars, no spaces).

```bash
BRANCH="harvis/$(echo 'short-description' | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-50)"
git checkout -b "$BRANCH"
```

### Step 3 — Make changes

Use `write` and `exec` tools to implement the required changes inside the workspace directory.

### Step 4 — Run tests (REQUIRED — do not skip)

```bash
# Frontend type check
cd front_end/newjfrontend && npm run type-check 2>&1 | tail -20

# Python syntax check
cd python_back_end && python -m py_compile workspace/openclaw_client.py workspace/workspace_router.py

# Any project-specific tests
# Add relevant test commands here based on what was changed
```

If tests fail: fix the issue, then re-run tests. Do not proceed to Step 5 until tests pass.

### Step 5 — Commit changes

```bash
git add -p   # stage only relevant files — never `git add -A` blindly
git commit -m "feat: <concise description of what was changed>

Co-authored-by: harvisai-dulc3-cmd <harvisai@users.noreply.github.com>"
```

### Step 6 — Push the branch

```bash
git push origin "$BRANCH"
```

Confirm output shows the branch was pushed, not main.

### Step 7 — Open a Pull Request via the Harvis backend proxy

PR creation goes through the Harvis backend at port 8000.
The backend enforces the repo allowlist and uses its own token — you do not
need to include `$GH_TOKEN` in this request at all.

```bash
# Build the PR payload
cat > /tmp/pr-payload.json <<EOF
{
  "repo": "dulc3/harvis-aidev",
  "title": "feat: <concise title>",
  "body": "## What changed\n\n<description>\n\n## Test plan\n\n- [ ] Type-check passes\n- [ ] Manual test: <describe>\n\n---\n🤖 Opened by Harvis AI (harvisai-dulc3-cmd)",
  "head": "$BRANCH",
  "base": "main",
  "draft": false
}
EOF

# POST to the backend proxy — auth via OPENCLAW_GATEWAY_TOKEN (already set in env)
curl -s -X POST \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  http://backend:8000/github/pulls \
  -d @/tmp/pr-payload.json | tee /tmp/pr-result.json

# Print the PR URL from the response
python3 -c "import json,sys; d=json.load(open('/tmp/pr-result.json')); print(d.get('pr_url','ERROR:',d))"

# Clean up
rm -f ~/.git-credentials /tmp/pr-payload.json /tmp/pr-result.json
```

The backend will:
- Reject PRs for repos not on the allowed list
- Reject PRs whose head branch is not `harvis/*`
- Reject PRs targeting anything other than `main`/`master`
- Log the PR creation with timestamp and metadata

---

## Creating a New Repository

Use this when the user explicitly asks you to create a new GitHub repo on their behalf.

**Always confirm with the user before creating** — repo creation is irreversible without manual deletion.

### Step — Create the repo via the Harvis backend proxy

```bash
cat > /tmp/repo-payload.json <<EOF
{
  "name": "my-new-repo",
  "description": "Short description of the project",
  "private": false,
  "auto_init": true
}
EOF

curl -s -X POST \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  http://backend:8000/github/repos \
  -d @/tmp/repo-payload.json | tee /tmp/repo-result.json

# Print the new repo URL
python3 -c "import json,sys; d=json.load(open('/tmp/repo-result.json')); print(d.get('repo_url','ERROR:', d))"
python3 -c "import json,sys; d=json.load(open('/tmp/repo-result.json')); print('Clone:', d.get('clone_url',''))"

rm -f /tmp/repo-payload.json /tmp/repo-result.json
```

**Rules for repo creation:**
- `name`: alphanumeric, hyphens, underscores, dots — max 100 chars, no spaces
- `private`: default `false` (public repo); set `true` only if user explicitly requests private
- `auto_init`: always `true` so the repo has an initial commit and is immediately cloneable
- After creation, the returned `full_name` (e.g. `dulc3/my-new-repo`) can be used as a target for the Standard PR Workflow in the same session

**Log the creation:**
```bash
echo "[harvis-github] $(date -u '+%Y-%m-%dT%H:%M:%SZ') ACTION: create_repo name=my-new-repo" \
  >> /home/node/workspaces/github-audit.log
```

---

## Security Checks

Before any git push, verify the target branch:

```bash
# MUST pass — refuse to push if this shows main or master
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
  echo "ERROR: Cannot push to $CURRENT_BRANCH. Create a feature branch first."
  exit 1
fi
echo "Safe to push: on branch $CURRENT_BRANCH"
```

---

## Logging

Log every git/GitHub action to the workspace log:

```bash
echo "[harvis-github] $(date -u '+%Y-%m-%dT%H:%M:%SZ') ACTION: git push origin $BRANCH" \
  >> /home/node/workspaces/github-audit.log
```

---

## What to Report Back

After a successful PR:
- Branch name pushed
- PR URL (from the API response `html_url`)
- Files changed (summarize, no raw diffs)
- Test results summary

Never include the token value in any response.
