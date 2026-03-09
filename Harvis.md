# Harvis.md — Task Queue for Harvis

Tasks for Harvis (OpenClaw agent) to execute autonomously.
Work in order. Open a PR for each task. Co-author every commit.

---

## BEFORE YOU START ANY TASK

**Step 1 — Read the relevant skill first.**
Every task below lists which skill to read. Do not skip this.

```
# How to read a skill:
read /skills/harvis-vibecoding/SKILL.md    ← for coding tasks
read /skills/harvis-github/SKILL.md        ← for PR/git tasks
read /skills/harvis-agent/SKILL.md         ← for general tasks
```

**Step 2 — Scan the repo before touching anything.**
```bash
exec: find /home/node/.openclaw/workspace/Harvis -maxdepth 3 -type f \( -name "*.py" -o -name "*.yaml" \) | grep -v __pycache__ | grep -v node_modules | head -50
exec: git -C /home/node/.openclaw/workspace/Harvis log --oneline -5
exec: git -C /home/node/.openclaw/workspace/Harvis status
```

**Step 3 — Memory check.**
```
memory_search: "harvis repo"
memory_search: "kubectl"
memory_search: "python-docx"
```

**You only have access to:**
- `k8s-manifests/` — all K8s manifests
- Harvis source — `python_back_end/`, `front_end/`, `scripts/`
- You CANNOT touch `openclaw/openclaw/` source — black box

**K8s changes: open PR only. Never kubectl apply directly.**

---

## Task 1 — Apply kubectl RBAC (ServiceAccount + ClusterRole)

**Skills to read first**: `harvis-vibecoding`, `harvis-github`
**Priority**: HIGH — enables Discord kubectl access from PR #57

### Background
PR #57 added `workspace/kubectl_proxy.py` (the backend endpoint for kubectl commands).
But the OpenClaw pod still needs a read-only K8s ServiceAccount so kubectl commands
inside the pod can authenticate against the cluster API.

### What Harvis Should Do

**Step 1 — Scan what RBAC files already exist:**
```bash
exec: find /home/node/.openclaw/workspace/Harvis/k8s-manifests -name "*rbac*" -o -name "*role*" -o -name "*serviceaccount*" | sort
exec: cat /home/node/.openclaw/workspace/Harvis/k8s-manifests/services/ 2>/dev/null || echo "no services dir yet"
```

**Step 2 — Check if kubectl binary exists in the OpenClaw pod:**
The backend proxy (`workspace/kubectl_proxy.py`) runs kubectl server-side on the backend pod,
not inside OpenClaw. So check the **backend pod** for kubectl:
```bash
exec: # Ask user to run this — Harvis cannot kubectl from workspace
# kubectl -n ai-agents exec deployment/harvis-ai-merged-ollama-backend -- which kubectl
```
If kubectl is missing from the backend pod, add an init container to install it there.

**Step 3 — Create `k8s-manifests/services/harvis-kubectl-rbac.yaml`:**

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
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods", "nodes"]
    verbs: ["get", "list"]
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

**Step 4 — Bind the ServiceAccount to the backend Deployment:**
In `k8s-manifests/overlays/prod/openclaw.yaml`, find the `harvis-ai-merged-ollama-backend`
Deployment and add under `spec.template.spec`:
```yaml
serviceAccountName: harvis-kubectl-reader
automountServiceAccountToken: true
```

