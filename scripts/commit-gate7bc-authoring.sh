#!/usr/bin/env bash
# CAD Gates 7B + 7C — a prompt authors a part, and the server decides whether it is
# the part that was asked for. One commit, seventeen files.
#
# NOT in the list, on purpose: python_back_end/workspace/orchestration/engine_adapter.py.
# Its _cad_mcp_args() is what carries the CAD context header into the sidecars and
# belongs with this work by subject — but the same file also holds the attachment
# staging from the 2026-08-01 arc, and scripts/commit-groups-2026-08-01.sh already
# names it. git can commit a file once. That script runs first and takes it; its
# group-11 message names this rider explicitly, the same way group 10 names its own.
#
# Run AFTER scripts/commit-gate7a-cadir.sh. That commit is the engine layer; this is
# everything above it, and neither is independently runnable — 7A's routes are in
# here, and this commit's engine calls are in 7A.
#
# WHY THESE TWO GATES SHARE A COMMIT. They were meant to be separate, and the old
# scripts/commit-gate7b-generation.sh (now deleted, replaced by this file) was
# written for that. It named cad_generate.py and cad_bridge.py; 7C then rewrote both,
# and `git commit -- <path>` commits the path's CURRENT content, so running it today
# would have put the DesignSpec, the conformance grade, the tool registry and the
# native model lane inside a commit whose message describes none of them. The choice
# was a message that does not match its diff, or one honest commit per layer. This is
# the second layer.
#
# Local commit only. Nothing is pushed. The lane stays behind the same
# HARVIS_ADAPTIVE_CAD_ENABLED flag it has been behind since Gate 0, and freeform AI
# authoring stays experimental — see the closing paragraph for what is NOT proven.
#
# Verified before this script was written (2026-08-11), in the running stack:
#   docker exec harvis-cad     python -m pytest tests -q               → 196 passed
#   docker exec harvis-backend python -m pytest tests/test_cad_store.py \
#                                     tests/test_cad_tools.py -q       →  80 passed
#   scripted-model E2E against the real dispatcher, engine and Postgres:
#     correct part      → conformance passed, proposal, head NULL
#     wrong + repaired  → repair lands as seq 2, passes, still a proposal
#     wrong, no repair  → conformance failed, proposal, head NULL
#
# Run from the repo root on branch harvis1.2.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

FILES=(
  python_back_end/owui_compat/cad_generate.py
  python_back_end/owui_compat/cad_designspec.py
  python_back_end/owui_compat/cad_conformance.py
  python_back_end/owui_compat/cad_tools.py
  python_back_end/owui_compat/cad_mcp.py
  python_back_end/owui_compat/cad_agent.py
  python_back_end/owui_compat/cad_bridge.py
  python_back_end/owui_compat/cad_router.py
  python_back_end/owui_compat/cad_store.py
  python_back_end/owui_compat/router.py
  python_back_end/tests/test_cad_store.py
  python_back_end/tests/test_cad_conformance.py
  python_back_end/tests/test_cad_normalize.py
  python_back_end/tests/test_cad_tools.py
  front_end/owui/src/lib/apis/cad/index.ts
  front_end/owui/src/lib/cad/CadStudioPanel.svelte
  front_end/owui/src/lib/components/chat/Messages/CadResultCard.svelte
)

MSG="$(cat <<'EOF'
feat(cad): a model authors the part, and the server decides if it is the right one

Gate 7A gave CadIR an execution path but nothing authored one. 7B closed that —
generate, validate, build, repair against a real error — and immediately exposed
the failure that 7C exists for: asked for a 30 mm cube with a 10 mm bore, the
lane produced a valid, watertight, single-solid part of the wrong size and
reported `build succeeded`. Geometry integrity and design conformance are not
the same claim, and only the first was ever checked.

7B — authoring
  cad_generate.py (new) is the generation lane. Ollama's /api/generate with
  stream and think both off and no num_ctx — setting it forces a model reload
  and times out, the same trap the task generator hit at router.py:305. Failure
  is answered 200 with ok:false and the whole attempt list, so a caller sees what
  was tried instead of a bare 500. normalize_document() drops an empty `at` and
  nothing else: every model tested emits "at": {} rather than omitting the key,
  and since `at` is a discriminated union of Points|Grid an empty object matches
  neither, so dropping it decides nothing on the model's behalf. It does NOT drop
  a `select` from a non-fillet op even though that was the single most common
  rejection across four models, because `select` is something the model asked for
  and silently discarding it is exactly the quiet-200-for-the-wrong-part failure
  this subsystem exists to avoid. It stays a reported model limit.
  cad_bridge.py is still explicit-marker-only, deliberately: a natural-language
  detector would turn an ordinary sentence about brackets into a build, and a
  build has a cost and a card.

7C-1 — the answer key the model does not hold
  cad_designspec.py extracts the dimensions and relationships the user actually
  stated into a frozen, visible DesignSpec, and cad_conformance.py measures the
  built solid against it — bounding box, recovered bore diameter, solid count,
  subtracted-feature count — with a fixed tolerance the model never sees and
  cannot argue with. The spec is read from the user's own message, not from the
  model's `description` argument (cad_tools._design_spec records which, as
  design_spec.source), because a model that authors both the part and the answer
  key grades itself. In the scripted E2E the model claimed "a 20 mm cube, exactly
  as asked" and was graded against the sentence the user typed.
  The extractor's own first defect is fixed here rather than shipped: _HOLE_COUNT
  read the 10 in "a 10 mm diameter hole" as a tally of ten holes and failed a
  CORRECT cube. A number carrying a unit can never be the count.

