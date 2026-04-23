# OpenClaw Gateway UI — Architecture Analysis

**Analysis Date:** 2026-04-21

## Overview

The OpenClaw Gateway UI is a **single-page application (SPA)** built with **Lit** (Web Components) and **Vite**. It communicates with the OpenClaw gateway via **JSON-RPC over WebSocket**. The entire UI is a single custom element `<openclaw-app>` with client-side routing and a centralized state model.

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| UI Framework | Lit (Web Components) | ^3.3.2 |
| Build Tool | Vite | 7.3.1 |
| Language | TypeScript (ESM) | — |
| Communication | WebSocket (custom JSON-RPC) | Protocol v3 |
| Markdown | marked | ^17.0.3 |
| HTML Sanitization | DOMPurify | ^3.3.1 |
| Crypto (device auth) | @noble/ed25519 | 3.0.0 |
| Signals | @lit-labs/signals | ^0.2.0 |
| Testing | Vitest + Playwright | 4.0.18 |

**No state management library** — all state lives in the `@state()` properties of the single `<openclaw-app>` element.
**No CSS framework** — all styling is custom CSS in `ui/src/styles.css`.
**No router library** — routing is handled by a simple `navigation.ts` module using `window.history`.

## Directory Layout

```
openclaw/
├── ui/                              # Frontend SPA
│   ├── src/
│   │   ├── main.ts                  # Entry: imports styles + app
│   │   ├── css.d.ts                 # CSS module type declarations
│   │   ├── styles.css               # Global styles
│   │   ├── styles/                  # CSS sub-modules
│   │   ├── i18n/                    # Internationalization
│   │   │   ├── index.ts
│   │   │   ├── locales/en.ts
│   │   │   ├── locales/pt-BR.ts
│   │   │   ├── locales/zh-CN.ts
│   │   │   └── locales/zh-TW.ts
│   │   └── ui/                      # Core UI logic
│   │       ├── app.ts               # Main <openclaw-app> web component (616 LOC)
│   │       ├── app.ts               # Main component — ALL state lives here
│   │       ├── gateway.ts           # GatewayBrowserClient — WebSocket RPC client
│   │       ├── app-gateway.ts       # WebSocket connection lifecycle + event routing
│   │       ├── app-chat.ts          # Chat send/receive, message queue
│   │       ├── app-render.ts        # render() function — single html template (1141 LOC)
│   │       ├── app-view-state.ts    # AppViewState type (merged state for render)
│   │       ├── app-lifecycle.ts     # connectedCallback/firstUpdated/disconnectedCallback
│   │       ├── app-settings.ts      # Tab switching, theme, settings persistence
│   │       ├── app-scroll.ts        # Chat scroll handling
│   │       ├── app-tool-stream.ts   # Agent tool call streaming
│   │       ├── app-channels.ts      # Channel-specific handlers (WhatsApp, Nostr)
│   │       ├── navigation.ts        # Tab definitions, path routing
│   │       ├── storage.ts           # localStorage persistence (UiSettings)
│   │       ├── theme.ts             # Theme resolution (light/dark/system)
│   │       ├── theme-transition.ts  # Theme transition animations
│   │       ├── markdown.ts          # Markdown rendering setup
│   │       ├── format.ts            # Text/date formatting utilities
│   │       ├── icons.ts             # Icon definitions
│   │       ├── uuid.ts              # UUID generation
│   │       ├── types.ts             # All API response types (640 LOC)
│   │       ├── types/chat-types.ts  # Chat message types
│   │       ├── types/usage-types.ts # Usage analytics types
│   │       ├── ui-types.ts          # UI-local types (attachments, queue, cron form)
│   │       ├── tool-display.ts      # Tool call display helpers
│   │       ├── tool-display.json    # Tool display configuration
│   │       ├── assistant-identity.ts # Agent identity normalization
│   │       ├── device-auth.ts       # Device token storage
│   │       ├── device-identity.ts   # Ed25519 device identity
│   │       ├── presenter.ts         # Content presentation layer
│   │       ├── focus-mode.browser.test.ts
│   │       ├── chat-event-reload.ts
│   │       ├── config-form.browser.test.ts
│   │       ├── controllers/         # Side-effect handlers (API calls)
│   │       │   ├── agents.ts        # Agents list, tools catalog
│   │       │   ├── agent-files.ts   # Agent file CRUD
│   │       │   ├── agent-identity.ts # Agent identity loading
│   │       │   ├── agent-skills.ts  # Agent skills loading
│   │       │   ├── chat.ts          # Chat history, message send, event handling
│   │       │   ├── config.ts        # Config load/save/apply/patch
│   │       │   ├── config/          # Config form helpers
│   │       │   ├── cron.ts          # Cron job CRUD
│   │       │   ├── debug.ts         # Debug method calling
│   │       │   ├── devices.ts       # Device pairing
│   │       │   ├── exec-approval.ts # Exec approval handling
│   │       │   ├── exec-approvals.ts # Exec approvals CRUD
│   │       │   ├── logs.ts          # Log tailing
│   │       │   ├── nodes.ts         # Node management
│   │       │   ├── presence.ts      # Presence polling
│   │       │   ├── sessions.ts      # Session management
│   │       │   ├── skills.ts        # Skills CRUD
│   │       │   ├── usage.ts         # Usage analytics
│   │       │   ├── channels.ts      # Channel status
│   │       │   ├── channels.types.ts
│   │       │   ├── assistant-identity.ts
│   │       │   ├── control-ui-bootstrap.ts
│   │       │   └── ... (29 files total)
│   │       ├── views/               # View render functions (Lit html templates)
│   │       │   ├── chat.ts          # Chat view (message list, input, sidebar)
│   │       │   ├── config.ts        # Config viewer (form + raw editor)
│   │       │   ├── agents.ts        # Agent list + detail panels
│   │       │   ├── channels.ts      # Channel status dashboard
│   │       │   ├── cron.ts          # Cron job management
│   │       │   ├── sessions.ts      # Session list + details
│   │       │   ├── usage.ts         # Usage analytics dashboard
│   │       │   ├── skills.ts        # Skills management
│   │       │   ├── nodes.ts         # Node management + exec approvals
│   │       │   ├── overview.ts      # Dashboard overview
│   │       │   ├── instances.ts     # Connected instances (presence)
│   │       │   ├── debug.ts         # Debug tools (method caller)
│   │       │   ├── logs.ts          # Log viewer
│   │       │   ├── exec-approval.ts # Exec approval prompts
│   │       │   ├── gateway-url-confirmation.ts
│   │       │   ├── markdown-sidebar.ts
│   │       │   ├── config-form.ts   # Dynamic config form renderer
│   │       │   ├── config-form.shared.ts  # Shared config form utilities
│   │       │   ├── channels.*       # Per-channel views (Discord, Slack, Telegram, etc.)
│   │       │   └── usage-styles/    # Usage dashboard CSS
│   │       ├── chat/                # Chat rendering subsystem
│   │       │   ├── grouped-render.ts  # Message grouping + rendering
│   │       │   ├── message-normalizer.ts # Message normalization
│   │       │   ├── message-extract.ts # Text extraction from messages
│   │       │   ├── tool-cards.ts    # Tool call card rendering
│   │       │   ├── tool-helpers.ts  # Tool display helpers
│   │       │   ├── constants.ts
│   │       │   └── copy-as-markdown.ts
│   │       ├── components/          # Shared web components
│   │       │   └── resizable-divider.ts  # Sidebar splitter
│   │       ├── test-helpers/        # Test utilities
│   │       └── __screenshots__/     # Visual regression test screenshots
│   ├── public/                      # Static assets (favicon.svg, etc.)
│   ├── index.html                   # SPA entry point
│   ├── vite.config.ts               # Vite build config
│   └── package.json
├── src/gateway/                     # Backend (TypeScript)
│   ├── control-ui.ts                # Static file serving + SPA fallback
│   ├── control-ui-contract.ts       # Bootstrap config contract
│   ├── control-ui-csp.ts            # CSP headers
│   ├── control-ui-shared.ts         # Shared utilities
│   ├── server-http.ts               # HTTP server (routes to control UI)
│   ├── server.ts                    # Main gateway server
│   ├── server-ws-runtime.ts         # WebSocket handler attachment
│   ├── server-methods.ts            # RPC method registry (all handlers)
│   ├── server-methods/              # Individual RPC method handlers
│   │   ├── connect.ts               # WebSocket connect handshake
│   │   ├── chat.ts                  # Chat send/history/abort
│   │   ├── config.ts                # Config get/set/apply/patch
│   │   ├── agents.ts                # Agent list/CRUD
│   │   ├── cron.ts                  # Cron job management
│   │   ├── sessions.ts              # Session management
│   │   ├── skills.ts                # Skills CRUD
│   │   ├── nodes.ts                 # Node management
│   │   ├── usage.ts                 # Usage analytics
│   │   └── ... (28 handler files)
│   ├── protocol/                    # WebSocket protocol definitions
│   │   ├── index.ts                 # All schemas + validators (AJV)
│   │   ├── schema.ts                # JSON Schema definitions
│   │   ├── schema/                  # Per-message-type schemas
│   │   ├── client-info.ts           # Client identification
│   │   └── connect-error-details.ts # Connection error codes
│   └── auth.ts                      # Authentication logic
└── config/openclaw.json             # Harvis instance config
```

