# Harvis Global Integrations — Plug-and-Play Capability Layer

**Handoff date:** 2026-06-26  
**Branch context:** `harvis1.1` (OWUI frontend at `front_end/owui/`, Python backend at `python_back_end/`)  
**Build target for this handoff:** **Phase A only** (catalog alignment + UI). Phases B–D are documented for continuity — do not implement them in this pass unless explicitly requested.

---

## 1. Product vision (one paragraph)

Harvis Integrations must become a **global plug-and-play capability layer**, not a Code-mode engine picker. Integrations belong to Harvis globally; Chat, Code, Notebook, Agent Studio, Automations, and future surfaces **consume** them by capability (e.g. `model_provider`, `agent_runtime`, `code_engine`). A new user should eventually be able to boot Harvis, detect/import their existing stack (OpenClaw, Ollama, MCP, GitHub, OpenCode, etc.), and have Harvis route work through it. **Today** Harvis already has scattered pieces of this (OpenClaw runtime, Ollama, GitHub OAuth, MCP registry, status probes, Integrations UI). **Do not build a greenfield integration system.** Wrap what exists into a cleaner global model, starting with Phase A (visible architecture, no runtime changes).

---

## 2. Mental model

```txt
Models are brains.
Applications are engines / work surfaces.
Services are connections.
Packs are recipes.
Harvis is the control plane.
```

```txt
Integration Catalog   → What can Harvis connect to? (static metadata)
Integration Detectors → What does the user already have? (safe probes)
Integration Profiles  → How should Harvis use it for this user? (saved config)
Capability Registry   → Which integrations provide ability X right now?
Harvis Consumers      → Chat, Code, Notebook, Agent Studio, Automations
Adapters              → Runtime translators that actually execute work (later)
```

**Capability-first. Engine second. Adapter third.**

Consumers should eventually ask: *"Give me ready integrations with capability `code_engine` for surface `code`."* They do **not** do that yet — Phase A only updates the Integrations page data model and UI.

---

## 3. What already exists (DO NOT REWRITE)

| System | Location | What it does |
|--------|----------|--------------|
| **Integrations catalog (frontend)** | `front_end/owui/src/lib/integrations/catalog.ts` | Static `CATALOG`, `mergeLiveStatus()`, `actionsFor()` |
| **Integrations page** | `front_end/owui/src/routes/(app)/harvis/integrations/+page.svelte` | Cards, rows, modal, Rescan |
| **UI components** | `IntegrationCard.svelte`, `IntegrationRow.svelte`, `IntegrationDetailModal.svelte`, `BrandGlyph.svelte`, `StatusBadge.svelte`, `CommandBlock.svelte` | |
| **Logos** | `front_end/owui/static/integrations/*.svg` | Vendored brand SVGs |
| **Status API** | `python_back_end/owui_compat/integrations_status.py` | `GET /api/owui/integrations/status` |
| **API client** | `front_end/owui/src/lib/apis/integrations/index.ts` | Fetches status |
| **OpenClaw runtime** | `workspace/openclaw_client.py`, `workspace_router.py`, `owui_compat/workspace_bridge.py`, `openclaw_resolver.py` | Chat/Code agent execution; BYO via `user_openclaw_config` |
| **Ollama** | `workspace/model_proxy.py`, Cookbook routes | Local models |
| **GitHub** | `vibecoding/auth_github.py`, `github_tokens` table | OAuth, VibeCode repos/PRs |
| **MCP registry** | `owui_compat/connections.py`, `mcp_servers` table, `Customize.svelte` | CRUD per user; **runtime wiring to OpenClaw deferred** |
| **Discord** | `integrations/discord_workspace_bot.py` | Bot; env `DISCORD_BOT_TOKEN` |
| **OpenCode LLM proxy** | `tools/opencode_llm_proxy.py` | `/api/opencode/chat` — NOT a code-engine adapter |

**OpenClaw is the only integration with a full end-to-end runtime path today.**

