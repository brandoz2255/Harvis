# Harvis AI - Code-Based Document Generation System

## Overview
Implemented a **code-based document generation system** that allows LLMs to generate documents (Excel, Word, PDF, PowerPoint) by writing Python code instead of JSON manifests. This approach is more flexible and easier for LLMs to use correctly.

## Architecture

### Execution Modes

| Environment | Execution Method | Isolation Level |
|-------------|------------------|-----------------|
| **Docker Compose** | Local subprocess in backend container | Medium - runs as appuser (UID 1001) |
| **Kubernetes** | kubectl exec in separate code-executor pod | High - isolated pod per execution |

### Key Components

#### 1. **Code Generator** (`python_back_end/artifacts/code_generator.py`)
- Extracts Python code from LLM responses (looks for ` ```python-doc ` blocks)
- Validates code for required imports and save operations
- Prepares code with boilerplate (OUTPUT_PATH variable, error handling)
- Executes code via subprocess (local) or kubectl (K8s)
- Returns result with output path and file size

#### 2. **Dockerfile.code-executor**
- Based on `python:3.11-slim`
- Pre-installed libraries:
  - `openpyxl` - Excel spreadsheets
  - `python-docx` - Word documents
  - `reportlab` - PDF generation
  - `python-pptx` - PowerPoint presentations
  - `pandas`, `fpdf2` - Additional utilities
- Runs as `appuser` (UID 1001) for security
- Mounts `/data/artifacts` for output

#### 3. **Artifact Instructions** (`python_back_end/prompts/artifact_instructions_code.txt`)
- Comprehensive instructions for LLMs on how to write Python code
- Examples for:
  - Excel spreadsheets with openpyxl
  - Word documents with python-docx
  - PDF reports with reportlab
  - PowerPoint presentations with python-pptx
- Emphasizes using `OUTPUT_PATH` variable

#### 4. **Database Schema** (`python_back_end/artifacts_schema.sql`)
- `artifacts` table: Stores artifact metadata, file paths, mime types
- `artifact_build_jobs` table: Tracks website/app builds in executor pods

## Flow

### Document Generation Flow:
```
1. User: "Create an Excel spreadsheet with sales data"

2. LLM Response:
   "Here's a sales report:
   
   ```python-doc
   import openpyxl
   wb = openpyxl.Workbook()
   ws = wb.active
   ws['A1'] = 'Region'
   # ... more code ...
   wb.save(OUTPUT_PATH)
   ```"

3. Backend Processing:
   - Detects `python-doc` code block
   - Extracts code
   - Generates UUID for artifact
   - Saves code to /data/artifacts/code/{id}/generate.py
   - Executes code (local subprocess or K8s pod)
   - Code generates file at /data/artifacts/{id}/output.xlsx
   - Saves record to database
   - Returns artifact_info with download URL

4. Frontend:
   - Shows cleaned response (code removed)
   - Displays download button for document
   - User can download generated file
```

## Configuration

### Environment Variables

**Backend:**
```bash
ARTIFACT_STORAGE_DIR=/data/artifacts
CODE_EXECUTOR_LOCAL=true          # Docker Compose: run locally
USE_K8S_EXECUTION=true            # Kubernetes: use kubectl
CODE_EXECUTOR_NAMESPACE=artifact-executor
CODE_EXECUTOR_IMAGE=dulc3/harvis-code-executor:latest
```

**Docker Compose:**
```yaml
backend:
  user: "1001:1001"
  environment:
    CODE_EXECUTOR_LOCAL: "true"
  volumes:
    - artifact_data:/data/artifacts
```

**Kubernetes:**
```yaml
# Backend deployment
env:
  - name: USE_K8S_EXECUTION
    value: "true"
  - name: CODE_EXECUTOR_NAMESPACE
    value: "artifact-executor"

# Code executor deployment
# Runs in artifact-executor namespace
# Mounts same PVC as backend
```

## Security Considerations

✅ **Non-root execution** - Runs as UID 1001 (appuser)
✅ **No 777 permissions** - Uses 750 (owner: rwx, group: rx, other: none)
✅ **No Docker socket** - Docker Compose runs code locally, no container spawning
✅ **Resource limits** - Memory (512m-1Gi), CPU (1.0), timeout (60s)
✅ **Code validation** - Checks for required imports, save operations
✅ **Isolation** - K8s runs in separate pods

## Files Created/Modified

### New Files:
- `python_back_end/artifacts/code_generator.py` - Core code generation logic
- `python_back_end/Dockerfile.code-executor` - Executor container image
- `python_back_end/prompts/artifact_instructions_code.txt` - LLM instructions
- `k8s-manifests/services/code-executor.yaml` - K8s deployment
- `python_back_end/artifacts_build_jobs_schema.sql` - Build jobs schema

### Modified Files:
- `python_back_end/main.py` - Integrated code-based generation, added DB saving
- `python_back_end/Dockerfile` - Added document generation libraries
- `python_back_end/artifacts/manifest_parser.py` - Added python-doc block cleaning
- `python_back_end/artifacts/routes.py` - Added build job endpoints
- `docker-compose.yaml` - Added artifact volume, init container, env vars
- `ci_pipeline.sh` - Added code-executor build step
- `init-db.sh` - Added automatic schema loading

## Testing

### Docker Compose:
```bash
# Build and start
docker-compose build backend
docker-compose up -d

# Check logs
docker-compose logs -f backend

# Test
# Ask: "Create an Excel spreadsheet with Q1 sales data"
```

### Kubernetes:
```bash
# Apply manifests
kubectl apply -f k8s-manifests/services/artifact-executor.yaml
kubectl apply -f k8s-manifests/services/backend-rockyvms.yaml

# Run migration
kubectl exec -i <postgres-pod> -n ai-agents -- psql -U pguser -d database < python_back_end/artifacts_schema.sql
kubectl exec -i <postgres-pod> -n ai-agents -- psql -U pguser -d database < python_back_end/artifacts_build_jobs_schema.sql

# Check pods
kubectl get pods -n artifact-executor
kubectl get pods -n ai-agents
```

## Debugging

### Common Issues:

1. **Permission Denied (Errno 13)**
   - Check volume permissions: `chmod 750 /data/artifacts`
   - Ensure running as UID 1001
   - Check init container ran successfully

2. **"No such file or directory" (Errno 2)**
   - Verify artifact_data volume is mounted
   - Check `ARTIFACT_STORAGE_DIR` env var
   - Ensure output directory exists

3. **Code not executing**
   - Check `CODE_EXECUTOR_LOCAL` or `USE_K8S_EXECUTION` env vars
   - Review backend logs for extraction errors
   - Verify code contains `OUTPUT_PATH` usage

4. **Document not appearing in UI**
   - Check database record was created
   - Verify `artifact_info` is returned in response
   - Check file exists at output_path

### Logs to Check:
```bash
# Docker Compose
docker-compose logs -f backend | grep -E "(artifact|document|code)"

# Kubernetes
kubectl logs -n ai-agents deployment/harvis-ai-backend | grep -E "(artifact|document|code)"
kubectl logs -n artifact-executor deployment/harvis-code-executor
```

## Next Steps / Improvements

1. **Frontend UI**: Add preview/thumbnails for generated documents
2. **Error Recovery**: Retry failed document generation with modified code
3. **Caching**: Cache generated documents by content hash
4. **Templates**: Pre-defined templates for common document types
5. **Versioning**: Track versions of generated documents
6. **Cleanup**: Automated cleanup of old generated files

## Summary

This system transforms LLM-generated Python code into actual documents, providing a more natural and flexible way for AI to create spreadsheets, documents, PDFs, and presentations. The dual execution mode (local for Docker Compose, K8s pods for Kubernetes) provides both simplicity and security.

**Key Achievement**: LLMs can now write Python code like they would normally write, and the system automatically compiles it into downloadable documents!
