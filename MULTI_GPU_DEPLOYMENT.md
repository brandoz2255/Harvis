# Multi-GPU Cluster Deployment Guide

## Architecture Overview

This deployment splits Harvis AI workloads across two GPU nodes for optimal performance:

- **Node 1 (node-gpu-1 / 192.168.1.195)**: Dedicated to **Ollama LLM inference**
- **Node 2 (node-gpu-2 / 10.20.0.125)**: Dedicated to **ML workloads** (Whisper STT, TTS, Vision models)

### Benefits

1. **Full GPU isolation**: Each workload gets dedicated 24GB VRAM
2. **Parallel processing**: Voice processing and LLM inference run simultaneously
3. **Shared storage**: NFS allows both nodes to access same model caches
4. **True load distribution**: Mimics 48GB combined GPU capability

## Deployment Steps

### Step 1: Configure NFS Server (Control Plane Node)

Run the NFS server setup script on the control plane node:

```bash
cd /home/guruai/compose/aidev
sudo ./setup-nfs-server.sh
```

This script will:
- Create NFS export directories: `/srv/nfs/ml-models-cache` and `/srv/nfs/ollama-models`
- Configure NFS exports for both cluster subnets
- Restart NFS server
- Display configured exports

### Step 2: Install NFS Client on Worker Node

SSH to the worker node and install NFS client:

```bash
ssh node-gpu-2
sudo apt update && sudo apt install -y nfs-common
```

Verify NFS connectivity:

```bash
# From worker node
showmount -e 192.168.1.195

# Expected output:
# Export list for 192.168.1.195:
# /srv/nfs/ollama-models   192.168.1.0/24,10.20.0.0/24
# /srv/nfs/ml-models-cache 192.168.1.0/24,10.20.0.0/24
```

### Step 3: Migrate Existing ML Models to NFS

Before deleting the old deployment, copy existing models to NFS:

```bash
# Find the existing ml-models-cache location
kubectl exec -it -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=merged-ollama-backend -o jsonpath='{.items[0].metadata.name}') -c harvis-backend -- ls -la /models-cache

# Copy existing models to NFS (from control plane node)
# This assumes the old PVC is mounted on node-gpu-1 node
sudo cp -r /var/lib/rancher/k3s/storage/pvc-6d5ffc7d-437d-42f8-8e62-76c9a478fee2_ai-agents_ml-models-cache/* /srv/nfs/ml-models-cache/

# Copy existing Ollama models
sudo cp -r /var/lib/rancher/k3s/storage/pvc-f8c8f139-e6ce-4ada-a0f7-47abd9d7f676_ai-agents_ollama-model-cache/* /srv/nfs/ollama-models/

# Verify copy
ls -lh /srv/nfs/ml-models-cache/
ls -lh /srv/nfs/ollama-models/
```

### Step 4: Apply NFS Storage Configuration

```bash
cd /home/guruai/compose/aidev/k8s-manifests
kubectl apply -f storage/nfs-storage.yaml
```

Verify PVs and PVCs are created and bound:

```bash
kubectl get pv | grep nfs
kubectl get pvc -n ai-agents | grep nfs
```

Expected output:
```
nfs-ml-models-cache-pv    100Gi      RWX            Retain           Bound    ai-agents/nfs-ml-models-cache
nfs-ollama-models-pv      100Gi      RWX            Retain           Bound    ai-agents/nfs-ollama-models
```

### Step 5: Delete Old Merged Deployment

```bash
kubectl delete deployment harvis-ai-merged-ollama-backend -n ai-agents
kubectl delete service harvis-ai-merged-backend -n ai-agents
```

### Step 6: Apply Split GPU Deployments

```bash
cd /home/guruai/compose/aidev/k8s-manifests

# Apply Ollama deployment (Node 1)
kubectl apply -f services/ollama-dedicated.yaml

# Apply Backend deployment (Node 2)
kubectl apply -f services/backend-dedicated.yaml

# Update Nginx config
kubectl apply -f base/nginx-configmap.yaml
kubectl rollout restart deployment harvis-ai-nginx -n ai-agents
```

### Step 7: Verify Pod Placement

Check that pods are scheduled on correct GPU nodes:

```bash
kubectl get pods -n ai-agents -o wide | grep -E 'ollama|backend'
```

Expected output:
```
harvis-ai-ollama-xxxxx    1/1   Running   ...   node-gpu-1
harvis-ai-backend-xxxxx   1/1   Running   ...   node-gpu-2
```

Verify GPU allocation:

