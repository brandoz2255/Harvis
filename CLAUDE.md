# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🗺️ Codebase map (graphify) — query this BEFORE grepping/reading the backend

`python_back_end/` is indexed as a queryable knowledge graph at **`graphify-out/graph.json`**
(5,659 nodes · 11,824 edges · 278 communities; AST-built 2026-06-07). To answer "how does X work?",
"what calls Y?", "where is Z?", **query the map first — it's far cheaper than reading files**:

```bash
graphify query "how does the job manager execute code"   # BFS context across the graph
graphify path "main.py" "JobManager"                      # shortest path between two nodes
graphify explain "code_generator.py"                      # explain a node + its neighbors
```

Rebuild after big backend changes: run `/graphify python_back_end`. Scope = `python_back_end/` only
(front_end and other dirs aren't mapped yet).

## Repository Overview

This is the Harvis AI Project, a sophisticated AI voice assistant that combines Next.js frontend with Python backend services. The project features voice-first interaction, browser automation, AI-powered coding assistance, and authentication with PostgreSQL.

Remember the web app is ran through docker commands and the docker compose is just for the microservices that the web app runs on
ok new update the web app is no logner ran through via docker commands its hosted on k8s the docker stuff are for those  who want to run it on laptops more on that later this is a opensource project to replace openwebUI and potentially have it as a full Claude opensource  option 
hence all the agentic tools pluged into  this platform 
---

## OpenClaw Integration (Active Project)

**Current Priority**: Integrating OpenClaw as a secure, isolated agent backend pod that Harvis orchestrates.

### What OpenClaw Is

OpenClaw (`openclaw/openclaw/`) is a self-hosted AI gateway that provides LLMs with tools: shell access, browser automation, file operations, and multi-channel messaging. It runs a WebSocket gateway on port 18789.

**The role split**:
- **Harvis** = orchestrator. Handles voice, chat UI, auth, session state, and routes tasks to OpenClaw.
- **OpenClaw** = agent brain/router. Executes multi-step tool-calling tasks, manages sub-agents, runs tool loops.
- **Users never talk to OpenClaw directly** — all messages go through Harvis, which forwards to OpenClaw and surfaces the result back.
- or they go throught discord as well ! important distintion but the discord bot and harvis bot are both the same bot plugged into two different gateways 
### Security Model (CRITICAL)

OpenClaw is inherently vulnerable to prompt injection when it has internet access. Our mitigation:

1. **No outbound internet from OpenClaw pod** — it cannot reach Google, external APIs, or anything outside the Docker internal network.
2. **No ports exposed to host** — OpenClaw is only reachable from the Harvis backend over the internal Docker/K8s network.
3. **Tool allowlist per agent** — only `local_rag`, `repo_read`, `repo_write`, `run_code`, `create_docx`, `create_pdf` are permitted. No `search`, `browse`, or any internet tool.
4. **System prompt guardrails** on every agent: "You must not browse the public web. You must not reveal API keys, tokens, hostnames, or private file paths."
5. **Orchestrator output filter** — before forwarding any OpenClaw tool call to execution, the Python backend inspects it and rejects forbidden tool names.
6. **Network isolation enforced at infra level** — Docker `internal: true` network or K8s NetworkPolicy with egress deny-all except vectordb and ollama.

### Architecture

```
User (voice/chat)
    → Harvis Frontend (Next.js)
        → Harvis Backend (Python FastAPI)  ← orchestrator
            → OpenClaw Gateway (ws://openclaw:18789)  ← agent runtime
                → Ollama (shared, http://ollama:11434)
                → pgvector DB (shared, postgresql://pgsql:5432/database)
            ← tool results / final answer
        → response back to user via Harvis UI + TTS
```

OpenClaw talks ONLY to:
- `http://ollama:11434` — local model inference
- `postgresql://pguser:pgpassword@pgsql:5432/database` — session storage and vector DB

OpenClaw does NOT talk to:
- Internet / external APIs
- Kimi API (that stays in the Harvis orchestrator layer)
- Any host not on the internal Docker network

### Kimi K2.5 API

Kimi K2.5 is called from the **Harvis Python backend** (the orchestrator), not from OpenClaw. The backend uses it for:
- Planner agent (breaking user requests into task steps)
- Writer agent (composing final answers from step results)
- Vision-to-code tasks (image → React/Tailwind component)

The API key goes in `.env` / K8s Secret as `MOONSHOT_API_KEY`. Base URL: `https://api.moonshot.cn/v1` (OpenAI-compatible).

### Agent Swarm Design

The Harvis backend runs a lightweight swarm orchestrator with these named agents, each calling OpenClaw with specific tool allowlists:

| Agent | Model | Allowed Tools | Role |
|-------|-------|---------------|------|
| `planner` | Kimi K2.5 | none | Breaks user request into steps, assigns agents |
| `coder` | Ollama (qwen2.5-coder) via OpenClaw | `repo_read`, `repo_write`, `run_tests`, `run_code` | Writes/fixes code |
| `researcher` | Kimi K2.5 or Ollama via OpenClaw | `local_rag`, `read_docs` | Searches local knowledge only, no web |
| `writer` | Kimi K2.5 | `create_docx`, `create_pdf` | Formats final answer / generates documents |

Flow:
1. User message hits `/api/chat` (or `/api/swarm` for swarm mode)
2. Harvis backend calls Kimi K2.5 as `planner` → gets JSON step list
3. Each step dispatched to the right agent via OpenClaw WebSocket
4. Results aggregated, `writer` agent composes final response
5. Final answer sent back to user through Harvis UI; TTS reads it

### Docker Compose Addition

OpenClaw runs on a **separate internal-only network** (`openclaw-internal`). The Harvis backend is dual-homed (on both `ollama-n8n-network` and `openclaw-internal`).

```yaml
# Add to docker-compose.yaml

networks:
  openclaw-internal:
    driver: bridge
    internal: true   # NO outbound internet

services:
  openclaw:
    image: openclaw:local          # built from openclaw/openclaw/
    container_name: harvis-openclaw
    restart: unless-stopped
    # NO ports: section — not reachable from host
    environment:
      HOME: /home/node
      NODE_ENV: production
      OPENCLAW_GATEWAY_TOKEN: "${OPENCLAW_GATEWAY_TOKEN}"
      OLLAMA_API_KEY: "ollama-local"
      DATABASE_URL: "postgresql://pguser:pgpassword@pgsql:5432/database"
      OPENCLAW_STATE_DIR: /data/openclaw
    volumes:
      - openclaw-data:/data/openclaw
      - ./openclaw/openclaw.json:/data/openclaw/openclaw.json:ro
    depends_on:
      pgsql:
        condition: service_healthy
      ollama:
        condition: service_started
    networks:
      - openclaw-internal   # internal only
      - ollama-n8n-network  # shared for ollama + pgsql access
    command: node openclaw.mjs gateway --bind lan --allow-unconfigured
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18789/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
```

Also add `openclaw-internal` to the `backend` service's networks list so the Python orchestrator can reach `ws://openclaw:18789`.

Add volume: `openclaw-data: {}`

### OpenClaw Config (`openclaw/openclaw.json`)

```json5
{
  gateway: {
    bind: "lan",
    port: 18789,
    auth: { mode: "token" },
  },
  session: {
    scope: "per-sender",
    reset: { mode: "never" },
    maintenance: { pruneAfter: "90d", maxEntries: 2000 },
  },
  models: {
    mode: "replace",   // local only, no cloud provider fallback
    providers: {
      ollama: {
        baseUrl: "http://ollama:11434",
        apiKey: "ollama-local",
      },
    },
  },
  agents: {
    defaults: {
      model: { primary: "ollama/qwen2.5-coder:32b" },
    },
  },
  channels: {},   // no messaging channels — Harvis is the only client
}
```

### K8s Deployment

OpenClaw goes in the `openclaw` namespace (separate from `harvis` namespace). NetworkPolicy blocks all egress except to:
- `ollama.harvis.svc.cluster.local:11434`
- `pgsql.harvis.svc.cluster.local:5432`

Ingress allowed only from pods with label `app: backend` in the `harvis` namespace.

Manifests live in `k8s-manifests/services/openclaw.yaml`. Follow the template in `openclaw/SETUP.md`.

### VectorDB Sync

The existing `pgvector/pgvector:pg15` database already has vector extension. OpenClaw sessions and embeddings should use the **same database** but **separate tables** to avoid conflicts:

```sql
-- Run once in the existing database
CREATE TABLE IF NOT EXISTS openclaw_sessions (
    id          SERIAL PRIMARY KEY,
    session_key TEXT UNIQUE NOT NULL,
    agent_id    TEXT NOT NULL,
    display_name TEXT,
    model_id    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_usd    NUMERIC(12, 8) DEFAULT 0,
    metadata    JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS openclaw_messages (
    id          SERIAL PRIMARY KEY,
    session_key TEXT NOT NULL REFERENCES openclaw_sessions(session_key),
    msg_id      TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     JSONB NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oc_sessions_agent ON openclaw_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_oc_messages_session ON openclaw_messages(session_key, created_at);
```

### Building OpenClaw Image

```bash
# Build context is openclaw/ (not openclaw/openclaw/) so skills/ can be baked in
docker build -t openclaw:local -f openclaw/openclaw/Dockerfile openclaw/

# Verify it starts
docker run --rm \
  -e HOME=/home/node \
  -e OPENCLAW_GATEWAY_TOKEN=test-token \
  -p 18789:18789 \
  openclaw:local \
  node openclaw.mjs gateway --bind lan --allow-unconfigured

curl http://localhost:18789/health
```

### Harvis Backend Orchestrator Endpoint

The Python backend will expose `/api/swarm` that:
1. Validates JWT auth (same as all other endpoints)
2. Runs the planner → worker → writer swarm loop
3. Streams the final answer back to the client

The swarm endpoint should be added to `python_back_end/main.py` and proxied through Nginx at `/api/swarm`.

### Environment Variables to Add

| Variable | Where | Purpose |
|----------|-------|---------|
| `OPENCLAW_GATEWAY_TOKEN` | `.env` + backend env | Auth token for OpenClaw WebSocket |
| `OPENCLAW_URL` | backend env | `ws://openclaw:18789` |
| `MOONSHOT_API_KEY` | backend env | Kimi K2.5 API key |
| `MOONSHOT_BASE_URL` | backend env | `https://api.moonshot.cn/v1` |

### Web Research Button

The frontend has a single **Web Research** toggle button. First click shows a one-time acknowledgment dialog, then enables live web research through OpenClaw. The button turns amber when active.

**How it works:**
1. User clicks "Chat Mode" → warning dialog (once per session)
2. User acknowledges → button becomes "Web Research" (amber/Globe icon)
3. Research requests route to `/api/research-chat` with `live_web: true`
4. Backend dispatches through OpenClaw workspace with `X-Live-Web: true` headers
5. OpenClaw uses `exec` + `curl` to search/fetch through backend proxy endpoints
6. Click again → back to "Chat Mode"

**Backend proxy behavior with `X-Live-Web: true`:**
- Domain allowlists bypassed (any public domain allowed)
- Rate limits relaxed (30 searches, 60 fetches per 60s)
- HTTP URLs allowed for web-fetch (not just HTTPS)
- Private-IP / localhost blocking always enforced (SSRF protection)
- All requests audited to `openclaw_tool_audit` table

**Key fix for OpenClaw web access:** `bashForegroundMs` in `openclaw.json` must be >= 30000 (30s). The previous 2000ms timeout killed curl commands before they could complete.

### What NOT to Do

- **Never** add a `ports:` section to the openclaw service — it must not be reachable from host
- **Never** put `MOONSHOT_API_KEY` or any cloud API key inside OpenClaw's config — those stay in the Harvis orchestrator layer
- **Never** let OpenClaw's egress rules include anything other than ollama and pgsql

---

## Kubernetes DNS Issues

**CRITICAL**: The Kubernetes cluster is in a network environment (csusb.edu) that blocks outbound UDP port 53 traffic from pods, preventing DNS resolution of external domains. This affects model pulling, registry access, and any external API calls.

**Solution**: See `K8S_DNS_WORKAROUND.md` for detailed instructions on adding DNS entries to CoreDNS.

**Quick Fix for Model Pulling:**
```bash
# Use the helper script
./scripts/add-dns-entry.sh registry.ollama.ai

# Or manually add entries - see K8S_DNS_WORKAROUND.md
```

**Current DNS Entries** (as of 2026-01-20):
- `104.21.75.227 registry.ollama.ai`
- `172.67.182.229 registry.ollama.ai`

## Docker Network URLs

**IMPORTANT**: Services communicate within Docker network using these URLs:
- **Backend URL**: `http://backend:8000` (Python FastAPI backend)
- **Frontend URL**: `http://frontend:3000` (Next.js frontend)
- **Ollama URL**: `http://ollama:11434` (Ollama AI models server)
- **Database URL**: `postgresql://pguser:pgpassword@pgsql:5432/database`
- **OpenClaw URL**: `ws://openclaw:18789` (internal only — backend → openclaw, no host exposure)

These are the correct URLs for inter-service communication within the Docker network.

### Architecture: Nginx Proxy + Backend Authentication

**IMPORTANT**: The application uses Nginx as a reverse proxy to handle all frontend-backend communication. All authentication logic is handled by the Python backend.

#### ❌ Incorrect (Direct backend calls):
```javascript
// This will fail due to CORS:
fetch("http://localhost:8000/api/auth/login")
```

#### ✅ Correct (Nginx Proxy Pattern):

**Nginx Configuration**: All API calls are proxied to the backend:
```nginx
location /api/ {
    proxy_pass http://backend:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**Frontend Calls**: Use relative paths that Nginx proxies:
```javascript
// Browser calls are proxied by Nginx to backend:
fetch("/api/auth/login", {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password })
})
```

#### Communication Flow:
```
Browser → Nginx Proxy → Backend → Ollama/DB
   ↑         (Proxy)      ↑         ↑
   └──────────────────────┴─────────┴─ Docker Network
