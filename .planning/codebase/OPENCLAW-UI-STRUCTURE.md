# OpenClaw Gateway UI — Codebase Structure

**Analysis Date:** 2026-04-21

## Project Layout

```
openclaw/                              # OpenClaw monorepo root
├── ui/                                # Frontend SPA (Vite + Lit)
│   ├── src/
│   │   ├── main.ts                    # Entry point: styles + app
│   │   ├── css.d.ts                   # CSS module type declarations
│   │   ├── styles.css                 # Global CSS (all styling)
│   │   ├── styles/                    # CSS sub-modules
│   │   ├── i18n/                      # Internationalization
│   │   │   ├── index.ts               # t() function + locale switching
│   │   │   ├── lib/                   # i18n utilities
│   │   │   └── locales/               # Translation files
│   │   │       ├── en.ts              # English (reference)
│   │   │       ├── pt-BR.ts           # Brazilian Portuguese
│   │   │       ├── zh-CN.ts           # Simplified Chinese
│   │   │       └── zh-TW.ts           # Traditional Chinese
│   │   └── ui/                        # Core UI logic
│   │       ├── app.ts                 # <openclaw-app> web component (616 LOC)
│   │       ├── app-render.ts          # render() function (1141 LOC)
│   │       ├── app-view-state.ts      # AppViewState type for render
│   │       ├── app-lifecycle.ts       # Lifecycle hooks
│   │       ├── app-settings.ts        # Tab/theme/settings logic
│   │       ├── app-scroll.ts          # Scroll handling
│   │       ├── app-gateway.ts         # WebSocket connection + event routing
│   │       ├── app-chat.ts            # Chat send/receive logic
│   │       ├── app-tool-stream.ts     # Tool call streaming
│   │       ├── app-channels.ts        # Channel handlers (WhatsApp, Nostr)
│   │       ├── app-defaults.ts        # Default values
│   │       ├── app-events.ts          # Event log types
│   │       ├── gateway.ts             # GatewayBrowserClient class
│   │       ├── navigation.ts          # Tab/route definitions
│   │       ├── storage.ts             # localStorage persistence
│   │       ├── theme.ts               # Theme resolution
│   │       ├── theme-transition.ts    # Theme transition effects
│   │       ├── markdown.ts            # Markdown setup
│   │       ├── format.ts              # Formatting utilities
│   │       ├── icons.ts               # Icon definitions
│   │       ├── uuid.ts                # UUID generation
│   │       ├── tool-display.ts        # Tool display config
│   │       ├── tool-display.json      # Tool display definitions
│   │       ├── presenter.ts           # Content presentation
│   │       ├── text-direction.ts      # RTL/LTR detection
│   │       ├── assistant-identity.ts  # Agent identity normalization
│   │       ├── device-auth.ts         # Device token storage
│   │       ├── device-identity.ts     # Ed25519 device identity
│   │       ├── types.ts               # API types (640 LOC)
│   │       ├── types/                 # Type sub-files
│   │       │   ├── chat-types.ts      # Chat message types
│   │       │   └── usage-types.ts     # Usage analytics types
│   │       ├── ui-types.ts            # UI-local types
│   │       ├── controllers/           # Side-effect handlers (29 files)
│   │       │   ├── agents.ts          # agents.list, tools.catalog
│   │       │   ├── agent-files.ts     # agents.files CRUD
│   │       │   ├── agent-identity.ts  # agents.identity
│   │       │   ├── agent-skills.ts    # Agent skills loading
│   │       │   ├── chat.ts            # chat.send, chat.history, event handling
│   │       │   ├── config.ts          # config.get/set/patch/apply/schema
│   │       │   ├── config/            # Config form helpers
│   │       │   │   ├── analyze.ts     # Schema analysis
│   │       │   │   └── render.ts      # Form rendering helpers
│   │       │   ├── cron.ts            # cron.list/add/update/remove/run
│   │       │   ├── debug.ts           # Debug method caller
│   │       │   ├── devices.ts         # Device pairing/rotation
│   │       │   ├── exec-approval.ts   # Exec approval queue
│   │       │   ├── exec-approvals.ts  # Exec approvals CRUD
│   │       │   ├── logs.ts            # logs.tail
│   │       │   ├── nodes.ts           # nodes.list/describe/invoke
│   │       │   ├── presence.ts        # Presence polling
│   │       │   ├── sessions.ts        # sessions.list/patch/delete
│   │       │   ├── skills.ts          # skills.status/update/install
│   │       │   ├── usage.ts           # Usage analytics loading
│   │       │   ├── channels.ts        # channels.status
│   │       │   ├── channels.types.ts  # Channel type definitions
│   │       │   ├── assistant-identity.ts
│   │       │   ├── control-ui-bootstrap.ts
│   │       │   └── ...
│   │       ├── views/                 # View render functions
│   │       │   ├── chat.ts            # Chat view (616 LOC)
│   │       │   ├── config.ts          # Config editor (820 LOC)
│   │       │   ├── config-form.ts     # Dynamic form renderer
│   │       │   ├── config-form.shared.ts  # Shared form utilities
│   │       │   ├── config-search.ts   # Config search indexing
│   │       │   ├── agents.ts          # Agent management
│   │       │   ├── agents-utils.ts    # Agent view utilities
│   │       │   ├── agents-panels-status-files.ts
│   │       │   ├── agents-panels-tools-skills.ts
│   │       │   ├── channels.ts        # Channel dashboard
│   │       │   ├── channels.shared.ts # Channel view utilities
│   │       │   ├── channels.types.ts  # Channel type definitions
│   │       │   ├── channels.discord.ts
│   │       │   ├── channels.googlechat.ts
│   │       │   ├── channels.imessage.ts
│   │       │   ├── channels.nostr.ts
│   │       │   ├── channels.nostr-profile-form.ts
│   │       │   ├── channels.signal.ts
│   │       │   ├── channels.slack.ts
│   │       │   ├── channels.telegram.ts
│   │       │   ├── channels.whatsapp.ts
│   │       │   ├── cron.ts            # Cron management
│   │       │   ├── sessions.ts        # Session list
│   │       │   ├── usage.ts           # Usage dashboard
│   │       │   ├── usage-metrics.ts   # Usage metrics
│   │       │   ├── usage-query.ts     # Usage query handling
│   │       │   ├── usage-render-details.ts
│   │       │   ├── usage-render-overview.ts
│   │       │   ├── usageTypes.ts
│   │       │   ├── usageStyles.ts
│   │       │   ├── usage-styles/      # Usage chart styles
│   │       │   ├── skills.ts          # Skills management
│   │       │   ├── skills-grouping.ts
│   │       │   ├── skills-shared.ts
│   │       │   ├── nodes.ts           # Node management
│   │       │   ├── nodes-exec-approvals.ts
│   │       │   ├── overview.ts        # Dashboard overview
│   │       │   ├── overview-hints.ts
│   │       │   ├── instances.ts       # Presence/instances
│   │       │   ├── debug.ts           # Debug tools
│   │       │   ├── logs.ts            # Log viewer
│   │       │   ├── exec-approval.ts   # Exec approval prompts
│   │       │   ├── gateway-url-confirmation.ts
│   │       │   └── markdown-sidebar.ts
│   │       ├── chat/                  # Chat rendering subsystem
│   │       │   ├── grouped-render.ts  # Message group rendering
│   │       │   ├── message-normalizer.ts
│   │       │   ├── message-extract.ts
│   │       │   ├── tool-cards.ts      # Tool call card rendering
│   │       │   ├── tool-helpers.ts
│   │       │   ├── constants.ts
│   │       │   └── copy-as-markdown.ts
│   │       ├── components/            # Shared web components
│   │       │   └── resizable-divider.ts  # Sidebar splitter
│   │       ├── test-helpers/          # Test utilities
│   │       └── __screenshots__/       # Visual regression tests
│   ├── public/                        # Static assets
│   ├── index.html                     # SPA entry
│   ├── vite.config.ts                 # Vite build config
│   ├── vitest.config.ts               # Browser test config
│   ├── vitest.node.config.ts          # Node test config
│   └── package.json                   # Dependencies
├── src/gateway/                       # Gateway server
│   ├── control-ui.ts                  # Static file serving
│   ├── control-ui-contract.ts         # Bootstrap config types
│   ├── control-ui-csp.ts              # CSP header builder
│   ├── control-ui-shared.ts           # Shared utilities
│   ├── server-http.ts                 # HTTP router
│   ├── server.ts                      # Main gateway
│   ├── server-ws-runtime.ts           # WebSocket setup
│   ├── server-methods.ts              # RPC method registry
│   ├── server-methods/                # RPC handlers (28 files)
│   └── protocol/                      # Protocol schemas
│       ├── index.ts                   # Schemas + validators
│       ├── schema.ts                  # JSON Schema definitions
│       ├── schema/                    # Per-type schemas
│       ├── client-info.ts             # Client identification
│       └── connect-error-details.ts   # Error codes
└── config/openclaw.json               # Harvis instance config
```