7C-2 — a failed proposal is not the project head
  cad_revisions has no mutable state column and still does not: a proposal is a
  revision with accepted_at IS NULL, and cad_store synthesizes the word. An
  AI-authored revision is appended to the history, is buildable, inspectable and
  comparable, and does not move head_revision. Acceptance is deliberately not a
  tool — POST /revisions/{id}/accept is reachable from the UI only, refuses a
  revision with no succeeded build, refuses one that failed conformance unless
  the caller explicitly acknowledges the failure in the request, and is a one-way
  latch so a double-click and a retry are the same thing.
  create_revision's staleness check is corrected in the same breath, because it
  made the bounded repair impossible: it compared the caller's base against the
  head alone, and a proposal never becomes the head — so on a generated project,
  where the head is NULL, a model told to fix its own wrong part got
  `stale_revision` for doing exactly what it was asked. Both the head and the
  newest revision are honest bases now; anything older is still the silent fork
  the check exists to catch, and a stated base is also the parent, so a repair
  chains to what it repaired.

7C-3 — one tool surface, three ways in
  cad_tools.py is the provider-neutral registry: nine tools, strict schemas, and
  a single dispatch() that owns ownership, quota, the proposal rule and the
  answer key. cad_mcp.py exposes it to the Claude Code and Kimi Code sidecars
  over authenticated MCP; cad_agent.py runs it as native Anthropic/OpenAI tool
  calls for normal chat. Every path shares the one dispatcher, so there is one
  implementation of every rule rather than three that drift.
  The model receives opaque IDs and nothing else — no filesystem path, no
  storage key, no database handle, no worker address. Who is asking, what they
  actually said, and which provider really served the call are injected
  server-side as context the model cannot forge.
  cad_agent.resolve_lane is the honesty gate and answers None unless a real
  stored credential exists for the selected model. What the caller then does with
  that None is 7C-3b's subject, and the first version got it wrong. It does
  NOT delegate to ModelRouter.complete for this: that method calls _resolve_route
  directly, _resolve_route has no Anthropic branch, and a Claude model handed to
  it would silently POST an OpenAI body at a DB-configured Ollama. A lane that
  resolves and then fails is reported as itself; there is no quiet hand-off to
  cad_generate, because a user told a frontier model authored their part deserves
  that to be true.

Verified in the running stack: 196/196 engine, 80/80 store and tools, and a
scripted-model E2E through the real dispatcher, the real engine and real
Postgres — a correct part passes conformance and stays a proposal with the head
NULL; a wrong part repaired once lands the fix as seq 2 chained to the proposal
it repaired and passes; a wrong part the model declines to fix stays failed, a
proposal, and never becomes the head.

7C-3b — the credential that cannot call the API, and the lane built for it
  The provider hop is proven now, and proving it needed a third lane. This
  account's Claude credential is an OAuth subscription token, not an API key, and
  a subscription token cannot drive /v1/messages at all — engine_auth.py:146 says
  so in its own words. resolve_lane therefore missed on both Anthropic branches
  and answered None, cad_bridge read None as "local", and a person who selected
  Opus 5 got a part authored by qwen3:4b with nothing on screen to say so. Every
  step was locally correct and the result was a lie.
  Lane.kind gains claude_code: the real claude CLI inside the harvis-claude-code
  sidecar, driving the same nine tools through the same dispatch(), with its own
  Bash/Write/WebFetch withheld so the CAD tools are all it has. The ids come out
  of the CLI's own stream-json — cad_tools.as_text is json.dumps, so every
  tool_result carries the payload the model was handed — rather than from a
  newest-row query that two concurrent builds would quietly falsify.
  cad_mcp.sidecar_mcp_config puts conversation id, the user's verbatim text and
  the real provider/model in an x-harvis-cad-context header beside the bearer
  token, and engine_adapter._cad_mcp_args forwards it. Without that the sidecar
  has no way to know either, so the DesignSpec answer key would be extracted from
  the model's paraphrase of the request and the part would be graded against its
  own restatement of the brief.
  And the honesty gate is finished on the other side: resolve_lane returning None
  had two unrelated meanings, so unavailable_reason() answers the cloud-model case
  with a sentence naming the remedy, and _local_model() refuses rather than
  substituting when the catalogue is readable and genuinely lacks the selection.
  An unreadable catalogue still overrides nothing — not knowing is not grounds.

Verified live on the subscription credential, twice, same request: lane
claude_code/anthropic/anthropic/claude-opus-5, six tool calls, conformance
passed, 0 repairs, ~21 s; and the stored revision carries design_spec.source
'user_message' with the user's sentence verbatim as the intent.

What is NOT proven, stated rather than left to be discovered: one part shape has
run the sidecar lane and it is a plate — the two requests that originally failed
have not been retried on it. The API-key branch of that lane is written and
untested because there is no Anthropic API key on this deployment. Kimi Code
inherits the context header and nothing routes CAD to it. Freeform AI authoring
therefore stays experimental and off by default. Attachments and imports stay off
until attachment ownership is fixed centrally; printer handoff stays off until
Gate 9.

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
git --no-pager show --stat --oneline HEAD | tail -20
