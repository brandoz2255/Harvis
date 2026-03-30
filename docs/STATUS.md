# Harvis AI Deployment Status & Fixes

**Date**: 2025-09-20
**Session**: FluxCD GitOps Pipeline Setup & Backend Authentication Fixes

## Current Status

### ✅ **FIXED - Infrastructure Issues**
1. **PVC Issue Resolved**: `ollama-model-cache` PVC now properly bound (50Gi)
2. **Nginx Proxy Fixed**: API calls now correctly route to backend (removed trailing slash)
3. **Backend Pods Running**: 2/2 containers running with proper secrets

### ❌ **ACTIVE ISSUE - Database Connection**
**Error**: `socket.gaierror: [Errno -2] Name or service not known`
**Root Cause**: Backend can't resolve PostgreSQL hostname in DATABASE_URL
**Impact**: Auth endpoints return 500 errors

---

## Technical Details

### Fixed Issues

#### 1. PVC Mount Problem
- **Issue**: Backend pods stuck in Pending - `persistentvolumeclaim "ollama-model-cache" not found`
- **Root Cause**: Helm upgrade failures left PVC in inconsistent state
- **Fix Applied**:
  - Scaled down deployment
  - Manually created PVC with correct labels
  - Helm adopted existing PVC

#### 2. Nginx API Routing
- **Issue**: All `/api/*` requests returning 404
- **Root Cause**: `proxy_pass http://backend/;` with trailing slash stripped `/api` prefix
- **Fix Applied**: Changed to `proxy_pass http://backend;` in configmap
- **Verification**: `/api/ollama-models` now returns 200

#### 3. Missing Secrets
- **Issue**: `Error: secret "harvis-ai-backend-secret" not found`
- **Fix Applied**: Created secret from backend.env file
- **Command Used**: `kubectl create secret generic harvis-ai-backend-secret --from-env-file=backend.env`

### Current Issue: Database Connection

**Error Stack Trace**:
```
socket.gaierror: [Errno -2] Name or service not known
```

**Affected Endpoints**:
- `/api/auth/login` - 500 Internal Server Error
- `/api/auth/signup` - Likely same issue

**Working Endpoints**:
- `/api/ollama-models` - 200 OK (no DB required)
- `/docs` - 200 OK (FastAPI docs)

**Database Service Status**:
- PostgreSQL pod: `harvis-ai-pgsql-69c48d8df4-2z57v` - Running
- Service: `harvis-ai-pgsql` - ClusterIP active

---

## Next Steps to Fix Database Connection

### 1. Check DATABASE_URL in Secret
```bash
kubectl -n ai-agents get secret harvis-ai-backend-secret -o yaml
# Decode and verify DATABASE_URL points to correct service name
```

### 2. Test Service Resolution
```bash
# From backend pod, test if it can resolve postgres service
kubectl -n ai-agents exec deployment/harvis-ai-merged-ollama-backend -c harvis-backend -- nslookup harvis-ai-pgsql
```

### 3. Verify PostgreSQL Service
```bash
kubectl -n ai-agents describe svc harvis-ai-pgsql
kubectl -n ai-agents get endpoints harvis-ai-pgsql
```

### 4. Expected DATABASE_URL Format
```
postgresql://pguser:pgpassword@harvis-ai-pgsql:5432/database
```

---

## FluxCD GitOps Pipeline Status

### ✅ **Working Components**
- **Flux Controllers**: All healthy (source, kustomize, helm, image-automation)
- **Image Scanning**: Backend/frontend images scanned (14/17 tags found)
- **Git Integration**: Synced to main@sha1:aeeb5777
- **Documentation**: Organized in `docs/flux/` directory

### ⏳ **Planned Implementation**
1. **GitHub Actions Workflow**: Automated builds with semantic versioning
2. **Image Policies**: Switch from `:latest` to semver (1.x range)
3. **Auto-deployment**: Push to main → CI builds → Flux deploys

> **Documentation**: See `docs/flux/README.md` for complete FluxCD setup and troubleshooting guides.

### 🔧 **Helm Release Issue**
- **Status**: Failed (context deadline exceeded)
- **Cause**: Stuck in remediation loop due to previous PVC issues
- **Solution**: Need to clear failed state once DB connection is fixed

---

## Architecture Verification

### Container Network
- **Frontend**: `harvis-ai-frontend:3000` ✅
- **Backend**: `harvis-ai-merged-backend:8000` ✅
- **PostgreSQL**: `harvis-ai-pgsql:5432` ✅
- **Nginx**: `harvis-ai-nginx:80` ✅

### Routing Flow
```
Browser → Nginx (port 80) → Backend (port 8000) → PostgreSQL (port 5432)
         ↓
    Frontend (port 3000)
```

### Current Test Results
- **Nginx → Backend**: ✅ Working
- **Backend → Ollama**: ✅ Working (cloud URL)
- **Backend → PostgreSQL**: ❌ DNS resolution failed

---

## Commands for Debugging Database Issue

```bash
# 1. Check secret contents
kubectl -n ai-agents get secret harvis-ai-backend-secret -o jsonpath='{.data.database-url}' | base64 -d

# 2. Test DNS resolution from backend
kubectl -n ai-agents exec deployment/harvis-ai-merged-ollama-backend -c harvis-backend -- nslookup harvis-ai-pgsql

# 3. Test direct connection
kubectl -n ai-agents exec deployment/harvis-ai-merged-ollama-backend -c harvis-backend -- nc -zv harvis-ai-pgsql 5432

# 4. Check PostgreSQL logs
kubectl -n ai-agents logs deployment/harvis-ai-pgsql --tail=50
```

---

## Success Criteria for Complete Fix

- [ ] Database connection working
- [ ] Auth endpoints returning proper responses
- [ ] Users can login/signup through frontend
- [ ] Helm release status: Ready=True
- [ ] Full GitOps pipeline operational

## Post-Fix: GitOps Pipeline Implementation

Once database issues are resolved:
1. Create GitHub Actions workflow for automated builds
2. Update Flux image policies for semantic versioning
3. Test complete push-to-deploy pipeline
4. Document the "Vercel-style" GitOps workflow

---

**Priority**: Fix DATABASE_URL and PostgreSQL service resolution to restore authentication functionality.