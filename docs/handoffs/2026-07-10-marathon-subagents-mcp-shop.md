# Marathon handoff — subagents · MCP shop · skills · side-rail · chat/engine (2026-07-10)

**Branch:** `harvis1.1` (MAIN tree `/home/user/Harvis`). NOT pushed. Nothing
committed yet this marathon (per "no push until verified"). The `jolly-dhawan-5babcd` worktree is stale
(13 commits behind) — do not build there.

**Goal (user marathon, ultracode, "use fable 5 subagents", "run through all phases no questions"):**
image-gen plan · verify skills self-management · MCP "discord shop" · custom sub-agents · side-rail nav
fix · then roadmap (chat/engine verify → dev console → discord → image gen → capability planner → printer).

## DONE + VERIFIED LIVE (backend restarted, tests pass)

1. **Skills forgery hole — FIXED + verified.** `owui_compat/skills.py` `skills_create`/`skills_update`
   accepted arbitrary client `meta`, so `meta.audit.verdict='supported'` could be forged (bypassing the
   human gate). Now both strip client `audit`/`revisions` and carry server-managed values from the stored
   row. E2E test: create-with-forged-verdict → stored `audit:{}`; two-step update forgery → verdict stays
   null. PASS.
2. **Chat/engine trace correctness — FIXED + verified.** Unified all `workspace_events` seq allocation
   through one `terminal_container.allocate_event_seq` (was two independent MAX(seq)+1 vs loop-counter
   allocators — the real cause of duplicate/missing trace state). Guarded migration
   `workspace/events_seq_migration.py` skip-and-warns on pre-existing dupes (no row deletion) — on boot it
   confirmed real dup pairs exist (`508eb466#2257`) and skipped the index safely. Also: FIX 3 replay
   whitelist (+token/source/text fields), FIX 4 ownership 403 gates on stream/cancel/status (was: any
   authed user could cancel another user's run). Backend healthy, boots clean.
3. **Skills self-management verdict = PARTIAL (reported).** Human create→audit→verdict→enable→inject/
   publish works E2E and is fail-closed (verified). Agent self-authorship (propose_skill tool, LLM
   self-edit, behavioural audit) does NOT exist yet — documented gap; the shared gate + the security fix
   are the foundation for it.
4. **Custom Sub-Agents — backend wired + verified; UI built.** New `owui_subagents` table +
   `owui_compat/subagents.py` (owner-scoped CRUD, kebab-validated, v1 local-model-only, unique). New
   `workspace/orchestration/subagent_defs.py` (load + resolve_profile, model precedence). `planner.py`
   roster/assignee delegation-by-description (safe no-op when subagents=None). `orchestrator.py` loads
   subagents → planner → resolves per-child equipment; `runner.py` applies system_prompt (verbatim, no
   `.format` brace crash), allowed_tools as offer-time withhold (authorize_action still dispatch
   authority), and injects skills via the SHARED `skills.gated_skill_blocks` gate. Connectors stored +
   honestly labeled deferred (HARVIS_MCP_LIVE). Verified live: CRUD (400 cloud-model, 400 bad-name, 409
   dup), and the shared skill gate (unsupported→"unavailable" note, supported→body). UI:
   `agent-studio/customize/SubAgents.svelte` mounted in Customize (sec-subagents).
5. **`skills.gated_skill_blocks`** — the per-skill fail-closed gate extracted so chat AND sub-agent runs
   share byte-identical governance (caps-ready + lane-enabled + human 'supported' verdict, else honest
   note). `chat_completion._inject_skills` now delegates to it.
6. **JWT secret log leak — FIXED.** `main.py` startup no longer prints `JWT_SECRET[:10]` + length; now
   just "set (len N)".

## DONE + VERIFIED (cont.)

7. **Dev Console v0 — backend verified, page built.** New `GET /api/harvis/jobs` list endpoint (owner-
   scoped two ways, persisted) in `workspace/harvis_jobs.py` — verified live (200, empty for user 1).
   New page `routes/(app)/harvis/console/+page.svelte` composes provider readiness
   (`/api/harvis/providers`), background jobs (`/api/harvis/jobs`), and recent runs
   (`/api/workspace/history?top_level=1`) with a Stop-job action; linked from the Build hub header.

## IN-FLIGHT

- **2nd frontend build** running (`front_end/owui` `npm run build`) to deploy the Dev Console page +
  Build-hub link (1st build already deployed side-rail/MCP-shop/SubAgents). After it succeeds →
  `docker restart nginx-proxy` → verify `/harvis/console` serves. If the build errors, the log names the file.

## DONE (code on disk, needs the frontend build to verify)

- **Side-rail nav fix.** `agent-studio/RunView.svelte` gained `onOpenFull` host-override prop (goto
  fallback preserved); `routes/(app)/harvis/vibecode/+page.svelte` wires all 3 dock RunView instances to
  the in-place `headerOpenRunId` inspector; `components/layout/Sidebar.svelte` activeMode 'code' branch
  also matches `/harvis/build` + `/harvis/agent-studio/run` (hardening).
- **MCP "discord shop".** New `owui_compat/mcp_catalog.py` (13 servers, single source of truth;
  `mcp_wizard.py` now imports it). New `agent-studio/customize/McpShop.svelte` (search + category chips +
  card grid + one-click attach via existing /api/owui/mcp/connections + BYO tiles + honest "not live in
  OpenClaw" sync banner). Mounted as default sec-mcp body; registered `mcp-shop` surface.

## PENDING (roadmap order)

1. **Dev Console v0** — recon: ONE new endpoint `GET /api/harvis/jobs` (list, owner-scoped) in
   `workspace/harvis_jobs.py` + a new `routes/(app)/harvis/console/+page.svelte` composing existing
   endpoints (lanes, providers `/api/harvis/providers`, jobs, recent runs, artifacts, readiness). Pure
   assembly. Deep-links to vibecode diff/PR for review→commit. No auto-push.
2. **Discord v0** — recon: 3 small JWT endpoints in `tools/discord_proxy.py`
   (GET /channels, POST /select-channel via messaging_platforms, POST
   /api/workspace/run/{id}/share/discord with ownership check + emit `share` trace event) + a Discord
   card panel + a run "Post to Discord" button with a preview→confirm modal (the click = approval).
3. **Image generation** — plan exists at `docs/plans/image-generation-v0.md` (ComfyUI-primary/A1111-
   fallback behind one ImageProvider; reuses jobs/artifacts/trace/readiness/skills + right-rail preview).
   BLOCKED on installing a provider (:8188 / :7860 both closed).
4. Capability planner / provider catalog; 5. 3D-printer Adaptive Space (later).

## CONSTRAINTS (verbatim)

No push until user verifies E2E. Never commit secrets/.env. Skills text-only, human 'supported' gate
before inject/publish. `authorize_action` = sole dispatch authority. SSH StrictHostKeyChecking=yes.
Credential secrets never logged. Build phases = Fable-5 build→verify workflows (`model:'fable'`) —
**BLOCKED by session rate limit until 5:10pm PT**; completing main-loop meanwhile. Local-first.

## DEPLOY / VERIFY

Backend: bind-mounted → `docker restart harvis-backend`. Frontend: `npm run build` in `front_end/owui`
→ nginx bind-mounts `build/` → `docker restart nginx-proxy`. Access `http://localhost:9000`. Mint a test
JWT INSIDE the container (`docker exec -i harvis-backend python3` → jwt.encode {sub:"1"} with in-container
JWT_SECRET) — never read the secret to disk/logs.