**Step 5 — Commit and open PR:**
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git add k8s-manifests/services/harvis-kubectl-rbac.yaml \
          k8s-manifests/overlays/prod/openclaw.yaml && \
  git commit -m "feat: add kubectl RBAC ServiceAccount for backend pod

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
exec: git push origin HEAD && gh pr create --title "feat: kubectl RBAC for Discord kubectl access" --body "## What\n- ServiceAccount harvis-kubectl-reader\n- Read-only ClusterRole + binding\n- Bind to backend deployment\n\n## Why\n- Enables /kubectl/exec endpoint to authenticate against cluster API"
```

### Files to Create/Modify
- `k8s-manifests/services/harvis-kubectl-rbac.yaml` — new file
- `k8s-manifests/overlays/prod/openclaw.yaml` — add serviceAccountName to backend Deployment

### Acceptance Criteria
- YAML is valid (no syntax errors)
- ServiceAccount bound to correct pod (backend, not openclaw)
- PR opened with co-author trailer

---

## Task 2 — Wire Web App to Use `planner` Agent

**Skills to read first**: `harvis-vibecoding`
**Priority**: HIGH — makes the web app Harvis much smarter than Discord Harvis

### Background
The Discord agent (`main`) accumulates long chat history which causes hallucination.
The `harvis-planner` agent (now configured in `openclaw.yaml`) uses Kimi K2.5 with a
disciplined plan-before-act system prompt. The web app chat should route to `planner`
instead of `main`.

### What Harvis Should Do

**Step 1 — Find where the web app sends chat requests:**
```bash
exec: grep -rn "agent_id\|agentId\|openclaw\|ws://" /home/node/.openclaw/workspace/Harvis/python_back_end/ | grep -v __pycache__ | head -20
exec: grep -rn "agent_id\|agentId" /home/node/.openclaw/workspace/Harvis/front_end/jfrontend/app/ | head -20
```

**Step 2 — Find the OpenClaw client:**
```bash
exec: cat /home/node/.openclaw/workspace/Harvis/python_back_end/workspace/openclaw_client.py
```

**Step 3 — Update to use `planner` agent_id for web app chat:**
In the backend chat handler (probably `main.py` `/api/chat` route), ensure calls to
OpenClaw pass `agent_id: "planner"` for web app sessions vs `agent_id: "main"` for Discord.

**Step 4 — Commit and PR:**
```bash
exec: cd /home/node/.openclaw/workspace/Harvis && \
  git add python_back_end/main.py python_back_end/workspace/openclaw_client.py && \
  git commit -m "feat: route web app chat to planner agent for smarter responses

Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>"
```

### Acceptance Criteria
- Web app chat uses `agent_id: "planner"`
- Discord still uses `agent_id: "main"` (unchanged)
- No regression in existing chat flow

---

## Task 3 — Research Agent Web-Fetch Proxy Endpoint

**Skills to read first**: `harvis-vibecoding`, `harvis-research`
**Priority**: MEDIUM — required for Research Agent to safely browse the web

### Background
OpenClaw cannot call external URLs directly (prompt injection risk).
All web fetches must go through the Harvis backend which sanitizes content.

### What Harvis Should Do

**Step 1 — Check if endpoint already exists:**
```bash
exec: grep -n "web.fetch\|web_fetch\|/api/tools" /home/node/.openclaw/workspace/Harvis/python_back_end/main.py | head -10
exec: ls /home/node/.openclaw/workspace/Harvis/python_back_end/tools/
```

**Step 2 — Create `python_back_end/tools/web_fetch.py`** if it doesn't exist:

```python
"""
Secure web-fetch proxy for OpenClaw agents.
Fetches URLs, strips dangerous content, returns clean plain text.
OpenClaw never calls external URLs directly — all go through here.

Security:
- Blocks RFC-1918 / localhost URLs (SSRF prevention)
- Strips <script>, <style>, hidden elements, HTML comments
- Truncates to 8000 tokens max
- Validates OPENCLAW_GATEWAY_TOKEN
- Logs all fetches to audit table
"""
import re
import logging
import os
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
BLOCKED_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                    "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                    "172.30.", "172.31.", "192.168.")

web_fetch_router = APIRouter(prefix="/api/tools", tags=["tools"])

class WebFetchRequest(BaseModel):
    url: str
    purpose: str = "research"

class WebFetchResponse(BaseModel):
    url: str
    content: str
    truncated: bool

def validate_url(url: str):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTS:
        raise HTTPException(status_code=403, detail="Blocked host")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=403, detail="Only http/https allowed")
    if any(host.startswith(p) for p in BLOCKED_PREFIXES):
        raise HTTPException(status_code=403, detail="RFC-1918 addresses blocked")

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none")):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text

MAX_CHARS = 32000  # ~8k tokens

@web_fetch_router.post("/web-fetch", response_model=WebFetchResponse)
async def web_fetch(
    request: WebFetchRequest,
    x_openclaw_token: str = Header(default="", alias="X-OpenClaw-Token"),
):
    if OPENCLAW_GATEWAY_TOKEN and x_openclaw_token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    validate_url(request.url)
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(request.url, headers={"User-Agent": "HarvisResearch/1.0"})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type:
                text = extract_text(resp.text)
            else:
                text = resp.text
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e}")
    truncated = len(text) > MAX_CHARS
    return WebFetchResponse(url=request.url, content=text[:MAX_CHARS], truncated=truncated)
```

**Step 3 — Register the router in main.py:**
```bash
exec: grep -n "from tools import\|include_router.*maps\|include_router.*openclaw" /home/node/.openclaw/workspace/Harvis/python_back_end/main.py | head -5
```
Add `from tools.web_fetch import web_fetch_router` and `app.include_router(web_fetch_router)`.

**Step 4 — Commit and PR.**

### Acceptance Criteria
- `POST /api/tools/web-fetch` returns clean text for valid URLs
- RFC-1918 URLs return 403
- Token auth works
- PR opened with co-author trailer

---

## Notes for Harvis

- **Read the skill file for each task before starting** — listed at top of each task
- **Scan the repo first** — never assume file locations
- **You cannot touch** `openclaw/openclaw/` — K8s manifests + Harvis source only
- **K8s changes**: PR only, never kubectl apply
- **Every commit**: `Co-authored-by: brandoz2255 <124217011+brandoz2255@users.noreply.github.com>`
- **Conventional commits**: `fix:` `feat:` `chore:` `docs:`
- **Document changes** in `front_end/jfrontend/changes.md`
