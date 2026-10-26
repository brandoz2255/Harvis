# Harvis AI - CI/CD Setup & Review Guide

## 📋 Overview

This guide documents the complete CI/CD pipeline for Harvis AI, which uses:
- **GitHub** as the single source of truth (code repository)
- **GitLab CI** for building Docker images (utilizing local K8s runners with Docker cache)
- **FluxCD** for GitOps-based automated deployments to Kubernetes

## 🏗️ Architecture Flowchart

```
┌──────────────┐
│  Developer   │
│ (Local Dev)  │
└──────┬───────┘
       │ git push feature-branch
       ▼
┌──────────────────────────────────────────┐
│         GitHub Repository                │
│         (Single Source of Truth)         │
└──────┬───────────────────────────────────┘
       │ Pull Request
       ▼
┌──────────────────────────────────────────┐
│      GitHub Actions - SAST Scans         │
│  ✓ CodeQL     ✓ Semgrep   ✓ Trivy       │
│  ✓ Safety     ✓ NPM Audit ✓ Hadolint    │
│  ✓ Gitleaks   ✓ Dependency Review       │
└──────┬───────────────────────────────────┘
       │ Merge to main (SAST passed)
       ▼
┌──────────────────────────────────────────┐
│  GitHub Actions - Trigger GitLab CI      │
│  (Webhook with commit metadata)          │
└──────┬───────────────────────────────────┘
       │ HTTP POST
       ▼
┌──────────────────────────────────────────┐
│         GitLab CI Pipeline               │
│  (Runs on K8s GitLab Runners)            │
│                                          │
│  Build Stage:                            │
│    • Backend  → node1 (RTX 4090)        │
│    • Frontend → node2 (RTX 3090 Ti)     │
│                                          │
│  Push Stage:                             │
│    • Push to localhost:5000             │
│    • Tag: staging-<sha>, staging-latest │
│                                          │
│  Tag Stage (for releases):               │
│    • Tag: v1.0.0, v1.0.1, etc.          │
└──────┬───────────────────────────────────┘
       │ docker push
       ▼
┌──────────────────────────────────────────┐
│    Local Container Registry              │
│    (localhost:5000)                      │
└──────┬───────────────────────────────────┘
       │ Image scan (every 1 minute)
       ▼
┌──────────────────────────────────────────┐
│            FluxCD                        │
│  (GitOps Continuous Deployment)          │
│                                          │
│  Image Reflector:                        │
│    • Scans registry for new images      │
│                                          │
│  Image Policy:                           │
│    • Staging: staging-* tags            │
│    • Prod: v*.*.* semver tags           │
│                                          │
│  Image Automation:                       │
│    • Updates K8s manifests in Git       │
│    • Commits changes automatically      │
│                                          │
│  Kustomization:                          │
│    • Reconciles staging (5min)          │
│    • Reconciles prod (10min)            │
└──────┬───────────────────────────────────┘
       │ kubectl apply
       ▼
┌──────────────────────────────────────────┐
│       Kubernetes Cluster (K3s)           │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   Staging (ai-agents-staging)      │ │
│  │   • Backend  (node1)               │ │
│  │   • Frontend (node2)               │ │
│  │   • Ollama   (node2)               │ │
│  │   • PostgreSQL, Nginx, n8n         │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │   Production (ai-agents)           │ │
│  │   • Backend  (node1)               │ │
│  │   • Frontend (node2)               │ │
│  │   • Ollama   (node2)               │ │
│  │   • PostgreSQL, Nginx, n8n         │ │
│  └────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

## 📁 Configuration Files Location Reference

### 1. GitHub Actions Workflows
**Location**: `.github/workflows/`

| File | Purpose |
|------|---------|
| `sast-security-scan.yml` | Security scanning (CodeQL, Semgrep, Trivy, Safety, NPM Audit, Hadolint, Gitleaks) |
| `trigger-gitlab-ci.yml` | Triggers GitLab CI pipeline via webhook when code is pushed to main |

**Key Features**:
- SAST runs on all PRs to main/develop
- Triggers GitLab CI only after SAST passes
- Passes commit metadata (SHA, author, message) to GitLab
- Creates GitHub deployment tracking events

### 2. GitLab CI Pipeline
**Location**: `.gitlab-ci.yml` (root directory)

**Stages**:
1. **Build**: Build Docker images with cache
2. **Push**: Push to localhost:5000 registry
3. **Tag**: Tag releases with semantic versions
4. **Deploy**: Trigger Flux updates and cleanup

**Runner Tags**:
- Node 1 (node-gpu-1): `node1`, `backend`, `gpu`, `docker`
- Node 2 (node-gpu-2): `node2`, `frontend`, `docker`

**Image Tagging Strategy**:
```
Backend: localhost:5000/jarvis-backend
Frontend: localhost:5000/jarvis-frontend

