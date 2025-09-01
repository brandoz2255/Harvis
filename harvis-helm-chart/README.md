# Harvis AI Helm Chart

A Helm chart for deploying the Harvis AI Project on Kubernetes. This chart deploys a sophisticated AI voice assistant with Next.js frontend, Python backend services, PostgreSQL database, and n8n workflow automation.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- NVIDIA GPU support (for AI backend)
- Persistent Volume provisioner support in the underlying infrastructure

## Installing the Chart

To install the chart with the release name `harvis-ai`:

```bash
helm install harvis-ai ./harvis-helm-chart
```

To install with custom values:

```bash
helm install harvis-ai ./harvis-helm-chart -f custom-values.yaml
```

## Uninstalling the Chart

To uninstall the `harvis-ai` deployment:

```bash
helm uninstall harvis-ai
```

## Configuration

The following table lists the configurable parameters of the Harvis AI chart and their default values.

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.imageRegistry` | Global Docker image registry | `""` |
| `global.storageClass` | Global StorageClass for Persistent Volume(s) | `""` |

### Nginx Proxy Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `nginx.enabled` | Enable Nginx proxy | `true` |
| `nginx.image.repository` | Nginx image repository | `nginx` |
| `nginx.image.tag` | Nginx image tag | `alpine` |
| `nginx.service.type` | Nginx service type | `LoadBalancer` |
| `nginx.service.port` | Nginx service port | `80` |

### Backend Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `backend.enabled` | Enable backend service | `true` |
| `backend.image.repository` | Backend image repository | `dulc3/jarvis-backend` |
| `backend.image.tag` | Backend image tag | `latest` |
| `backend.resources.requests.nvidia.com/gpu` | GPU requests | `1` |

### Frontend Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `frontend.enabled` | Enable frontend service | `true` |
| `frontend.build.enabled` | Enable frontend build | `true` |
| `frontend.build.context` | Build context path | `"./front_end/jfrontend"` |

### PostgreSQL Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgresql.enabled` | Enable PostgreSQL | `true` |
| `postgresql.auth.username` | PostgreSQL username | `pguser` |
| `postgresql.auth.password` | PostgreSQL password | `pgpassword` |
| `postgresql.auth.database` | PostgreSQL database | `database` |

### n8n Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `n8n.enabled` | Enable n8n | `true` |
| `n8n.auth.basicAuthUser` | n8n basic auth username | `admin` |
| `n8n.auth.basicAuthPassword` | n8n basic auth password | `adminpass` |

## GPU Support

The backend service requires NVIDIA GPU support. Make sure your Kubernetes cluster has:

1. NVIDIA device plugin installed
2. GPU nodes properly labeled
3. NVIDIA runtime configured

## Persistence

The chart mounts persistent volumes for:

- PostgreSQL data (`20Gi` by default)
- n8n data (`5Gi` by default)
- Backend code and embeddings (`10Gi` by default)

## Networking

The chart creates the following services:

- **nginx**: LoadBalancer service (port 80) - Main application entry point
- **backend**: ClusterIP service (port 8000) - Python FastAPI backend
- **frontend**: ClusterIP service (port 3000) - Next.js frontend
- **postgresql**: ClusterIP service (port 5432) - Database
- **n8n**: LoadBalancer service (port 5678) - Workflow automation

## Security

The chart includes:

- Secrets for sensitive data (JWT tokens, API keys, passwords)
- ConfigMaps for non-sensitive configuration
- Service accounts with minimal required permissions
- Network policies (optional)

## Examples

### Deploy with custom resource limits:

```bash
helm install harvis-ai ./harvis-helm-chart \
  --set backend.resources.limits.memory=8Gi \
  --set backend.resources.limits.cpu=4 \
  --set postgresql.resources.limits.memory=2Gi
```

### Deploy with custom ingress:

```bash
helm install harvis-ai ./harvis-helm-chart \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=harvis.yourdomain.com \
  --set ingress.hosts[0].paths[0].path=/ \
  --set ingress.hosts[0].paths[0].service.name=nginx \
  --set ingress.hosts[0].paths[0].service.port=80
```

### Deploy without n8n:

```bash
helm install harvis-ai ./harvis-helm-chart \
  --set n8n.enabled=false
```

## Troubleshooting

### Common Issues

1. **Pod Pending**: Check if GPU nodes are available and properly configured
2. **ImagePullBackOff**: Ensure the backend image `dulc3/jarvis-backend:latest` is accessible
3. **PVC Pending**: Verify storage class is available and has sufficient capacity
4. **Database Connection Issues**: Check PostgreSQL pod logs and network connectivity

### Checking Deployment Status

```bash
# Check all pods
kubectl get pods

# Check services
kubectl get services

# Check persistent volume claims
kubectl get pvc

# Check logs
kubectl logs -l app.kubernetes.io/name=harvis-ai
```

### Port Forwarding for Testing

```bash
# Access nginx proxy
kubectl port-forward svc/harvis-ai-nginx 8080:80

# Access backend directly
kubectl port-forward svc/harvis-ai-backend 8000:8000

# Access n8n
kubectl port-forward svc/harvis-ai-n8n 5678:5678
```

## Values Files Example

Create a `production-values.yaml` file:

```yaml
# Production configuration
global:
  storageClass: "fast-ssd"

backend:
  resources:
    limits:
      memory: "8Gi"
      cpu: "4"
      nvidia.com/gpu: 2
  env:
    JWT_SECRET: "your-production-jwt-secret"

postgresql:
  auth:
    password: "your-secure-database-password"
  persistence:
    size: 100Gi

ingress:
  enabled: true
  hosts:
    - host: harvis.yourdomain.com
      paths:
        - path: /
          pathType: Prefix
          service:
            name: nginx
            port: 80

nodeSelector:
  nvidia.com/gpu: "true"
```

Then deploy with:

```bash
helm install harvis-ai ./harvis-helm-chart -f production-values.yaml
```