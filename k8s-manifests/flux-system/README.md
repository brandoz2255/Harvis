# FluxCD Installation and Configuration Guide

FluxCD is a GitOps tool that automatically deploys and updates your applications based on Git repository changes and container registry updates.

## Prerequisites

- Kubernetes cluster (K3s) running
- kubectl configured to access your cluster
- Git repository (GitHub) with your manifests
- Local Docker registry at localhost:5000

## Installation

### Step 1: Install Flux CLI

```bash
# Install Flux CLI
curl -s https://fluxcd.io/install.sh | sudo bash

# Verify installation
flux --version
```

### Step 2: Check Cluster Compatibility

```bash
# Verify cluster meets requirements
flux check --pre

# Expected output: ✔ all checks passed
```

### Step 3: Bootstrap Flux (Option A - GitHub)

If you want Flux to manage its own configuration via GitHub:

```bash
# Export GitHub token
export GITHUB_TOKEN=<your-github-personal-access-token>
export GITHUB_USER=<your-github-username>
export GITHUB_REPO=<your-repo-name>

# Bootstrap Flux (creates flux-system namespace and components)
flux bootstrap github \
  --owner=${GITHUB_USER} \
  --repository=${GITHUB_REPO} \
  --branch=main \
  --path=./k8s-manifests/flux-system \
  --personal \
  --components-extra=image-reflector-controller,image-automation-controller
```

### Step 3: Bootstrap Flux (Option B - Manual)

If you prefer manual installation without GitHub integration:

```bash
# Install Flux components
flux install \
  --components-extra=image-reflector-controller,image-automation-controller

# Export Flux components to file (for version control)
flux install \
  --components-extra=image-reflector-controller,image-automation-controller \
  --export > k8s-manifests/flux-system/gotk-components.yaml
```

### Step 4: Verify Flux Installation

```bash
# Check Flux components are running
flux check

# View Flux pods
kubectl get pods -n flux-system

# Expected pods:
# - source-controller
# - kustomize-controller
# - helm-controller
# - notification-controller
# - image-reflector-controller (for image automation)
# - image-automation-controller (for image automation)
```

## Configuration

### Step 5: Configure Git Repository Source

Edit `git-repository.yaml` and update the repository URL:

```yaml
spec:
  url: https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

Then apply:

```bash
kubectl apply -f k8s-manifests/flux-system/git-repository.yaml
```

### Step 6: Apply Image Automation

```bash
# Apply image repository scanners
kubectl apply -f k8s-manifests/flux-system/image-registry.yaml

# Apply image update automation
kubectl apply -f k8s-manifests/flux-system/image-update-automation.yaml
```

### Step 7: Apply Kustomizations for Environments

```bash
# Deploy staging environment
kubectl apply -f k8s-manifests/flux-system/kustomization-staging.yaml

# Deploy production environment
kubectl apply -f k8s-manifests/flux-system/kustomization-prod.yaml
```

## How It Works

### GitOps Workflow

```
1. Developer pushes code to GitHub (main branch)
   ↓
2. GitHub Actions runs SAST security scans
   ↓
3. If SAST passes, trigger GitLab CI webhook
   ↓
4. GitLab CI builds Docker images
   ↓
5. Images pushed to localhost:5000 with tags:
   - staging-latest (for staging)
   - staging-<sha> (for staging)
   - v1.0.0 (for production)
   ↓
6. Flux ImageRepository scans localhost:5000
   ↓
7. Flux ImagePolicy selects appropriate tag:
   - Staging: staging-latest
   - Production: v1.0.0+ (semver)
   ↓
8. Flux ImageUpdateAutomation updates kustomization.yaml
   ↓
9. Flux Kustomization reconciles changes
   ↓
10. New pods deployed with updated images
```

### Image Tagging Strategy

**Staging Environment:**
- Tags: `staging-latest`, `staging-<git-sha>`
- Auto-deploys on every main branch push
- Namespace: `ai-agents-staging`

**Production Environment:**
- Tags: `v1.0.0`, `v1.0.1`, `v2.0.0` (semantic versioning)
- Auto-deploys on version tag creation
- Namespace: `ai-agents` (current production namespace)

## Monitoring Flux

### View Flux Resources

```bash
# View all Flux resources
flux get all

# View Git repositories
flux get sources git

# View image repositories
flux get images repository

# View image policies
flux get images policy

# View image automation
flux get images update

# View kustomizations
flux get kustomizations
```

### View Reconciliation Status

```bash
# Check staging environment
flux get kustomizations harvis-ai-staging

# Check production environment
flux get kustomizations harvis-ai-production