```

#### Authentication Architecture:
- **Backend-Only Authentication**: All auth logic in Python FastAPI backend
- **No Frontend API Routes**: Frontend only handles UI and calls backend via Nginx
- **CORS Configuration**: Backend properly configured for Nginx proxy
- **JWT Tokens**: Generated and validated entirely by backend
- **Database Access**: Only backend connects to PostgreSQL

#### **IMPORTANT: Access Pattern**
**✅ Correct Way to Access the Application:**
- Access via Nginx proxy: `http://localhost:9000`
- All API calls use relative paths: `/api/auth/login`, `/api/chat`, etc.
- Nginx handles all proxying and CORS headers

**❌ Incorrect (Will cause CORS errors):**
- Accessing backend directly: `http://localhost:8000` 
- Making direct backend API calls from browser

This pattern eliminates CORS issues and centralizes all logic in the backend.

## Database Safety and Management

**🚨 CRITICAL: Database data protection measures are now in place to prevent accidental data loss.**

### Database Safety Features

#### **Production-Safe Schema Script**
- **Location**: `front_end/jfrontend/db_setup.sql`
- **Safety**: Now uses `CREATE TABLE IF NOT EXISTS` (safe)
- **Previous Danger**: Contained `DROP TABLE CASCADE` (removed)
- **Purpose**: Safe table creation for production deployments

