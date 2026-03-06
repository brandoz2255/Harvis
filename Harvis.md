# Harvis.md — Tasks for Harvis to Fix

This file is the task queue for Harvis (OpenClaw agent) to execute autonomously.
Each task has a clear goal, acceptance criteria, and files to touch.
Work through these in order. Open a PR for each one co-authored by brandoz2255.

---

## BEFORE YOU START ANYTHING — Scan the Repo First

**Do this before touching a single file.**

You only have access to two parts of this repo:
1. `k8s-manifests/` — all Kubernetes manifests, overlays, ConfigMaps, secrets, RBAC
2. The Harvis source code — `python_back_end/`, `front_end/`, `rest_api/`, `scripts/`

You do **NOT** have access to OpenClaw's source code. `openclaw/openclaw/` is a
vendored binary/image — treat it as a black box. You cannot modify its Dockerfile,
its internal packages, or its Node.js source. The only way to influence the OpenClaw
pod's environment is through the K8s manifest (init containers, volume mounts, ConfigMaps).

### Scan steps (run these first, read the output before proceeding)

```bash
# 1. Understand the overall repo layout
find . -maxdepth 2 -type d | sort

# 2. See every k8s manifest file you have to work with
find k8s-manifests/ -type f | sort

# 3. Read the current openclaw overlay — this is your main file for OpenClaw changes
cat k8s-manifests/overlays/prod/openclaw.yaml

# 4. Read the backend requirements — for Harvis-side Python changes
cat python_back_end/requirements.txt

# 5. Check what scripts exist for CI
ls scripts/

# 6. Check what skills are already mounted
find k8s-manifests/ -name "SKILL.md" | sort
```

Read and understand all of the above before writing any code or applying any manifest.

---

## Task 1 — Fix: `create_docx` fails because `python-docx` is not in the OpenClaw pod

**Priority**: HIGH — Research agent and Document agent are broken until this is fixed.

### Why This Is Tricky

You **cannot** modify OpenClaw's Dockerfile or source code — it's a pre-built image
(`dulc3/openclaw:latest`). The only way to add Python packages to the OpenClaw pod
is with a **Kubernetes init container** that installs the package before OpenClaw starts,
using a shared `emptyDir` volume.

### What Harvis Should Do

#### Step 1 — Verify the problem

```bash
# Check if python-docx is missing from the OpenClaw pod
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- pip show python-docx 2>&1 || echo "pip not found"
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- python3 -c "import docx; print('ok')" 2>&1

# Also check the backend pod (in case create_docx is handled there instead)
kubectl -n harvis exec deployment/harvis-ai-merged-backend -- pip show python-docx 2>&1
```

Read the output. Figure out which pod is actually missing the package.

#### Step 2a — If it's the OpenClaw pod (most likely)

Since you can't touch OpenClaw's image, add an **init container** in
`k8s-manifests/overlays/prod/openclaw.yaml` under the OpenClaw Deployment:

```yaml
initContainers:
  - name: install-python-docx
    image: python:3.11-slim
    command:
      - sh
      - -c
      - |
        pip install --target /python-extra python-docx
    volumeMounts:
      - name: python-extra
        mountPath: /python-extra
```

Add a shared volume between the init container and the main openclaw container:
```yaml
volumes:
  - name: python-extra
    emptyDir: {}
```

Mount it in the main openclaw container so Python can find the package:
```yaml
volumeMounts:
  - name: python-extra
    mountPath: /python-extra
env:
  - name: PYTHONPATH
    value: "/python-extra"
```

After editing `k8s-manifests/overlays/prod/openclaw.yaml`, commit and open a PR.
Do NOT apply to the cluster directly — the user will apply after merging.

#### Step 2b — If it's the Harvis backend pod

Add to `python_back_end/requirements.txt`:
```
python-docx
```

Commit and open a PR. The CI pipeline will pick it up on next build.

#### Step 3 — Verify after the user applies

These verification commands are for AFTER the user merges and applies:
```bash
# Confirm init container ran successfully
kubectl -n ai-agents describe pod -l app=harvis-ai-openclaw | grep -A5 "Init Containers"

# Confirm python-docx is importable
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- \
  python3 -c "import sys; sys.path.insert(0,'/python-extra'); import docx; print('python-docx OK')"
```

### Where to Look in the Repo
- `k8s-manifests/overlays/prod/openclaw.yaml` — **the only file you edit for this task**
- `python_back_end/requirements.txt` — only if the bug is in the backend pod instead

### Acceptance Criteria
- Init container installs `python-docx` into `/python-extra` on pod start
- `import docx` succeeds inside the openclaw container
- `create_docx` tool call produces a `.docx` file without error
- PR opened, co-authored by brandoz2255

