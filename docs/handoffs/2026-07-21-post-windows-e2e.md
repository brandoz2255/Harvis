# Handoff — 2026-07-21

**Where things stand:** the setup flow is built, adversarially verified, and **pushed** —
46 commits on `origin/harvis1.1-deploy-test` (`origin/harvis1.1` untouched). Then the first Windows
install E2E found **7 blockers**. The stack *works* (login + real inference verified), but it took
**five manual fixes** to get there, so the honest answer to "does one command work out of the box" is
**still no**.

Full findings: `docs/reports/2026-07-20-windows-install-e2e-findings.md`
Session note: Obsidian `code/harvis/2026-07-20-setup-flow-shipped-and-windows-e2e.md`

---

## 1. Do this first — blocker #1, nothing else matters until it's done

**Make `openclaw/config/` ship with the repository.**

`.gitignore:134` ignores `openclaw/` wholesale, and `config/bundled/` + `config/shared/` were never
committed on any branch. Compose bind-mounts **six files** from those paths. When a bind-mount source
doesn't exist, Docker silently creates an empty **directory**; OpenClaw then reads a directory as its
config and crashloops; `backend` declares `depends_on: openclaw`, so **a fresh clone starts nothing —
on any OS.** This is not a Windows problem.

Two viable routes:
- **Force-add a sanitized template tree** past `.gitignore` (`git add -f`) — simpler, self-documenting.
- **Have `install.sh` generate the files** — better if they carry per-instance identity.

⚠️ **Whichever you pick must also handle already-poisoned volumes.** Once Docker has created those
empty directories, the pollution is **persisted in the `openclaw-data` named volume**. Fixing the repo
alone does nothing for anyone who already ran a broken start — the volume needs cleaning, or a
`docker compose down -v`.

**Done when:** a genuinely fresh clone reaches a running `backend` with no manual file seeding.

---

## 1b. The keystone for FEATURES — a SECOND OpenClaw P0 (found 2026-07-22)

Fixing §1 (config ships) gets the stack to *start*. It does **not** revive workspace or build — those
stay dead on a **separate** OpenClaw problem: **device pairing is a version mismatch.** The backend
correctly requests `role: operator` + `operator.admin` (which should trigger
`skipPairingForOperatorSharedAuth`), but pinned **`openclaw v2026.5.22` doesn't honor it** (gateway logs
`v2026.7.1-2` available). Fix = bump the version in `openclaw-browser/Dockerfile`, rebuild, retest the
handshake; fallback is explicit `openclaw devices approve` (the backend persists its device key, so it
sticks). **This is the single highest-value move once the stack starts — it revives workspace AND build.**

**The full 15-issue, `file:line`-cited fix list is `docs/reports/ISSUES-FOR-FIX-2026-07-22.md`.** Work it
top-down. Fresh-clone repro order is at its bottom.

## 2. Then — the clean-slate run (the actual measurement)

Fresh clone → `./install.sh` → touch nothing. This converts one tester's findings into a verified bug
list and gives an honest number for the one-command claim.

It also **exercises `HARVIS_SETUP_CODE` for the first time.** That flow — the feature this entire branch
exists for — **has still never run**, because the carried-over database meant `needs_setup` was already
`false`. To force the real path, wipe only `harvis_pgsql_data` (preserves the ~8 GB model cache).

---

## 3. The blocker list, ranked

| # | Severity | Blocker | Windows-only? |
|---|---|---|---|
| F-04 | **CRITICAL** | OpenClaw config tree never ships → fresh clone starts nothing | **No — any OS** |
| F-05 | HIGH | Double lockout: signup hidden AND setup code closed, no error, no way in | **No — any OS** |
| F-06 | HIGH | Post-login redirect never fires → client-side 404 on a successful login | **No — any OS** |
| F-07 | HIGH | `--check-only` reports occupied ports as free (probes 127.0.0.1 from inside WSL) | Windows/WSL |
| F-08 | MEDIUM | 3 migrations (`cron_jobs`, `workspace_jobs`, `workspace_runs`) never run | **No — any OS** |
| F-09 | MEDIUM | Port 11434 collides with native Ollama | Common on Win/macOS |
| F-10 | LOW | `docker compose up -d` without `--build` → `pull access denied` | No |
| F-03 | HIGH | 532s cold build — no `.dockerignore`, 24 GB context shipped twice | Worst on Docker Desktop |

**Three of the top four are not Windows problems.** They'd break a fresh clone on Linux identically.

**Two of these are ours, from today:** F-05 (T2 has no answer for a non-empty DB whose credentials you
don't have — i.e. the upgrade path) and F-07 (a confident PASS for something the check structurally
cannot see — the exact bug class this effort exists to kill).

---

## 4. Local modifications on the Windows box (not in git)

