# Handoff — 2026-08-10 · CAD Gate 8A/8B written, Gate 7D still measuring

Branch `harvis1.2`. Nothing committed. Nothing deployed to `harvis-cad`.

## Where things actually stand

Two threads ran today and neither is finished, for different reasons.

**Thread A — the Gate 7D benchmark is still running.** 23 of 72 runs are in
`/tmp/cad_bench_7d.jsonl` inside `harvis-backend`. At roughly 2.5 minutes a run it needs about
two more hours. It survives being left alone; it does **not** survive `docker compose restart
backend`, because it is a `docker exec … python -` process. If it dies, it is resumable from the
JSONL.

**Thread B — Gates 8A and 8B are code-complete and unverified.** 8A (attachment ownership) needs
a backend restart to register its Postgres owner lookup, and that restart is exactly what would
kill Thread A. 8B (imported geometry) lives entirely inside `harvis-cad`, which is `read_only:
true` with zero bind mounts — so none of it is running until the image is rebuilt, and that
rebuild would also disturb Thread A.

That single conflict is why both are parked rather than proven.

## The 7D partial numbers (23 runs, granite4.1:8b only)

These are real measurements, not projections, and they cover only the first model.

| | count | of |
|---|---|---|
| produced a solid at all | 17 | 23 |
| every gradeable dimension correct | 4 | 17 built |
| end-to-end exact | 4 | 23 attempted |
| refused before geometry | 6 | 23 — 4 `validation_failed`, 2 `invalid_document` |

Report those three denominators separately. "4 of 17" and "4 of 23" answer different questions and
collapsing them is how the old Gate 7 number got misread.

A representative failure, because the shape of the miss matters more than the rate: asked for *a
30 mm cube with a 10 mm bore*, the model built a valid, watertight, single-solid part measuring
90 × 30 × 35 mm. Nothing about it is broken — the geometry is sound, the topology is valid, the
grader is the only thing that noticed it is the wrong part. That is the argument for
server-enforced dimensional conformance existing at all.

One caution for whoever reads the JSONL next: the per-check verdict field is **`ok`**, not `pass`,
and `ok` can be `null` when a dimension is not recoverable from the measured solid. Grading with
`all(c["pass"])` silently reports zero successes. It cost me a wrong number today before I caught
it.

## What was written today

### Gate 8B — imported reference geometry (STEP / STL / 3MF / BREP)

New and changed in `cad-engine/`:

- `importers.py` — extension→parser mapping, structural prechecks, and the parser call. Every
  refusal carries a code and a sentence naming what is wrong with the file. Added `ERROR_CODES`,
  an exported frozenset, so the HTTP layer can answer 400 for "your file is wrong" and 500 for
  "we are wrong" without a hand-copied list that drifts.
- `validation.py` — new `import_verdict`. The authored-geometry `verdict` asserts solid count,
  positive volume and watertightness; all three are wrong for an import. An STL re-imports as a
  `Face` with no volume, a STEP's solid count is discovered rather than expected, and a reference
  mesh is allowed to be open. What survives is a finite positive bounding box always, plus B-Rep
  validity and volume only when the parser handed back a real solid.
- `server.py` — `POST /cad/v2/import`. **The body is the file**: raw bytes, metadata in the query
  string. Base64 would inflate a 32 MB asset to 43 MB and then hand it to a JSON parser; multipart
  would add a parser dependency to the one container whose whole argument is that it has very few.
  The 64 KB body cap became a per-route map so the import route can be the single exception, and
  the route re-reads its own body through a streaming capped reader — the header-based middleware
  cannot stop a chunked request that declares no `content-length`.
- `worker_main.py` / `runner.py` — the `source_kind: "import"` branch. Parsing happens in the
  killable child, not the server. That is why imports waited for Gate 1B: a malformed STEP is
  outside code driving OCCT, and 1B is what makes a build that will not finish stoppable.
