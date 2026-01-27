# Harvis AI Workstation Two-GPU Setup

This document describes the two-GPU workstation deployment for high-performance inference.

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        HARVIS AI WORKSTATION CLUSTER                        │
├────────────────────────────────────┬───────────────────────────────────────┤
│  NODE 1: pop-os (RTX 4090 24GB)    │  NODE 2: pop-os-343570d8 (3090Ti 24GB)│
│  ─────────────────────────────     │  ───────────────────────────────────  │
│                                    │                                       │
│  ┌──────────────────────────┐      │  ┌─────────────────────────────────┐  │
│  │  OLLAMA (Dedicated)      │      │  │  ML BACKEND (Dedicated)         │  │
│  │  ────────────────────    │      │  │  ─────────────────────────────  │  │
│  │  • All LLM models        │◄─────│──│  • Whisper STT                  │  │
│  │  • LOCAL fast storage    │ API  │  │  • Chatterbox TTS               │  │
│  │  • Full 24GB VRAM        │ call │  │  • Voice cloning                │  │
│  │  • DeepSeek, Llama, etc  │      │  │  • Full 24GB VRAM for ML        │  │
│  └──────────────────────────┘      │  └─────────────────────────────────┘  │
│                                    │                                       │
│  PVC: ollama-model-cache           │  PVC: nfs-ml-models-cache             │
│  (Local NVMe - fast!)              │  (NFS - load once pattern)            │
└────────────────────────────────────┴───────────────────────────────────────┘
```

## Why This Architecture?

1. **No NFS for LLMs**: NFS is too slow for constant model weight streaming
2. **Network API calls are fast**: Backend calls Ollama over K8s network (just JSON)
3. **Full GPU dedication**: Each GPU is 100% dedicated to its workload
4. **Simple**: No load balancing complexity, no model duplication

## Deployment Files

| File | Description | Node |
|------|-------------|------|
| `ollama-workstation.yaml` | Dedicated Ollama for LLMs | pop-os (RTX 4090) |
| `backend-workstation.yaml` | Dedicated ML Backend (no Ollama) | pop-os-343570d8 (RTX 3090 Ti) |

## Configuration

### Backend ConfigMap

The workstation backend uses:

```yaml
# harvis-ai-backend-workstation-config
OLLAMA_URL: "http://harvis-ai-ollama-workstation:11434"
```

This calls Ollama on Node 1 over the Kubernetes network.

### Edge vs Workstation Comparison

| Setting | Edge (Single GPU/Merged) | Workstation (Two GPU) |
|---------|--------------------------|------------------------|
| OLLAMA_URL | `http://localhost:11434` | `http://harvis-ai-ollama-workstation:11434` |
| ConfigMap | `harvis-ai-backend-config` | `harvis-ai-backend-workstation-config` |
| Ollama | Same pod as backend | Separate pod on Node 1 |
| ML Backend | Same pod as Ollama | Separate pod on Node 2 |

## Storage Strategy

### Node 1 (Ollama - LLMs)
- **Storage**: Local PVC (`ollama-model-cache`) on fast NVMe
- **Why**: LLMs need fast random access for model weights
- **No NFS**: Would be too slow

### Node 2 (Backend - ML)
- **Storage**: NFS PVC (`nfs-ml-models-cache`)
- **Why**: ML models (Whisper, TTS) load once into GPU memory, then inference is all compute
- **Pattern**: "Load once, run in memory" - NFS latency only at startup
- **Fallback**: If NFS is too slow, switch to emptyDir + init container

## Deployment Commands

### Deploy Workstation Setup

```bash
# 1. Apply ConfigMaps
kubectl apply -f k8s-manifests/base/configmaps.yaml

# 2. Deploy Ollama on Node 1
kubectl apply -f k8s-manifests/services/ollama-workstation.yaml

# 3. Deploy Backend on Node 2
kubectl apply -f k8s-manifests/services/backend-workstation.yaml
```

### Verify Deployment

```bash
# Check pods are on correct nodes
kubectl get pods -n ai-agents -o wide | grep workstation

# Expected:
# harvis-ai-ollama-workstation-xxx    pop-os
# harvis-ai-backend-workstation-xxx   pop-os-343570d8

# Test Ollama from backend pod
kubectl exec -n ai-agents deploy/harvis-ai-backend-workstation -- \
  curl -s http://harvis-ai-ollama-workstation:11434/api/tags

# Check backend can reach Ollama
kubectl logs -n ai-agents deploy/harvis-ai-backend-workstation | grep -i ollama
```

## GPU Allocation

| Node | GPU | Workload | VRAM Usage |
|------|-----|----------|------------|
| pop-os | RTX 4090 (24GB) | Ollama LLMs | Up to 24GB for models |
| pop-os-343570d8 | RTX 3090 Ti (24GB) | Whisper + TTS | ~6-10GB typical |

## Troubleshooting

### Pod Not Scheduling

```bash
# Check events
kubectl describe pod <pod-name> -n ai-agents

# Common issues:
# - Volume node affinity conflict
# - Node selector mismatch
kubectl get nodes --show-labels | grep kubernetes.io/hostname
```

### Backend Can't Reach Ollama

```bash
# Test network connectivity
kubectl exec -n ai-agents deploy/harvis-ai-backend-workstation -- \
  curl -v http://harvis-ai-ollama-workstation:11434/api/tags

# Check service endpoints
kubectl get endpoints harvis-ai-ollama-workstation -n ai-agents
```

### ML Models Loading Slowly (NFS)

If NFS is too slow for ML model loading, switch to emptyDir:

```yaml
volumes:
  - name: ml-models-cache
    emptyDir:
      sizeLimit: 50Gi  # Adjust as needed
```

The init container will download models fresh each deployment.

## Switching Between Edge and Workstation

### Use Edge Setup (Single GPU, Merged Pod)
```bash
kubectl delete -f k8s-manifests/services/ollama-workstation.yaml
kubectl delete -f k8s-manifests/services/backend-workstation.yaml
kubectl apply -f k8s-manifests/services/merged-ollama-backend.yaml
```

### Use Workstation Setup (Two GPU, Separate Pods)
```bash
kubectl delete -f k8s-manifests/services/merged-ollama-backend.yaml
kubectl apply -f k8s-manifests/services/ollama-workstation.yaml
kubectl apply -f k8s-manifests/services/backend-workstation.yaml
```

## Network Flow

```
User Request
     │
     ▼
┌─────────────────┐
│    Frontend     │
│   (Nginx/Next)  │
└────────┬────────┘
         │ /api/*
         ▼
┌─────────────────┐         ┌─────────────────┐
│  Backend (ML)   │  HTTP   │  Ollama (LLM)   │
│  Node 2         │────────►│  Node 1         │
│  RTX 3090 Ti    │  :11434 │  RTX 4090       │
└─────────────────┘         └─────────────────┘
     │                              │
     ▼                              ▼
  Whisper                     DeepSeek R1
  Chatterbox                  Llama 3
  TTS/STT                     Mistral
```

## Future Improvements

### LiteLLM Integration
For smarter routing or adding cloud fallback:

```yaml
# LiteLLM can proxy to local Ollama with cloud fallback
model_list:
  - model_name: deepseek-r1
    litellm_params:
      model: ollama/deepseek-r1:70b
      api_base: http://harvis-ai-ollama-workstation:11434
  - model_name: gpt-4
    litellm_params:
      model: openai/gpt-4
      api_key: os.environ/OPENAI_API_KEY
```

### Horizontal Scaling
For more capacity, add more nodes with the same pattern:
- Node 3: Another Ollama instance
- Use Kubernetes service to load balance across Ollama instances