Tags:
  - <git-sha-short>           # Unique commit tag
  - staging-latest            # Latest staging build
  - staging-<git-sha-short>   # Staging specific commit
  - latest                    # Latest production (from main only)
  - v1.0.0                    # Semantic version (from Git tags)
  - build-<pipeline-id>       # Build identifier
```

### 3. GitLab Runners (Kubernetes Deployment)
**Location**: `k8s-manifests/ci-cd/`

| File | Purpose |
|------|---------|
| `gitlab-runner-namespace.yaml` | Creates `gitlab-runner` namespace |
| `gitlab-runner-secrets.yaml` | GitLab registration token and credentials (TEMPLATE - requires update) |
| `gitlab-runner-config.yaml` | Runner configuration (concurrent jobs, Docker executor) |
| `gitlab-runner-rbac.yaml` | RBAC permissions for runners |
| `gitlab-runner-deployment.yaml` | Deploys 2 runners (one per K8s node) |
| `local-registry-config.yaml` | Registry garbage collection config |
| `README.md` | Detailed setup instructions |

**Deployment Strategy**:
- **2 Runners**: One on each K8s node (node1, node2)
- **Executor**: Docker (using host Docker socket `/var/run/docker.sock`)
- **Node Affinity**: Each runner pinned to specific node for GPU access
- **RBAC**: Full cluster access for Docker builds

### 4. FluxCD GitOps Configuration
**Location**: `k8s-manifests/flux-system/`

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates `flux-system` namespace |
| `gotk-components.yaml` | Flux controllers (generated by `flux install`) |
| `git-repository.yaml` | Git source pointing to GitHub repo (REQUIRES UPDATE) |
| `image-registry.yaml` | ImageRepository and ImagePolicy for localhost:5000 |
| `image-update-automation.yaml` | Auto-updates image tags in Git |
| `kustomization-staging.yaml` | Reconciles staging environment (5min interval) |
| `kustomization-prod.yaml` | Reconciles production environment (10min interval) |
| `README.md` | Flux installation and configuration guide |

**Image Policies**:
- **Staging**: Filters for `staging-*` tags, uses latest
- **Production**: Filters for `v*.*.*` tags, uses semver range `>=1.0.0`

**Automation**:
- Scans registry every 1 minute
- Auto-commits image updates to Git
- Reconciles staging every 5 minutes
- Reconciles production every 10 minutes

### 5. Kustomize Overlays
**Location**: `k8s-manifests/overlays/`

```
overlays/
├── staging/
│   ├── kustomization.yaml    # Staging patches (namespace, replicas, resources)
│   └── namespace.yaml         # ai-agents-staging namespace
└── prod/
    ├── kustomization.yaml     # Production patches (namespace, replicas, resources)
    └── (uses ai-agents namespace from base)
```

**Environment Differences**:
- **Staging**: Reduced resources (8Gi memory), DEBUG logging, 1 replica, staging-latest tags
- **Production**: Full resources (12Gi memory), INFO logging, 1 replica, semver tags

### 6. Development Environment
**Location**: `docker-compose.dev.yml` (root directory)

**Features**:
- Hot-reload for backend and frontend
- Debug logging enabled
- No GPU constraints
- Pulls from localhost:5000 or builds locally
- Shared network with services (PostgreSQL, Ollama, n8n)

**Usage**: `docker-compose -f docker-compose.dev.yml up`

### 7. Documentation Files
**Location**: Various

| File | Purpose |
|------|---------|
| `CICD_QUICK_START.md` | 15-minute quick setup guide |
| `CI_CD_IMPLEMENTATION_SUMMARY.md` | Complete implementation details |
| `docs/CI_CD_DEPLOYMENT_GUIDE.md` | Comprehensive deployment guide |
| `k8s-manifests/ci-cd/README.md` | GitLab Runner setup instructions |
| `k8s-manifests/flux-system/README.md` | FluxCD setup instructions |

## 🔧 Prerequisites Checklist

Before setting up the pipeline, ensure you have:

- [ ] **K3s Cluster**: 2-node cluster running (node1 + node2)
- [ ] **kubectl**: Configured to access your K3s cluster
- [ ] **GitHub Repository**: Code pushed to GitHub
- [ ] **GitLab Account**: gitlab.com account or self-hosted instance
- [ ] **Local Registry**: Running at `localhost:5000`
- [ ] **Git**: Installed locally
- [ ] **Flux CLI**: Installed (`curl -s https://fluxcd.io/install.sh | sudo bash`)
- [ ] **Docker**: Running on both K8s nodes

