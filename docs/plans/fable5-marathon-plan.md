# Fable 5 Marathon Plan — Harvis Adaptive Workspace

> Status ledger lives at the bottom. Update per phase. Nothing pushed until user verifies end-to-end.
> Authored 2026-07-03 by the external long-run builder (Claude Fable 5). Branch: `claude/jolly-dhawan-5babcd`.

## 1. The goal, simply

Make Harvis a polished adaptive AI workspace: the user gives it a task, and Harvis organizes the right workspace around that task — with premium UI/UX, strong multi-model orchestration, NotebookLM-grade notebooks, a Claude-Code-Desktop-grade Build area, manageable integrations, shell/SSH reach, and adaptive workflows (actions, fabrication, image→3D, printer) built as tool orchestration behind approval gates.

## 2. Goals by area

| # | Goal | Area | Nature |
|---|------|------|--------|
| 1 | UI/UX polish (same theme) | Cross-cutting | Refine |
| 2 | NotebookLM-style Notebooks | Notebooks | Extend `open-notebook` + onb facade |
| 3 | Build Area → Claude Code Desktop feel | Build | Extend RunView revamp |
| 4 | Shell tab in Build | Build | **Revive** stranded vibecoding PTY backend |
| 5 | Customize + orchestration (Cursor/Claude-like) | Customize | Refine Agent Studio Customize |
| 6 | MCP connection wizard | Integrations | Extend `mcp_servers` builder |
| 7 | Integrations UI redesign | Integrations | Refine control-panel cards |
| 8 | SSH / remote devices + folders | Integrations/CLI-lane | New, gated |
| 9 | **Adaptive Space** (flagship) | New surface | New, manifest-driven |
| 10 | Action/Operator workflow | Adaptive Space exemplar | New, mock-adapter-first |
| 11 | Fabrication prototyping | Adaptive Space exemplar | New, tool orchestration |
| 12 | Image→3D→sim→export | Adaptive Space exemplar | New, tool orchestration |
| 13 | 3D printer integration | Adaptive Space target | Design-only this marathon |
| 14 | Workspace IA (Home/Notebooks/Build/Adaptive/Integrations/Customize/Settings) | Shell/nav | Light early, polish late |
| 15 | Fable 5 = external builder | Meta | Not a Harvis runtime role |

## 3. Adaptive Space, corrected

A **general task-shaped workspace**, not a fabrication feature. The user states a goal; Harvis composes a temporary workspace from a **workspace manifest**: which panels (chat, checklist, preview, diff, terminal, artifact/export), which tools/agents, which steps, and which **approval gates**. Printer/image-to-3D/social-post are *instances* the manifest system can express — never hardcoded modes. Deterministic templates first (a small library of task-shape templates matched by intent), planner-assist only to fill parameters — honoring the deterministic-first rule. It scaffolds, previews, tests, and guides; it **never** self-installs unreviewed code, touches hardware, publishes, or runs risky actions without explicit approval (enforced through `risk.py` tiers + `capability_check.py`, both fail-closed).

## 4. Priority order (and 5. dependencies)

```
Phase 1  Build Area redesign (G3)         ← foundation tabs/layout others slot into
Phase 2  Shell tab (G4)                   ← needs P1 tab frame; backend EXISTS (vibecoding/*)  [GATE: enable]
Phase 3  Notebooks NotebookLM (G2)        ← independent; big user value
Phase 4  Customize + orchestration (G5)   ← Customize.svelte exists; close skills/MCP→OpenClaw load gap
Phase 5  MCP wizard (G6)                  ← feeds P6's MCP section
Phase 6  Integrations redesign (G7)       ← absorbs P5; adds SSH/cloud sections (stubs until P7)
Phase 7  SSH (G8)                         ← [GATE: credentials+enable]; registers into P6 UI
Phase 8  Adaptive Space core (G9)         ← reuses Build run infra (P1), panels from P1–P7
Phase 9  Exemplars (G10–12)               ← manifests + mock adapters over P8   [GATE: real adapters]
Phase 10 Printer design doc (G13)         ← design + adapter interface only     [GATE: hardware]
Phase 11 IA + polish sweep (G14, G1)      ← nav homes added light in P1; finalize here
```

