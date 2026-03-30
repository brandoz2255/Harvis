# Kubernetes Commands - Harvis AI Async Jobs

## Initial Setup (One-Time)

```bash
# Apply database migrations
kubectl exec -it pgsql-pod -- psql -U pguser -d database -f /docker-entrypoint-initdb.d/001_add_document_jobs.sql

# Deploy document workers
kubectl apply -f k8s-manifests/services/document-worker.yaml
```

## Deployment Management

```bash
# Deploy all services
kubectl apply -f k8s-manifests/services/document-worker.yaml

# Verify deployment
kubectl get pods -l app.kubernetes.io/component=document-worker

# Check rollout status
kubectl rollout status deployment/harvis-document-worker

# Rollout restart (if needed)
kubectl rollout restart deployment/harvis-document-worker
```

## Scaling

```bash
# Scale manually to 5 workers
kubectl scale deployment harvis-document-worker --replicas=5

# Check HPA (Horizontal Pod Autoscaler) status
kubectl get hpa harvis-document-worker-hpa

# Watch HPA in real-time
kubectl get hpa harvis-document-worker-hpa -w

# View current queue depth
kubectl exec pgsql-pod -- psql -U pguser -d database -c "SELECT status, COUNT(*) FROM document_jobs GROUP BY status;"
```

## Monitoring & Logs

```bash
# Get all pods
kubectl get pods -l app.kubernetes.io/component=document-worker

# View worker logs
kubectl logs -f deployment/harvis-document-worker

# View specific worker pod logs
kubectl logs -f harvis-document-worker-abc123

# Get pod events
kubectl get events --field-selector involvedObject.name=harvis-document-worker
```

## Troubleshooting

```bash
# Describe pod (check issues)
kubectl describe pod harvis-document-worker-abc123

# Check pod status
kubectl get pods -l app.kubernetes.io/component=document-worker -o wide

# Exec into pod for debugging
kubectl exec -it harvis-document-worker-abc123 -- /bin/sh

# Check resource usage
kubectl top pods -l app.kubernetes.io/component=document-worker
```

## Database Commands (from K8s)

```bash
# Access PostgreSQL from K8s pod
kubectl exec -it pgsql-pod -- psql -U pguser -d database

# Check jobs table
kubectl exec pgsql-pod -- psql -U pguser -d database -c "SELECT id, status, job_type, created_at FROM document_jobs ORDER BY created_at DESC LIMIT 10;"

# Check pending jobs
kubectl exec pgsql-pod -- psql -U pguser -d database -c "SELECT COUNT(*) FROM document_jobs WHERE status IN ('pending', 'processing');"
```

## Deletion & Cleanup

```bash
# Delete deployment
kubectl delete -f k8s-manifests/services/document-worker.yaml

# Delete specific pod (it will be recreated by deployment)
kubectl delete pod harvis-document-worker-abc123

# Force delete stuck pod
kubectl delete pod harvis-document-worker-abc123 --grace-period=0 --force
```

## File Locations

```bash
# K8s manifest file
k8s-manifests/services/document-worker.yaml

# Database migration
front_end/newjfrontend/db/migrations/001_add_document_jobs.sql
```

