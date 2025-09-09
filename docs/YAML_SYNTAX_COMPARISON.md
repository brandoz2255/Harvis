# Helm vs Regular Kubernetes YAML: Syntax Comparison

## Overview

This guide compares the syntax differences between regular Kubernetes YAML manifests and Helm chart templates, showing how Helm transforms static configurations into dynamic, reusable templates.

## Table of Contents
1. [Basic Structure Differences](#basic-structure-differences)
2. [Variable Substitution](#variable-substitution)
3. [Conditional Logic](#conditional-logic)
4. [Loops and Iteration](#loops-and-iteration)
5. [Helper Functions](#helper-functions)
6. [Real-World Examples](#real-world-examples)

## Basic Structure Differences

### Regular Kubernetes YAML
```yaml
# static-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-web-app
  namespace: default
  labels:
    app: my-web-app
    version: v1.0.0
    environment: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-web-app
  template:
    metadata:
      labels:
        app: my-web-app
    spec:
      containers:
      - name: web
        image: nginx:1.21.0
        ports:
        - containerPort: 80
```

### Helm Template
```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  namespace: {{ .Release.Namespace }}
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
        ports:
        - containerPort: {{ .Values.service.targetPort }}
```

## Variable Substitution

### Static Values (Regular YAML)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-web-service
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  selector:
    app: my-web-app
```

### Dynamic Values (Helm Template)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
  - port: {{ .Values.service.port }}
    targetPort: {{ .Values.service.targetPort }}
    protocol: TCP
    name: http
  selector:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
```

**Corresponding values.yaml:**
```yaml
service:
  type: ClusterIP
  port: 80
  targetPort: 8080

image:
  repository: nginx
  tag: "1.21.0"

replicaCount: 3
```

## Conditional Logic

### Static Configuration Problem
In regular Kubernetes YAML, you need separate files for different configurations:

```yaml
# development-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  LOG_LEVEL: "DEBUG"
  ENABLE_METRICS: "false"
---
# production-config.yaml  
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  LOG_LEVEL: "ERROR"
  ENABLE_METRICS: "true"
  METRICS_ENDPOINT: "/metrics"
```

### Helm Conditional Logic
```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
data:
  LOG_LEVEL: {{ .Values.logLevel | quote }}
  {{- if .Values.metrics.enabled }}
  ENABLE_METRICS: "true"
  METRICS_ENDPOINT: {{ .Values.metrics.endpoint | quote }}
  {{- else }}
  ENABLE_METRICS: "false"
  {{- end }}
  {{- if eq .Values.environment "development" }}
  DEBUG_MODE: "true"
  {{- end }}
```

**values.yaml:**
```yaml
environment: production
logLevel: INFO
metrics:
  enabled: true
  endpoint: "/metrics"
```

### Conditional Resource Creation
```yaml
# templates/ingress.yaml
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- if .Values.ingress.className }}
  ingressClassName: {{ .Values.ingress.className }}
  {{- end }}
  rules:
  {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
        {{- range .paths }}
        - path: {{ .path }}
          pathType: {{ .pathType }}
          backend:
            service:
              name: {{ include "myapp.fullname" $ }}
              port:
                number: {{ .port }}
        {{- end }}
  {{- end }}
{{- end }}
```

## Loops and Iteration

### Static Multiple Resources
```yaml
# Multiple separate files needed
---
apiVersion: v1
kind: Service
metadata:
  name: auth-service
spec:
  ports:
  - port: 8001
  selector:
    app: auth
---
apiVersion: v1
kind: Service
metadata:
  name: api-service
spec:
  ports:
  - port: 8002
  selector:
    app: api
---
apiVersion: v1
kind: Service
metadata:
  name: worker-service
spec:
  ports:
  - port: 8003
  selector:
    app: worker
```

### Helm Loop Generation
```yaml
# templates/services.yaml
{{- range .Values.services }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" $ }}-{{ .name }}
  labels:
    {{- include "myapp.labels" $ | nindent 4 }}
    app.kubernetes.io/component: {{ .name }}
spec:
  type: {{ .type | default "ClusterIP" }}
  ports:
  - port: {{ .port }}
    targetPort: {{ .targetPort | default .port }}
    protocol: TCP
    name: http
  selector:
    {{- include "myapp.selectorLabels" $ | nindent 4 }}
    app.kubernetes.io/component: {{ .name }}
{{- end }}
```

**values.yaml:**
```yaml
services:
  - name: auth
    port: 8001
    targetPort: 8001
    type: ClusterIP
  - name: api
    port: 8002
    targetPort: 8002
    type: ClusterIP
  - name: worker
    port: 8003
    targetPort: 8003
    type: ClusterIP
```

### Environment Variables Loop
```yaml
# Static approach - hard to maintain
env:
- name: DATABASE_URL
  value: "postgresql://user:pass@db:5432/mydb"
- name: REDIS_URL  
  value: "redis://redis:6379"
- name: LOG_LEVEL
  value: "INFO"
- name: API_KEY
  value: "secret-key"

# Helm template approach
env:
{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- if .Values.secrets }}
{{- range $key, $secret := .Values.secrets }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ include "myapp.fullname" $ }}-secret
      key: {{ $secret.key }}
{{- end }}
{{- end }}
```

## Helper Functions

### Regular YAML - Repetitive Labels
```yaml
# deployment.yaml
metadata:
  name: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/instance: my-release
    app.kubernetes.io/version: "1.0.0"
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: my-system
    helm.sh/chart: my-app-0.1.0

# service.yaml  
metadata:
  name: my-app-service
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/instance: my-release
    app.kubernetes.io/version: "1.0.0"
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: my-system
    helm.sh/chart: my-app-0.1.0

# configmap.yaml
metadata:
  name: my-app-config
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/instance: my-release
    app.kubernetes.io/version: "1.0.0"
    app.kubernetes.io/component: web
    app.kubernetes.io/part-of: my-system
    helm.sh/chart: my-app-0.1.0
```

### Helm Helper Functions (_helpers.tpl)
```yaml
{{/*
Common labels
*/}}
{{- define "myapp.labels" -}}
helm.sh/chart: {{ include "myapp.chart" . }}
{{ include "myapp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "myapp.fullname" -}}
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

### Using Helper Functions
```yaml
# All templates can now use:
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}

selector:
  matchLabels:
    {{- include "myapp.selectorLabels" . | nindent 4 }}
```

## Real-World Examples

### Example 1: Database Configuration

**Static Kubernetes YAML:**
```yaml
# postgres-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    spec:
      containers:
      - name: postgres
        image: postgres:13
        env:
        - name: POSTGRES_DB
          value: "myapp"
        - name: POSTGRES_USER
          value: "user"  
        - name: POSTGRES_PASSWORD
          value: "password123"
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-data
        persistentVolumeClaim:
          claimName: postgres-pvc
```

**Helm Template:**
```yaml
# templates/postgres-deployment.yaml
{{- if .Values.postgresql.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}-postgresql
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
    app.kubernetes.io/component: postgresql
spec:
  replicas: 1
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: postgresql
  template:
    spec:
      containers:
      - name: postgresql
        image: "{{ .Values.postgresql.image.repository }}:{{ .Values.postgresql.image.tag }}"
        env:
        - name: POSTGRES_DB
          value: {{ .Values.postgresql.auth.database | quote }}
        - name: POSTGRES_USER
          value: {{ .Values.postgresql.auth.username | quote }}
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ include "myapp.fullname" . }}-postgresql-secret
              key: postgres-password
        {{- if .Values.postgresql.extraEnvVars }}
        {{- range $key, $value := .Values.postgresql.extraEnvVars }}
        - name: {{ $key }}
          value: {{ $value | quote }}
        {{- end }}
        {{- end }}
        volumeMounts:
        - name: postgresql-data
          mountPath: /var/lib/postgresql/data
          {{- if .Values.postgresql.persistence.subPath }}
          subPath: {{ .Values.postgresql.persistence.subPath }}
          {{- end }}
        resources:
          {{- toYaml .Values.postgresql.resources | nindent 10 }}
      volumes:
      - name: postgresql-data
        {{- if .Values.postgresql.persistence.enabled }}
        persistentVolumeClaim:
          claimName: {{ include "myapp.fullname" . }}-postgresql-pvc
        {{- else }}
        emptyDir: {}
        {{- end }}
{{- end }}
```

### Example 2: Multi-Environment Secret Management

**Static Approach - Multiple Files:**
```yaml
# secrets-dev.yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
type: Opaque
stringData:
  database-password: "dev-password"
  api-key: "dev-api-key"
  jwt-secret: "dev-jwt-secret"

# secrets-prod.yaml  
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
type: Opaque
stringData:
  database-password: "prod-secure-password"
  api-key: "prod-api-key"
  jwt-secret: "prod-jwt-secret"
```

**Helm Template Approach:**
```yaml
# templates/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "myapp.fullname" . }}-secret
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
type: Opaque
stringData:
  database-password: {{ .Values.secrets.databasePassword | quote }}
  api-key: {{ .Values.secrets.apiKey | quote }}
  jwt-secret: {{ .Values.secrets.jwtSecret | quote }}
  {{- if .Values.secrets.additionalSecrets }}
  {{- range $key, $value := .Values.secrets.additionalSecrets }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
  {{- end }}
```

**Environment-specific values:**
```yaml
# values-dev.yaml
secrets:
  databasePassword: "dev-password"
  apiKey: "dev-api-key"  
  jwtSecret: "dev-jwt-secret"

# values-prod.yaml
secrets:
  databasePassword: "prod-secure-password"
  apiKey: "prod-api-key"
  jwtSecret: "prod-jwt-secret"
  additionalSecrets:
    monitoring-token: "prod-monitoring-token"
```

## Key Advantages Summary

| Feature | Regular YAML | Helm Templates |
|---------|--------------|----------------|
| **Reusability** | ❌ Copy/paste required | ✅ Single template, multiple deployments |
| **Configuration** | ❌ Hard-coded values | ✅ External values.yaml |
| **Environment Management** | ❌ Multiple file sets | ✅ Values override hierarchy |
| **Conditional Logic** | ❌ Not possible | ✅ if/else, range loops |
| **DRY Principle** | ❌ Lots of repetition | ✅ Helper functions, includes |
| **Validation** | ❌ Manual verification | ✅ Built-in linting and validation |
| **Versioning** | ❌ Manual tracking | ✅ Chart versions and rollbacks |
| **Dependency Management** | ❌ Manual coordination | ✅ Automatic dependency resolution |

The Helm templating system transforms static Kubernetes manifests into dynamic, reusable, and maintainable infrastructure-as-code that can be easily customized for different environments and use cases.