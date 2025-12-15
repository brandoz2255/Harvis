# Harvis AI - CI/CD Quick Start Guide

## 🚀 Quick Overview

This project now has a complete CI/CD pipeline:

```
GitHub (SAST) → GitLab CI (Build) → Local Registry → FluxCD (Deploy) → Kubernetes
```

## 📋 What Was Created

### 1. GitHub Actions Workflows
- ✅ `.github/workflows/sast-security-scan.yml` - Security scanning (CodeQL, Semgrep, Trivy, etc.)
- ✅ `.github/workflows/trigger-gitlab-ci.yml` - Triggers GitLab CI on main branch push

### 2. GitLab CI Pipeline
- ✅ `.gitlab-ci.yml` - Build and push Docker images to localhost:5000
- ✅ `k8s-manifests/ci-cd/` - GitLab Runner deployment on K8s (2 pods, one per node)

### 3. FluxCD GitOps
- ✅ `k8s-manifests/flux-system/` - FluxCD configuration for auto-deployment
- ✅ Image automation: Scans localhost:5000 for new images and auto-deploys

### 4. Kustomize Overlays
- ✅ `k8s-manifests/overlays/staging/` - Staging environment configuration
- ✅ `k8s-manifests/overlays/prod/` - Production environment configuration

### 5. Development Environment
- ✅ `docker-compose.dev.yml` - Local development with hot-reload

### 6. Documentation
- ✅ `docs/CI_CD_DEPLOYMENT_GUIDE.md` - Complete deployment guide
- ✅ `k8s-manifests/ci-cd/README.md` - GitLab Runner setup
- ✅ `k8s-manifests/flux-system/README.md` - FluxCD setup

## 🔧 Prerequisites

Before starting, ensure you have:

- ✅ K3s cluster running (your 2-node setup)
- ✅ kubectl configured
- ✅ GitHub repository with your code
- ✅ GitLab account (gitlab.com or self-hosted)
- ✅ Local Docker registry at localhost:5000 (already running ✅)
- ✅ Git installed

## 🏃 Quick Setup (15 minutes)

### Step 1: Configure GitHub Secrets (2 min)

GitHub Repo → Settings → Secrets and variables → Actions

Add:
```
GITLAB_WEBHOOK_URL=https://gitlab.com/api/v4/projects/YOUR_PROJECT_ID/trigger/pipeline
GITLAB_TOKEN=<get from GitLab: Settings → CI/CD → Pipeline triggers>
```

### Step 2: Deploy GitLab Runners to K8s (5 min)

```bash
# Update registration token in secrets file
nano k8s-manifests/ci-cd/gitlab-runner-secrets.yaml

# Deploy runners
kubectl apply -f k8s-manifests/ci-cd/

# Verify
kubectl get pods -n gitlab-runner
```

### Step 3: Install FluxCD (5 min)

```bash
# Install Flux CLI
curl -s https://fluxcd.io/install.sh | sudo bash

# Install Flux on cluster
flux install --components-extra=image-reflector-controller,image-automation-controller

# Update Git repo URL
nano k8s-manifests/flux-system/git-repository.yaml
# Change: url: https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Apply Flux configuration
kubectl apply -f k8s-manifests/flux-system/
```

### Step 4: Verify Everything (3 min)

```bash
# Check GitLab Runners
kubectl get pods -n gitlab-runner

# Check Flux
flux check
flux get all

# Check registry
curl http://localhost:5000/v2/_catalog
```

## 🎯 How to Use

### Development Workflow

```bash
# Start local dev environment
docker-compose -f docker-compose.dev.yml up

# Make changes, test locally
# Push to feature branch
git checkout -b feature/my-feature
git add .
git commit -m "feat: Add new feature"
git push origin feature/my-feature

# Create PR on GitHub
# GitHub Actions runs SAST scans automatically
```

### Deploy to Staging

```bash
# Merge PR to main (after SAST passes)
# Automatic flow:
# 1. GitHub Actions triggers GitLab CI
# 2. GitLab CI builds images (staging-<sha>)
# 3. Flux detects new images
# 4. Auto-deploys to ai-agents-staging namespace

# Monitor staging deployment
kubectl get pods -n ai-agents-staging
flux get kustomizations
```

### Deploy to Production

```bash
# Create version tag
git tag v1.0.0
git push origin v1.0.0

# Automatic flow:
# 1. GitLab CI builds images (v1.0.0)
# 2. Flux detects version tag
# 3. Auto-deploys to ai-agents namespace (production)

# Monitor production deployment
kubectl get pods -n ai-agents
kubectl rollout status deployment/harvis-ai-backend -n ai-agents
```