## Architecture Pattern

### Single Custom Element Architecture

The entire application is **one web component** (`<openclaw-app>`) defined in `ui/src/ui/app.ts`. This is an unusual but effective pattern for a dashboard:

```typescript
@customElement("openclaw-app")
export class OpenClawApp extends LitElement {
  @state() connected = false;
  @state() tab: Tab = "chat";
  @state() chatMessages: unknown[] = [];
  @state() agentsList: AgentsListResult | null = null;
  // ... 100+ @state() properties

  createRenderRoot() {
    return this; // Light DOM — no shadow root
  }

  render() {
    return renderApp(this as unknown as AppViewState);
  }
}
```

**Key design decisions:**
- **Light DOM** (`createRenderRoot() { return this; }`) — CSS from global stylesheets applies directly. No shadow DOM encapsulation.
- **Single render function** (`renderApp()` in `app-render.ts`, 1141 lines) — all 13 views rendered in one giant template with `?: nothing` conditionals.
- **Controller pattern** — side effects (API calls) are in `controllers/` files. Views are pure render functions receiving props.
- **No Redux/MobX/Jotai** — all state is `@state()` on the component. Updates trigger re-render of the entire tree.

### Client-Side Routing

Routing is handled by `navigation.ts` using `window.history`:

```typescript
export const TAB_GROUPS = [
  { label: "chat", tabs: ["chat"] },
  { label: "control", tabs: ["overview", "channels", "instances", "sessions", "usage", "cron"] },
  { label: "agent", tabs: ["agents", "skills", "nodes"] },
  { label: "settings", tabs: ["config", "debug", "logs"] },
];

export type Tab = "agents" | "overview" | "channels" | "instances" | "sessions" |
  "usage" | "cron" | "skills" | "nodes" | "chat" | "config" | "debug" | "logs";
```

