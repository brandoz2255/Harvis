# CI Pipeline Guide for LLM Agents

**Last Updated:** 2026-03-27  
**Purpose:** Enable LLM agents (like opencode/Claude Code) to automate the Harvis build and deployment pipeline

---

## Overview

The `ci_pipeline.sh` script is the primary automation tool for building, tagging, and deploying Harvis images. It's designed to work both interactively (for humans) and non-interactively (for LLM agents).

### Architecture Flow

```
┌─────────────────┐
│  LLM Agent      │
│  (opencode)     │
└────────┬────────┘
         │ Executes
         ▼
┌─────────────────┐
│  ci_pipeline.sh │  ← Build images, update K8s manifests
└────────┬────────┘
         │ Pushes
         ▼
┌─────────────────┐
│  Docker Hub     │  ← dulc3/jarvis-{frontend,backend}
└────────┬────────┘
         │ Triggers
         ▼
┌─────────────────┐
│  ArgoCD         │  ← Auto-syncs from main branch
└────────┬────────┘
         │ Deploys
         ▼
┌─────────────────┐
│  K8s Cluster    │  ← ai-agents namespace
└─────────────────┘
```

---

## CLI Flags Reference

| Flag | Short | Description | Default | Example |
|------|-------|-------------|---------|---------|
| `--frontend-version` | `-f` | Frontend image tag | `latest` | `-f v1.2.3` |
| `--backend-version` | `-b` | Backend image tag | `latest` | `-b v1.2.3` |
| `--commit-msg` | `-m` | Custom git commit message | auto-generated | `-m "feat: add MCP RAG"` |
| `--push` | `-p` | Push images to Docker Hub | `no` | `-p` |
| `--no-git-push` | `-n` | Skip git commit/push | `no` | `-n` |
| `--debug` | `-d` | Enable debug/verbose output | `no` | `-d` |
| `--dry-run` | | Preview without executing | `no` | `--dry-run` |
| `--yes` | `-y` | Skip all prompts | `no` | `-y` |
| `--help` | `-h` | Show help message | - | `-h` |

---

## Common Agent Workflows

### 1. Full Build and Deploy (Most Common)

Build all images, push to Docker Hub, commit K8s changes, push to GitHub:

```bash
./ci_pipeline.sh -f newest -b newest -m "chore: deploy latest build [ci]" -p
```

**What happens:**
1. Builds `dulc3/jarvis-frontend:newest`
2. Builds `dulc3/jarvis-backend:newest`
3. Builds artifact-executor, code-executor, document-worker, tts-worker
4. Pushes all images to Docker Hub
5. Updates `k8s-manifests/overlays/prod/kustomization.yaml`
6. Commits with message "chore: deploy latest build [ci]"
7. Pushes to GitHub (ArgoCD auto-deploys)

---

### 2. Build Only (No Push)

Build images locally without pushing or committing:

```bash
./ci_pipeline.sh -f test -b test -n
```

**Use case:** Testing a new build before deploying

---

### 3. Debug Mode

Enable verbose output for troubleshooting:

```bash
./ci_pipeline.sh -d -f debug -b debug
```

**Use case:** Debugging build failures or checking what the script is doing

---

### 4. Dry Run

Preview what would happen without making changes:

```bash
./ci_pipeline.sh -f v1.0.0 -b v1.0.0 --dry-run
```

**Use case:** Safe preview before executing

---

### 5. Custom Commit Message

Provide a meaningful commit message for the change:

```bash
./ci_pipeline.sh -f v1.2.3 -b v1.2.3 -m "feat: add MCP RAG server for external AI agents" -p
```

**Use case:** When deploying a specific feature

---

## Commit Message Convention

