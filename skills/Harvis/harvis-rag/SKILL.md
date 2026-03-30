---
name: harvis-rag
description: >
  Search the Harvis local vector database for relevant code and documentation.
  Always loaded. Use this BEFORE saying "I don't know" — the answer may already
  be in the knowledge base.
always: true
requires:
  bins: [curl, jq]
---

# Harvis RAG — Vector Search Skill

## When to use (mandatory)

**Search the RAG before:**
- Saying "I don't know", "I'm not sure", or "I don't have that information"
- Writing a new function, class, or module — it may already exist
- Answering questions about how something works in the codebase
- Answering questions about the project architecture or design decisions
- Looking up any internal API, endpoint, config, or schema

If the RAG returns no results (total: 0) or all scores are below 0.4, then you can say you don't know.

---

## Corpus types

| `context_type` | Use for |
|---------------|---------|
| `"code"` | Functions, classes, file content, implementation patterns, endpoints |
| `"docs"` | Architecture docs, README content, design decisions, how-tos |

When unsure, run **both** — one code search and one docs search.

---

## Search — code corpus

```bash
curl -s -X POST http://backend:8000/rag/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -d '{
    "query": "YOUR QUERY HERE",
    "context_type": "code",
    "top_k": 5,
    "score_threshold": 0.3
  }' | jq '.results[] | {score, source, text: .text[:400]}'
```

## Search — docs corpus

```bash
curl -s -X POST http://backend:8000/rag/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -d '{
    "query": "YOUR QUERY HERE",
    "context_type": "docs",
    "top_k": 5,
    "score_threshold": 0.3
  }' | jq '.results[] | {score, source, text: .text[:400]}'
```

## With NVIDIA reranker (better precision, use when top results look marginal)

Add `"rerank": true` to re-score results. Only works if `NVIDIA_API_KEY` is set — falls back silently if not.

```bash
curl -s -X POST http://backend:8000/rag/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  -d '{
    "query": "YOUR QUERY HERE",
    "context_type": "code",
    "top_k": 8,
    "score_threshold": 0.25,
    "rerank": true
  }' | jq '.results[] | {score, source, text: .text[:400]}'
```

---

## Response format

```json
{
  "query": "original query",
  "context_type": "code",
  "results": [
    {
      "id": "chunk-id",
      "text": "the relevant code or text chunk",
      "source": "path/to/file.py",
      "metadata": {},
      "score": 0.85
    }
  ],
  "total": 5,
  "reranked": false
}
```

---

## Score interpretation

| Score | Meaning |
|-------|---------|
| ≥ 0.7 | Strong match — use this |
| 0.5–0.7 | Good match — likely relevant |
| 0.3–0.5 | Weak match — use with judgment |
| < 0.3 | Not returned (filtered by threshold) |

---

## Rules

1. **Search before saying "I don't know"** — this is not optional.
2. Run both `"code"` and `"docs"` searches if the question could span either corpus.
3. Never make web requests for internal knowledge — this endpoint is the only path.
4. If `total: 0` after both searches, you may admit uncertainty.
5. Cite the `source` file path when using a result in your answer.

---

## MCP RAG Server Tools (2026-03-27)

### Overview

As of 2026-03-27, an MCP (Model Context Protocol) server was implemented to allow opencode/Claude Code to directly query the RAG vector database. The MCP server exposes 5 tools for semantic search across the vectorDB.

### MCP Server Details

**Service:** `harvis-ai-mcp-rag` in `ai-agents` namespace  
**Endpoint:** `http://harvis-ai-mcp-rag.ai-agents.svc.cluster.local:8000/mcp`  
**Protocol:** JSON-RPC 2.0

### Available Tools

| Tool | Collection | Model | Dimensions | Description |
|------|------------|-------|------------|-------------|
| `search_code` | `local_rag_corpus_code` | qwen3-embedding | 2560 | Search code/tech docs |
| `search_cyber` | `local_rag_corpus_docs` | nomic-embed-text | 768 | Search cyber security docs |
| `search_linux` | `local_rag_corpus_docs` | nomic-embed-text | 768 | Search Linux commands (Red Hat + Arch) |
| `search_all` | both collections | both models | 2560 + 768 | Cross-collection search |
| `get_source_list` | metadata | N/A | N/A | List available sources |

### Tool Usage Examples

#### search_code

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
        "query": "kubernetes deployment rolling update",
        "top_k": 5,
        "sources": ["kubernetes_docs", "github"]
      }
    }
  }'
```

#### search_linux

```bash
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
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

#### get_source_list

```bash
curl -X POST http://localhost:8888/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "tool.invoke",
    "params": {
      "name": "get_source_list",
      "args": {}
    }
  }'
```

### opencode Configuration

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

### New RAG Sources (2026-03-27)

Two new documentation sources were added to the RAG corpus:

| Source | Description | Collection | Docs |
|--------|-------------|------------|------|
| `redhat_docs` | Red Hat Enterprise Linux docs - installation, administration, security, OpenShift | `local_rag_corpus_docs` | ~150-250 |
| `arch_linux_docs` | Arch Linux Wiki - Linux commands, system administration, kernel, networking | `local_rag_corpus_docs` | ~200-300 |

### Triggering RAG Updates

To fetch new content from the added sources:

```bash
curl -X POST http://localhost:8000/api/rag/update-local \
  -H "Content-Type: application/json" \
  -d '{"sources": ["redhat_docs", "arch_linux_docs"]}'
```

### File Locations

| File | Purpose |
|------|---------|
| `python_back_end/mcp_server/app.py` | FastAPI entrypoint |
| `python_back_end/mcp_server/registry.py` | Tool registry |
| `python_back_end/mcp_server/vectordb_client.py` | pgvector queries |
| `python_back_end/mcp_server/embedding_client.py` | Embedding generation |
| `python_back_end/mcp_server/tools/` | 5 tool implementations |
| `k8s-manifests/services/mcp-rag-server.yaml` | K8s deployment |

### Architecture

```
opencode CLI → MCP Server (harvis-ai-mcp-rag:8000) → pgvector DB
                                    ↓
                          Embedding Servers (dulc3-top)
                          - qwen3:8080 (2560-dim)
                          - nomic:8081 (768-dim)
```
