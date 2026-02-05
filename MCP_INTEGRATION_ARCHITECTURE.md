# Harvis Codebase Architecture Summary

**Analysis Date:** 2026-02-03

## Overview

Harvis is an AI voice assistant with a Next.js frontend and Python FastAPI backend. It features voice-first interaction, browser automation, AI-powered coding assistance (vibe coding), web research, and n8n workflow automation.

---

## 1. Current Plugin/Extension System

### Status: **NO FORMAL PLUGIN SYSTEM EXISTS**

There is no dedicated plugin, extension, or tool registry system currently in place. However, the codebase has several extensible patterns that can serve as foundation for MCP integration.

### Existing Extension Points:

**A. Research Agent System** (`python_back_end/research/research_agent.py`)
- Modular agent architecture with pluggable search engines
- Currently supports: DuckDuckGo, Tavily
- Extensible via `WebSearchAgent` and `TavilySearchAgent` classes
- Pattern: Agents inherit base functionality and implement `search_web()`, `search_and_extract()` methods

**B. n8n Workflow Builder** (`python_back_end/n8n/workflow_builder.py`)
- Template-based workflow generation
- Supports dynamic node creation from AI-analyzed requirements
- Node type mapping system for extensibility
- Template registry pattern in `WorkflowBuilder._load_templates()`

**C. Model Manager** (`python_back_end/model_manager.py`)
- Handles multiple TTS and STT models
- GPU/CPU auto-detection and memory management
- Model loading/unloading lifecycle management

**D. AIOrchestrator** (`front_end/doNoteEditThisJustLook/components/AIOrchestrator.tsx`)
- Frontend model capability registry
- Hardcoded model definitions with task mappings
- Hardware detection for model selection
- Pattern could be extended for MCP tool registration

---

## 2. Frontend Architecture

### Technology Stack:
- **Framework:** Next.js 14 with App Router
- **Language:** TypeScript
- **Styling:** Tailwind CSS
- **UI Components:** Radix UI primitives (`components/ui/`)
- **State Management:** Zustand
- **Animation:** Framer Motion
- **Icons:** Lucide React

### Directory Structure:
```
front_end/doNoteEditThisJustLook/
├── app/                          # Next.js app router
│   ├── api/                      # API route handlers (proxies to backend)
│   ├── login/                    # Auth pages
│   ├── signup/
│   ├── settings/
│   ├── profile/
│   └── page.tsx                  # Main dashboard
├── components/                   # React components
│   ├── ui/                       # Base UI components (Radix-based)
│   ├── UnifiedChatInterface.tsx  # Main chat UI
│   ├── AIOrchestrator.tsx        # Model selection logic
│   ├── ChatHistory.tsx           # Session sidebar
│   ├── CompactScreenShare.tsx    # Screen sharing widget
│   ├── VoiceControls.tsx         # Voice input handling
│   └── Vibe*.tsx                 # Vibe coding components
├── stores/                       # Zustand state stores
│   ├── chatStore.ts              # Simple message store
│   ├── chatHistoryStore.ts       # Session management
│   └── insightsStore.ts          # AI insights display
├── lib/                          # Utilities
│   ├── auth/                     # Authentication
│   └── db.ts                     # Database connection
└── hooks/                        # Custom React hooks
    └── useAIInsights.ts
```

### Key Files for MCP Integration:

**`components/UnifiedChatInterface.tsx`**
- Main chat interface component (~1300 lines)
- Handles: text input, voice input, model selection, research mode
- State: messages, loading states, audio playback, search results
- Key patterns:
  - Message interface: `{ role, content, timestamp, model, inputType, searchResults, searchQuery }`
  - API endpoints: `/api/chat`, `/api/research-chat`, `/api/mic-chat`
  - Streaming response handling via SSE
  - Reasoning model support with `<think>` tag parsing

**`stores/chatHistoryStore.ts`**
- Zustand store for chat session management
- Features: session CRUD, message pagination, circuit breaker pattern
- Key interfaces:
  ```typescript
  interface ChatSession {
    id: string
    user_id: number
    title: string
    created_at: string
    updated_at: string
    message_count: number
    model_used?: string
  }
  
  interface ChatMessage {
    id?: number
    session_id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    reasoning?: string  // For reasoning models
    model_used?: string
    input_type: 'text' | 'voice' | 'screen'
    metadata: Record<string, any>
  }
  ```

**`components/AIOrchestrator.tsx`**
- Model capability registry (hardcoded)
- Hardware detection (GPU, CPU, memory)
- Model selection logic based on task type and priority
- Could be extended for MCP tool registry

### API Route Pattern:

All API routes in `app/api/*/route.ts` follow proxy pattern:
```typescript
const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get('authorization')
  const body = await request.json()
  
  const response = await fetch(`${BACKEND_API}/api/endpoint`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": authHeader,
    },
    body: JSON.stringify(body),
  })
  
  const data = await response.json()
  return NextResponse.json(data)
}
```