## 🔍 Monitoring Commands

```bash
# GitHub Actions
# Visit: https://github.com/YOUR_USERNAME/YOUR_REPO/actions

# GitLab CI
# Visit: https://gitlab.com/YOUR_USERNAME/YOUR_REPO/-/pipelines

# Flux Status
flux get all
flux get kustomizations
flux get images all

# Kubernetes
kubectl get deployments -n ai-agents
kubectl get pods -n ai-agents
kubectl logs -n ai-agents deployment/harvis-ai-backend -f
```

## 🚨 Common Issues & Quick Fixes

### Issue: GitLab CI not triggering
**Fix:**
```bash
# Check GitHub secrets are set correctly
# Test trigger manually:
curl -X POST \
  -F "token=YOUR_GITLAB_TOKEN" \
  -F "ref=main" \
  "https://gitlab.com/api/v4/projects/PROJECT_ID/trigger/pipeline"
```

### Issue: Flux not detecting images
**Fix:**
```bash
# Force image scan
flux reconcile image repository harvis-backend --with-source

# Check registry connectivity
curl http://localhost:5000/v2/_catalog
```

### Issue: Pods not updating
**Fix:**
```bash
# Force Flux reconciliation
flux reconcile kustomization harvis-ai-staging --with-source

# Check pod image
kubectl describe pod -n ai-agents-staging <pod-name> | grep Image
```

## 📊 Architecture Diagram

```
┌──────────────┐
│   Developer  │
└──────┬───────┘
       │ git push
       ▼
┌──────────────────┐
│  GitHub (Code)   │◄─────────────┐
│  - SAST Scans    │              │ (commits updates)
└────────┬─────────┘              │
         │ webhook trigger        │
         ▼                         │
┌──────────────────┐              │
│ GitLab CI (K8s)  │              │
│  - Node1: Backend│              │
│  - Node2: Frontend│             │
└────────┬─────────┘              │
         │ docker push            │
         ▼                         │
┌──────────────────┐              │
│localhost:5000    │              │
│ Container Registry│             │
└────────┬─────────┘              │
         │ image scan             │
         ▼                         │
┌──────────────────┐              │
│  FluxCD (K8s)    │──────────────┘
│  - Image automation
│  - Auto-deploy   │
└────────┬─────────┘
         │
         ▼
┌────────────────────────────┐
│  Kubernetes Cluster        │
│  ┌──────────────────────┐  │
│  │ Staging (namespace)  │  │
│  │ - ai-agents-staging  │  │
│  └──────────────────────┘  │
│  ┌──────────────────────┐  │
│  │ Production (namespace│  │
│  │ - ai-agents          │  │
│  └──────────────────────┘  │
└────────────────────────────┘
```

## 🎓 Learning Resources

- **Full Documentation**: `docs/CI_CD_DEPLOYMENT_GUIDE.md`
- **GitLab Runner Setup**: `k8s-manifests/ci-cd/README.md`
- **FluxCD Setup**: `k8s-manifests/flux-system/README.md`

## ✅ Checklist

Before going live, ensure:

- [ ] GitHub secrets configured
- [ ] GitLab runners deployed and registered
- [ ] FluxCD installed and configured
- [ ] Git repository URL updated in Flux config
- [ ] Initial images pushed to localhost:5000
- [ ] Staging environment deployed and tested
- [ ] SAST scans passing on main branch
- [ ] Production deployment tested (with test tag)
- [ ] Rollback procedure tested
- [ ] Monitoring and logging configured

## 🔐 Security Notes

- ✅ SAST scans on all PRs (CodeQL, Semgrep, Trivy, etc.)
- ✅ Secrets stored in Kubernetes secrets (not in code)
- ✅ Branch protection enabled on main
- ✅ Container image scanning
- ✅ Dockerfile linting
- ⚠️ Consider enabling registry TLS for production

## 🚀 Next Steps

1. **Configure GitHub Secrets** (required)
2. **Deploy GitLab Runners** (required)
3. **Install FluxCD** (required)
4. **Test staging deployment** (recommended)
5. **Create first production tag** (when ready)

## 📞 Support

Questions? Check:
1. This quick start guide
2. Full documentation in `docs/CI_CD_DEPLOYMENT_GUIDE.md`
3. Component-specific READMEs
4. GitHub Issues for troubleshooting

---

**Happy Deploying! 🎉**