G1 (polish) applies inside every UI phase + final sweep. G14 light version lands in P1 (nav home for Adaptive Space placeholder) to avoid a late nav reshuffle.

## 6. UI/UX architecture

- **Stack:** existing forked OWUI (Svelte) + additive `agent-studio/` components. No new framework. Theme = existing Tailwind/dark tokens; match `RunView.svelte`/`UsageMeter.svelte` conventions. Inline `background-clip:text` when gradient text is needed (minifier strips the class).
- **Build:** `RunView.svelte` (372L) grows a **left-rail + tabbed-main** Claude-Code-Desktop layout: tabs = Chat · Tasks · Diff · Background Runs · Shell(P2). Filters become persistent segmented controls, not buried toggles. Top-right = Controls · Shell · Stop, consistent order.
- **Adaptive Space:** new sidebar surface rendering a `SpaceManifest` → grid of known panel components (reuse: chat thread, `RunTable`, `VibecodeSessionDiff`, `ArtifactPreview`, checklist(new), approval-gate card(new), export area(new)).
- **Integrations/Customize/MCP:** stay on the existing card/drawer system (`status.ts` 6 statuses), refined per phase.

## 7. Backend architecture

- **Facade rule:** all new endpoints in `owui_compat/` or `workspace/` routers — additive, never forked into OWUI upstream code.
- **Shell:** reuse `vibecoding/terminal.py` (PTY, 266L) + `sessions.py` + `command_security.py`; new thin router alias under `/api/workspace/{id}/shell`; manual-vs-agent command provenance recorded per entry; risk-gate by permission mode; **feature-flag `HARVIS_BUILD_SHELL` default OFF** until user review.
- **Adaptive Space:** new module `python_back_end/adaptive_space/`: `templates.py` (deterministic task-shape library), `manifest.py` (schema), `router.py` (CRUD + step advance + approval), tables `adaptive_spaces` / `space_steps` (additive migration, `CREATE TABLE IF NOT EXISTS` only).
- **Tool adapters:** `python_back_end/tools/adapters/` with a common interface (`prepare/preview/execute/status`), **mock adapter first** for social/fabrication/printer; real adapters are separate, gated work.
- **Security invariants (unchanged):** OpenClaw isolation (no egress, no cloud keys); `capability_check.py` fail-closed for bundled; `risk.py` allow/gate/block; `engine_auth.py` write-only creds. SSH keys, when built, follow the `engine_auth` encrypt-at-rest/decrypt-at-exec pattern.

## 8–9. Phases (goal · files · changes · checks · result · stop)

