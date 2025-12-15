# Harvis AI - Complete CI/CD Deployment Guide

## Overview

This guide covers the complete CI/CD pipeline for Harvis AI, from code commit to production deployment using GitHub Actions, GitLab CI, and FluxCD.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CI/CD Pipeline Flow                           │
└─────────────────────────────────────────────────────────────────────┘

1. Developer Workflow
   ├─ Code changes pushed to GitHub (feature branch)
   ├─ Create Pull Request to 'main'
   └─ GitHub Actions runs SAST security scans
      ├─ CodeQL (code analysis)
      ├─ Semgrep (vulnerability scanning)
      ├─ Trivy (filesystem scanning)
      ├─ Python Safety (dependency check)
      ├─ NPM Audit (dependency check)
      ├─ Hadolint (Dockerfile linting)
      └─ Gitleaks (secret scanning)

2. Main Branch Merge (After SAST Passes)
   ├─ GitHub Actions triggers GitLab CI webhook
   └─ GitLab CI pipeline starts

3. GitLab CI Build Stage
   ├─ Backend build job (runs on node1 - node-gpu-1)
   │  ├─ Docker build: python_back_end/Dockerfile
   │  └─ Tags: staging-<sha>, staging-latest, build-<id>
   └─ Frontend build job (runs on node2 - node-gpu-2)
      ├─ Docker build: front_end/jfrontend/Dockerfile
      └─ Tags: staging-<sha>, staging-latest, build-<id>

4. GitLab CI Push Stage
   ├─ Push backend images to localhost:5000/jarvis-backend
   ├─ Push frontend images to localhost:5000/jarvis-frontend
   └─ If main branch: Also tag and push as 'latest'

5. Flux Image Automation
   ├─ ImageRepository scans localhost:5000 every minute
   ├─ ImagePolicy selects appropriate tags:
   │  ├─ Staging: staging-latest (auto-deploy)
   │  └─ Production: v*.*.* (semver tags, auto-deploy)
   ├─ ImageUpdateAutomation updates kustomization.yaml
   └─ Commits changes back to GitHub

6. Flux Kustomization Reconciliation
   ├─ Staging: Updates ai-agents-staging namespace
   ├─ Production: Updates ai-agents namespace
   └─ K8s deploys new pods with updated images

7. Deployment Complete
   ├─ Health checks verify pod readiness
   └─ Application running with new version
```

## Environment Strategy

### Development (docker-compose)
- **Purpose**: Local development and testing
- **Location**: Developer's machine
- **Configuration**: `docker-compose.dev.yml`
- **Image Source**: Local builds or localhost:5000/jarvis-*:dev-latest
- **Features**:
  - Hot-reload enabled
  - Debug logging
  - No GPU constraints
  - Fast iteration cycle

**Start dev environment:**
```bash
docker-compose -f docker-compose.dev.yml up
```

### Staging (Kubernetes)
- **Purpose**: Pre-production testing
- **Namespace**: `ai-agents-staging`
- **Configuration**: `k8s-manifests/overlays/staging/`
- **Image Tags**: `staging-latest`, `staging-<git-sha>`
- **Auto-Deploy**: Yes (on every main branch push)
- **Features**:
  - Reduced resource limits
  - Debug logging
  - Quick feedback on changes
  - Separate from production data

**Deploy staging:**
```bash
# Apply staging overlay
kubectl apply -k k8s-manifests/overlays/staging/

# Or let Flux auto-deploy after image push
```

### Production (Kubernetes)
- **Purpose**: Live production environment
- **Namespace**: `ai-agents`
- **Configuration**: `k8s-manifests/overlays/prod/`
- **Image Tags**: `latest`, `v1.0.0`, `v1.0.1` (semver)
- **Auto-Deploy**: Yes (on version tags) or manual
- **Features**:
  - Full resource allocation
  - Info-level logging
  - Production monitoring
  - High availability

**Deploy production:**
```bash
# Option 1: Automatic (create version tag)
git tag v1.0.0
git push origin v1.0.0
# GitLab CI builds and tags as v1.0.0
# Flux auto-deploys to production

