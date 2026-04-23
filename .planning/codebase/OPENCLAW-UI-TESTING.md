# OpenClaw Gateway UI — Testing Patterns

**Analysis Date:** 2026-04-21

## Test Framework

**Runner:**
- **Vitest** 4.0.18 — Primary test runner
- Config: `ui/vitest.config.ts` (browser tests), `ui/vitest.node.config.ts` (node tests)

**Assertion Library:**
- Vitest built-in assertions (`expect`, `vi.mock`, `vi.fn`)

**Run Commands:**
```bash
cd ui
pnpm test              # Run all tests
pnpm test -- --watch   # Watch mode
```

## Test File Organization

**Location:**
- Colocated with source files
- Same directory as the module being tested

**Naming:**
- `*.test.ts` — Standard test files
- `*.browser.test.ts` — Browser tests (Playwright-based)
- `*.node.test.ts` — Node.js tests (Vitest node environment)

**Directory pattern:**
```
ui/src/ui/
├── app.test.ts              # (if exists)
├── app-scroll.test.ts       # Scroll tests
├── app-gateway.node.test.ts # Gateway tests (node env)
├── app-tool-stream.node.test.ts
├── app-render.helpers.node.test.ts
├── app-settings.test.ts
├── chat.test.ts             # Chat view tests
├── chat-event-reload.test.ts
├── config-form.browser.test.ts  # Config form browser tests
├── markdown.test.ts
├── navigation.test.ts
├── navigation.browser.test.ts
├── usage-helpers.node.test.ts
├── uuid.test.ts
├── format.test.ts
├── text-direction.test.ts
├── focus-mode.browser.test.ts
├── controllers/
│   ├── agents.test.ts
│   ├── chat.test.ts
│   ├── config.test.ts
│   ├── sessions.test.ts
│   └── cron.test.ts
├── views/
│   ├── sessions.test.ts
│   ├── cron.test.ts
│   ├── config-search.node.test.ts
│   ├── config-form.search.node.test.ts
│   ├── overview.node.test.ts
│   └── usage-render-details.test.ts
├── chat/
│   ├── message-extract.test.ts
│   ├── message-normalizer.test.ts
│   ├── tool-helpers.test.ts
│   └── usage.test.ts
└── __screenshots__/         # Visual regression test screenshots
```

## Test Structure

**Suite Organization:**
```typescript
import { expect, test, vi } from "vitest";
import { someFunction } from "./some-module.ts";

test("describes behavior", () => {
  const result = someFunction(input);
  expect(result).toBe(expected);
});

test("handles edge case", () => {
  vi.spyOn(SomeClass, "method").mockReturnValue(mockValue);
  // ...
});
```

**Patterns:**
- Test files use `vitest` imports (`expect`, `test`, `vi`)
- Browser tests use Playwright for DOM interaction
- Node tests use Vitest's node environment for file system and network tests

## Mocking

**Framework:** Vitest's built-in mocking (`vi.fn()`, `vi.mock()`, `vi.spyOn()`)

**Patterns:**
```typescript
// Mock a function
vi.spyOn(someObject, "method").mockResolvedValue(mockData);

// Mock a module
vi.mock("./some-module.ts", () => ({
  someFunction: vi.fn(() => mockResult),
}));

// Mock WebSocket
const mockWebSocket = {
  send: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  close: vi.fn(),
  readyState: WebSocket.OPEN,
};
```

**What to Mock:**
- WebSocket connections (use mock client)
- File system operations (in node tests)
- External API calls
- `crypto.subtle` for device identity tests

**What NOT to Mock:**
- Core business logic (normalize, format, validate)
- Type guards and type checks
- Simple utility functions with pure behavior

## Fixtures and Factories

**Test Data:**
```typescript
// Inline fixtures in test files
const mockAgentsList: AgentsListResult = {
  defaultId: "main",
  mainKey: "main",
  scope: "per-sender",
  agents: [{ id: "main", name: "Main Agent" }],
};

const mockChatMessage = {
  role: "assistant",
  content: [{ type: "text", text: "Hello!" }],
};
```

**Location:**
- Inline in test files (no separate fixture files)
- Shared via `test-helpers/` directory for complex setups

## Coverage

**Requirements:**
- No enforced coverage threshold in the UI package
- Coverage is tracked at the parent project level (`src/gateway/` has 70% thresholds)

**View Coverage:**
```bash
cd ui
npx vitest run --coverage
```

