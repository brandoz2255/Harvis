# Artifact System Deployment Guide

This guide covers deploying the artifact generation system for Harvis AI with:
- **Docker Compose**: Simple single-node setup with local volume
- **Kubernetes**: Multi-node setup with isolated code execution

## What Was Created

### Backend Components

| File | Purpose |
|------|---------|
| `python_back_end/artifacts_build_jobs_schema.sql` | Database schema for build jobs |
| `python_back_end/artifacts/executor_models.py` | Pydantic models for build jobs |
| `python_back_end/artifacts/build_manager.py` | Job queue and K8s orchestration |
| `python_back_end/artifacts/routes.py` | Updated with build job endpoints |
| `python_back_end/executor_service/main.py` | FastAPI app for executor pods |
| `python_back_end/executor_service/` | Executor service code |
| `python_back_end/Dockerfile.executor` | Docker image for executor |
| `python_back_end/requirements-executor.txt` | Executor dependencies |

### Kubernetes Manifests

| File | Purpose |
|------|---------|
| `k8s-manifests/services/artifact-executor-namespace.yaml` | Executor namespace |
| `k8s-manifests/services/artifact-executor.yaml` | Executor deployment + service |
| `k8s-manifests/services/backend-rockyvms.yaml` | Backend for RockyVMs |

### Docker Compose Updates

| File | Changes |
|------|---------|
| `docker-compose.yaml` | Added artifact_data volume + ARTIFACT_STORAGE_DIR env |

## Architecture Overview

### Docker Compose (Simple)
```
┌─────────────────────────────────────┐
│         Docker Compose Stack        │
├─────────────────────────────────────┤
│  Backend Container                  │
│  ├─ Document generation (xlsx, docx)│
│  ├─ Code storage (Next.js apps)     │
│  └─ Sandpack preview (client-side)  │
│           │                         │
│           ▼                         │
│  artifact_data:/data/artifacts      │
└─────────────────────────────────────┘
```

### Kubernetes (Isolated)
```
┌─────────────────────────────────────────────────────────────┐
│                    RockyVMs Cluster                        │
├─────────────────────────────────────────────────────────────┤
│  Node 1-2 (Backend)        │  Node 3 (Executor)            │
│  ┌─────────────────────┐   │  ┌──────────────────────┐     │
│  │  Harvis Backend     │   │  │  Artifact Executor   │     │
│  │  - API endpoints    │   │  │  - npm install       │     │
│  │  - Doc generation   │   │  │  - next build        │     │
│  │  - Job queue mgmt   │◄──┼──┤  - next start        │     │
│  │  - Sandpack preview │   │  └──────────────────────┘     │
│  └─────────────────────┘   │                               │
│           │                │  Namespace: artifact-executor │
│           └────────────────┼───────────┐                   │
│                            ▼           │                   │
│              ┌─────────────────────┐   │                   │
│              │  NFS PVC            │   │                   │
│              │  harvis-artifacts   │   │                   │
│              │  /data/artifacts    │◄──┘                   │
│              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

## Deployment Steps

### 1. Database Migration

Run the build jobs schema:

```bash
# Docker Compose
docker exec -i pgsql-db psql -U pguser -d database < python_back_end/artifacts_build_jobs_schema.sql

# Kubernetes
kubectl exec -i <postgres-pod> -n ai-agents -- psql -U pguser -d database < python_back_end/artifacts_build_jobs_schema.sql
```

### 2. Docker Compose Deployment

```bash
# Build and start services
docker-compose up --build -d

# The backend will automatically have:
# - artifact_data volume mounted at /data/artifacts
# - ARTIFACT_STORAGE_DIR environment variable set
```

### 3. Kubernetes Deployment

#### Build Executor Image

```bash
# Build executor Docker image
cd python_back_end
docker build -f Dockerfile.executor -t harvis-artifact-executor:latest .

# Push to registry (if using private registry)
docker tag harvis-artifact-executor:latest <registry>/harvis-artifact-executor:latest
docker push <registry>/harvis-artifact-executor:latest
```

#### Deploy to Kubernetes

```bash
# 1. Apply artifact storage PVC (if not already applied)
kubectl apply -f k8s-manifests/storage/artifact-storage.yaml

# 2. Create executor namespace
kubectl apply -f k8s-manifests/services/artifact-executor-namespace.yaml

# 3. Deploy executor
kubectl apply -f k8s-manifests/services/artifact-executor.yaml

# 4. Deploy backend (RockyVMs version)
kubectl apply -f k8s-manifests/services/backend-rockyvms.yaml

