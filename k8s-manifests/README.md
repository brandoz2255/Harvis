# Harvis AI Kubernetes Manifests

Plain Kubernetes manifests for deploying the Harvis AI Project to Kubernetes.

## Prerequisites

- Kubernetes cluster (v1.24+)
- `kubectl` CLI tool configured
- NVIDIA GPU runtime configured (for merged-ollama-backend)
- MetalLB or similar LoadBalancer provider (for nginx service)
- Storage provisioner for PersistentVolumeClaims

## Architecture

The deployment consists of the following components:

- **Nginx**: LoadBalancer service (192.168.4.241) - Entry point for all traffic
- **Frontend**: Next.js web application (ClusterIP:3000)
- **Merged Ollama + Backend**: Combined deployment with GPU support
  - Ollama AI models server (port 11434)
  - Harvis Python FastAPI backend (port 8000)
- **PostgreSQL**: Database with pgvector extension
- **n8n**: Workflow automation service

## Directory Structure

```
k8s-manifests/
├── base/
│   ├── configmaps.yaml        # Backend, frontend, and PostgreSQL init configs
│   ├── nginx-configmap.yaml   # Nginx reverse proxy configuration
│   └── secrets.yaml           # All secrets (JWT, DB passwords, API keys)
├── storage/
│   └── pvcs.yaml              # PersistentVolumeClaims for all services
├── services/
│   ├── merged-ollama-backend.yaml  # GPU-enabled Ollama + Backend
│   ├── frontend.yaml          # Next.js frontend
│   ├── postgresql.yaml        # PostgreSQL database
│   ├── n8n.yaml               # n8n workflow automation
│   └── nginx.yaml             # Nginx LoadBalancer
└── kustomization.yaml         # Kustomize configuration
```

## Quick Start

### 1. Create Namespace

```bash
kubectl create namespace ai-agents
```

### 2. Configure Secrets (IMPORTANT!)

Before deploying, update the secrets in `base/secrets.yaml`:

```bash
# Edit secrets file
vim k8s-manifests/base/secrets.yaml

# Set the following values:
# - harvis-ai-backend-secret:
#   - jwt-secret: Your JWT secret key
#   - ollama-api-key: Ollama API key (if using cloud)
#   - openai-api-key: OpenAI API key (optional)
# - harvis-ai-frontend-secret:
#   - jwt-secret: Same JWT secret as backend
# - harvis-ai-postgresql-secret:
#   - postgres-password: Strong PostgreSQL password
# - harvis-ai-n8n-secret:
#   - basic-auth-password: n8n admin password
#   - personal-api-key: n8n API key (optional)
```

### 3. Deploy Using Kustomize

```bash
# Apply all manifests
kubectl apply -k k8s-manifests/

# Or deploy individually
kubectl apply -f k8s-manifests/base/
kubectl apply -f k8s-manifests/storage/
kubectl apply -f k8s-manifests/services/
```

### 4. Verify Deployment

```bash
# Check all resources in ai-agents namespace
kubectl get all -n ai-agents

# Check pod status
kubectl get pods -n ai-agents

# Check services
kubectl get svc -n ai-agents

# Check PVCs
kubectl get pvc -n ai-agents
```

### 5. Access the Application

- **Web UI**: http://192.168.4.241 (via Nginx LoadBalancer)
- **Backend API**: http://192.168.4.241/api (proxied by Nginx)
- **n8n**: Configure Ingress or port-forward to access

```bash
# Port-forward n8n (if needed)
kubectl port-forward -n ai-agents svc/harvis-ai-n8n 5678:5678
# Access at http://localhost:5678
```

## Configuration

### Update Image Tags

To use different image versions, edit the deployments directly or use Kustomize:

```yaml
# In kustomization.yaml, uncomment and modify:
images:
  - name: dulc3/jarvis-frontend
    newTag: latest
  - name: dulc3/jarvis-backend
    newTag: latest
```

Then apply:
```bash
kubectl apply -k k8s-manifests/
```

### Modify Resource Limits

Edit the resource requests/limits in each service YAML file:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 1Gi
```

### Change LoadBalancer IP

Edit `services/nginx.yaml`:

```yaml
spec:
  type: LoadBalancer
  loadBalancerIP: 192.168.4.241  # Change this IP
```

### GPU Configuration

The merged-ollama-backend deployment requires NVIDIA GPU:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1  # Number of GPUs
```

Ensure your cluster has the NVIDIA device plugin installed:
```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.0/nvidia-device-plugin.yml
```

## Monitoring and Logs

### View Logs

