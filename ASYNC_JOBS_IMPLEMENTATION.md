# Async Job System Implementation

## Overview
Complete async job queue system for document generation using PostgreSQL (pg-boss compatible) with Server-Sent Events (SSE) for real-time updates.

## Architecture

```
┌─────────────┐     POST /api/jobs     ┌─────────────────┐
│   Frontend  │ ─────────────────────> │  Next.js API    │
│  (React)    │                        │  (Create Job)   │
└─────────────┘                        └────────┬────────┘
       │                                        │
       │  SSE Connection                        │ INSERT job
       │  /api/jobs/[id]/events                 │ into Postgres
       │                                        ▼
       │                               ┌─────────────────┐
       │                               │  document_jobs  │
       │                               │     table       │
       │                               └────────┬────────┘
       │                                        │
       │                               ┌────────▼────────┐
       │                               │  job_queue      │
       │                               │  (Python)       │
       │                               └────────┬────────┘
       │                                        │
       │                               ┌────────▼────────┐
       │                               │  Worker Process │
       │                               │  (Docker/K8s)   │
       │                               │                 │
       │                               │  - Generate doc │
       │                               │  - Save artifact│
       │                               │  - NOTIFY       │
       │                               └────────┬────────┘
       │                                        │
       │                          NOTIFY triggers
       │                          SSE push
       │                                        │
       ▼────────────────────────────────────────┘
┌─────────────┐
│   UPDATE    │
│   UI with   │
│  Artifact   │
└─────────────┘
```

## Files Created

### Database
- `front_end/newjfrontend/db/migrations/001_add_document_jobs.sql` - Schema with triggers and indexes

### Backend (Python)
- `python_back_end/job_queue.py` - Job queue implementation with asyncpg
- `python_back_end/workers/document_worker.py` - Document generation worker
- Updated `python_back_end/main.py` - Added job enqueue/status endpoints

### Frontend (Next.js)
- `front_end/newjfrontend/app/api/jobs/route.ts` - Job creation endpoint
- `front_end/newjfrontend/app/api/jobs/[jobId]/events/route.ts` - SSE endpoint
- `front_end/newjfrontend/components/artifacts/DocumentGenerator.tsx` - Real-time document component
- Updated `front_end/newjfrontend/components/artifacts/index.ts` - Added exports

## Database Schema

### document_jobs table
```sql
- id (UUID, PK)
- user_id (INTEGER, FK)
- session_id (UUID, FK)
- message_id (UUID, FK)
- job_type (VARCHAR: spreadsheet, document, pdf, presentation)
- status (VARCHAR: pending, processing, completed, failed)
- payload (JSONB: code, title)
- result (JSONB: artifact_id, download_url)
- priority (INTEGER)
- retry_count/max_retries
- timestamps (created_at, started_at, completed_at, expires_at)
```

### Features
- LISTEN/NOTIFY triggers for real-time updates
- Automatic cleanup of old jobs
- Job statistics view
- Indexed for performance

## API Endpoints

### POST /api/jobs
Create a new document generation job.

**Request:**
```json
{
  "code": "python code...",
  "documentType": "spreadsheet",
  "title": "Sales Report",
  "sessionId": "uuid",
  "userId": 123,
  "priority": 0
}
```

**Response:**
```json
{
  "jobId": "uuid",
  "status": "pending"
}
```

### GET /api/jobs/[jobId]/events
Server-Sent Events stream for job status updates.

**Events:**
- `status` - Job status changed (pending, processing)
- `job-complete` - Job finished successfully
- `job-failed` - Job failed with error
- `error` - Connection/validation error

### POST /api/jobs/enqueue (Backend)
Enqueue job in Python job queue.

### GET /api/jobs/[jobId]/status (Backend)
Get current job status.

## Deployment

### Docker Compose
Add worker service:

```yaml
worker:
  build:
    context: ./python_back_end
    dockerfile: Dockerfile.worker
  command: python workers/document_worker.py
  environment:
    - DATABASE_URL=postgresql://pguser:pgpassword@pgsql:5432/database
  depends_on:
    - pgsql
    - backend
  restart: unless-stopped
```

### Kubernetes
See `k8s-manifests/worker-deployment.yaml`

## Usage Flow

1. **User requests document generation** in chat
2. **Backend creates job** and returns jobId immediately
3. **Frontend shows DocumentGenerator component** with loading state
4. **Component connects to SSE** /api/jobs/[jobId]/events
5. **Worker picks up job** from queue and generates document
6. **Worker updates database** with result and triggers NOTIFY
7. **SSE receives notification** and updates frontend
8. **DocumentGenerator shows ArtifactBlock** with preview/download

## Benefits

✅ No page refresh needed
✅ Real-time progress updates
✅ Handles long-running jobs (1+ minute)
✅ Survives backend restarts
✅ Scales horizontally (multiple workers)
✅ Uses existing Postgres (no Redis needed)
✅ Compatible with both Docker and K8s

## Next Steps

1. Update chat flow to use async jobs
2. Create K8s worker deployment
3. Update Docker Compose
4. Test complete flow
5. Add more job types (code generation, research, etc.)

