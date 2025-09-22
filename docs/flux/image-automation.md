# FluxCD Image Automation Guide

This guide covers FluxCD's image automation system for automatically updating container images in Kubernetes deployments.

## 🔄 Overview

FluxCD's image automation continuously monitors Docker registries for new images and automatically updates your Kubernetes deployments when new images are available. For Harvis AI, this means:

- **Backend**: Monitors `dulc3/jarvis-backend:latest`
- **Frontend**: Monitors `dulc3/jarvis-frontend:latest`
- **Update Frequency**: Checks every 30 seconds, applies updates every 5 minutes
- **Git Integration**: Automatically commits image tag updates to the repository

## 🏗️ Architecture Components

The image automation system consists of three main components:

### 1. ImageRepository
Monitors a specific Docker image repository for new tags.

```yaml
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: harvis-backend
  namespace: flux-system
spec:
  image: dulc3/jarvis-backend
  interval: 30s
```

### 2. ImagePolicy
Defines which image tags to consider for updates using filtering and sorting policies.

```yaml
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: harvis-backend-policy
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: harvis-backend
  policy:
    alphabetical:
      order: asc
  filterTags:
    pattern: '^latest$'
```

### 3. ImageUpdateAutomation
Orchestrates the automatic updating of image references in Git and applies them to the cluster.

```yaml
apiVersion: image.toolkit.fluxcd.io/v1beta1
kind: ImageUpdateAutomation
metadata:
  name: harvis-automation
  namespace: flux-system
spec:
  interval: 5m
  sourceRef:
    kind: GitRepository
    name: harvis-source
  git:
    commit:
      author:
        email: fluxcdbot@users.noreply.github.com
        name: fluxcdbot
      messageTemplate: |
        Automated image update

        Images:
        {{ range .Updated.Images -}}
        - {{.}}
        {{ end -}}
    push:
      branch: main
  update:
    path: "./flux-config/harvis"
    strategy: Setters
```

## 🎯 Current Harvis AI Configuration

### Monitored Images
- **Backend**: `dulc3/jarvis-backend:latest`
- **Frontend**: `dulc3/jarvis-frontend:latest`

### Update Strategy
- **Policy**: Alphabetical order (latest tag wins)
- **Filter**: Only `latest` tags are considered
- **Scan Interval**: 30 seconds for new images
- **Update Interval**: 5 minutes for applying changes

### Automation Behavior
1. **Image Detection**: FluxCD scans Docker Hub every 30 seconds
2. **Policy Evaluation**: Checks if new image matches `latest` tag pattern
3. **File Updates**: Updates image tags in `flux-config/harvis/base/helmrelease.yaml`
4. **Git Commit**: Commits changes with automated message
5. **Deployment**: HelmRelease picks up changes and updates pods

## 🔧 Image Tag Patterns

### Current Pattern: Latest Tag Only
```yaml
filterTags:
  pattern: '^latest$'
```
**Use case**: Development environments where you always want the newest build

### Alternative Patterns

#### Semantic Versioning
```yaml
policy:
  semver:
    range: '>=1.0.0'
filterTags:
  pattern: '^v(?P<version>.*)$'
  extract: '$version'
```
**Use case**: Production environments with versioned releases

#### Development + Production Tags
```yaml
filterTags:
  pattern: '^(dev|latest|v.+)$'
```
**Use case**: Multi-environment setup with different tag strategies

#### Numeric Tags
```yaml
policy:
  numerical:
    order: asc
filterTags:
  pattern: '^[0-9]+$'
```
**Use case**: Build number-based tagging

#### Date-based Tags
```yaml
filterTags:
  pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
```
**Use case**: Daily build releases

## 📝 Image Reference Format

In your HelmRelease files, image references must include special FluxCD annotations:

```yaml
image:
  repository: dulc3/jarvis-backend
  tag: latest # {"$imagepolicy": "flux-system:harvis-backend-policy:tag"}
  pullPolicy: Always
```

**Important**: The comment `# {"$imagepolicy": "..."}` is required for FluxCD to update the tag automatically.

## 🔍 Monitoring and Debugging

### Check Image Automation Status
```bash
# View all image automation resources
flux get images all

# Check specific components
flux get images repository
flux get images policy
flux get images update

# Detailed status
kubectl describe imagerepository harvis-backend -n flux-system
kubectl describe imagepolicy harvis-backend-policy -n flux-system
kubectl describe imageupdateautomation harvis-automation -n flux-system
```

