---
name: harvis-mcp-rag
description: >
  MCP (Model Context Protocol) server for querying Harvis RAG vector database.
  Provides 5 tools for semantic search across code and documentation.
always: true
requires:
  bins: [curl, jq]
---

# Harvis MCP RAG Server — Skill Documentation

**Created:** 2026-03-27  
**Status:** Implemented and ready for deployment

---

## Overview

The Harvis MCP RAG server is a FastAPI service that exposes 5 tools for querying the Harvis RAG vector database via the Model Context Protocol (MCP). This allows opencode/Claude Code to directly search the vectorDB for relevant code, documentation, and Linux commands.

### Server Details

| Property | Value |
|----------|-------|
| **Service Name** | `harvis-ai-mcp-rag` |
| **Namespace** | `ai-agents` |
| **Endpoint** | `http://harvis-ai-mcp-rag.ai-agents.svc.cluster.local:8000/mcp` |
| **Protocol** | JSON-RPC 2.0 |
| **Image** | `harvis-ai-backend:latest` |

---

## Available Tools

### 1. search_code

Search code and technical documentation (2560-dimensional Qwen3 embeddings).

**Collection:** `local_rag_corpus_code`  
**Model:** qwen3-embedding  
**Sources:** kubernetes_docs, github, stack_overflow, docker_docs, python_docs, nextjs_docs

**Input:**
```json
{
  "query": "kubernetes deployment rolling update",
  "top_k": 5,
  "sources": ["kubernetes_docs", "github"]  // optional filter
}
```

**Output:**
```json
{
  "results": [
    {
      "text": "...",
      "source": "kubernetes_docs",
      "similarity": 0.87
    }
  ]
}
```

---

### 2. search_cyber

Search cybersecurity documentation (768-dimensional nomic embeddings).

**Collection:** `local_rag_corpus_docs`  
**Model:** nomic-embed-text  
**Sources:** owasp_docs, mitre_attack, nvd_nist, cis_benchmarks, nist_csf

**Input:**
```json
{
  "query": "SQL injection prevention",
  "top_k": 5,
  "sources": ["owasp_docs"]  // optional filter
}
```

**Output:**
```json
{
  "results": [
    {
      "text": "...",
      "source": "owasp_docs",
      "similarity": 0.91
    }
  ]
}
```

---

### 3. search_linux

Search Linux commands and system administration (Red Hat + Arch Linux docs only).

**Collection:** `local_rag_corpus_docs`  
**Model:** nomic-embed-text  
**Sources:** redhat_docs, arch_linux_docs (auto-filtered)

**Input:**
```json
{
  "query": "systemctl service management",
  "top_k": 5
}
```

**Output:**
```json
{
  "results": [
    {
      "text": "systemctl start|stop|restart [service]...",
      "source": "arch_linux_docs",
      "similarity": 0.91
    }
  ]
}
```

---

### 4. search_all

Cross-collection search (both code and docs, merged by similarity).

**Collections:** `local_rag_corpus_code` + `local_rag_corpus_docs`  
**Models:** qwen3-embedding + nomic-embed-text

**Input:**
```json
{
  "query": "docker container networking",
  "top_k": 10
}
```

**Output:**
```json
{
  "results": [
    {
      "text": "...",
      "source": "docker_docs",
      "similarity": 0.89
    },
    {
      "text": "...",
      "source": "arch_linux_docs",
      "similarity": 0.83
    }
  ]
}
```

---

### 5. get_source_list

List all available sources and their document counts.

**Input:**
```json
{}
```

**Output:**
```json
{
  "sources": {
    "local_rag_corpus_code": {
      "embedding_model": "qwen3-embedding",
      "dimensions": 2560,
      "sources": [
        {"name": "kubernetes_docs", "count": 150},
        {"name": "github", "count": 410}
      ]
    },
    "local_rag_corpus_docs": {
      "embedding_model": "nomic-embed-text",
      "dimensions": 768,
      "sources": [
        {"name": "owasp_docs", "count": 2566},
        {"name": "redhat_docs", "count": 189},
        {"name": "arch_linux_docs", "count": 267}
      ]
    }
  },
  "total_documents": 5347
}
```

---

## Deployment

### Apply K8s Manifest

```bash
kubectl apply -f k8s-manifests/services/mcp-rag-server.yaml -n ai-agents
```

### Verify Deployment

```bash
# Check pod status
kubectl get pods -n ai-agents | grep mcp-rag
# Expected: harvis-ai-mcp-rag-xxxxx   1/1   Running

# Check logs
kubectl logs -f deployment/harvis-ai-mcp-rag -n ai-agents
# Expected startup:
# Registered 5 tools: ['search_code', 'search_cyber', 'search_linux', 'search_all', 'get_source_list']
# VectorDB client initialized
# Embedding client initialized (qwen3: http://10.42.2.5:8080, nomic: http://10.42.2.5:8081)
# MCP RAG Server started
```

### Port-Forward for Testing

```bash
kubectl port-forward svc/harvis-ai-mcp-rag 8888:8000 -n ai-agents
```

---

## Testing

### Health Check

```bash
curl http://localhost:8888/health
```

Expected:
```json
{
  "status": "healthy",
  "tools": ["search_code", "search_cyber", "search_linux", "search_all", "get_source_list"],
  "vectordb_connected": true,
  "embedding_client_ready": true
}
```

