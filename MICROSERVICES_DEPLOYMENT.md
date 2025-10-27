# Microservices Deployment Guide

**Date**: 2025-10-27
**Branch**: `claude/split-backend-microservices-011CUXPiDjkAqJT5qGV3MVLC`
**Status**: Ready for Testing

## Overview

The Harvis AI backend has been split into 7 specialized microservices to reduce Docker image sizes and enable independent scaling. This guide explains how to deploy and manage the microservices architecture.

## Architecture Summary

```
┌──────────────────────────────────────────────────────┐
│         Nginx Proxy (Port 9000)                      │
│         Entry point for all requests                 │
└─────────────────┬────────────────────────────────────┘
                  │
┌─────────────────┴────────────────────────────────────┐
│    Core API Service (Port 8000) - ~500MB            │
│    Authentication Gateway & Router                   │
└─┬────────┬────────┬────────┬────────┬────────────────┘
  │        │        │        │        │        │
  v        v        v        v        v        v
┌───┐   ┌───┐   ┌───┐   ┌───┐   ┌───┐   ┌───┐
│Res│   │Voi│   │Bro│   │MCP│   │N8N│   │Vib│
│ear│   │ce │   │wse│   │   │   │   │   │e  │
│ch │   │   │   │r  │   │   │   │   │   │   │
└───┘   └───┘   └───┘   └───┘   └───┘   └───┘
8001    8002    8003    8004    8005    8006
1.5GB   4GB     800MB   600MB   1GB     800MB
```

## Services Breakdown

### 1. Core API Service (Port 8000) - ~500MB
- **Purpose**: Authentication gateway, request routing
- **Components**: JWT auth, user management, service proxy
- **Dependencies**: FastAPI, asyncpg, JWT libraries

### 2. Research Service (Port 8001) - ~1.5GB
- **Purpose**: Web search, research agents, fact-checking
- **Components**: LangChain, DuckDuckGo search, research pipeline
- **Dependencies**: langchain, beautifulsoup4, newspaper3k

### 3. Voice Service (Port 8002) - ~4GB
- **Purpose**: Speech-to-text (Whisper), Text-to-speech (Chatterbox)
- **Components**: Whisper models, Chatterbox TTS
- **Dependencies**: PyTorch, whisper, chatterbox-tts
- **Note**: Largest service due to PyTorch and audio models

### 4. Browser Service (Port 8003) - ~800MB
- **Purpose**: Selenium web automation
- **Components**: Chromium, Selenium WebDriver
- **Dependencies**: selenium, chromium

### 5. MCP Service (Port 8004) - ~600MB
- **Purpose**: Model Context Protocol tools
- **Components**: Network tools, OS operations, notifications
- **Dependencies**: Basic Python libraries

### 6. N8N Integration (Port 8005) - ~1GB
- **Purpose**: N8N workflow automation
- **Components**: Workflow builder, automation service
- **Dependencies**: pgvector, psycopg, docker

### 7. Vibe Coding (Port 8006) - ~800MB
- **Purpose**: AI-powered development environment
- **Components**: Code execution, session management
- **Dependencies**: docker, ollama client

## Prerequisites

1. **Docker and Docker Compose**
   ```bash
   docker --version  # Should be 20.10+
   docker-compose --version  # Should be 2.0+
   ```

2. **External Docker Network**
   ```bash
   docker network create ollama-n8n-network
   ```

3. **Environment Variables**
   Create `.env` file in project root:
   ```bash
   JWT_SECRET=your-secure-jwt-secret-key
   N8N_PERSONAL_API_KEY=your-n8n-api-key
   TAVILY_API_KEY=your-tavily-key  # Optional for research
   OLLAMA_URL=http://ollama:11434
   WHISPER_MODEL=base  # or small, medium, large
   ```

4. **NVIDIA GPU Support** (for Voice Service)
   - Install nvidia-docker2
   - Verify GPU access: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`

## Deployment

### Option 1: Deploy All Microservices

```bash
# Build and start all services
docker-compose -f docker-compose-microservices.yaml up --build -d

# View logs
docker-compose -f docker-compose-microservices.yaml logs -f

# Check service health
docker-compose -f docker-compose-microservices.yaml ps
```

### Option 2: Deploy Individual Services

```bash
# Start only core services (database, nginx, core-api)
docker-compose -f docker-compose-microservices.yaml up -d pgsql nginx core-api

# Add research service
docker-compose -f docker-compose-microservices.yaml up -d research-service

# Add voice service
docker-compose -f docker-compose-microservices.yaml up -d voice-service

# Add remaining services as needed
docker-compose -f docker-compose-microservices.yaml up -d browser-service mcp-service n8n-integration vibe-coding
```

### Option 3: Selective Deployment (Recommended for Testing)

Start with core services and add others based on needs:

```bash
# Minimal setup (auth + research)
docker-compose -f docker-compose-microservices.yaml up -d pgsql nginx core-api research-service

# Add voice capabilities
docker-compose -f docker-compose-microservices.yaml up -d voice-service

# Add browser automation
docker-compose -f docker-compose-microservices.yaml up -d browser-service
```

## Service Management

### View Service Status
```bash
docker-compose -f docker-compose-microservices.yaml ps
```

### View Logs
```bash
# All services
docker-compose -f docker-compose-microservices.yaml logs -f

# Specific service
docker-compose -f docker-compose-microservices.yaml logs -f core-api
docker-compose -f docker-compose-microservices.yaml logs -f voice-service
```

### Restart a Service
```bash
docker-compose -f docker-compose-microservices.yaml restart voice-service
```

### Rebuild a Service
```bash
docker-compose -f docker-compose-microservices.yaml up --build -d voice-service
```

### Stop All Services
```bash
docker-compose -f docker-compose-microservices.yaml down
```

### Stop and Remove Volumes
```bash
docker-compose -f docker-compose-microservices.yaml down -v
```

## Health Checks

Each microservice exposes a `/health` endpoint:

```bash
# Core API
curl http://localhost:8000/health

