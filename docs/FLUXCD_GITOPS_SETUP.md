# FluxCD GitOps Setup Guide

This guide documents how to set up FluxCD for automated GitOps deployment of any Kubernetes application, using Harvis AI as a complete example.

## Overview

FluxCD provides GitOps continuous deployment for Kubernetes, automatically deploying changes from Git repositories and updating applications when new container images are available.

### Benefits
- **Automated Deployments**: Code changes trigger automatic deployments
- **Image Automation**: New Docker images automatically update deployments  
- **Self-Healing**: Failed deployments automatically rollback
- **Security**: Secrets managed separately from code
- **Audit Trail**: All changes tracked in Git

## Prerequisites

- Kubernetes cluster with FluxCD installed
- Git repository with Helm charts
- Docker registry with container images
- kubectl access to cluster

## Directory Structure

```
your-project/
├── flux-config/
│   └── your-app/
│       ├── base/
│       │   ├── source.yaml          # GitRepository + HelmRepository
│       │   ├── helmrelease.yaml     # Helm deployment config
│       │   ├── namespace.yaml       # Target namespace
│       │   ├── image-automation.yaml # Image monitoring & updates
│       │   ├── kustomization.yaml   # Kustomize resources
│       │   └── external-secret-template.yaml # Secret template
│       └── flux-kustomization.yaml  # FluxCD Kustomization
├── your-helm-chart/                 # Helm chart directory
│   ├── Chart.yaml
│   ├── values.yaml                  # Default values (no secrets)
│   └── templates/
└── .gitignore                       # Protects secrets
```

## Step-by-Step Setup

### 1. Verify FluxCD Installation

```bash
# Check FluxCD version
flux version

# Check FluxCD status
kubectl get pods -n flux-system

# All pods should be Running
```

### 2. Create Directory Structure

```bash
mkdir -p flux-config/your-app/{base,overlays/production}
```

### 3. Configure GitRepository Source

Create `flux-config/your-app/base/source.yaml`:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: your-app-source
  namespace: flux-system
spec:
  interval: 1m0s
  ref:
    branch: main
  url: https://github.com/your-username/your-repo.git
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: your-app-helm
  namespace: flux-system
spec:
  interval: 5m0s
  url: oci://registry-1.docker.io/your-username
```

### 4. Create HelmRelease

Create `flux-config/your-app/base/helmrelease.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: your-app
  namespace: your-namespace
spec:
  interval: 5m
  releaseName: your-app
  chart:
    spec:
      chart: ./your-helm-chart
      version: "*"
      sourceRef:
        kind: GitRepository
        name: your-app-source
        namespace: flux-system
  values:
    # Override Helm chart values here
    namespace: your-namespace
    
    # Application configuration
    app:
      image:
        repository: your-username/your-app
        tag: latest # {"$imagepolicy": "flux-system:your-app-policy:tag"}
        pullPolicy: Always
    
    # Database configuration
    database:
      enabled: true
      persistence:
        enabled: true
        size: 20Gi
    
    # Ingress configuration
    ingress:
      enabled: true
      className: "nginx"
      hosts:
        - host: your-app.example.com
          paths:
            - path: /
              pathType: Prefix
              service:
                name: your-app
                port: 80
  
  # Automated upgrade configuration
  upgrade:
    remediation:
      retries: 3
  
  # Rollback configuration
  rollback:
    cleanupOnFail: true
  
  # Dependencies
  dependsOn:
    - name: your-namespace-setup
```

### 5. Create Namespace

Create `flux-config/your-app/base/namespace.yaml`:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: your-namespace
  labels:
    name: your-namespace
    toolkit.fluxcd.io/tenant: your-app
```

### 6. Configure Image Automation

Create `flux-config/your-app/base/image-automation.yaml`:

```yaml
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: your-app-images
  namespace: flux-system
spec:
  image: your-username/your-app
  interval: 1m0s
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: your-app-policy
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: your-app-images
  policy:
    semver:
      range: '>=1.0.0'
  filterTags:
    pattern: '^(?P<version>.*)$'
    extract: '$version'
---
apiVersion: image.toolkit.fluxcd.io/v1beta1
kind: ImageUpdateAutomation
metadata:
  name: your-app-automation
  namespace: flux-system
spec:
  interval: 30m
  sourceRef:
    kind: GitRepository
    name: your-app-source
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        email: fluxcdbot@users.noreply.github.com
        name: fluxcdbot
      messageTemplate: |
        Automated image update for {{ .AutomationObject }}
        
        Images:
        {{ range .Updated.Images -}}
        - {{.}}
        {{ end -}}
    push:
      branch: main
  update:
    path: "./flux-config/your-app"
    strategy: Setters
```

### 7. Create Kustomization

Create `flux-config/your-app/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - namespace.yaml
  - source.yaml
  - helmrelease.yaml
  - image-automation.yaml
```

### 8. Create FluxCD Kustomization

Create `flux-config/your-app/flux-kustomization.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: your-app
  namespace: flux-system
spec:
  interval: 10m0s
  path: ./flux-config/your-app/base
  prune: true
  sourceRef:
    kind: GitRepository
    name: your-app-source
  healthChecks:
    - apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      name: your-app
      namespace: your-namespace
  timeout: 5m0s
```

### 9. Secure Secrets Management

Create `flux-config/your-app/base/external-secret-template.yaml`:

```yaml
# This is a template for creating external secrets
# DO NOT commit this file with real values!
# 
# To use:
# 1. Copy this file to external-secret.yaml
# 2. Replace placeholders with real values  
# 3. Apply: kubectl apply -f external-secret.yaml
# 4. Add external-secret.yaml to .gitignore

apiVersion: v1
kind: Secret
metadata:
  name: your-app-secrets
  namespace: your-namespace
type: Opaque
stringData:
  API_KEY: "YOUR_API_KEY_HERE"
  DATABASE_PASSWORD: "YOUR_DB_PASSWORD_HERE"
```

### 10. Update .gitignore

Add to your `.gitignore`:

```gitignore
# ==========================================
# FluxCD and Kubernetes Secrets Protection
# ==========================================

# Ignore personal values files with secrets/API keys
**/values-personal.yaml
**/values-secret.yaml
**/values-local.yaml
**/secrets.yaml
**/secret-*.yaml

# Ignore Helm chart values with personal info
your-helm-chart/values-production.yaml
your-helm-chart/values-staging.yaml
your-helm-chart/charts/
your-helm-chart/*.tgz

# Ignore FluxCD personal configurations
flux-config/**/overlays/personal/
flux-config/**/secrets/
flux-config/**/*-secret.yaml
flux-config/**/external-secret.yaml

# Kubeconfig and kubectl contexts
kubeconfig
kubeconfig.*
.kube/config

# API Keys and tokens
**/*api-key*
**/*token*
**/credentials*
*.pem
*.key
*.crt
*.p12

# Database dumps with potential sensitive data
*.sql.gz
*.dump
backup-*.sql

# Personal development overrides
docker-compose.override.yml
docker-compose.local.yml
.env.local
.env.personal
.env.secret
```

## Deployment Process

### 1. Deploy FluxCD Resources

```bash
# Apply the FluxCD Kustomization to start GitOps
kubectl apply -f flux-config/your-app/flux-kustomization.yaml
```

### 2. Create External Secrets (if needed)

```bash
# Copy template and add real values (don't commit!)
cp flux-config/your-app/base/external-secret-template.yaml external-secret.yaml
# Edit external-secret.yaml with real values
kubectl apply -f external-secret.yaml
rm external-secret.yaml  # Remove after applying
```

### 3. Commit and Push