**Verify Prerequisites**:
```bash
# Check K3s cluster
kubectl get nodes

# Check local registry
curl http://localhost:5000/v2/_catalog

# Check Flux CLI
flux --version

# Check Docker
docker ps
```

## 🚀 Setup Instructions

### Step 1: Configure GitHub Actions

#### 1.1 - Review GitHub Workflows
Files are already in place at `.github/workflows/`:
- `sast-security-scan.yml` ✅
- `trigger-gitlab-ci.yml` ✅

#### 1.2 - Set GitHub Secrets
Go to: `GitHub Repo → Settings → Secrets and variables → Actions → New repository secret`

Add these secrets:
```
GITLAB_WEBHOOK_URL=https://gitlab.com/api/v4/projects/<PROJECT_ID>/trigger/pipeline
GITLAB_TOKEN=<trigger-token-from-gitlab>
```

**How to get GitLab trigger token**:
1. Go to your GitLab project
2. Settings → CI/CD → Pipeline triggers
3. Click "Add trigger"
4. Copy the token

**How to get GitLab project ID**:
1. Go to your GitLab project
2. Settings → General
3. Project ID is shown at the top

**Example**:
```
GITLAB_WEBHOOK_URL=https://gitlab.com/api/v4/projects/12345678/trigger/pipeline
GITLAB_TOKEN=glptt-abc123xyz789
```

### Step 2: Set Up GitLab CI

#### 2.1 - Create/Mirror GitLab Repository
Option A: Mirror from GitHub (recommended)
1. GitLab → New project → Run CI/CD for external repository
2. Connect to GitHub and select your repo

Option B: Manual sync
1. Add GitLab as a remote: `git remote add gitlab <gitlab-repo-url>`
2. Push to GitLab: `git push gitlab main`

#### 2.2 - Review GitLab CI Configuration
File is already in place: `.gitlab-ci.yml` ✅

**Key Configuration**:
- Registry: `localhost:5000`
- Backend image: `localhost:5000/jarvis-backend`
- Frontend image: `localhost:5000/jarvis-frontend`
- Build cache enabled with `--cache-from`

### Step 3: Deploy GitLab Runners to Kubernetes

#### 3.1 - Update GitLab Runner Secrets

**IMPORTANT**: The secrets file is in `.gitignore` to prevent accidental commits of sensitive data.

```bash
# Copy the template to create your secrets file
cp k8s-manifests/ci-cd/gitlab-runner-secrets.yaml.template k8s-manifests/ci-cd/gitlab-runner-secrets.yaml

# Edit your secrets file (this file is gitignored)
nano k8s-manifests/ci-cd/gitlab-runner-secrets.yaml
```

Update these fields:
```yaml
stringData:
  # GitLab URL (use gitlab.com or your self-hosted URL)
  gitlab-url: "https://gitlab.com"

  # Get from: GitLab Project → Settings → CI/CD → Runners → New project runner
  registration-token: "YOUR_ACTUAL_REGISTRATION_TOKEN"

  # This will be populated after registration (leave as placeholder)
  runner-token: "REPLACE_WITH_YOUR_GITLAB_RUNNER_TOKEN_AFTER_REGISTRATION"
```

**Note**: The values are in plain text under `stringData` - Kubernetes will automatically base64 encode them.

#### 3.2 - Deploy GitLab Runners
```bash
# Deploy all GitLab Runner resources
kubectl apply -f k8s-manifests/ci-cd/

# Verify deployment
kubectl get pods -n gitlab-runner
kubectl get deployments -n gitlab-runner
```

Expected output:
```
NAME                           READY   STATUS    RESTARTS   AGE
gitlab-runner-node1-xxx        1/1     Running   0          1m
gitlab-runner-node2-xxx        1/1     Running   0          1m
```

#### 3.3 - Verify Runners in GitLab
1. Go to: GitLab Project → Settings → CI/CD → Runners
2. You should see 2 runners registered:
   - `gitlab-runner-node1` (tags: node1, backend, gpu, docker)
   - `gitlab-runner-node2` (tags: node2, frontend, docker)

### Step 4: Install and Configure FluxCD

#### 4.1 - Install Flux CLI
```bash
curl -s https://fluxcd.io/install.sh | sudo bash
flux --version
```