```bash
# On Node 1 (node-gpu-1) - should show Ollama using GPU
kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=ollama -o jsonpath='{.items[0].metadata.name}') -- nvidia-smi

# On Node 2 (node-gpu-2) - should show Backend using GPU
kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=backend -o jsonpath='{.items[0].metadata.name}') -- nvidia-smi
```

### Step 8: Verify NFS Mounts

Check that both pods can access NFS storage:

```bash
# Ollama pod
kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=ollama -o jsonpath='{.items[0].metadata.name}') -- df -h | grep nfs

# Backend pod
kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=backend -o jsonpath='{.items[0].metadata.name}') -- df -h | grep nfs
```

### Step 9: Test Functionality

```bash
# Test Ollama API
kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=ollama -o jsonpath='{.items[0].metadata.name}') -- curl http://localhost:11434/api/tags

# Test Backend API
kubectl port-forward -n ai-agents svc/harvis-ai-backend 8000:8000 &
curl http://localhost:8000/docs
```

## Node Labels

Nodes are labeled for GPU workload distribution:

```bash
kubectl get nodes --show-labels | grep gpu-workload
```

- `gpu-workload=ollama` - Node 1 (node-gpu-1)
- `gpu-workload=ml-backend` - Node 2 (node-gpu-2)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    NFS Server (Control Plane)                │
│                    192.168.1.195                             │
│   /srv/nfs/ml-models-cache  │  /srv/nfs/ollama-models       │
└────────────────┬────────────────────────┬───────────────────┘
                 │                        │
        ┌────────▼────────┐      ┌───────▼────────┐
        │   Node 1 (GPU)  │      │  Node 2 (GPU)  │
        │   node-gpu-1        │      │ node-gpu-2│
        │                 │      │                 │
        │  ┌───────────┐  │      │  ┌──────────┐  │
        │  │  Ollama   │  │      │  │ Backend  │  │
        │  │    Pod    │  │      │  │   Pod    │  │
        │  │           │  │      │  │          │  │
        │  │ GPU: 24GB │  │      │  │GPU: 24GB │  │
        │  └─────┬─────┘  │      │  └────┬─────┘  │
        │        │NFS     │      │       │NFS     │
        └────────┼────────┘      └───────┼────────┘
                 │                       │
                 └───────────┬───────────┘
                             │
                    ┌────────▼────────┐
                    │  Nginx Proxy    │
                    │ (Load Balancer) │
                    │  Port 8080/8443 │
                    └─────────────────┘
```

## Monitoring and Debugging

### Check Pod Logs

```bash
# Ollama logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=ollama -f

# Backend logs
kubectl logs -n ai-agents -l app.kubernetes.io/component=backend -f
```

### GPU Usage Monitoring

```bash
# Watch GPU usage on both nodes
watch -n 1 'kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=ollama -o jsonpath="{.items[0].metadata.name}") -- nvidia-smi'

watch -n 1 'kubectl exec -n ai-agents $(kubectl get pods -n ai-agents -l app.kubernetes.io/component=backend -o jsonpath="{.items[0].metadata.name}") -- nvidia-smi'
```

### NFS Troubleshooting

```bash
# Check NFS exports on server
showmount -e 192.168.1.195

# Check NFS mounts in pods
kubectl exec -n ai-agents POD_NAME -- mount | grep nfs

# Check NFS server logs
journalctl -u nfs-kernel-server -f
```

## Rollback Procedure

If you need to rollback to the merged deployment:

```bash
# Delete split deployments
kubectl delete -f k8s-manifests/services/ollama-dedicated.yaml
kubectl delete -f k8s-manifests/services/backend-dedicated.yaml

# Revert kustomization.yaml to use merged-ollama-backend.yaml
# Then apply:
kubectl apply -f k8s-manifests/services/merged-ollama-backend.yaml
```

## Performance Expectations

With this split architecture, you should see:

1. **Faster voice processing**: Whisper STT has dedicated GPU
2. **Faster LLM responses**: Ollama has full 24GB for model inference
3. **True parallel execution**: Voice transcription while generating responses
4. **No GPU contention**: Workloads never compete for same GPU
5. **Shared model caching**: Models downloaded once, accessible by all

## Future Scaling

This architecture supports:

- **Horizontal scaling**: Add more Ollama or Backend replicas on additional GPU nodes
- **Model replication**: ReadWriteMany allows multiple replicas to share same models
- **Load balancing**: K8s can load balance across multiple Ollama instances
- **Fault tolerance**: If one node fails, reschedule to available GPU nodes