# View recent reconciliations
kubectl get gitrepositories -n flux-system
kubectl get kustomizations -n flux-system
```

### View Logs

```bash
# Source controller logs (Git repo sync)
kubectl logs -n flux-system deployment/source-controller -f

# Kustomize controller logs (manifest apply)
kubectl logs -n flux-system deployment/kustomize-controller -f

# Image reflector logs (registry scanning)
kubectl logs -n flux-system deployment/image-reflector-controller -f

# Image automation logs (manifest updates)
kubectl logs -n flux-system deployment/image-automation-controller -f
```

## Manual Operations

### Force Reconciliation

```bash
# Force Git repository sync
flux reconcile source git harvis-ai-repo

# Force staging environment reconciliation
flux reconcile kustomization harvis-ai-staging

# Force production environment reconciliation
flux reconcile kustomization harvis-ai-production

# Force image repository scan
flux reconcile image repository harvis-backend
flux reconcile image repository harvis-frontend
```

### Suspend/Resume Automation

```bash
# Suspend production auto-updates (for manual control)
flux suspend image update harvis-prod-auto-update

# Resume auto-updates
flux resume image update harvis-prod-auto-update

# Suspend entire kustomization
flux suspend kustomization harvis-ai-production

# Resume kustomization
flux resume kustomization harvis-ai-production
```

## Troubleshooting

### Flux Not Detecting New Images

```bash
# Check image repository status
flux get images repository harvis-backend
flux get images repository harvis-frontend

# Check if registry is accessible
kubectl run -n flux-system curl-test --image=curlimages/curl --rm -it -- \
  curl -v http://localhost:5000/v2/_catalog

# Force image repository scan
flux reconcile image repository harvis-backend --with-source
```

### Kustomization Failing

```bash
# View detailed error
flux logs --kind=Kustomization --name=harvis-ai-staging

# Check kustomization build locally
cd k8s-manifests/overlays/staging
kustomize build .

# Validate manifests
kubectl apply --dry-run=client -k .
```

### Image Policy Not Selecting Tags

```bash
# View image policy status
flux get images policy harvis-backend-staging -o yaml

# Check available tags in registry
curl http://localhost:5000/v2/jarvis-backend/tags/list

# Update filter pattern if needed
kubectl edit imagepolicy -n flux-system harvis-backend-staging
```

## Security Considerations

### Private Repository Access

If your Git repository is private:

```bash
# Create SSH key for Flux
ssh-keygen -t ed25519 -C "flux@harvis.ai" -f ~/.ssh/flux

# Add SSH key to GitHub deploy keys

# Create Kubernetes secret
kubectl create secret generic github-credentials \
  --from-file=identity=~/.ssh/flux \
  --from-literal=known_hosts="$(ssh-keyscan github.com)" \
  -n flux-system

# Update git-repository.yaml to use SSH URL and secret
```

### Image Registry Authentication

For secure registry access:

```bash
# Create registry credentials secret
kubectl create secret docker-registry regcred \
  --docker-server=localhost:5000 \
  --docker-username=<user> \
  --docker-password=<pass> \
  -n flux-system

# Update image-registry.yaml to reference secret
```

## Best Practices

1. **Staging First**: Always test in staging before promoting to production
2. **Semantic Versioning**: Use semver tags (v1.0.0) for production releases
3. **Monitor Reconciliation**: Set up alerts for failed reconciliations
4. **Rollback Plan**: Tag stable versions for easy rollback
5. **Resource Limits**: Set appropriate resource limits in overlays
6. **Health Checks**: Configure liveness/readiness probes
7. **Gradual Rollout**: Use progressive delivery (Flagger) for production

## Uninstalling Flux

```bash
# Uninstall Flux (keeps CRDs and resources)
flux uninstall

# Complete removal (including CRDs)
flux uninstall --crds

# Remove Flux namespace
kubectl delete namespace flux-system
```

## Next Steps

1. ✅ Install Flux CLI
2. ✅ Bootstrap Flux on K8s cluster
3. ✅ Configure Git repository source
4. ✅ Apply image automation
5. ⏭️ Update GitHub repository URL in git-repository.yaml
6. ⏭️ Test staging deployment
7. ⏭️ Create version tag for production deployment
8. ⏭️ Monitor Flux reconciliation

## References

- [FluxCD Official Documentation](https://fluxcd.io/flux/)
- [Image Automation Guide](https://fluxcd.io/flux/guides/image-update/)
- [GitOps Toolkit](https://fluxcd.io/flux/components/)
- [Flux CLI Reference](https://fluxcd.io/flux/cmd/)