# 5. Verify deployments
kubectl get pods -n artifact-executor
kubectl get pods -n ai-agents
```

## How It Works

### Document Generation (Excel, Word, PDF, PPTX)

1. LLM outputs artifact manifest
2. Backend stores in `artifacts` table
3. Background task generates file:
   - `spreadsheet` → openpyxl → .xlsx
   - `document` → python-docx → .docx
   - `pdf` → weasyprint/reportlab → .pdf
   - `presentation` → python-pptx → .pptx
4. File saved to `/data/artifacts`
5. User downloads via `/api/artifacts/{id}/download`

### Website/App Generation (Next.js)

1. LLM outputs artifact manifest with code
2. Backend stores in `artifacts` table (status: ready)
3. Client can immediately preview via Sandpack (client-side sandbox)
4. Optional: Create build job for server-side execution:
   ```bash
   POST /api/artifacts/{artifact_id}/build
   ```
5. Build manager queues job
6. Executor pod (on rockyvm3):
   - Receives build request
   - Writes files to workspace
   - Runs `npm install`
   - Runs `next build`
   - Starts `next start`
7. App accessible via preview URL
8. Auto-cleanup after 24 hours

## API Endpoints

### Artifact Management
- `POST /api/artifacts/generate` - Create new artifact
- `GET /api/artifacts/{id}` - Get artifact metadata
- `GET /api/artifacts/{id}/download` - Download document
- `GET /api/artifacts/{id}/preview` - Get code preview
- `DELETE /api/artifacts/{id}` - Delete artifact

### Build Jobs (New)
- `POST /api/artifacts/{id}/build` - Create build job
- `GET /api/artifacts/{id}/build` - Get build status
- `POST /api/artifacts/{id}/build/stop` - Stop build
- `POST /api/artifacts/build-status` - Executor callback (internal)
- `GET /api/artifacts/builds/active` - List active builds (admin)

## Configuration

### Environment Variables

**Backend:**
```bash
ARTIFACT_STORAGE_DIR=/data/artifacts
ARTIFACT_EXECUTOR_NAMESPACE=artifact-executor
ARTIFACT_EXECUTOR_SERVICE=http://artifact-executor.artifact-executor.svc.cluster.local:8080
ARTIFACT_EXECUTOR_NODE=rockyvm3
ARTIFACT_PORT_START=30000
ARTIFACT_PORT_END=31000
```

**Executor:**
```bash
BACKEND_URL=http://harvis-ai-backend.ai-agents.svc.cluster.local:8000
EXECUTOR_WORKSPACE=/workspace
ARTIFACTS_DIR=/data/artifacts
```

## Testing

### Test Document Generation

1. Ask LLM to create a spreadsheet:
   ```
   "Create an Excel file with sales data for Q1-Q4"
   ```
2. Check artifact status: `GET /api/artifacts/{id}`
3. Download: Click download button or `GET /api/artifacts/{id}/download`

### Test Next.js App

1. Ask LLM to create a website:
   ```
   "Create a simple todo app with React"
   ```
2. Preview in chat (Sandpack loads immediately)
3. For server-side execution:
   ```bash
   curl -X POST /api/artifacts/{id}/build \
     -H "Authorization: Bearer <token>"
   ```
4. Poll build status: `GET /api/artifacts/{id}/build`
5. Access preview URL when ready

## Monitoring

### View Active Builds
```bash
kubectl exec -it <backend-pod> -n ai-agents -- psql -U pguser -d database -c "SELECT * FROM artifact_active_builds;"
```

### Build Statistics
```bash
kubectl exec -it <backend-pod> -n ai-agents -- psql -U pguser -d database -c "SELECT * FROM artifact_build_stats;"
```

### Cleanup Expired Jobs
```bash
# This runs automatically every hour, but can be triggered manually:
kubectl exec -it <backend-pod> -n ai-agents -- psql -U pguser -d database -c "SELECT cleanup_expired_build_jobs();"
```

## Troubleshooting

### Build Job Stuck in "queued"
- Check executor pod is running: `kubectl get pods -n artifact-executor`
- Check backend logs: `kubectl logs -n ai-agents <backend-pod>`
- Verify build manager initialized in main.py

### Executor Pod Fails to Start
- Check image exists: `docker images | grep artifact-executor`
- Check node selector (rockyvm3): `kubectl get nodes`
- Check PVC is bound: `kubectl get pvc -n artifact-executor`

### Preview URL Not Working
- Check network policy allows traffic
- Verify port allocation (30000-31000)
- Check executor logs: `kubectl logs -n artifact-executor <executor-pod>`

## Security Considerations

1. **Isolation**: Executor runs on separate node (rockyvm3) in separate namespace
2. **Network Policy**: Restricts egress to only necessary services
3. **Resource Limits**: Each app limited to 1GB RAM, 1000m CPU
4. **Auto-cleanup**: Builds auto-stop after 24 hours
5. **Callback Token**: Optional token for executor-backend communication

## Next Steps

1. **Initialize Build Manager**: Add to `main.py` startup:
   ```python
   from artifacts.build_manager import ArtifactBuildManager
   
   @app.on_event("startup")
   async def startup_event():
       app.state.pg_pool = await asyncpg.create_pool(...)
       app.state.artifact_build_manager = ArtifactBuildManager(app.state.pg_pool)
       await app.state.artifact_build_manager.start_queue_processor()
   ```

2. **Frontend Updates**: ArtifactBlock.tsx already has preview support

3. **Ingress Configuration**: Add ingress rules for preview URLs

4. **Monitoring**: Set up alerts for failed builds

## Files Summary

Created/Modified:
- ✅ `docker-compose.yaml` - Added artifact storage
- ✅ `python_back_end/artifacts_build_jobs_schema.sql`
- ✅ `python_back_end/artifacts/executor_models.py`
- ✅ `python_back_end/artifacts/build_manager.py`
- ✅ `python_back_end/artifacts/routes.py` - Updated
- ✅ `python_back_end/executor_service/main.py`
- ✅ `python_back_end/Dockerfile.executor`
- ✅ `python_back_end/requirements-executor.txt`
- ✅ `k8s-manifests/services/artifact-executor-namespace.yaml`
- ✅ `k8s-manifests/services/artifact-executor.yaml`
- ✅ `k8s-manifests/services/backend-rockyvms.yaml`

Ready for deployment! 🚀
