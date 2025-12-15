# GitLab CI/CD Runner Setup Guide

This directory contains Kubernetes manifests for deploying GitLab Runners on your K8s cluster for CI/CD automation.

## Architecture

- **2 GitLab Runners**: One on each node (node1: node-gpu-1, node2: node-gpu-2)
- **Node 1 Runner**: Handles backend builds (GPU-enabled node)
- **Node 2 Runner**: Handles frontend builds
- **Executor**: Docker (using host Docker socket)
- **Registry**: Pushes to localhost:5000 (existing registry)

## Prerequisites

1. **GitLab Instance**: You need access to a GitLab instance (gitlab.com or self-hosted)
2. **Registration Token**: Obtain from GitLab project/group settings
3. **Docker Registry**: localhost:5000 should be running (already configured)

## Setup Instructions

### Step 1: Update Secrets

Edit `gitlab-runner-secrets.yaml` and replace placeholder values:

```bash
# Get your GitLab registration token
# For project runner: GitLab Project > Settings > CI/CD > Runners > New project runner
# For group runner: GitLab Group > Settings > CI/CD > Runners > New group runner

# Update gitlab-runner-secrets.yaml with:
# - gitlab-url: Your GitLab instance URL (https://gitlab.com or your self-hosted URL)
# - registration-token: The token from GitLab runner registration page
```

### Step 2: Deploy GitLab Runner to K8s

```bash
# Apply all manifests in order
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-namespace.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-secrets.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-config.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-rbac.yaml
kubectl apply -f k8s-manifests/ci-cd/gitlab-runner-deployment.yaml

# Verify deployments
kubectl get pods -n gitlab-runner
kubectl get deployments -n gitlab-runner
```

### Step 3: Register Runners with GitLab

The runners will auto-register on startup using the token in the secret. Verify registration:

```bash
# Check runner logs
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1
kubectl logs -n gitlab-runner deployment/gitlab-runner-node2

# You should see "Runner registered successfully"
```

Alternatively, manually register if needed:

```bash
# Node 1 runner
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -it -- \
  gitlab-runner register \
    --non-interactive \
    --url "https://gitlab.com" \
    --registration-token "YOUR_TOKEN" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --description "harvis-k8s-node1-backend" \
    --tag-list "node1,backend,gpu,docker" \
    --docker-privileged=false \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock"

# Node 2 runner
kubectl exec -n gitlab-runner deployment/gitlab-runner-node2 -it -- \
  gitlab-runner register \
    --non-interactive \
    --url "https://gitlab.com" \
    --registration-token "YOUR_TOKEN" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --description "harvis-k8s-node2-frontend" \
    --tag-list "node2,frontend,docker" \
    --docker-privileged=false \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock"
```

### Step 4: Verify Runners in GitLab

1. Go to your GitLab project/group
2. Navigate to **Settings > CI/CD > Runners**
3. You should see 2 runners:
   - `harvis-k8s-node1-backend` (tags: node1, backend, gpu, docker)
   - `harvis-k8s-node2-frontend` (tags: node2, frontend, docker)

### Step 5: Configure GitHub Actions Integration

For GitHub Actions to trigger GitLab CI:

1. **Get GitLab Pipeline Trigger Token**:
   - GitLab Project > Settings > CI/CD > Pipeline triggers
   - Create a new trigger token

2. **Add GitHub Secrets**:
   - GitHub Repo > Settings > Secrets and variables > Actions
   - Add secrets:
     - `GITLAB_WEBHOOK_URL`: `https://gitlab.com/api/v4/projects/YOUR_PROJECT_ID/trigger/pipeline`
     - `GITLAB_TOKEN`: The trigger token from step 1

3. **Test GitHub → GitLab Integration**:
   ```bash
   # Push to main branch (after SAST passes)
   git add .
   git commit -m "Test CI/CD pipeline"
   git push origin main

   # GitHub Actions will:
   # 1. Run SAST scans
   # 2. Trigger GitLab CI webhook
   # 3. GitLab CI builds images
   # 4. Images pushed to localhost:5000
   # 5. Flux auto-deploys updates
   ```

## Configuration Files

- **gitlab-runner-namespace.yaml**: Creates `gitlab-runner` namespace
- **gitlab-runner-secrets.yaml**: GitLab credentials and registry secrets
- **gitlab-runner-config.yaml**: Runner configuration (config.toml)
- **gitlab-runner-rbac.yaml**: RBAC permissions for runners
- **gitlab-runner-deployment.yaml**: Runner deployments (2 pods, one per node)
- **local-registry-config.yaml**: Registry garbage collection and config

## Runner Tags and Job Assignment

GitLab CI jobs are assigned to runners based on tags:

- **node1, backend, gpu**: Jobs requiring GPU (backend builds)
- **node2, frontend**: Frontend and general builds
- **docker**: All jobs using Docker executor

Example `.gitlab-ci.yml` job targeting specific runner:

```yaml
build-backend:
  stage: build
  tags:
    - node1      # Run on node1
    - backend
    - docker
  script:
    - docker build -t localhost:5000/jarvis-backend:latest .
```

## Troubleshooting

### Runners not appearing in GitLab

```bash
# Check runner logs
kubectl logs -n gitlab-runner deployment/gitlab-runner-node1 -f

# Common issues:
# 1. Registration token expired - get a new one from GitLab
# 2. Network connectivity - ensure pods can reach GitLab
# 3. Secret not updated - verify gitlab-runner-secrets.yaml
```

### Docker builds failing

```bash
# Verify Docker socket is mounted
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -- ls -la /var/run/docker.sock

# Check Docker is accessible
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -- docker ps

# Verify runner has correct permissions
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -- docker info
```

### Registry push failures

```bash
# Check registry is accessible from runners
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -- curl -v http://localhost:5000/v2/_catalog

# For insecure registry, ensure Docker is configured:
# On each node, add to /etc/docker/daemon.json:
# {
#   "insecure-registries": ["localhost:5000"]
# }
# Then: sudo systemctl restart docker
```

### Verifying runner health

```bash
# Check runner status
kubectl get pods -n gitlab-runner -o wide

# View runner configuration
kubectl exec -n gitlab-runner deployment/gitlab-runner-node1 -- cat /etc/gitlab-runner/config.toml

# Check runner metrics (if enabled)
kubectl port-forward -n gitlab-runner deployment/gitlab-runner-node1 9252:9252
# Visit http://localhost:9252/metrics
```

## Uninstalling

```bash
# Remove all GitLab Runner resources
kubectl delete -f k8s-manifests/ci-cd/

# Or delete namespace (removes everything)
kubectl delete namespace gitlab-runner
```

## Next Steps

1. ✅ Deploy GitLab Runners to K8s
2. ✅ Configure `.gitlab-ci.yml` pipeline
3. ⏭️ Deploy FluxCD for GitOps automation
4. ⏭️ Create Kustomize overlays for staging/prod
5. ⏭️ Test full CI/CD pipeline

## References

- [GitLab Runner Kubernetes Executor](https://docs.gitlab.com/runner/executors/kubernetes.html)
- [GitLab CI/CD Pipelines](https://docs.gitlab.com/ee/ci/pipelines/)
- [Docker Executor](https://docs.gitlab.com/runner/executors/docker.html)
- [Runner Registration](https://docs.gitlab.com/runner/register/)