---

## 4. Phased roadmap

### Phase A — Catalog alignment (**BUILD NOW**)

- Add typed `IntegrationCapability` and `HarvisSurface` to catalog
- Add `usedBy` on every catalog entry
- Add `source` state: `static` | `detected` | `imported` | `configured` (derived in UI; `imported` only when profile exists — not in A unless heuristic)
- Add `runtimeState` / honest notes (e.g. MCP: registered, agent wiring planned)
- Update `IntegrationCard`, `IntegrationRow`, `IntegrationDetailModal` to show capabilities, used-by, source line
- Replace Code-only `save_for_code` with generic `save_preference` (localStorage, capability-scoped)
- **No** backend runtime changes
- **No** new `python_back_end/integrations/` package
- **No** consumer rewiring (Chat, Code, Notebook, Agent Studio, Automations unchanged)

### Phase B — Profiles + import (later)

- Server-side integration profiles (unify `user_openclaw_config`, `github_tokens`, `mcp_servers` under one model)
- `POST /api/owui/integrations/{id}/import`
- `PATCH /api/owui/integrations/{id}/profile`
- Import = detect + save non-secret config; never auto-import secrets

### Phase C — Capability registry (later)

- `GET /api/owui/capabilities?capability=code_engine&surface=code`
- Frontend `capabilities.ts` query helpers
- First consumer: VibeCode engine picker reads registry

### Phase D — Adapters (later)

- OpenClaw BYO polished UX on Integrations page
- OpenCode as first external `code_engine` adapter
- Hermes only if a real agent service exists (today = Ollama model family only)
- Claude Code / Codex spikes only when headless path proven

---

## 5. Integration capability mapping (authoritative)

Use this table when updating `catalog.ts`:

| Catalog `id` | `capabilities` | `usedBy` | Runtime honesty |
|--------------|------------------|----------|-----------------|
| `ollama` | `model_provider` | `chat`, `code`, `notebook`, `agent_studio` | Live if status probe ready |
| `openclaw` | `agent_runtime`, `tool_runtime`, `code_engine_candidate` | `chat`, `code`, `agent_studio` | **Live** — primary runtime; BYO in workspace settings |
| `github` | `repo_provider`, `pr_provider` | `code`, `automations`, `agent_studio` | Live when `github_tokens` row exists |
| `mcp` | `tool_provider` | `chat`, `agent_studio`, `automations` | Registered only; **agent runtime wiring planned** |
| `discord` | `notification_provider` | `automations` | Deploy-level env var |
| `opencode` | `code_engine_candidate` | `code` | **Not runnable** as engine yet |
| `claude-code` | `code_engine_candidate` | `code` | **Planned** external engine |
| `codex-app` | `code_engine_candidate` | `code` | **Planned** external engine |
| `hermes-agent` | `model_provider` | `chat`, `code`, `notebook`, `agent_studio` | Hermes **models** via Ollama — not a separate agent daemon |
| `ssh` | `remote_execution_target` | `code` | **Planned** |
| `pack-local-coder` | (recipe — derive from members) | `code` | Recipe only |
| `pack-repo-review` | (recipe — derive from members) | `code`, `agent_studio` | Recipe only |

**Harvis CLI** (hero on integrations page, not in `CATALOG` today):
- `local_execution_bridge`
- `usedBy`: `code`, `agent_studio`, `automations`
- Status: `coming_soon`

Optional: add `harvis-cli` catalog entry or keep hero-only.

---

## 6. Type definitions (Phase A)

Add to `front_end/owui/src/lib/integrations/` (new `types.ts` or extend `catalog.ts`):