## File Organization Principles

### 1. Single Custom Element

All application logic lives in `<openclaw-app>` (`ui/src/ui/app.ts`). The component has ~100 `@state()` properties that represent the entire application state. There is no component tree — just one element with a single render function.

### 2. Controller Pattern

Side effects (API calls, WebSocket mutations) are in `controllers/`. Each controller file handles a domain:

```typescript
// controllers/chat.ts — example pattern
export async function loadChatHistory(state: ChatState) {
  const res = await state.client.request("chat.history", { sessionKey, limit: 200 });
  state.chatMessages = res.messages ?? [];
}

export async function handleSendChat(state: ChatState, message: string) {
  await state.client.request("chat.send", { sessionKey, text: message });
}
```

Controllers receive the state object and mutate it directly. No return values needed for state changes.

### 3. Pure View Functions

Views (`views/`) are pure Lit `html` template functions that receive props:

```typescript
// views/chat.ts
export function renderChat(props: ChatProps) {
  return html`<div class="chat">
    ${renderMessageList(props)}
    ${renderInput(props)}
  </div>`;
}
```

Views never make API calls — they receive all data via props from `app-render.ts`.

### 4. Render Function as Central Orchestrator

`app-render.ts` (1141 lines) is the single render function that:
- Receives the full `AppViewState` (merged from `app.ts`)
- Renders the shell layout (topbar, nav, content area)
- Conditionally renders each tab's view
- Passes props to each view including event handlers