These were applied by hand to reach a working stack. **They are not fixes — they're the evidence of
what's missing.** Revert before measuring out-of-box:

1. Seeded `openclaw/config/` tree by hand
2. Cleaned the broken shape out of the `openclaw-data` volume
3. Applied 3 migrations manually
4. Added `pull_policy: build` to 7 services *(this one is a genuine durable fix — worth committing)*
5. **`HARVIS_OWUI_ENABLE_SIGNUP=true` in `.env`** — ⚠️ **a local test setting. Revert before that
   instance ever faces a network.**

**Build state:** the remaining 9 services got ~4 minutes in before the session ended. BuildKit resumes
from cache. Loop script was at `/tmp/build_rest.sh` (may clear on reboot; the Windows-side
`HANDOFF-2026-07-21.md` carries it inline).

**Two traps for tomorrow:**
- **Start native Ollama first.** If it isn't running, every service still starts and *looks* healthy but
  there's no inference — and it presents as a Harvis bug, not a missing Windows process.
- **The post-login 404 is not a failure.** Auth succeeded; navigate to `/` manually. This cost hours.

---

## 5. Still open from the security order

- **T3** — hide Share actions everywhere (gate behind a flippable const, don't delete)
- **T4** — Clone chat (reuse `get_chat` + `create_chat`; new chat, differentiated title)
- **T5** — remove `/workspace` + `/admin` from nav via reversible flags

T1 and T2 are closed and verified. Also outstanding: the **6 LOW honesty findings** from the pen-test,
and the **`.dockerignore` before/after timing** (532s is the baseline; the post-fix number is unmeasured).

---

## 6. Review list — captured ideas, NOT scheduled work

Two items captured 2026-07-20. Both are "just a thought" stage — recorded so they aren't lost, not
queued for build.

### R-01 · Add Kimi to the agent engines

**Where Kimi actually is today (verified):** Kimi/Moonshot appears in **6 backend files** —
`moonshot_api.py`, `research_agent.py`, `agent_research.py`, `owui_compat/workspace_bridge.py`,
`tools/openclaw_proxy.py`, `owui_compat/integration_logs.py`. It is used as a **cloud model API by the
orchestrator layer** (planner/writer/vision per `CLAUDE.md`).

**What it is NOT:** one of the four **agent engines** — `opencode`, `codex`, `claude-code`,
`hermes-agent` — each of which is a *containerized CLI* with its own compose service
(`docker-compose.yaml:1002/1025/1044/1066`) driven through the engine adapter.

**So the item is real**, and the interesting question is *which shape it should take*:
- **(a) Containerized CLI engine**, matching the existing four — heaviest, and only justified if there's
  a Kimi CLI worth driving.
- **(b) External/API engine** — Kimi is OpenAI-compatible (`https://api.moonshot.cn/v1`), so it may fit
  the existing external-engine path with **no new container at all**. Likely the cheap correct answer.
- **(c) Leave as-is** — if Kimi's value is as the orchestrator's planner/writer rather than as a coding
  agent, promoting it to "engine" may be miscategorisation rather than a feature.

**Before building:** decide whether Kimi is meant to *write code in a workspace* (engine) or *reason
about the plan* (current role). That determines (a) vs (b) vs (c).

### R-02 · Verify multiple engines can run concurrently, and can be swapped

**The spec to verify:** more than one agent engine active at the same time, with the ability to swap
between them.

**Why this needs verifying rather than assuming:** the engines are separate containers with an adapter
in front, so concurrency *looks* plausible — but the pen-test already found that engine readiness is
reported from **`docker container status == running`**, never by calling the sidecar's API. A wedged
engine reports "ready." So "multiple engines working at once" is exactly the kind of claim the current
readiness surface would happily assert without evidence.

**What a real verification looks like** (not a code read):
- Start two engines, run a real task on each **concurrently**, confirm both produce correct output and
  neither's session/state bleeds into the other.
- Swap engines **mid-session** and confirm the run continues coherently rather than silently resetting.
- Kill one engine while the other is running and confirm the failure is reported honestly, per-engine —
  not as a global outage or, worse, a green tick.

**Prerequisite:** none of this is measurable until F-04 is fixed and the optional engine containers
actually build — five of them (`opencode`, `codex`, `claude-code`, `hermes-agent`, `cad-engine`) were
still unbuilt at the end of the Windows session.

---

## 7. Context

- Roadmap/checklist: `docs/plans/2026-07-18-plan-of-action.md`
- Inventory: `docs/plans/2026-07-19-master-checklist.md`
- Weekly report: `docs/reports/2026-07-20-weekly-development-report.md`
- Standing rules: no push without verification + asking · one commit per task · never commit secrets ·
  gate UI behind a flippable const rather than deleting · `origin/harvis1.1` stays untouched
