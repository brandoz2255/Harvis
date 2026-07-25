# Handoff — Cookbook runtime GPU nodes + Kimi/Moonshot API-key tile (2026-07-23)

**Status:** SHIPPED + pushed to `harvis1.1-deploy-test`. Verified locally (clean backend boot,
clean owui build). Awaiting your in-app E2E (add a node, enter a Moonshot key) once booted.

**Branch:** commits landed on local `harvis1.1`, pushed to `origin/harvis1.1-deploy-test`.
`origin/harvis1.1` is **untouched** at `bcd6005e`.

## Commits

| SHA | Item | What |
|-----|------|------|
| `c59f7080` | **B** | Cookbook: add/remove GPU inference nodes at runtime via the "+" button |
| `f29a6646` | **A + C** | Integrations: Kimi/Moonshot API-key tile + fix silent `authEngine` routing |

deploy-test tip after push: `f29a6646`.

## What changed (9 files)

### Item B — Cookbook "+" add-a-GPU-node (the headline ask)

Users register another GPU box (running `llmfit serve` on :8787) as an inference node straight from
the Cookbook model-selector — the same manual multi-GPU wiring, now a button.

- **`python_back_end/cookbook/config.py`** — DB-backed `cookbook_nodes` table (name PK, role,
  llmfit_url, ollama_url, created_at). `NODES` stays a **plain dict** so every existing synchronous
  reader is unchanged. Baseline env nodes always win over persisted rows (can't shadow `main-host`).
  `load_persisted_nodes(pool)` merges DB rows at startup and never raises. Also
  `register_node` / `unregister_node` / `persist_node` / `delete_persisted_node` / `is_baseline`.
- **`python_back_end/cookbook/router.py`** — admin-gated `POST /api/cookbook/nodes` (name regex
  validation, rejects baseline names, probes llmfit reachability → **422 if unreachable** so a typo
  can't register a dead node) and `DELETE /nodes/{name}` (protects baseline, 404 unknown).
- **`python_back_end/main.py`** — startup merges persisted subhosts back into the live registry so a
  UI-added node survives a restart. **Bug fixed this session:** the startup call passed a bare `pool`
  that wasn't in scope (logged `⚠️ Cookbook node load failed: name 'pool' is not defined`). The block
  runs inside `async with app.state.pg_pool.acquire() as conn:`, so the fix passes
  `app.state.pg_pool`. Now boots clean: `✅ Cookbook nodes ensured (0 persisted)`.
- **`front_end/owui/src/lib/apis/cookbook/index.ts`** — `addNode` / `removeNode`.
- **`front_end/owui/src/lib/agent-studio/Cookbook.svelte`** — `+ Add device` button, add-node modal
  (name + llmfit URL + optional ollama URL), per-node `×` remove (hidden for the `main` role node).

### Items A + C — Kimi/Moonshot key + tile (unified)

C's intent (a place to add a per-provider key) is delivered **through** A's tile, no separate panel:
the tile writes to the existing per-user `/api/user/api-keys` store with `provider_name="moonshot"` —
the exact row Kimi's readiness reads (`cloud_chat._moonshot_key`, `workspace_router._get_kimi_key`).
So connecting the tile makes Kimi a ready **Build engine AND chat model** in one action.

- **`front_end/owui/src/lib/apis/integrations/index.ts`** — `hasUserApiKey` / `saveUserApiKey` /
  `deleteUserApiKey` against `/api/user/api-keys` (Fernet-encrypted, write-only GET).
- **`front_end/owui/src/lib/integrations/catalog.ts`** — new `user_api_key` connect kind +
  `providerKey` field; `kimi-api` entry (brandKey `kimi`, provider "Moonshot AI"); indigo brand tone.
- **`front_end/owui/src/lib/integrations/BrandGlyph.svelte`** — inline crescent-moon+spark glyph.
- **`front_end/owui/src/lib/integrations/ConnectionPanel.svelte`** — `user_api_key` render branch
  (save / replace / disconnect). **A2 fix:** the silent `authEngine` ternary that mis-routed unknown
  ids to `'claude-code'` is replaced with an explicit `ENGINE_AUTH_OF` map that fails loudly
  (`console.error`) on any unmapped `engine_api_key` tile.

## Verified locally

- Backend restart → `Application startup complete`, `✅ Cookbook nodes ensured (0 persisted)`.
- `POST /api/cookbook/nodes` (unauth) → **401** (auth gate live, not 404/500).
- owui `vite build` → **exit 0**; new build already live via the nginx static mount
  (`front_end/owui/build → /usr/share/nginx/owui`), no restart needed.

## Your E2E when the branch boots

1. **Cookbook → "+ Add device"** (admin only): name + the other box's llmfit URL
   (`http://192.168.x.x:8787`). Reachability-probed; survives a backend restart.
2. **Integrations → Kimi (Moonshot)**: paste your Moonshot key → lands as `provider_name="moonshot"`
   → Kimi lights up as a ready Build engine + chat model.

## Deliberately deferred — Item D

`nvidia-kimi` and `cloud-ollama` catalog tiles were **not** built. Their credentials don't flow
through the per-user `/api/user/api-keys` path, so shipping them now = display-only tiles that can't
connect. Wire that credential path first, as its own task.

## A2 corrections carried from prior session (still true)

- **A4 was wrong** — do NOT add `kimi-api` to `_AUTH_ENGINE_OF` (that's the engine-auth table for
  codex/claude-code; Kimi uses the per-user api-key store instead).
- A3 (separate Settings API-keys panel) is **dissolved** by the tile writing to `/api/user/api-keys`.
