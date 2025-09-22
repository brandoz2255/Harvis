# FluxCD Troubleshooting Guide

This guide covers common issues and solutions for FluxCD deployments in the Harvis AI project.

## 📊 Health Check Commands

Before troubleshooting, run these commands to assess the current state:

```bash
# Check FluxCD overall status
flux get all

# Check specific components
flux get kustomizations
flux get helmreleases
flux get sources git
flux get images all

# Check Kubernetes resources
kubectl get pods -n flux-system
kubectl get pods -n ai-agents

# View FluxCD logs
flux logs --level=info --all-namespaces
```

## 🔍 Common Issues and Solutions

### 1. GitRepository Not Found or Sync Issues

**Symptoms:**
- `GitRepository not found` errors in FluxCD logs
- Kustomization fails to reconcile
- Source references point to non-existent repositories

**Diagnosis:**
```bash
flux get sources git
kubectl describe gitrepository harvis-source -n flux-system
```

**Solutions:**

#### Issue: Repository URL incorrect or inaccessible
```bash
# Check current GitRepository configuration
kubectl get gitrepository harvis-source -n flux-system -o yaml

# Update repository URL if needed
flux create source git harvis-source \
  --url=https://github.com/your-username/aidev.git \
  --branch=main \
  --namespace=flux-system
```

#### Issue: Authentication problems (private repos)
```bash
# Create Git credentials secret for private repos
kubectl create secret generic git-credentials \
  --from-literal=username=your-username \
  --from-literal=password=your-token \
  --namespace=flux-system

# Update GitRepository to use credentials
kubectl patch gitrepository harvis-source -n flux-system \
  --type='merge' \
  -p='{"spec":{"secretRef":{"name":"git-credentials"}}}'
```

#### Issue: Branch or path doesn't exist
```bash
# Verify branch exists and has the required flux-config directory
git ls-remote --heads origin main
git show main:flux-config/harvis/

# Update branch reference if needed
flux create source git harvis-source \
  --url=https://github.com/brandoz2255/aidev.git \
  --branch=main \  # Change to correct branch
  --namespace=flux-system
```

### 2. HelmRelease Deployment Failures

**Symptoms:**
- HelmRelease shows `Failed` or `Pending` status
- Pods in `ai-agents` namespace fail to start
- Resource creation errors

**Diagnosis:**
```bash
flux get helmreleases -A
kubectl describe helmrelease harvis-ai -n ai-agents
kubectl get events -n ai-agents --sort-by='.lastTimestamp'
```

**Solutions:**

#### Issue: Helm chart not found
```bash
# Check if chart path exists in repository
git show main:harvis-helm-chart/Chart.yaml

# Verify HelmRelease chart reference
kubectl get helmrelease harvis-ai -n ai-agents -o yaml | grep -A 10 'chart:'
```

#### Issue: Invalid Helm values or template errors
```bash
# Test Helm chart locally
helm template harvis-ai ./harvis-helm-chart --debug

# Check for syntax errors in values
helm lint ./harvis-helm-chart

# Fix values in flux-config/harvis/base/helmrelease.yaml
```

#### Issue: Resource conflicts or insufficient permissions
```bash
# Check for conflicting resources
kubectl get all -n ai-agents
kubectl describe pod <failing-pod> -n ai-agents

# Check service account permissions
kubectl auth can-i create pods --as=system:serviceaccount:ai-agents:harvis-ai
```

#### Issue: Persistent Volume claim issues
```bash
# Check PVC status
kubectl get pvc -n ai-agents
kubectl describe pvc <pvc-name> -n ai-agents

# Fix storage class or volume availability
kubectl get storageclass
```

### 3. Image Automation Problems

**Symptoms:**
- New Docker images aren't triggering updates
- ImageRepository shows no images or old tags
- ImageUpdateAutomation not committing changes

**Diagnosis:**
```bash
flux get images all
kubectl describe imagerepository harvis-backend -n flux-system
kubectl describe imagepolicy harvis-backend-policy -n flux-system
kubectl logs -n flux-system deployment/image-automation-controller
```

**Solutions:**

#### Issue: Docker registry authentication
```bash
# Create registry credentials (if using private registry)
kubectl create secret docker-registry regcred \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=your-username \
  --docker-password=your-password \
  --namespace=flux-system

# Update ImageRepository to use credentials
kubectl patch imagerepository harvis-backend -n flux-system \
  --type='merge' \
  -p='{"spec":{"secretRef":{"name":"regcred"}}}'
```

#### Issue: Image tag filtering not matching
```bash
# Check current policy configuration
kubectl get imagepolicy harvis-backend-policy -n flux-system -o yaml

# Common patterns for tag filtering:
# For latest tags:
pattern: '^latest$'

# For semantic versioning:
pattern: '^v(?P<version>.*)$'

# For development tags:
pattern: '^(dev|latest|v.+)$'
```

