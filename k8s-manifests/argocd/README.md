# ArgoCD Setup for Harvis AI

ArgoCD provides GitOps-based continuous deployment for Harvis AI.

## Architecture

- **ArgoCD Server**: Runs on `rocky2vm.local`
- **Web UI**: Accessible via MetalLB IP `192.168.122.241`
- **Auto-sync**: Watches git repo and deploys changes automatically

## Installation

### Step 1: Create Namespace
```bash
kubectl apply -f k8s-manifests/argocd/namespace.yaml
```

### Step 2: Install ArgoCD
```bash
# Install official ArgoCD manifests
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for pods to be ready
kubectl wait --for=condition=Ready pods --all -n argocd --timeout=300s
```

### Step 3: Pin to rocky2vm.local
```bash
# Apply node affinity patches
kubectl apply -f k8s-manifests/argocd/node-affinity-patches.yaml

# Restart deployments to pick up changes
kubectl rollout restart deployment -n argocd
kubectl rollout restart statefulset -n argocd
```

### Step 4: Expose Web UI via MetalLB
```bash
kubectl apply -f k8s-manifests/argocd/argocd-server-service.yaml
```

### Step 5: Get Initial Admin Password
```bash
# Get the initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
echo

# Login with:
# Username: admin
# Password: <output from above>
```

### Step 6: Access Web UI
```bash
# The UI is available at:
# http://192.168.122.241 (or https://192.168.122.241)

# Or port-forward for local access:
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Then visit: https://localhost:8080
```

### Step 7: Configure Harvis Application
```bash
# Apply the Harvis application config
kubectl apply -f k8s-manifests/argocd/harvis-application.yaml
```

## CLI Access

```bash
# Install ArgoCD CLI
# Linux:
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64

# Login to ArgoCD
argocd login 192.168.122.241 --username admin --password <password> --insecure

# List applications
argocd app list

# Sync an application
argocd app sync harvis-ai

# Get application status
argocd app get harvis-ai
```

## Image Update Workflow

1. **Push to main** -> GitLab CI builds new image
2. **Image pushed** -> Tagged with commit SHA
3. **ArgoCD detects** -> New image tag in registry
4. **Auto-deploy** -> Updates deployments with new image

### Manual Image Update
```bash
# Force update to specific image
argocd app set harvis-ai --kustomize-image dulc3/jarvis-backend:v2.29.0
argocd app sync harvis-ai
```

## Troubleshooting

### Pods not scheduling on rocky2vm.local
```bash
# Check node labels
kubectl get nodes --show-labels | grep rocky2vm

# Check pod events
kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-server
```

### Can't access Web UI
```bash
# Check LoadBalancer service
kubectl get svc -n argocd argocd-server-lb

# Check MetalLB
kubectl get ipaddresspool -n metallb-system
kubectl logs -n metallb-system -l app=metallb

# Verify IP assignment
kubectl describe svc -n argocd argocd-server-lb
```

### Sync failing
```bash
# Check application status
argocd app get harvis-ai

# View sync logs
argocd app logs harvis-ai

# Force refresh
argocd app refresh harvis-ai --hard
```

## Uninstall

```bash
# Remove ArgoCD
kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl delete namespace argocd
```