# Option 2: Manual (apply overlay)
kubectl apply -k k8s-manifests/overlays/prod/
```

## Setup Instructions

### Prerequisites

- ✅ Kubernetes cluster (K3s) running
- ✅ kubectl configured
- ✅ GitHub repository with code
- ✅ GitLab account (gitlab.com or self-hosted)
- ✅ Local Docker registry at localhost:5000
- ✅ Git installed locally

### Step 1: GitHub Configuration

#### 1.1 Add GitHub Secrets

Navigate to: **GitHub Repo > Settings > Secrets and variables > Actions**

Add the following secrets:

```
GITLAB_WEBHOOK_URL=https://gitlab.com/api/v4/projects/YOUR_PROJECT_ID/trigger/pipeline
GITLAB_TOKEN=<your-gitlab-pipeline-trigger-token>
```

To get GitLab trigger token:
1. Go to GitLab Project > Settings > CI/CD > Pipeline triggers
2. Create a new trigger token
3. Copy the token and webhook URL

#### 1.2 Enable GitHub Actions

GitHub Actions are automatically enabled from the `.github/workflows/` directory:
- `sast-security-scan.yml`: Runs security scans on PRs and main
- `trigger-gitlab-ci.yml`: Triggers GitLab CI on main branch push

#### 1.3 Branch Protection (Recommended)

GitHub Repo > Settings > Branches > Add rule for `main`:
- ✅ Require pull request reviews before merging
- ✅ Require status checks to pass (SAST scans)
- ✅ Require branches to be up to date before merging

### Step 2: GitLab CI Configuration

#### 2.1 Create GitLab Project

Option A: Mirror GitHub repository to GitLab
```bash
# In GitLab: New Project > Run CI/CD for external repository
# Connect to GitHub and select your repository
```

Option B: Manual push to GitLab
```bash
git remote add gitlab git@gitlab.com:YOUR_USERNAME/harvis-ai.git
git push gitlab main
```

#### 2.2 Deploy GitLab Runners to K8s

```bash
# Update GitLab registration token in secrets
nano k8s-manifests/ci-cd/gitlab-runner-secrets.yaml

# Apply GitLab Runner manifests
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-namespace.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-secrets.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-config.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-rbac.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-deployment.yaml

# Verify runners are running
kubectl get pods -n gitlab-runner

# Check runner logs
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1
kubectl logs -n gitlab-runner deployment/gitlab-runner-node2
```

#### 2.3 Verify Runners in GitLab

GitLab Project > Settings > CI/CD > Runners

You should see:
- `harvis-k8s-node1-backend` (tags: node1, backend, gpu, docker)
- `harvis-k8s-node2-frontend` (tags: node2, frontend, docker)

### Step 3: FluxCD Installation

#### 3.1 Install Flux CLI

```bash
curl -s https://fluxcd.io/install.sh | sudo bash
flux --version
```

#### 3.2 Bootstrap Flux

```bash
# Check cluster prerequisites
flux check --pre

# Install Flux with image automation
flux install \
  --components-extra=image-reflector-controller,image-automation-controller

# Verify installation
flux check
kubectl get pods -n flux-system
```

#### 3.3 Configure Flux Git Repository

Edit `k8s-manifests/flux-system/git-repository.yaml`:
```yaml
spec:
  url: https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

Apply Flux configuration:
```bash
kubectl apply -f k8s-manifests/flux-system/namespace.yaml
kubectl apply -f k8s-manifests/flux-system/git-repository.yaml
kubectl apply -f k8s-manifests/flux-system/image-registry.yaml
kubectl apply -f k8s-manifests/flux-system/image-update-automation.yaml
kubectl apply -f k8s-manifests/flux-system/kustomization-staging.yaml
kubectl apply -f k8s-manifests/flux-system/kustomization-prod.yaml
```

#### 3.4 Verify Flux Resources

```bash
# Check all Flux resources
flux get all

# Check image repositories
flux get images repository

# Check kustomizations
flux get kustomizations

# Force reconciliation
flux reconcile source git harvis-ai-repo
flux reconcile kustomization harvis-ai-staging
```

### Step 4: Local Registry Configuration

#### 4.1 Verify Registry is Running

```bash
docker ps | grep registry
# Should show: registry:2 on port 5000

# Test registry access
curl http://localhost:5000/v2/_catalog
```

#### 4.2 Configure Insecure Registry (if needed)

On each K8s node, add to `/etc/docker/daemon.json`:
```json
{
  "insecure-registries": ["localhost:5000"]
}
```

Restart Docker:
```bash
sudo systemctl restart docker
```

### Step 5: Initial Image Push

Build and push initial images to registry:

```bash
# Backend
cd python_back_end
docker build -t localhost:5000/jarvis-backend:latest .
docker push localhost:5000/jarvis-backend:latest

# Frontend
cd ../front_end/jfrontend
docker build -t localhost:5000/jarvis-frontend:latest .
docker push localhost:5000/jarvis-frontend:latest

# Verify images in registry
curl http://localhost:5000/v2/_catalog
curl http://localhost:5000/v2/jarvis-backend/tags/list
curl http://localhost:5000/v2/jarvis-frontend/tags/list
```

## Workflow Examples

### Example 1: Development to Staging

```bash
# 1. Create feature branch
git checkout -b feature/new-feature

# 2. Make changes and commit
git add .
git commit -m "feat: Add new feature"

# 3. Push and create PR
git push origin feature/new-feature

# 4. GitHub Actions runs SAST scans on PR
# - Check Actions tab for scan results

# 5. After review, merge to main
# - SAST scans run again
# - On success, GitHub Actions triggers GitLab CI

# 6. GitLab CI builds images
# - Backend: localhost:5000/jarvis-backend:staging-abc123
# - Frontend: localhost:5000/jarvis-frontend:staging-abc123

# 7. Flux detects new images
# - Updates staging kustomization
# - Deploys to ai-agents-staging namespace

# 8. Verify staging deployment
kubectl get pods -n ai-agents-staging
kubectl logs -n ai-agents-staging deployment/staging-harvis-ai-backend
```

### Example 2: Staging to Production

```bash
# 1. Test staging environment thoroughly
kubectl exec -n ai-agents-staging deployment/staging-harvis-ai-backend -- curl localhost:8000/docs

# 2. Create version tag for production
git tag v1.0.0
git push origin v1.0.0

# 3. GitLab CI detects tag
# - Builds images with tag v1.0.0
# - localhost:5000/jarvis-backend:v1.0.0
# - localhost:5000/jarvis-frontend:v1.0.0

# 4. Flux detects production version
# - ImagePolicy selects v1.0.0 (semver)
# - Updates production kustomization
# - Deploys to ai-agents namespace

# 5. Verify production deployment
kubectl get pods -n ai-agents
kubectl rollout status deployment/harvis-ai-backend -n ai-agents
```

### Example 3: Hotfix to Production

```bash
# 1. Create hotfix branch from production tag
git checkout -b hotfix/critical-fix v1.0.0

# 2. Apply fix and commit
git add .
git commit -m "fix: Critical security fix"

# 3. Merge to main via PR
# - SAST scans run
# - After merge, builds staging images

# 4. Create hotfix version tag
git tag v1.0.1
git push origin v1.0.1

# 5. GitLab CI builds v1.0.1
# 6. Flux auto-deploys to production
# 7. Verify fix is deployed

kubectl describe pod -n ai-agents -l app.kubernetes.io/component=backend
```

## Monitoring and Observability

### GitHub Actions

View workflow runs:
- GitHub Repo > Actions tab
- Click on workflow run to see details
- Check individual job logs

### GitLab CI

View pipeline status:
- GitLab Project > CI/CD > Pipelines
- Click on pipeline to see job details
- View job logs for build output

### FluxCD

```bash
# View all Flux resources
flux get all

# Check reconciliation status
flux get kustomizations

# View image automation status
flux get images all

# Force reconciliation
flux reconcile kustomization harvis-ai-staging --with-source

# View Flux controller logs
kubectl logs -n flux-system deployment/source-controller -f
kubectl logs -n flux-system deployment/kustomize-controller -f
kubectl logs -n flux-system deployment/image-reflector-controller -f
```

### Kubernetes

```bash
# View deployments
kubectl get deployments -n ai-agents
kubectl get deployments -n ai-agents-staging

# View pods
kubectl get pods -n ai-agents
kubectl get pods -n ai-agents-staging

# View pod logs
kubectl logs -n ai-agents deployment/harvis-ai-backend -f

# Describe pod for troubleshooting
kubectl describe pod -n ai-agents <pod-name>

# View events
kubectl get events -n ai-agents --sort-by='.lastTimestamp'
```

## Troubleshooting

### SAST Scans Failing

```bash
# Check GitHub Actions logs
# GitHub Repo > Actions > Click failing workflow

# Common issues:
# - CodeQL: Language detection issues (check languages in matrix)
# - Semgrep: High severity findings (review and fix)
# - Gitleaks: Secrets detected (remove and rotate)
# - Safety/NPM: Vulnerable dependencies (update)
```

### GitLab CI Not Triggering

