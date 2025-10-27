# Microservices Architecture

**Date**: 2025-10-27
**Status**: In Development
**Branch**: `claude/split-backend-microservices-011CUXPiDjkAqJT5qGV3MVLC`

## Overview

This document outlines the microservices architecture for the Harvis AI backend, splitting the monolithic Python backend into specialized services to reduce Docker image sizes and enable independent scaling.

## Problem Statement

The current monolithic backend has a single large Docker image (~8-10GB) containing all dependencies, making:
- Build times slow
- Deployment inefficient
- Scaling all-or-nothing
- Development iteration slow

## Solution: Microservices Split

### Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Nginx Proxy (Port 9000)               │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│              Core API Service (Port 8000)                   │
│          (Authentication Gateway & Main Router)             │
└─┬────────┬────────┬────────┬────────┬────────┬─────────────┘
  │        │        │        │        │        │
  v        v        v        v        v        v
┌───────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│Research│ │Voice │ │Browser│ │ MCP  │ │ N8N  │ │   Vibe   │
│Service │ │Service│ │Service│ │Service│ │ Intg │ │  Coding  │
│:8001  │ │:8002 │ │:8003 │ │:8004 │ │:8005 │ │  :8006   │
└───────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────────┘
```

## Services Breakdown

### 1. Core API Service (`microservices/core-api/`)
**Purpose**: Main API gateway, authentication, user management, request routing

**Components**:
- `main.py` (core FastAPI app with auth endpoints)
- `auth_optimized.py`, `auth_utils.py`
- API routing to other microservices
- JWT token validation middleware

**Dependencies**:
- fastapi, uvicorn
- asyncpg (database)
- python-jose, passlib, bcrypt (auth)
- requests (for inter-service communication)

**Estimated Size**: ~500MB

**Endpoints**:
- `POST /api/auth/login`
- `POST /api/auth/signup`
- `GET /api/auth/me`
- `GET /api/auth/stats`
- Proxy endpoints to other services

---

### 2. Research Service (`microservices/research-service/`)
**Purpose**: Web search, research agents, fact-checking, comparative analysis

**Components**:
- `research/` (entire directory)
- `agent_research.py`

**Dependencies**:
- langchain, langchain-community
- ddgs (DuckDuckGo search)
- beautifulsoup4, newspaper3k
- trafilatura, rank-bm25
- tavily-python
- requests-cache

**Estimated Size**: ~1.5GB

**Endpoints**:
- `POST /api/web-search`
- `POST /api/research-chat`
- `POST /api/fact-check`
- `POST /api/comparative-research`

---

### 3. Voice Service (`microservices/voice-service/`)
**Purpose**: Speech-to-text (Whisper), Text-to-speech (Chatterbox TTS)

**Components**:
- `chatterbox_tts.py`
- Whisper model integration
- Audio processing utilities

**Dependencies**:
- torch, torchaudio (PyTorch stack)
- openai-whisper
- chatterbox-tts
- soundfile

**Estimated Size**: ~4GB (largest due to PyTorch + audio models)

**Endpoints**:
- `POST /api/mic-chat` (STT + TTS)
- `POST /api/tts` (Text-to-speech only)
- `POST /api/stt` (Speech-to-text only)

---

### 4. Browser Automation Service (`microservices/browser-service/`)
**Purpose**: Selenium-based web automation, screen analysis

**Components**:
- `browser.py`
- `screen_analyzer.py`
- `screen_share_server.py`

**Dependencies**:
- selenium
- Chrome/Chromium driver
- PIL (image processing)
- Basic AI models for screen analysis

**Estimated Size**: ~800MB

**Endpoints**:
- `POST /api/browser/navigate`
- `POST /api/browser/interact`
- `GET /api/browser/screenshot`
- `POST /api/screen-analyze`

---

### 5. MCP Service (`microservices/mcp-service/`)
**Purpose**: MCP (Model Context Protocol) server with network tools, OS operations

**Components**:
- `mcp/` (entire directory)
  - `server/app.py`
  - `server/tools/network/` (DNS, ping, whois, SSL check, etc.)
  - `server/tools/notifications/` (email, SMS, webhooks)
  - `server/tools/os_ops/` (file ops, processes, archives)

**Dependencies**:
- fastapi
- Standard library tools
- defusedxml
- python-magic

**Estimated Size**: ~600MB

**Endpoints**:
- `POST /api/mcp/tool` (generic tool execution)
- `GET /api/mcp/tools` (list available tools)

---

### 6. N8N Integration Service (`microservices/n8n-integration/`)
**Purpose**: N8N workflow automation, vector DB optimization

**Components**:
- `n8n/` (entire directory)
- `n8n_automation_system.py`
- `ollama_n8n_optimizer.py`

**Dependencies**:
- pgvector
- psycopg[binary]
- langchain (for embeddings)
- sentence-transformers
- docker (for container management)

**Estimated Size**: ~1GB

**Endpoints**:
- `POST /api/n8n/workflow/create`
- `POST /api/n8n/workflow/execute`
- `GET /api/n8n/workflow/status`
- `POST /api/n8n/optimize`

---

### 7. Vibe Coding Service (`microservices/vibe-coding/`)
**Purpose**: AI-powered development environment, code execution

**Components**:
- `vibecoding/` (entire directory)
- `ollama_cli/` (TUI and vibe agent)

**Dependencies**:
- fastapi
- docker (for code execution sandboxes)
- ollama client
- code analysis tools

**Estimated Size**: ~800MB

**Endpoints**:
- `POST /api/vibe/session/create`
- `POST /api/vibe/execute`
- `GET /api/vibe/session/{id}`
- Existing vibe router endpoints

---

## Inter-Service Communication

### Authentication Flow
1. Client sends request to Nginx (port 9000)
2. Nginx proxies to Core API Service (port 8000)
3. Core API validates JWT token
4. If valid, Core API proxies to appropriate microservice with auth context
5. Microservice processes request and returns response

### Service-to-Service Authentication
- Core API adds `X-Internal-Auth` header with user context
- Microservices trust requests from Core API (internal network only)
- No direct external access to microservices (only via Core API)

### Docker Network
All services communicate via Docker internal network: `ollama-n8n-network`
- No port exposure except Core API and Nginx
- Service discovery via Docker DNS (service names)

---

## Implementation Plan

### Phase 1: Create Service Structure
1. Create `microservices/` directory
2. Create subdirectories for each service
3. Copy relevant code to each service directory

### Phase 2: Create Dockerfiles
1. Create optimized Dockerfile for each service
2. Split requirements.txt by service dependencies
3. Use multi-stage builds where appropriate

### Phase 3: Update Docker Compose
1. Define all microservices in docker-compose.yaml
2. Configure internal networking
3. Set up health checks and dependencies

### Phase 4: Update Core API
1. Modify main.py to route requests to microservices
2. Implement service discovery
3. Add request proxying logic

### Phase 5: Testing
1. Test each microservice independently
2. Test inter-service communication
3. Test authentication flow
4. Verify all endpoints work as before

---

## Benefits

### Size Reduction
- **Before**: Single 8-10GB image
- **After**:
  - Core API: ~500MB
  - Research: ~1.5GB
  - Voice: ~4GB
  - Browser: ~800MB
  - MCP: ~600MB
  - N8N: ~1GB
  - Vibe: ~800MB
- **Total**: ~9.2GB (distributed across 7 images)

### Performance Benefits
1. **Faster Builds**: Only rebuild changed services
2. **Independent Scaling**: Scale voice service separately from research
3. **Resource Efficiency**: Allocate resources per service needs
4. **Development Speed**: Work on one service without full stack rebuild

### Operational Benefits
1. **Isolated Failures**: One service crash doesn't affect others
2. **Targeted Deployments**: Deploy only changed services
3. **Better Monitoring**: Service-level metrics and logs
4. **Easier Debugging**: Smaller, focused codebases

---

## Migration Strategy

### Backward Compatibility
- Maintain all existing API endpoints at same paths
- Nginx proxies all requests to Core API
- Core API proxies to microservices transparently
- Zero changes required to frontend code

### Rollback Plan
- Keep monolithic backend as fallback
- Tag microservices images with version
- Can switch back by changing docker-compose.yaml

---

## Security Considerations

1. **Network Isolation**: Microservices only accessible via internal Docker network
2. **Authentication Centralization**: All auth in Core API
3. **Inter-Service Trust**: Services trust Core API via internal headers
4. **Rate Limiting**: Implement at Core API level
5. **Audit Logging**: Log all inter-service requests

---

## Future Enhancements

1. **Service Mesh**: Implement Istio or Linkerd for advanced routing
2. **Message Queue**: Add RabbitMQ/Redis for async communication
3. **API Gateway**: Replace simple proxy with Kong or similar
4. **Monitoring**: Prometheus + Grafana for service metrics
5. **Tracing**: Jaeger for distributed tracing

---

## Files to Create

```
microservices/
├── core-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── auth_optimized.py
│   ├── auth_utils.py
│   └── service_router.py (new - proxies to other services)
├── research-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py (FastAPI app)
│   └── research/ (copied from parent)
├── voice-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── chatterbox_tts.py
├── browser-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── browser.py
│   └── screen_analyzer.py
├── mcp-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── mcp/ (copied from parent)
├── n8n-integration/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── n8n/ (copied from parent)
└── vibe-coding/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py
    ├── vibecoding/ (copied from parent)
    └── ollama_cli/ (copied from parent)
```

---

## Status: Ready for Implementation

All planning complete. Ready to proceed with implementation.