---

## 3. Backend Architecture

### Technology Stack:
- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL with asyncpg
- **Auth:** JWT tokens (python-jose), bcrypt password hashing
- **AI Models:** Ollama (local), Gemini API (cloud)
- **Voice:** Whisper (STT), Chatterbox (TTS)
- **Vision:** Qwen2VL, LLaVA via Ollama

### Directory Structure:
```
python_back_end/
├── main.py                       # FastAPI app, main endpoints
├── auth_optimized.py             # Authentication utilities
├── model_manager.py              # TTS/STT model lifecycle
├── chat_history_module/          # Chat persistence
│   ├── __init__.py
│   ├── manager.py               # ChatHistoryManager class
│   ├── models.py                # Pydantic models
│   └── storage.py               # Database operations
├── research/                     # Research agent system
│   ├── research_agent.py        # Main research agent
│   ├── web_search.py            # Search implementations
│   └── pipeline/                # Research pipeline stages
├── n8n/                          # Workflow automation
│   ├── workflow_builder.py      # Workflow construction
│   ├── ai_agent.py              # AI workflow generation
│   └── models.py                # Workflow data models
├── vibecoding/                   # AI coding environment
│   ├── core.py                  # Vibe agent initialization
│   ├── sessions.py              # Session management
│   ├── files.py                 # File operations
│   └── containers.py            # Docker container management
├── rag_corpus/                   # RAG document system
│   ├── __init__.py
│   ├── routes.py                # API routes
│   ├── vectordb_adapter.py      # Vector DB interface
│   └── embedding_adapter.py     # Embedding models
└── vison_models/                 # Vision model connectors
    ├── llm_connector.py
    └── qwen.py
```

### Key Files for MCP Integration:

**`main.py`** (~2500+ lines)
- FastAPI application setup
- Core endpoints:
  - `/api/chat` - Main chat with SSE streaming
  - `/api/vision-chat` - Vision model chat
  - `/api/research-chat` - Web research chat
  - `/api/chat-history/*` - Session management
  - `/api/models` - Available models endpoint
- Authentication via JWT tokens
- Database connection pooling
- RAG integration for local document context

**LLM Interaction Flow:**
1. Frontend sends POST to `/api/chat` or `/api/research-chat`
2. Backend validates JWT token via `get_current_user()`
3. Chat request is processed:
   - Attachments processed (if any)
   - Auto-research detection (Perplexity-style)
   - Chat history loaded from database (if session_id provided)
   - RAG context retrieved from local corpus
   - Request sent to Ollama/Gemini
   - Streaming response via SSE with heartbeats
   - TTS generation (if enabled)
   - Response saved to database

**`chat_history_module/manager.py`**
- `ChatHistoryManager` class for session/message CRUD
- Methods: `create_session()`, `add_message()`, `get_session_messages()`
- Integrates with PostgreSQL via asyncpg

**`research/research_agent.py`**
- `ResearchAgent` class for web research
- Supports multiple search engines
- Quality gates for citation validation
- Could be extended as MCP "research" tool

---

## 4. Database Schema

### Tables:

**users**
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

**chat_sessions** (via chat_history_module)
```sql
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0,
    model_used VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE
);
```

