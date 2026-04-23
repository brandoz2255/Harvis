# OpenClaw Gateway UI — External Integrations

**Analysis Date:** 2026-04-21

## APIs & External Services

### OpenClaw Gateway (Primary Integration)

The UI communicates exclusively with the OpenClaw gateway via WebSocket:

- **Protocol:** Custom JSON-RPC over WebSocket (v3)
- **Connection:** `ws://host` or `wss://host` (auto-detected from current origin)
- **Client identity:** `"openclaw-control-ui"` with mode `"webchat"`
- **Role:** `"operator"` with scopes `["operator.admin", "operator.approvals", "operator.pairing"]`
- **Auth:** Ed25519 device identity + token/password
- **Methods:** 80+ RPC methods across 20+ categories
- **Events:** 8+ event types streamed bidirectionally

**Connection URL resolution** (`storage.ts` line 21-24):
```typescript
const defaultUrl = (() => {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}`;
})();
```

**GatewayBrowserClient** (`gateway.ts`):
- Auto-reconnect with exponential backoff (800ms → 15s max)
- Message sequencing with gap detection
- Pending request tracking (UUID-based)
- Device identity with Ed25519 signing
- Challenge-nonce auth flow

### Harvis Backend (via OpenClaw proxy)

In the Harvis deployment, the OpenClaw gateway proxies to:
- **Harvis LLM proxy:** `http://backend:8000/v1` (OpenAI-compatible API)
- **Ollama local:** `http://ollama:11434`
- **MCP Mempalace:** `http://harvis-mempalace:8095/sse`

The UI itself does NOT connect to these directly — all communication goes through the OpenClaw gateway.

## Data Storage

**Client-side:**
- **localStorage** — `openclaw.control.settings.v1` key stores `UiSettings`
  - Contains: gatewayUrl, token, sessionKey, theme, locale, nav state
- **Device identity** — Ed25519 keypair generated and stored in localStorage
- **Device auth tokens** — Stored in localStorage, keyed by device ID + role

**Server-side (gateway):**
- Agent sessions: `~/.openclaw/sessions/` (JSONL format)
- Config: `config/openclaw.json`
- Skills: `skills/` directory
- Node data: gateway-managed

## Authentication & Identity

### Device Identity Flow

1. **Key generation** (`device-identity.ts`): `crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"])`
2. **Key storage**: Public key and device ID in localStorage
3. **Connection auth** (`gateway.ts`):
   - Secure context (HTTPS/localhost): Ed25519 signed device auth
   - Non-secure context: Falls back to token-only auth
   - Server rejects insecure auth unless `gateway.controlUi.allowInsecureAuth` is enabled

### Auth Flow Details

```
Browser                          Gateway
   |                                |
   |--- WebSocket connect ---------->|
   |<-- event: connect.challenge ---|
   |   { nonce: "..." }             |
   |                                |
   |--- req: connect -------------->|
   |   {                           |
   |     device: {                 |
   |       id, publicKey,          |
   |       signature, signedAt,    |
   |       nonce                  |
   |     },                        |
   |     auth: { token, password },|
   |     role: "operator",         |
   |     scopes: [...]             |
   |   }                           |
   |<-- res: ok -------------------|
   |   { type: "hello-ok",        |
   |     auth: { deviceToken },    |
   |     snapshot: {...}           |
   |   }                           |
```

### Role-Based Method Authorization

Methods are scoped by role and permissions:
- `operator.admin` — All methods
- `operator.approvals` — Exec approval methods
- `operator.pairing` — Device/node pairing methods
- `node` role — Node-specific methods only

## Monitoring & Observability

**No external monitoring services** integrated into the UI.

**Built-in observability:**
- **Debug tab** (`views/debug.ts`): Method caller, health snapshot, event log
- **Logs tab** (`views/logs.ts`): Gateway log tailing with level filtering
- **Event log** (debug tab): Last 250 WebSocket events buffered client-side
- **Health endpoint**: `health` RPC method returns gateway health status

