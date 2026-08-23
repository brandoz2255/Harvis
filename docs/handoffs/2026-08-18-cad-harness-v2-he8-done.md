# CAD Harness V2 — tranche 1 (evidence layer): HE-0 … HE-8 done, HE-9 next

**Date:** 2026-08-18
**Branch:** `harvis1.2` in the main checkout at `/home/user/Harvis`
(**not** the `jolly-dhawan-5babcd` worktree — that one is 8 commits behind and has none of
this code; its dirty files are an unrelated pass and were never touched)
**Plan:** `~/.claude/plans/gsd-ultraplan-phase-harvis-adaptive-ui-iridescent-lightning.md` (Rev 2)
**Nothing is committed.** Everything below is on disk and deployed to the running stack.

---

## Where it stands

| Gate | State |
|---|---|
| HE-0 … HE-7 | done, verified, deployed |
| **HE-8 — disposable experiments** | **done, verified** — 29 new tests, full suite green |
| HE-9 — measurement-driven repair | **not started**; reconnaissance only (below) |
| HE-10 — Kimi routing + real Claude/Kimi E2E | not started |

**Test baseline: 515 passed, 13 skipped** (was 486/13 before HE-8). Run it with:

```bash
cd /home/user/Harvis && tar -C python_back_end -cf - tests | docker exec -i harvis-backend sh -c 'rm -rf /tmp/pbe2 && mkdir -p /tmp/pbe2 && tar -C /tmp/pbe2 -xf -' && docker exec harvis-backend sh -c 'for p in owui_compat workspace integrations research skills api rag_corpus main.py; do ln -sfn /app/$p /tmp/pbe2/$p; done' && docker exec harvis-backend sh -c 'cd /tmp/pbe2 && PYTHONPATH=/app python -m pytest tests -q -p no:cacheprovider'
```

