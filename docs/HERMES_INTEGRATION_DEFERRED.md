# Hermes Integration — Deferred Work

This document captures Phases 8 and 9 of the Hermes integration plan
(see `docs/HARVIS_HERMES_VERIFICATION_REPORT.md` for full context). These
phases were deliberately scoped out of the "land it all in one branch"
push that produced commits `97cf594` (Phase 1+2) through `c6a8617`
(Phase 7) on `feat/hermes-integration`. They aren't blocked — they're
just genuinely larger and need product-design decisions that were out
of scope for the foundational ports.

Hermes upstream is a moving target. The Phase 1-3 ports are pinned at
commit `8081425a` (2026-04-27). Phase 3B onwards verified against
`58a6171` (2026-04-29, +205 commits). Re-pin and re-scan upstream
before starting either phase below.

---

## Phase 8 — CLI branding & UX

### What Hermes ships

| Component | Path | LOC |
|-----------|------|----:|
| Slash command registry | `hermes_cli/commands.py` | ~600 |
| Skin engine | `hermes_cli/skin_engine.py` | 882 |
| Banner / ASCII art | `hermes_cli/banner.py` | 588 |
| Status display | `hermes_cli/status.py` | ~400 |
| Setup wizard | `hermes_cli/setup.py` | 3,361 |
| Doctor | `hermes_cli/doctor.py` | 1,273 |
| Profiles | `hermes_cli/profiles.py` | 1,111 |
| Main CLI | `cli.py` (top-level) | ~11,000 |

Plus the React+Ink TUI under `ui-tui/` (~3,000 LOC TypeScript) which is
the modern interactive experience.

### What's portable

The skin engine is the cleanest extract — it's data-driven (YAML skins
under `~/.hermes/skins/`), already documented in `AGENTS.md`, and
demonstrated by the working `plugins/strike-freedom-cockpit/theme/`.
The interface contract: skins customize banner colors / borders, spinner
faces+verbs+wings, tool prefix, response box, branding strings.

What needs Harvis-specific design:

1. **Which CLI surface gets branded** — the existing Harvis CLI footprint
   is small (no equivalent of `cli.py` or `hermes_cli/main.py`). We
   either need to build one (3-4 weeks of work), or we adopt a different
   approach (web-only UI, Discord-as-CLI, ACP editor as the primary
   interactive surface — Phase 2 already shipped that).
2. **`harvis doctor`** — Hermes's doctor checks ~25 things (Python
   version, venv, deps, provider keys, services, file permissions,
   systemd linger, SOUL.md presence). HARVIS's checks would be Postgres
   reachability, Ollama reachability, OpenClaw reachability, Discord
   token validity, etc. Different content, but the report-formatting
   helpers (`check_ok` / `check_warn` / `check_fail` / `check_info`) port
   in <100 lines.
3. **`harvis setup`** — Hermes's wizard is 3,361 lines but is HEAVILY
   modular: `setup_model_provider`, `setup_tts`, `setup_terminal_backend`,
   `setup_agent_settings`, plus 12 per-platform `_setup_<platform>`
   functions. For HARVIS, the equivalent is per-service env-var
   walkthroughs. Could ship in waves — start with model provider, add
   one platform at a time.

### Recommended split

If Phase 8 happens, slice it three ways:

- **8A — Skin engine + branding library** (~1 week). Port
  `hermes_cli/skin_engine.py` + `banner.py`. Provide a `harvis cli theme`
  command that lists / switches skins. No CLI surface to apply it to
  yet — the library just exists.
- **8B — Doctor + setup wizard scaffolding** (~1-2 weeks). Build the
  report helpers + wizard sections framework. Each section is a
  pluggable module. Ship 3-4 sections to start (provider, postgres,
  openclaw); add more incrementally.
- **8C — Full interactive CLI** (~3-4 weeks). This is where the
  product-design decision sits. Options:
    - REPL parallel to `hermes` (full prompt_toolkit + slash commands)
    - thin wrapper that delegates to ACP (the editor is the UX)
    - skip — HARVIS is web-first, no full CLI needed

