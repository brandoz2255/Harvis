# OpenClaw RAG Integration Plan

**Created:** 2026-03-31  
**Status:** Research/Planning  
**Priority:** Low

---

## Goal

Enable OpenClaw agents to use the same RAG (Retrieval-Augmented Generation) tools that the MCP server exposes to opencode/Claude Code. This allows OpenClaw to query the Harvis vector database for:
- Code & tech documentation (`search_code`)
- Cybersecurity docs (`search_cyber`)
- Linux commands (`search_linux`)
- Cross-collection search (`search_all`)

---

## Architecture Options

### Option 1: Internal HTTP API (Recommended)

Expose RAG tools as internal HTTP endpoints that OpenClaw can call.

**Pros:**
- Reuse existing MCP server code
- Simple HTTP requests from OpenClaw
- No code duplication
- Easy to monitor/debug

**Cons:**
- Requires exposing new internal endpoints
- Slight overhead of HTTP vs direct function calls

**Implementation:**
```
┌─────────────────┐
│   OpenClaw      │
│   (agent tools) │
└────────┬────────┘
         │ HTTP POST
         │ http://harvis-ai-mcp-rag:8000/api/rag/search
         ▼
┌─────────────────────────────────┐
│  MCP RAG Server                 │
│  - /api/rag/search_code         │
│  - /api/rag/search_cyber        │
│  - /api/rag/search_linux        │
│  - /api/rag/search_all          │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  VectorDB (pgvector)            │
│  - local_rag_corpus_code        │
│  - local_rag_corpus_docs        │
└─────────────────────────────────┘
```

### Option 2: Shared Python Module

Move RAG tool logic to a shared Python package that both MCP server and OpenClaw can import.

**Pros:**
- No code duplication
- Direct function calls (fastest)
- Type safety

**Cons:**
- OpenClaw is Node.js-based, not Python
- Would require a Python sidecar or subprocess

**Verdict:** Not feasible for OpenClaw (JavaScript runtime)

### Option 3: OpenClaw Extension (JavaScript)

Create an OpenClaw extension/skill that wraps the MCP server HTTP API.

**Pros:**
- Native OpenClaw integration
- Can be configured via openclaw.json
- Follows OpenClaw extension patterns

**Cons:**
- Requires writing JavaScript extension
- Adds maintenance overhead

**Verdict:** Good long-term solution, but Option 1 is faster

---

## Recommended Implementation: Option 1 + Option 3 Hybrid

### Phase 1: Add Internal HTTP Endpoints (Fast)

Add simple HTTP endpoints to the MCP server that OpenClaw can call:

```python
# python_back_end/mcp_server/app.py

@app.post("/api/rag/search")
async def rag_search(request: RAGSearchRequest) -> RAGSearchResponse:
    """Internal API for OpenClaw to query RAG."""
    tool = TOOL_REGISTRY.get_tool(request.tool_name)
    if not tool:
        raise HTTPException(404, f"Unknown tool: {request.tool_name}")
    
    results = await tool.fn(**request.args)
    return RAGSearchResponse(results=results)
```

**Request:**
```json
{
  "tool_name": "search_code",
  "args": {
    "query": "kubernetes deployment rolling update",
    "top_k": 5
  }
}
```

**Response:**
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

### Phase 2: Create OpenClaw Skill (Later)

Create a `harvis-rag` skill in OpenClaw that wraps the HTTP API:

```javascript
// openclaw/openclaw/skills/harvis-rag/index.js

export default {
  name: "harvis-rag",
  tools: {
    searchCode: async ({ query, topK = 5 }) => {
      const response = await fetch("http://harvis-ai-mcp-rag:8000/api/rag/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_name: "search_code",
          args: { query, top_k: topK }
        })
      });
      return response.json();
    },
    // ... other tools
  }
};
```

---

## Implementation Steps

### Step 1: Add HTTP Endpoints to MCP Server

**File:** `python_back_end/mcp_server/app.py`

1. Add Pydantic models for request/response
2. Add `/api/rag/search` endpoint
3. Validate tool_name against registry
4. Call tool function and return results

### Step 2: Update K8s Service

**File:** `k8s-manifests/overlays/prod/mcp-rag-server.yaml`

No changes needed - LoadBalancer already exposes port 8000

### Step 3: Create OpenClaw Skill

**File:** `openclaw/openclaw/skills/harvis-rag/`

1. Create skill directory structure
2. Implement JavaScript wrapper for HTTP API
3. Add skill manifest
4. Test with OpenClaw agent

### Step 4: Configure OpenClaw

**File:** `openclaw/openclaw.json`

Add harvis-rag skill to agent defaults:

```json
{
  "agents": {
    "defaults": {
      "skills": ["harvis-rag"]
    }
  }
}
```

---

## Security Considerations

### Current State (No Auth)
- MCP server is exposed via LoadBalancer (`192.168.10.246`)
- No authentication required
- **Risk:** Anyone on local network can query RAG

### Mitigation Options

1. **Network Isolation (Already Done)**
   - OpenClaw pod is on internal-only network
   - Can only reach `harvis-ai-mcp-rag` via K8s DNS
   - Cannot reach external networks

2. **API Key (Future)**
   - Add `X-API-Key` header validation
   - Store key in `harvis-backend-env` secret
   - OpenClaw reads key from env var

3. **mTLS (Overkill)**
   - Mutual TLS between OpenClaw and MCP server
   - Complex to manage certificates
   - Not needed for internal-only traffic

**Recommendation:** Keep no auth for now (local network only), add API key later if needed

---

## Testing

### Test HTTP Endpoint

```bash
# From any machine on local network
curl -X POST http://192.168.10.246:8000/api/rag/search \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "search_code",
    "args": {
      "query": "kubernetes deployment",
      "top_k": 3
    }
  }'
```

### Test from OpenClaw Pod

```bash
kubectl exec -it deployment/harvis-ai-openclaw -n ai-agents -- sh

# Inside pod
curl -X POST http://harvis-ai-mcp-rag:8000/api/rag/search \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"search_linux","args":{"query":"systemctl restart","top_k":3}}'
```

---

## Related Files

- **MCP Server:** `python_back_end/mcp_server/app.py`
- **VectorDB Client:** `python_back_end/mcp_server/vectordb_client.py`
- **Embedding Client:** `python_back_end/mcp_server/embedding_client.py`
- **Tools Registry:** `python_back_end/mcp_server/registry.py`
- **K8s Manifest:** `k8s-manifests/overlays/prod/mcp-rag-server.yaml`
- **OpenClaw Config:** `openclaw/openclaw/openclaw.json`

---

## Next Steps

1. ✅ Expose MCP server via LoadBalancer
2. ⏳ Add HTTP `/api/rag/search` endpoint to MCP server
3. ⏳ Create OpenClaw `harvis-rag` skill
4. ⏳ Test end-to-end from OpenClaw agent
5. ⏳ Document usage in OpenClaw AGENTS.md

---

**Last Updated:** 2026-03-31