#### 4.2 - Install Flux on Kubernetes
```bash
# Install Flux with image automation controllers
flux install --components-extra=image-reflector-controller,image-automation-controller

# Verify installation
flux check
```

#### 4.3 - Update Git Repository URL
Edit: `k8s-manifests/flux-system/git-repository.yaml`

```bash
nano k8s-manifests/flux-system/git-repository.yaml
```

Update the URL to your GitHub repository:
```yaml
spec:
  url: https://github.com/YOUR_USERNAME/YOUR_REPO.git
  ref:
    branch: main
```

**IMPORTANT**: If your repo is private, you'll need to configure Git credentials:
```bash
# Create a GitHub personal access token (PAT)
# GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
# Required scopes: repo

# Create Flux secret with Git credentials
flux create secret git flux-system \
  --url=https://github.com/YOUR_USERNAME/YOUR_REPO.git \
  --username=YOUR_GITHUB_USERNAME \
  --password=YOUR_GITHUB_PAT \
  --namespace=flux-system
```

For public repos, the secret is not required.

#### 4.4 - Apply Flux Configuration
```bash
# Apply all Flux resources
kubectl apply -f k8s-manifests/flux-system/

# Verify Flux resources
flux get all
flux get kustomizations
flux get images all
```

#### 4.5 - Configure Git Write-Back (for Image Automation)
FluxCD will auto-commit image tag updates to your Git repo. Configure credentials:

```bash
# Create deploy key for Flux (read/write)
ssh-keygen -t ed25519 -C "flux-image-automation" -f ~/.ssh/flux-deploy-key

# Add public key to GitHub
# GitHub → Repo → Settings → Deploy keys → Add deploy key
# Paste contents of ~/.ssh/flux-deploy-key.pub
# ✅ Enable "Allow write access"

# Create Flux secret with SSH key
kubectl create secret generic flux-system \
  --from-file=identity=~/.ssh/flux-deploy-key \
  --from-file=identity.pub=~/.ssh/flux-deploy-key.pub \
  --from-literal=known_hosts="$(ssh-keyscan github.com)" \
  --namespace=flux-system
```

Update `git-repository.yaml` to use SSH:
```yaml
spec:
  url: ssh://git@github.com/YOUR_USERNAME/YOUR_REPO.git
  secretRef:
    name: flux-system
```

Then reapply:
```bash
kubectl apply -f k8s-manifests/flux-system/git-repository.yaml
```

### Step 5: Deploy Staging Environment

#### 5.1 - Create Staging Namespace
```bash
kubectl apply -f k8s-manifests/overlays/staging/namespace.yaml
```

#### 5.2 - Build and Push Initial Images
You need at least one image in the registry for Flux to detect:

```bash
# Option A: Trigger via GitHub (recommended)
git commit --allow-empty -m "trigger: Initial CI/CD pipeline run"
git push origin main

# Option B: Build locally
cd python_back_end
docker build -t localhost:5000/jarvis-backend:staging-latest .
docker push localhost:5000/jarvis-backend:staging-latest

cd ../front_end/jfrontend
docker build -t localhost:5000/jarvis-frontend:staging-latest .
docker push localhost:5000/jarvis-frontend:staging-latest
```

#### 5.3 - Verify Staging Deployment
```bash
# Check Flux detected images
flux get images all

# Force reconciliation
flux reconcile kustomization harvis-ai-staging --with-source

# Check staging pods
kubectl get pods -n ai-agents-staging
kubectl get deployments -n ai-agents-staging

# Check pod images
kubectl describe pod -n ai-agents-staging <pod-name> | grep Image
```

### Step 6: Test the Complete Pipeline

#### 6.1 - Create a Feature Branch
```bash
git checkout -b feature/test-pipeline
echo "# Test change" >> README.md
git add README.md
git commit -m "test: Pipeline test"
git push origin feature/test-pipeline
```

#### 6.2 - Create Pull Request
1. Go to GitHub
2. Create PR: `feature/test-pipeline` → `main`
3. Watch GitHub Actions run SAST scans
4. Review security findings in PR comments and Security tab

#### 6.3 - Merge to Main
1. After SAST passes, merge the PR
2. GitHub Actions triggers GitLab CI webhook

#### 6.4 - Monitor GitLab CI Build
1. Go to GitLab: `Project → CI/CD → Pipelines`
2. Watch build progress:
   - Build backend (node1)
   - Build frontend (node2)
   - Push to localhost:5000
   - Tag as `staging-latest`

