# Handoff — 2026-06-29 — Hermes BYO reframe (shipped) + cloud-Claude issues to fix next

## Goal (this session)
1. Finish the Hermes product-model work and **reframe it around user-owned Hermes** ("Bring your Hermes into Harvis").
2. Install a set of skill/plugin packs onto the dev Claude Code instance.
3. Document the day + write this handoff.

## State (what's done + verified)
- **3 commits on `harvis1.1`, branch ahead 16 of origin, NOT pushed** (standing rule: hold until the user says go):
  - `7b2a3dc` — Hermes Agent reads as the **engine** (sidecar), not a model (detect.serviceKey `hermes`→`hermes-agent`; `Used by Chat, Build`; `code`→`Build` label). Proved it runs the real binary (Chat self-id on `:8642`; Build ran `hermes -z --yolo` → `hello.py` + diff).
  - `dd01302d` — **H1: per-user Hermes model preference** (`resolve_hermes_model`: pref → `HARVIS_HERMES_AGENT_DEFAULT_MODEL` → recommended-installed → first; stored `settings.integrations.preferences.hermes_agent_model`; `POST /api/owui/integrations/hermes-model`; used by Build + Chat). qwen3:4b no longer hardcoded.
  - `6158902c` — **"Bring your Hermes into Harvis"** 3-mode drawer: **Import profile** (`hermes_import.py`: preview→backup→replace into the SIDECAR home via `docker exec` uid-1001 `find -type f | tar` pipe — symlinks skipped, secrets flagged, traversal-guarded), **Connect external** (`hermes_connect.py`: Fernet URL+token, verify, Chat routes there, Build off via `engine_readiness.hermes-agent.reason='external_no_workspace'`), **Harvis-managed (Advanced)** fallback. Frontend `HermesConnect.svelte` + `registry.ts` clients.
- All three drawer modes browser-verified on `:9000`; import + external endpoints tested E2E (traversal→400, symlink skipped, backup made, save/verify/disconnect).
- **Skills installed** onto the laptop's `~/.claude` (user scope): `ui-ux-pro-max`, `obsidian` (kepano), `superpowers` (obra) via `claude plugin install`; **GSD** = `open-gsd/get-shit-done-redux` via `npx @opengsd/gsd-core --global --claude` (the redux fork — the original `jnuyens/gsd-plugin` has trust concerns); LightRAG = wrapper SKILL.md (it's a pip lib). **claude-mem skipped** (user choice). settings.json carries claude-flow + GSD hooks coexisting.
- Obsidian dev-log: `notes-vault/code/harvis/2026-06-29-hermes-byo-reframe-and-skill-packs.md`. Memory: `project_hermes_byo_reframe`, `reference_installed_skill_packs`.

## Files in flight (committed, not pushed)
`owui_compat/hermes_chat.py` · `hermes_connect.py` (NEW) · `hermes_import.py` (NEW) · `capabilities.py` · `router.py` · `catalog.ts` · `capabilities.ts` · `registry.ts` · `HermesConnect.svelte` (NEW) · `ConnectionPanel.svelte` · `engine_adapter.py`.

---

## NEXT (priority order)

### 🔴 1. Subscription Stop must HARD-KILL the model — credit safety (HIGH)
**Concern (user):** when using a **subscription** (Claude Code OAuth / `claude -p`), Stop must kill the process *no matter what* — subscription credits are finite, and "a model running with no end" burns them.

**The gap found today (not yet fixed):**
- Claude subscription paths run `claude -p` **in the sidecar**: chat → `cloud_chat.py:481 _proxy_claude_cli` (`claude -p <prompt>`, line 492); build → `engine_adapter.py:114 _build_claude_command` (`claude -p <task>`).
- Existing Build Stop does **`pkill -TERM -f "{workspace_path}"`** (`engine_adapter.py:248`). But `claude -p` runs with the workspace as its **cwd** (`docker exec -w <path>`), which usually is **NOT in the `claude` process argv** → that pkill **may not match `claude`** → it keeps running on credits. SIGTERM is also catchable; children may survive.
- The **chat** subscription path (`_proxy_claude_cli`) appears to have **no kill wired** to a Stop/disconnect at all, and no visible **hard timeout cap** — the bigger risk.

