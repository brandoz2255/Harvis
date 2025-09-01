# Helm Templating System Deep Dive

## Table of Contents
1. [Template Engine Overview](#template-engine-overview)
2. [Template Syntax](#template-syntax)
3. [Built-in Objects](#built-in-objects)
4. [Template Functions](#template-functions)
5. [Control Structures](#control-structures)
6. [Variables and Scope](#variables-and-scope)
7. [Helper Templates](#helper-templates)
8. [Advanced Patterns](#advanced-patterns)
9. [Best Practices](#best-practices)

## Template Engine Overview

Helm uses Go's `text/template` package with additional Sprig functions. Templates are processed to generate valid Kubernetes YAML manifests.

### Template Processing Flow
```
values.yaml + Chart.yaml + templates/ 
           ↓
    Template Engine
           ↓
    Kubernetes YAML
           ↓
      kubectl apply
```

### Template File Types
- **Regular templates** (`.yaml`): Generate Kubernetes resources
- **Helper templates** (`_helpers.tpl`): Define reusable functions
- **Partials** (`_*.yaml`): Included by other templates
- **NOTES.txt**: Post-installation instructions

## Template Syntax

### Basic Actions

| Syntax | Purpose | Example |
|--------|---------|---------|
| `{{ }}` | Insert value | `{{ .Values.name }}` |
| `{{- }}` | Trim left whitespace | `{{- if .Values.enabled }}` |
| `{{ -}}` | Trim right whitespace | `{{ .Values.name -}}` |
| `{{- -}}` | Trim both sides | `{{- .Values.name -}}` |

### Whitespace Control Examples

**Without whitespace control:**
```yaml
data:
{{ if .Values.enabled }}
  enabled: true
{{ end }}
```

**Generated output (malformed):**
```yaml
data:

  enabled: true

```

**With whitespace control:**
```yaml
data:
  {{- if .Values.enabled }}
  enabled: true
  {{- end }}
```

**Generated output (correct):**
```yaml
data:
  enabled: true
```

## Built-in Objects

### .Values Object
Access values from `values.yaml` and overrides:

```yaml
# values.yaml
app:
  name: myapp
  port: 8080
  config:
    debug: true
    workers: 4

# Template usage
name: {{ .Values.app.name }}
port: {{ .Values.app.port }}
debug: {{ .Values.app.config.debug }}
```

### .Chart Object
Access chart metadata from `Chart.yaml`:

```yaml
# Chart.yaml
name: myapp
version: 1.0.0
appVersion: "2.1.0"

# Template usage
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
```

### .Release Object
Information about the current release:

```yaml
name: {{ .Release.Name }}           # Release name
namespace: {{ .Release.Namespace }} # Target namespace
service: {{ .Release.Service }}     # "Helm"
revision: {{ .Release.Revision }}   # Release revision number
```

### .Template Object
Current template information:

```yaml
# In templates/deployment.yaml
name: {{ .Template.Name }}     # "myapp/templates/deployment.yaml"
basePath: {{ .Template.BasePath }} # "myapp/templates"
```

### .Files Object
Access files within the chart:

```yaml
# Chart structure:
# myapp/
# ├── config.json
# ├── scripts/
# │   └── init.sh
# └── templates/

# Access files
{{- (.Files.Glob "config.json").AsConfig | nindent 2 }}
{{- .Files.Get "scripts/init.sh" | nindent 2 }}
```

### .Capabilities Object
Information about Kubernetes cluster:

```yaml
{{- if .Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress" }}
apiVersion: networking.k8s.io/v1
{{- else }}
apiVersion: extensions/v1beta1
{{- end }}
kind: Ingress
```

## Template Functions

### String Functions

```yaml
# Case conversion
name: {{ .Values.name | upper }}      # MYAPP
name: {{ .Values.name | lower }}      # myapp
name: {{ .Values.name | title }}      # Myapp

# String manipulation
name: {{ .Values.name | quote }}      # "myapp"
name: {{ .Values.name | squote }}     # 'myapp'
name: {{ .Values.name | indent 4 }}   # Indent 4 spaces
name: {{ .Values.name | nindent 4 }}  # Newline + indent 4 spaces

# Default values
name: {{ .Values.name | default "defaultapp" }}
```

### Type Conversion

```yaml
# Convert to YAML
resources:
  {{- toYaml .Values.resources | nindent 2 }}

# Convert to JSON
config: {{ toJson .Values.config }}

# Convert types
port: {{ .Values.port | int }}
enabled: {{ .Values.enabled | toString }}
```

### List Functions

```yaml
# values.yaml
environments: ["dev", "staging", "prod"]
services:
  - name: web
    port: 80
  - name: api  
    port: 8080

# Templates
{{- range .Values.environments }}
- {{ . }}
{{- end }}

# List operations
first_env: {{ first .Values.environments }}      # dev
last_env: {{ last .Values.environments }}        # prod  
has_prod: {{ has "prod" .Values.environments }}  # true
```

### Dictionary Functions

```yaml
# values.yaml
labels:
  app: myapp
  version: v1.0.0
  env: prod

# Template
{{- range $key, $value := .Values.labels }}
{{ $key }}: {{ $value }}
{{- end }}

# Dictionary operations
{{- if hasKey .Values.labels "env" }}
environment: {{ .Values.labels.env }}
{{- end }}
```

## Control Structures

### Conditionals

#### Basic If/Else
```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "myapp.fullname" . }}
{{- else }}
# Ingress is disabled
{{- end }}
```

#### Multiple Conditions
```yaml
{{- if and .Values.persistence.enabled .Values.database.enabled }}
# Both persistence and database are enabled
{{- else if .Values.persistence.enabled }}
# Only persistence is enabled
{{- else }}
# Neither is enabled
{{- end }}
```

#### Complex Logic
```yaml
{{- if or (eq .Values.environment "production") (eq .Values.environment "staging") }}
replicas: {{ .Values.replicas.production }}
{{- else }}
replicas: {{ .Values.replicas.development }}
{{- end }}
```

### Loops

#### Range Over Lists
```yaml
# values.yaml
ports:
  - name: http
    port: 80
    targetPort: 8080
  - name: https
    port: 443
    targetPort: 8443

# Template
ports:
{{- range .Values.ports }}
- name: {{ .name }}
  port: {{ .port }}
  targetPort: {{ .targetPort }}
{{- end }}
```

#### Range Over Maps
```yaml
# values.yaml
env:
  DATABASE_URL: "postgresql://..."
  LOG_LEVEL: "INFO"
  DEBUG: "false"

# Template
env:
{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
```

#### Range with Index
```yaml
# values.yaml
replicas: ["web-0", "web-1", "web-2"]

# Template
{{- range $index, $replica := .Values.replicas }}
- name: {{ $replica }}
  index: {{ $index }}
{{- end }}
```

## Variables and Scope

### Variable Assignment
```yaml
{{- $fullname := include "myapp.fullname" . }}
{{- $labels := include "myapp.labels" . }}

metadata:
  name: {{ $fullname }}
  labels:
    {{- $labels | nindent 4 }}
```

### Scope Management
```yaml
# Root context is . (dot)
name: {{ .Values.name }}

{{- range .Values.services }}
# Inside range, . refers to current item
service_name: {{ .name }}
service_port: {{ .port }}

# Access root context with $
chart_name: {{ $.Chart.Name }}
release_name: {{ $.Release.Name }}
{{- end }}
```

### Complex Variable Usage
```yaml
{{- $root := . }}
{{- $fullname := include "myapp.fullname" . }}

{{- range .Values.services }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $fullname }}-{{ .name }}
  labels:
    {{- include "myapp.labels" $root | nindent 4 }}
    app.kubernetes.io/component: {{ .name }}
spec:
  ports:
  - port: {{ .port }}
    targetPort: {{ .targetPort | default .port }}
  selector:
    {{- include "myapp.selectorLabels" $root | nindent 4 }}
    app.kubernetes.io/component: {{ .name }}
{{- end }}
```

## Helper Templates

### Defining Helper Templates (_helpers.tpl)

```yaml
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
Create environment variables from values
*/}}
{{- define "myapp.envVars" -}}
{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- if .Values.secrets }}
{{- range $key, $secret := .Values.secrets }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ include "myapp.fullname" . }}-secret
      key: {{ $secret.key }}
{{- end }}
{{- end }}
{{- end }}
```

### Using Helper Templates

```yaml
# templates/deployment.yaml
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}

# templates/service.yaml  
metadata:
  name: {{ include "myapp.fullname" . }}-service
  labels:
    {{- include "myapp.labels" . | nindent 4 }}

# Environment variables
env:
  {{- include "myapp.envVars" . | nindent 2 }}
```

## Advanced Patterns

### Named Templates with Parameters

```yaml
{{/*
Create a container spec
*/}}
{{- define "myapp.container" -}}
{{- $container := .container -}}
{{- $global := .global -}}
- name: {{ $container.name }}
  image: "{{ $container.image.repository }}:{{ $container.image.tag }}"
  ports:
  {{- range $container.ports }}
  - name: {{ .name }}
    containerPort: {{ .port }}
  {{- end }}
  env:
  {{- range $key, $value := $container.env }}
  - name: {{ $key }}
    value: {{ $value | quote }}
  {{- end }}
  resources:
    {{- toYaml $container.resources | nindent 4 }}
{{- end }}

# Usage
containers:
{{- range .Values.containers }}
{{- include "myapp.container" (dict "container" . "global" $) | nindent 2 }}
{{- end }}
```

### Conditional Includes

```yaml
{{- define "myapp.securityContext" -}}
{{- if .Values.securityContext.enabled }}
securityContext:
  {{- if .Values.securityContext.runAsUser }}
  runAsUser: {{ .Values.securityContext.runAsUser }}
  {{- end }}
  {{- if .Values.securityContext.runAsGroup }}
  runAsGroup: {{ .Values.securityContext.runAsGroup }}
  {{- end }}
  {{- if .Values.securityContext.fsGroup }}
  fsGroup: {{ .Values.securityContext.fsGroup }}
  {{- end }}
{{- end }}
{{- end }}

# Usage
spec:
  {{- include "myapp.securityContext" . | nindent 2 }}
```

### Template Validation

```yaml
{{/*
Validate required values
*/}}
{{- define "myapp.validateValues" -}}
{{- if not .Values.image.repository }}
  {{- fail "image.repository is required" }}
{{- end }}
{{- if not .Values.service.port }}
  {{- fail "service.port is required" }}
{{- end }}
{{- if and .Values.ingress.enabled (not .Values.ingress.hosts) }}
  {{- fail "ingress.hosts is required when ingress is enabled" }}
{{- end }}
{{- end }}

# Call validation at the top of main templates
{{- include "myapp.validateValues" . -}}
```

## Best Practices

### 1. Consistent Naming
```yaml
# Good: Consistent naming pattern
{{ include "myapp.fullname" . }}-deployment
{{ include "myapp.fullname" . }}-service
{{ include "myapp.fullname" . }}-configmap

# Bad: Inconsistent naming
{{ .Release.Name }}-deploy
{{ .Chart.Name }}-svc
app-{{ .Values.name }}-config
```

### 2. Proper Indentation
```yaml
# Good: Use nindent for clean output
metadata:
  labels:
    {{- include "myapp.labels" . | nindent 4 }}

# Bad: Manual spacing
metadata:
  labels:
{{ include "myapp.labels" . }}
```

### 3. Default Values
```yaml
# Good: Provide sensible defaults
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
replicas: {{ .Values.replicaCount | default 1 }}

# Bad: No defaults, potential failures
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
replicas: {{ .Values.replicaCount }}
```

### 4. Resource Management
```yaml
# Good: Conditional resource creation
{{- if .Values.ingress.enabled }}
# Ingress resource here
{{- end }}

# Good: Optional resource sections
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

### 5. Comments and Documentation
```yaml
{{/*
Generate database connection string based on configuration.
Parameters:
- .Values.database.host: Database hostname
- .Values.database.port: Database port
- .Values.database.name: Database name
Returns: Complete database URL string
*/}}
{{- define "myapp.databaseUrl" -}}
{{- printf "postgresql://%s:%s@%s:%d/%s" .Values.database.username .Values.database.password .Values.database.host (.Values.database.port | int) .Values.database.name -}}
{{- end }}
```

### 6. Error Handling
```yaml
{{- if not (or .Values.persistence.enabled .Values.persistence.existingClaim) }}
  {{- if not .Values.persistence.storageClass }}
    {{- if not (eq .Values.persistence.storageClass "-") }}
      {{- fail "Must specify persistence.storageClass or set to '-' for default StorageClass" }}
    {{- end }}
  {{- end }}
{{- end }}
```

This templating system allows Helm charts to be highly flexible and reusable while maintaining the structure and validation that Kubernetes requires.