#### **Development Reset Script**
- **Location**: `dev-setup/db_reset_dev_only.sql` 
- **⚠️ DESTRUCTIVE**: Drops all tables and data
- **Use Case**: Development environment database reset only
- **Safety**: Clearly marked as development-only with warnings

### **Backup and Restore System**

#### **Automatic Backup Script**
```bash
./database-backup/backup.sh
```
- Creates timestamped backups: `harvis_backup_20250113_143022.sql`
- Automatic cleanup (keeps 10 most recent)
- Backup verification and size reporting

#### **Safe Restore Script**
```bash
# List available backups
./database-backup/restore.sh

# Restore latest backup  
./database-backup/restore.sh latest

# Restore specific backup
./database-backup/restore.sh harvis_backup_20250113_143022.sql
```
- **Safety backup**: Creates backup before restore
- **Confirmation prompts**: Prevents accidental restores
- **Verification**: Confirms restore completed successfully

### **Database Safety Workflow**

#### **Before Any Database Changes:**
1. **Always backup first**: `./database-backup/backup.sh`
2. **Make changes**: Schema updates, migrations, etc.
3. **If problems occur**: `./database-backup/restore.sh latest`

#### **Development Database Reset:**
```bash
# DEVELOPMENT ONLY - destroys all data
docker exec -i pgsql-db psql -U pguser -d database < dev-setup/db_reset_dev_only.sql

# Recreate tables safely
docker exec -i pgsql-db psql -U pguser -d database < front_end/jfrontend/db_setup.sql
```