Don't attempt 8C without a decision on the CLI's role.

---

## Phase 9 — Migration framework

### What Hermes ships

`hermes claw migrate` (`hermes_cli/claw.py` + `optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py`):
- 734 lines of CLI plumbing
- 2,819 lines of migration script
- `--preset full | user-data`, `--dry-run`, `--overwrite`, `--migrate-secrets`,
  `--workspace-target`, `--skill-conflict`, `--yes` flags
- Maps `~/.openclaw` → `~/.hermes` — SOUL.md, MEMORY.md, USER.md,
  TTS assets, allowlisted secrets, workspace agents, AGENTS.md.

### What's portable

The script is a clean fork target IF the inverted direction is what
Harvis needs. Three real adaptation points:

1. **Multi-tenant target** — Hermes is single-user file tree → Harvis
   is per-user Postgres rows. The "copy file from A to B" mental model
   doesn't translate; it becomes "INSERT/UPSERT row(s) for user X."
   Every step of the migrator needs re-targeting at row writes.
2. **Profile model** — Hermes profiles (`~/.hermes/profiles/<name>`) map
   to Harvis users (rows in `users`). Migration produces N user rows,
   one per source profile.
3. **Skill format** — Hermes skills land in
   `~/.hermes/skills/openclaw-imports/`. Harvis skills live in
   `skills/Harvis/<domain>/`. The skill conflict resolution
   (`--skill-conflict skip|overwrite|rename`) needs re-mapping to
   Harvis's plugin architecture (Phase 3B's `plugin.yaml` convention is
   the natural target — imported skills become plugin manifests).

### Recommended trigger

Don't build Phase 9 until Harvis has a real "migrate from another agent
system" need. Likely triggers:

- A user asks how to bring their existing OpenClaw workspace into Harvis.
- A user asks how to bring their existing Hermes profile into Harvis.
- A second third-party agent system shows up and the import shape becomes
  reusable instead of bespoke.

When the trigger arrives, the work is roughly:

- **9A — Migration framework core** (~1 week). Adapter ABC: `discover()`,
  `dry_run() -> Report`, `apply() -> Report`. Generic conflict
  resolution. Idempotent — re-running shouldn't create duplicates.
- **9B — First adapter** (~1-2 weeks). Pick the first source. OpenClaw
  is the obvious choice given how much Harvis already knows about its
  layout. Port the relevant parts of `openclaw_to_hermes.py`, retarget
  to Postgres writes.
- **9C — Optional UI** (~1 week). Settings panel that runs `dry_run` on
  request, shows what would change, and lets the user click Apply.

---

## What's done (so the next person isn't surprised)

| Phase | Commit | Notes |
|------:|--------|-------|
| 1+2 | `97cf594` | Messaging gateway sidecar (Slack + Discord), ACP adapter |
| 3 | `a0c31f5` | Plugin hook registry — 10 valid hook names, dispatcher firings |
| 3B | `b5c94b5` | Plugin manifest + auto-discovery loader (matches Hermes plugin.yaml convention) |
| 4 | `cbcc202` | Memory provider ABC + builtin Postgres provider |
| 5 | `48e92b7` | MCP server registry + OAuth token storage |
| 6 | `38eaf48` | Cron jobs table + scheduler scaffold |
| 7 | `c6a8617` | Per-user SOUL.md storage + loader |

All commits on `feat/hermes-integration`, no upstream, no push. Each
phase has a self-contained smoke test (15+11+8+11+11+9 = 65 checks all
green plus the original Phase 1/2 E2E suites).

## How to resume

1. Re-pin upstream Hermes: `cd /tmp/hermes-agent && git pull --ff-only
   origin main` and note the new commit.
2. Walk the diff against `8081425a` for any architectural changes that
   might invalidate Phases 1-7 (none through `58a6171`, but verify).
3. Pick a phase based on user demand, not the original ordering.
4. Smoke-test against fresh Postgres (the existing tests in /tmp can
   serve as templates).
5. Commit cleanly per phase.