### View Recent Updates
```bash
# Check recent commits for automated updates
git log --oneline --grep="Automated image update" -10

# View FluxCD automation logs
kubectl logs -n flux-system deployment/image-automation-controller

# Check for image policy violations
flux get images policy --output=json | jq '.[] | select(.ready==false)'
```

### Force Image Scan
```bash
# Force immediate image repository scan
flux reconcile image repository harvis-backend

# Force automation update
flux reconcile image update harvis-automation
```

## ⚠️ Common Issues and Solutions

### 1. Images Not Being Detected

**Problem**: New images pushed to registry but FluxCD doesn't detect them

**Solutions**:
```bash
# Check ImageRepository status
kubectl describe imagerepository harvis-backend -n flux-system

# Verify Docker registry connectivity
docker pull dulc3/jarvis-backend:latest

# Check for rate limiting or authentication issues
kubectl logs -n flux-system deployment/image-reflector-controller
```

### 2. Policy Not Matching Tags

**Problem**: Images available but policy filters them out

**Solutions**:
```bash
# Test tag pattern locally
echo "latest" | grep -E '^latest$'

# Check all available tags
flux get images repository harvis-backend --output=json | jq '.status.tags'

# Update policy pattern if needed
kubectl patch imagepolicy harvis-backend-policy -n flux-system \
  --type='merge' \
  -p='{"spec":{"filterTags":{"pattern":"^(latest|dev)$"}}}'
```

### 3. Git Automation Not Working

**Problem**: Images detected but changes not committed to Git

**Solutions**:
```bash
# Check Git repository write permissions
kubectl describe imageupdateautomation harvis-automation -n flux-system

# Verify Git credentials (for private repos)
kubectl get secret -n flux-system | grep git

# Check automation logs
kubectl logs -n flux-system deployment/image-automation-controller
```

### 4. Deployment Not Updating

**Problem**: Git updated but pods still running old images

**Solutions**:
```bash
# Force HelmRelease reconciliation
flux reconcile helmrelease harvis-ai -n ai-agents

# Check HelmRelease status
kubectl describe helmrelease harvis-ai -n ai-agents

# Manually restart deployment if needed
kubectl rollout restart deployment/merged-backend -n ai-agents
```

## 🔒 Security Considerations

### Registry Authentication
For private registries, create image pull secrets:

```bash
kubectl create secret docker-registry regcred \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=your-username \
  --docker-password=your-password \
  --namespace=flux-system

# Reference in ImageRepository
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: harvis-backend
spec:
  secretRef:
    name: regcred
```

### Git Repository Access
For private Git repositories, configure SSH or HTTPS credentials:

```bash
# SSH key method
kubectl create secret generic git-auth \
  --from-file=identity=/path/to/private-key \
  --namespace=flux-system

# Token method
kubectl create secret generic git-auth \
  --from-literal=username=your-username \
  --from-literal=password=your-token \
  --namespace=flux-system
```

## 📊 Performance Tuning

### Interval Configuration
- **High-frequency updates**: Set shorter intervals (30s for images, 1m for automation)
- **Reduced API calls**: Set longer intervals (5m for images, 30m for automation)
- **Mixed approach**: Short intervals for critical services, longer for stable components

### Resource Limits
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: image-automation-quota
  namespace: flux-system
spec:
  hard:
    requests.cpu: "100m"
    requests.memory: "128Mi"
    limits.cpu: "200m"
    limits.memory: "256Mi"
```

## 🚀 Advanced Configurations

### Multi-Environment Setup
```yaml
# Production policy - semantic versioning
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: harvis-backend-prod
spec:
  policy:
    semver:
      range: '>=1.0.0 <2.0.0'

# Staging policy - release candidates
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: harvis-backend-staging
spec:
  filterTags:
    pattern: '^v.*-rc.*$'
```

### Conditional Updates
```yaml
# Only update during maintenance windows
apiVersion: image.toolkit.fluxcd.io/v1beta1
kind: ImageUpdateAutomation
metadata:
  name: harvis-automation
spec:
  interval: 5m
  suspend: false  # Set to true to pause automation
```

This image automation system ensures Harvis AI stays up-to-date with the latest container images while maintaining control over the deployment process through GitOps principles.