URLs map directly to tabs: `/chat`, `/agents`, `/config`, etc. Base path is supported for reverse proxy deployments (`window.__OPENCLAW_CONTROL_UI_BASE_PATH__`).

### State Management

**Centralized state object** with ~100 reactive properties on `OpenClawApp`:

```typescript
@state() settings: UiSettings = loadSettings();
@state() connected = false;
@state() hello: GatewayHelloOk | null = null;
@state() chatMessages: unknown[] = [];
@state() chatStream: string | null = null;
@state() agentsList: AgentsListResult | null = null;
@state() configRaw = "{\n}\n";
@state() cronJobs: CronJob[] = [];
@state() logsEntries: LogEntry[] = [];
// ... etc
```

**Persistence:** `storage.ts` — settings saved to `localStorage` under key `openclaw.control.settings.v1`.

**Settings shape (`UiSettings`):**
```typescript
type UiSettings = {
  gatewayUrl: string;       // WebSocket URL (default: ws://current-host)
  token: string;            // Auth token
  sessionKey: string;       // Current session ("main")
  lastActiveSessionKey: string;
  theme: "light" | "dark" | "system";
  chatFocusMode: boolean;
  chatShowThinking: boolean;
  splitRatio: number;       // Sidebar split ratio (0.4-0.7)
  navCollapsed: boolean;
  navGroupsCollapsed: Record<string, boolean>;
  locale?: string;
};
```

