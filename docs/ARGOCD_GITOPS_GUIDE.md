# ArgoCD GitOps Guide - Harvis AI

**Date:** 2026-02-17  
**Setup:** GitHub (Main Repo) + GitLab (CI/DevOps) + ArgoCD (GitOps)

---

## Table of Contents

1. [Current Architecture Overview](#1-current-architecture-overview)
2. [Understanding the GitOps Flow](#2-understanding-the-gitops-flow)
3. [Current Setup - Local CI + ArgoCD](#3-current-setup---local-ci--argocd)
4. [Future Setup - GitLab CI Integration](#4-future-setup---gitlab-ci-integration)
5. [How to Update Applications](#5-how-to-update-applications)
6. [Creating New Applications](#6-creating-new-applications)
7. [Sync Strategy Options](#7-sync-strategy-options)
8. [Troubleshooting](#8-troubleshooting)
9. [Best Practices](#9-best-practices)

---

## 1. Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEVELOPMENT FLOW                          │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│   GitHub     │────▶│  Your Local  │────▶│  GitLab (CI)         │
│  (Main Repo) │     │   Machine    │     │  (Future Setup)      │
└──────────────┘     └──────────────┘     └──────────────────────┘
                            │                        │
                            │                        │
                            ▼                        ▼
                    ┌──────────────┐          ┌──────────────┐
                    │ Local CI     │          │ GitLab CI    │
                    │ Scripts      │          │ Pipelines    │
                    └──────────────┘          └──────────────┘
                            │                        │
                            └──────────┬─────────────┘
                                       │
                                       ▼
                            ┌──────────────────┐
                            │  Build Images    │
                            │  Push to Registry│
                            └──────────────────┘
                                       │
                                       ▼
                            ┌──────────────────┐
                            │ Update Manifests │
                            │ (YAML/Kustomize) │
                            └──────────────────┘
                                       │
                                       ▼
                            ┌──────────────────┐
                            │  ArgoCD (GitOps) │
                            │  Auto-Syncs K8s  │
                            └──────────────────┘
```

**Current Status:**
- ✅ GitHub: Main source code repository
- ✅ ArgoCD: Deployed and managing Harvis AI application
- ✅ Local CI: Your custom scripts building images
- ⏳ GitLab CI: Ready to integrate when you want

---

## 2. Understanding the GitOps Flow

### What is GitOps?

GitOps uses Git as the single source of truth for infrastructure and applications:

1. **Git Repo = Desired State**: Your YAML manifests in Git represent what SHOULD be running
2. **ArgoCD = Reconciliation**: ArgoCD constantly compares Git with the cluster
3. **Auto-Sync**: When Git changes, ArgoCD updates the cluster automatically

### How It Works for Harvis

```
GitHub Repo
├── front_end/                    # Frontend source code
├── python_back_end/             # Backend source code
├── k8s-manifests/               # THIS IS WHAT ARGOCD WATCHES
│   ├── overlays/
│   │   └── prod/
│   │       └── kustomization.yaml   # Image versions defined here
│   └── services/
│       ├── backend-rockyvms.yaml
│       ├── frontend.yaml
│       └── nginx.yaml
└── .gitlab-ci.yml              # CI pipeline (future)

When you update kustomization.yaml with new image tags:
→ ArgoCD detects the change within 3 minutes
→ ArgoCD applies the new manifests to the cluster
→ Pods restart with new images automatically
```

---

## 3. Current Setup - Local CI + ArgoCD

### Current Workflow

**Step 1: Build Images Locally**
```bash
# Your current script builds images
./ci_pipeline.sh
# Outputs:
#   dulc3/jarvis-frontend:v2.28.10
#   dulc3/jarvis-backend:v2.28.10
```

**Step 2: Update Manifests**
```bash
# Edit the kustomization file
nano k8s-manifests/overlays/prod/kustomization.yaml

# Change image tags:
images:
  - name: harvis-backend
    newName: dulc3/jarvis-backend
    newTag: v2.28.11  # ← Update this
  - name: harvis-frontend
    newName: dulc3/jarvis-frontend
    newTag: v2.28.11  # ← Update this
```

**Step 3: Commit & Push**
```bash
git add k8s-manifests/overlays/prod/kustomization.yaml
git commit -m "Update Harvis to v2.28.11"
git push origin main
```

**Step 4: ArgoCD Auto-Syncs**
- ArgoCD detects the change in Git
- Within 3 minutes, it syncs automatically
- Pods restart with new images
- Check UI: http://10.0.0.7:31179

### Current Application Structure

```yaml
# k8s-manifests/argocd/harvis-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: harvis-ai
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/dulc3/harvis-aidev.git
    targetRevision: HEAD
    path: k8s-manifests/overlays/prod
    kustomize:
      namePrefix: prod-
  destination:
    server: https://kubernetes.default.svc
    namespace: ai-agents
  syncPolicy:
    automated:
      prune: true        # Delete resources not in Git
      selfHeal: true     # Fix drift automatically
```

---

## 4. Future Setup - GitLab CI Integration

### Migration Plan: From Local CI to GitLab CI

**Phase 1: Current (Local CI)**
```bash
# You run this manually:
./ci_pipeline.sh → Builds images → Updates YAML → Git commit
```

**Phase 2: GitLab CI (Automated)**
```
Push to GitLab main branch
        ↓
GitLab CI Pipeline triggers automatically
        ↓
Stages:
  1. Build (build Docker images)
  2. Test (run tests)
  3. Push (push to registry)
  4. Update Manifests (auto-update kustomization.yaml)
  5. Commit & Push (commit back to repo)
        ↓
ArgoCD detects change
        ↓
Auto-deploys to K8s
```

### GitLab CI Pipeline Structure

```yaml
# .gitlab-ci.yml (create this file)
stages:
  - build
  - test
  - push
  - gitops

variables:
  DOCKER_REGISTRY: registry.gitlab.com
  FRONTEND_IMAGE: $DOCKER_REGISTRY/$CI_PROJECT_PATH/frontend
  BACKEND_IMAGE: $DOCKER_REGISTRY/$CI_PROJECT_PATH/backend

build-frontend:
  stage: build
  script:
    - docker build -t $FRONTEND_IMAGE:$CI_COMMIT_SHA ./front_end/jfrontend
    - docker tag $FRONTEND_IMAGE:$CI_COMMIT_SHA $FRONTEND_IMAGE:latest

test:
  stage: test
  script:
    - npm test  # or pytest, etc.

push-images:
  stage: push
  script:
    - docker push $FRONTEND_IMAGE:$CI_COMMIT_SHA
    - docker push $BACKEND_IMAGE:$CI_COMMIT_SHA

gitops-update:
  stage: gitops
  script:
    # Auto-update kustomization.yaml with new image tags
    - sed -i "s/newTag: .*/newTag: $CI_COMMIT_SHA/" k8s-manifests/overlays/prod/kustomization.yaml
    - git add k8s-manifests/overlays/prod/kustomization.yaml
    - git commit -m "Update images to $CI_COMMIT_SHA [ci skip]"
    - git push https://oauth2:$GIT_TOKEN@github.com/dulc3/harvis-aidev.git HEAD:main
```

### Setting Up GitLab CI

**Step 1: Mirror Repository**
```bash
# In GitLab, go to: Project → Settings → Repository → Mirroring
# Add mirror from GitHub:
Git repository URL: https://github.com/dulc3/harvis-aidev.git
Password: Your GitHub personal access token
```

**Step 2: Add GitLab Runner**
```bash
# Your runners are already deployed on Raspberry Pis!
kubectl get pods -n gitlab-runner
# They just need to be registered with your GitLab instance
```

**Step 3: Create .gitlab-ci.yml**
```bash
# Copy the pipeline file I provided above
nano .gitlab-ci.yml
git add .gitlab-ci.yml
git commit -m "Add GitLab CI pipeline"
git push
```

**Step 4: Configure Secrets**
In GitLab: Project → Settings → CI/CD → Variables
- `DOCKER_REGISTRY_TOKEN`: For pushing images
- `GIT_TOKEN`: For pushing back to GitHub
- `KUBECONFIG`: If you want GitLab to deploy directly

---

## 5. How to Update Applications

### Method 1: Manual Update (Current)

```bash
# 1. Build new images locally
./ci_pipeline.sh
# Tags: v2.28.11

# 2. Update the kustomization file
sed -i 's/v2.28.10/v2.28.11/g' k8s-manifests/overlays/prod/kustomization.yaml

# 3. Commit and push
git add k8s-manifests/overlays/prod/kustomization.yaml
git commit -m "Bump version to v2.28.11"
git push origin main

# 4. Watch ArgoCD sync
kubectl get application harvis-ai -n argocd -w
```

### Method 2: Via ArgoCD UI (Emergency Use)

```bash
# ONLY for hotfixes - ArgoCD will self-heal back to Git state
# 1. Go to: http://10.0.0.7:31179
# 2. Click harvis-ai application
# 3. Click "Sync" button
# 4. For manual override: "App Details" → "Parameters" → Edit
```

### Method 3: Automated via GitLab CI (Future)

```bash
# Just push to main branch - everything happens automatically!
git add .
git commit -m "New feature"
git push origin main

# GitLab CI:
# 1. Builds images
# 2. Updates kustomization.yaml
# 3. Commits back
# 4. ArgoCD deploys
```

---

## 6. Creating New Applications

### Template for New Microservices

**Step 1: Create Deployment Manifest**
```yaml
# k8s-manifests/services/my-new-service.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-new-service
  namespace: ai-agents
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-new-service
  template:
    metadata:
      labels:
        app: my-new-service
    spec:
      nodeSelector:
        kubernetes.io/hostname: rocky1vm.local  # Choose your node
      containers:
        - name: service
          image: dulc3/my-new-service:v1.0.0
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: my-new-service
  namespace: ai-agents
spec:
  selector:
    app: my-new-service
  ports:
    - port: 80
      targetPort: 8080
```

**Step 2: Add to Kustomization**
```yaml
# k8s-manifests/overlays/prod/kustomization.yaml
resources:
  - ../../services/backend-rockyvms.yaml
  - ../../services/frontend.yaml
  - ../../services/nginx.yaml
  - ../../services/my-new-service.yaml  # ← Add this

images:
  - name: my-new-service
    newName: dulc3/my-new-service
    newTag: v1.0.0
```

**Step 3: Create ArgoCD Application**
```bash
# Option A: Via kubectl
cat << EOF | kubectl apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-new-service
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/dulc3/harvis-aidev.git
    targetRevision: HEAD
    path: k8s-manifests/services
  destination:
    server: https://kubernetes.default.svc
    namespace: ai-agents
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF

# Option B: Via ArgoCD UI
# 1. Click "+ New App"
# 2. Use settings from above
```

### Application Types Reference

```yaml
# Type 1: Single Service (Simple)
spec:
  source:
    path: k8s-manifests/services/my-service.yaml

# Type 2: Kustomize Overlay (Recommended)
spec:
  source:
    path: k8s-manifests/overlays/production
    kustomize:
      namePrefix: prod-

# Type 3: Helm Chart
spec:
  source:
    chart: my-chart
    repoURL: https://charts.example.com
    targetRevision: 1.0.0
    helm:
      values: |
        replicaCount: 3

# Type 4: Multiple Apps (App of Apps)
spec:
  source:
    path: k8s-manifests/argocd/apps
    directory:
      recurse: true
```

---

## 7. Sync Strategy Options

### Auto-Sync (Current Setup)

```yaml
syncPolicy:
  automated:
    prune: true      # Delete resources removed from Git
    selfHeal: true   # Fix manual changes to cluster
  syncOptions:
    - CreateNamespace=true
```

**Pros:**
- ✅ Fully automated
- ✅ No manual intervention
- ✅ Drift detection

**Cons:**
- ⚠️ Accidental deletes in Git = production down
- ⚠️ No approval gates

### Manual Sync (Safe for Production)

```yaml
syncPolicy:
  automated:
    prune: false     # Don't auto-delete
    selfHeal: false  # Don't fix drift automatically
```

**Usage:**
1. Push changes to Git
2. Review in ArgoCD UI
3. Click "Sync" manually

### Sync Waves (Ordered Deployment)

```yaml
# Add to your manifests
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "1"  # Deploy first (databases)
    # argocd.argoproj.io/sync-wave: "2"  # Deploy second (backend)
    # argocd.argoproj.io/sync-wave: "3"  # Deploy third (frontend)
```

### Health Checks

```yaml
# Add to Deployment for better health monitoring
spec:
  template:
    metadata:
      annotations:
        argocd.argoproj.io/hook: Sync
        argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

---

## 8. Troubleshooting

### Issue: ArgoCD Not Syncing

```bash
# Check application status
kubectl get application harvis-ai -n argocd -o yaml

# Check for errors
kubectl describe application harvis-ai -n argocd

# Force sync
argocd app sync harvis-ai --force

# Check pod logs
kubectl logs -n argocd deployment/argocd-application-controller
```

### Issue: Images Not Updating

```bash
# Check if kustomization is correct
kustomize build k8s-manifests/overlays/prod | grep image

# Verify ArgoCD sees the change
kubectl exec -n argocd deployment/argocd-repo-server -- \
  git -C /tmp/https:__github.com_dulc3_harvis-aidev.git log -1
```

### Issue: Sync Failed

```bash
# Check sync status
kubectl get application harvis-ai -n argocd \
  -o jsonpath='{.status.operationState.phase}'

# View operation details
kubectl get application harvis-ai -n argocd \
  -o jsonpath='{.status.operationState.message}'

# Retry sync
kubectl patch application harvis-ai -n argocd \
  --type merge -p '{"operation":{"sync":{}}}'
```

### Common Commands

```bash
# List all applications
kubectl get applications -n argocd

# Get application details
argocd app get harvis-ai

# View application diff (what will change)
argocd app diff harvis-ai

# Rollback to previous version
argocd app rollback harvis-ai 0

# Delete application (keeps resources)
kubectl delete application harvis-ai -n argocd

# Delete application AND resources
argocd app delete harvis-ai --cascade
```

---

## 9. Best Practices

### 1. Repository Structure

```
harvis-aidev/
├── .github/                  # GitHub Actions (if using)
├── .gitlab-ci.yml           # GitLab CI pipeline
├── front_end/               # Frontend source
├── python_back_end/         # Backend source
├── k8s-manifests/
│   ├── argocd/             # ArgoCD applications
│   │   ├── harvis-application.yaml
│   │   └── other-apps/
│   ├── base/               # Base manifests (don't edit directly)
│   │   ├── backend.yaml
│   │   └── frontend.yaml
│   ├── overlays/           # Environment-specific
│   │   ├── dev/
│   │   ├── staging/
│   │   └── prod/           # Production configs
│   │       └── kustomization.yaml
│   └── services/           # Individual services
│       ├── backend-rockyvms.yaml
│       └── frontend.yaml
└── scripts/                # CI/CD scripts
    └── ci_pipeline.sh
```

### 2. Image Tagging Strategy

```yaml
# ❌ BAD - Don't use "latest"
image: dulc3/jarvis-backend:latest

# ✅ GOOD - Use specific versions
image: dulc3/jarvis-backend:v2.28.10

# ✅ BETTER - Use commit SHA for traceability
image: dulc3/jarvis-backend:a1b2c3d

# ✅ BEST - Use semantic versioning + metadata
image: dulc3/jarvis-backend:v2.28.10-14-gabcdef
```

### 3. Git Workflow

```
main branch (production)
     ↑
     │  PR: Update kustomization.yaml
     │  ArgoCD auto-deploys
     │
feature/new-feature
     ↑
     │  Development
     │  Local testing
```

### 4. Monitoring ArgoCD

```bash
# Add these to your monitoring stack

# Check sync status
kubectl get applications -n argocd -o json | jq '.items[] | {name: .metadata.name, sync: .status.sync.status, health: .status.health.status}'

# Alert when apps are not synced
# (Add to Prometheus/Grafana alerts)
```

### 5. Security Best Practices

```yaml
# Use read-only tokens for ArgoCD
# Limit ArgoCD to specific paths
spec:
  source:
    path: k8s-manifests/overlays/prod  # Only this path

# Enable audit logging
# Rotate Git tokens regularly
# Use separate repos for sensitive configs (Sealed Secrets)
```

---

## Quick Reference Card

| Task | Command |
|------|---------|
| **Access ArgoCD UI** | http://10.0.0.7:31179 |
| **Get admin password** | `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" \| base64 -d` |
| **List applications** | `kubectl get applications -n argocd` |
| **Sync application** | `argocd app sync harvis-ai` |
| **Check status** | `kubectl get application harvis-ai -n argocd` |
| **Update images** | Edit `k8s-manifests/overlays/prod/kustomization.yaml` |
| **Force refresh** | `argocd app get harvis-ai --hard-refresh` |
| **View diff** | `argocd app diff harvis-ai` |
| **Rollback** | `argocd app rollback harvis-ai 0` |

---

## Next Steps

1. **Immediate**: Test updating to v2.28.11 manually
2. **This Week**: Set up GitLab mirror and runners
3. **Next Sprint**: Create .gitlab-ci.yml for automated builds
4. **Future**: Add staging environment with automated testing

---

**Questions?** Check the ArgoCD docs: https://argo-cd.readthedocs.io/

**Repository**: https://github.com/dulc3/harvis-aidev

**ArgoCD URL**: http://10.0.0.7:31179

---

*Last Updated: 2026-02-17*
*ArgoCD Version: v2.x*
*Kubernetes: v1.33.5+k3s1*
