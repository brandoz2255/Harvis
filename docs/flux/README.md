# FluxCD GitOps Documentation

This directory contains comprehensive documentation for FluxCD GitOps setup and management in the Harvis AI project.

## 📋 Quick Overview

FluxCD is successfully deployed and actively managing automated deployments for Harvis AI. The system automatically:
- Monitors Docker images (`dulc3/jarvis-frontend:latest`, `dulc3/jarvis-backend:latest`)
- Updates Kubernetes deployments when new images are pushed
- Manages Helm chart deployments via GitOps workflow
- Provides self-healing and rollback capabilities

## 🎯 Current Status

✅ **Active & Working**: FluxCD is successfully updating from the newer branch and managing deployments
✅ **Image Automation**: Monitoring images every 30 seconds, applying updates every 5 minutes
✅ **Git Integration**: Auto-committing configuration updates to main branch
✅ **Health Monitoring**: HelmRelease health checks configured

## 📚 Documentation Structure

### [Setup Guide](./setup-guide.md)
Complete step-by-step guide for setting up FluxCD GitOps in any Kubernetes environment. Includes:
- Directory structure and configuration
- GitRepository and HelmRelease setup
- Image automation configuration
- Secrets management best practices

### [Harvis Architecture](./harvis-architecture.md)
Detailed documentation of the Harvis AI Helm chart architecture including:
- Multi-service deployment (Frontend, Backend, PostgreSQL, n8n, Nginx)
- GPU resource management for Ollama + Backend
- Ingress configuration and SSL/TLS setup
- Resource allocation and scaling

### [Image Automation](./image-automation.md)
Comprehensive guide to FluxCD's image automation system:
- ImageRepository and ImagePolicy configuration
- Update strategies and tag filtering
- Automation intervals and commit templates
- Monitoring and troubleshooting image updates

### [Troubleshooting](./troubleshooting.md)
Common issues and solutions for FluxCD deployments:
- GitRepository connection problems
- HelmRelease deployment failures
- Image automation issues
- Health check and monitoring problems

## 🚀 Quick Start Commands

```bash
# Check FluxCD status
flux get all

# View Harvis deployment status
flux get helmreleases -A
kubectl get pods -n ai-agents

# Force reconciliation
flux reconcile kustomization harvis-app --with-source

# Monitor logs
flux logs --level=info --all-namespaces

# Check image policies
flux get images all
```

## 🔧 Key Configuration Files

- `flux-config/harvis/flux-kustomization.yaml` - Main FluxCD resource
- `flux-config/harvis/base/helmrelease.yaml` - Helm deployment configuration
- `flux-config/harvis/base/image-automation.yaml` - Image monitoring and updates
- `harvis-helm-chart/` - Helm chart templates and values

## 📖 Related Documentation

- [Helm Charts Guide](../HELM_CHARTS_GUIDE.md) - Helm chart development and templating
- [System Architecture](../system-architecture.md) - Overall Harvis AI architecture
- [Docker Deployment](../docker-deployment.md) - Container and Docker configuration
- [CI/CD Pipelines](../ci-cd-pipelines.md) - Continuous integration and deployment

## 🔗 External Resources

- [FluxCD Official Documentation](https://fluxcd.io/docs/)
- [Helm Documentation](https://helm.sh/docs/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

---

> **Note**: This documentation reflects the current state of FluxCD deployment for Harvis AI. All configurations have been tested and are actively running in production.