#### 6.5 - Verify Flux Deployment
```bash
# Watch Flux detect new image
flux get images all

# Watch staging deployment update
watch kubectl get pods -n ai-agents-staging

# Check deployment rollout
kubectl rollout status deployment/staging-harvis-ai-backend -n ai-agents-staging
kubectl rollout status deployment/staging-harvis-ai-frontend -n ai-agents-staging
```

#### 6.6 - Test Staging Application
```bash
# Get staging service URL
kubectl get svc -n ai-agents-staging

# Test staging endpoint (adjust port as needed)
curl http://<staging-ip>:9000
```

### Step 7: Deploy to Production

#### 7.1 - Create Version Tag
```bash
# Tag the release
git tag v1.0.0
git push origin v1.0.0
```

#### 7.2 - Monitor GitLab CI Build
GitLab CI detects the tag and builds production images:
- Tag as `v1.0.0`
- Tag as `latest`

#### 7.3 - Verify Flux Production Deployment
```bash
# Watch Flux detect versioned image
flux get images all

# Force production reconciliation
flux reconcile kustomization harvis-ai-prod --with-source

# Watch production deployment
watch kubectl get pods -n ai-agents

# Check rollout status
kubectl rollout status deployment/harvis-ai-backend -n ai-agents
kubectl rollout status deployment/harvis-ai-frontend -n ai-agents
```

## ✅ Verification Commands

### Check GitHub Actions
```bash
# View in browser
# https://github.com/YOUR_USERNAME/YOUR_REPO/actions

# Check recent workflow runs
gh run list  # Requires GitHub CLI
```

### Check GitLab CI
```bash
# View in browser
# https://gitlab.com/YOUR_USERNAME/YOUR_REPO/-/pipelines

# Test webhook manually
curl -X POST \
  -F "token=YOUR_GITLAB_TOKEN" \
  -F "ref=main" \
  "https://gitlab.com/api/v4/projects/PROJECT_ID/trigger/pipeline"
```

### Check GitLab Runners
```bash
# Check runner pods
kubectl get pods -n gitlab-runner

# Check runner logs
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1 -f
kubectl logs -n gitlab-runner deployment/gitlab-runner-node2 -f

# Verify runners in GitLab UI
# GitLab → Settings → CI/CD → Runners
```

### Check Container Registry
```bash
# List all images
curl http://localhost:5000/v2/_catalog

# List backend tags
curl http://localhost:5000/v2/jarvis-backend/tags/list

# List frontend tags
curl http://localhost:5000/v2/jarvis-frontend/tags/list
```

### Check FluxCD
```bash
# Overall Flux status
flux check

# Get all Flux resources
flux get all

# Check Git repository sync
flux get sources git

# Check image repositories
flux get images repository

# Check image policies
flux get images policy

# Check kustomizations
flux get kustomizations

# View Flux logs
flux logs --all-namespaces --follow
```

### Check Kubernetes Deployments
```bash
# Staging environment
kubectl get all -n ai-agents-staging
kubectl get pods -n ai-agents-staging -o wide
kubectl describe deployment staging-harvis-ai-backend -n ai-agents-staging

# Production environment
kubectl get all -n ai-agents
kubectl get pods -n ai-agents -o wide
kubectl describe deployment harvis-ai-backend -n ai-agents

# Check pod images
kubectl get pods -n ai-agents -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}'
```

### Check Application Logs
```bash
# Staging logs
kubectl logs -n ai-agents-staging deployment/staging-harvis-ai-backend -f
kubectl logs -n ai-agents-staging deployment/staging-harvis-ai-frontend -f

# Production logs
kubectl logs -n ai-agents deployment/harvis-ai-backend -f
kubectl logs -n ai-agents deployment/harvis-ai-frontend -f
```

## 🔍 Troubleshooting Guide

### Issue: GitHub Actions not triggering GitLab CI

**Symptoms**: Pipeline doesn't start after merge to main

**Checks**:
```bash
# Verify GitHub secrets are set
# GitHub → Repo → Settings → Secrets → Actions

# Test webhook manually
curl -X POST \
  -F "token=YOUR_GITLAB_TOKEN" \
  -F "ref=main" \
  "https://gitlab.com/api/v4/projects/PROJECT_ID/trigger/pipeline"
```

**Solution**:
- Verify `GITLAB_WEBHOOK_URL` and `GITLAB_TOKEN` are correct
- Check GitLab project ID is correct
- Verify trigger token is valid (GitLab → Settings → CI/CD → Pipeline triggers)