## Communication Protocol

### WebSocket Connection Flow

1. **Client connects** to `ws://host` (or `wss://host` for HTTPS)
2. **Server sends** `{"type": "event", "event": "connect.challenge", "payload": {"nonce": "..."}}`
3. **Client responds** with `{"type": "req", "id": "...", "method": "connect", "params": {...}}`
4. **Server responds** with `{"type": "res", "id": "...", "ok": true, "payload": {"type": "hello-ok", ...}}`
5. **Connection established** — bidirectional message exchange begins

### JSON-RPC Frame Format

**Request (client → server):**
```json
{
  "type": "req",
  "id": "uuid",
  "method": "chat.send",
  "params": { "sessionKey": "main", "text": "hello" }
}
```

**Response (server → client):**
```json
{
  "type": "res",
  "id": "uuid",
  "ok": true,
  "payload": { ... }
}
```

**Event (server → client):**
```json
{
  "type": "event",
  "event": "chat",
  "payload": {
    "runId": "...",
    "sessionKey": "main",
    "state": "delta",
    "message": { "role": "assistant", "content": "..." }
  },
  "seq": 42
}
```

### WebSocket Methods (RPC API)

Registered in `src/gateway/server-methods.ts`:

| Category | Methods | File |
|----------|---------|------|
| **Connect** | `connect`, `health` | `server-methods/connect.ts`, `health.ts` |
| **Chat** | `chat.send`, `chat.history`, `chat.abort`, `chat.inject` | `server-methods/chat.ts` |
| **Config** | `config.get`, `config.set`, `config.patch`, `config.apply`, `config.schema` | `server-methods/config.ts` |
| **Agents** | `agents.list`, `agents.create`, `agents.update`, `agents.delete`, `agents.files.list`, `agents.files.get`, `agents.files.set`, `agents.identity`, `agents.wait` | `server-methods/agents.ts`, `agent.ts` |
| **Sessions** | `sessions.list`, `sessions.patch`, `sessions.delete`, `sessions.reset`, `sessions.compact`, `sessions.usage`, `sessions.preview`, `sessions.resolve` | `server-methods/sessions.ts` |
| **Cron** | `cron.list`, `cron.status`, `cron.add`, `cron.update`, `cron.remove`, `cron.run`, `cron.runs` | `server-methods/cron.ts` |
| **Skills** | `skills.status`, `skills.update`, `skills.install`, `skills.bins` | `server-methods/skills.ts` |
| **Channels** | `channels.status`, `channels.logout`, `web.login.start`, `web.login.wait` | `server-methods/channels.ts`, `web.ts` |
| **Nodes** | `nodes.list`, `nodes.describe`, `nodes.invoke`, `nodes.invoke.result`, `nodes.event`, `nodes.pair.request`, `nodes.pair.list`, `nodes.pair.approve`, `nodes.pair.reject`, `nodes.pair.verify`, `nodes.rename` | `server-methods/nodes.ts` |
| **Devices** | `device.pair.list`, `device.pair.approve`, `device.pair.reject`, `device.token.rotate`, `device.token.revoke` | `server-methods/devices.ts` |
| **Exec Approvals** | `exec.approvals.get`, `exec.approvals.set`, `exec.approvals.node.get`, `exec.approvals.node.set`, `exec.approval.request`, `exec.approval.resolve` | `server-methods/exec-approvals.ts` |
| **Usage** | `usage.sessions`, `usage.daily`, `usage.time-series` | `server-methods/usage.ts` |
| **Logs** | `logs.tail` | `server-methods/logs.ts` |
| **Models** | `models.list` | `server-methods/models.ts` |
| **Tools** | `tools.catalog` | `server-methods/tools-catalog.ts` |
| **Update** | `update.run` | `server-methods/update.ts` |
| **Wizard** | `wizard.start`, `wizard.next`, `wizard.cancel`, `wizard.status` | `server-methods/wizard.ts` |
| **Talk** | `talk.mode`, `talk.config` | `server-methods/talk.ts` |
| **Voicewake** | `voicewake.*` | `server-methods/voicewake.ts` |
| **TTS** | `tts.*` | `server-methods/tts.ts` |
| **Push** | `push.test` | `server-methods/push.ts` |
| **Send** | `send.*` | `server-methods/send.ts` |
| **Browser** | `browser.*` | `server-methods/browser.ts` |
| **Doctor** | `doctor.*` | `server-methods/doctor.ts` |
| **System** | `system.*` | `server-methods/system.ts` |

