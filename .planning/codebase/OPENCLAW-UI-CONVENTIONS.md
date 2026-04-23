# OpenClaw Gateway UI — Coding Conventions

**Analysis Date:** 2026-04-21

## Naming Patterns

**Files:**
- `snake_case` for most files: `app-render.ts`, `app-gateway.ts`, `app-view-state.ts`
- `kebab-case` for view files: `chat.ts`, `config.ts`, `channels.ts`
- Test files: `*.test.ts` (same name as source, e.g., `agents.test.ts`)
- Browser test files: `*.browser.test.ts` (e.g., `chat.test.ts`)
- Node test files: `*.node.test.ts` (e.g., `app-gateway.node.test.ts`)

**Functions:**
- `camelCase` for all functions: `handleChatEvent`, `loadChatHistory`, `renderApp`
- Handler functions prefixed with `handle`: `handleGatewayEvent`, `handleSendChat`
- Load functions prefixed with `load`: `loadAgents`, `loadConfig`, `loadSessions`
- Render functions prefixed with `render`: `renderChat`, `renderConfig`, `renderApp`
- Update functions prefixed with `update`: `updateConfigFormValue`, `updateSkillEdit`

**Variables:**
- `camelCase` for local variables: `chatMessages`, `sessionKey`, `configForm`
- `const` for constants: `TOOL_STREAM_LIMIT`, `TOOL_STREAM_THROTTLE_MS`
- `PascalCase` for types and interfaces

**Types:**
- `PascalCase` for all types: `UiSettings`, `AppViewState`, `ChatProps`, `ToolStreamEntry`
- Props types suffixed with `Props`: `ChatProps`, `ConfigProps`, `CronProps`
- Result types suffixed with `Result`: `AgentsListResult`, `SessionsListResult`
- State types suffixed with `State`: `CronFormState`
- Type aliases with `type` keyword

## Code Style

**Formatting:**
- **Oxfmt** — Rust-style formatter (used by the parent OpenClaw project)
- Run: `pnpm format` (check), `pnpm format:fix` (auto-fix)
- 2-space indentation
- Semicolons required
- Single quotes for strings

**Linting:**
- **Oxlint** — Fast Rust-based linter
- Run: `pnpm check` (lint + format check)
- No `@ts-nocheck` allowed
- No `any` type — fix root causes

**TypeScript:**
- ESM modules (`"type": "module"`)
- Strict mode enabled
- Import `.js` extension for local imports (TypeScript ESM convention)
- Explicit return types on public functions

## Import Organization

**Order:**
1. Node.js built-ins (`node:path`, `node:url`)
2. External dependencies (`lit`, `lit/directives/repeat.js`)
3. Local imports (relative paths)
   - Sibling files: `../gateway.ts`
   - Parent directory: `../../i18n/index.ts`
   - Child directory: `./chat/grouped-render.ts`
   - Sub-module: `./types/chat-types.ts`

**Path Aliases:**
- No path aliases configured. All imports use relative paths.

**Import conventions:**
```typescript
// External first
import { html, nothing } from "lit";
import { ref } from "lit/directives/ref.js";

// Then local
import { t } from "../i18n/index.ts";
import type { AppViewState } from "./app-view-state.ts";
import { renderChat } from "./views/chat.ts";

// Type-only imports
import type { ChatProps, MessageGroup } from "./types/chat-types.ts";
```

## Error Handling

**Patterns:**
- **Try/catch** for async operations:
```typescript
try {
  const res = await state.client.request("chat.history", { sessionKey });
  state.chatMessages = Array.isArray(res.messages) ? res.messages : [];
} catch (err) {
  state.lastError = String(err);
} finally {
  state.chatLoading = false;
}
```

- **Error propagation** via state properties:
```typescript
@state() lastError: string | null = null;
@state() lastErrorCode: string | null = null;
@state() channelsError: string | null = null;
```

- **GatewayRequestError** for RPC failures:
```typescript
export class GatewayRequestError extends Error {
  readonly gatewayCode: string;
  readonly details?: unknown;
}
```

- **Null checks** everywhere for API responses

## Logging

**Framework:** `console.error()` for client-side errors

**Patterns:**
```typescript
console.error("[gateway] event handler error:", err);
console.error("[gateway] handleGatewayEvent error:", evt.event, err);
```

- Prefixed with `[gateway]` for easy filtering
- No debug logging in production code
- Error messages include context (event name, error details)

## Comments

**When to Comment:**
- Brief comments for tricky or non-obvious logic only
- No comments for obvious code
- Document the "why", not the "what"

**TSDoc:**
- Not used extensively
- Some JSDoc for type exports: `/** Chat message types for the UI layer */`

## Function Design

**Size:**
- Aim for <100 LOC per function
- Extract helpers for complex logic (e.g., `resolveAssistantAvatarUrl`)
- View render functions can be large (600-1100 LOC) because they're mostly templates

**Parameters:**
- Props objects for view functions: `renderChat({ sessionKey, onSend, ... })`
- State object for controllers: `loadAgents(state: OpenClawApp)`
- Minimal parameters otherwise

**Return Values:**
- Controllers: `void` (mutate state directly) or `Promise<void>`
- View functions: Lit `TemplateResult`
- Utility functions: typed return values

## Module Design

**Exports:**
- Named exports preferred
- Type exports: `export type { ChatProps }`
- One default export per file (the component or main class)

**Barrel Files:**
- None detected. Each module exports directly.

## Architecture Conventions

### Controller Pattern

Controllers are pure functions that take a state object and mutate it:

```typescript
// controllers/agents.ts
export async function loadAgents(state: OpenClawApp) {
  if (!state.client || !state.connected) return;
  state.agentsLoading = true;
  try {
    const res = await state.client.request("agents.list");
    state.agentsList = res as AgentsListResult;
  } catch (err) {
    state.agentsError = String(err);
  } finally {
    state.agentsLoading = false;
  }
}
```

**Rules:**
- Controllers receive the full state object (not just a slice)
- Controllers mutate state directly (no return values for state changes)
- Controllers are async — use try/catch/finally
- Controllers are imported and called from `app-gateway.ts` or `app-render.ts`

### View Pattern

Views are pure render functions:

```typescript
// views/chat.ts
export function renderChat(props: ChatProps) {
  return html`<div class="chat">...</div>`;
}
```

**Rules:**
- Views never make API calls
- Views receive all data via props
- Views are pure — same input always produces same output
- Views use Lit `html` template literals

### State Convention

```typescript
@state() property: Type | null = null;
@state() isLoading = false;
@state() errorMessage: string | null = null;
```

**Rules:**
- Loading states: `*Loading` suffix
- Error states: `*Error` suffix
- Result states: `*Result` or `*List` suffix
- All error states are `string | null`
