# Plan: newjfrontend as OpenClaw Gateway UI

## Goal

Replace OpenClaw's built-in Lit-based gateway UI (`openclaw/ui/`) with the Harvis Next.js frontend (`front_end/newjfrontend/`). newjfrontend becomes the primary interface for interacting with OpenClaw.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     newjfrontend (Next.js)                      │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │  Chat    │ │ Sessions │ │  Agents  │ │Workspace │          │
│  │  View    │ │  View    │ │  View    │ │   View   │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│       │             │             │             │               │
│  ┌────┴─────────────┴─────────────┴─────────────┴────┐         │
│  │           OpenClawClient (TypeScript)              │         │
│  │  - JSON-RPC over WebSocket                         │         │
│  │  - Event handling (chat, agent)                     │         │
│  │  - Session/agent CRUD via REST                      │         │
│  └────────────────────────┬───────────────────────────┘         │
│                            │                                    │
└────────────────────────────┼────────────────────────────────────┘
                             │ ws://localhost:9000/ws/openclaw
                             │
┌────────────────────────────┼────────────────────────────────────┐
│                   Harvis Backend (FastAPI)                       │
│                                                                 │
│  ┌─────────────────────────────────────────────────────┐       │
│  │         OpenClawGatewayProxy (new module)            │       │
│  │                                                      │       │
│  │  - Maintains SINGLE connection to OpenClaw gateway   │       │
│  │  - Bridges JSON-RPC frames: frontend ↔ OpenClaw      │       │
│  │  - Handles device identity generation                 │       │
│  │  - Manages reconnection, heartbeat, ping/pong        │       │
│  │  - Per-user session routing (sessionKey)             │       │
│  └─────────────┬────────────────────────────────────────┘       │
│                │                                                 │
│  ┌─────────────┴──────────────┐                                 │
│  │  Existing openclaw_client  │                                 │
│  │  (workspace streaming)     │                                 │
│  └────────────────────────────┘                                 │
│                                                                 │
└────────────────────┬───────────────────────────────────────────┘
                     │ ws://openclaw:18789 (Docker)
                     │ ws://harvis-ai-openclaw:18789 (K8s)
                     │
              ┌──────┴──────┐
              │ OpenClaw    │
              │ Gateway     │
              │ (TypeScript)│
              │             │
              │ 80+ RPC     │
              │ methods     │
              └─────────────┘
```

## Key Design Decisions

### 1. Backend as WebSocket Proxy

The Harvis backend acts as a **WebSocket proxy** between newjfrontend and the OpenClaw gateway. This means:

- **Frontend** connects to `ws://localhost:9000/ws/openclaw` (proxied by Nginx to backend)
- **Backend** maintains a persistent connection to OpenClaw gateway at `ws://openclaw:18789`
- **Bidirectional frame relay**: All JSON-RPC messages from frontend are forwarded to OpenClaw, and all events/responses from OpenClaw are forwarded to frontend
- **Backend handles device identity**: Ed25519 key pair is generated in the backend (reusing the pattern from `openclaw_client.py`), eliminating Ed25519 in the browser

**Why not direct WebSocket?**
- Ed25519 in browser requires `@noble/ed25519` dependency + complex crypto
- Backend already has proven device identity code in `openclaw_client.py`
- Single OpenClaw connection managed centrally (no per-user connections)
- Easier to add auth, rate limiting, message filtering later

### 2. Protocol: Transparent JSON-RPC Relay

The proxy is **protocol-transparent** — it relays raw JSON-RPC frames between frontend and OpenClaw. This means:

- Frontend speaks the exact same JSON-RPC protocol as OpenClaw's built-in UI
- No need to reimplement RPC methods in the backend
- All 80+ OpenClaw RPC methods work automatically
- Event types (`chat`, `agent`, `presence`, etc.) flow through unchanged

### 3. Tab Structure in newjfrontend

| Tab | OpenClaw RPC Methods | Implementation |
|-----|---------------------|----------------|
| **Chat** | `chat.send`, `chat.history`, `chat.abort`, `chat.inject` | New chat view with tool stream sidebar |
| **Sessions** | `sessions.list`, `sessions.patch`, `sessions.delete`, `sessions.reset`, `sessions.compact`, `sessions.usage` | Session list + detail panel |
| **Agents** | `agents.list`, `agents.files.list`, `agents.identity`, `agents.wait`, `tools.catalog`, `skills.status` | Agent list + files/tools/skills panels |
| **Workspaces** | Existing Harvis workspace flow (backend proxy) | Keep existing workspace integration |

### 4. State Management

Zustand stores needed:
- `openclawChatStore` — current session, messages, chat stream, tool stream
- `openclawSessionsStore` — session list, active session
- `openclawAgentsStore` — agent list, selected agent, agent files/tools
- `openclawConnectionStore` — connection state, auth status, reconnection

## Implementation Phases

### Phase 1: Backend WebSocket Proxy

**Files to create:**
- `python_back_end/openclaw/gateway_proxy.py` — WebSocket proxy server
- `python_back_end/openclaw/__init__.py` — Package init

**Files to modify:**
- `python_back_end/main.py` — Register gateway_proxy router
- `python_back_end/nginx.conf` — Add WebSocket proxy route for `/ws/openclaw`

### Phase 2: Frontend OpenClaw Client

**Files to create:**
- `front_end/newjfrontend/lib/openclaw/client.ts` — JSON-RPC WebSocket client
- `front_end/newjfrontend/lib/openclaw/types.ts` — All OpenClaw API types
- `front_end/newjfrontend/stores/openclawChatStore.ts`
- `front_end/newjfrontend/stores/openclawSessionsStore.ts`
- `front_end/newjfrontend/stores/openclawAgentsStore.ts`
- `front_end/newjfrontend/stores/openclawConnectionStore.ts`
- `front_end/newjfrontend/hooks/useOpenClawConnection.ts`
- `front_end/newjfrontend/hooks/useOpenClawChat.ts`

### Phase 3: Chat View

**Files to create:**
- `front_end/newjfrontend/components/openclaw/ChatView.tsx`
- `front_end/newjfrontend/components/openclaw/ChatMessageList.tsx`
- `front_end/newjfrontend/components/openclaw/ChatInput.tsx`
- `front_end/newjfrontend/components/openclaw/ToolStreamSidebar.tsx`
- `front_end/newjfrontend/components/openclaw/MessageGroup.tsx`

### Phase 4: Sessions View

**Files to create:**
- `front_end/newjfrontend/components/openclaw/SessionsView.tsx`
- `front_end/newjfrontend/components/openclaw/SessionList.tsx`
- `front_end/newjfrontend/components/openclaw/SessionDetail.tsx`

### Phase 5: Agents View

**Files to create:**
- `front_end/newjfrontend/components/openclaw/AgentsView.tsx`
- `front_end/newjfrontend/components/openclaw/AgentList.tsx`
- `front_end/newjfrontend/components/openclaw/AgentFiles.tsx`
- `front_end/newjfrontend/components/openclaw/AgentTools.tsx`
- `front_end/newjfrontend/components/openclaw/AgentSkills.tsx`

### Phase 6: Navigation Integration

**Files to modify:**
- `front_end/newjfrontend/app/page.tsx` — Main layout with new tab navigation
- `front_end/newjfrontend/components/chat-sidebar.tsx` — Add OpenClaw tabs

## Security

1. Backend enforces JWT auth on WebSocket endpoint
2. Single OpenClaw connection (not per-user)
3. `OPENCLAW_GATEWAY_TOKEN` never exposed to frontend
4. Ed25519 device identity generated server-side