### WebSocket Events

| Event | Payload | Handler |
|-------|---------|---------|
| `chat` | `ChatEventPayload` (runId, state: delta/final/aborted/error) | `controllers/chat.ts` → `handleChatEvent()` |
| `agent` | `AgentEventPayload` (stream, data, seq) | `app-tool-stream.ts` → `handleAgentEvent()` |
| `presence` | `PresenceEntry[]` | Updates presence list |
| `cron` | — | Reloads cron jobs |
| `device.pair.requested` | — | Reloads devices |
| `device.pair.resolved` | — | Reloads devices |
| `exec.approval.requested` | ExecApprovalRequest | Adds to approval queue |
| `exec.approval.resolved` | — | Removes from approval queue |
| `update-available` | UpdateAvailable info | Shows update banner |

## Authentication Flow

### Device Identity + Token Auth

1. **Device identity** (`device-identity.ts`): Generates Ed25519 keypair, stored in localStorage
2. **Device auth** (`device-auth.ts`): Device tokens stored in localStorage
3. **Connect flow** (`gateway.ts` line 161-278):
   - In secure contexts (HTTPS/localhost): uses device identity with Ed25519 signature
   - Over plain HTTP: falls back to token-only auth (requires `gateway.controlUi.allowInsecureAuth`)
   - Scopes requested: `["operator.admin", "operator.approvals", "operator.pairing"]`
   - Role: `"operator"`
   - Client name: `"openclaw-control-ui"`
   - Mode: `"webchat"`

### Server-Side Auth (`src/gateway/auth.ts`)

- Token-based auth mode (configured in `openclaw.json`)
- Device auth via Ed25519 signatures
- Role-based method authorization (`method-scopes.ts`)
- Rate limiting on auth attempts

## Views (13 Tabs)

### Chat (`/chat`) — Primary Interface
- **File:** `views/chat.ts` (616 lines)
- **Features:** Message groups, streaming text, tool call cards, image attachments, session selector, focus mode, sidebar for tool output, split ratio
- **Message types:** User messages, assistant messages (text + tool calls), tool results, streaming text, reading indicator, dividers
- **Grouping:** Messages grouped by role (consecutive same-role messages merged)
- **State:** `chatMessages`, `chatStream`, `chatToolMessages`, `chatQueue`

### Overview (`/overview`) — Dashboard
- **File:** `views/overview.ts`
- **Features:** Version display, health status, session count, cron status, channel status, quick settings

### Channels (`/channels`) — Messaging Integration
- **File:** `views/channels.ts`
- **Sub-views:** Per-channel status (Discord, Slack, Telegram, WhatsApp, Signal, iMessage, Google Chat, Nostr, MS Teams)
- **Features:** QR code for WhatsApp, channel config form, Nostr profile editing

### Instances (`/instances`) — Connected Nodes
- **File:** `views/instances.ts`
- **Features:** Presence list (host, platform, version, roles, last seen)

