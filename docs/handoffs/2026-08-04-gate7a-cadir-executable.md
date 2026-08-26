# Handoff — 2026-08-04 · CAD Gate 7A: CadIR becomes an execution path

**Branch:** `harvis1.2` @ `603f3617` (`feat(cad): the Gate 6 composer and settings surfaces`)
**State:** Gate 7A done, live-verified, **uncommitted**. Commit script written and syntax-checked.
**Session note:** `notes-vault/code/harvis/2026-08-04-cadir-becomes-executable.md`

---

## Run this first

```bash
./scripts/commit-gate7a-cadir.sh
```

One commit, seven files. `git commit` is blocked for the assistant, so this has to be you. The
2026-08-01 commit script is separate and still unrun (checklist #116) — it covers the agent-reach /
free-provider / redaction arcs and names **no CAD path at all**, so the two scripts don't overlap.

---

## What changed

Gate 7 in the plan is "prompt → CadIR with bounded repair." Reading the code first turned up the
reason to split it: `cad-engine/cadir/templates.py:13-16` states plainly that the recipes remain the
execution path and nothing in CadIR is wired into `/cad/execute` or `/cad/v2/build`. Every revision
in `cad_store` was `source_kind: "recipe"`. Generating CadIR from a prompt would have stored a
document, rendered it, and built the part from a hardcoded Python function that ignored it.

**7A = make CadIR executable. 7B = prompt → CadIR.** 7A is what's in the tree.

### Engine — `cad-engine/` (no bind mounts)

Changes here need a rebuild, not a restart:

```bash
docker compose --profile cad build cad-engine
docker compose --profile cad up -d --force-recreate cad-engine
```

- **`server.py`** — `BuildV2Req.document` plus a `_one_source` model validator (exactly one of
  `recipe`/`document`; both present would force the server to pick one silently). `_plan_document`
  runs parse → resolve → `cadir.check` **in the server process**, where `recipes.estimate_cost`
  already runs, so an over-budget document is refused in milliseconds instead of holding a
  concurrency slot for the full 20 s deadline. `_enforce_output_caps` now takes `expected_solids` as
  a **value** — it used to do `RECIPE_SOLIDS.get(recipe, 1)`, and a document's name isn't in that
  table, so a legitimately multi-body document would have silently defaulted to 1.
- **`runner.py`** — `document=` kwarg threaded into `job.json`.
- **`worker_main.py`** — a `source_kind` branch (`"recipe"` is the default, so every pre-Gate-7
  caller keeps meaning what it meant). The child re-parses, re-resolves and re-budgets rather than
  trusting the parent, matching the posture `recipes._finite` set in Gate 1A. Pydantic
  `ValidationError` is summarized rather than echoed — its string form names every field it walked.
- **`tests/test_cadir_build.py`** — new, 16 tests.

Response gains `source_kind`. `recipe` keeps its key and carries the document's own `name` — both
CadIR templates are named exactly like their recipes, so nothing downstream changed shape.

### Backend — `python_back_end/owui_compat/` (bind-mounted)

```bash
docker compose restart backend       # NEVER `up -d backend` — see the flag warning below
```

- **`fab_cad.py`** — `execute(..., document=...)`, fenced by `cad_ir.check_document` instead of the
  `KNOWN_RECIPES` allowlist. A recipe must name something the engine compiled in, so the allowlist
  is the whole check; a document has no name to check against, and this fence only refuses the
  obviously-wrong before it costs a round trip. It can't see the budget; the engine can't see the DB.
  Neither layer substitutes for the other.
- **`cad_router.py`** — `document` on both request models, `_clean_source()`, `_spec()` writes the
  `cadir` column, `_start_build`/`_run_build` thread it, and `restore_revision` **re-checks** the
  stored document rather than trusting it because it was stored.
- **`cad_store.py`** — `_row_revision` now returns `cadir`. **It was dropping it.** `SELECT r.*`
  returned it and `create_revision` wrote it; the mapper never copied it out. Nothing was broken yet
  because no revision had ever been a document, but the first CadIR revision would have been
  unrestorable — there is no registry to look a document's name up in.

---

## Verification (all run, all passed)

```
docker exec harvis-cad python -m pytest tests/test_cadir_build.py -q   →  16 passed in 25.61s
docker exec harvis-cad python -m pytest tests -q                       → 196 passed in 111.64s
live E2E inside harvis-backend                                         → GATE 7A E2E PASS
```

The E2E created a project from a document, polled the build, compared validation against a recipe
build, checked persistence, and restored a revision. It also left **four test CAD projects in the
database** — clean those up when convenient.

Direct probe of the running engine after the rebuild returned `200` with `source_kind: "cadir"` and
the brick at 39.8 × 19.8 × 12.0 mm.

**What is compared, and why not bytes:** STEP embeds a one-second-resolution wall-clock timestamp
and 3MF is a ZIP that differs on two writes in the same second — Gate 2 measured both. The gate is
the canonical source hash, the measured geometry, and the normalized `mesh_signature` (sorted,
rounded triangle set). Document and recipe match on all of it. `source_hash` is asserted to
**differ**: a recipe hashes its name, a document hashes the document, and `cad_revisions` compares
on it, so a collision would let a restore resolve to the wrong source.

---

## Recon sweep — state of the stack right now

| Check | Result |
|---|---|
| Mount drift on the three `owui_compat` modules | none — host and container hashes match |
| `HARVIS_ADAPTIVE_CAD_ENABLED` in the running backend | `true` |
| `/api/cad/*` routes | registered — real paths `401`, bogus paths `404` |
| CAD engine health | 2 recipes, 4 formats, 2-worker warm pool, 20 s deadline |
| owui build vs source | build 15:42 > newest source 15:40; nginx restarted after; `/harvis/cad` → `200` |
| CAD tables | 8 projects · 20 revisions · 13 builds · 36 artifacts · 4 `cadir` revisions |
| Containers | all 24 Harvis containers up |

### Three things that need a decision

1. **`/openapi.json` looks fixed and isn't.** Through nginx on `:9000` it returns `200` — that's the
   SPA fallback HTML, not the schema. The backend itself still `500`s on the `SearchRequest`
   forward-ref in `notebooks/router.py`, unchanged since 07-30. Don't read the `200` as resolved.
2. **Two files deleted on disk, still tracked at HEAD** — `python_back_end/api/__init__.py` and
   `api/tts_routes.py`, unstaged and unexplained. Nothing imports them (only reference anywhere is
   `masterprompt3.md`), so nothing breaks, but they sit in the dirty set awaiting your call.
3. **The CAD flag is shell-only.** `.env` is still empty, so any `docker compose up -d backend`
   re-bakes the env and turns the lane off. `restart` is safe; `up -d` is not. Persisting
   `HARVIS_ADAPTIVE_CAD_ENABLED=true` in `.env` would close this.

---

## Next: Gate 7B

Prompt → DesignSpec → CadIR patch → static validation → execute → validate → **bounded repair** → a
*proposed* revision the user accepts. Constraints from the plan, unchanged:

- structured output validated against the schema; **no arbitrary Python**
- a hard repair cap; patches preferred over regeneration
- no silent provider or cloud fallback
- assumptions shown before any accuracy claim
- benchmarked on dimensions / solid count / validity / feature count / runtime / repair attempts —
  **never screenshot similarity**
- **stop rule:** if no locally-installed model clears the benchmark, report the numbers. Do not
  paper over it.

Local candidates: `gpt-oss:20b`, `gemma4:e4b`, `granite4.1:8b`, `gemma3:12b`, `llama3.1:8b`,
`qwen3:4b`. The dev rig has 8 GB of VRAM and that is the real constraint.

The structured selection chip deferred from Gate 6 belongs here — it only becomes meaningful once a
prompt can revise an existing project, and `cad_bridge.py` currently calls
`cad_store.create_project(...)` on every chat build.

Then Gate 8 (attachments / imports / markup — blocked on the missing ownership check at
`attachments.py:99-107`) and Gate 9 (downstream fabrication).

---

## New idea logged — multiple engines at once

Raised this session, captured as a spark in `notes-vault/projects/multi-engine-concurrency.md`, not
built. Grounded findings:

- Parallel fan-out already exists — `run_orchestrated` spawns N isolated sub-agents in their own
  clones (`workspace/kimi_workspace.py:571-613`).
- But `vibecode_sessions.engine` is **one column per session**
  (`workspace/orchestration/__init__.py:80-83`), so every sub-agent in a fan-out is the same engine.
- The per-session `asyncio.Lock` (`orchestration/session_turn.py:65-73`, taken at `:367`) serializes
  turns on purpose — two turns must never edit one working tree. That lock is correct and should
  survive whatever gets built.

Three different features hide behind the one sentence and share almost no implementation: **RACE**
(same task, N engines, pick a winner — the hard part is judging), **SPLIT** (subtasks by engine
strength — needs a per-engine capability model that doesn't exist), and **PARALLEL SESSIONS** (N
unrelated jobs — mostly plumbing, and the honest v0). That fork gets answered before anything is
scoped.