### 5. Event-Driven State Updates

`app-gateway.ts` routes WebSocket events to the appropriate handler:

```typescript
function handleGatewayEventUnsafe(host, evt) {
  if (evt.event === "chat") handleChatGatewayEvent(host, evt.payload);
  if (evt.event === "agent") handleAgentEvent(host, evt.payload);
  if (evt.event === "presence") host.presenceEntries = evt.payload.presence;
  // ... etc
}
```

## Key File Roles

### Core Files

| File | Purpose | LOC |
|------|---------|-----|
| `ui/src/ui/app.ts` | Main component — all state | 616 |
| `ui/src/ui/app-render.ts` | Single render function — all views | 1141 |
| `ui/src/ui/gateway.ts` | WebSocket client class | 360 |
| `ui/src/ui/app-gateway.ts` | Connection lifecycle + event routing | 349 |
| `ui/src/ui/types.ts` | All API response types | 640 |
| `ui/src/ui/navigation.ts` | Tab/route definitions | 165 |
| `ui/src/ui/app-chat.ts` | Chat send/receive logic | ~250 |
| `ui/src/ui/app-tool-stream.ts` | Tool call streaming | 455 |
| `ui/src/ui/storage.ts` | Settings persistence | 91 |
| `ui/src/ui/views/config.ts` | Config editor | 820 |
| `ui/src/ui/views/chat.ts` | Chat view | 616 |

### Controller Files (29 total)

| File | Domain |
|------|--------|
| `controllers/agents.ts` | agents.list, tools.catalog |
| `controllers/agent-files.ts` | agents.files CRUD |
| `controllers/agent-identity.ts` | agents.identity |
| `controllers/agent-skills.ts` | Agent skills |
| `controllers/chat.ts` | chat.send, chat.history, chat events |
| `controllers/config.ts` | config.get/set/patch/apply/schema |
| `controllers/cron.ts` | cron CRUD + runs |
| `controllers/debug.ts` | Debug method caller |
| `controllers/devices.ts` | Device pairing |
| `controllers/exec-approval.ts` | Exec approval queue |
| `controllers/exec-approvals.ts` | Exec approvals CRUD |
| `controllers/logs.ts` | logs.tail |
| `controllers/nodes.ts` | nodes CRUD |
| `controllers/presence.ts` | Presence polling |
| `controllers/sessions.ts` | sessions CRUD |
| `controllers/skills.ts` | skills CRUD |
| `controllers/usage.ts` | Usage analytics |
| `controllers/channels.ts` | channels.status |
| `controllers/assistant-identity.ts` | Assistant identity |
| `controllers/control-ui-bootstrap.ts` | Bootstrap config |

