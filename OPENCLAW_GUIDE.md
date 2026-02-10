# OpenClaw Documentation

## Overview

**OpenClaw** is an AI agent platform that provides LLMs with secure access to systems through a gateway architecture. It allows AI agents to execute commands, browse the web, and interact with various services through a controlled interface.

## Architecture

```
┌─────────────────┐      WebSocket       ┌──────────────────┐
│   AI Client     │◄────────────────────►│  OpenClaw        │
│   (Harvis,      │   (with auth token)  │  Gateway         │
│    Claude, etc) │                      │  Port: 18789     │
└─────────────────┘                      └────────┬─────────┘
                                                  │
                       ┌──────────────────────────┼──────────┐
                       │                          │          │
                       ▼                          ▼          ▼
              ┌──────────────┐          ┌──────────────┐ ┌──────────┐
              │   Browser    │          │   Discord    │ │  Shell   │
              │  Automation  │          │   Bot        │ │  Access  │
              └──────────────┘          └──────────────┘ └──────────┘
```

## Components

### 1. Gateway (Port 18789)
- **Purpose**: Main API/WebSocket server for AI agent communication
- **Web UI**: Control dashboard at `http://192.168.122.100:18789`
- **Protocol**: WebSocket for real-time bidirectional communication
- **Authentication**: Token-based (gateway token required)

### 2. CLI Container
- **Purpose**: Interactive terminal for manual OpenClaw commands
- **Usage**: Run one-off commands like `openclaw agent`, `openclaw message`
- **Note**: Not a daemon - runs interactively then exits

### 3. Control UI
- Built-in web interface for managing:
  - **Chat**: Direct gateway chat session
  - **Overview**: System health and metrics
  - **Channels**: Discord, Telegram integrations
  - **Instances**: Running agent instances
  - **Sessions**: Active chat sessions
  - **Skills**: Available capabilities
  - **Settings**: Configuration and tokens

## Quick Start

### 1. Access the Gateway

Open your browser to: `http://192.168.122.100:18789`

### 2. Authenticate

1. Click **"Control"** in the left sidebar (gear icon)
2. Go to **"Settings"**
3. Paste this Gateway Token:
   ```
   54a80e7033ddbe58d1caefbfff670d04310dea6885c2da3d321454da14f333c0
   ```
4. Save settings

### 3. Test Connection

In the **Chat** tab, you should now see "Connected to gateway" instead of the disconnected error.

## Using OpenClaw

### Via Web UI (Control Dashboard)

Once authenticated, you can:
- **Chat directly** with the AI agent
- **Send commands** to execute on the system
- **Browse the web** through the browser integration
- **Monitor** agent instances and sessions

### Via External AI (Harvis Integration)

Connect your AI assistant to OpenClaw:

```javascript
// Example WebSocket connection
const ws = new WebSocket('ws://192.168.122.100:18789');

ws.onopen = () => {
  // Authenticate with token
  ws.send(JSON.stringify({
    type: 'auth',
    token: '54a80e7033ddbe58d1caefbfff670d04310dea6885c2da3d321454da14f333c0'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle agent responses
};
```

### Via CLI (Interactive)

Attach to the CLI container for manual commands:

```bash
# Attach to CLI container
docker exec -it openclaw-openclaw-cli-1 /bin/bash

# Or run a specific command
docker exec openclaw-openclaw-cli-1 node dist/index.js agent --help
```

## Available Features

### System Access
- Shell command execution
- File system operations
- Process management
- Package installation

### Browser Automation
- Web browsing
- Screenshot capture
- Form interaction
- Page navigation

### Communication Channels
- Discord bot integration
- Telegram bot support
- Webhook endpoints

### AI Capabilities
- Multi-step task execution
- Sub-agent spawning
- Tool use (skills)
- Context management

## Configuration

### Config File Location
```
~/.openclaw/openclaw.json
```

### Key Settings
```json
{
  "gateway": {
    "mode": "local",
    "port": 18789
  },
  "channels": {
    "discord": {
      "enabled": false,
      "token": ""
    }
  },
  "agents": {
    "defaults": {
      "maxConcurrent": 4
    }
  }
}
```

## Security

### Gateway Token
- **Location**: Stored in docker-compose environment
- **Usage**: Required for all WebSocket connections
- **Rotation**: Can be regenerated in Settings

### Isolation
- Runs in Docker container
- Non-root user (node:1000)
- Volume-mounted config (read-only where possible)

### Network
- Default: Binds to 0.0.0.0 (all interfaces)
- In VM: Accessible from host at `192.168.122.100:18789`
- Ports: 18789 (gateway), 18790 (bridge)

## Troubleshooting

### "Gateway token missing" Error
**Solution**: Go to Control → Settings and paste the gateway token

### Container Won't Start
```bash
# Check logs
docker compose logs openclaw-gateway

# Restart
docker compose restart
```

### Permission Denied
```bash
# Fix ownership (container runs as uid 1000)
sudo chown -R 1000:1000 ~/.openclaw
```

### Connection Refused
- Verify gateway is running: `docker ps`
- Check port binding: `ss -tlnp | grep 18789`
- Ensure VM network allows connections

## Integration with Harvis

OpenClaw serves as an **extended backend** for Harvis AI:

1. **Harvis** (Frontend) → Handles voice, chat UI, user interaction
2. **OpenClaw Gateway** (Backend) → Handles system access, browser automation
3. **Communication**: WebSocket API between them

### Flow
```
User Voice → Harvis → OpenClaw Gateway → System Commands
                ↓
         LLM Processing
                ↓
         Results ← Browser/Screen Data
```

## API Endpoints

### WebSocket
- `ws://192.168.122.100:18789` - Main agent communication

### HTTP
- `http://192.168.122.100:18789/__openclaw__/canvas/` - Canvas/file manager
- `http://192.168.122.100:18789/__openclaw__/health` - Health check

## Docker Management

### Start
```bash
cd ~/openclaw
docker compose up -d
```

### Stop
```bash
cd ~/openclaw
docker compose down
```

### View Logs
```bash
# Gateway
docker compose logs -f openclaw-gateway

# CLI
docker compose logs openclaw-cli
```

### Restart
```bash
docker compose restart
```

## Resources

- **OpenClaw Docs**: https://docs.openclaw.ai/cli
- **GitHub**: https://github.com/openclaw
- **Gateway URL**: http://192.168.122.100:18789
- **Gateway Token**: `54a80e7033ddbe58d1caefbfff670d04310dea6885c2da3d321454da14f333c0`

## VM Details

- **IP**: 192.168.122.100
- **User**: openclaw
- **Password**: openclaw123
- **Location**: `/home/openclaw/openclaw`
- **Config**: `/home/openclaw/.openclaw`

---

*OpenClaw is now running and ready for AI agent integration!*
