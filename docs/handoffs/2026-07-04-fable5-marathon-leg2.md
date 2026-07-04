# Handoff — Fable 5 marathon, leg 2 (P2–P11 complete)

All 11 phases code-complete in worktree `jolly-dhawan-5babcd`. **Nothing committed/pushed** — user verifies end-to-end first. Status ledger: `docs/plans/fable5-marathon-plan.md`. Leg-1 handoff: `2026-07-03-fable5-marathon-leg1.md`.

## Verification state
- Frontend: every touched .svelte parse-checked; full `npm run build` run at the end (see final report in chat for exit + warnings).
- Backend: `py_compile` green across owui_compat/*, onb_compat/*, remote/*, vibecoding/terminal.py, main.py. FastAPI not installed on host → no live TestClient run; first `docker restart harvis-backend` is the real smoke test.
- open-notebook (Next.js): no node_modules → esbuild parse-check + manual type review only; run its typecheck before deploy.

## Feature flags introduced (ALL default OFF — the stop-gates)
| Flag | Gates | Where enforced |
|---|---|---|
| `HARVIS_BUILD_SHELL` | Build Shell tab (PTY into session container) | config.py feature + terminal.py WS guard (both sides) |
| `HARVIS_SSH_ENABLED` | SSH profile CRUD (connect is 501 even when ON) | remote/ssh_manager.py router dependency |
| `HARVIS_OPENCLAW_SYNC` | applying skills/MCP config to live OpenClaw (dry-run always available) | owui_compat (P45 agent's endpoint) |
| per-adapter `HARVIS_ADAPTER_*` | real social/CAD/sim/slicer adapters | not built — mock only (see adaptive-exemplar-adapters.md) |

## Known follow-ups
- Wave-1 agent incident (session limit) — work was completed/wired by orchestrator + finisher agent; if anything in Customize/Integrations/Notebooks looks half-styled, that's the seam to check.
- open-notebook typecheck + notebooks E2E (upload → grounded chat → report kinds → save-to-note).
- Adaptive Space: linked_runs panel renders nothing yet in SpaceView (mock-execute writes to manifest; surfacing is v1.1).
- P11 was the LIGHT version (sidebar nav + per-phase polish); the full Home/Dashboard IA is future work by design.
- node_modules in worktree is a SYMLINK to main checkout — don't commit it (gitignored anyway).
- P3 NotebookLM parity gaps: no inline citations in reports, chips don't refresh per turn, 12-source grounding cap.
