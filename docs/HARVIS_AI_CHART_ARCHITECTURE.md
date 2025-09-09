# Harvis AI Helm Chart Architecture

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Service Components](#service-components)
3. [Template Structure Analysis](#template-structure-analysis)
4. [Configuration Management](#configuration-management)
5. [Networking Architecture](#networking-architecture)
6. [Storage Strategy](#storage-strategy)
7. [Security Implementation](#security-implementation)
8. [Deployment Flow](#deployment-flow)

## Architecture Overview

The Harvis AI Helm chart transforms a complex Docker Compose setup into a production-ready Kubernetes deployment with 5 main services:

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │                 Ingress Layer                   │    │
│  │        (External Access + SSL Termination)     │    │
│  └─────────────────┬───────────────────────────────┘    │
│                    │                                    │
│  ┌─────────────────▼───────────────────────────────┐    │
│  │              Nginx Proxy                       │    │
│  │    (LoadBalancer Service - Port 80/443)       │    │
│  │         Routes: / → Frontend                   │    │
│  │                /api/ → Backend                 │    │
│  └─────┬──────────────────────────────────┬────────┘    │
│        │                                  │             │
│  ┌─────▼─────────┐               ┌────────▼────────┐    │
│  │   Frontend    │               │    Backend      │    │
│  │  (Next.js)    │◄──────────────┤   (FastAPI)     │    │
│  │  ClusterIP    │   Internal    │   ClusterIP     │    │
│  │  Port 3000    │   API Calls   │   Port 8000     │    │
│  │               │               │   + GPU Access  │    │
│  └───────────────┘               └─────┬───────────┘    │
│                                        │                │
│          ┌─────────────────────────────▼──────────┐     │
│          │           PostgreSQL                   │     │
│          │      (pgvector/pgvector:pg15)         │     │
│          │         ClusterIP Port 5432           │     │
│          │    + Vector Extensions for AI         │     │
│          └─────────────────┬───────────────────────┘     │
│                            │                           │
│          ┌─────────────────▼───────────────────────┐   │
│          │              n8n                       │   │
│          │    (Workflow Automation Platform)     │   │
│          │      LoadBalancer Port 5678          │   │
│          │     Connected to PostgreSQL          │   │
│          └─────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Microservices Architecture**: Each component is independently deployable
2. **GPU Resource Management**: Backend optimized for AI workloads with GPU allocation
3. **Service Discovery**: Kubernetes DNS for internal communication
4. **Configuration Separation**: Values-based configuration management
5. **Security First**: Secrets management, RBAC, and network policies
6. **Scalability**: HorizontalPodAutoscaler and resource management
7. **Observability**: Health checks, probes, and monitoring integration

## Service Components

### 1. Nginx Proxy Service

**Role**: Reverse proxy and ingress controller
**Image**: `nginx:alpine`
**Configuration**: Dynamic nginx.conf via ConfigMap

```yaml
# Key template sections from nginx-deployment.yaml
spec:
  containers:
    - name: nginx
      image: "{{ .Values.nginx.image.repository }}:{{ .Values.nginx.image.tag }}"
      volumeMounts:
        - name: nginx-config
          mountPath: /etc/nginx/nginx.conf
          subPath: nginx.conf
          readOnly: true
  volumes:
    - name: nginx-config
      configMap:
        name: {{ include "harvis-ai.fullname" . }}-nginx-config
```

**Routing Logic** (from nginx-configmap.yaml):
```nginx
# Frontend routes - serve Next.js application
location / {
    proxy_pass http://{{ include "harvis-ai.fullname" . }}-frontend:3000;
}

# API routes - proxy to Python backend
location /api/ {
    proxy_pass http://{{ include "harvis-ai.fullname" . }}-backend:8000/api/;
    # CORS headers for API access
}
```

### 2. Backend Service (AI Processing Engine)

**Role**: Python FastAPI backend with AI/ML capabilities
**Image**: `dulc3/jarvis-backend:latest`
**Special Requirements**: NVIDIA GPU access

```yaml
# Key template sections from backend-deployment.yaml
spec:
  containers:
    - name: backend
      image: "{{ .Values.backend.image.repository }}:{{ .Values.backend.image.tag }}"
      resources:
        requests:
          memory: "1Gi"
          cpu: "500m"
          nvidia.com/gpu: 1
        limits:
          memory: "4Gi" 
          cpu: "2"
          nvidia.com/gpu: 1
      volumeMounts:
        - name: backend-code
          mountPath: /app
        - name: embedding
          mountPath: /app/embedding
        - name: docker-sock
          mountPath: /var/run/docker.sock
```

**Features**:
- GPU-accelerated AI processing
- Docker-in-Docker capability via socket mounting
- Persistent volume for embeddings and code
- Health checks with `/health` endpoint
- Environment configuration via ConfigMaps/Secrets

### 3. Frontend Service (User Interface)

**Role**: Next.js React application
**Image**: Built from source using init containers

```yaml
# Build process from frontend-deployment.yaml
initContainers:
  - name: build-frontend
    image: node:18-alpine
    workingDir: /build
    command: ["sh", "-c"]
    args:
      - |
        npm ci --only=production
        npm run build
        cp -r .next /app/
        cp -r public /app/
```

**Features**:
- Production-optimized build process
- Environment-specific configuration
- Integration with backend via relative API calls
- Health checks for application readiness

### 4. PostgreSQL Database

**Role**: Primary data storage with vector extensions
**Image**: `pgvector/pgvector:pg15`

```yaml
# Database configuration from postgresql-deployment.yaml  
env:
  - name: POSTGRES_USER
    value: {{ .Values.postgresql.auth.username | quote }}
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ include "harvis-ai.fullname" . }}-postgresql-secret
        key: postgres-password
  - name: POSTGRES_INITDB_ARGS
    value: {{ .Values.postgresql.initdbArgs | quote }}
```

**Extensions** (from configmaps.yaml):
```bash
# Initialization script
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS btree_gin;
EOSQL
```

### 5. n8n Workflow Automation

**Role**: Workflow automation and integration platform
**Image**: `n8nio/n8n:latest`

```yaml
# Configuration from n8n-deployment.yaml
env:
  - name: DB_TYPE
    value: "postgres"
  - name: DB_POSTGRES_HOST
    value: "{{ include "harvis-ai.fullname" . }}-pgsql"
  - name: N8N_BASIC_AUTH_ACTIVE
    value: {{ .Values.n8n.auth.basicAuthActive | quote }}
```

## Template Structure Analysis

### Chart File Organization

```
harvis-helm-chart/
├── Chart.yaml                 # Chart metadata
├── values.yaml               # Default configuration
├── README.md                 # Documentation
└── templates/
    ├── _helpers.tpl          # Reusable template functions
    ├── configmaps.yaml       # Non-sensitive configuration
    ├── secrets.yaml          # Sensitive data
    ├── pvcs.yaml            # Storage claims
    ├── nginx-deployment.yaml # Nginx proxy + service
    ├── nginx-configmap.yaml  # Nginx configuration
    ├── backend-deployment.yaml # Backend + service
    ├── frontend-deployment.yaml # Frontend + service
    ├── postgresql-deployment.yaml # Database + service
    ├── n8n-deployment.yaml   # n8n + service
    ├── ingress.yaml         # External access rules
    └── serviceaccount.yaml  # RBAC configuration
```

### Helper Template Functions (_helpers.tpl)

```yaml
{{/*
Generate consistent resource names
*/}}
{{- define "harvis-ai.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate consistent labels for all resources
*/}}
{{- define "harvis-ai.labels" -}}
helm.sh/chart: {{ include "harvis-ai.chart" . }}
{{ include "harvis-ai.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
```

## Configuration Management

### Values Hierarchy

The chart supports multiple levels of configuration override:

1. **Default values** (values.yaml)
2. **Environment-specific values** (values-prod.yaml)
3. **Command-line overrides** (--set flags)

### Key Configuration Sections

#### Global Configuration
```yaml
global:
  imageRegistry: ""          # Override default registry
  storageClass: ""          # Default storage class
```

#### Service-Specific Configuration
```yaml
backend:
  enabled: true
  image:
    repository: dulc3/jarvis-backend
    tag: latest
  resources:
    requests:
      nvidia.com/gpu: 1
  env:
    DATABASE_URL: "postgresql://..."
    OLLAMA_URL: "http://ollama:11434"
```

#### Security Configuration
```yaml
postgresql:
  auth:
    username: pguser
    password: pgpassword    # Should be overridden in production
    database: database

secrets:
  jwtSecret: "change-this-in-production"
  apiKeys:
    openai: ""
    ollama: ""
```

### Configuration Template Patterns

#### Environment Variables
```yaml
# Static environment variables
env:
  - name: ENVIRONMENT
    value: "production"
  - name: LOG_LEVEL
    value: {{ .Values.logLevel | quote }}

# Dynamic environment variables from values
{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}

# Secret environment variables
{{- range $key, $secret := .Values.secrets }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ include "harvis-ai.fullname" $ }}-secret
      key: {{ $secret.key }}
{{- end }}
```

## Networking Architecture

### Service Discovery

Services communicate using Kubernetes DNS:

```yaml
# Backend connects to database
DATABASE_URL: "postgresql://{{ .Values.postgresql.auth.username }}:{{ .Values.postgresql.auth.password }}@{{ include "harvis-ai.fullname" . }}-pgsql:5432/{{ .Values.postgresql.auth.database }}"

# Frontend connects to backend via nginx proxy
BACKEND_URL: "http://{{ include "harvis-ai.fullname" . }}-backend:8000"

# n8n connects to database
DB_POSTGRES_HOST: "{{ include "harvis-ai.fullname" . }}-pgsql"
```

### Service Types and Exposure

```yaml
# External services (LoadBalancer)
nginx:
  service:
    type: LoadBalancer
    port: 80

n8n:
  service:
    type: LoadBalancer  
    port: 5678

# Internal services (ClusterIP)
backend:
  service:
    type: ClusterIP
    port: 8000

frontend:
  service:
    type: ClusterIP
    port: 3000

postgresql:
  service:
    type: ClusterIP
    port: 5432
```

### Ingress Configuration

```yaml
# Optional ingress for custom domains
ingress:
  enabled: true
  hosts:
    - host: harvis.local
      paths:
        - path: /
          service:
            name: nginx
            port: 80
    - host: harvis-api.local
      paths:
        - path: /api
          service:
            name: backend
            port: 8000
```

## Storage Strategy

### Persistent Volume Claims

```yaml
# Database storage (critical data)
{{- if .Values.persistence.pgsqlData.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "harvis-ai.fullname" . }}-pgsql-pvc
spec:
  accessModes:
    - {{ .Values.persistence.pgsqlData.accessMode }}
  resources:
    requests:
      storage: {{ .Values.persistence.pgsqlData.size }}
{{- end }}

# Backend application data
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "harvis-ai.fullname" . }}-backend-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

### Volume Mount Strategy

```yaml
# Backend volume mounts
volumeMounts:
  - name: backend-code          # Application code
    mountPath: /app
  - name: embedding            # AI embeddings data
    mountPath: /app/embedding
  - name: tmp                  # Temporary files
    mountPath: /tmp
  - name: docker-sock          # Docker socket
    mountPath: /var/run/docker.sock

volumes:
  - name: backend-code
    persistentVolumeClaim:
      claimName: {{ include "harvis-ai.fullname" . }}-backend-pvc
  - name: embedding
    persistentVolumeClaim:
      claimName: {{ include "harvis-ai.fullname" . }}-embedding-pvc
  - name: tmp
    emptyDir: {}
  - name: docker-sock
    hostPath:
      path: /var/run/docker.sock
```

## Security Implementation

### Secrets Management

```yaml
# Separate secrets for each component
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "harvis-ai.fullname" . }}-backend-secret
type: Opaque
stringData:
  jwt-secret: {{ .Values.backend.env.JWT_SECRET | quote }}
  openai-api-key: {{ .Values.backend.env.OPENAI_API_KEY | quote }}

# Database credentials
apiVersion: v1
kind: Secret  
metadata:
  name: {{ include "harvis-ai.fullname" . }}-postgresql-secret
type: Opaque
stringData:
  postgres-password: {{ .Values.postgresql.auth.password | quote }}
```

### RBAC Configuration

```yaml
# Service account for pods
{{- if .Values.serviceAccount.create -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "harvis-ai.serviceAccountName" . }}
  labels:
    {{- include "harvis-ai.labels" . | nindent 4 }}
{{- end }}
```

### Security Contexts

```yaml
# Pod-level security
securityContext:
  runAsNonRoot: false  # Required for Docker socket access
  runAsUser: 0
  fsGroup: 0

# Container-level security
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
```

## Deployment Flow

### 1. Pre-deployment Validation

```bash
# Validate chart syntax
helm lint ./harvis-helm-chart

# Test template rendering
helm template harvis-ai ./harvis-helm-chart --debug

# Dry run deployment
helm install harvis-ai ./harvis-helm-chart --dry-run --debug
```

### 2. Resource Creation Order

1. **ConfigMaps and Secrets** (configuration)
2. **PersistentVolumeClaims** (storage)
3. **ServiceAccount** (RBAC)
4. **PostgreSQL** (database foundation)
5. **Backend** (depends on database)
6. **Frontend** (depends on backend)
7. **Nginx** (depends on frontend + backend)
8. **n8n** (depends on database)
9. **Ingress** (external access)

### 3. Dependency Management

```yaml
# Service dependencies in deployment specs
depends_on:
  - condition: service_healthy
    service: postgresql
  - condition: service_started
    service: backend
```

### 4. Health Checks and Readiness

```yaml
# Liveness probes (restart if unhealthy)
livenessProbe:
  httpGet:
    path: /health
    port: http
  initialDelaySeconds: 30
  periodSeconds: 10

# Readiness probes (traffic routing)  
readinessProbe:
  httpGet:
    path: /health
    port: http
  initialDelaySeconds: 5
  periodSeconds: 5
```

### 5. Post-Deployment Verification

```bash
# Check all pods are running
kubectl get pods -l app.kubernetes.io/name=harvis-ai

# Check services
kubectl get services -l app.kubernetes.io/name=harvis-ai

# Check ingress
kubectl get ingress -l app.kubernetes.io/name=harvis-ai

# Port forward for testing
kubectl port-forward svc/harvis-ai-nginx 8080:80
```

This architecture provides a robust, scalable, and maintainable deployment of the Harvis AI application on Kubernetes, with proper separation of concerns, security best practices, and production-ready configuration management.