#### **Production Database Updates:**
1. **Backup**: `./database-backup/backup.sh`
2. **Test on staging**: Never test on production first
3. **Apply changes**: Use migration scripts, not DROP commands
4. **Verify**: Check data integrity after changes

### **Database Security Considerations**

#### **Access Control**
- Database connection only from backend services
- No direct frontend database access
- Connection pooling with proper timeout settings
- Environment variables for sensitive credentials

#### **Data Protection**
- Password hashing with bcrypt
- JWT token expiration (configurable)
- No sensitive data in logs or error messages
- Database volume persistence with Docker

### **Common Issues Prevention**

#### **Data Loss Prevention**
- ✅ Removed dangerous `DROP TABLE CASCADE` from production scripts
- ✅ Separated development reset from production setup
- ✅ Added backup/restore system with safety measures
- ✅ Clear documentation of destructive vs safe operations

#### **Recovery Procedures**
- Regular automated backups (recommended: daily)
- Quick restore capability with verification
- Safety backups before any restore operation
- Clear documentation of backup/restore workflows

### Reasoning Model Integration

**IMPORTANT**: The application now fully supports reasoning models (DeepSeek R1, QwQ, O1, etc.) with proper separation of thinking process from final answers.

#### How It Works:

1. **Automatic Detection**: Backend detects `<think>...</think>` tags in model responses
2. **Content Separation**: Thinking process extracted from final answer server-side  
3. **Clean UI**: Main chat shows only final answers, AI insights shows reasoning
4. **TTS Optimization**: Chatterbox reads only final answers (not thinking process)