- `tests/test_import.py` — new. Refusal cases run without OCP (build123d is imported lazily);
  round-trip cases need the container. Includes a drift guard that scans `importers.py` for every
  `ImportRejected("<code>"` and asserts the set equals `ERROR_CODES`, and a negative control
  proving the authored verdict *would* have failed the same mesh — without it the import-verdict
  tests prove nothing new.

**GLB and glTF are refused by name, with the reason.** build123d ships no glTF reader, and
`trimesh` and `pygltflib` are not installed. GLB stays an export format here, not an import one.
`/health` therefore advertises `import_kinds` separately from `formats_available` — publishing one
list for both directions would promise a round trip that does not exist.

Measured import behaviour, from a live 10×20×30 box: STEP → `Solid`, volume exactly 6000.0; 3MF →
one `Solid` (lib3mf rebuilds the closed shell); STL → `Face`, area 2200.0, no volume.

All five touched engine files pass `python3 -m py_compile`.

### Gate 8A — attachment ownership

Written, not verified. `resolve_attachment_bytes` now takes an `owner_id`, and `main.py` registers
a Postgres owner lookup at startup. Until the backend restarts there is a live window where
lazily-imported paths run the new module with no lookup registered, so an OWUI-store attachment can
fail closed. Not dangerous, but it is a real behaviour change that nobody has watched happen yet.

## Do this next, in order

1. Let the benchmark finish (about two hours). Do not restart the backend until it does.
2. Report 7D with the three denominators above, and state two things plainly: the extractor was
   fixed *before* the measured run, and the attempted prompt fix for the missing `mode: "subtract"`
   cost every build (0 of 8) and was reverted. The `mode` gap is a **finding**, not a fixed item.
3. `docker compose restart backend`, confirm `✅ Attachment ownership lookup registered` in the
   logs, then verify a real Build attachment still stages and a real chat image still reaches a
   model. That closes 8A.
4. `docker compose --profile cad build cad-engine && docker compose --profile cad up -d
   --force-recreate cad-engine`, then run `tests/test_import.py` in the container. That is the
   first moment any of Gate 8B has executed.
5. Backend side of 8B: a `cad_router.py` endpoint that resolves the uploaded asset through the
   now-ownership-checked `resolve_attachment_bytes`, POSTs the bytes to `/cad/v2/import`, and
   persists the artifact plus its provenance blob.

Then 8C (viewport markup) and 9 (fabrication handoff). 7C-4 (cancellation end-to-end) and 7C-5
(browser E2E) are still open behind them.

## Still waiting on you

- Run `./scripts/commit-gate7a-cadir.sh`, then `./scripts/commit-gate7bc-authoring.sh`, in that
  order — `git commit` is blocked for the assistant. 7D, 8A and 8B all touch the same files, so
  the scripts' `git commit -- <path>` semantics will sweep later content into the earlier commits
  unless they are repacked first.
- `./scripts/commit-groups-2026-08-01.sh` (14 groups, no CAD paths).
- Rotate the Kimi/Anthropic key and `OPENCLAW_GATEWAY_TOKEN` — both still appear in the event log
  history.
- Put `HARVIS_ADAPTIVE_CAD_ENABLED=true` in `.env`. It is currently only a shell-exported variable,
  so the next `docker compose up -d backend` turns the whole CAD lane off.
- Add a cloud API key in the app if you want the Claude/Kimi CAD lane proven — `user_api_keys` has
  zero rows, so that hop cannot be demonstrated on this box.

## Gotchas worth keeping

- `docker cp` **into** `harvis-cad` fails: the rootfs is read-only. Use
  `docker exec -i harvis-cad sh -c 'cat > /tmp/f.py' < localfile`.
- A heredoc piped into `docker exec <c> python -` silently produces no output. Write the file first.
- `python_back_end/tests` is not bind-mounted; `docker cp` test files in or pytest runs the image's
  stale copy.
- Never `grep` on this box — it resolves to `ugrep` and wedges. Python + `re`, or `rg`.