**Logging approach:**
- Client-side: `console.error()` for gateway errors
- Server-side: Subsystem logging (gateway, health, ws-control)

## CI/CD & Deployment

**Build pipeline:**
- `pnpm ui:build` — Build UI to `dist/control-ui/`
- Gateway includes built UI in static file serving

**Deployment:**
- UI is bundled into the gateway Docker image
- Served from `dist/control-ui/` path on the gateway HTTP server
- SPA fallback: all non-asset paths return `index.html`
- Base path support for reverse proxy deployments (`/openclaw-control-ui/`)

**K8s deployment (Harvis):**
- Gateway runs in Kubernetes
- Port 18789 exposed internally
- UI accessible via Nginx proxy at `http://localhost:9000`
- Currently disabled in Harvis (`gateway.controlUi.enabled: false`)

## Webhooks & Callbacks

**Incoming:**
- No webhook endpoints in the UI
- Channel webhooks (Telegram, Slack, Google Chat) are configured at the gateway level, not the UI

**Outgoing:**
- No outgoing webhooks from the UI
- Cron delivery can send to webhook URLs (configured via cron jobs), but this goes through the gateway, not the UI

## Environment Configuration

**Required env vars:**
- `OPENCLAW_CONTROL_UI_BASE_PATH` — Optional base path for reverse proxy

**Secrets location:**
- Auth tokens stored in `localStorage` (key: `openclaw.control.settings.v1`)
- Device Ed25519 private key stored in `localStorage`
- Gateway config tokens referenced via env var substitution (`${OPENCLAW_GATEWAY_TOKEN}`)

## WebSocket Protocol Details

### Frame Types

| Type | Direction | Structure |
|------|-----------|-----------|
| `req` | Client → Server | `{ type: "req", id: uuid, method: string, params: any }` |
| `res` | Server → Client | `{ type: "res", id: uuid, ok: bool, payload: any, error: { code, message } }` |
| `event` | Server → Client | `{ type: "event", event: string, payload: any, seq?: number }` |

### Event Types

| Event | Payload Type | UI Handler |
|-------|-------------|------------|
| `chat` | `ChatEventPayload` | `controllers/chat.ts` → `handleChatEvent()` |
| `agent` | `AgentEventPayload` | `app-tool-stream.ts` → `handleAgentEvent()` |
| `presence` | `PresenceEntry[]` | Updates `presenceEntries` state |
| `cron` | — | Reloads cron jobs |
| `device.pair.requested` | — | Reloads devices |
| `device.pair.resolved` | — | Reloads devices |
| `exec.approval.requested` | `ExecApprovalRequest` | Adds to approval queue |
| `exec.approval.resolved` | — | Removes from approval queue |
| `update-available` | `UpdateAvailable` | Shows update banner |

### Chat Event States

| State | Meaning |
|-------|---------|
| `delta` | Streaming text update |
| `final` | Message complete — append to history |
| `aborted` | User cancelled |
| `error` | Error occurred |

### Agent Event Stream

```typescript
type AgentEventPayload = {
  runId: string;
  seq: number;
  stream: string;       // Tool call stream identifier
  ts: number;
  sessionKey?: string;
  data: Record<string, unknown>;  // Tool call/result data
};
```

Agent events are processed by `app-tool-stream.ts` which:
- Maintains a map of tool call entries by `toolCallId`
- Limits to 50 entries
- Throttles updates at 80ms
- Caps output at 120,000 characters
- Renders tool calls in the right sidebar

## Configuration Integration

The UI reads gateway configuration through:

1. **Bootstrap config** (`GET /openclaw-control-ui/bootstrap`): Returns assistant name, avatar, agent ID
2. **Config snapshot** (`config.get` RPC): Full config JSON
3. **Config schema** (`config.schema` RPC): JSON Schema with UI hints for form rendering
4. **Agents list** (`agents.list` RPC): Available agents with identity info
5. **Tools catalog** (`tools.catalog` RPC): Available tools with profiles
6. **Channels status** (`channels.status` RPC): Channel connectivity info