### Test Tool Invocation

```bash
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tool.invoke",
    "params": {
      "name": "search_code",
      "args": {
        "query": "kubernetes pod health check",
        "top_k": 3
      }
    }
  }'
```

---

## opencode Configuration

Add to `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "harvis-rag": {
      "type": "remote",
      "url": "http://harvis-ai-mcp-rag.ai-agents.svc.cluster.local:8000/mcp",
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

For local testing (with port-forward):
```json
{
  "mcp": {
    "harvis-rag": {
      "type": "remote",
      "url": "http://localhost:8888/mcp",
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

Verify opencode recognizes the server:
```bash
opencode mcp list
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    opencode CLI                             │
│  (MCP Client in ~/.config/opencode/opencode.json)           │
└───────────────────────┬─────────────────────────────────────┘
                        │ JSON-RPC 2.0 POST /mcp/invoke
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              harvis-ai-mcp-rag Service                      │
│              (ai-agents namespace, ClusterIP:8000)          │
│                                                             │
│  FastAPI + Uvicorn                                          │
│  Tools: search_code, search_cyber, search_linux,            │
│         search_all, get_source_list                         │
└───────────────────────┬─────────────────────────────────────┘
                        │
         ┌──────────────┴──────────────┐
         │                             │
         ▼                             ▼
┌─────────────────┐         ┌─────────────────┐
│  Embedding      │         │  VectorDB       │
│  Client         │         │  Client         │
│                 │         │                 │
│  qwen3:8080     │         │  pgvector       │
│  nomic:8081     │         │  - local_rag_   │
│                 │         │    corpus_code  │
│                 │         │  - local_rag_   │
│                 │         │    corpus_docs  │
└─────────────────┘         └─────────────────┘
         │                             │
         └───────────┬─────────────────┘
                     ▼
         ┌─────────────────────────┐
         │  dulc3-top (GTX 1650 Ti)│
         │  - qwen3-embedding:8080 │
         │  - nomic-embed-text:8081│
         └─────────────────────────┘
```

---

## File Structure

```
python_back_end/mcp_server/
├── __init__.py              # Package init
├── app.py                   # FastAPI entrypoint
├── registry.py              # Tool registry & invocation
├── vectordb_client.py       # pgvector similarity search
├── embedding_client.py      # HTTP client for embeddings
└── tools/
    ├── __init__.py          # Tool registration
    ├── search_code.py       # Code search (2560-dim)
    ├── search_cyber.py      # Cyber docs search (768-dim)
    ├── search_linux.py      # Linux commands (768-dim)
    ├── search_all.py        # Cross-collection search
    └── get_sources.py       # Source listing

k8s-manifests/services/
└── mcp-rag-server.yaml      # Deployment + Service
```

---

## RAG Corpus Sources

### Code Collection (2560-dim, qwen3-embedding)

| Source | Count | Description |
|--------|-------|-------------|
| kubernetes_docs | ~150 | Kubernetes concepts, tasks, references |
| github | ~410 | Code from GitHub repos |
| stack_overflow | ~690 | Programming Q&A |
| docker_docs | ~218 | Docker engine, compose, swarm |

### Docs Collection (768-dim, nomic-embed-text)

| Source | Count | Description |
|--------|-------|-------------|
| owasp_docs | ~2566 | OWASP security cheat sheets |
| nvd_nist | ~744 | National Vulnerability Database |
| mitre_attack | ~480 | MITRE ATT&CK framework |
| cis_benchmarks | ~227 | CIS hardening benchmarks |
| **redhat_docs** | **~150-250** | **Red Hat Enterprise Linux** |
| **arch_linux_docs** | **~200-300** | **Arch Linux Wiki** |

---

## Performance

| Operation | Latency |
|-----------|---------|
| Embedding generation (qwen3) | ~200-500ms |
| Embedding generation (nomic) | ~100-300ms |
| Vector search (single collection) | ~10-50ms |
| Total (single tool) | ~200-600ms |
| Total (search_all) | ~400-1000ms |

---

## Troubleshooting

### Pod Not Starting

```bash
# Check logs
kubectl logs deployment/harvis-ai-mcp-rag -n ai-agents

# Verify secret exists
kubectl get secret harvis-db-creds -n ai-agents

# Test embedding server connectivity
kubectl run test --rm -it --image=curlimages/curl -- \
  curl http://10.42.2.5:8080
```

### Empty Search Results

```bash
# Verify data in database
kubectl exec -it harvis-ai-pgsql -n ai-agents -- \
  psql -U pguser -d database -c \
  "SELECT source, COUNT(*) FROM local_rag_corpus_docs GROUP BY source;"
```

### RAG Update Failed

```bash
# Check job status
curl http://localhost:8000/api/rag/jobs/<job_id>

# Monitor backend logs
kubectl logs -f deployment/harvis-ai-backend -n ai-agents
```

---

## Related Documentation

- **Main Implementation:** `MCP_RAG_SERVER_IMPLEMENTATION.md`
- **RAG Corpus:** `skills/Harvis/harvis-rag/SKILL.md`
- **GPU Troubleshooting:** `fixes/gpu-xid-69-low-power-mode-fix.md`

---

**Last Updated:** 2026-03-27  
**Version:** 1.0.0
