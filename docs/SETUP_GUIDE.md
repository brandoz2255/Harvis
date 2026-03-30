# MCP Plugin System with OpenClaw Integration - Setup Guide

## Overview

This implementation adds MCP (Model Context Protocol) plugin support to Harvis AI, with OpenClaw as the first plugin for browser automation and computer control.

## Architecture

```
Harvis Frontend (Next.js)
    ↓
Harvis Backend (FastAPI)
    ├── MCP Registry (plugin management)
    ├── OpenClaw Bridge (VM orchestration)
    └── Event Stream (WebSocket)
    ↓
OpenClaw VM (VirtualBox)
    └── OpenClaw Agent (automation)
```

## What Was Built

### Backend Components

1. **Core Schema** (`plugins/core/`)
   - `events.py` - Event protocol with 15+ event types
   - `job_schema.py` - Job/task models and policy profiles
   - `models.py` - Database models and SQL schema
   - `migration.py` - Database migration script

2. **MCP Registry** (`plugins/mcp/`)
   - `registry.py` - MCP server and tool management
   - `routes.py` - REST API endpoints for MCP

3. **OpenClaw Bridge** (`plugins/openclaw/`)
   - `bridge.py` - WebSocket bridge for VM communication
   - `routes.py` - REST API endpoints for OpenClaw

### Frontend Components

1. **Store** (`stores/openclawStore.ts`)
   - Zustand store for state management
   - Instance, task, and event tracking

2. **Components** (`components/`)
   - `openclaw/OpenClawWorkspace.tsx` - Main workspace view
   - `openclaw/TaskStarter.tsx` - Task creation dialog
   - `workspace/WorkspaceLayout.tsx` - Layout switcher
   - `mcp/MCPPluginManager.tsx` - Plugin registry UI

3. **Hooks** (`hooks/`)
   - `useOpenClawWebSocket.ts` - Real-time event streaming
   - `useOpenClawAPI.ts` - API methods

## Setup Instructions

### 1. Database Migration

Run the migration to add the necessary tables:

```bash
# Copy the migration SQL
cd /home/dulc3/Documents/github/harvis/aidev/python_back_end
python -c "from plugins.core.migration import MIGRATION_SQL; print(MIGRATION_SQL)" > migration.sql

# Run against your PostgreSQL database
docker exec -i pgsql-db psql -U pguser -d database < migration.sql
```

### 2. Backend Integration

Add the plugin routes to your FastAPI main.py:

```python
# In python_back_end/main.py
from plugins.openclaw.routes import router as openclaw_router
from plugins.mcp.routes import router as mcp_router
from plugins.openclaw.bridge import bridge

# Add startup/shutdown events
@app.on_event("startup")
async def startup_event():
    await bridge.start()

@app.on_event("shutdown")
async def shutdown_event():
    await bridge.stop()

# Include routers
app.include_router(openclaw_router)
app.include_router(mcp_router)
```

### 3. Frontend Integration

Install required dependencies:

```bash
cd /home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend
npm install zustand immer
```

Update your main page to use the workspace layout:

```tsx
// In app/page.tsx
import { WorkspaceLayout } from '@/components/workspace/WorkspaceLayout'
import { OpenClawWorkspace } from '@/components/openclaw/OpenClawWorkspace'
import { TaskStarter } from '@/components/openclaw/TaskStarter'

// Add TaskStarter to your chat input area
// Wrap your layout with WorkspaceLayout
```

### 4. VM Setup (OpenClaw)

1. **Create VirtualBox VM**:
   - OS: Ubuntu 22.04 LTS
   - RAM: 4GB minimum
   - Disk: 20GB
   - Network: NAT + Host-only adapter

2. **Install OpenClaw**:
   ```bash
   # Inside VM
   git clone https://github.com/opencrawl/openclaw
   cd openclaw
   npm install
   npm run build
   ```

3. **Configure Bridge Connection**:
   Create `/opt/openclaw-bridge/config.json`:
   ```json
   {
     "harvis_bridge_url": "ws://192.168.56.1:8000/ws/openclaw/vm/your-instance-id",
     "bridge_token": "your-bridge-token",
     "auto_connect": true
   }
   ```

4. **Start Bridge Service**:
   ```bash
   npm run bridge
   ```

## API Endpoints

### OpenClaw

- `POST /api/openclaw/instances` - Create VM instance
- `GET /api/openclaw/instances` - List instances
- `GET /api/openclaw/instances/{id}/bridge-config` - Get connection config
- `POST /api/openclaw/tasks` - Create task
- `GET /api/openclaw/tasks/{id}` - Get task status
- `POST /api/openclaw/tasks/{id}/cancel` - Cancel task
- `POST /api/openclaw/tasks/{id}/approve` - Approve action
- `WS /ws/openclaw/vm/{id}` - VM connection endpoint
- `WS /ws/openclaw/tasks/{id}` - Task event stream

### MCP

- `POST /api/mcp/servers` - Register MCP server
- `GET /api/mcp/servers` - List servers
- `GET /api/mcp/servers/{id}/tools` - List tools
- `POST /api/mcp/servers/{id}/tools/{tool}/execute` - Execute tool

## Usage

### Starting a Task

1. Click the "OpenClaw" button in the chat interface
2. Enter your task description
3. Select a VM instance
4. Choose a security policy
5. Click "Start Task"

The interface will switch to workspace mode showing:
- Task progress checklist
- Live screenshot preview
- Event logs
- Generated artifacts

### Security Policies

- **Default**: Approval for destructive actions
- **Strict**: All actions require approval
- **Unattended**: Minimal approvals for trusted tasks

### Approval Gates

When the automation encounters a sensitive action:
1. Task pauses
2. Approval request appears in UI
3. User reviews action details
4. User approves or denies
5. Task continues or stops

## Next Steps

1. **Testing**: Test the WebSocket connections between frontend, backend, and VM
2. **OpenClaw Agent**: Implement the agent bridge that runs inside the VM
3. **Screenshots**: Set up screenshot storage (filesystem -> S3 for production)
4. **Tool Integration**: Connect MCP tools to the LLM tool calling system
5. **VM Automation**: Automate VM creation and management

## File Structure

```
python_back_end/
└── plugins/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── events.py          # Event protocol
    │   ├── job_schema.py      # Job models
    │   ├── models.py          # DB models
    │   └── migration.py       # SQL migration
    ├── mcp/
    │   ├── __init__.py
    │   ├── registry.py        # MCP registry
    │   └── routes.py          # MCP API
    └── openclaw/
        ├── __init__.py
        ├── bridge.py          # VM bridge
        └── routes.py          # OpenClaw API

front_end/newjfrontend/
├── components/
│   ├── openclaw/
│   │   ├── OpenClawWorkspace.tsx
│   │   └── TaskStarter.tsx
│   ├── mcp/
│   │   └── MCPPluginManager.tsx
│   └── workspace/
│       └── WorkspaceLayout.tsx
├── hooks/
│   ├── useOpenClawWebSocket.ts
│   └── useOpenClawAPI.ts
└── stores/
    └── openclawStore.ts
```

## Support

For issues or questions:
1. Check the event logs in the workspace UI
2. Review backend logs for WebSocket connections
3. Verify VM bridge is connected (`status: online`)
4. Test API endpoints with curl or Postman
