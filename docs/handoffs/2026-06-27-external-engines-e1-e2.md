# External Code Engines — E1 (OpenCode, shipped) + E2 (Codex + Claude Code, built)

**Date:** 2026-06-27
**Branch:** `harvis1.1` (ahead 4 of origin; **nothing pushed**)
**Status:** E1 committed · E2 fully built + deployed + verified-sans-key, **uncommitted**

---

## The one-line story

Build (VibeCode) used to always run Harvis's native OpenClaw coder. Now its **engine is swappable**: a session can run an external coding CLI instead. **E1** shipped **OpenCode** (local Ollama, no auth). **E2** added **Codex (cloud GPT)** + **Claude Code (cloud Claude)**, each on the *user's own* API key. Selector is now **Native | OpenCode | Codex | Claude Code**.

---

## Where things stand

### E1 — OpenCode — DONE + COMMITTED
- Sidecar `harvis-opencode` + `engine_adapter.py` (`agent_id="engine-adapter"`), `docker exec opencode run --format json` against the session clone, NDJSON→OpenClawEvents→diff. Local Ollama, zero cloud creds.
- Committed as **two commits** on `harvis1.1`:
  - `63f207e` feat(owui): Integrations capability registry + connections + default-model routing (A→D)
  - `6576f70` feat(build): OpenCode external code-engine adapter (Phase E1)
- E2E-verified earlier (turn→diff, Stop→no orphan, native/orchestrate preserved).

### E2 — Codex + Claude Code — BUILT, VERIFIED-SANS-KEY, **NOT COMMITTED**
Both are **cloud** engines on the **user's own API key** (operator pays nothing). Symmetric, auth-gated.

**New files**
- `codex/` + `claude-code/` — sidecar Dockerfiles/entrypoints (node:20 + the CLI + git, uid 1001, share `artifact_data`; **no key baked**).
- `python_back_end/owui_compat/engine_auth.py` — per-user encrypted keys (`user_engine_auth` table, reuses `main.encrypt/decrypt_api_key` Fernet). Endpoints `GET/POST/{e}/verify/{e}/disconnect /api/owui/engine-auth/{codex|claude-code}`, **write-only** (never returns the key). Verify hits OpenAI `/v1/models` / Anthropic `max_tokens:1`.

**Modified**
- `docker-compose.yaml` — `codex` + `claude-code` services.
- `engine_adapter.py` — refactored to per-engine `_build_*_command` + `_map_*_line` (opencode/codex/claude); shared path-guard/timeout/diff/persist + per-run kill (cwd `readlink /proc/*/cwd` + argv `pkill -f <clone>`). Accepts decrypted `api_key=` for cloud.
- `workspace_router.py` — `EXTERNAL_ENGINE_IDS`/`CLOUD_ENGINE_IDS`; **one global flag** `HARVIS_OWUI_EXTERNAL_ENGINES` (no per-engine flags); session-create coerces native (flag-off/in-place) + **rejects** (unknown engine | cloud-without-verified-key); turn-start decrypts the user's key → `_workspaces["engine_key"]` → adapter.
- `capabilities.py` (codex/claude `service_key`s + `_derive_source` + **`engine_readiness` object**) · `integrations_status.py` (cloud engines ready iff flag+sidecar+**verified key**) · `orchestration/__init__.py` (`user_engine_auth` table).
- Frontend: `ConnectionPanel.svelte` `engine_api_key` mode (write-only "🔑 saved · Replace") · `apis/integrations/index.ts` engine-auth clients · `catalog.ts` connect+runtimeNote · `vibecode/+page.svelte` selector = Native + each *ready* engine (cloud never auto-default unless preferred + verified).
- Docs: `docs/guides/vibecode-external-engines.md` (E2 section) · changelog · memory `project_engine_adapter_e2.md`.

---

## Verified today (flag ON, :9000)

| Check | Result |
|---|---|
| codex + claude-code sidecars up, CLIs present | ✓ |
| no-key Codex run | **401 from api.openai.com** (auth gate works) |
| `engine_readiness` | `opencode:ready`, `codex/claude:needs_setup (missing_auth)` |
| verify a **bogus** key | `"OpenAI rejected the key (HTTP 401)"` + `last_error` set (whole verify path works) |
| unknown engine | 400 |
| **OpenCode regression** | refactored adapter still produces a real diff (`ok.py`) |

**Could NOT verify (needs a real key):** an actual cloud Codex/Claude turn editing a file. By design the key goes through the encrypted **Connect panel in the UI**, never chat. The path is proven by the 401; a valid key just makes it succeed.

---

## Build-step-0 findings (why decisions were made)

- **Codex installs** (`@openai/codex` 0.142, `codex exec --json`), **Claude Code installs** (`@anthropic-ai/claude-code` 2.1, `claude -p --output-format stream-json`). Both headless + machine-readable.
- **Codex JSON schema captured:** `thread.started`/`turn.started`/`item.completed{command_execution,reasoning,agent_message,error}`/`turn.completed`. **Claude stream-json:** `assistant`(text/tool_use)/`user`(tool_result)/`result` — mapper written from docs, refine when a key is connected.
- **Codex-local was DROPPED** (user's call): works only with heavy `gpt-oss:20b` (13.8 GB; smaller models lack Codex metadata → `apply_patch` disabled), `-s danger-full-access` (container can't run Codex's bubblewrap sandbox — no namespace caps), and a **socat `localhost:11434→ollama:11434` forward** (Codex `--oss` hardcodes localhost; custom providers now need `wire_api="responses"` which Ollama doesn't speak). Impractical on the 8 GB dev GPU → OpenCode is the free-local option. (Left a `gpt-oss:20b` ollama alias from testing — harmless.)

---

## NEXT (tomorrow)

1. **Connect a real key + finish cloud E2E.** Integrations → Codex (or Claude Code) → paste key → **Connect & verify** → it appears in the Build selector → start a clone session → run a turn → confirm a real diff. (For Claude, this is also when the stream-json mapper gets confirmed against live output.)
2. **Commit decision.** E2 is uncommitted on `harvis1.1`. Likely a focused **E2 commit** on top of `6576f70` once a cloud turn is confirmed. Strays to keep excluded: `front_end/harvis-ui-prototype/` (68 MB, node_modules), `front_end/newjfrontend/app/docs/byo-openclaw-setup/`. **No push until verified.**
3. **E4 — Hermes engine (deferred).** User wants Hermes as a real OpenClaw-style *routable engine*, not just a model. Today Hermes = `model_provider` (Ollama tags); there's a PARTIAL pattern-port (`plugins/core/hooks.py`, `plugins/soul/loader.py`, `plugins/messaging/base_adapter.py`) + `docs/HARVIS_HERMES_VERIFICATION_REPORT.md` + `feat/hermes-integration`. E4.0 = feasibility-first: is there a runnable hermes-agent gateway, or only patterns? It's a gateway+client/resolver (like OpenClaw), NOT a CLI sidecar.

## State of the live dev box
- 3 sidecars up: `harvis-opencode`, `harvis-codex`, `harvis-claude-code`.
- `harvis-backend` has `HARVIS_OWUI_EXTERNAL_ENGINES=1` (committed default is OFF). New OWUI build deployed (nginx restarted).
- Full plan: `~/.claude/plans/noble-noodling-pnueli.md` (E2 section at top).