```ts
export type IntegrationCapability =
  | 'model_provider'
  | 'tool_provider'
  | 'agent_runtime'
  | 'tool_runtime'
  | 'workflow_runtime'
  | 'code_engine_candidate'
  | 'repo_provider'
  | 'pr_provider'
  | 'notification_provider'
  | 'remote_execution_target'
  | 'local_execution_bridge'
  | 'document_provider'
  | 'research_runtime';

export type HarvisSurface =
  | 'chat'
  | 'code'
  | 'notebook'
  | 'agent_studio'
  | 'automations';

export type IntegrationSource =
  | 'static'      // catalog baseline only
  | 'detected'    // live probe succeeded
  | 'configured'  // user/server has real config (GitHub token, MCP rows, OpenClaw BYO)
  | 'imported';   // explicit import profile (Phase B — omit or don't show in A)

export interface IntegrationDefinition {
  // ... existing fields ...
  capabilities: IntegrationCapability[];  // replace informal string[]
  usedBy: HarvisSurface[];
  runtimeNote?: string;  // honest state, e.g. MCP wiring planned
  // runtime-derived (set by mergeLiveStatus or deriveSource()):
  source?: IntegrationSource;
}
```

Add `capabilities.ts` with:
- `CAPABILITY_LABEL: Record<IntegrationCapability, string>` — human labels ("Models", "Agent runtime", …)
- `SURFACE_LABEL: Record<HarvisSurface, string>` — ("Chat", "Code", …)
- `formatSourceLine(def)` — e.g. "Ready · Detected · 12 models"
- `deriveSource(def, live)` — logic per integration id

---

## 7. Source derivation rules (Phase A, frontend-only)

| Integration | `configured` when | `detected` when | Default |
|-------------|-------------------|-----------------|---------|
| Ollama | — | status `ready` from probe | `static` |
| OpenClaw | user has BYO verified (optional: skip in A, use detect only) | status `ready` | `static` |
| GitHub | status `ready` ("Connected") | — | `needs_setup` → static |
| MCP | enabled server count > 0 | — | `available` → static; show runtimeNote |
| Hermes | — | hermes models in probe | `static` |
| Discord | env probe ready | — | `static` |
| OpenCode, Claude, Codex, SSH | — | — | `static` + planned copy |

Do **not** show `imported` until Phase B.

---

## 8. UI changes (Phase A)

### IntegrationCard + IntegrationRow

Below description, add:
1. **Capability chips** — use `CAPABILITY_LABEL` (max ~3 on card, "+N" overflow ok)
2. **Used by** — compact: `Chat · Code · Agent Studio`
3. **Source line** — e.g. `Ready · Detected` or `Connected · Configured` (combine with existing `StatusBadge` + `detail`)

### IntegrationDetailModal

Add sections (before or after engine support):
- **Capabilities** — typed chips with labels
- **Used by** — list surfaces with `SURFACE_LABEL`
- **Runtime** — `runtimeNote` if set; for MCP always show agent wiring planned
- Demote **Engine support** block to only show when `code_engine_candidate` in capabilities

Update page subtitle to reflect global framing:
> "Harvis integrations power Chat, Code, agents, and automations from one place."

### Actions — replace Code-only framing

In `catalog.ts`:
- Change `ActionKind`: `'save_for_code'` → `'save_preference'`
- Change label: `Save preference` (not `Save for Code`)
- Tooltip: capability-scoped, e.g. "Save as your preferred code engine (preference only — routing coming later)"

In `+page.svelte` handler:
```ts
// Old: localStorage.setItem('harvis.code.defaultApp', def.id);
// New:
const cap = def.capabilities.includes('code_engine_candidate') ? 'code_engine' : def.capabilities[0];
localStorage.setItem(`harvis.integrations.preferences.${cap}`, def.id);
// Optional: migrate read of harvis.code.defaultApp on load for backwards compat
```

Only show `save_preference` on entries that have a saveable capability (applications with `code_engine_candidate`, not services).

### Harvis CLI hero

Align copy with mapping:
- Capabilities: Local execution bridge
- Used by: Code, Agents, Automations

---

## 9. Backend (Phase A)

**Default: no backend changes required.**

Optional small enhancement (only if trivial):
- Extend `integrations_status.py` to return `configured: boolean` per service key (github has token, mcp count > 0). Frontend uses it for `source` derivation.