**P1 Build Area (G3):** files `agent-studio/RunView.svelte`, `RunWorkspace.svelte`, `RunTable.svelte`, composer component, `runStages.ts`. Changes: tab frame (Chat/Tasks/Diff/Runs), chatbox restyle, run-status header, filter controls, top-right control order; keep UsageMeter. Checks: `npm run build`, manual pass on run lifecycle (start/stream/stop/diff). Result: Build reads like Claude Code Desktop. Stop: no route renames, no backend changes.
**P2 Shell (G4):** files `vibecoding/terminal.py` (reuse), new `workspace/shell_router.py`, new `agent-studio/ShellTab.svelte`. Changes: PTY websocket wired to tab; history + cwd display; provenance label "manual"; flag OFF. Checks: unit on command provenance; PTY echo test in dev. Result: Shell tab present, disabled pending review. **STOP before enabling.**
**P3 Notebooks (G2):** files `front_end/open-notebook/*` (vendored UI), onb facade routers, `owui_compat/knowledge.py` (retrieval exists). Changes: NotebookLM 3-pane (Sources | Chat | Studio) inside Notebooks tab; per-notebook Create; grounded-answer citations from existing chunk store; artifacts list. Checks: source upload→chat grounding E2E on a test doc. Result: Notebooks feels NotebookLM-close. Stop: no new embedding backend; reuse pgvector store.
**P4 Customize (G5):** files `agent-studio/Customize.svelte`, `orchestration/planner.py`, `owui_compat/skills.py`. Changes: model-routing matrix UI (task-type → model), presets, persona editor polish; wire created skills/MCP into live OpenClaw config load (close known gap). Checks: routing pref persists (`owui_user_settings` RMW); OpenClaw sees new skill after save. Stop: no silent model swaps — routing is explicit user config (no keyword auto-routing).
**P5 MCP wizard (G6):** files Customize MCP builder, `mcp_servers` table, new wizard component. Changes: stepper (template → config → creds → permission preview → test → enable); creds via existing encrypt path. Checks: connection test endpoint round-trip. **STOP at credential handling review.**
**P6 Integrations (G7):** files `owui_compat/capabilities.py`, `integrations_status.py`, control-panel components. Changes: category sections (OpenClaw/OpenCode/Hermes/MCP/SSH/Cloud), health checks surface, logs drawer, install/configure/disable per card. Checks: statuses match `status.ts` contract; 7s polling unchanged. Result: single manageable dashboard.
**P7 SSH (G8):** new `python_back_end/remote/ssh_manager.py` + UI in Integrations. Changes: connection manager (host/user/key), folder picker, mount-as-workspace (read-only first), terminal via P2 PTY plumbing; keys encrypted at rest. **STOP before first real connection + before write-mount.**
**P8 Adaptive Space (G9):** new `adaptive_space/` + surface UI + 3–4 seed templates (research-notebook, integration-scaffold, feature-plan, ssh-workspace). Checks: "plan a Harvis feature" produces a shaped workspace with checklist + gates. Stop: scaffold-only; generated integration code goes through worktree→diff→review, never auto-mounted.
**P9 Exemplars (G10–12):** manifests `social-post`, `fabrication`, `image-to-3d`; mock adapters emitting "prepared, no real action taken"; tool-orchestration interfaces documented per stage (image-to-3D model, mesh check, FEA hook, slicer). **STOP before any real platform/tool adapter.**
**P10 Printer (G13):** design doc + adapter interface only. **STOP: hardware = CLI-lane, explicit setup, user approval.**
**P11 IA + polish (G14+G1):** finalize sidebar (Home/Notebooks/Build/Adaptive/Integrations/Customize/Settings), empty states, spacing/hierarchy sweep, regression pass.

## 10. Executor prompts

Stored per-phase in `docs/plans/executor-prompts/` as phases begin. Shape: goal, exact files, invariants (theme, facade rule, fail-closed gates, <500-line files), verification steps, stop conditions. Never instruct an executor to handle credentials, enable shell/SSH, or touch hardware without the user gate.

## 11. Review checklists

**UI:** theme tokens only; empty/loading/error states; keyboard nav; no layout shift on stream; mobile-sane. **Maintainability:** additive facade; components <500L; no upstream OWUI forks edited; types on public APIs. **Permissions/security:** fail-closed through `capability_check.py`/`risk.py`; creds write-only + encrypted; no secrets in logs/prompts; SSRF/path-traversal guards on any new fetch/file endpoint; OpenClaw isolation untouched. **Regression:** run lifecycle (start/stream/stop/diff/PR), chat, notebooks, Discord bot untouched paths. **Rollback:** every phase = one local commit; revert = `git revert <phase-sha>`; flags default OFF for new risk surfaces.

## 12. Hard stop-gates (ask user first)

Destructive changes · credential handling · enabling shell execution · enabling SSH · hardware control · production deploy · external platform posting · broad refactors.

---

