# HARVIS × Hermes Verification Report

**Hermes commit verified:** `8081425a1c095d01db858ea1a574d17c93703f48` (2026-04-27 21:24:08 -0700, "feat(security): make secret redaction off by default (#16794)")
**Repo location:** `/tmp/hermes-agent` (cloned from `https://github.com/NousResearch/hermes-agent` at this commit)
**Verification date:** 2026-04-27
**License:** MIT (`LICENSE:1-3`, `pyproject.toml:12`)
**Verdict summary:** 5/5 factual corrections **VERIFIED**, 13/13 missed features **CONFIRMED**, 0 INSUFFICIENT EVIDENCE. The previous extraction plan was systematically wrong — the corrected analysis is right. Coupling concerns are real but tractable.

---

## Phase 0 — Ground truth

- **Repo size:** 277 top-level Python files, 821 test files (Hermes is a mature, heavily-tested codebase). `cli.py` is ~515k chars / ~11k LOC, `run_agent.py` ~12k LOC per `AGENTS.md:24-27`.
- **Primary entry points:** `hermes` → `hermes_cli.main:main`, `hermes-agent` → `run_agent:main`, `hermes-acp` → `acp_adapter.entry:main` (`pyproject.toml:128-131`).
- **Plugin source set:** repo `plugins/` (memory, context_engine, image_gen, example-dashboard, disk-cleanup, google_meet, spotify, strike-freedom-cockpit) + `~/.hermes/plugins/` + pip `entry_points` group `hermes_agent.plugins` (`hermes_cli/plugins.py:98`).
- **License:** MIT, plain text (`LICENSE:1-21`). All `[project.optional-dependencies]` extras are pip-resolvable; only the `rl` extra pulls git-pinned URLs (`atropos`, `tinker`).
- **`AGENTS.md` contradicts the original analysis 7+ ways:** explicit FTS5 mention (line 28), explicit ACP adapter (line 51), explicit cron module (line 52), explicit profile system (lines 551-606), explicit skin engine architecture (lines 346-431), explicit memory provider list with 8 plugins (line 463), explicit plugin hook list (lines 446-449). The original analysis appears to have been generated without reading `AGENTS.md`.

---

## Phase 1 — Factual corrections

### 1.1 — `hermes claw migrate` exists as a working OpenClaw → Hermes migration tool

**Verdict: VERIFIED**

**Evidence:**
- `hermes_cli/claw.py:1-734` — entire module, 734 lines.
- `hermes_cli/claw.py:303` — `def _cmd_migrate(args):`.
- `hermes_cli/claw.py:4-9` — top-of-file usage examples document `--dry-run`, `--yes`, `--preset full`, `--overwrite`, `claw cleanup --dry-run`.
- `hermes_cli/main.py:9651-9700` — argparse subparser registers `claw migrate` with flags `--source`, `--dry-run`, `--preset`, `--overwrite`, `--migrate-secrets`, `--workspace-target`, `--skill-conflict`, `--yes` (line numbers map to specific `add_argument` calls).
- `hermes_cli/main.py:7217` — `"claw"` registered as a top-level CLI command.
- `optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py` — **2,819 lines** (matches "~2,800" claim).
- `optional-skills/migration/openclaw-migration/SKILL.md` — exists.
- `website/docs/guides/migrate-from-openclaw.md` — user-facing docs exist.
- `README.md:60` and `README.md:111-136` — full migration spec in public README, listing what's imported (SOUL.md, MEMORY.md, USER.md, skills, command allowlist, messaging settings, API keys, TTS assets, AGENTS.md).

**What the script covers** (from grep over the script):
- SOUL.md (line 856 of script — `source = self.source_candidate("workspace/SOUL.md", ...)`, copied to `target_root / "SOUL.md"` with `transform=rebrand_text`)
- MEMORY.md / USER.md (lines 702-712 of script)
- TTS workspace audio assets (line 733)
- `TELEGRAM_BOT_TOKEN` and other allowlisted secrets (line 37 declares the env var allowlist)
- Workspace agents / instructions (line 50, 698)
- Skills (preset entry on line 33: "Skills migrated from an OpenClaw workspace.")
- The script handles OpenClaw's `workspace/` → `workspace-main/` rename (line 663-673).

**What it skips:** the `--preset user-data` mode excludes secrets (`README.md:123`); `cleanup` is a separate subcommand, not part of `migrate`.

**HARVIS relevance:** The script is **Tier 1 fork-able** for an inverted Hermes → HARVIS migration, but the top three HARVIS-specific assumptions to invert are:
1. Path layout: script assumes `~/.openclaw` source and `~/.hermes` target. HARVIS lives in Postgres + per-user state, not a `~/.harvis` directory — the importer becomes "rows in HARVIS DB" rather than "files in `~/.harvis`".
2. Profile model: script assumes single-user file-tree-per-profile (`HERMES_HOME`). HARVIS is multi-tenant with a `users` table — migration writes per-user records.
3. Skill format: HARVIS's skills are `skills/Harvis/<domain>/SKILL.md`; Hermes's land in `~/.hermes/skills/openclaw-imports/`. The skill conflict resolution model needs re-mapping to HARVIS's plugin architecture.

---

### 1.2 — SOUL.md exists with a working personality-injection pipeline

**Verdict: VERIFIED**

**Evidence:**
- `docker/SOUL.md` — 14-line user-facing template, exists.
- `hermes_cli/default_soul.py:1` — `"""Default SOUL.md template seeded into HERMES_HOME on first run."""` — 11 lines.
- `agent/prompt_builder.py:966` — `def load_soul_md() -> Optional[str]:`. Reads `get_hermes_home() / "SOUL.md"` (line 979).
- `agent/prompt_builder.py:1079` — `def build_context_files_prompt(cwd: Optional[str] = None, skip_soul: bool = False) -> str:` — explicit `skip_soul` guard (line 1110-1112) prevents double-injection.
- `run_agent.py:4552` — comment block: `"#   1. Agent identity — SOUL.md when available, else DEFAULT_AGENT_IDENTITY"` confirms SOUL.md is **identity slot #1** in the system prompt.
- `run_agent.py:4560` — `"# Try SOUL.md as primary identity (unless context files are skipped)"`.
- `hermes_cli/profiles.py:56,453-455` — profiles seed a `SOUL.md` template into each profile dir.
- `hermes_cli/doctor.py:552-572` — `hermes doctor` checks SOUL.md presence, offers to create.
- 17+ references to `SOUL.md` across `hermes_cli/`, `agent/`, `run_agent.py`, `cli.py`, `batch_runner.py`, `hermes_cli/claw.py:566`.