---

## Task 2 — Discord Kubectl Access (Harvis-only, read + CI scripts)

**Priority**: HIGH — Enables remote cluster monitoring from Discord without terminal access.

### Goal
When the user DMs Harvis on Discord, Harvis should be able to answer cluster health
questions by running `kubectl` commands and returning summarized output. After a PR
is merged (or the user says "run CI"), Harvis can trigger the CI pipeline scripts.

### Repo Scan Before Starting

```bash
# Find every file related to openclaw config/skills
find k8s-manifests/ -name "*.yaml" | xargs grep -l "skill\|SKILL" 2>/dev/null

# Find existing skills already mounted in the openclaw deployment
grep -n "skill" k8s-manifests/overlays/prod/openclaw.yaml

# Find existing RBAC for openclaw
find k8s-manifests/ -name "*rbac*" -o -name "*role*" | sort

# Find CI scripts
ls scripts/
cat scripts/build-push.sh 2>/dev/null || echo "not found"
cat scripts/deploy.sh 2>/dev/null || echo "not found"

# Check if kubectl is already in the openclaw image
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- which kubectl 2>&1
```

Read all of this before writing anything.

### What Harvis Should Do

#### Step 1 — Create read-only RBAC for the OpenClaw pod

Create `k8s-manifests/services/harvis-kubectl-rbac.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: harvis-kubectl-reader
  namespace: ai-agents
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: harvis-kubectl-readonly
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "nodes", "events", "namespaces", "endpoints"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: harvis-kubectl-readonly-binding
subjects:
  - kind: ServiceAccount
    name: harvis-kubectl-reader
    namespace: ai-agents
roleRef:
  kind: ClusterRole
  name: harvis-kubectl-readonly
  apiGroup: rbac.authorization.k8s.io
```

#### Step 2 — Check if kubectl binary exists in the OpenClaw pod

```bash
kubectl -n ai-agents exec deployment/harvis-ai-openclaw -- which kubectl 2>&1
```

If `kubectl` is **not present**: add a second init container to download it:

```yaml
initContainers:
  - name: install-kubectl
    image: bitnami/kubectl:latest
    command:
      - sh
      - -c
      - cp /opt/bitnami/kubectl/bin/kubectl /tools/kubectl && chmod +x /tools/kubectl
    volumeMounts:
      - name: tools
        mountPath: /tools
```

Add to volumes: `- name: tools\n  emptyDir: {}`

Mount `/tools` in the main openclaw container and add `/tools` to PATH via env:
```yaml
env:
  - name: PATH
    value: "/tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
```

If kubectl **is present**, skip this init container.

#### Step 3 — Bind the ServiceAccount to the OpenClaw Deployment

In `k8s-manifests/overlays/prod/openclaw.yaml` under the Deployment spec:
```yaml
spec:
  template:
    spec:
      serviceAccountName: harvis-kubectl-reader
      automountServiceAccountToken: true
```

This gives the pod in-cluster credentials matching the read-only ClusterRole.

#### Step 4 — Create the Discord kubectl SKILL.md

Create `k8s-manifests/overlays/prod/skills/harvis-kubectl/SKILL.md` with content:

```markdown
# harvis-kubectl skill

You are the Harvis cluster monitor. The user is messaging you from Discord.
Your job: answer cluster health questions by running kubectl and summarizing clearly.

## Hard rules
- Run ONLY the kubectl commands listed below. Nothing else.
- NEVER print lines containing SECRET, TOKEN, PASSWORD, KEY — redact as [REDACTED].
- For output longer than 40 lines, summarize; do not dump raw text.
- Write ops (rollout restart, scale) require the user to reply "confirm" first.
- CI scripts run ONLY when user says "run CI", "deploy", or "build and push".

## Allowed read commands
kubectl get pods -A
kubectl get pods -n <namespace>
kubectl describe pod <name> -n <namespace>
kubectl logs <pod> -n <namespace> --tail=100
kubectl logs <pod> -n <namespace> --tail=100 --previous
kubectl get services -A
kubectl get deployments -A
kubectl rollout status deployment/<name> -n <namespace>
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
kubectl get nodes
kubectl describe node <name>
kubectl top pods -n <namespace>
kubectl top nodes

## Allowed write commands (require "confirm" reply before running)
kubectl rollout restart deployment/<name> -n <namespace>
kubectl scale deployment/<name> --replicas=<n> -n <namespace>

## CI scripts (run ONLY on explicit trigger)
./scripts/build-push.sh
./scripts/deploy.sh

## Response format
1. One-line health summary
2. Bullet list of any pods NOT in Running/Completed state (with restart count)
3. For logs: highlight ERROR/WARN lines only
4. Close with: "All good ✓" or "Action needed: <what>"
```

