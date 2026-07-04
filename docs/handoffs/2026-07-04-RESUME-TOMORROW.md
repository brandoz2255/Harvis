# RESUME HERE — Fable 5 marathon (start of next session)

**Worktree:** `/home/user/Harvis/.claude/worktrees/jolly-dhawan-5babcd`
**Branch:** `claude/jolly-dhawan-5babcd` (tip still `bcd6005e` — **nothing committed/pushed/deployed**)
**Status:** P1–P11 code-complete + a verification/polish pass done. Next step is **you viewing it in docker**, then a cleanup + (if it looks good) commit.

---

## ① FIRST THING: view the work in docker

Your running stack is the **main checkout** (`/home/user/Harvis`, compose project `harvis`) — that's why the changes weren't visible; it serves main's files, not the worktree's. Point the same stack at the worktree, reusing your real `harvis_*` data volumes:

```bash
# stop the main-checkout stack
cd /home/user/Harvis
docker compose down

# bring it up from the worktree, REUSING the real data volumes (the project-name pin is essential)
cd /home/user/Harvis/.claude/worktrees/jolly-dhawan-5babcd
COMPOSE_PROJECT_NAME=harvis docker compose up -d

# rebuild ONLY the notebook UI (P3) — it's a built image, not a bind mount
COMPOSE_PROJECT_NAME=harvis docker compose up -d --build open-notebook-ui
```
Open **http://localhost:9000**.

**Switch back to main when done:**
```bash
cd /home/user/Harvis/.claude/worktrees/jolly-dhawan-5babcd && COMPOSE_PROJECT_NAME=harvis docker compose down
cd /home/user/Harvis && docker compose up -d
```

- `COMPOSE_PROJECT_NAME=harvis` is REQUIRED — without it compose names the project after the worktree folder and spins up **empty** volumes (no DB/models).
- `npm run preview` is abandoned (didn't work, not needed).
- **Compose change made:** worktree `docker-compose.yaml` now bind-mounts `./python_back_end/remote:/app/remote:ro` (right after the `vibecoding` mount). **Without it the backend crashes on boot** — `main.py:1322` imports `remote.ssh_manager` and the dir wasn't mounted. Module is inert (`HARVIS_SSH_ENABLED` off). ⚠️ If this ever runs from *main*, that one line must be carried into main's compose too.

---

## ② What to click-test (manual UAT)
1. **Adaptive Space** — sidebar (above Integrations) → type a task → template cards show panel-chips + step/gate counts → Create → complete steps → hit a ✋ gate (confirm modal, audited) → **Run (mock)** on an execute step → entry appears in **Activity & output**.
2. **Build ⚙** — opens **Customize as a right-drawer INSIDE Build** (URL `?panel=customize`), not a bounce to chat. Browser-back closes it; "Full page" link works.
3. **Build dock** — tabs Tasks·Plan·Files·File (Tasks badge; Explorer→File jump). **No Shell tab** should appear (flag off).
4. **Customize** — sticky section-nav chips (Routing·Presets·Orchestration·Skills·Tools·MCP); MCP "Guided setup" wizard beside "Quick add".
5. **Integrations** — five named sections, SSH placeholder card, **Logs** button per card → drawer.
6. **Notebooks** — upload source → grounded chat → generate briefing/FAQ → save-to-note → question chips on empty chat.

---

## ③ Gates still CLOSED (all flags default OFF — decide when to open)
| Flag | Opens | Where enforced |
|---|---|---|
| `HARVIS_BUILD_SHELL` | Build Shell tab (PTY into session container, not host) | config.py + terminal.py WS guard |
| `HARVIS_SSH_ENABLED` | SSH profile CRUD (connect still hard-501; zero ssh libs) | remote/ssh_manager.py router dep |
| `HARVIS_OPENCLAW_SYNC` | apply skills/MCP to live OpenClaw (dry-run always on) | owui_compat sync endpoint |
| per-adapter `HARVIS_ADAPTER_*` | real social/CAD/printer adapters | not built — mock only |

## ④ Known gaps / cleanup backlog for after viewing
- open-notebook `tsc` never run (no node_modules there) — typecheck before trusting P3.
- Backend never booted live on host (FastAPI only in the image) — the docker view above IS the first real smoke test. Watch `docker logs harvis-backend` for import errors on first boot.
- NotebookLM parity gaps: no inline citations in reports; chips don't refresh per turn; 12-source grounding cap.
- Wave-1 agents (P3/P4-5/P6) died on a session limit mid-task; their work was surveyed + finished by hand — **look hardest at Customize / Integrations / Notebooks** if anything's half-styled.
- `node_modules` in the worktree is a symlink to main's — gitignored, don't commit.
- Then: the cleanup round + decide what to commit.

## ⑤ Reference docs (already written)
- `docs/plans/fable5-marathon-plan.md` — full plan + per-phase status ledger.
- `docs/handoffs/2026-07-03-fable5-marathon-leg1.md` — P0/P1.
- `docs/handoffs/2026-07-04-fable5-marathon-leg2.md` — P2–P11 details + flag table.
- `docs/plans/printer-integration-design.md`, `docs/plans/adaptive-exemplar-adapters.md` — design-only.

## ⑥ git status snapshot (uncommitted)
~23 modified + ~15 new files/dirs across `front_end/owui`, `front_end/open-notebook`, `python_back_end/{owui_compat,onb_compat,remote,vibecoding,notebooks}`, `docker-compose.yaml`, and `docs/`. Nothing staged. `git status` for the live list.