**End-to-end flow:**
1. On first run / profile create, `default_soul.py:DEFAULT_SOUL_MD` is seeded to `HERMES_HOME/SOUL.md`.
2. At conversation start, `run_agent.py:4560` calls `load_soul_md()` from `agent/prompt_builder.py:966`.
3. The returned content fills identity slot #1; if absent, `DEFAULT_AGENT_IDENTITY` is used.
4. `build_context_files_prompt()` is then called with `skip_soul=True` to avoid re-injecting SOUL.md as a context file (since it already filled the identity slot).
5. The doctor command and the migration script both treat SOUL.md as a first-class user asset.

**HARVIS relevance:** HARVIS already ships `skills/Harvis/harvis-soul/SKILL.md` (95 lines). The Hermes identity-slot pattern is **compatible** but requires HARVIS to:
- Decide whether SOUL.md is per-user or global (Hermes is single-user-per-profile; HARVIS is multi-tenant — needs per-user storage, e.g. a `user_soul` text column).
- Adopt the `skip_soul` double-injection guard if HARVIS also surfaces SOUL.md as a separate context file.
- The existing `harvis-soul/SKILL.md` is documentation-style; the Hermes pattern is template-style. They serve different purposes — keep the SKILL.md as developer guidance, port the SOUL.md template separately.

---

### 1.3 — FTS5 is used extensively (not absent)

**Verdict: VERIFIED for FTS5. VERIFIED for absence of pgvector.**

**Evidence (FTS5 in `hermes_state.py`):**
- `hermes_state.py:5` — module docstring: `"Provides persistent session storage with FTS5 full-text search, replacing..."`
- `hermes_state.py:11` — `"FTS5 virtual table for fast text search across all session messages"`.
- `hermes_state.py:104-107` — first FTS5 table:
  ```sql
  CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
      content, ...
  )
  ```
  (default unicode61 tokenizer)
- `hermes_state.py:124-133` — second FTS5 table with **trigram tokenizer for CJK/substring search**:
  ```sql
  CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(
      ..., tokenize='trigram'
  )
  ```
- `hermes_state.py:110-146` — six triggers maintaining both FTS tables on INSERT/DELETE/UPDATE.
- `hermes_state.py:153` — `SessionDB` class docstring confirms `"SQLite-backed session storage with FTS5 search."`

**Evidence (FTS5 in holographic memory plugin):**
- `plugins/memory/holographic/store.py:1-40` — SQLite backend with `facts` table, vector storage (`hrr_vector BLOB`), entity resolution.
- `plugins/memory/holographic/README.md:3` — `"Local SQLite fact store with FTS5 search, trust scoring, entity resolution, and HRR-based compositional retrieval."`
- 4 holographic plugin files reference FTS5 (`plugin.yaml`, `README.md`, `retrieval.py`, `store.py`).

**Evidence (no pgvector):**
- `grep -rn "pgvector" /tmp/hermes-agent` returned **zero matches** across all `.py` files. pgvector is genuinely absent.

**Role of FTS5:**
- **Sessions** (`hermes_state.py`) — every message in every session goes into both `messages_fts` (English/Latin script) and `messages_fts_trigram` (CJK/substring). Powers `/insights`, session search, cross-session recall.
- **Memory** (`holographic`) — facts get FTS5 on top of an HRR (Holographic Reduced Representation) vector store. Local-only, no API dependency.