#### Backend Implementation:
```python
def separate_thinking_from_final_output(text: str) -> tuple[str, str]:
    """Extract reasoning content and return (reasoning, final_answer)"""
    # Processes <think>...</think> tags
    # Returns clean separation of content
```

#### API Response Format:
```json
{
  "history": [...],
  "audio_path": "/api/audio/...",
  "reasoning": "The thinking process...",     // Only if reasoning detected
  "final_answer": "The clean answer..."      // Clean answer for display/TTS
}
```

#### Frontend Handling:
- **Chat Bubble**: Displays only `final_answer` 
- **TTS/Chatterbox**: Reads only `final_answer`
- **AI Insights**: Shows `reasoning` with purple CPU icon
- **Zero Regression**: Non-reasoning models work exactly as before

#### Supported Models:
- Any model using `<think>...</think>` tag format
- DeepSeek R1 series, QwQ-32B, O1/O3 models
- Future: Can extend to support vLLM `reasoning_content` API format

#### Extensibility:
- Easy to modify `separate_thinking_from_final_output()` for other tag formats
- AI insights can be enhanced with reasoning analysis features
- Can add reasoning quality scoring or step-by-step breakdown display

## Documentation Requirements

**IMPORTANT for Claude Code**: Always document all changes and fixes in `front_end/jfrontend/changes.md` with:
- Timestamp of the change
- Problem description
- Root cause analysis  
- Solution applied
- Files modified
- Result/status

This helps track all modifications and provides debugging context for future development.

## Fixes and Troubleshooting

**IMPORTANT**: Before implementing solutions for common issues, check the `fixes/` directory for documented solutions:
- `fixes/` contains detailed documentation of resolved issues with complete step-by-step solutions
- Each fix document includes problem symptoms, root cause analysis, failed approaches, and working solutions
- When encountering authentication errors, API failures, or integration issues, search `fixes/` first
- Always reference existing fix documentation in new changes.md entries

