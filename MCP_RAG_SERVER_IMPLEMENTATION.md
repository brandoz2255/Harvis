# MCP RAG Server Implementation - 2026-03-27

## Summary

Implemented a complete MCP (Model Context Protocol) server that allows opencode/Claude Code to query the Harvis RAG vector database. Also added Red Hat and Arch Linux documentation sources to the RAG corpus.

---

## What Was Done Today

### 1. Added New RAG Documentation Sources

**File Modified:** `python_back_end/rag_corpus/source_config.py`

Added two new documentation sources to `DEFAULT_SOURCES`:

| Source | Description | Collection | Dimensions | Est. Docs |
|--------|-------------|------------|------------|-----------|
| `redhat_docs` | Red Hat Enterprise Linux docs - installation, administration, security, OpenShift | `local_rag_corpus_docs` | 768 (nomic-embed-text) | ~150-250 |
| `arch_linux_docs` | Arch Linux Wiki - Linux commands, system administration, kernel, networking | `local_rag_corpus_docs` | 768 (nomic-embed-text) | ~200-300 |

**Configuration Details:**
```python
"redhat_docs": SourceConfig(
    id="redhat_docs",
    name="Red Hat Documentation",
    description="Red Hat Enterprise Linux - installation, administration, security, OpenShift",
    category=SourceCategory.DEVOPS,
    embedding_tier=EmbeddingTier.STANDARD,  # nomic-embed-text (768 dims)
    fetcher_type="generic",
    base_url="https://access.redhat.com/documentation/en-us",
    url_patterns=["/documentation/", "/rhel/", "/openshift/"],
    exclude_patterns=["/ja/", "/ko/", "/zh/", "/legal/", "/errata/"],
    rate_limit_delay=1.0,
    max_pages=200,
),
"arch_linux_docs": SourceConfig(
    id="arch_linux_docs",
    name="Arch Linux Wiki",
    description="Arch Wiki - Linux commands, system administration, kernel, networking, security",
    category=SourceCategory.DEVOPS,
    embedding_tier=EmbeddingTier.STANDARD,  # nomic-embed-text (768 dims)
    fetcher_type="generic",
    base_url="https://wiki.archlinux.org",
    url_patterns=["/title/", "/wiki/"],
    exclude_patterns=["/Special:", "/Talk:", "/User:", "/Arch:", "/AUR:", "/Category:"],
    rate_limit_delay=0.7,
    max_pages=300,
),
```

---

### 2. Created MCP Server (11 New Files)

**Directory:** `python_back_end/mcp_server/`

#### Core Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package initialization |
| `registry.py` | Tool registry and invocation logic |
| `vectordb_client.py` | pgvector database client for similarity search |
| `embedding_client.py` | HTTP client for embedding generation (qwen3 + nomic) |
| `app.py` | FastAPI entrypoint with JSON-RPC MCP protocol |

#### Tool Implementations

| File | Tool Name | Collection | Model | Dimensions |
|------|-----------|------------|-------|------------|
| `tools/search_code.py` | `search_code` | `local_rag_corpus_code` | qwen3-embedding | 2560 |
| `tools/search_cyber.py` | `search_cyber` | `local_rag_corpus_docs` | nomic-embed-text | 768 |
| `tools/search_linux.py` | `search_linux` | `local_rag_corpus_docs` | nomic-embed-text | 768 |
| `tools/search_all.py` | `search_all` | both collections | both models | 2560 + 768 |
| `tools/get_sources.py` | `get_source_list` | metadata | N/A | N/A |

#### Tool Specifications

**`search_code`** - Search code/technical documentation
- **Input:** `{query: str, top_k: int = 5, sources: List[str] | None}`
- **Output:** `{results: [{text, source, similarity}]}`
- **Use case:** Kubernetes, Docker, GitHub, Stack Overflow queries

**`search_cyber`** - Search cybersecurity documentation
- **Input:** `{query: str, top_k: int = 5, sources: List[str] | None}`
- **Output:** `{results: [{text, source, similarity}]}`
- **Use case:** OWASP, MITRE ATT&CK, NVD, CIS benchmarks queries

**`search_linux`** - Search Linux commands (Red Hat + Arch only)
- **Input:** `{query: str, top_k: int = 5}`
- **Output:** `{results: [{text, source, similarity}]}`
- **Use case:** System administration, kubectl, systemctl, docker commands

**`search_all`** - Cross-collection search
- **Input:** `{query: str, top_k: int = 5}`
- **Output:** `{results: [{text, source, similarity}]}`
- **Use case:** General queries that might span code and docs

**`get_source_list`** - List available sources
- **Input:** `{}`
- **Output:** `{sources: {collection: {model, dims, sources: [{name, count}]}}, total_documents: int}`
- **Use case:** Discover what's available in the vector DB

---

### 3. Created K8s Deployment Manifest

**File:** `k8s-manifests/services/mcp-rag-server.yaml`