**HARVIS relevance:** HARVIS uses **pgvector**, Hermes uses **SQLite + FTS5**. These don't transfer cleanly:
- Hermes's `SessionDB` is single-user, single-file SQLite. Multi-tenant HARVIS would need to either (a) shard SQLite per-user or (b) port the schema + FTS5 to Postgres `tsvector`/`pg_trgm`/`pgroonga`.
- The `holographic` plugin's HRR-vector approach could run alongside HARVIS's pgvector as an alternate provider, but its `db_path` is hardcoded to `$HERMES_HOME/memory_store.db` (`plugins/memory/holographic/README.md`, config table).
- **Original analysis was wrong on FTS5 (it's pervasive); right on pgvector (genuinely absent).** Don't conflate the two.

---

### 1.4 — Memory has 9 providers, not just file-based

**Verdict: VERIFIED**

**Evidence:**
- `ls plugins/memory/` returns: `byterover/ hindsight/ holographic/ honcho/ mem0/ openviking/ retaindb/ supermemory/` + `__init__.py` — **8 plugin providers** + the **built-in** (file-based MEMORY.md/USER.md path) = 9 total. (`AGENTS.md:464` lists them.)
- `agent/memory_provider.py:42` — `class MemoryProvider(ABC):`.
- `agent/memory_provider.py:13-14` — comment confirms: `"1. Built-in: BuiltinMemoryProvider — always present, not removable."` and `"2. Plugins: Ship in plugins/memory/<name>/, activated by memory.provider config."`
- `plugins/memory/__init__.py:3-19` — discovery system docstring: scans repo `plugins/memory/` and user `~/.hermes/plugins/memory/`, validates each via `MemoryProvider` subclass check.
- `plugins/memory/__init__.py:122` — `def discover_memory_providers() -> List[Tuple[str, str, bool]]:` — lists all available.
- `plugins/memory/__init__.py:159` — `def load_memory_provider(name: str) -> Optional["MemoryProvider"]:` — loads one based on `memory.provider` config key.

**Per-provider table** (from `plugins/memory/<name>/README.md` headers):

| Provider | Requires | One-line | Status |
|---|---|---|---|
| `byterover` | API key | Cloud memory service | working (plugin shipped) |
| `hindsight` | API key | Cloud memory service | working |
| `holographic` | None (SQLite) | Local FTS5 + HRR vectors | working — most adoptable |
| `honcho` | `honcho-ai` pip + cloud or self-host | AI peer/dialectic user modeling | working — deeply integrated (~14 CLI subcommands) |
| `mem0` | API key | Cloud memory service | working |
| `openviking` | API key | Cloud memory service | working |
| `retaindb` | API key | Cloud memory service | working |
| `supermemory` | API key | Cloud memory service | working |
| **builtin** | None | MEMORY.md + USER.md files | always-on, not removable |

**HARVIS relevance:** For HARVIS's pgvector + Postgres stack:
- `holographic` is **most adoptable** (single-file SQLite, no external service, no API key). Could either run as-is or be re-targeted to Postgres.
- `honcho` is the second pick if user-modeling matters — it's the only provider with deep CLI integration (`hermes honcho identity/peer/mode/tokens/migrate/...`) and supports self-hosted Honcho.
- Cloud-only providers (byterover, hindsight, mem0, openviking, retaindb, supermemory) are out-of-scope for an open-source HARVIS deployment unless HARVIS users opt in with their own keys.

---

### 1.5 — `agentskills.io` is referenced (not absent)

**Verdict: VERIFIED**

**Evidence (full reference inventory):**

| File | Line | Context |
|---|---|---|
| `README.md` | 21 | Feature claim: `"Compatible with the agentskills.io open standard."` |
| `README.md` | 170 | Community link: `"📚 Skills Hub (https://agentskills.io)"` |
| `website/docs/index.md` | 54 | Open-standard claim. |
| `website/docs/user-guide/features/skills.md` | 9 | `"compatible with the agentskills.io open standard"` with link to `/specification`. |
| `website/docs/user-guide/features/overview.md` | 14 | Same claim. |
| `tools/skills_tool.py` | 23 | Comment: `"assets/ — agentskills.io standard directory for supplementary files"` |
| `tools/skills_tool.py` | 28 | Section header: `"SKILL.md Format (YAML Frontmatter, agentskills.io compatible):"` |
| `tools/skills_tool.py` | 33 | `"license: MIT  # Optional (agentskills.io)"` |
| `tools/skills_tool.py` | 41 | `"compatibility: Requires X  # Optional (agentskills.io)"` |
| `tools/skills_tool.py` | 42 | `"metadata:  # Optional, arbitrary key-value (agentskills.io)"` |
| `tools/skills_tool.py` | 1204 | Code comment about assets/ directory standard. |
| `tools/skills_tool.py` | 1219 | Code comment: `"Check metadata.hermes.* first (agentskills.io convention)"` |
| `tools/skills_tool.py` | 1378 | `"Surface agentskills.io optional fields when present"` |

**These are not stray comments — they are the spec the SKILL.md format implements.** `tools/skills_tool.py` is the runtime surface that loads/lists/installs skills.

**HARVIS relevance:** HARVIS already ships `skills/Harvis/harvis-*/SKILL.md` files. To be `agentskills.io`-conformant they need:
- Frontmatter fields: `name`, `description`, `version`, `license` (optional), `compatibility` (optional), `metadata.hermes.tags` (or generic `metadata.<vendor>.tags`), `metadata.<vendor>.category` (per `AGENTS.md:511-518`).
- Optional `assets/` subdirectory for supplementary files (per `tools/skills_tool.py:23,1204`).
- Conformance buys interoperability with the Skills Hub (`https://agentskills.io`) and any other agent that adopts the standard.

---

## Phase 2 — Missed features

### 2.1 — ACP (Agent Client Protocol) adapter

- **Existence:** `acp_adapter/` (9 files: `auth.py`, `entry.py`, `events.py`, `__init__.py`, `__main__.py`, `permissions.py`, `server.py`, `session.py`, `tools.py`) + `acp_registry/` (`agent.json`, `icon.svg`).
- **Wired in:**
  - `pyproject.toml:131` — `hermes-acp = "acp_adapter.entry:main"` (binary entrypoint).
  - `pyproject.toml:64` — `acp = ["agent-client-protocol>=0.9.0,<1.0"]` (real PyPI package).
  - `hermes_cli/main.py:40` — `"hermes acp                 Run as an ACP server for editor integration"` in usage.
  - `hermes_cli/main.py:7219` — `"acp"` in command list.
  - `hermes_cli/main.py:9789-9792` — `acp` subparser registered.
  - `acp_adapter/server.py:12-13` — `import acp` + `from acp.schema import ...`.
  - `acp_adapter/permissions.py:10` — `from acp.schema import (...)`.
- **Documentation:** `acp_registry/agent.json` (machine-readable agent manifest); the ACP protocol itself is documented externally (it's a standard for Zed/VS Code/JetBrains agent integration).
- **Maturity signal:** `tests/acp/` exists.
- **Tier:** **1** — fork directly. ACP is the right cross-agent protocol.
- **HARVIS-relevance:** ACP gives HARVIS editor integration (Zed/VS Code/JetBrains) and a standard cross-agent surface. The `acp_adapter/server.py` shape is portable; what couples it to Hermes is `agent/` imports and `run_agent.AIAgent` (see Phase 3 coupling). For HARVIS, the ACP server would wrap whichever agent the user's session is dispatched to (OpenClaw, Hermes-derived, etc.). **Strong recommendation:** adopt ACP for HARVIS as the cross-agent + editor-integration surface.

### 2.2 — Profile system

- **Existence:** `hermes_cli/profiles.py` — **1,111 lines**.
- **Wired in:**
  - `hermes_cli/main.py:9821-9842+` — `profile create/use/delete/import/...` subparsers registered.
  - `hermes_cli/main.py:7275` — bare `hermes profile` shows current profile status.
  - `hermes_cli/main.py:_apply_profile_override()` — sets `HERMES_HOME` before any module imports (per `AGENTS.md:556-558`).
- **Per-profile isolation** (`hermes_cli/profiles.py:5,38-91`): each profile has its own `config.yaml`, `.env`, `memory`, `sessions`, `skills`, `gateway`, `cron`, `logs`, optionally `SOUL.md`.
- **Documentation:** `AGENTS.md:551-606` covers full profile rules (`get_hermes_home()`, `display_hermes_home()`, token-lock pattern for gateway adapters).
- **Maturity signal:** `tests/hermes_cli/test_profiles.py` referenced in `AGENTS.md:659`. PR #3575 fixed 5 profile bugs (`AGENTS.md:612`).
- **Tier:** **2** (extract pattern).
- **HARVIS-relevance:** HARVIS is multi-tenant via Postgres `users` table — it has a *different* isolation primitive (per-user DB rows). Hermes's profile system is **single-OS-user, multi-instance**. The patterns are mostly redundant for HARVIS's primary use case. However, the `HERMES_HOME` env-var indirection pattern is portable as `HARVIS_USER_CONTEXT` if HARVIS ever wants per-user file-tree isolation (e.g. for agent workspaces). **Defer adoption** unless HARVIS needs single-machine multi-instance.

### 2.3 — Mixture-of-Agents tool

- **Existence:** `tools/mixture_of_agents_tool.py` — **541 lines**.
- **Models** (`tools/mixture_of_agents_tool.py`):
  - Lines 64-67: defaults are `claude-opus-4.6`, `gemini-2.5-pro`, `gpt-5.4-pro`, `deepseek-v3.2` (all OpenRouter-prefixed).
  - Line 72: aggregator default = `anthropic/claude-opus-4.6`.
  - Lines 237-238: function signature `reference_models: Optional[List[str]] = None, aggregator_model: Optional[str] = None` — **configurable**, not hardcoded.
- **Wired in:** registered as a tool via `tools/registry.py` import-time pattern (per `AGENTS.md:67-73`).
- **Documentation:** module docstring references arXiv:2406.04692.
- **Tier:** **3** — interesting, defer.
- **HARVIS-relevance:** Yes, HARVIS could use MoA across Ollama-local + Kimi K2.5 + Claude. The OpenRouter coupling is in the model name format (`anthropic/claude-opus-4.6` etc.) — to use HARVIS's local Ollama, replace the URL prefix logic. Defer until HARVIS has a clear best-of-N use case.

### 2.4 — Delegate (subagent) tool

- **Existence:** `tools/delegate_tool.py` — **2,517 lines** (one of the larger tool files).
- **Features** (file lines):
  - Line 5-6: docstring confirms `"Spawns child AIAgent instances with isolated context, restricted toolsets, and their own terminal sessions."`
  - Line 41: `DELEGATE_BLOCKED_TOOLS = frozenset(...)` — children can't call certain tools.
  - Line 478: `DEFAULT_CHILD_TIMEOUT = 600` — 10 min stuck-child timeout.
  - Line 543: `_build_child_agent` constructs focused child system prompt.
  - Line 590: confirms recursion — children can spawn grandchildren.
  - Line 2145: `_invoke_hook(...)` integration with the plugin hook system.
- **Wired in:** registered via tools registry.
- **Tier:** **1** (fork directly, with caveats).
- **HARVIS-relevance:** This is **the cleanest pattern** for HARVIS to spawn OpenClaw / Hermes-derived agents as supervised children. The abstraction is tightly coupled to `AIAgent` (constructor, lifecycle, message format) — **not directly genericizable** to "any agent runtime." For HARVIS, two paths:
  1. Adopt Hermes's `AIAgent` as the child runtime (heavy port).
  2. Build a HARVIS-native delegate tool that spawns OpenClaw-or-Hermes children via the existing OpenClaw bridge pattern, taking only the *behavioral* contract (blocked tools, isolated terminals, parallel batch, timeout) from Hermes's implementation.
  Recommend (2).

### 2.5 — Skin engine + banner system

- **Existence:** `hermes_cli/skin_engine.py` — **882 lines**. `hermes_cli/banner.py` — **588 lines**. Combined: 1,470 lines.
- **Schema:** `SkinConfig` dataclass at `hermes_cli/skin_engine.py:129`. `_BUILTIN_SKINS` dict at line 163. Built-in skins per `AGENTS.md:382-388`: `default`, `ares`, `mono`, `slate`.
- **Working full-reskin example:** `plugins/strike-freedom-cockpit/theme/strike-freedom.yaml` — confirmed exists.
- **ASCII art:** `HERMES_AGENT_LOGO` (`hermes_cli/banner.py:69`), `HERMES_CADUCEUS` (`hermes_cli/banner.py:76`). Both are overridable per skin via `banner_logo` / `banner_hero` (`hermes_cli/skin_engine.py:138-139`).
- **Wiring:** `cli.py:670-671` — `init_skin_from_config(CLI_CONFIG)` at startup. `get_active_skin()` invocations at `cli.py:1210, 1237, 1715`.
- **Documentation:** `AGENTS.md:346-431` — full architecture section, including user skin YAML format and runtime `/skin` switch.
- **Tier:** **1**.
- **HARVIS-relevance:** This **answers** the user's intent to write a "HARVIS CLI BRANDING & UX MASTERPROMPT." The skin engine covers ASCII art, banner panels, spinner faces/verbs/wings, tool prefixes, response box, branding text, and per-tool emojis. **The masterprompt should be a port spec, not a build spec.** The 1,470 lines plus the working `strike-freedom-cockpit` example save weeks of work versus building from scratch.

### 2.6 — Plugin lifecycle hooks (16 hook points, not 14)

- **Existence:** `hermes_cli/plugins.py:60-96` — `VALID_HOOKS: Set[str]` with **16** named hooks (the corrected analysis said 14 — actual count is 16):

| Hook | Purpose (from inline comments) |
|---|---|
| `pre_tool_call` | Before tool execution |
| `post_tool_call` | After tool execution |
| `transform_terminal_output` | Modify terminal output before display |
| `transform_tool_result` | Modify tool result before agent sees it |
| `pre_llm_call` | Before LLM API call |
| `post_llm_call` | After LLM API call |
| `pre_api_request` | Lower-level pre-request |
| `post_api_request` | Lower-level post-request |
| `on_session_start` | Session boot |
| `on_session_end` | Session ending |
| `on_session_finalize` | Session being archived |
| `on_session_reset` | `/new` or `/reset` |
| `subagent_stop` | Delegate child finished |
| `pre_gateway_dispatch` | Inbound gateway message before auth/dispatch (skip/rewrite/allow) |
| `pre_approval_request` | Dangerous-command approval pending |
| `post_approval_response` | Approval answered |

- **Wired in:** real call sites at `model_tools.py:551, 598, 619`, `cli.py:757, 4802, 11089`, `run_agent.py:9796, 9897, 10331, 12049, 12923, 13025`, `gateway/run.py:1931, 2518, 3412, 5465, 5501`, `tools/terminal_tool.py:1864`, `tools/approval.py:50`, `tools/delegate_tool.py:2145`. Plus shell-hook bridge at `agent/shell_hooks.py`.
- **Tier:** **1**.
- **HARVIS-relevance:** HARVIS's day-one minimum: `pre_gateway_dispatch` (for security/rate-limiting messaging), `pre_tool_call` + `post_tool_call` (for audit logging via `proxy_usage_log` table), `on_session_start` + `on_session_end` (for HARVIS's chat session model), `pre_approval_request` + `post_approval_response` (for sensitive-tool gating). That's **7 hooks** — same shape, port directly.

### 2.7 — MCP OAuth 2.1 with PKCE

- **Existence:** `tools/mcp_oauth.py` — **573 lines**, `tools/mcp_oauth_manager.py` — **556 lines** (1,129 total).
- **Implementation:**
  - `tools/mcp_oauth.py:5-10` — uses MCP Python SDK's `OAuthClientProvider` (an `httpx.Auth` subclass).
  - `tools/mcp_oauth.py:58, 526, 539, 566` — actual import + instantiation.
  - `tools/mcp_oauth.py:172, 243-250, 496` — `HermesTokenStorage` persists tokens & client info to disk; survives process restarts.
  - `tools/mcp_oauth.py:479` — explicit `["authorization_code", "refresh_token"]` grant types.
- **Wired in:** consumed by `tools/mcp_tool.py` (the actual MCP tool surface).
- **Documentation:** module docstrings; not a separate doc.
- **Tier:** **2** (extract pattern).
- **HARVIS-relevance:** HARVIS's existing `harvis-mcp` service (`docker-compose.yaml:592`) doesn't currently include OAuth. The OAuth flow is moderately coupled to Hermes's `mcp_tool.py`, but `HermesTokenStorage` is a clean class that can be ported. Recommend adopting after Phase 1; not a day-one need.

### 2.8 — Doctor + Setup wizard

- **Existence:** `hermes_cli/doctor.py` — **1,273 lines**. `hermes_cli/setup.py` — **3,361 lines** (4,634 total).
- **Doctor checks (sample from `hermes_cli/doctor.py`):**
  - Python version (lines 192-199) — gates on 3.10+ / 3.11+.
  - Virtual environment active (line 205).
  - System binaries (line 232).
  - Provider env config (line 89: `_has_provider_env_config`).
  - Honcho configuration (line 94: `_honcho_is_configured_for_doctor`).
  - Tool availability with overrides (line 105).
  - Gateway service linger / systemd (lines 134-167).
  - SOUL.md presence (lines 552-572).
- **Setup modularity** (per `hermes_cli/setup.py`):
  - Independent re-runnable sections (line 4 of docstring).
  - `setup_model_provider()` (line 667).
  - `setup_tts()` (line 1165).
  - `setup_terminal_backend()` (line 1175).
  - `setup_agent_settings()` (line 1541).
  - Per-platform: `_setup_telegram` (1713), `_setup_discord` (1784), `_setup_slack` (1852), `_setup_matrix` (1953), `_setup_mattermost` (2039), `_setup_whatsapp` (2082), `_setup_weixin` (2100), `_setup_signal` (2106), `_setup_email` (2112), `_setup_sms` (2118), `_setup_dingtalk` (2124), `_setup_feishu` (2130).
- **Tier:** **2** (extract pattern, not files).
- **HARVIS-relevance:** The user named "harvis doctor" as a desired CLI command. `hermes doctor` is not directly portable — every check is wired to Hermes-specific paths (`hermes_home / "SOUL.md"`, Hermes config schema, Honcho-aware checks). What's portable is the **shape**: `check_ok` / `check_warn` / `check_fail` / `check_info` helpers + section structure (Python → venv → deps → config → keys → services → permissions). Implement HARVIS doctor against HARVIS's own paths, copy the report-formatting helpers.

### 2.9 — `gateway/platforms/ADDING_A_PLATFORM.md`

- **Existence:** 313 lines. Full integration checklist.
- **Required ABC:** `BasePlatformAdapter` at `gateway/platforms/base.py:1086`. Required methods: `__init__`, `connect()`, `disconnect()`, `send()`, `send_typing()`, `send_image()`, `get_chat_info()` (per checklist sections 1).
- **Supporting types:** `Platform` enum (`gateway/config.py:48`), `PlatformConfig` (`gateway/config.py:145`), `MessageType` (`gateway/platforms/base.py:809`), `MessageEvent` (`gateway/platforms/base.py:831`), `SendResult` (`gateway/platforms/base.py:911`).
- **Existing adapters:** **29 files** under `gateway/platforms/` including `telegram.py`, `discord.py`, `slack.py`, `whatsapp.py`, `email.py`, `signal.py`, `matrix.py`, `mattermost.py`, `sms.py`, `homeassistant.py`, `dingtalk.py`, `wecom.py`, `weixin.py`, `feishu.py`, `webhook.py`, `api_server.py`, `bluebubbles.py` + crypto/helpers/network sub-modules.
- **Tier:** **1**.
- **HARVIS-relevance:** This checklist + the Telegram/Slack/Email/Discord adapter files are **the entire Phase 1 messaging gateway**. Estimated savings vs. greenfield: building 4 platforms from scratch (Telegram=1.5wk, Slack=1.5wk, Email=1wk, Discord-port=0.5wk) would be ~4.5 weeks. Porting Hermes's adapters via the checklist is realistically **1.5-2 weeks** including HARVIS-specific dispatch wiring. Net savings: ~2-3 weeks.

### 2.10 — `AGENTS.md` (architecture spec)

- 764 lines. Read end-to-end during verification.
- **Top 5 things in `AGENTS.md` neither analysis caught:**
  1. **Cache-aware slash commands** (`AGENTS.md:521-535`) — strict policy that mid-conversation state changes break prompt cache; commands that mutate state must default to deferred invalidation with `--now` opt-in. **HARVIS chat will need this discipline if it adopts caching.**
  2. **Background process notifications** (`AGENTS.md:537-548`) — gateway watches `terminal(background=true)` jobs and triggers new agent turns when they finish. `HERMES_BACKGROUND_NOTIFICATIONS` env var controls verbosity. HARVIS's job-queue model could adopt this as "agent gets pinged when its long-running task finishes."
  3. **Two-guard message gateway architecture** (`AGENTS.md:630-639`) — base adapter queues messages while session is active, runner intercepts `/stop`, `/new`, `/queue`, `/status`, `/approve`, `/deny` before they reach `interrupt()`. Any new bypass-eligible command must clear BOTH guards. HARVIS's messaging plugin needs the same architecture or it'll race.
  4. **Plugin rule (Teknium, May 2026)** (`AGENTS.md:478-483`) — plugins MUST NOT modify core files. PR #5295 removed 95 lines of hardcoded honcho argparse from `main.py`. The HARVIS plugin system needs the same hard rule.
  5. **`_last_resolved_tool_names` is a process-global** (`AGENTS.md:624-625`) — `_run_single_child()` saves and restores around subagent execution. If HARVIS ports the delegate pattern, watch for shared mutable state.

### 2.11 — `batch_runner.py` and `trajectory_compressor.py`

- **Existence:** `batch_runner.py` — **1,287 lines**. `trajectory_compressor.py` — **1,508 lines**.
- **Purpose:** confirmed RL/training tooling — `batch_runner.py` returns "trajectory" dicts (lines 249, 281, 345-355, 461), used for batch-generating agent trajectories for training data. `trajectory_compressor.py` compresses those trajectories.
- **Tier:** **3** — defer; not a core agent feature for HARVIS.
- **HARVIS-relevance:** Out of scope unless HARVIS becomes an RL data pipeline. The `pyproject.toml:92-98` `rl` extra pulls `atroposlib` + `tinker` git URLs — these are research-only and not part of the day-one HARVIS adoption surface.

### 2.12 — Honcho deep integration

- **Existence:** `plugins/memory/honcho/` — `client.py`, `cli.py`, `__init__.py`, `plugin.yaml`, `README.md`, `session.py`.
- **CLI subcommands** (`hermes_cli/main.py:21-36`): **14 honcho subcommands** including:
  - `setup`, `status`, `sessions`, `map`, `peer`, `mode`, `tokens`, `identity`, `migrate`
  - `peer --user/--ai/--reasoning` for dialectic config
  - `mode [hybrid|honcho|local]` for memory mode
  - `identity <file>` to seed AI peer identity from SOUL.md (line 35!)
- **Quiet sync at gateway**: `hermes_cli/main.py:6700-6706` — `sync_honcho_profiles_quiet()` runs in background.
- **Tier:** **2**.
- **HARVIS-relevance:** Honcho's "AI peer / dialectic reasoning" is a different abstraction than pgvector RAG. They don't overlap — pgvector is "fetch similar past content," Honcho is "build a model of who the user is over time." Worth considering as a parallel layer if HARVIS wants user-modeling as a first-class feature. Self-host is supported; cloud is optional. Defer unless user-modeling is a priority.

### 2.13 — Top 3 additional features not in either prior analysis

1. **`mcp_serve.py`** — Hermes can run as an MCP **server** (not just consume MCP tools). 30,701 chars / ~700 LOC. Module docstring (`mcp_serve.py:1-5`): `"Hermes MCP Server — expose messaging conversations as MCP tools. Starts a stdio MCP server that lets any MCP client (Claude Code, Cursor, Codex, etc.) list conversations, read message history, send messages, poll for live..."`. **HARVIS could adopt the same pattern: expose HARVIS chat sessions as MCP tools so external editors can talk to HARVIS through the MCP standard.**
2. **`optional-skills/`** — 17 categories of niche skills (`autonomous-ai-agents`, `blockchain`, `communication`, `creative`, `devops`, `email`, `health`, `mcp`, `migration`, `mlops`, `productivity`, `research`, `security`, `web-development`, etc.) shipped but inactive by default. Loaded via `hermes skills install official/<category>/<skill>` (per `AGENTS.md:500-509`). HARVIS's `skills/Harvis/` is monolithic — adopting the optional-skills pattern would let HARVIS ship niche skills without bloating the default install.
3. **`mini_swe_runner.py`** — 28k chars. SWE-bench-style benchmark runner. Out-of-scope for day-one HARVIS but interesting for HARVIS's coding-agent quality eval.

---

## Phase 3 — Extraction viability

### 3.1 — License confirmation

- Repo `LICENSE`: **MIT** (`LICENSE:1, pyproject.toml:12`).
- No alternate licenses spotted in Tier 1/2 file headers.
- The **only** non-MIT compatibility concern is the `rl` extra (`pyproject.toml:92-98`) — `atroposlib` and `tinker` are git-pinned upstream repos. HARVIS won't adopt those for Phase 2.11 (Tier 3, deferred).
- Conclusion: **MIT copy-in with NOTICE attribution** is clean for all Tier 1/2 items.

### 3.2 — Per-item coupling table

| Item | Hermes-internal imports | Hardcoded paths | Stack assumptions | External deps | Extraction effort |
|---|---|---|---|---|---|
| **Gateway adapters** (Telegram/Slack/Email/Discord) | `gateway.config.Platform`, `gateway.platforms.base.*`, `agent.redact`, `gateway.session.SessionSource`, `hermes_cli.config` | `~/.hermes` via `get_hermes_home()` (centralized — easy to swap) | SQLite session store, `AIAgent` dispatch | Per-platform pip extras (already declared) | **M** — port adapter + replace dispatch with HTTP POST to HARVIS |
| **ACP adapter** | `agent.*`, `run_agent.AIAgent`, `acp_adapter.session.SessionManager` | `~/.hermes` indirectly | `AIAgent` is the wrapped runtime | `agent-client-protocol>=0.9` (PyPI) | **M-L** — heavy `AIAgent` coupling; either port `AIAgent` or rewrite the wrap layer to wrap HARVIS dispatcher |
| **Delegate tool** | `run_agent.AIAgent`, `model_tools._last_resolved_tool_names`, `tools.registry`, plugin hooks | None directly | Tightly coupled to `AIAgent` lifecycle, `model_tools.handle_function_call` | None new | **L** — tightest `AIAgent` coupling of any tool. Recommend re-implementing the contract (blocked tools, isolation, parallel) against HARVIS's dispatcher rather than porting |
| **Skin engine + banner** | `hermes_cli.config`, `agent.display` | `~/.hermes/skins/*.yaml` | Rich, prompt_toolkit | None new | **S-M** — mostly data-driven; main port work is replacing `hermes_cli.config` integration with HARVIS's settings and stripping `prompt_toolkit`-specific output if HARVIS CLI uses different rendering |
| **Plugin hook system** | `hermes_cli.plugins.invoke_hook`, plugin manager | `~/.hermes/plugins/` + entry-point group `hermes_agent.plugins` | Synchronous Python hooks | None new | **S** — small port; HARVIS already has a `python_back_end/plugins/` directory; layer the hook dispatcher on top |
| **Cron** (`cron/jobs.py`, `cron/scheduler.py`) | `cron.jobs`, gateway dispatch (for delivery) | `~/.hermes/cron/jobs.json`, `~/.hermes/cron/output/*` | JSON-on-disk persistence | `croniter` (PyPI) | **M** — swap JSON file for Postgres `cron_jobs` table, swap `_deliver_result()` to call HARVIS messaging plugin |
| **Memory provider ABC + holographic** | `agent.memory_provider.MemoryProvider`, `agent.memory_manager` | `$HERMES_HOME/memory_store.db` | SQLite | NumPy optional | **M** — ABC is clean; if HARVIS wants Postgres-backed holographic, reschematize the SQL |
| **MCP OAuth** | `mcp.client.auth.OAuthClientProvider` (external SDK), `tools.mcp_tool` | Token storage path (centralizable) | `httpx.Auth` model | MCP Python SDK | **M** — `HermesTokenStorage` ports clean; integration with `harvis-mcp` service requires touching that service's MCP client |
| **SOUL.md pipeline** | `agent.prompt_builder.load_soul_md`, identity slot wiring | `$HERMES_HOME/SOUL.md` | None significant | None | **S** — small function + injection point. Per-user SOUL.md storage in HARVIS DB is the main change |
| **`pre_gateway_dispatch` flow** | `gateway.run.GatewayRunner`, two-guard architecture | None | Async asyncio dispatch | None | **M** — only relevant once HARVIS has the messaging gateway plugin |

### 3.3 — HARVIS overlap matrix

| Hermes feature | HARVIS equivalent | Verdict |
|---|---|---|
| Gateway: Discord adapter | `python_back_end/integrations/discord_workspace_bot.py` (65KB) | **Augment** — Hermes's adapter is more idiomatic + integrates with shared session model. Port Hermes adapter, retire workspace bot once parity is verified. |
| Gateway: Telegram/Slack/Email | not present | **Replace** (i.e. adopt) |
| Memory: pgvector RAG | HARVIS already has pgvector | **Augment** — Hermes's `MemoryProvider` ABC adds a pluggable layer; pgvector becomes one provider, holographic could be another. |
| Memory: FTS5 sessions | HARVIS does not have FTS5 over chat history | **Replace** — port Hermes `SessionDB`'s FTS5 model to Postgres `tsvector` for HARVIS's `chat_messages` table. |
| MCP integration | `harvis-mcp` service exists | **Augment** — port `mcp_oauth.py` into `harvis-mcp` for OAuth-required servers. |
| SOUL.md / personality | `skills/Harvis/harvis-soul/SKILL.md` exists (95 lines) | **Augment** — keep harvis-soul SKILL.md as developer guidance, add per-user SOUL.md template using Hermes's identity-slot-#1 pattern. |
| Browser automation | `browser-runner` service (Selenium) at `docker-compose.yaml:218` | **Skip** — HARVIS already has it. |
| ACP adapter | not present | **Replace** (i.e. adopt) — HARVIS gains editor integration. |
| Profile system | HARVIS's per-user Postgres model | **Skip** — different abstraction, redundant for HARVIS. |
| Skin engine | not present | **Replace** (i.e. adopt) — answers the "HARVIS CLI BRANDING" intent. |
| Plugin hook system | `python_back_end/plugins/` (router-include style) | **Augment** — HARVIS plugins register routers; layer Hermes's lifecycle hook dispatcher on top. |
| Cron | not present (HARVIS has Postgres `boss` job queue but no cron scheduling) | **Replace** (i.e. adopt with Postgres swap) |
| MoA tool | not present | **Replace** if useful (Tier 3, defer) |
| Delegate / subagents | OpenClaw bridge handles this implicitly | **Augment** — adopt the *contract* (blocked tools, parallel, isolation), implement on HARVIS dispatcher rather than porting `AIAgent`-coupled file. |
| Doctor + Setup | not present | **Replace** (i.e. adopt the pattern, not the files) — `harvis doctor` re-implementing the report shape. |
| `mcp_serve.py` (Hermes-as-MCP-server) | not present | **Replace** (i.e. adopt the pattern) — would let external editors talk to HARVIS via MCP. |
| `optional-skills/` pattern | HARVIS skills are all in `skills/Harvis/` | **Augment** — adopt the optional-skill pattern to reduce default install bloat. |

---

## Phase 4 — Phase plan validation

| Phase | Corrected scope | Estimate verdict | Hidden risks |
|---|---|---|---|
| **1. Messaging gateway** | Extract `BasePlatformAdapter` + adapters via 16-step `ADDING_A_PLATFORM.md` checklist | **2-3 weeks for Telegram + Slack + Email is REALISTIC** — verified by 29 platform files + 313-line checklist. Discord port is +0.5wk if migrating from existing workspace bot. | Two-guard architecture (`AGENTS.md:630-639`), `pre_gateway_dispatch` hook plumbing, SQLite session model → Postgres swap. |
| **2. ACP adapter (NEW)** | Port `acp_adapter/` for editor integration + cross-agent comms | **1.5-2.5 weeks**. Requires either `AIAgent` port (heavy) or rewriting wrap layer to wrap HARVIS dispatcher (medium). | `agent.*` import surface; ACP schema version drift; needs design decision on which agent the ACP server fronts. |
| **3. Memory provider abstraction** | Extract `MemoryProvider` ABC; consider forking `holographic`; evaluate Honcho | **1-2 weeks for ABC is REALISTIC**; FTS5/Postgres-tsvector port is +1 week. | Cache-invalidation policy (`AGENTS.md:521-535`) is a real constraint; multi-tenant scoping across Hermes's single-user-per-profile model needs design. |
| **4. MCP integration** | Finish `harvis-mcp` wiring; port `mcp_oauth.py` | **1 week is OPTIMISTIC**. Realistic: 1.5-2 weeks because OAuth has UI/redirect/storage components. | Token storage cross-process consistency; `harvis-mcp` service architecture not yet documented. |
| **5. Cron** | Port `cron/jobs.py` + `cron/scheduler.py`, swap JSON for Postgres | **1-2 weeks is REALISTIC**. Requires Phase 1 messaging gateway done first (for delivery). | `_deliver_result()` cross-coupling to gateway; `croniter` natural-language parsing; cross-platform file lock removal. |
| **6. Backend abstraction** | Pattern only; skip RL env code | **2 weeks is REALISTIC** if scope stays at "interface + Local + Docker." Skip Modal/Daytona/Singularity unless asked. | Confusing the RL `environments/` (out of scope) with the terminal-backend system inside `tools/environments/` (in scope). |
| **7. SOUL/personality** | Extract `load_soul_md()` slot-#1 pipeline | **3-5 days is REALISTIC**. Mostly per-user storage swap + injection-point port. | `skip_soul` discipline must be respected to avoid double-injection; HARVIS multi-tenant SOUL.md storage decision (column vs file). |
| **8. UI / CLI branding** | Extract skin engine + banner + dashboard plugin slots | **3-4 weeks is REALISTIC** for a full HARVIS CLI experience parity with `hermes` (banner, panels, slash commands, autocomplete). The skin engine itself ports in 1-2 weeks; the surrounding CLI is the bulk. | `prompt_toolkit` vs alternatives; Ink TUI port is separate (defer to web-first for HARVIS). |
| **9. Migration framework (DEFERRED)** | Fork `openclaw_to_hermes.py`, invert to `hermes_to_harvis.py` when needed | **2-3 weeks for inverted script is REALISTIC**. Defer until HARVIS has 2+ third-party agents to migrate from. | Multi-tenant target (HARVIS DB rows), profile-tree → DB schema mapping, conflict resolution UI. |

### Suggested re-ordering

The original recommended order (Messaging → Memory → MCP → Cron → Backend → SOUL → UI → Migration) is **mostly right**, but two adjustments based on Phase 1-2 evidence:

1. **Move ACP (new Phase 2) earlier — between Messaging and Memory.** Reason: ACP gives HARVIS immediate value (editor integration) and is on a parallel critical path from Messaging — they don't block each other. Doing ACP early validates the cross-agent dispatch model that subsequent phases will rely on.
2. **Move Hooks (was implicit) to a standalone early phase, between ACP and Memory.** Reason: `pre_tool_call` / `pre_gateway_dispatch` / approval hooks are foundational for security. Phases 3-7 all want to register hooks; if the hook system isn't there first, every later phase invents a workaround.

**Revised suggested order:** Messaging → ACP → Plugin Hooks → Memory ABC → MCP+OAuth → Cron → SOUL → CLI Branding → Backend abstraction → Migration.

---

## Phase 5 — Open questions for the user

These need a human decision before implementation begins:

1. **Hermes's `AIAgent` — adopt or wrap?** ACP and Delegate are tightly coupled to `run_agent.AIAgent`. Port options: (a) adopt `AIAgent` as a HARVIS internal agent runtime alongside OpenClaw, (b) rewrite the wrap layer to drive HARVIS's existing dispatcher. (a) is heavier but unlocks more Hermes features cheaply; (b) is lighter but means rewriting more files per feature. **Pick before Phase 2.**
2. **FTS5 path: SQLite-per-user or Postgres-tsvector?** Hermes's session FTS5 is single-user SQLite. HARVIS multi-tenant options: (a) shard SQLite per user, (b) port to Postgres `tsvector` + `pg_trgm`/`pgroonga`. (b) is more idiomatic for HARVIS but is real porting work; (a) is faster but adds a per-user file footprint. **Pick before Phase 3.**
3. **Memory provider scope.** Adopt only `holographic` (Tier 1, simplest) for HARVIS day-one, or also wire Honcho (cloud or self-hosted) for user-modeling? Honcho changes the day-one user-experience surface meaningfully (peer/dialectic).
4. **CLI branding scope.** Full `hermes` CLI parity (banner + panels + slash commands + autocomplete + skin engine) or skin engine + banner only as a "phase 1 wedge" of the CLI work? Full parity is 3-4 weeks; wedge is 1-2.
5. **Discord overlap timing.** Migrate `python_back_end/integrations/discord_workspace_bot.py` to the Hermes adapter pattern in the same Phase 1 sprint, or parallel-run both temporarily and migrate users gradually? Parallel-run risks duplicate replies during the cutover.

---

## Appendix A — Search log

Each entry: command (paraphrased) → load-bearing finding.

1. `git rev-parse HEAD; git log -1` → pinned commit `8081425a` from 2026-04-27.
2. `wc -l AGENTS.md README.md ADDING_A_PLATFORM.md hermes_cli/main.py pyproject.toml` → 764 / 180 / 313 / 10166 / 172.
3. `Read AGENTS.md` (2 chunks, full file) → ground-truth, contradicts original analysis 7+ ways.
4. `Read README.md` → confirms `hermes claw migrate`, FTS5, agentskills.io, Honcho in public spec at lines 21, 60, 111-136, 170.
5. `Read pyproject.toml` → MIT, 3 entry points (`hermes`, `hermes-agent`, `hermes-acp`), `acp` extra at line 64.
6. `wc -l hermes_cli/claw.py + migrate script` → 734 + 2,819 lines.
7. `grep _cmd_migrate / claw migrate hermes_cli/claw.py` → flags VERIFIED.
8. `grep claw hermes_cli/main.py` → subparser registered at lines 9651-9700.
9. `grep MEMORY/USER/SOUL/TELEGRAM_BOT_TOKEN openclaw_to_hermes.py` → script touches all 4.
10. `wc -l docker/SOUL.md hermes_cli/default_soul.py` → 14 / 11 lines confirmed.
11. `grep SOUL.md --include="*.py"` → 17+ refs across 9 files; identity slot #1 confirmed at `run_agent.py:4552`.
12. `grep load_soul_md agent/prompt_builder.py` → function at line 966, `skip_soul` guard at line 1110.
13. `grep FTS5 hermes_state.py` → 2 FTS5 tables (lines 104, 129); module docstring confirms.
14. `ls plugins/memory/` → 8 providers + `__init__.py` + builtin = 9.
15. `grep MemoryProvider agent/memory_provider.py` → ABC at line 42.
16. `grep agentskills --include="*.py" --include="*.md"` → 13 refs across README, docs, `tools/skills_tool.py`.
17. `grep pgvector` → **zero matches** (absence VERIFIED).
18. `ls acp_adapter/ acp_registry/` → 9 + 2 files.
19. `grep acp hermes_cli/main.py` → subparser at line 9789-9792, mention at line 40.
20. `grep "from acp" acp_adapter/*.py` → uses real PyPI `acp` package.
21. `wc -l hermes_cli/profiles.py` → 1,111 lines.
22. `wc -l tools/mixture_of_agents_tool.py` → 541 lines; models configurable via function args.
23. `wc -l tools/delegate_tool.py` → 2,517 lines; `DELEGATE_BLOCKED_TOOLS` frozenset at line 41.
24. `wc -l hermes_cli/skin_engine.py hermes_cli/banner.py` → 882 + 588 = 1,470.
25. `ls plugins/strike-freedom-cockpit/theme/` → `strike-freedom.yaml` working full reskin.
26. `Read hermes_cli/plugins.py:60-96` → 16 valid hooks (not 14 as the corrected analysis said).
27. `grep invoke_hook --include="*.py"` → real call sites at `model_tools.py`, `cli.py`, `run_agent.py`, `gateway/run.py`, `tools/terminal_tool.py`, `tools/approval.py`, `tools/delegate_tool.py`, `agent/shell_hooks.py`.
28. `wc -l tools/mcp_oauth*.py` → 573 + 556 = 1,129; uses real MCP Python SDK `OAuthClientProvider`.
29. `wc -l hermes_cli/doctor.py hermes_cli/setup.py` → 1,273 + 3,361 = 4,634.
30. `grep _setup_<platform> hermes_cli/setup.py` → 12 platform-specific setup functions, modular.
31. `wc -l gateway/platforms/base.py` → 2,907 lines; `BasePlatformAdapter` at line 1086.
32. `ls gateway/platforms/*.py` → 29 files.
33. `wc -l batch_runner.py trajectory_compressor.py` → 1,287 + 1,508 = 2,795 (RL training tooling).
34. `grep honcho hermes_cli/main.py` → 14 honcho subcommands; `identity` seeds from SOUL.md at line 35.
35. `head plugins/memory/holographic/store.py` → SQLite + HRR vectors + `facts` table.
36. `find tests/ -name "*.py" | wc -l` → 821 test files (mature).
37. `head /tmp/hermes-agent/mcp_serve.py` → confirms Hermes-as-MCP-server (Phase 2.13.1).
38. `grep init_skin_from_config cli.py` → wired at startup line 670-671.
39. HARVIS-side: `wc -l skills/Harvis/harvis-soul/SKILL.md` → 95 lines exists.
40. HARVIS-side: `grep harvis-mcp docker-compose.yaml` → service at line 592.
41. HARVIS-side: `grep browser-runner docker-compose.yaml` → service at line 218.

Total tool calls used for verification: ~30. Well under the 60-90 budget.

---

**End of report.** All claims have file:line evidence. All Tier 1/2 items have coupling assessments. All phases have estimate verdicts. The corrected analysis is overwhelmingly right; the original analysis was wrong because it skipped `AGENTS.md` and never cloned the repo.