### Issue: GitLab Runners not registering

**Symptoms**: Runners don't appear in GitLab UI

**Checks**:
```bash
# Check runner pods
kubectl get pods -n gitlab-runner

# Check runner logs
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1
```

**Common errors**:
- `ERROR: Registering runner... failed`: Wrong registration token
- `ERROR: Verifying runner... is removed`: Runner was manually deleted in GitLab

**Solution**:
```bash
# Update registration token in secrets
kubectl edit secret gitlab-runner-secrets -n gitlab-runner

# Restart runner pods
kubectl rollout restart deployment/gitlab-runner-node1 -n gitlab-runner
kubectl rollout restart deployment/gitlab-runner-node2 -n gitlab-runner
```

### Issue: GitLab CI build fails with "Cannot connect to Docker daemon"

**Symptoms**: Build jobs fail with Docker errors

**Checks**:
```bash
# Verify Docker socket is mounted
kubectl describe pod -n gitlab-runner <runner-pod> | grep -A5 Mounts

# Check Docker is running on nodes
ssh node1 'docker ps'
ssh node2 'docker ps'
```

**Solution**:
- Verify `/var/run/docker.sock` is mounted in runner pods
- Check Docker daemon is running on K8s nodes
- Verify runner service account has RBAC permissions

### Issue: Flux not detecting new images

**Symptoms**: New images pushed but Flux doesn't update deployments

**Checks**:
```bash
# Check image repository status
flux get images repository

# Check for errors
kubectl describe imagerepository harvis-backend -n flux-system

# Test registry connectivity
curl http://localhost:5000/v2/jarvis-backend/tags/list
```

**Common issues**:
- Registry not accessible from cluster
- `insecure: true` not set for HTTP registry
- Image policy pattern doesn't match tags

**Solution**:
```bash
# Force image repository scan
flux reconcile image repository harvis-backend --with-source
flux reconcile image repository harvis-frontend --with-source

# Check image-registry.yaml has insecure: true
kubectl get imagerepository harvis-backend -n flux-system -o yaml
```

### Issue: Flux not updating manifests

**Symptoms**: Images detected but deployments don't update

**Checks**:
```bash
# Check image automation status
flux get images update

# Check for errors
kubectl describe imageupdateautomation flux-system -n flux-system

# Check Git repository write permissions
kubectl describe gitrepository harvis-ai-repo -n flux-system
```

**Solution**:
- Verify Flux has write access to Git repository (deploy key)
- Check `image-update-automation.yaml` Git configuration
- Verify image policy markers in deployment YAMLs:
  ```yaml
  # {"$imagepolicy": "flux-system:harvis-backend-staging"}
  ```

### Issue: Pods not updating after Flux reconciliation

**Symptoms**: Flux reconciles but pods still run old images

**Checks**:
```bash
# Check kustomization status
flux get kustomizations

# Check deployment image
kubectl get deployment staging-harvis-ai-backend -n ai-agents-staging -o jsonpath='{.spec.template.spec.containers[0].image}'

# Check pod image
kubectl get pods -n ai-agents-staging -o jsonpath='{.items[0].spec.containers[0].image}'
```

**Solution**:
```bash
# Force reconciliation
flux reconcile kustomization harvis-ai-staging --with-source

# Manually restart deployment
kubectl rollout restart deployment/staging-harvis-ai-backend -n ai-agents-staging

# Check for pod errors
kubectl describe pod <pod-name> -n ai-agents-staging
```

### Issue: SAST scans failing

**Symptoms**: GitHub Actions SAST workflow fails

**Checks**:
- Check GitHub Actions logs: `Repo → Actions → Workflow run`
- Review Security tab: `Repo → Security → Code scanning alerts`

**Common failures**:
- CodeQL: Code quality issues
- Semgrep: Vulnerability patterns detected
- Gitleaks: Secrets detected in code
- Trivy: High/critical vulnerabilities in dependencies

**Solution**:
- Fix security issues identified by scanners
- Review and accept false positives in Security tab
- Update dependencies to patch vulnerabilities

### Issue: Docker build cache not working

**Symptoms**: Builds are slow, not using cache

**Checks**:
```bash
# Check GitLab CI logs for cache messages
# Look for: "CACHED" or "Pulling from cache"
```

**Solution**:
- Ensure `latest` tag exists in registry
- Verify `--cache-from` is used in .gitlab-ci.yml
- Push an initial `latest` tag:
  ```bash
  docker tag localhost:5000/jarvis-backend:staging-latest localhost:5000/jarvis-backend:latest
  docker push localhost:5000/jarvis-backend:latest
  ```