#### Step 5 — Mount the skill as a ConfigMap in openclaw.yaml

In `k8s-manifests/overlays/prod/openclaw.yaml` add a ConfigMap:

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: harvis-kubectl-skill
  namespace: ai-agents
data:
  SKILL.md: |
    <paste full SKILL.md content here>
```

Add to the Deployment volumeMounts:
```yaml
- name: harvis-kubectl-skill
  mountPath: /skills/harvis-kubectl/SKILL.md
  subPath: SKILL.md
```

Add to volumes:
```yaml
- name: harvis-kubectl-skill
  configMap:
    name: harvis-kubectl-skill
```

Register it in the `openclaw.json` ConfigMap skills array:
```json
{
  "name": "harvis-kubectl",
  "path": "/skills/harvis-kubectl/SKILL.md",
  "triggers": ["kubectl", "pods", "cluster", "logs", "deploy", "health", "run CI", "build and push"]
}
```

### Files to Create/Modify
- `k8s-manifests/services/harvis-kubectl-rbac.yaml` — new file
- `k8s-manifests/overlays/prod/openclaw.yaml` — ServiceAccount binding, init container (if kubectl missing), skill ConfigMap + mount
- `k8s-manifests/overlays/prod/skills/harvis-kubectl/SKILL.md` — new file (source of truth before inlining into ConfigMap)

### Acceptance Criteria
- `kubectl get pods -A` returns cluster status when asked in Discord DM
- No secrets/tokens appear in output
- CI scripts only run on explicit user trigger
- Write ops ask for "confirm" before executing
- All changes in a single PR, co-authored by brandoz2255

---

## Task 3 — CI Auto-trigger After PR Merge (do after Task 2 is merged)

**Priority**: MEDIUM

### Goal
When Harvis opens a PR and the user merges it, Harvis sends a Discord DM:
"PR #N merged ✓ — want me to run CI?" If user says yes, runs build-push + deploy.

### Repo Scan Before Starting
```bash
# Check if a GitHub webhook handler already exists in the backend
grep -rn "webhook\|github" python_back_end/main.py | head -20
grep -rn "webhook" python_back_end/ --include="*.py" | head -20

# Check existing backend routes
grep -n "^@app\." python_back_end/main.py | head -30

# Check discord bridge if it exists
ls python_back_end/discord_bridge.py 2>/dev/null || echo "not found"
```

### What Harvis Should Do

1. If `/api/github/webhook` doesn't exist in `python_back_end/main.py`, create it:
   - Validate `X-Hub-Signature-256` header against `GITHUB_WEBHOOK_SECRET` env var
   - On `pull_request` event with `action: "closed"` + `merged: true`:
     - Check if PR author is `harvisai-dulc3-cmd`
     - Send Discord DM via bot: "PR #N '{title}' merged ✓ — reply 'run CI' to deploy"

2. The Discord listener (in `python_back_end/discord_bridge.py` if it exists, or
   wire into the existing Discord channel path) handles "run CI" reply:
   - Runs `./scripts/build-push.sh && ./scripts/deploy.sh`
   - Reports rollout status back to Discord

3. Add `GITHUB_WEBHOOK_SECRET` to `k8s-manifests/overlays/prod/backend-secret.yaml`
   (add as a placeholder — user fills in the real value before applying)

### Files to Modify
- `python_back_end/main.py` — webhook endpoint
- `python_back_end/discord_bridge.py` — DM notification + "run CI" handler (create if missing)
- `python_back_end/requirements.txt` — add `discord.py` if not present
- `k8s-manifests/overlays/prod/backend-secret.yaml` — add `GITHUB_WEBHOOK_SECRET` placeholder

### Acceptance Criteria
- Webhook receives GitHub merge event and sends Discord DM
- "run CI" reply triggers build-push + deploy scripts
- Webhook signature validated — unsigned requests rejected

---

## Notes for Harvis

- **Scan the repo first** on every task — don't assume, read the actual files
- **You cannot touch** `openclaw/openclaw/` source — black box, use init containers + K8s manifests only
- **Your k8s access** is `k8s-manifests/` only — all OpenClaw changes go in `k8s-manifests/overlays/prod/openclaw.yaml`
- Always open PRs with: `Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>`
- Use conventional commits: `fix:`, `feat:`, `chore:`
- Document changes in `front_end/jfrontend/changes.md`
- Do NOT apply manifests to the cluster — open the PR, the user merges and applies
