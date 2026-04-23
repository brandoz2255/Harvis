# OpenClaw Gateway UI — Technology Stack

**Analysis Date:** 2026-04-21

## Languages

**Primary:**
- **TypeScript** — All source code (`.ts` files), ESM modules, strict typing
- **CSS** — All styling (vanilla CSS, no preprocessor)
- **HTML** — SPA entry point (`index.html`)

**Secondary:**
- **JSON** — Config files, protocol schemas, tool definitions

## Runtime

**Environment:**
- **Node.js 22+** — Required for building and running the gateway server
- **Browser** — Target browsers support WebSockets, ES2022, Web Components (Lit)

**Package Manager:**
- **pnpm** — Monorepo package manager with lockfile (`pnpm-lock.yaml`)
- **Bun** — Also supported for TypeScript execution (scripts, dev, tests)

## Frameworks

**UI Framework:**
- **Lit** ^3.3.2 — Web Components library
  - `@customElement` decorator for component definition
  - `@state` decorator for reactive properties
  - `html` tagged template literal for rendering
  - `lit/directives/repeat` for list rendering
  - `lit/directives/ref` for DOM refs
  - Custom element: `<openclaw-app>` (light DOM)

**Build Tool:**
- **Vite** 7.3.1 — Development server and production bundler
  - Dev server: port 5173
  - Output: `dist/control-ui/`
  - Sourcemaps enabled
  - Configurable base path via `OPENCLAW_CONTROL_UI_BASE_PATH`

**Testing:**
- **Vitest** 4.0.18 — Test runner
  - Browser tests: Playwright-based (`@vitest/browser-playwright`)
  - Node tests: Standard Vitest
  - Separate configs: `vitest.config.ts`, `vitest.node.config.ts`

## Key Dependencies

### Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `lit` | ^3.3.2 | Web Components framework |
| `@lit-labs/signals` | ^0.2.0 | Signal-based reactive primitives |
| `@lit/context` | ^1.1.6 | Context API for Lit components |
| `marked` | ^17.0.3 | Markdown rendering |
| `dompurify` | ^3.3.1 | HTML sanitization |
| `@noble/ed25519` | 3.0.0 | Ed25519 cryptography for device auth |
| `signal-polyfill` | ^0.2.2 | Signal API polyfill |
| `signal-utils` | ^0.21.1 | Signal utilities |

### Dev Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `vite` | 7.3.1 | Build tool (also a runtime dep for dev) |
| `vitest` | 4.0.18 | Test runner |
| `@vitest/browser-playwright` | 4.0.18 | Browser test driver |
| `playwright` | ^1.58.2 | Browser automation for tests |

## Configuration

**Build Configuration:**
- `ui/vite.config.ts` — Vite config with base path support
- `ui/vitest.config.ts` — Browser test config
- `ui/vitest.node.config.ts` — Node test config
- Root: `tsconfig.json`, `vitest.config.ts`, `vitest.unit.config.ts`, etc.

**Gateway Configuration (Harvis instance):**
- `config/openclaw.json` — Main config file
  - `gateway.bind`: "lan"
  - `gateway.port`: 18789
  - `gateway.auth.mode`: "token"
  - `gateway.controlUi.enabled`: false (UI disabled in Harvis)
  - `models.providers`: harvis-proxy (OpenAI-compatible), ollama-local
  - `agents.list`: main + ollama agents
  - `mcpServers`: mempalace (SSE)

**Environment Variables:**
- `OPENCLAW_CONTROL_UI_BASE_PATH` — Base path for reverse proxy deployment
- `OPENCLAW_GATEWAY_TOKEN` — Auth token for gateway (referenced in config)

## Platform Requirements

**Development:**
- Node.js 22+
- pnpm or Bun
- Modern browser with WebSocket support
- GPU acceleration for smooth animations (chat streaming, theme transitions)

**Production:**
- Gateway runs on Linux (Docker/K8s)
- UI served as static files from gateway process
- No separate frontend server needed
- WebSocket connections from browser to gateway port (18789)

## Protocol Dependencies

**WebSocket Protocol v3** — Defined in `src/gateway/protocol/`:
- AJV (Another JSON Schema Validator) for schema validation
- Protocol schemas in `protocol/schema.ts` and `protocol/schema/*.ts`
- 60+ message types with strict validation
