#!/usr/bin/env bash
# CAD Gate 7A — make CadIR an execution path. One commit, six files.
#
# The 2026-08-01 commit script covers none of this: it was written before the CAD
# gates and names no cad-engine or cad_* path. Gates 0–6 are already committed
# (603f3617 is Gate 6); this is the first of the uncommitted CAD work.
#
# RE-SCOPED 2026-08-11, and this is the reason: as first written this script also
# named cad_router.py and cad_store.py, which 7A did edit. Gates 7C-1 and 7C-2 then
# rewrote the same two files, and `git commit -- <path>` commits the path's CURRENT
# content — so running the original script today would have buried the DesignSpec,
# the conformance grade and the accept latch inside a commit whose message says
# "CadIR execution path". Splitting those files by hunk is patch surgery nobody
# should run unattended, so the arc is repacked by layer instead: this commit is
# the engine and its one backend client, and everything above it is the second
# commit (scripts/commit-gate7bc-authoring.sh). The cost is that this commit is not
# independently runnable — the routes it serves land in the next one — and saying
# so is better than a message that does not match its own diff.
#
# cadir/interpret.py moves here from the old Gate 7B script for the same reason:
# it is engine code, and the rest of that script's files are backend code.
#
# Local commit only. Nothing is pushed. The lane stays behind the same
# HARVIS_ADAPTIVE_CAD_ENABLED flag it was behind before.
#
# Verified before this script was written (2026-08-04):
#   docker exec harvis-cad python -m pytest tests -q   → 196 passed
#   live E2E in harvis-backend                          → GATE 7A E2E PASS
#   a document build through the running engine         → 200, source_kind "cadir"
#
# Run from the repo root on branch harvis1.2.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

FILES=(
  cad-engine/server.py
  cad-engine/runner.py
  cad-engine/worker_main.py
  cad-engine/cadir/interpret.py
  cad-engine/tests/test_cadir_build.py
  python_back_end/owui_compat/fab_cad.py
)

MSG="$(cat <<'EOF'
feat(cad): CadIR becomes an execution path, and builds the same solid

templates.py said it plainly in its own docstring: nothing called the CadIR
schema, evaluator, budget or interpreter. Every revision in cad_store was
source_kind "recipe". Generating CadIR from a prompt would have shipped a
feature that renders and does nothing, so Gate 7 splits — this is 7A, and 7B
(prompt -> CadIR with bounded repair) is still ahead.

Engine:
  server.py    BuildV2Req.document plus a _one_source validator (exactly one of
               recipe/document); _plan_document runs parse -> resolve -> budget
               in the server process, where recipes.estimate_cost already runs,
               so an over-budget document is refused in milliseconds instead of
               holding a concurrency slot for the full deadline.
               _enforce_output_caps now takes expected_solids as a value rather
               than a RECIPE_SOLIDS lookup: a document's name is not in that
               table and a legitimately multi-body document would have silently
               defaulted to 1.
  runner.py    document= threaded into job.json.
  worker_main.py  a source_kind branch; the child re-parses, re-resolves and
               re-budgets rather than trusting the parent, matching the posture
               recipes._finite already set.
  cadir/interpret.py  _apply_fillet re-authors build123d's fillet failure.
               worker_main's generic handler was flattening it to "geometry engine
               failed (ValueError)", which tells a repair attempt to guess. The
               traceback only survived because the warm pool's worker log outlives
               the deleted workdir (/tmp/cad_pool_worker_*.log) — the non-pool path
               writes into the workdir and loses it. The replacement is built from
               the op_id and radius the caller already sent us, so the rule that no
               kernel string escapes still holds, and a repair loop gets something
               it can act on. Third time this subsystem has paid for that lesson:
               an error a machine cannot act on is worse than no repair loop.

The response gains source_kind. `recipe` keeps its key and carries the
document's own name — both templates are named exactly like their recipes, so
nothing downstream changed shape.

Backend:
  fab_cad      execute(document=...), fenced by cad_ir.check_document instead of
               the KNOWN_RECIPES allowlist. A recipe must name something the
               engine compiled in, so the allowlist is the whole check; a
               document has no name to check against, and this fence is only a
               coarse refusal of the obviously-wrong before it costs a round
               trip. It cannot see the budget and the engine cannot see the DB.
The router and store changes this needs — document on both request models, the
cadir column written and read back, restore re-checking a stored document rather
than trusting it because it was stored — are in the next commit, because Gates
7C-1 and 7C-2 rewrote the same two files and no honest line splits them.

tests/test_cadir_build.py is Gate 5's stated success criterion, only now
executable: for both templates the document and the recipe agree on brep_valid,
solid_count, volume_mm3, surface_area_mm2, bbox_mm, center_of_mass_mm and
mesh_signature — the sorted, rounded triangle set, not a tolerance that happened
to be wide enough. source_hash is asserted to DIFFER: a recipe hashes its name,
a document hashes the document, and cad_revisions compares on it, so a collision
would let a restore resolve to the wrong source. The refusals are checked on the
endpoint and not only in the evaluator's own tests, because a grammar nothing
enforces on the wire protects nothing.

Verified: 196/196 in the cad-engine container, and a live E2E — document build,
geometry identical to the recipe build, revision persisted as cadir with the
document round-tripped, restore rebuilding the same solid from stored bytes, and
an unknown op refused 400 unknown_op.

Co-Authored-By: claude-flow <ruv@ruv.net>
EOF
)"

# --- Commit exactly these paths, and nothing that happens to be in the index -------
#
# The index is NOT empty on this branch — unrelated MCP-runtime work is staged — and
# a bare `git add <paths> && git commit` builds its tree from the WHOLE index, so
# every one of those staged files would ride along inside this CAD commit. Naming the
# paths on `git commit` makes it a partial commit: the tree is HEAD plus these paths
# only, and whatever else is staged stays staged and uncommitted.
#
# `git add` still runs first, because a path git has never heard of cannot be named
# in a pathspec — it is there to make the new files known, not to build the tree.
STAGED_BEFORE="$(git diff --cached --name-only | sort)"

git add -- "${FILES[@]}"
git commit -q -m "$MSG" -- "${FILES[@]}"

# --- Prove it committed what it said it would --------------------------------------
ACTUAL="$(git show --pretty=format: --name-only HEAD | sed '/^$/d' | sort -u)"
EXPECT="$(printf '%s\n' "${FILES[@]}" | sort -u)"
if [ "$ACTUAL" != "$EXPECT" ]; then
  echo "REFUSING TO CONTINUE: this commit does not match the intended file list." >&2
  echo "--- expected ---" >&2; echo "$EXPECT" >&2
  echo "--- actual   ---" >&2; echo "$ACTUAL" >&2
  echo "Undo it with: git reset --soft HEAD~1" >&2
  exit 1
fi

if [ "$STAGED_BEFORE" != "$(git diff --cached --name-only | sort)" ]; then
  echo "NOTE: the staged set changed across the commit. It was:" >&2
  echo "$STAGED_BEFORE" >&2
fi

echo "OK — ${#FILES[@]} files committed; unrelated staged work left untouched."
git --no-pager log --oneline -1
git --no-pager show --stat --oneline HEAD | tail -12