### View Files (15+ total)

| File | Tab |
|------|-----|
| `views/chat.ts` | chat |
| `views/overview.ts` | overview |
| `views/channels.ts` | channels |
| `views/instances.ts` | instances |
| `views/sessions.ts` | sessions |
| `views/usage.ts` | usage |
| `views/cron.ts` | cron |
| `views/agents.ts` | agents |
| `views/skills.ts` | skills |
| `views/nodes.ts` | nodes |
| `views/config.ts` | config |
| `views/debug.ts` | debug |
| `views/logs.ts` | logs |
| `views/exec-approval.ts` | exec approval modal |
| `views/markdown-sidebar.ts` | tool output sidebar |

### Chat Subsystem

| File | Purpose |
|------|---------|
| `chat/grouped-render.ts` | Message group rendering |
| `chat/message-normalizer.ts` | Normalize API messages |
| `chat/message-extract.ts` | Extract text from messages |
| `chat/tool-cards.ts` | Tool call card rendering |
| `chat/tool-helpers.ts` | Tool display helpers |
| `chat/constants.ts` | Chat constants |
| `chat/copy-as-markdown.ts` | Copy messages as markdown |

## Dependency Graph

```
app.ts
├── app-render.ts          # render() function
│   ├── views/*.ts         # All view render functions
│   ├── app-render.helpers.ts
│   ├── app-render-usage-tab.ts
│   └── navigation.ts
├── app-gateway.ts         # WebSocket connection
│   ├── gateway.ts         # GatewayBrowserClient
│   ├── app-chat.ts        # Chat event handling
│   ├── app-tool-stream.ts # Agent event handling
│   ├── app-settings.ts    # Settings persistence
│   ├── controllers/*      # API call functions
│   └── device-auth.ts
├── app-lifecycle.ts       # Lifecycle hooks
├── app-settings.ts        # Tab/theme/settings
├── app-scroll.ts          # Scroll handling
├── app-channels.ts        # Channel handlers
├── storage.ts             # localStorage
├── theme.ts               # Theme resolution
└── i18n/index.ts          # Internationalization
```

## Build Output

```
openclaw/
├── ui/                    # Source
└── dist/control-ui/       # Build output (served by gateway)
    ├── index.html
    ├── assets/*.js        # Bundled JavaScript
    ├── assets/*.css       # Bundled CSS
    ├── favicon.svg
    └── ...
```

Build command: `pnpm ui:build` (outputs to `dist/control-ui/`)
Dev command: `pnpm ui:dev` (Vite dev server on port 5173)

## Where to Add New Code

### New Tab/View
1. Add tab to `navigation.ts` → `TAB_GROUPS` and `Tab` type
2. Add path mapping to `TAB_PATHS`
3. Add `@state()` properties to `app.ts`
4. Create `views/new-tab.ts` with render function
5. Add conditional render in `app-render.ts`
6. Create controller in `controllers/new-tab.ts` for API calls
7. Add handlers in `app-gateway.ts` for WebSocket events
8. Add methods to `server-methods.ts` and `server-methods/new-tab.ts` on backend
9. Add schema validation to `protocol/schema.ts`

### New API Method
1. Add schema to `protocol/schema.ts` (or `protocol/schema/*.ts`)
2. Add validator to `protocol/index.ts`
3. Create handler in `src/gateway/server-methods/new-method.ts`
4. Register in `src/gateway/server-methods.ts`
5. Add client method call in `controllers/new-tab.ts`
6. Add response type in `ui/src/ui/types.ts`

### New WebSocket Event
1. Add event type to `protocol/schema.ts`
2. Add handler in `app-gateway.ts` → `handleGatewayEventUnsafe()`
3. Add state properties to `app.ts` if needed
4. Add event type to `GatewayEventFrame` in `gateway.ts`

### New CSS
1. Add to `ui/src/styles.css` or create new file in `ui/src/styles/`
2. Use BEM-like naming: `.block__element--modifier`