## Test Types

### Unit Tests (Node Environment)

**Scope:** Pure functions, data transformations, type validation

**Examples:**
- `format.test.ts` — Text/date formatting
- `uuid.test.ts` — UUID generation
- `markdown.test.ts` — Markdown rendering
- `text-direction.test.ts` — RTL/LTR detection
- `message-extract.test.ts` — Text extraction from messages
- `message-normalizer.test.ts` — Message normalization
- `tool-helpers.test.ts` — Tool display helpers
- `config-form.search.node.test.ts` — Config search indexing

**Pattern:**
```typescript
import { expect, test } from "vitest";
import { normalizeMessage } from "./message-normalizer.ts";

test("normalizes assistant message", () => {
  const input = { role: "assistant", content: [{ type: "text", text: "hi" }] };
  const result = normalizeMessage(input);
  expect(result.role).toBe("assistant");
  expect(result.content[0].type).toBe("text");
});
```

### Browser Tests (Playwright)

**Scope:** DOM interaction, component rendering, user flows

**Examples:**
- `navigation.browser.test.ts` — Tab navigation
- `focus-mode.browser.test.ts` — Chat focus mode
- `config-form.browser.test.ts` — Config form interaction
- `app-scroll.test.ts` — Chat scroll behavior (browser)

**Pattern:**
```typescript
import { test, expect } from "@vitest/browser/playwright";

test("navigates to agents tab", async ({ page }) => {
  await page.goto("/");
  await page.click('[data-tab="agents"]');
  await expect(page.locator(".agents-view")).toBeVisible();
});
```

### Visual Regression Tests

**Scope:** UI rendering consistency

**Location:** `ui/src/ui/__screenshots__/`

**Pattern:**
- Screenshot captured during browser tests
- Compared against baseline screenshots
- Failures indicate unintended visual changes

## Common Patterns

### WebSocket Client Testing

```typescript
import { GatewayBrowserClient } from "./gateway.ts";

test("handles connect challenge", async () => {
  const client = new GatewayBrowserClient({
    url: "ws://localhost:18789",
    onHello: vi.fn(),
    onEvent: vi.fn(),
    onClose: vi.fn(),
  });
  // Simulate WebSocket messages
  // Assert client state
});
```

### Chat Event Testing

```typescript
import { handleChatEvent } from "./controllers/chat.ts";

test("handles delta event", () => {
  const state = createMockState();
  const payload = { runId: "1", state: "delta", message: { text: "Hello" } };
  const result = handleChatEvent(state, payload);
  expect(result).toBe("delta");
  expect(state.chatStream).toBe("Hello");
});
```

### Config Form Testing

```typescript
import { analyzeConfigSchema } from "./views/config-form.ts";

test("analyzes schema sections", () => {
  const schema = {
    type: "object",
    properties: {
      gateway: { type: "object", properties: { port: { type: "number" } } },
    },
  };
  const sections = analyzeConfigSchema(schema);
  expect(sections).toHaveLength(1);
});
```

### Controller Testing

```typescript
import { loadAgents } from "./controllers/agents.ts";

test("loads agents list", async () => {
  const mockClient = {
    request: vi.fn().mockResolvedValue({ agents: [{ id: "main" }] }),
  };
  const state = { client: mockClient, connected: true, agentsLoading: false };
  await loadAgents(state as unknown as OpenClawApp);
  expect(state.agentsLoading).toBe(false);
  expect(mockClient.request).toHaveBeenCalledWith("agents.list");
});
```

## Test Helpers

**Location:** `ui/src/ui/test-helpers/`

**Purpose:** Shared utilities for test setup:
- Mock state creation
- WebSocket mock factories
- DOM setup utilities
- Fixture data generators

## Testing the Gateway Server

The gateway server (`src/gateway/`) has its own test suite with higher coverage requirements:

```bash
# Gateway tests
pnpm test                    # All tests
pnpm test:coverage           # With coverage
pnpm test:live               # Live tests (real keys)
pnpm test:docker:onboard     # Docker onboarding tests
```

**Test categories:**
- `*.test.ts` — Unit tests
- `*.live.test.ts` — Live integration tests
- `*.e2e.test.ts` — End-to-end tests
- `*.node.test.ts` — Node-specific tests
- `*.browser.test.ts` — Browser tests

**Coverage thresholds:**
- 70% lines, branches, functions, statements
- Enforced via Vitest V8 provider