#### Issue: Git automation not committing
```bash
# Check ImageUpdateAutomation logs
kubectl logs -n flux-system deployment/image-automation-controller

# Verify Git repository write access
# Update automation with proper Git credentials
kubectl patch imageupdateautomation harvis-automation -n flux-system \
  --type='merge' \
  -p='{"spec":{"git":{"author":{"email":"your-email@example.com","name":"FluxCD"}}}}'
```

### 4. Namespace and RBAC Issues

**Symptoms:**
- Resources created in wrong namespace
- Permission denied errors
- ServiceAccount issues

**Solutions:**

#### Issue: Missing or incorrect namespace
```bash
# Create namespace if missing
kubectl create namespace ai-agents

# Check namespace in HelmRelease
kubectl get helmrelease harvis-ai -n ai-agents -o yaml | grep namespace
```

#### Issue: ServiceAccount permissions
```bash
# Check existing service accounts
kubectl get serviceaccount -n ai-agents

# Create service account with proper RBAC
kubectl create serviceaccount harvis-ai -n ai-agents
kubectl create clusterrolebinding harvis-ai-admin \
  --clusterrole=admin \
  --serviceaccount=ai-agents:harvis-ai
```

### 5. Network and Ingress Issues

**Symptoms:**
- Services not accessible externally
- SSL/TLS certificate issues
- Load balancer not getting external IP

**Solutions:**

#### Issue: Ingress controller not installed
```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# Install nginx ingress controller if missing
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
```

#### Issue: SSL certificate problems
```bash
# Check cert-manager
kubectl get pods -n cert-manager

# Check certificate status
kubectl get certificate -n ai-agents
kubectl describe certificate harvis-tls -n ai-agents

# Check ClusterIssuer
kubectl get clusterissuer letsencrypt-prod
```

#### Issue: LoadBalancer external IP pending
```bash
# Check LoadBalancer services
kubectl get svc -n ai-agents

# For cloud providers, check if LoadBalancer support is enabled
# For local clusters, consider using NodePort or port-forward
kubectl port-forward svc/nginx 8080:80 -n ai-agents
```

## 🔧 Emergency Recovery Procedures

### Force Reconciliation
```bash
# Force all FluxCD resources to reconcile
flux reconcile kustomization harvis-app --with-source

# Suspend and resume if needed
flux suspend kustomization harvis-app
flux resume kustomization harvis-app
```

### Rollback Deployment
```bash
# Check Helm release history
helm history harvis-ai -n ai-agents

# Rollback to previous version
helm rollback harvis-ai 1 -n ai-agents

# Or delete and let FluxCD recreate
kubectl delete helmrelease harvis-ai -n ai-agents
# FluxCD will recreate automatically
```

### Reset FluxCD State
```bash
# Delete and recreate Kustomization
kubectl delete kustomization harvis-app -n flux-system
kubectl apply -f flux-config/harvis/flux-kustomization.yaml

# Clear image automation state
kubectl delete imageupdateautomation harvis-automation -n flux-system
kubectl apply -f flux-config/harvis/base/image-automation.yaml
```

## 📋 Monitoring and Alerting

### Set up monitoring for FluxCD health:

```bash
# Watch FluxCD status continuously
watch flux get all

# Monitor HelmRelease status
kubectl get helmreleases -A -w

# Check resource usage
kubectl top pods -n flux-system
kubectl top pods -n ai-agents
```

### Log Analysis
```bash
# FluxCD component logs
kubectl logs -n flux-system deployment/source-controller
kubectl logs -n flux-system deployment/kustomize-controller
kubectl logs -n flux-system deployment/helm-controller
kubectl logs -n flux-system deployment/image-automation-controller

# Application logs
kubectl logs -n ai-agents deployment/merged-backend
kubectl logs -n ai-agents deployment/frontend
```

## 📞 Getting Help

1. **Check FluxCD Status**: Always start with `flux get all`
2. **Review Events**: `kubectl get events -A --sort-by='.lastTimestamp'`
3. **Check Logs**: Use `flux logs` and `kubectl logs` extensively
4. **Validate Configuration**: Test Helm charts and YAML syntax locally
5. **Community Resources**:
   - [FluxCD Slack](https://cloud-native.slack.com/)
   - [FluxCD GitHub Discussions](https://github.com/fluxcd/flux2/discussions)
   - [FluxCD Documentation](https://fluxcd.io/docs/)

Remember: FluxCD is designed to be self-healing. Many issues resolve automatically when the underlying problems (network, permissions, etc.) are fixed.