**chat_messages**
```sql
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning TEXT,  -- For reasoning models (DeepSeek, QwQ)
    model_used VARCHAR(100),
    input_type VARCHAR(20) DEFAULT 'text' CHECK (input_type IN ('text', 'voice', 'screen')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**user_api_keys** (for external services)
```sql
CREATE TABLE user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL,  -- 'ollama', 'gemini', 'openai'
    api_key_encrypted TEXT NOT NULL,
    api_url VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, provider_name)
);
```

**vibe_sessions** (AI coding)
```sql
CREATE TABLE vibe_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);
```

**vibe_files** (File tree for vibe coding)
```sql
CREATE TABLE vibe_files (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES vibe_files(id),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(10) CHECK (type IN ('file', 'folder')),
    content TEXT,
    language VARCHAR(50),
    path TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Extension Tables Needed for MCP:
- `mcp_servers` - Registered MCP server configurations
- `mcp_tools` - Available tools from MCP servers
- `user_mcp_settings` - User-specific MCP configurations
- `chat_mcp_calls` - Log of MCP tool calls in chats

---

## 5. Workspace/Multi-View UI Patterns

### Current Layout (`app/page.tsx`):

```
┌─────────────────────────────────────────────────────────┐
│                    HARVIS AI Header                      │
├──────────────────────────────────┬──────────────────────┤
│                                  │                      │
│    UnifiedChatInterface          │   Sidebar (w-64)     │
│    (flex-1, main content)        │   - CompactScreenShare│
│                                  │   - MiscDisplay       │
│    • Chat messages               │                      │
│    • Input bar                   │                      │
│    • Model selector              │                      │
│    • Research mode toggle        │                      │
│                                  │                      │
└──────────────────────────────────┴──────────────────────┘
```

### State Management Pattern:
- **Global:** `chatHistoryStore` for sessions/messages
- **Local:** Component state for UI (input, loading, audio)
- **Ref:** `chatInterfaceRef` for imperative message addition

### UI Components Available:
- `Button`, `Card`, `Input`, `Badge`, `Dialog`, `Select`, `Switch` (Radix-based)
- `Aurora` - Animated background
- `GlassPanel` - Glassmorphism container

### Extension Points for MCP:
- Sidebar could host MCP tool panels
- Chat input could have tool selector dropdown
- Message display could show tool call results
- New tabbed interface could show connected MCP servers

---

## 6. LLM Interaction Flow

### Standard Chat Flow:

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend (UnifiedChatInterface.tsx)                        │
│  1. User types/clicks send                                  │
│  2. Optimistic message added to state                       │
│  3. Token retrieved from localStorage                       │
│  4. POST to /api/chat (Next.js API route)                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Next.js API Proxy (app/api/chat/route.ts)                  │
│  1. Auth header extracted                                   │
│  2. Request forwarded to Python backend                     │
│  3. Response proxied back                                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Python Backend (main.py)                                   │
│  1. JWT token validated (get_current_user)                  │
│  2. Request body parsed (ChatRequest)                       │
│  3. Attachments processed (extract_text_from_file)          │
│  4. Auto-research detection (should_auto_research)          │
│  5. Session history loaded (if session_id)                  │
│  6. RAG context retrieved (get_local_rag_context)           │
│  7. System prompt loaded (system_prompt.txt)                │
│  8. Request sent to Ollama/Gemini                           │
│  9. Streaming response processed (SSE)                      │
│  10. TTS generated (if enabled)                             │
│  11. Messages saved to database                             │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Ollama Server                                              │
│  • Local model inference                                    │
│  • Returns streaming tokens                                 │
│  • Supports reasoning models (<think> tags)                 │
└─────────────────────────────────────────────────────────────┘
```

### Research Chat Flow:
```
User Input → ResearchAgent.research_topic()
                ├── _generate_search_queries() - LLM generates search queries
                ├── search_and_extract() - Web search + content extraction
                ├── _prepare_research_context() - Format for LLM
                ├── query_llm() - Generate analysis
                ├── _validate_response_quality() - Quality gates
                └── Return analysis + sources + videos
```

### Vision Chat Flow:
```
Image + Text → /api/vision-chat
                    ├── Images processed (base64 decode, format detection)
                    ├── Images converted to PNG
                    ├── Messages built with image attachments
                    ├── Request sent to Ollama vision model
                    └── Response streamed back
```

---

## 7. Gaps for MCP Integration

### Missing Components:

**1. MCP Server Registry**
- No table/schema for MCP server configurations
- No UI for adding/removing MCP servers
- No backend service for MCP client management

**2. Tool Discovery & Registration**
- No dynamic tool loading mechanism
- No tool capability registry
- AIOrchestrator is hardcoded, not dynamic

**3. Tool Call Interface**
- No standardized tool call format
- Chat interface doesn't support tool call display
- No tool result rendering components

**4. Authentication & Security**
- No OAuth flow for external MCP servers
- No API key management for third-party tools
- No permission system for tool access

**5. Message Format Extension**
- Current Message interface lacks tool call fields
- No support for function/tool calling in chat history

### Recommended MCP Integration Points:

**Backend:**
1. Add `mcp/` module with client management
2. Create MCP server registry in database
3. Extend chat endpoints to support tool calls
4. Add `/api/mcp/servers` and `/api/mcp/tools` endpoints

**Frontend:**
1. Add MCP server management UI (settings panel)
2. Extend chat interface with tool call display
3. Add tool selector to input bar
4. Create tool result rendering components

**Database:**
1. Create `mcp_servers` table
2. Create `mcp_tools` table
3. Extend `chat_messages.metadata` for tool calls

---

## Key File References

| Purpose | File Path |
|---------|-----------|
| Main Chat UI | `front_end/doNoteEditThisJustLook/components/UnifiedChatInterface.tsx` |
| Chat State | `front_end/doNoteEditThisJustLook/stores/chatHistoryStore.ts` |
| Model Selection | `front_end/doNoteEditThisJustLook/components/AIOrchestrator.tsx` |
| Backend API | `python_back_end/main.py` |
| Chat History Module | `python_back_end/chat_history_module/manager.py` |
| Research Agent | `python_back_end/research/research_agent.py` |
| Workflow Builder | `python_back_end/n8n/workflow_builder.py` |
| Database Schema | `front_end/doNoteEditThisJustLook/db_setup.sql` |
| API Proxy Pattern | `front_end/doNoteEditThisJustLook/app/api/chat/route.ts` |
| Main Page | `front_end/doNoteEditThisJustLook/app/page.tsx` |

---

*Architecture analysis: 2026-02-03*