```bash
# Backend logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=merged-ollama-backend -c harvis-backend -f

# Ollama logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=merged-ollama-backend -c ollama -f

# Frontend logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=frontend -f

# PostgreSQL logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=postgresql -f

# Nginx logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=nginx -f

# n8n logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=n8n -f
```

### Exec into Pods

```bash
# Access PostgreSQL
kubectl exec -it -n ai-agents deployment/harvis-ai-pgsql -- psql -U pguser -d database

# Access backend container
kubectl exec -it -n ai-agents deployment/harvis-ai-merged-ollama-backend -c harvis-backend -- /bin/bash

# Access Ollama container
kubectl exec -it -n ai-agents deployment/harvis-ai-merged-ollama-backend -c ollama -- /bin/bash
```

## Troubleshooting

### Pods Not Starting

```bash
# Describe pod to see events
kubectl describe pod -n ai-agents <pod-name>

# Check pod logs
kubectl logs -n ai-agents <pod-name>
```

### PVC Pending

```bash
# Check PVC status
kubectl get pvc -n ai-agents

# Describe PVC to see events
kubectl describe pvc -n ai-agents <pvc-name>

# Ensure you have a storage provisioner installed
```

### GPU Not Available

```bash
# Check GPU availability
kubectl get nodes "-o=custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu"

# Verify NVIDIA device plugin is running
kubectl get pods -n kube-system | grep nvidia
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
kubectl get pods -n ai-agents -l app.kubernetes.io/component=postgresql

# Check database initialization
kubectl logs -n ai-agents deployment/harvis-ai-pgsql

# Test database connection from backend
kubectl exec -it -n ai-agents deployment/harvis-ai-merged-ollama-backend -c harvis-backend -- curl http://harvis-ai-pgsql:5432
```

## Updating the Deployment

### Rolling Update

```bash
# Update image version in deployment
kubectl set image deployment/harvis-ai-frontend -n ai-agents frontend=dulc3/jarvis-frontend:new-tag

# Or edit deployment directly
kubectl edit deployment harvis-ai-frontend -n ai-agents

# Watch rollout status
kubectl rollout status deployment/harvis-ai-frontend -n ai-agents
```

### Rollback

```bash
# View rollout history
kubectl rollout history deployment/harvis-ai-frontend -n ai-agents

# Rollback to previous version
kubectl rollout undo deployment/harvis-ai-frontend -n ai-agents

# Rollback to specific revision
kubectl rollout undo deployment/harvis-ai-frontend -n ai-agents --to-revision=2
```

## Cleanup

### Delete All Resources

```bash
# Delete using kustomize
kubectl delete -k k8s-manifests/

# Or delete namespace (removes everything)
kubectl delete namespace ai-agents
```

### Delete Specific Components

```bash
# Delete specific deployment
kubectl delete deployment harvis-ai-frontend -n ai-agents

# Delete service
kubectl delete service harvis-ai-nginx -n ai-agents

# Delete PVCs (WARNING: This will delete data!)
kubectl delete pvc --all -n ai-agents
```

## Production Considerations

### Security

1. **Update all secrets** in `base/secrets.yaml` with strong, unique values
2. **Never commit secrets** to version control
3. Use **Sealed Secrets** or **External Secrets Operator** for secret management
4. Enable **RBAC** and create service accounts with minimal permissions
5. Use **Network Policies** to restrict pod-to-pod communication

### High Availability

1. Increase replica counts for stateless services:
   ```yaml
   spec:
     replicas: 3  # For frontend and nginx
   ```

2. Use **StatefulSets** for PostgreSQL in production
3. Configure **PodDisruptionBudgets**
4. Use **anti-affinity** rules to spread replicas across nodes

### Monitoring

1. Install **Prometheus** and **Grafana** for metrics
2. Configure **Loki** for log aggregation
3. Set up **alerts** for critical components
4. Monitor GPU utilization for the merged-ollama-backend

### Backup

1. Regular **database backups** using CronJob
2. Backup **PVC data** using Velero or similar
3. Store **backup configuration** in version control
4. Test **restore procedures** regularly

## Migration from Helm

This manifest set is equivalent to the Helm chart deployment with the following changes:

- All template variables replaced with hardcoded values from `values.yaml`
- Release name pattern: `harvis-ai-<component>` (replaces `{{ include "harvis-ai.fullname" . }}-<component>`)
- Namespace: `ai-agents` (from `global.namespace`)
- Node selector: `environment: dulc3-os` (from `nodeSelector`)
- All conditional logic removed (enabled components only)

## Support

For issues or questions:
- Project: https://github.com/brandoz2255/aidev
- Maintainer: dulc3 <0081833650@coyote.csusb.edu>