### Sessions (`/sessions`) — Chat History
- **File:** `views/sessions.ts`
- **Features:** Session list with filters (active time, limit, global, unknown), session details, patch/delete

### Usage (`/usage`) — Analytics
- **File:** `views/usage.ts` + `usage-render-overview.ts`, `usage-render-details.ts`
- **Features:** Token/cost charts, daily breakdown, time series, session log viewer, query filters

### Cron (`/cron`) — Scheduled Tasks
- **File:** `views/cron.ts`
- **Features:** Job list with pagination, job CRUD form, run history, delivery configuration

### Agents (`/agents`) — Agent Management
- **File:** `views/agents.ts`
- **Panels:** overview, files, tools, skills, channels, cron
- **Features:** Agent selection, file editor (agent config files), tool catalog/profile management, skills management

### Skills (`/skills`) — Skill Management
- **File:** `views/skills.ts`
- **Features:** Skills list, enable/disable, API key management, install, edit

### Nodes (`/nodes`) — Node Management
- **File:** `views/nodes.ts`
- **Features:** Node list, device pairing, exec approval configuration, node bindings

### Config (`/config`) — Configuration Editor
- **File:** `views/config.ts` (820 lines)
- **Features:** JSON schema-driven form editor + raw JSON editor, config validation, save/apply/update

### Debug (`/debug`) — Diagnostic Tools
- **File:** `views/debug.ts`
- **Features:** Status summary, health snapshot, model list, method caller (manual RPC testing), event log

### Logs (`/logs`) — Gateway Logs
- **File:** `views/logs.ts`
- **Features:** Log tailing, level filtering, text search, export, auto-follow

## Config Form System

The config view (`views/config-form.ts`) is a **dynamic form renderer** driven by JSON Schema:

1. **Schema fetch:** `config.schema` endpoint returns JSON Schema + UI hints
2. **Schema analysis:** `analyzeConfigSchema()` traverses the schema to build sections
3. **Section metadata:** `SECTION_META` defines section ordering and grouping
4. **Form rendering:** Recursive renderer handles objects, arrays, primitives, enums
5. **UI hints:** `ConfigUiHints` provides labels, help text, tags, placeholders, sensitivity flags
6. **Search:** Config search (`config-search.ts`) indexes schema paths by tags
7. **Form mode:** Toggle between form view and raw JSON editor

**Config form path operations:**
- `updateConfigFormValue(state, ["agents", "list", 0, "model"], "ollama/qwen")` — nested path updates
- `removeConfigFormValue(state, ["agents", "list", 0, "model"])` — nested path deletion

## Chat Architecture

### Message Flow

1. **Send:** `controllers/chat.ts` → `client.request("chat.send", { sessionKey, text, attachments })`
2. **Streaming:** Events arrive via WebSocket:
   - `chat` event with `state: "delta"` → accumulate `chatStream`
   - `agent` event → update tool stream sidebar
   - `chat` event with `state: "final"` → append to `chatMessages`, clear stream
3. **History load:** `client.request("chat.history", { sessionKey, limit: 200 })`
4. **Abort:** `client.request("chat.abort", { runId })`

### Message Normalization (`chat/message-normalizer.ts`)

Raw messages from the API are normalized to a consistent shape:
```typescript
type NormalizedMessage = {
  role: string;           // "user" | "assistant" | "system"
  content: MessageContentItem[];
  timestamp: number;
  id?: string;
};

type MessageContentItem = {
  type: "text" | "tool_call" | "tool_result";
  text?: string;
  name?: string;          // tool name
  args?: unknown;         // tool arguments
};
```

### Message Grouping (`chat/grouped-render.ts`)

Consecutive messages from the same role are grouped (like Slack):
```typescript
type MessageGroup = {
  kind: "group";
  role: string;
  messages: Array<{ message: unknown; key: string }>;
  timestamp: number;
  isStreaming: boolean;
};
```

### Tool Stream (`app-tool-stream.ts`)