```bash
# Check GitHub webhook delivery
# GitHub Repo > Settings > Webhooks (if using webhook method)

# Check GitLab trigger token
# GitLab Project > Settings > CI/CD > Pipeline triggers

# Verify secrets in GitHub
# GitHub Repo > Settings > Secrets > Actions

# Test trigger manually
curl -X POST \
  -F "token=YOUR_GITLAB_TOKEN" \
  -F "ref=main" \
  "https://gitlab.com/api/v4/projects/PROJECT_ID/trigger/pipeline"
```

### GitLab Runner Issues

```bash
# Check runner status
kubectl get pods -n gitlab-runner
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1

# Common issues:
# - Registration failed: Check token in secrets
# - Docker socket permission denied: Verify volume mount
# - Jobs not running: Check runner tags match job tags

# Re-register runner
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -it -- \
  gitlab-runner register --help
```

### Flux Not Detecting Images

```bash
# Check image repository status
flux get images repository

# Force image scan
flux reconcile image repository harvis-backend --with-source

# Check registry connectivity from Flux
kubectl run -n flux-system curl-test --image=curlimages/curl --rm -it -- \
  curl -v http://localhost:5000/v2/_catalog

# Verify insecure registry is allowed
# Check image-registry.yaml has: insecure: true
```

### Deployment Not Updating

```bash
# Check kustomization status
flux get kustomizations

# View reconciliation errors
kubectl describe kustomization -n flux-system harvis-ai-staging

# Force reconciliation
flux reconcile kustomization harvis-ai-staging --with-source

# Check image policy
flux get images policy
kubectl describe imagepolicy -n flux-system harvis-backend-staging

# Verify image tags in registry
curl http://localhost:5000/v2/jarvis-backend/tags/list
```

## Rollback Procedures

### Rollback Staging

```bash
# Option 1: Roll back to previous deployment
kubectl rollout undo deployment/staging-harvis-ai-backend -n ai-agents-staging

# Option 2: Deploy specific image tag
kubectl set image deployment/staging-harvis-ai-backend \
  harvis-backend=localhost:5000/jarvis-backend:staging-abc123 \
  -n ai-agents-staging

# Verify rollback
kubectl rollout status deployment/staging-harvis-ai-backend -n ai-agents-staging
```

### Rollback Production

```bash
# Option 1: Roll back to previous deployment
kubectl rollout undo deployment/harvis-ai-backend -n ai-agents

# Option 2: Tag previous version and let Flux deploy
git tag v1.0.2  # Previous stable version
git push origin v1.0.2
# Flux will detect and deploy

# Option 3: Manual image update
kubectl set image deployment/harvis-ai-backend \
  harvis-backend=localhost:5000/jarvis-backend:v1.0.0 \
  -n ai-agents
```

## Security Considerations

### SAST Scanning
- All PRs require SAST scans to pass
- Security findings must be addressed before merge
- Regular dependency updates

### Image Security
- Container image scanning with Trivy
- Dockerfile linting with Hadolint
- No secrets in images (use Kubernetes secrets)

### Access Control
- GitHub: Branch protection rules
- GitLab: Runner access controls
- Kubernetes: RBAC for Flux and runners

### Registry Security
- Consider enabling TLS for registry
- Implement image signing (Cosign/Notary)
- Regular image cleanup/garbage collection

## Best Practices

1. **Always test in staging first**
2. **Use semantic versioning for production** (v1.0.0, v1.0.1, etc.)
3. **Tag stable versions** for easy rollback
4. **Monitor Flux reconciliation** for deployment issues
5. **Keep dependencies updated** to avoid security vulnerabilities
6. **Review SAST findings** before merging PRs
7. **Test rollback procedures** regularly
8. **Document configuration changes** in Git
9. **Use resource limits** to prevent pod resource exhaustion
10. **Monitor application logs** for errors

## Maintenance

### Weekly Tasks
- Review and update dependencies
- Check for SAST security findings
- Clean up old Docker images
- Review Flux reconciliation logs

### Monthly Tasks
- Update Flux controllers
- Review and update runner configurations
- Audit access controls
- Test disaster recovery procedures

### Quarterly Tasks
- Security audit of entire pipeline
- Performance optimization review
- Update documentation
- Review and update CI/CD workflows

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [FluxCD Documentation](https://fluxcd.io/flux/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [K3s Documentation](https://docs.k3s.io/)

## Support

For issues or questions:
1. Check this documentation first
2. Review troubleshooting section
3. Check GitHub Issues for similar problems
4. Create new issue with detailed description and logs
