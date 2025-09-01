# Helm Charts Complete Guide

## Table of Contents
1. [What is Helm?](#what-is-helm)
2. [Helm vs Regular Kubernetes YAML](#helm-vs-regular-kubernetes-yaml)
3. [Helm Chart Structure](#helm-chart-structure)
4. [Templating System](#templating-system)
5. [Values and Configuration](#values-and-configuration)
6. [Harvis AI Chart Architecture](#harvis-ai-chart-architecture)
7. [Deployment and Management](#deployment-and-management)

## What is Helm?

Helm is the **package manager for Kubernetes**, often called the "apt/yum/homebrew for Kubernetes." It helps you:

- **Package applications** into reusable charts
- **Manage complex deployments** with a single command
- **Template configurations** for different environments
- **Version and rollback** deployments
- **Share applications** through chart repositories

### Key Concepts

- **Chart**: A Helm package containing Kubernetes manifests and metadata
- **Release**: An instance of a chart deployed to a Kubernetes cluster  
- **Repository**: A collection of charts that can be shared and downloaded
- **Values**: Configuration parameters that customize chart behavior

## Helm vs Regular Kubernetes YAML

The fundamental difference is that Helm uses **templates** with **variables** instead of static YAML files.

### Regular Kubernetes YAML (Static)

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  labels:
    app: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: my-app
          image: my-app:1.0.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

**Problems with Static YAML:**
- Hard-coded values (image tags, resource limits, replica counts)
- No reusability across environments
- Difficult to maintain multiple configurations
- No conditional logic
- Manual management of related resources

### Helm Template (Dynamic)

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "myapp.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: {{ .Values.service.targetPort }}
              protocol: TCP
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          {{- if .Values.env }}
          env:
            {{- range $key, $value := .Values.env }}
            - name: {{ $key }}
              value: {{ $value | quote }}
            {{- end }}
          {{- end }}
```

**Benefits of Helm Templates:**
- ✅ **Configurable**: Values can be changed without modifying templates
- ✅ **Reusable**: Same chart works across dev/staging/production
- ✅ **Conditional**: Resources can be enabled/disabled based on configuration
- ✅ **DRY**: Shared helper functions eliminate repetition
- ✅ **Validated**: Built-in validation and testing capabilities

## Helm Chart Structure

```
harvis-helm-chart/
├── Chart.yaml          # Chart metadata and dependencies
├── values.yaml         # Default configuration values
├── README.md          # Chart documentation
├── charts/            # Chart dependencies (sub-charts)
└── templates/         # Kubernetes manifest templates
    ├── _helpers.tpl   # Template helper functions
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    ├── secret.yaml
    └── NOTES.txt      # Post-installation notes
```

### Key Files Explained

#### 1. Chart.yaml - Chart Metadata
```yaml
apiVersion: v2
name: harvis-ai
description: Harvis AI Project - Sophisticated AI voice assistant
type: application
version: 0.1.0          # Chart version
appVersion: "1.0.0"     # Application version
keywords:
  - ai
  - voice-assistant
dependencies: []         # Other charts this depends on
```

#### 2. values.yaml - Configuration Schema
```yaml
# Default values for harvis-ai
replicaCount: 1

image:
  repository: nginx
  pullPolicy: IfNotPresent
  tag: ""

service:
  type: ClusterIP
  port: 80

resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "256Mi"
    cpu: "200m"
```

#### 3. _helpers.tpl - Reusable Functions
```yaml
{{/*
Expand the name of the chart.
*/}}
{{- define "harvis-ai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
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
```

## Templating System

Helm uses Go's `text/template` package with additional functions. Here's the syntax:

### Template Actions

| Syntax | Description | Example |
|--------|-------------|---------|
| `{{ .Values.key }}` | Insert value | `{{ .Values.image.tag }}` |
| `{{- if condition }}` | Conditional | `{{- if .Values.enabled }}` |
| `{{ include "template" . }}` | Include template | `{{ include "app.name" . }}` |
| `{{ range .Values.list }}` | Loop | `{{ range .Values.env }}` |
| `{{ toYaml .Values.resources }}` | Function call | `{{ toYaml .Values.resources \| nindent 4 }}` |

### Built-in Objects

| Object | Description | Example |
|--------|-------------|---------|
| `.Values` | Values from values.yaml | `.Values.image.repository` |
| `.Chart` | Chart metadata | `.Chart.Name`, `.Chart.Version` |
| `.Release` | Release information | `.Release.Name`, `.Release.Namespace` |
| `.Template` | Current template info | `.Template.Name` |
| `.Files` | Access to files | `.Files.Get "config.txt"` |

### Template Functions

```yaml
# String manipulation
{{ .Values.name | upper }}              # Convert to uppercase
{{ .Values.name | quote }}              # Add quotes
{{ default "defaultvalue" .Values.key}} # Default value

# YAML manipulation  
{{ toYaml .Values.resources | nindent 4 }} # Convert to YAML with indentation

# Conditionals
{{- if .Values.enabled }}
enabled: true
{{- else }}
enabled: false
{{- end }}

# Loops
{{- range .Values.environments }}
- name: {{ .name }}
  url: {{ .url }}
{{- end }}
```

## Values and Configuration

### Hierarchical Values

Values can be overridden in multiple ways (from lowest to highest priority):

1. **Chart defaults** (`values.yaml`)
2. **Parent chart values** (if subchart)
3. **User-supplied values file** (`-f values-prod.yaml`)
4. **Command-line parameters** (`--set key=value`)

### Example Values Override

```bash
# Using values file
helm install myapp ./chart -f production-values.yaml

# Using command line
helm install myapp ./chart \
  --set image.tag=v2.0.0 \
  --set replicaCount=5 \
  --set resources.limits.memory=1Gi
```

### Complex Value Structures

```yaml
# values.yaml
backend:
  enabled: true
  image:
    repository: myapp/backend
    tag: "1.0.0"
  resources:
    limits:
      cpu: 1000m
      memory: 1Gi
  env:
    DATABASE_URL: "postgresql://localhost:5432/mydb"
    LOG_LEVEL: "INFO"
  
services:
  - name: auth
    port: 8001
    replicas: 3
  - name: api  
    port: 8002
    replicas: 2
```

## Harvis AI Chart Architecture

Let me explain what I built for your Harvis AI project:

### Chart Overview

The Harvis AI chart manages a complex multi-service application:

```
┌─────────────────────────────────────────────┐
│                 Ingress                     │
│        (harvis.local, n8n.local)           │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│            Nginx Proxy                      │
│    (Load Balancer - Port 80)               │
└─────┬──────────────────────────────┬────────┘
      │                              │
┌─────▼─────────┐           ┌────────▼────────┐
│   Frontend    │           │    Backend      │
│  (Next.js)    │◄──────────┤   (FastAPI)     │
│  Port 3000    │   API     │   Port 8000     │
└───────────────┘  Calls    │   + GPU         │
                            └─────┬───────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │      PostgreSQL          │
                    │   (pgvector/pg15)        │
                    │      Port 5432           │
                    └──────────────────────────┘
                                  ▲
                    ┌─────────────┴─────────────┐
                    │         n8n              │
                    │  (Workflow Automation)    │
                    │      Port 5678           │
                    └──────────────────────────┘
```

### Service Components

#### 1. Nginx Proxy (Entry Point)
```yaml
# templates/nginx-deployment.yaml
spec:
  containers:
    - name: nginx
      image: "nginx:alpine"
      volumeMounts:
        - name: nginx-config
          mountPath: /etc/nginx/nginx.conf
          subPath: nginx.conf
```

**Purpose**: Routes traffic between frontend and backend APIs
**Configuration**: Dynamic nginx.conf generated from ConfigMap
**Networking**: LoadBalancer service exposed on port 80

#### 2. Backend (AI Processing)
```yaml
# templates/backend-deployment.yaml  
spec:
  containers:
    - name: backend
      image: "dulc3/jarvis-backend:latest"
      resources:
        requests:
          nvidia.com/gpu: 1
        limits:
          nvidia.com/gpu: 1
      volumeMounts:
        - name: backend-code
          mountPath: /app
        - name: docker-sock
          mountPath: /var/run/docker.sock
```

**Purpose**: Python FastAPI backend with AI capabilities
**GPU Support**: Configured for NVIDIA GPU access
**Volumes**: Mounts backend code and Docker socket
**Health Checks**: Liveness and readiness probes

#### 3. Frontend (User Interface)  
```yaml
# templates/frontend-deployment.yaml
spec:
  initContainers:
    - name: build-frontend
      image: node:18-alpine
      command: ["sh", "-c"]
      args:
        - |
          npm ci --only=production
          npm run build
          cp -r .next /app/
```

**Purpose**: Next.js frontend application
**Build Process**: InitContainer builds the application
**Configuration**: Environment variables from ConfigMap/Secrets

#### 4. PostgreSQL (Database)
```yaml
# templates/postgresql-deployment.yaml
spec:
  containers:
    - name: postgresql
      image: "pgvector/pgvector:pg15"
      env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: harvis-ai-postgresql-secret
              key: postgres-password
```

**Purpose**: Database with vector extensions for AI embeddings
**Persistence**: PVC for data storage
**Extensions**: pgvector, pg_trgm, btree_gin
**Security**: Password managed via Kubernetes Secret

#### 5. n8n (Workflow Automation)
```yaml
# templates/n8n-deployment.yaml
spec:
  containers:
    - name: n8n
      image: "n8nio/n8n:latest"
      env:
        - name: DB_TYPE
          value: "postgres"
        - name: DB_POSTGRES_HOST
          value: "harvis-ai-pgsql"
```

**Purpose**: Workflow automation and integration platform
**Database**: Connected to PostgreSQL for persistence
**Access**: Basic authentication with configurable credentials

### Configuration Management

#### Secrets (Sensitive Data)
```yaml
# templates/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: harvis-ai-backend-secret
stringData:
  jwt-secret: {{ .Values.backend.env.JWT_SECRET | quote }}
  openai-api-key: {{ .Values.backend.env.OPENAI_API_KEY | quote }}
```

#### ConfigMaps (Non-sensitive Configuration)
```yaml
# templates/configmaps.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: harvis-ai-backend-config
data:
  ENVIRONMENT: "production"
  LOG_LEVEL: "INFO"
  CORS_ORIGINS: "*"
```

#### Persistent Volumes
```yaml
# templates/pvcs.yaml
{{- if .Values.persistence.pgsqlData.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: harvis-ai-pgsql-pvc
spec:
  accessModes:
    - {{ .Values.persistence.pgsqlData.accessMode }}
  resources:
    requests:
      storage: {{ .Values.persistence.pgsqlData.size }}
{{- end }}
```

### Key Differences from Docker Compose

| Aspect | Docker Compose | Helm Chart |
|--------|----------------|------------|
| **Configuration** | Single docker-compose.yml | Multiple template files + values.yaml |
| **Customization** | Environment files | Values hierarchy and templating |
| **Networking** | Docker networks | Kubernetes Services and Ingress |
| **Storage** | Docker volumes | PersistentVolumeClaims |
| **Scaling** | Manual container scaling | Kubernetes ReplicaSets + HPA |
| **Health Checks** | Basic health checks | Liveness/Readiness probes |
| **Security** | Environment variables | Secrets + ServiceAccounts + RBAC |
| **Load Balancing** | External load balancer | Kubernetes Services + Ingress |

### Template Logic Examples

#### Conditional Resources
```yaml
{{- if .Values.nginx.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "harvis-ai.fullname" . }}-nginx
# ... deployment spec
{{- end }}
```

#### Dynamic Resource Allocation
```yaml
resources:
  {{- if .Values.backend.resources.requests }}
  requests:
    {{- if .Values.backend.resources.requests.memory }}
    memory: {{ .Values.backend.resources.requests.memory }}
    {{- end }}
    {{- if .Values.backend.resources.requests.cpu }}
    cpu: {{ .Values.backend.resources.requests.cpu }}
    {{- end }}
    {{- if .Values.backend.resources.requests."nvidia.com/gpu" }}
    nvidia.com/gpu: {{ .Values.backend.resources.requests."nvidia.com/gpu" }}
    {{- end }}
  {{- end }}
```

#### Service Discovery
```yaml
env:
  - name: DATABASE_URL
    value: "postgresql://{{ .Values.postgresql.auth.username }}:{{ .Values.postgresql.auth.password }}@{{ include "harvis-ai.fullname" . }}-pgsql:5432/{{ .Values.postgresql.auth.database }}"
```

## Deployment and Management

### Basic Commands

```bash
# Install chart
helm install harvis-ai ./harvis-helm-chart

# Upgrade existing release
helm upgrade harvis-ai ./harvis-helm-chart

# Rollback to previous version
helm rollback harvis-ai 1

# Uninstall release
helm uninstall harvis-ai

# List releases
helm list

# Get release status
helm status harvis-ai

# Get release values
helm get values harvis-ai
```

### Advanced Deployment

```bash
# Install with custom values
helm install harvis-ai ./harvis-helm-chart \
  --values production-values.yaml \
  --set backend.image.tag=v2.1.0 \
  --set postgresql.auth.password=secure-password \
  --namespace harvis-ai \
  --create-namespace

# Dry run (test without installing)
helm install harvis-ai ./harvis-helm-chart --dry-run --debug

# Template rendering (see generated YAML)
helm template harvis-ai ./harvis-helm-chart

# Validate chart
helm lint ./harvis-helm-chart
```

### Environment-Specific Deployments

```bash
# Development
helm install harvis-dev ./harvis-helm-chart -f values-dev.yaml

# Staging  
helm install harvis-staging ./harvis-helm-chart -f values-staging.yaml

# Production
helm install harvis-prod ./harvis-helm-chart -f values-production.yaml
```

This Helm chart transforms your complex Docker Compose setup into a production-ready, scalable, and maintainable Kubernetes deployment with proper configuration management, security, and operational best practices.