(`python_back_end/tests` is **not** bind-mounted — without the `tar` step pytest runs the
image's stale copy and reports a pass that means nothing.)

---

## What HE-8 actually built

An experiment is a disposable working branch off a revision. A repair round runs inside it,
and at most one revision comes back out — only if something worked. That closes #176 / DE-3
and it is the thing HE-9 depends on.

**Files touched (all uncommitted):**

- `python_back_end/owui_compat/cad_store.py` — `cad_experiments` DDL + `cad_builds.experiment_id`
  in `CAD_SCHEMA_SQL`, plus 10 query patches
- `python_back_end/owui_compat/cad_experiments.py` — **new**, 490 lines, the behaviour
- `python_back_end/owui_compat/cad_tools.py` — 1114 → 1325 lines, four new model-facing tools
- `python_back_end/tests/test_cad_experiments.py` — **new**, 594 lines, 29 tests

**The four tools:** `cad_open_experiment`, `cad_experiment_build`, `cad_promote_experiment`,
`cad_abandon_experiment`. All non-read-only, all through the existing `dispatch()` fence, no
new execution path.

### Three design decisions worth not re-deriving

**An experiment build keeps `revision_id` pointing at the base revision** and carries a new
nullable `cad_builds.experiment_id`. Artifacts, quota, the reaper and the render binding all
key on `revision_id`; the alternative needed a second implementation of each. The cost is paid
once, in **9 query sites that now say `experiment_id IS NULL`** — and there is a test that
asserts all of them at once, because missing one shows a failed attempt in the user's workspace
as if it were their part.

**The frozen spec is unreachable from inside an experiment.** `design_spec` is copied at open
time and hashed into `spec_sha256`; `record_attempt` takes only cadir + parameters, so there is
no column an attempt could write a spec into. "An experiment may not weaken the DesignSpec or
widen a tolerance" is therefore a property of the schema, not a rule someone has to remember —
and the test for it reads the module's own source and asserts no `UPDATE` writes those columns.
A spec edited out of band refuses to promote with `spec_drift`.

**Promotion refuses `failed`, allows `unverified`.** `unverified` is the common grade for
anything the regex extractor could not state a check for; refusing it would make experiments
useless on exactly the parts that need them. The promoted revision is still a **proposal** —
`created_by` is the experiment's, which is `'ai'` for every repair loop, so `cad_store.is_proposal`
keeps the head where it is. No new enforcement mechanism was added, and there is a test that
says so.

---

## HE-9 — what was learned before stopping

Nothing was written. The reconnaissance:

**Two different `MAX_REPAIRS`, and only one of them should rise.**

- `cad_generate.py:74` — `HARVIS_CAD_MAX_REPAIRS`, default 2. This loop runs **before** any
  revision exists, entirely in memory. It burns nothing. Leave it.
- `cad_agent.py:151` — `HARVIS_CAD_AGENT_REPAIRS`, default 1. This is the one the plan means:
  each repair here is a real `cad_propose_revision` + build, so it burns permanent history.
  It stays at 1 until repairs actually run inside experiments — which is the work, not a
  side effect of HE-8 landing.

**So HE-9's agent-lane work is:** rewrite `_WORKFLOW` step 4 (`cad_agent.py:371-375`) so a
`conformance_status: failed` sends the model to `cad_open_experiment` → `cad_experiment_build`
→ `cad_promote_experiment` / `cad_abandon_experiment` rather than to another
`cad_propose_revision`; then and only then raise the budget to a hard cap.

**The repair prompt** (`cad_generate.build_conformance_prompt`, `:788`) currently prints
`f"- {c['requirement']}: {c['detail']}"`. The plan wants the numbers and the provenance:
*"cavity_depth measured 3.02 mm at target `lid/opening_plane→lid/cavity_floor`, spec states
5.5 mm ±0.1 (method plane_gap/v1)."* HE-5's check records already carry `measured`, `expected`,
`tolerance`, `basis`, `method`, `method_version` — the prompt just is not reading them yet.

**Careful with that function.** Its docstring records two measured regressions: the
minimal-edit instruction has to be withheld when a *structural* check failed (a count cannot be
fixed by changing a number), and softening "change nothing else" put a stud back at the wrong
height 0/6. Do not simplify the `gap_case` / `structural` branching.

**Still to do beyond the prompt:** a repair that improves no measurement stops the loop rather
than spending the budget (needs a round-over-round comparison of `checks[].measured`), and
`_author_via_sidecar` hardcodes `"repairs": 0` at `cad_agent.py:818` — it has been reporting a
count it never computed.

---

## Known-open, unchanged from yesterday

- **`kimi-code/*` resolves to no CAD lane** and silently drops to the local generator
  (`provider_route.py:44`, `cad_agent.resolve_lane:190`). Release blocker for HE-10.
- **The `render_framing` reframe-retry from the plan text was not implemented.** Captures always
  frame via `aimAt` at the fitted distance, so a framing warning means an unusual part rather
  than a fixable framing; the upload succeeds with the warning attached to `meta.qc`.
- **The mask pass has not been confirmed in a real browser.** MCP Chrome tabs are always
  `visibilityState: 'hidden'`, which throttles `requestAnimationFrame` — exactly what a WebGL
  readback depends on.
- Defects found and left unfixed: the "Creating the project — refused" `unknown_field`;
  `cad_designspec.extract()` dropping "24 mm outer diameter" and "60 mm by 40 mm"; "mounting
  block" misrouting into the studded-brick recipe; the API-key Anthropic lane never requesting
  thinking in `_complete_anthropic`; `TypeError: this.traverse is not a function` from the
  viewer's dispose path.

---

## Next action for the user

**`git add` and commit the HE-0 → HE-8 files.** `git commit` is blocked for the assistant and
no existing commit script covers these paths. HE-8 is green on both halves, so the whole
HE-0 → HE-8 span is safe to commit as one group or eight.

Files in the span, all under `python_back_end/`:
`owui_compat/{cad_store,cad_tools,cad_router,cad_designspec,cad_conformance,cad_generate}.py`,
`owui_compat/{cad_evidence,cad_render_recipes,cad_render_qc,cad_experiments}.py` (new),
`cad-engine/{targets,measure}.py` + `cad-engine/tests/` (new), `tests/test_cad_*.py`,
and `front_end/owui/src/lib/cad/CadViewer.svelte`.

Two credentials are still owed a rotation from earlier sessions: the Kimi/Anthropic key and
`OPENCLAW_GATEWAY_TOKEN`.