**Fix direction for tomorrow:**
1. Tag every subscription run with a unique marker (env `HARVIS_RUN_ID=<id>` or a sentinel arg) and kill by that marker — `docker exec <sidecar> pkill -KILL -f <run_id>` (SIGKILL, not TERM), plus kill the **child tree** (`claude` spawns helpers). Don't rely on the cwd path.
2. Wire a **kill on the chat path** too (Stop / client-disconnect → kill the sidecar `claude` proc), and add a **hard timeout cap** (env-tunable) on both chat + build subscription runs so a stuck run can't run unbounded.
3. Verify: start a subscription run → Stop → confirm `docker exec <sidecar> pgrep -f claude` is empty (no orphan); confirm a disconnected chat turn doesn't keep a `claude` proc alive.
4. Same audit for the **api_key** path (it's an HTTP request to Anthropic — cancel the `httpx` request/stream on Stop so we don't keep paying for output tokens).

### 🔴 2. Cloud Claude failing with 404 / 500 (user-reported, needs logs)
**Symptom (user):** "using claude is failing from errors of either 404 or 500 something." No logs captured yet — **first step tomorrow = reproduce + grab the actual error** (`docker compose logs backend` around a Claude chat send; check the Network tab status + body on `:9000`).
**Hypotheses to check (per [[project_cloud_chat_models_f]] + [[project_claude_code_dual_auth]]):**
- **404** — likely a bad Anthropic **model id** or endpoint: confirm the `anthropic/` prefix is stripped before the Messages API call (`cloud_chat._api_model`), and that the concrete id is a real API id (e.g. `claude-opus-4-8` may not be a valid *API* model string — verify against the live model list; the memory notes the api-key paths were "plumbing-only, never run with a real key"). Could also be a wrong base URL/path.
- **500** — likely the **subscription `claude -p`** path erroring (the `CLAUDE_CODE_SIMPLE=1` baked-in-sidecar gotcha → "Not logged in"; the fix is per-exec `-e CLAUDE_CODE_SIMPLE=` off for oauth — confirm it's applied on the **chat** path too, not just build), or an unhandled exception in the proxy surfacing as 500.
- Decide which path (api_key Anthropic HTTP vs subscription CLI) is the one failing — they fail differently.

### 🟡 3. Make the Claude model actively work WITH OpenClaw (user direction)
**Want:** Claude shouldn't only be a chat model / Claude-Code build engine — it should be able to **drive the OpenClaw tool runtime** (shell, browser, file ops, the agent loop). I.e. Claude-as-brain over OpenClaw-as-tools.
**Where to start:** OpenClaw is the agent/tool router (`workspace/openclaw_client.py`, gateway `ws://openclaw:18789`). Today the OpenClaw agent loop runs on local Ollama models. The task = let a **Claude** model (api_key or subscription) be the model OpenClaw's loop calls — likely by pointing OpenClaw's model provider at the Harvis cloud-Claude proxy, OR a Harvis-side agent loop that uses Claude for reasoning and OpenClaw for tool execution. Scope it as its own phase. (Security: OpenClaw stays internet-isolated per CLAUDE.md; routing Claude in must not open egress.)

### Existing roadmap (unchanged)
- Push the Hermes arc when the user says go (ahead 16).
- Import-via-upload + merge-import; external-mode Build (shared-FS / workspace-sync / tool-bridge).
- Rotate the public JWT_SECRET (from the first-push follow-up).

## Standing rules
Branch `harvis1.1`; **no push until the user says go**. Build = `front_end/owui` `npm run build` → `docker restart nginx-proxy`; backend bind-mounted → `docker restart harvis-backend`. Secrets Fernet-encrypted, decrypt only at call time, never logged. Reviews ≤3 agents, single pass.

## Failed attempts / notes
- None blocking this session. The previous turn's recon got cut off by a transient model-availability blip; re-ran cleanly here.