Use [Conventional Commits](https://www.conventionalcommits.org/) for meaningful history:

| Type | Description | Example |
|------|-------------|---------|
| `feat:` | New feature | `feat: add MCP RAG server` |
| `fix:` | Bug fix | `fix: resolve embedding timeout` |
| `chore:` | Maintenance | `chore: update images to v1.2.3 [ci]` |
| `docs:` | Documentation | `docs: update deployment guide` |
| `refactor:` | Code refactor | `refactor: simplify RAG client` |
| `perf:` | Performance | `perf: optimize vector search` |

**Examples:**
```bash
# Feature deployment
./ci_pipeline.sh -f v1.2.3 -b v1.2.3 -m "feat: add MCP RAG server for external AI agents" -p

# Bug fix
./ci_pipeline.sh -f v1.2.4 -b v1.2.4 -m "fix: resolve embedding timeout issue" -p

# Routine update
./ci_pipeline.sh -f newest -b newest -m "chore: deploy latest build [ci]" -p
```

---

## Images Built by Pipeline

| Image | Source Directory | Purpose |
|-------|------------------|---------|
| `dulc3/jarvis-frontend:<VERSION>` | `front_end/newjfrontend/` | Next.js frontend |
| `dulc3/jarvis-backend:<VERSION>` | `python_back_end/` | Main backend (FastAPI) |
| `dulc3/harvis-artifact-executor:<VERSION>` | `python_back_end/` | Node.js artifact executor |
| `dulc3/harvis-code-executor:<VERSION>` | `python_back_end/` | Python code executor |
| `dulc3/harvis-document-worker:<VERSION>` | `python_back_end/` | Async document processing |
| `dulc3/harvis-tts-worker:<VERSION>` | `python_back_end/` | TTS/Whisper (tagged from backend) |
| **MCP RAG Server** | Uses `dulc3/jarvis-backend:<VERSION>` | External AI agent RAG access |

**Note:** MCP RAG server uses the same backend image but runs a different command (`mcp_server.app:app` instead of main backend).

---

## ArgoCD Integration

### How It Works

1. **Image Push:** Images are pushed to Docker Hub (with `-p` flag)
2. **Kustomization Update:** Script updates `k8s-manifests/overlays/prod/kustomization.yaml`
3. **Git Commit:** Changes are committed with provided or auto-generated message
4. **Git Push:** Changes are pushed to `main` branch
5. **ArgoCD Sync:** ArgoCD detects changes and auto-deploys within 3 minutes

### Files Modified

- `k8s-manifests/overlays/prod/kustomization.yaml` - Image tags updated
- All patch references to `dulc3/jarvis-*` images updated

### What's NOT Updated

- OpenClaw images (managed by separate `ci_openclaw_pipeline.sh`)
- Non-Harvis services

---

## Prerequisites for LLM Agents

### 1. SSH Keys (for Git Push)

```bash
# SSH agent must be running with keys loaded
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

**Error if not configured:**
```
Push failed - you may need to push manually:
  eval $(ssh-agent -s) && ssh-add ~/.ssh/id_ed25519 && git push origin main
```

### 2. Docker Hub Authentication

```bash
# Must be logged into Docker Hub
docker login
```

**Error if not authenticated:**
```
unauthorized: authentication required
```

### 3. Docker Build Prerequisites

- Docker daemon running
- Sufficient disk space (~8-10 GB per image)
- Network connectivity for pulling base images

---

## Troubleshooting

### Build Fails

**Check:**
```bash
# Enable debug mode
./ci_pipeline.sh -d -f test -b test

# Check Docker logs
docker logs <container_id>

# Verify source directory exists
ls -la python_back_end/
ls -la front_end/newjfrontend/
```

### Git Push Fails

**Solution:**
```bash
# Manual push
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
git push origin main
```

**Or use skip flag:**
```bash
./ci_pipeline.sh -f v1.0.0 -b v1.0.0 -n  # Skip git push
```

### ArgoCD Not Syncing

**Check:**
```bash
# Verify git push succeeded
git log --oneline -5

# Check ArgoCD app status
kubectl get app -n argocd

# Force sync if needed
argocd app sync harvis --grpc-web
```

### Image Not Deployed

**Verify:**
```bash
# Check image exists on Docker Hub
docker pull dulc3/jarvis-backend:<VERSION>

# Check K8s pod status
kubectl get pods -n ai-agents

# Check pod logs
kubectl logs -f deployment/harvis-ai-backend -n ai-agents
```

---

## Agent-Specific Instructions

### For opencode/Claude Code

**Step 1:** Read this file and `CLAUDE.md`

**Step 2:** Execute pipeline with appropriate flags:
```bash
# Example: Deploy MCP RAG server
./ci_pipeline.sh -f newest -b newest -m "feat: add MCP RAG server for external AI agents" -p
```

**Step 3:** Verify deployment:
```bash
# Check pods
kubectl get pods -n ai-agents | grep -E "mcp|backend"

# Check logs
kubectl logs -f deployment/harvis-ai-mcp-rag -n ai-agents
```

**Step 4:** Test functionality:
```bash
# Port-forward for testing
kubectl port-forward svc/harvis-ai-mcp-rag 8888:8000 -n ai-agents

# Test health endpoint
curl http://localhost:8888/health
```

---

## Examples by Use Case

### Deploy New Feature

```bash
./ci_pipeline.sh \
  -f v1.3.0 \
  -b v1.3.0 \
  -m "feat: add MCP RAG server for external AI agents" \
  -p
```

### Emergency Hotfix

```bash
./ci_pipeline.sh \
  -f hotfix-1 \
  -b hotfix-1 \
  -m "fix: critical security patch [hotfix]" \
  -p
```

### Testing in Dev

```bash
./ci_pipeline.sh \
  -f test-$(date +%s) \
  -b test-$(date +%s) \
  -n  # Don't push to production
```

### Nightly Build

```bash
./ci_pipeline.sh \
  -f nightly-$(date +%Y%m%d) \
  -b nightly-$(date +%Y%m%d) \
  -m "chore: nightly build $(date +%Y-%m-%d) [ci]" \
  -p
```

---

## Script Location

```
/home/dulc3/Documents/github/harvis/aidev/ci_pipeline.sh
```

**Make executable if needed:**
```bash
chmod +x ci_pipeline.sh
```

---

## Related Documentation

- **CLAUDE.md** - Main repository guidelines
- **MCP_RAG_SERVER_IMPLEMENTATION.md** - MCP server details
- **skills/Harvis/harvis-mcp-rag/SKILL.md** - MCP RAG skill documentation
- **k8s-manifests/overlays/prod/** - Kubernetes manifests

---

**Last Updated:** 2026-03-27  
**Maintained by:** Harvis CI/CD Team