**Deployment Details:**
- **Name:** `harvis-ai-mcp-rag`
- **Namespace:** `ai-agents`
- **Image:** `harvis-ai-backend:latest` (reuses existing backend image)
- **Command:** `uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000`
- **Resources:** 500m CPU limit, 1Gi memory limit
- **Probes:** Health check on `/health` endpoint

**Environment Variables:**
- `DATABASE_URL` - From `harvis-db-creds` secret
- `EMBED_QW3_URL` - `http://10.42.2.5:8080` (dulc3-top qwen3 embedding)
- `EMBED_NOMIC_URL` - `http://10.42.2.5:8081` (dulc3-top nomic embedding)
- `PYTHONPATH` - `/app`

**Service:**
- **Type:** ClusterIP (internal only)
- **Port:** 8000

---

### 4. Code Validation

All Python files pass `py_compile`:
```bash
✅ mcp_server/__init__.py
✅ mcp_server/registry.py
✅ mcp_server/vectordb_client.py
✅ mcp_server/embedding_client.py
✅ mcp_server/app.py
✅ mcp_server/tools/__init__.py
✅ mcp_server/tools/search_code.py
✅ mcp_server/tools/search_cyber.py
✅ mcp_server/tools/search_linux.py
✅ mcp_server/tools/search_all.py
✅ mcp_server/tools/get_sources.py
✅ rag_corpus/source_config.py
```

---

## Next Steps for Deployment & Testing

### Step 1: Deploy MCP Server to K8s

```bash
# Apply the deployment
kubectl apply -f k8s-manifests/services/mcp-rag-server.yaml -n ai-agents

# Verify deployment
kubectl get pods -n ai-agents | grep mcp-rag

# Expected output:
# harvis-ai-mcp-rag-xxxxx   1/1   Running   0   <age>

# Check logs
kubectl logs -f deployment/harvis-ai-mcp-rag -n ai-agents

# Expected startup logs:
# Registered 5 tools: ['search_code', 'search_cyber', 'search_linux', 'search_all', 'get_source_list']
# VectorDB client initialized
# Embedding client initialized (qwen3: http://10.42.2.5:8080, nomic: http://10.42.2.5:8081)
# MCP RAG Server started
```

### Step 2: Test MCP Server Endpoints

```bash
# Port-forward for local testing
kubectl port-forward svc/harvis-ai-mcp-rag 8888:8000 -n ai-agents

# Test health endpoint
curl http://localhost:8888/health

# Expected response:
# {
#   "status": "healthy",
#   "tools": ["search_code", "search_cyber", "search_linux", "search_all", "get_source_list"],
#   "vectordb_connected": true,
#   "embedding_client_ready": true
# }

# Test list tools
curl http://localhost:8888/tools

# Test get_source_list tool
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tool.invoke",
    "params": {
      "name": "get_source_list",
      "args": {}
    }
  }'

# Test search_code tool
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "tool.invoke",
    "params": {
      "name": "search_code",
      "args": {
        "query": "kubernetes deployment rolling update",
        "top_k": 3
      }
    }
  }'

# Test search_linux tool
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "tool.invoke",
    "params": {
      "name": "search_linux",
      "args": {
        "query": "systemctl service management",
        "top_k": 5
      }
    }
  }'
```

### Step 3: Trigger RAG Update for New Sources

```bash
# Start background job to fetch Red Hat and Arch Linux docs
curl -X POST http://localhost:8000/api/rag/update-local \
  -H "Content-Type: application/json" \
  -d '{"sources": ["redhat_docs", "arch_linux_docs"]}'

# Expected response:
# {"job_id": "xxx-xxx-xxx", "status": "accepted", "message": "Job started for sources: ['redhat_docs', 'arch_linux_docs']"}

# Monitor job progress
curl http://localhost:8000/api/rag/jobs/<job_id>

# Or watch backend logs
kubectl logs -f deployment/harvis-ai-backend -n ai-agents

# This may take 15-30 minutes depending on network speed
```

### Step 4: Verify New Sources in Database

```bash
# Check source counts
kubectl exec -it harvis-ai-pgsql-668f97d75f-gphjd -n ai-agents -- \
  psql -U pguser -d database -c \
  "SELECT source, COUNT(*) as count FROM local_rag_corpus_docs GROUP BY source ORDER BY count DESC;"

# Expected output should include:
# source         | count
#----------------+-------
# owasp_docs     |  2566
# nvd_nist       |   744
# mitre_attack   |   480
# redhat_docs    |  ~150-250  <-- NEW
# arch_linux_docs|  ~200-300  <-- NEW
# cis_benchmarks |   227
# nist_csf       |    12
```

### Step 5: Configure opencode

