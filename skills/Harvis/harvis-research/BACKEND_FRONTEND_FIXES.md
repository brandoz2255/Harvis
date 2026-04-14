# Harvis Backend & Frontend Integration Troubleshooting

## Common Startup Errors & Fixes

### 1. FastAPI WebSocket `tags` Parameter Error

**Error:**
```
TypeError: FastAPI.websocket() got an unexpected keyword argument 'tags'
```

**Cause:** FastAPI's `@app.websocket()` decorator does NOT support the `tags` parameter (unlike `@app.get()`, `@app.post()`, etc.).

**Fix:**
```python
# ❌ WRONG
@app.websocket("/api/jobs/events/{queue_name}", tags=["jobs"])

# ✅ CORRECT
@app.websocket("/api/jobs/events/{queue_name}")
```

**Location:** `python_back_end/main.py`

---

### 2. Research Agent `default_model` Parameter Error

**Error:**
```
TypeError: ResearchAgent.__init__() got an unexpected keyword argument 'default_model'
```

**Cause:** The `ResearchAgent` class was refactored to use `model` instead of `default_model`. The hardcoded `"mistral"` default was removed (the "mistral virus" from an old hallucinating model).

**Fix:**
```python
# ❌ OLD (broken)
research_agent_instance = ResearchAgent(
    ollama_url="http://ollama:11434",
    default_model="mistral",  # Removed - no more hardcoded defaults
)

# ✅ NEW (correct)
research_agent_instance = ResearchAgent(
    ollama_url=os.getenv("OLLAMA_URL", "http://localhost:8080/v1"),
    model="mistral",  # Will be overridden by req.model at runtime
)
```

**Files to check when adding new research agent instances:**
- `python_back_end/agent_research.py`
- `python_back_end/research/research_agent.py`
- `python_back_end/research/enhanced_research_agent.py`

**Rule:** Always pass `model=` not `default_model=`. The model name should come from `req.model` at runtime, not be hardcoded.

---

### 3. WebSocket Mixed Content Error (HTTPS → ws://)

**Error (in browser console):**
```
DOMException: The operation is insecure.
```

**Cause:** The site is served over HTTPS but the WebSocket URL hardcodes `ws://`. Browsers block mixed content (secure page → insecure WebSocket).

**Fix:**
```typescript
// ❌ WRONG - hardcoded ws://
const wsUrl = `ws://${window.location.host}/api/jobs/events/research-updates`

// ✅ CORRECT - use wss:// for HTTPS, ws:// for HTTP
const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const wsUrl = `${wsProto}//${window.location.host}/api/jobs/events/research-updates`
```

**Location:** `front_end/newjfrontend/app/page.tsx`

**Rule:** Always derive WebSocket protocol from `window.location.protocol`:
- `https:` → `wss:`
- `http:` → `ws:`

---

### 4. Ollama URL Points to Wrong Service

**Error:**
```
Error querying LLM: 500 Server Error: Internal Server Error for url: http://harvis-ai-llama-embed:8081/api/chat
```

**Cause:** Research agent was using `http://ollama:11434` or `http://harvis-ai-llama-embed:8081` but the merged pod uses llama-server on `localhost:8080/v1`.

**Fix:**
```python
# ❌ OLD (broken)
ollama_url = "http://ollama:11434"  # External Ollama service
ollama_url = "http://harvis-ai-llama-embed:8081"  # Embedding model (can't do chat!)

# ✅ NEW (correct)
ollama_url = os.getenv("OLLAMA_URL", "http://localhost:8080/v1")  # llama-server in same pod
```

**Files updated:**
- `python_back_end/research/config/settings.py`
- `python_back_end/research/research_agent.py`
- `python_back_end/research/enhanced_research_agent.py`
- `python_back_end/research/llm/ollama_client.py`
- `python_back_end/agent_research.py`

**Note:** The env var is still named `OLLAMA_URL` for backward compatibility, but it now points to llama-server, not Ollama.

---

## CI Pipeline Best Practices

### Always Use CI Pipeline, Not Direct Git Commands

```bash
# ✅ CORRECT
./ci_pipeline.sh -f v2.34.40 -b v2.34.40 -m "fix: description" -p -y

# ❌ WRONG - won't update kustomization or build images
git add . && git commit -m "fix" && git push
```

### Version Bumping

Always increment version by 1 from the last deployed version:
- If last was `v2.34.39`, use `v2.34.40`
- The CI pipeline updates kustomization automatically

### When Pod Crashes After Deploy

1. Check if image was built BEFORE the fix was committed
2. Force restart: `kubectl rollout restart deployment/<name> -n <namespace>`
3. Delete old crashing pod: `kubectl delete pod <name> -n <namespace> --grace-period=0 --force`
4. Rebuild with new version tag

---

## Research Agent Architecture

### LLM-Driven Web Search Flow

```
User query → LLM generates response
  ↓
LLM emits: <web_search>query here</web_search>
  ↓
Backend: parse_web_search_tags() extracts query
  ↓
Research: async_research_agent(query, model=req.model)
  ↓
llama-server: localhost:8080/v1 (NOT ollama!)
  ↓
Results prepended to response
  ↓
pg-boss: Publish to 'research-updates' queue
  ↓
WebSocket: Frontend receives update via wss://
  ↓
UI: Auto-refresh research chain
```

### Key Functions

| Function | File | Purpose |
|----------|------|---------|
| `parse_web_search_tags()` | `main.py` | Extract `<web_search>` tags from LLM response |
| `extract_web_search_context()` | `main.py` | Remove tags, return clean response |
| `async_research_agent()` | `agent_research.py` | Execute research with fallback |
| `research_agent_instance.research_topic()` | `agent_research.py` | Fallback simple research |

### Model Selection Rule

Research agent MUST use the model selected by the user (`req.model`). No hardcoded defaults. If the model fails, research fails — no silent fallback to other models.