```bash
git add flux-config/ your-helm-chart/ .gitignore
git commit -m "feat: Add FluxCD GitOps configuration

- Created FluxCD directory structure and resources
- Added GitRepository and HelmRelease automation 
- Configured ImageRepository and ImagePolicy for auto-updates
- Set up automated deployment pipeline

🤖 Generated with FluxCD GitOps Setup Guide"
git push origin main
```

## Monitoring and Troubleshooting

### Check FluxCD Status

```bash
# View all Flux resources
flux get all

# Check specific resources
flux get kustomizations
flux get helmreleases
flux get sources git
flux get images all

# View logs
flux logs --level=info --all-namespaces
```

### Common Commands

```bash
# Force reconciliation
flux reconcile kustomization your-app --with-source

# Suspend/resume automation
flux suspend kustomization your-app
flux resume kustomization your-app

# Check image policies
flux get images repository
flux get images policy
```

### Troubleshooting

1. **GitRepository not found**: Ensure you've committed and pushed flux-config files
2. **HelmRelease fails**: Check Helm chart syntax and values
3. **Image automation not working**: Verify image repository access and tag patterns
4. **Secrets missing**: Apply external secrets manually before HelmRelease

## Harvis AI Example

The complete Harvis AI FluxCD setup includes:

### Structure
```
flux-config/harvis/
├── base/
│   ├── source.yaml              # GitHub repo + OCI registry
│   ├── helmrelease.yaml         # Harvis Helm deployment
│   ├── namespace.yaml           # ai-agents namespace
│   ├── image-automation.yaml    # Monitor dulc3/jarvis-* images
│   ├── kustomization.yaml       # Combine resources
│   └── external-secret-template.yaml # API keys template
└── flux-kustomization.yaml     # FluxCD management
```

### Key Features
- **Multi-service deployment**: Frontend, backend, PostgreSQL, n8n, Nginx
- **GPU resource management**: Shared GPU for Ollama + backend
- **Image automation**: Monitors `dulc3/jarvis-frontend:dev` and `dulc3/jarvis-backend:latest`
- **Ingress configuration**: Multiple hosts (harvis.dulc3.tech, n8n.dulc3.tech)
- **Secret management**: API keys managed via external secrets

### Deployment Command
```bash
kubectl apply -f flux-config/harvis/flux-kustomization.yaml
```

## Best Practices

### Security
1. **Never commit secrets** - Use external secret management
2. **Use .gitignore patterns** - Protect sensitive files
3. **Separate environments** - Use overlays for staging/production
4. **Limit permissions** - Use service accounts with minimal RBAC

### Organization
1. **Consistent naming** - Use predictable resource names
2. **Environment separation** - Separate flux-config per environment
3. **Documentation** - Document all custom configurations
4. **Testing** - Test in staging before production

### Monitoring
1. **Set up alerts** - Monitor FluxCD component health
2. **Use health checks** - Configure proper readiness/liveness probes
3. **Log aggregation** - Collect FluxCD and application logs
4. **Backup strategy** - Backup GitOps repository and cluster state

## Migration from Manual Deployments

### 1. Export Existing Resources
```bash
# Export current deployment
kubectl get deployment your-app -o yaml > existing-deployment.yaml
kubectl get service your-app -o yaml > existing-service.yaml
```

### 2. Create Helm Chart
```bash
# Generate Helm chart from existing resources
helm create your-app-chart
# Customize templates with exported resources
```

### 3. Set up FluxCD
```bash
# Follow the setup steps above
# Test in staging environment first
```

### 4. Cutover
```bash
# Delete manual resources
kubectl delete -f existing-deployment.yaml
kubectl delete -f existing-service.yaml

# Let FluxCD take over
kubectl apply -f flux-config/your-app/flux-kustomization.yaml
```

This guide provides a complete, reusable template for setting up FluxCD GitOps for any Kubernetes application. Customize the resource names, namespaces, and configurations for your specific use case.