**File:** `~/.config/opencode/opencode.json` (create if doesn't exist)

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

**For local testing (port-forward):**
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

### Step 6: Test from opencode/Claude Code

```bash
# Verify MCP server is recognized
opencode mcp list

# Expected output:
# MCP Servers
#   harvis-rag
#     ✓ authenticated
#     Tools:
#     - search_code
#     - search_cyber
#     - search_linux
#     - search_all
#     - get_source_list
```

**Test from opencode chat:**
```
User: "Search for kubernetes debugging commands"
# opencode should invoke search_linux tool

User: "How do I prevent SQL injection?"
# opencode should invoke search_cyber tool

User: "What's the best way to deploy a Kubernetes application?"
# opencode should invoke search_code or search_all tool
```

---

## Troubleshooting

### MCP Server Pod Not Starting

```bash
# Check logs for errors
kubectl logs deployment/harvis-ai-mcp-rag -n ai-agents

# Common issues:
# 1. DATABASE_URL not found - check secret exists
kubectl get secret harvis-db-creds -n ai-agents -o yaml

# 2. Embedding servers unreachable - verify dulc3-top is accessible
kubectl run test --rm -it --image=curlimages/curl -- curl http://10.42.2.5:8080
kubectl run test --rm -it --image=curlimages/curl -- curl http://10.42.2.5:8081

# 3. Python path issues - check PYTHONPATH env var
kubectl exec -it deployment/harvis-ai-mcp-rag -n ai-agents -- printenv PYTHONPATH
```

### Vector Search Returns Empty Results

```bash
# Verify data exists in database
kubectl exec -it harvis-ai-pgsql-668f97d75f-gphjd -n ai-agents -- \
  psql -U pguser -d database -c "SELECT COUNT(*) FROM local_rag_corpus_code;"
kubectl exec -it harvis-ai-pgsql-668f97d75f-gphjd -n ai-agents -- \
  psql -U pguser -d database -c "SELECT COUNT(*) FROM local_rag_corpus_docs;"

# Check embedding server is working
curl http://10.42.2.5:8080/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-embedding", "prompt": "test"}'
```

### RAG Update Job Fails

```bash
# Check job status
curl http://localhost:8000/api/rag/jobs/<job_id>

# Check backend logs
kubectl logs -f deployment/harvis-ai-backend -n ai-agents

# Common issues:
# 1. Network connectivity to source sites
# 2. Rate limiting - increase rate_limit_delay in source config
# 3. Source site structure changed - check url_patterns
```

---

## Files Created/Modified

### Created (12 files)
```
python_back_end/mcp_server/
├── __init__.py
├── app.py
├── registry.py
├── vectordb_client.py
├── embedding_client.py
└── tools/
    ├── __init__.py
    ├── search_code.py
    ├── search_cyber.py
    ├── search_linux.py
    ├── search_all.py
    └── get_sources.py

k8s-manifests/services/
└── mcp-rag-server.yaml
```

### Modified (1 file)
```
python_back_end/rag_corpus/source_config.py
  - Added redhat_docs source config
  - Added arch_linux_docs source config
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    opencode CLI                             │
│  (MCP Client configured in ~/.config/opencode/opencode.json)│
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP POST /mcp/invoke
                        │ JSON-RPC 2.0
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              harvis-ai-mcp-rag Service                      │
│              (ai-agents namespace, ClusterIP:8000)          │
│                                                             │
│  FastAPI Server (uvicorn)                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Tools Registry                                     │   │
│  │  - search_code (qwen3-embedding → 2560-dim)        │   │
│  │  - search_cyber (nomic-embed-text → 768-dim)       │   │
│  │  - search_linux (nomic-embed-text → 768-dim)       │   │
│  │  - search_all (both models)                        │   │
│  │  - get_source_list (metadata)                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                        │                                    │
│  Embedding Client      │  VectorDB Client                  │
│  ┌────────────────────┴──────────────────────┐            │
│  │ qwen3: http://10.42.2.5:8080              │            │
│  │ nomic: http://10.42.2.5:8081              │            │
│  └────────────────────┬──────────────────────┘            │
│                       │                                    │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              harvis-ai-pgsql (PostgreSQL + pgvector)        │
│                                                             │
│  Tables:                                                    │
│  - local_rag_corpus_code (2560-dim halfvec)                │
│    * kubernetes_docs, github, stack_overflow, docker_docs  │
│  - local_rag_corpus_docs (768-dim vector)                  │
│    * owasp_docs, mitre_attack, nvd_nist,                   │
│      redhat_docs, arch_linux_docs, cis_benchmarks          │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Notes

- **Embedding generation:** ~100-500ms per query (depends on model size)
- **Vector search:** ~10-50ms per collection (HNSW index)
- **Total latency:** ~200-600ms for single-collection search, ~400-1000ms for cross-collection
- **Concurrent requests:** Limited by embedding server capacity (single pod on dulc3-top)

---

## Future Enhancements

1. **Hybrid search:** Combine semantic + keyword matching for better precision
2. **Re-ranking:** Use cross-encoder for top-k re-ranking
3. **Caching:** Cache frequent query embeddings
4. **Multi-query batching:** Process multiple queries in parallel
5. **Source weighting:** Allow users to prioritize certain sources
6. **Pagination:** Support for fetching more than top_k results

---

**Date:** 2026-03-27
**Status:** ✅ Implementation Complete, Ready for Deployment