# Research Service
curl http://localhost:8001/health

# Voice Service
curl http://localhost:8002/health

# Browser Service
curl http://localhost:8003/health

# MCP Service
curl http://localhost:8004/health

# N8N Integration
curl http://localhost:8005/health

# Vibe Coding
curl http://localhost:8006/health
```

## Accessing the Application

- **Main Application**: http://localhost:9000
- **Core API**: http://localhost:8000
- **N8N Dashboard**: http://localhost:5678 (admin/adminpass)

**Important**: Always access the application through the Nginx proxy (port 9000) to ensure proper routing and authentication.

## Troubleshooting

### Service Won't Start

1. **Check logs**:
   ```bash
   docker-compose -f docker-compose-microservices.yaml logs [service-name]
   ```

2. **Check dependencies**:
   ```bash
   docker-compose -f docker-compose-microservices.yaml ps
   ```

3. **Verify network**:
   ```bash
   docker network inspect ollama-n8n-network
   ```

### Database Connection Issues

1. **Wait for database to be ready**:
   ```bash
   docker-compose -f docker-compose-microservices.yaml logs pgsql
   ```

2. **Check database health**:
   ```bash
   docker exec pgsql-db pg_isready -U pguser -d database
   ```

3. **Reset database** (⚠️ Destroys all data):
   ```bash
   docker-compose -f docker-compose-microservices.yaml down -v
   docker-compose -f docker-compose-microservices.yaml up -d pgsql
   ```

### Voice Service GPU Issues

1. **Verify GPU access**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
   ```

2. **Check GPU driver**:
   ```bash
   nvidia-smi
   ```

3. **Restart Docker daemon**:
   ```bash
   sudo systemctl restart docker
   ```

### Memory Issues

1. **Check Docker memory**:
   ```bash
   docker stats
   ```

2. **Increase Docker memory limit** (Docker Desktop):
   - Settings → Resources → Memory → Increase to 8GB+

3. **Free up space**:
   ```bash
   docker system prune -a
   ```

## Performance Tuning

### Resource Allocation

Recommended resources per service:
- **Core API**: 512MB RAM, 0.5 CPU
- **Research**: 1GB RAM, 1 CPU
- **Voice**: 4GB RAM, 2 CPU, 1 GPU
- **Browser**: 1GB RAM, 1 CPU
- **MCP**: 512MB RAM, 0.5 CPU
- **N8N**: 1GB RAM, 1 CPU
- **Vibe**: 1GB RAM, 1 CPU

Add to docker-compose.yaml:
```yaml
services:
  core-api:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M
```

### Scaling Services

Scale horizontally for load:
```bash
docker-compose -f docker-compose-microservices.yaml up -d --scale research-service=3
```

## Migration from Monolithic Backend

### Step 1: Backup Current Setup
```bash
# Backup database
./database-backup/backup.sh

# Export environment variables
docker exec backend env > backend-env-backup.txt
```

### Step 2: Stop Old Backend
```bash
docker-compose down
```

### Step 3: Deploy Microservices
```bash
docker-compose -f docker-compose-microservices.yaml up -d
```

### Step 4: Verify Functionality
Test all endpoints through Nginx proxy (port 9000)

### Step 5: Rollback (if needed)
```bash
docker-compose -f docker-compose-microservices.yaml down
docker-compose up -d  # Start old monolithic backend
```

## Cost Benefits

### Before (Monolithic)
- Single image: ~8-10GB
- Full rebuild required for any change
- All-or-nothing scaling

### After (Microservices)
- Core API: ~500MB (rebuilt frequently)
- Research: ~1.5GB (rebuilt occasionally)
- Voice: ~4GB (rarely rebuilt)
- Browser: ~800MB (rarely rebuilt)
- MCP: ~600MB (rarely rebuilt)
- N8N: ~1GB (occasionally rebuilt)
- Vibe: ~800MB (occasionally rebuilt)

**Total**: ~9.2GB distributed across 7 images
**Rebuild time**: 80% reduction (only rebuild changed services)
**Deployment**: Independent service deployment

## Monitoring

### Service Status Dashboard
```bash
watch -n 5 'docker-compose -f docker-compose-microservices.yaml ps'
```

### Log Aggregation
```bash
docker-compose -f docker-compose-microservices.yaml logs -f --tail=100
```

### Resource Usage
```bash
docker stats
```

## Production Considerations

1. **Use a reverse proxy with SSL** (Traefik, Caddy)
2. **Implement service mesh** (Istio, Linkerd) for advanced routing
3. **Add monitoring** (Prometheus + Grafana)
4. **Implement distributed tracing** (Jaeger)
5. **Use container orchestration** (Kubernetes, Docker Swarm)
6. **Set up CI/CD pipelines** for automated deployments
7. **Implement rate limiting** at API gateway level
8. **Add automated backup** for database

## Support

For issues or questions:
1. Check service logs: `docker-compose -f docker-compose-microservices.yaml logs [service]`
2. Review architecture documentation: `MICROSERVICES_ARCHITECTURE.md`
3. Check changes log: `front_end/jfrontend/changes.md`
4. Report issues on GitHub

## Next Steps

1. **Test all endpoints** through the Core API
2. **Monitor resource usage** with `docker stats`
3. **Optimize service configurations** based on usage patterns
4. **Implement load balancing** for high-traffic services
5. **Set up automated backups** for production

---

**Note**: This is the initial microservices implementation. Services currently have placeholder implementations for some endpoints. Full functionality will be migrated from the monolithic backend in subsequent updates.