Common fix categories:
- Authentication issues (n8n, database, JWT)
- API integration problems  
- Docker networking and configuration
- Frontend-backend communication errors
- Voice/Audio processing authentication issues

### Voice Processing Authentication Fix

**CRITICAL**: When voice/audio processing fails with 401 Unauthorized errors:

**Problem**: The audio processing functionality in `UnifiedChatInterface.tsx` calls `/api/mic-chat` without including the Authorization header, causing authentication failures.

**Location**: `/home/guruai/compose/aidev/front_end/jfrontend/components/UnifiedChatInterface.tsx`

**Fix**: In the `sendAudioToBackend` function (around line 764-780), add authentication headers:

```typescript
// Get auth token for API request
const token = localStorage.getItem('token')
console.log('🔥🔥🔥 UnifiedChatInterface: Token exists:', !!token, token ? `${token.substring(0, 20)}...` : 'null')

const headers: Record<string, string> = {}
if (token) {
  headers['Authorization'] = `Bearer ${token}`
} else {
  console.error('UnifiedChatInterface: No auth token found in localStorage')
}

const response = await fetch("/api/mic-chat", {
  method: "POST",
  headers,  // <- Add this line
  body: formData,
  credentials: 'include',
})
```

**Root Cause**: The voice processing was implemented directly in `UnifiedChatInterface.tsx`, not in the separate `VoiceControls.tsx` component, so authentication fixes must be applied to the correct file.

**Verification**: Look for the console log `🔥🔥🔥 UnifiedChatInterface: Token exists: true` to confirm the fix is active. 


## Key Commands

### Frontend Development (jfrontend)
- `cd front_end/jfrontend` - Navigate to the main frontend directory
- `npm run dev` - Start development server (runs on port 3000)
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint
- `npm run type-check` - Run TypeScript type checking

### Docker Operations
- `docker-compose up --build -d` - Build and run the entire stack
- `docker-compose down` - Stop all services
- `docker-compose logs -f [service]` - View logs for specific service

### Database Operations
- Database setup script: `front_end/jfrontend/db_setup.sql`
- PostgreSQL runs on port 5432 in container
- Uses environment variables from `.env.local`

## Architecture Overview

### Frontend (Next.js)
- **Location**: `front_end/jfrontend/`
- **Framework**: Next.js 14 with App Router
- **Styling**: Tailwind CSS with Radix UI components
- **State Management**: Zustand for chat state
- **Authentication**: JWT-based with bcrypt password hashing

### Backend Services
- **Python Backend**: `python_back_end/` - Main AI processing, voice controls, browser automation
- **REST API**: `rest_api/` - Additional API services
- **Database**: PostgreSQL with connection pooling

### Key Frontend Directories
- `app/` - Next.js app router pages and API routes
- `components/` - Reusable React components including UI components
- `lib/` - Utility functions, database connection, and authentication services
- `stores/` - Zustand state management
- `rag_context/` - RAG context documentation

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    avatar VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Authentication Architecture

### Recommended Approach: Backend-Centric Authentication (Most Secure)

**Current Status**: Authentication is currently handled by the Next.js frontend API routes. For maximum security, consider migrating to Python backend authentication.

### Option 1: Python Backend Authentication (RECOMMENDED - Most Secure)
- **Location**: Add auth endpoints to `python_back_end/main.py`
- **Database**: Direct PostgreSQL connection from Python using `psycopg2` or `asyncpg`
- **Security Benefits**:
  - Server-side password hashing with bcrypt
  - JWT token generation and validation on backend
  - Database queries isolated from frontend
  - Protection against client-side manipulation
  - Centralized auth logic for all AI services

### Option 2: Frontend API Routes (Current Implementation)
- **Location**: `front_end/jfrontend/app/api/auth/`
- **Database**: Uses `pg` library with connection pooling
- **Security**: Good but less secure than backend auth
- **Current Flow**:
  1. User signup/login through `/api/auth/login` or `/api/auth/signup`
  2. Passwords hashed with bcrypt
  3. JWT tokens generated with 1-hour expiration
  4. Token verification handled by `/api/me` endpoint