## 🔄 Common Workflows

### Development Workflow
```bash
# 1. Start local development
docker-compose -f docker-compose.dev.yml up

# 2. Make changes, test locally

# 3. Commit and push to feature branch
git checkout -b feature/my-feature
git add .
git commit -m "feat: Add new feature"
git push origin feature/my-feature

# 4. Create PR on GitHub
# 5. SAST scans run automatically
# 6. Review and merge PR
```

### Staging Deployment Workflow
```bash
# 1. Merge PR to main (automatically triggers)

# 2. Monitor GitLab CI build
# Visit: https://gitlab.com/YOUR_USERNAME/YOUR_REPO/-/pipelines

# 3. Wait for Flux to deploy (5min max)
flux get kustomizations
kubectl get pods -n ai-agents-staging

# 4. Test staging environment
kubectl get svc -n ai-agents-staging
curl http://<staging-ip>:9000
```

### Production Release Workflow
```bash
# 1. Create version tag
git tag v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# 2. Monitor GitLab CI build
# Images tagged as v1.0.0

# 3. Wait for Flux to deploy (10min max)
flux get kustomizations
kubectl get pods -n ai-agents

# 4. Verify production deployment
kubectl rollout status deployment/harvis-ai-backend -n ai-agents
kubectl get svc -n ai-agents
curl http://<prod-ip>:9000
```

### Rollback Workflow (Staging)
```bash
# Option A: Via Flux (revert Git commit)
git revert <commit-sha>
git push origin main
flux reconcile kustomization harvis-ai-staging --with-source

# Option B: Via kubectl (temporary)
kubectl rollout undo deployment/staging-harvis-ai-backend -n ai-agents-staging

# Option C: Specific image tag
kubectl set image deployment/staging-harvis-ai-backend \
  backend=localhost:5000/jarvis-backend:staging-<old-sha> \
  -n ai-agents-staging
```

### Rollback Workflow (Production)
```bash
# Option A: Via Git tag (safest)
# Find previous version
git tag -l
# Create rollback tag
git tag v1.0.1 <previous-commit-sha>
git push origin v1.0.1
# Flux will auto-deploy v1.0.1

# Option B: Via kubectl (emergency only)
kubectl rollout undo deployment/harvis-ai-backend -n ai-agents
```

### Force Flux Reconciliation
```bash
# Force all reconciliations
flux reconcile source git harvis-ai-repo
flux reconcile image repository harvis-backend
flux reconcile image repository harvis-frontend
flux reconcile kustomization harvis-ai-staging
flux reconcile kustomization harvis-ai-prod

# Or reconcile specific environment
flux reconcile kustomization harvis-ai-staging --with-source
```

### Clean Up Old Images
```bash
# Check registry disk usage
du -sh /var/lib/registry  # On node running registry

# Clean up old images (manual)
curl -X DELETE http://localhost:5000/v2/jarvis-backend/manifests/<tag>

# Run registry garbage collection (configured in local-registry-config.yaml)
kubectl exec -n gitlab-runner <registry-pod> -- registry garbage-collect /etc/docker/registry/config.yml
```

## 🔐 Security Considerations

### Secrets Management
- ✅ GitHub secrets for GitLab webhook
- ✅ Kubernetes secrets for GitLab runner registration
- ✅ Flux secrets for Git repository access
- ⚠️ Consider using Sealed Secrets or External Secrets Operator for production

### Registry Security
- ⚠️ Current setup uses HTTP registry (`insecure: true`)
- 📝 For production: Enable TLS on registry
- 📝 Consider implementing image signing (Cosign)

### RBAC Permissions
- GitLab runners have cluster-admin access (required for Docker builds)
- Flux has limited permissions (only manages specific namespaces)
- Review and tighten RBAC as needed for production

### Network Security
- Registry is accessible only within cluster network
- Consider network policies to restrict access

## 📊 Monitoring and Observability

### GitHub Actions
- View workflows: `https://github.com/YOUR_USERNAME/YOUR_REPO/actions`
- Security tab: `https://github.com/YOUR_USERNAME/YOUR_REPO/security`

### GitLab CI
- Pipelines: `https://gitlab.com/YOUR_USERNAME/YOUR_REPO/-/pipelines`
- Runners: `https://gitlab.com/YOUR_USERNAME/YOUR_REPO/-/settings/ci_cd`