Do **not**:
- Create `python_back_end/integrations/` package
- Duplicate OpenClaw/GitHub/MCP/Ollama logic
- Add import/test endpoints
- Execute catalog commands server-side

---

## 10. Security rules (always)

- No arbitrary command execution from catalog
- No secret values in status API or UI
- Commands in catalog are **copy-only** (already enforced)
- Fail closed on probes (already enforced)
- Do not claim Claude Code/Codex/OpenCode engines work before adapters exist
- MCP: honest "registered" vs "active in agents"

---

## 11. Files to modify (Phase A)

```
front_end/owui/src/lib/integrations/
  catalog.ts              — types, mapping table, mergeLiveStatus + deriveSource, actionsFor
  capabilities.ts         — NEW: labels + helpers
  IntegrationCard.svelte  — capabilities, usedBy, source line
  IntegrationRow.svelte   — same (compact)
  IntegrationDetailModal.svelte — full sections, runtime honesty

front_end/owui/src/routes/(app)/harvis/integrations/+page.svelte
  — save_preference handler, optional subtitle

front_end/jfrontend/changes.md — document per project rules (timestamp, problem, solution, files)
```

**Do not modify** in Phase A:
- `python_back_end/workspace/*` (except optional status tweak)
- VibeCode, Chat, Agent Studio, Automations routes
- `harvis.code.defaultApp` consumers in vibecode (leave until Phase C)

---

## 12. Verification checklist

- [ ] `/harvis/integrations` loads
- [ ] Every catalog entry has typed `capabilities` and `usedBy`
- [ ] Cards and modal show capabilities + used-by + source/status
- [ ] Ollama status still works (model count in detail)
- [ ] OpenClaw status still works when gateway reachable
- [ ] GitHub/MCP/Discord status unchanged
- [ ] MCP shows honest "runtime wiring planned" (or equivalent)
- [ ] Claude Code, Codex, OpenCode show planned/candidate — not "active engine"
- [ ] Harvis CLI hero shows coming soon + local_execution_bridge framing
- [ ] No secrets displayed
- [ ] No commands executed server-side
- [ ] `Save preference` replaces `Save for Code`; no Code-only framing in UI copy
- [ ] `npm run build` passes in `front_end/owui`
- [ ] No git push until reviewed

---

## 13. Future phases (reference only)

### Phase B — Profiles + import

User journey: *"I already run OpenClaw at ws://my-host:18789 → Import → Chat/Code use my gateway."*

- Unify existing stores into integration profiles
- Import flow on Integrations page
- OpenClaw BYO moved from buried workspace settings to Integrations Import/Manage

### Phase C — Registry + consumers

- `GET /api/owui/capabilities`
- VibeCode reads `code_engine` from registry
- Chat model/tool sections optionally split by capability

### Phase D — Adapters

Adapter contract (future): detect, test, configure, start session, run task, stream events, stop, collect artifacts/diff, cleanup.

External engines start in **isolated clone/session workspaces**, not directly on real repos.

Priority adapters: OpenClaw (formalize), OpenCode (proxy exists), then Hermes only if real service.

---

## 14. Product sentence

```txt
Catalog tells Harvis what exists.
Detectors find what the user already has.
Profiles save how the user wants to use it.
Capabilities expose it across the site.
Adapters make it runnable later.
```

Phase A makes the first two lines **visible and honest** on the Integrations page. Plug-and-play execution for bring-your-own-engine users requires Phases B–D.

---

## 15. Build instructions for Claude

1. Read existing files listed in §3 before editing.
2. Implement **Phase A only** per §5–§11.
3. Use the capability mapping table as source of truth — replace informal `capabilities: ['coding', 'tool_use', …]`.
4. Keep runtime behavior unchanged.
5. Run `npm run build` in `front_end/owui`.
6. Update `front_end/jfrontend/changes.md`.
7. Do not commit unless user asks.