### Migration Path (Frontend → Backend Auth)
1. Create Python auth endpoints in `python_back_end/main.py`:
   - `POST /api/auth/login`
   - `POST /api/auth/signup`
   - `GET /api/auth/me`
2. Update frontend to call Python backend auth endpoints
3. Move database schema setup to Python backend
4. Update environment variables for backend database connection

## AI Integration

### Core AI Components
- **Voice Processing**: Whisper STT, Chatterbox TTS
- **LLM Integration**: Ollama for local model hosting
- **Browser Automation**: Selenium WebDriver
- **Screen Analysis**: Blip AI for visual understanding
- **Web Search**: LangChain-based web search with DuckDuckGo integration

### Key AI Features
- **Vibe Coding**: AI-powered development environment at `python_back_end/ollama_cli/vibe_agent.py`
- **Real-time Screen Analysis**: Context-aware assistance
- **Voice-First Interaction**: Natural language commands
- **Browser Automation**: Web navigation and interaction
- **Research & Web Search**: Comprehensive web search and research capabilities

### Web Search & Research API Endpoints

#### `/api/web-search` - Basic Web Search
**POST** - Perform web search using LangChain search agents

**Request Body:**
```json
{
  "query": "search query",
  "max_results": 5,
  "extract_content": false
}
```

**Response:**
```json
{
  "query": "search query",
  "search_results": [
    {
      "title": "Result Title",
      "url": "https://example.com",
      "snippet": "Result snippet",
      "source": "DuckDuckGo"
    }
  ],
  "extracted_content": []
}
```

#### `/api/research-chat` - Enhanced Research Chat
**POST** - Enhanced research with comprehensive web search and analysis

**Request Body:**
```json
{
  "message": "research question",
  "history": [],
  "model": "mistral",
  "enableWebSearch": true
}
```

#### `/api/fact-check` - Fact Checking
**POST** - Fact-check claims using web search

**Request Body:**
```json
{
  "claim": "claim to verify",
  "model": "mistral"
}
```

#### `/api/comparative-research` - Comparative Analysis
**POST** - Compare multiple topics using web research

**Request Body:**
```json
{
  "topics": ["topic1", "topic2"],
  "model": "mistral"
}
```

### Web Search Implementation Details

#### Search Agents
- **Location**: `python_back_end/research/`
- **Primary**: DuckDuckGo search via LangChain
- **Fallback**: Tavily API (requires `TAVILY_API_KEY`)
- **Content Extraction**: newspaper3k for full article content

#### Dependencies
Required packages in `requirements.txt`:
```
langchain
langchain-community
duckduckgo-search
beautifulsoup4
newspaper3k
tavily-python
```

### Troubleshooting Web Search

#### Common Issues with 0 Results

1. **Rate Limiting**: DuckDuckGo may throttle requests
   - **Solution**: Add delays between requests
   - **Check**: Look for rate limit errors in logs

2. **Network Issues in Docker**: Container connectivity problems
   - **Solution**: Verify Docker network configuration
   - **Check**: Test network connectivity from container

3. **User-Agent Blocking**: Search engines blocking requests
   - **Solution**: Set proper User-Agent (automatically configured)
   - **Environment**: `USER_AGENT` is set automatically if missing

4. **API Changes**: DuckDuckGo search library changes
   - **Warning**: Library suggests using `ddgs` instead of `duckduckgo_search`
   - **Solution**: Consider updating to newer library version

#### Debugging Steps

1. **Enable Debug Logging**: Set logging level to DEBUG
2. **Check Raw Results**: Verify DuckDuckGo returns data
3. **Network Tests**: Test connectivity from container
4. **Rate Limit Checks**: Monitor for rate limiting messages

#### Log Analysis
The web search endpoint provides detailed logging:
- Request parameters and query
- DuckDuckGo response count
- Formatted result details
- Error messages with full stack traces

Example log output:
```
INFO:main:Web search request: query='python', max_results=5, extract_content=False
INFO:research.web_search:Starting DuckDuckGo search for query: 'python' with max_results: 5
INFO:research.web_search:DuckDuckGo returned 5 raw results
INFO:main:Search completed: found 5 results
```

## Development Workflow