## Status ledger

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 0 Plan | ✅ | — | graphify index absent in worktree; recon by direct read |
| 1 Build Area | ✅ code-complete, build green | uncommitted (user verifies first) | Tabbed dock (Tasks·Plan·Files·File + running badge) replaced 2×2 grid; composer polish (bubbles/chips/send); BuildHeader rounded controls. **BONUS: fixed `build/` gitignore bug + rescued 7 never-committed source files** (agent-studio/build/* + /harvis/build route). Full `npm run build` passed 1m15s. |
| 2 Shell tab | ✅ code-complete | uncommitted | `ShellTab.svelte` (xterm→PTY WS), 5th dock tab; `HARVIS_BUILD_SHELL` default OFF enforced BOTH sides (config.py feature flag + terminal.py WS guard). Shell runs in the SESSION CONTAINER, not the host. **GATE: enable = user decision.** |
| 3 Notebooks | ✅ (agent + finisher) | uncommitted | NotebookLM report kinds (briefing/faq/timeline + study_guide), selected-source grounding, save-to-note, suggested-question chips (wired into ChatPanel empty state), audio-overview rail button. Gaps listed in finisher report (no inline citations in reports, no per-turn follow-ups, 12-source cap). |
| 4 Customize | ✅ (agent + my wiring) | uncommitted | ModelRoutingMatrix + AgentPresets + persona sections wired into Customize.svelte. Explicit user routing config only — no keyword auto-routing. OpenClaw sync = dry-run preview + apply behind `HARVIS_OPENCLAW_SYNC` (default OFF). |
| 5 MCP wizard | ✅ (agent + my wiring) | uncommitted | McpWizard stepper (template→config→creds-constrained→permission preview→test→enable) wired as "Guided setup" beside Quick add; backend `mcp_wizard.py` with SSRF-guarded connection test. **GATE: new credential kinds = pending review.** |
| 6 Integrations | ✅ (agent + my wiring) | uncommitted | 5 named sections (status.ts additive; 6-status contract untouched), SSH placeholder card, Logs button per card → `IntegrationLogs` drawer → `integration_logs.py` (SELECT-only, redacted, fail-soft). |
| 7 SSH scaffold | ✅ | uncommitted | `remote/ssh_manager.py`: CRUD behind `HARVIS_SSH_ENABLED` (default OFF→403); connect/test additionally hard-501; ZERO ssh lib imports; creds via Fernet write-only; 13/13 validation tests pass. **GATES: enable flag + first connection + write-mount.** |
| 8 Adaptive Space | ✅ | uncommitted | `owui_compat/adaptive_space.py` (manifest schema, 7 templates, approval-gated steps w/ audit, ownership-scoped) + `/harvis/adaptive` launcher + SpaceView (checklist/gates/todo/notes). Sidebar link added. Suggest ranks; USER picks. |
| 9 Exemplars | ✅ | uncommitted | social-post / fabrication / image-to-3d templates + mock-execute endpoint ("no real action taken", audited) + `docs/plans/adaptive-exemplar-adapters.md` (per-stage tool contracts, ApprovalToken, per-adapter flags default mock). **GATE: any real adapter.** |
| 10 Printer doc | ✅ | uncommitted | `docs/plans/printer-integration-design.md` — CLI-lane bridge, mock-first adapter, approval before hardware. |
| 11 IA + polish | ✅ (light) | uncommitted | Adaptive Space in sidebar footer nav (beside Integrations). Full IA reshuffle deliberately deferred — Adaptive Space creates temporary task-shaped studios per the no-over-splitting rule. Final build: see report. |

**Incident:** wave-1 agents P3/P45/P6 died on a session limit mid-task without reports; work was surveyed file-by-file, half-wired pieces completed (Customize wiring, integrations sections/logs UI, notebook grounding props + chips), and a finisher agent verified P3 end-to-end.

**Polish pass (2026-07-04):** Build ⚙ now opens Customize IN Build (right drawer, `?panel=customize`, deep-linkable) instead of bouncing to the hub; Customize gained a sticky section-nav (Routing·Presets·Orchestration·Skills·Tools·MCP); Adaptive launcher cards preview the workspace shape (panels + gate count); SpaceView gained an Activity&Output panel + Run-(mock) on execute steps; SSH scaffold re-audited (all 7 safety properties hold). Build exit 0 / 1m22s / 0 new warnings.

**Docker-view fix (2026-07-04, end of session):** running stack is the MAIN checkout (project `harvis`); worktree changes were never in its path. Added the missing `./python_back_end/remote:/app/remote:ro` backend mount to the WORKTREE compose (main.py imports `remote.ssh_manager` → backend would crash on boot without it). View method = run the stack from the worktree with `COMPOSE_PROJECT_NAME=harvis` to reuse the real `harvis_*` volumes (+ `--build open-notebook-ui` for P3). `npm run preview` dropped. **Full instructions: `docs/handoffs/2026-07-04-RESUME-TOMORROW.md` — START THERE next session.** Not committed/pushed/deployed; user views in docker tomorrow, then cleanup + commit decision.
