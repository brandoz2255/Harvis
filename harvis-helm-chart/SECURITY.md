# Harvis AI Helm Chart - Security Guide

## 🔒 Security Configuration

This Helm chart is configured with security best practices. **NO SECRETS ARE STORED IN GIT!**

## Required Secrets for Production Deployment

The following secrets must be provided via `--set` flags or external secret management:

### 1. JWT Secret (Required)
Used for authentication between frontend and backend services.

```bash
--set backend.env.JWT_SECRET="your-secure-jwt-secret-here"
--set frontend.env.JWT_SECRET="your-secure-jwt-secret-here"
```

**Note:** Both frontend and backend must use the same JWT secret.

### 2. PostgreSQL Password (Required)
Database password for all PostgreSQL connections.

```bash
--set postgresql.auth.password="your-secure-postgres-password"
```

### 3. n8n Basic Auth Password (Required)
Password for n8n web interface authentication.

```bash
--set n8n.auth.basicAuthPassword="your-secure-n8n-password"
```

### 4. API Keys (Optional)
External service API keys as needed.

```bash
--set backend.env.OLLAMA_API_KEY="your-ollama-api-key"
--set backend.env.OPENAI_API_KEY="your-openai-api-key"
--set n8n.env.N8N_PERSONAL_API_KEY="your-n8n-api-key"
```

## Deployment Examples

### Secure Deployment Command
```bash
helm upgrade --install harvis-ai ./harvis-helm-chart \
  --namespace ai-agents \
  --set backend.env.JWT_SECRET="$(openssl rand -hex 32)" \
  --set frontend.env.JWT_SECRET="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)" \
  --set n8n.auth.basicAuthPassword="$(openssl rand -hex 16)"
```

### FluxCD HelmRelease with External Secrets
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: harvis-ai
spec:
  valuesFrom:
    - kind: Secret
      name: harvis-ai-secrets
      valuesKey: values.yaml
```

## Secret Management Options

### Option 1: External Secrets Operator (Recommended)
Use External Secrets Operator to sync from external secret stores (AWS Secrets Manager, HashiCorp Vault, etc.).

### Option 2: Sealed Secrets
Use Sealed Secrets to encrypt secrets in Git while keeping them secure.

### Option 3: Manual kubectl Secrets
Create secrets manually and reference them in the HelmRelease.

## Default Fallback Values

If secrets are not provided, the chart uses obvious placeholder values that will fail in production:

- JWT Secret: `CHANGE-THIS-JWT-SECRET-IN-PRODUCTION`
- PostgreSQL Password: `CHANGE-THIS-POSTGRES-PASSWORD-IN-PRODUCTION`
- n8n Password: `CHANGE-THIS-N8N-PASSWORD-IN-PRODUCTION`

These are intentionally obvious to prevent accidental production deployments with insecure defaults.

## Security Checklist

- [ ] All secrets provided via external sources (not in Git)
- [ ] JWT secrets are cryptographically secure (32+ random hex characters)
- [ ] Database passwords are strong and unique
- [ ] API keys are valid and properly scoped
- [ ] Kubernetes RBAC is properly configured
- [ ] Network policies restrict inter-service communication as needed
- [ ] TLS certificates are properly configured for ingress
- [ ] Container images are from trusted sources and regularly updated

## Troubleshooting

### "CHANGE-THIS-*-IN-PRODUCTION" Errors
This means you haven't provided the required secrets. Set them via `--set` flags or external secrets.

### Authentication Failures
Ensure JWT secrets match between frontend and backend services.

### Database Connection Errors
Verify PostgreSQL password is correctly set and matches across all services that need database access.