### FluxCD
```bash
# Flux dashboard (install flux-ui)
kubectl port-forward -n flux-system svc/flux-ui 8080:80

# Prometheus metrics (if configured)
kubectl port-forward -n flux-system svc/source-controller 8080:80
curl http://localhost:8080/metrics
```

### Kubernetes
```bash
# Resource usage
kubectl top nodes
kubectl top pods -n ai-agents
kubectl top pods -n ai-agents-staging

# Events
kubectl get events -n ai-agents --sort-by='.lastTimestamp'
kubectl get events -n ai-agents-staging --sort-by='.lastTimestamp'
```

## 📝 Maintenance Tasks

### Weekly
- Review SAST findings in GitHub Security tab
- Check for dependency updates (Dependabot)
- Review failed pipeline runs
- Check disk usage on registry node

### Monthly
- Update Flux to latest version
- Review and update GitLab Runner versions
- Clean up old Docker images
- Review and rotate secrets
- Test rollback procedures

### Quarterly
- Review and update RBAC permissions
- Audit security configurations
- Review and update documentation
- Test disaster recovery procedures

## 📚 Additional Resources

### Documentation
- [CICD_QUICK_START.md](./CICD_QUICK_START.md) - Quick 15-minute setup guide
- [CI_CD_IMPLEMENTATION_SUMMARY.md](./CI_CD_IMPLEMENTATION_SUMMARY.md) - Detailed implementation
- [docs/CI_CD_DEPLOYMENT_GUIDE.md](./docs/CI_CD_DEPLOYMENT_GUIDE.md) - Comprehensive deployment guide
- [k8s-manifests/ci-cd/README.md](./k8s-manifests/ci-cd/README.md) - GitLab Runner setup
- [k8s-manifests/flux-system/README.md](./k8s-manifests/flux-system/README.md) - FluxCD setup

### External Documentation
- [GitHub Actions](https://docs.github.com/en/actions)
- [GitLab CI/CD](https://docs.gitlab.com/ee/ci/)
- [FluxCD](https://fluxcd.io/docs/)
- [Kustomize](https://kustomize.io/)
- [K3s](https://docs.k3s.io/)

## ✅ Final Checklist

Before considering the setup complete:

### GitHub Setup
- [ ] `.github/workflows/` files committed to repository
- [ ] `GITLAB_WEBHOOK_URL` secret configured
- [ ] `GITLAB_TOKEN` secret configured
- [ ] Branch protection enabled on `main`
- [ ] Test SAST scan completed successfully
- [ ] Test GitLab trigger webhook working

### GitLab Setup
- [ ] GitLab project created/mirrored
- [ ] Pipeline trigger token generated
- [ ] `.gitlab-ci.yml` committed
- [ ] Test pipeline run successful
- [ ] Images pushed to localhost:5000

### GitLab Runners
- [ ] `gitlab-runner` namespace created
- [ ] Secrets updated with registration token
- [ ] Runners deployed to K8s (2 pods running)
- [ ] Runners registered in GitLab UI
- [ ] Tags assigned correctly (node1, node2, backend, frontend)
- [ ] Test build on each runner successful

### FluxCD
- [ ] Flux CLI installed
- [ ] Flux controllers installed on K8s
- [ ] `git-repository.yaml` URL updated
- [ ] Git credentials configured (for private repos)
- [ ] Deploy key added to GitHub (with write access)
- [ ] All Flux resources applied
- [ ] Image repositories scanning successfully
- [ ] Image policies configured correctly
- [ ] Test image detection working

### Environments
- [ ] Staging namespace created (`ai-agents-staging`)
- [ ] Production namespace created (`ai-agents`)
- [ ] Initial images pushed to registry
- [ ] Staging deployment successful
- [ ] Production deployment tested (with test tag)
- [ ] Applications accessible and functioning

### Integration Testing
- [ ] Feature branch → PR → SAST → Merge workflow tested
- [ ] GitLab CI triggered by GitHub Actions
- [ ] Images built and pushed successfully
- [ ] Flux detected new images
- [ ] Staging auto-deployed
- [ ] Version tag created and pushed
- [ ] Production auto-deployed
- [ ] Rollback tested (staging)
- [ ] Rollback tested (production)

### Monitoring
- [ ] GitHub Actions workflows monitored
- [ ] GitLab CI pipelines monitored
- [ ] Flux status checked regularly
- [ ] Kubernetes deployments monitored
- [ ] Application logs accessible

---

**Setup Date**: 2025-12-15
**Status**: Ready for deployment
**Maintained by**: Harvis AI Team

🎉 **Your CI/CD pipeline is ready!** Use this guide to review and apply the configuration.