Tool calls and results are displayed in a **right sidebar** with split ratio control:
- `ToolStreamEntry` tracks each tool call by `toolCallId`
- Limited to 50 entries, throttled at 80ms
- Output capped at 120,000 characters
- Sync timer debounces sidebar updates

## Styling Approach

**No CSS framework or preprocessor.** All styling is vanilla CSS in:
- `ui/src/styles.css` — global styles
- `ui/src/styles/` — CSS sub-modules (likely component-specific)
- Scoped via CSS class naming conventions (BEM-like): `.shell`, `.topbar`, `.nav`, `.content`, `.nav-group`, etc.

**Theme:** CSS custom properties for light/dark themes, resolved via `theme.ts` (system preference, light, or dark).

**Key CSS classes:**
- `.shell` — main layout container
- `.topbar` — top status bar
- `.nav` — collapsible sidebar navigation
- `.content` — main content area
- `.nav-group` — nav group with collapsible sections
- `.nav-item` — individual nav items with icons
- `.page-title` / `.page-sub` — page headers
- `.content-header` — header with title + actions
- `.update-banner` — update notification
- `.sidebar` — tool output sidebar

## Internationalization

**Framework:** Custom i18n module in `i18n/index.ts` using a simple key-based system.

**Supported locales:** `en`, `pt-BR`, `zh-CN`, `zh-TW`

**Translation keys:** `t("tabs.chat")`, `t("nav.control")`, `t("common.version")`, etc.

**Structure:**
```
i18n/
├── index.ts           # t() function, locale switching
├── lib/               # i18n utilities
└── locales/
    ├── en.ts          # English (reference)
    ├── pt-BR.ts       # Brazilian Portuguese
    ├── zh-CN.ts       # Simplified Chinese
    └── zh-TW.ts       # Traditional Chinese
```

## Build & Deployment

### Build Process
```bash
pnpm ui:build  # Builds to dist/control-ui/
```

**Vite config:**
- Output: `dist/control-ui/`
- Base path: configurable via `OPENCLAW_CONTROL_UI_BASE_PATH` env var
- Sourcemaps enabled
- Dev server: port 5173

### Server-Side Serving (`src/gateway/control-ui.ts`)

The gateway serves the built UI as static files:

1. **SPA fallback:** All non-asset paths return `index.html` (client-side router)
2. **Asset caching:** `Cache-Control: no-cache` for all UI assets
3. **Security headers:** `X-Frame-Options: DENY`, CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`
4. **Bootstrap config:** `GET /openclaw-control-ui/bootstrap` returns assistant identity + base path
5. **Avatar serving:** `GET /openclaw-control-ui/avatar/:agentId` serves agent avatars
6. **Base path support:** When `gateway.controlUi.basePath` is set, all routes are prefixed

### Harvis Deployment

In `config/openclaw.json`:
```json
{
  "gateway": {
    "controlUi": { "enabled": false }  // UI is disabled in Harvis
  }
}
```

The UI is served behind Nginx at `http://localhost:9000` (same as Harvis frontend), but is currently disabled.

## Key Architecture Decisions for UI Replacement

If building a replacement UI, you need to replicate:

1. **WebSocket JSON-RPC protocol** — This is the primary communication channel. Every UI action is either a `request()` or an event handler.
2. **Event-driven state updates** — The UI updates reactively to WebSocket events (chat delta, agent tool stream, presence changes).
3. **13 tabs across 4 groups** — Navigation structure is fixed in `navigation.ts`.
4. **Centralized state** — All state in one place. No need for a state management library if you follow this pattern.
5. **Controller pattern** — Side effects (API calls) are separated from views. Controllers modify the state object directly.
6. **Config form from JSON Schema** — The config view is dynamically generated from the schema returned by `config.schema`. This is a complex system (~800 LOC).
7. **Chat message normalization + grouping** — Messages must be normalized from the API format and grouped by role for rendering.
8. **Tool stream sidebar** — Tool calls are displayed in a resizable sidebar alongside the chat.
9. **Device auth flow** — Ed25519 device identity for secure WebSocket authentication.
10. **localStorage persistence** — Settings are saved to localStorage.