### Frontend Development
1. Navigate to `front_end/jfrontend/`
2. Install dependencies: `npm install`
3. Set up environment variables in `.env.local`
4. Run development server: `npm run dev`
5. Always run `npm run type-check` before committing

### Authentication Development

#### Current Frontend Implementation
- AuthService: `lib/auth/AuthService.ts` - Client-side auth functions
- UserProvider: `lib/auth/UserProvider.tsx` - Auth context provider
- Database connection: `lib/db.ts` - PostgreSQL connection pool

#### For Backend Authentication Migration
- Add auth dependencies to `python_back_end/requirements.txt`:
  ```
  python-jose[cryptography]
  passlib[bcrypt]
  python-multipart
  asyncpg
  ```
- Create auth middleware for protecting AI endpoints
- Update frontend AuthService to call backend endpoints
- Implement JWT token validation in Python backend

### Component Development
- UI components use Radix UI primitives
- Styling with Tailwind CSS
- Follow existing component patterns in `components/ui/`

## Docker Configuration

### Services
- **frontend**: Next.js app (port 3001 → 3000)
- **pgsql**: PostgreSQL database with health checks
- **Networks**: Uses external `ollama-n8n-network`

### Environment Variables
Required in `.env.local`:
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET` - JWT signing secret
- `BACKEND_URL` - Backend service URL (default: http://backend:8000)

For backend authentication, also add to Python backend environment:
- `DATABASE_URL` - PostgreSQL connection for Python backend
- `JWT_SECRET` - Same secret for token validation consistency
- `JWT_ALGORITHM` - JWT algorithm (default: HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Token expiration (default: 60)

## Common Issues

### Database Connection
- Ensure PostgreSQL service is healthy before frontend starts
- Check `DATABASE_URL` environment variable
- Verify network connectivity between services

### Authentication
- JWT tokens expire after 1 hour (configurable)
- Password hashing uses bcrypt
- Check JWT_SECRET is properly set and consistent between frontend/backend
- For backend auth: Ensure Python backend can connect to PostgreSQL
- Token validation should be consistent across all services

### Type Checking
- Run `npm run type-check` regularly
- TypeScript errors are ignored in builds (not recommended for production)

## Git Branch Strategy
- Main branch: `main`
- Feature branches: Create from `main`
- Use conventional commits: `feat:`, `fix:`, `docs:`, etc.
- NEVER commit until the user has reviewed the changes — stage or
  `git commit --dry-run` if useful, but the user commits, or explicitly says to.

## Testing
- No specific test framework configured
- Manual testing recommended for auth flows
- Test database operations with PostgreSQL running

## Security Considerations

### Current Security (Frontend Auth)
- Passwords are hashed with bcrypt
- JWT tokens for authentication
- Environment variables for sensitive data
- Database connection uses connection pooling
- Frontend runs in standalone mode for Docker deployment

### Enhanced Security (Backend Auth - Recommended)
- **Authentication Logic**: Move all auth logic to Python backend
- **Database Access**: Direct backend-to-database connection (no frontend DB access)
- **Token Validation**: Centralized JWT validation in Python backend
- **API Protection**: Protect all AI endpoints with auth middleware
- **CORS Configuration**: Properly configure CORS for frontend-backend communication
- **Input Validation**: Server-side validation of all auth inputs
- **Rate Limiting**: Implement rate limiting on auth endpoints
- **Audit Logging**: Log all authentication attempts and API access

### Security Benefits of Backend Auth
1. **Reduced Attack Surface**: Auth logic not exposed to client-side
2. **Centralized Security**: All AI services protected by same auth system
3. **Database Security**: Direct backend-to-database connection
4. **Token Security**: JWT secrets never exposed to frontend
5. **Consistent Validation**: Same auth validation across all endpoints

## CLAUDE AND HARVIS SKILLS

- both harvis and claudes skills will be in the skills directory from the root of the project its where u guys will see how i want u guys to do things would be great for what we need in this task and these codes in this project
- Mainly a bunch of skills.md to tell u how to do things and how i want them done as well as workflows 
- One possible consideration is vectorizing them so there would not need to read where i just prompt and the vectordb pulls the right skillmd to give to the llm would also be nice for now we will integrate it like this 
