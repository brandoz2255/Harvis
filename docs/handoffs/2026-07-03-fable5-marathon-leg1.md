# Handoff — Fable 5 marathon, leg 1 (P0 plan + P1 Build Area)

**Goal:** 15-goal marathon brief (see `docs/plans/fable5-marathon-plan.md` — the plan + live status ledger). Worktree `jolly-dhawan-5babcd`, branch `claude/jolly-dhawan-5babcd`. **Nothing committed/pushed — user verifies end-to-end first** (standing rule).

## State

- **P0 done:** plan doc written; 11 tasks in the task ledger (P1–P11).
- **P1 code-complete, `npm run build` GREEN (1m15s, exit 0):**
  - `front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte`: right dock 2×2 PaneGroup grid → **tabbed dock** (Tasks·Plan·Files·File; running-count badge; `dockTab` persisted at `harvis.vibecode.docktab`; ⋯ menu still gates which tabs exist; run-start → Tasks tab; Explorer file pick → File tab). Composer: user bubbles `rounded-2xl rounded-br-md`, run-mode/Agents pills `rounded-full`, model chip `rounded-lg`, send = filled blue `size-7 rounded-lg` bottom-right, run-dock cards `rounded-xl`.
  - `front_end/owui/src/lib/agent-studio/build/BuildHeader.svelte`: Stop/Create PR/Open Run/⋯/settings → `rounded-lg`.
  - **Repo bug fixed:** `front_end/owui/.gitignore` bare `build/` → `/build/`; it had silently un-tracked `src/lib/agent-studio/build/*` (6 components) + `src/routes/(app)/harvis/build/+page.svelte` — copied from main checkout into worktree (now untracked-but-present; commit with P1). Memory: `project_gitignore_build_dir_bug.md`.
- **node_modules**: symlinked from main checkout (`ln -sfn`) — same commit, package.json identical. Don't commit the symlink.

## Failed attempts / gotchas
- Big single-Edit replacement of the dock grid failed (transcription drift) → did a Python line-splice (2038–2129) instead; splice verified, boundaries clean. External edits reset the harness read-state — re-Read before further Edits to that file.
- `graphify` CLI/index absent in this worktree — recon by direct reads.

## Next steps (P2 — Shell tab)
1. Backend EXISTS: `python_back_end/vibecoding/terminal.py` — WS `/ws/vibecoding/terminal?session_id&token`, JWT + container-label ownership check, PTY `bash -l` **inside the session container** (not host). Mounted via main.py already.
2. Frontend: reuse `src/lib/components/chat/XTerminal.svelte` (xterm v6 + fit/web-links already deps). Add `sh` tab to `dockTabs` in vibecode page; flag default OFF.
3. **STOP-GATE pending user answer:** enable shell? Fact for the decision: it's the same container sandbox the agent's own bash already uses in full-auto — container boundary, not host.
4. Then P3 Notebooks (extend `front_end/open-notebook` + onb facade; retrieval in `owui_compat/knowledge.py`).

## Verify P1 (user)
Deploy per usual (build → rsync → restart nginx) or `npm run preview`; check: dock tabs switch + badge counts; run start jumps to Tasks; file pick jumps to File tab; ⋯ menu still hides/shows tabs; composer chips/send look right; Create PR / Open Run / Stop still fire.
