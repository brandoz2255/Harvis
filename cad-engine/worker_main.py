"""The child process that actually runs geometry (Gate 1B).

One of these per build. It is spawned by :mod:`runner` into its own process group
so it can be killed outright, which is the whole point of Gate 1B: OCP holds the
GIL through native OpenCascade calls, so geometry running inside the server process
cannot be interrupted by anything — not a timeout, not a cancelled future, not a
dropped connection. Measured at Gate 0: one malformed request starved ``/health``
for 43.269 s.

Contract with the parent, deliberately file-based rather than pipe-based:

* ``argv[1]`` is a workdir the PARENT created and the PARENT removes.
* ``<workdir>/job.json``   in   ``{"source_kind": "recipe"|"cadir", "recipe": str,
  "document": {...}, "params": {...}, "step": bool, "formats": ["stl", "step", ...]}``
  — ``source_kind`` defaults to ``"recipe"``; ``document`` is the CadIR source and is
  read only when it is ``"cadir"``.
* ``<workdir>/part.<ext>`` out  one file per requested format
* ``<workdir>/result.json`` out ``{"ok": true, ...}`` or ``{"ok": false, "error_code", "message"}``
* stdout/stderr go to ``<workdir>/worker.log``; nothing is written to a pipe.

``formats`` is the Gate 2 addition, and it is deliberately on the *inner* contract
only. GLB and 3MF become production code the moment this file writes them, while
``/cad/execute`` keeps asking for exactly ``["stl", "step"]`` and keeps returning the
response shape the backend already parses. Unfreezing the HTTP contract is Gate 3's
job; doing it here to save one endpoint would break the only existing client.
``step: bool`` is still honoured when ``formats`` is absent.

Files, not pipes, because a pipe the parent is not draining fills at 64 KB and
deadlocks the child — and the parent cannot drain it while it is also enforcing a
deadline without another thread. OCCT writes to stderr on its own schedule, so the
pipe would be carrying data we never asked for.

This process re-validates its parameters instead of trusting the ones the parent
already checked. Same reason ``recipes._finite`` re-checks after the schema: the
inner layer never trusts the outer one.
"""
from __future__ import annotations

import json
import os
import resource
import sys
import traceback


def _pin_to_allotted_cpus() -> None:
    """Confine this build to the CPUs the parent allotted it, BEFORE OCP is imported.

    Measured at Gate 2: one 8x8 brick build spawned **47 threads**. The container is
    capped at 2.0 CPUs, but ``sched_getaffinity`` still reports the host's 16, and every
    thread pool in the stack — OCCT's, OpenBLAS's, OpenMP's — sizes itself from that.
    Two concurrent builds put ~90 threads on a 2-CPU budget, and the second build's main
    thread parked in ``futex_do_wait`` at 1.6 s of CPU and never moved again: it was
    killed by the 20 s deadline having produced nothing, while the first finished at its
    solo speed. That is not the concurrency the cap advertises.

    Pinning fixed both halves. Confined to its own CPU a build stops thrashing (an 8x8
    went 1.98 s -> 1.12 s *solo*), and two of them stop fighting over one budget.

    Order matters: OpenBLAS sizes its pool at import and OCCT sizes its at first use, so
    this has to run before ``import recipes`` pulls in build123d. That is why it is a
    call at module scope rather than something tidy inside ``main()``.
    """
    raw = (os.environ.get("CAD_CPU_AFFINITY") or "").strip()
    if not raw:
        return
    try:
        cpus = {int(part) for part in raw.split(",") if part.strip()}
    except ValueError:
        return
    if not cpus:
        return
    try:
        os.sched_setaffinity(0, cpus)
    except OSError:
        # A restricted cpuset or a non-Linux host. The build is still correct without
        # the pin; it is only slower, so this is not worth failing over.
        pass


def _cap_occt_thread_pool() -> None:
    """Size OCCT's thread pool to the CPUs this process actually has.

    OCCT builds its default pool from the host's core count and ignores the affinity
    mask, so a worker pinned to one CPU still created **16** threads on first build —
    measured here, and measured at *build* time rather than import time (1 thread
    through every import, 16 the moment geometry runs).

    Those 16 were never parallelism. Pinned to a single CPU they are contention, and
    capping the pool is faster on every case measured, on the full job rather than
    just solid construction: 14x14 brick 10.356 s -> 9.762 s, 12x12 6.633 -> 6.318,
    8x8 2.077 -> 1.995. Triangle counts, volumes and **mesh signatures are identical**
    across all five cases, so this changes cost and nothing else.

    It also has to be true for the warm pool to exist at all. `pids_limit` counts
    threads on Linux, and a worker that holds 16 of them for its whole life instead of
    for the duration of one build put two resident workers plus uvicorn at 66 of 128
    PIDs. The suite runs inside this same container by design, so a second interpreter
    tipped it over and thread creation started failing — surfacing as anyio's
    ``RuntimeError: can't start new thread`` and, to the caller, a 20 s build_timeout.
    One thread per worker instead of sixteen is what makes the pool fit under a limit
    that stays where Gate 1A put it.

    After the pin, so ``sched_getaffinity`` reports the slice rather than the host.
    """
    try:
        want = int(os.environ.get("CAD_OCCT_THREADS") or len(os.sched_getaffinity(0)))
    except (OSError, ValueError):
        return
    try:
        from OCP import OSD
        OSD.OSD_ThreadPool.DefaultPool_s(max(1, want))
    except Exception:
        # A different OCP build, or a pool already in use. The build is still correct
        # without the cap — only slower and thread-hungrier — so this never fails a job.
        pass


_pin_to_allotted_cpus()
_cap_occt_thread_pool()

import cadir  # noqa: E402
import exporters  # noqa: E402
import importers  # noqa: E402
import manifest  # noqa: E402
import measure  # noqa: E402
import measure_spec  # noqa: E402
import recipes  # noqa: E402
# Aliased because `_finish` takes a parameter called `targets` — the export paths — and
# the name would otherwise be shadowed exactly where the module is needed.
import targets as part_targets  # noqa: E402
import validation  # noqa: E402
from cadir import interpret as cadir_interpret  # noqa: E402


def _peak_rss_bytes() -> int:
    """Linux reports ``ru_maxrss`` in kibibytes. Reported back so the parent can
    record what a build actually cost rather than inferring it from the container,
    where concurrent builds are indistinguishable."""
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _write(workdir: str, payload: dict) -> None:
    """Write the result atomically. A partially-written result.json read by the
    parent after a kill would be worse than no file at all — the parent treats a
    missing file as "the child died", which is the truth."""
    tmp = os.path.join(workdir, "result.json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, os.path.join(workdir, "result.json"))


def _run_job(workdir: str) -> int:
    """Build one job out of ``workdir``. Always leaves a ``result.json`` behind.

    "Always" is the contract that makes warm-worker mode possible. A one-shot child
    could signal a malformed job by exiting non-zero and writing nothing, because the
    parent notices the exit. A warm worker does not exit, so a silent return would
    leave the parent polling for a file that is never coming until the deadline fires
    — a 20 s stall reported as a timeout, for what is really a parse error.
    """
    try:
        with open(os.path.join(workdir, "job.json"), encoding="utf-8") as fh:
            job = json.load(fh)
        # Two source kinds, one job file. `recipe` names a vetted Python function;
        # `cadir` carries a declarative document the interpreter walks. The default is
        # `recipe` so every caller written before Gate 7 keeps meaning what it meant.
        source_kind = job.get("source_kind") or "recipe"
        if source_kind not in ("recipe", "cadir", "import"):
            raise ValueError(f"unknown source_kind: {source_kind}")
        document = job.get("document")
        recipe = job.get("recipe")
        asset = job.get("asset")
        if source_kind == "cadir":
            if not isinstance(document, dict):
                raise ValueError("a cadir job needs a document object")
        elif source_kind == "import":
            # A bare filename, never a path. The parent wrote the bytes into this same
            # workdir; letting the job name a path would let it name any path.
            if not isinstance(asset, str) or not asset or os.path.basename(asset) != asset:
                raise ValueError("an import job needs an asset filename")
        elif not isinstance(recipe, str) or not recipe:
            raise ValueError("a recipe job needs a recipe name")
        params = job.get("params") or {}
        # What node ids are hashed from. The caller owns it because the alternative —
        # the document's own `name` — is a field the authoring model writes freely, so
        # a model that renamed the document between two turns silently reissued every
        # id, resetting selection and the per-part colours keyed on them. A caller that
        # sends nothing keeps the old behaviour, which is what the recipe path and every
        # pre-CS-2 client still rely on.
        scope_override = job.get("scope")
        if scope_override is not None and (not isinstance(scope_override, str)
                                           or not scope_override.strip()):
            raise ValueError("scope must be a non-empty string when given")
        want_step = bool(job.get("step", True))
        requested = job.get("formats")
        if requested is None:
            requested = ["stl", "step"] if want_step else ["stl"]
        # STL is not optional: it is the mesh mesh_report and mesh_signature read, so
        # dropping it would leave the parent unable to check anything it was sent.
        formats = ["stl"] + [f for f in requested if f != "stl"]
        unknown = [f for f in formats if f not in exporters.FORMATS]
        if unknown:
            raise ValueError(f"unknown export format(s): {unknown}")
        # Re-parsed here even though the server already validated it, for the same
        # reason every other field on this job is: the inner layer never trusts the
        # outer one. A malformed list is `invalid_job`, not a crash halfway through
        # measuring, because a half-written measurement set reads as a verdict.
        wanted = measure_spec.parse(job.get("measurements"))
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "invalid_job",
                         "message": f"the job description could not be read "
                                    f"({type(e).__name__})"})
        return 2

    targets = {f: os.path.join(workdir, f"part.{f}") for f in formats}
    stl_path = targets["stl"]

    # Resolution and, for a document, the budget too. The parent ran both already;
    # this is the inner layer re-checking rather than trusting the outer one, the same
    # posture `recipes._finite` takes after the schema has already had its say.
    # An import has no parameters to resolve and no budget to price — the file is the
    # source. What it does have is a parser reading bytes we did not write, which is
    # why it runs here, inside the process the parent can kill, rather than in the
    # server. `importers` refuses structurally before OCCT sees anything.
    provenance = None
    doc = None
    if source_kind == "import":
        asset_path = os.path.join(workdir, asset)
        try:
            kind = importers.kind_for(asset)
            facts = importers.precheck(kind, asset_path)
            part, provenance = importers.load(kind, asset_path, facts=facts)
        except importers.ImportRejected as e:
            _write(workdir, {"ok": False, "error_code": e.code, "message": e.message})
            return 1
        except Exception as e:
            traceback.print_exc()
            _write(workdir, {"ok": False, "error_code": "import_malformed",
                             "message": f"that file could not be imported "
                                        f"({type(e).__name__})"})
            return 1
        resolved = {}
        label = os.path.splitext(asset)[0] or "imported"
        # The identity of an import is its bytes. Two uploads of the same file are the
        # same source; a re-export from the same CAD package with a new timestamp is
        # not, and pretending otherwise would let a stale reference masquerade as fresh.
        source_hash = provenance.get("sha256") or ""
        return _finish(workdir, part, label, formats, targets, stl_path,
                       resolved, source_hash, provenance, scope=scope_override,
                       wanted=wanted)

    try:
        if source_kind == "cadir":
            doc = cadir.parse(document)
            resolved = cadir.resolve_params(doc, params)
            env, steps, _cost = cadir.check(doc, resolved)
            label = doc.name
        else:
            resolved = recipes.resolve_params(recipe, params)
            label = recipe
    except (recipes.ParamError, cadir.ParamError, cadir.ExprError, cadir.BudgetError) as e:
        # Reachable only if the parent's identical check was bypassed. Still
        # answered structurally rather than as a crash.
        code = getattr(e, "code", None) or "too_complex"
        _write(workdir, {"ok": False, "error_code": code,
                         "message": getattr(e, "message", str(e))})
        return 1
    except Exception as e:
        # Pydantic's own ValidationError lands here. Its string form names every field
        # it walked, which is more of the document's shape than an error message should
        # carry back over the wire.
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "invalid_document",
                         "message": f"the document could not be read ({type(e).__name__})"})
        return 1

    try:
        if doc is not None:
            part = cadir_interpret.build(doc, resolved, steps=steps, env=env)
        else:
            part = recipes.build(recipe, resolved)
    except cadir_interpret.CadIRRuntimeError as e:
        # Our own diagnosis, naming an op_id the caller sent. Safe to echo, and the
        # only form of this error a generator can actually repair — "geometry engine
        # failed (ValueError)" tells it to guess.
        traceback.print_exc()
        _write(workdir, _failure("geometry_failed", str(e), doc, steps, label,
                                 error_op_id=_failing_op(doc, e), scope=scope_override))
        return 1
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "geometry_failed",
                         "message": f"geometry engine failed ({type(e).__name__})"})
        return 1

    source_hash = (cadir.canonical_source_hash(doc, resolved) if doc is not None
                   else recipes.canonical_source_hash(recipe, resolved))

    return _finish(workdir, part, label, formats, targets, stl_path,
                   resolved, source_hash, None, doc=doc, steps=steps if doc else None,
                   scope=scope_override, wanted=wanted)


def _failure(code: str, message: str, doc, steps, label: str, *,
             error_op_id: str | None = None, part=None,
             scope: str | None = None) -> dict:
    """A failure result carrying the tree the engine was attempting, when it can build one.

    A failed build is exactly when the workspace most needs a tree: it has to mark the
    operation that broke, and there is no geometry left to derive one from. The document
    is enough — everything but the bodies comes from it, and the bodies come from ``part``
    when the failure happened late enough that one exists.

    Every path here is best-effort. A manifest is a convenience; the error is the answer,
    and the nicety must never turn a diagnosed failure into an undiagnosed one.
    """
    payload = {"ok": False, "error_code": code, "message": message}
    try:
        scope = scope or (doc.name if doc is not None else label)
        payload["scene_manifest"] = manifest.compose(
            scope=scope, label=label,
            bodies=manifest.bodies_of(part) if part is not None else [label],
            features=(manifest.plan(doc, steps, scope=scope, error_op_id=error_op_id)
                      if doc is not None else []),
            body_status="error")
    except Exception:
        traceback.print_exc()
    return payload


def _failing_op(doc, error) -> str | None:
    """Which operation the interpreter blamed, if it blamed one.

    ``CadIRRuntimeError`` messages are formatted ``f"{op.op_id}: …"`` — except the
    no-geometry case, which uses the *document* name in the same position. Matching the
    prefix against the declared op_ids is what keeps that one from marking a feature
    that never failed, and keeps a future message format from inventing a node id.
    """
    head = str(error).split(":", 1)[0].strip()
    return head if any(op.op_id == head for op in doc.operations) else None


def _finish(workdir, part, label, formats, targets, stl_path,
            resolved, source_hash, provenance, *, doc=None, steps=None,
            scope: str | None = None, wanted=()) -> int:
    """Export, measure, and write the result — the tail every source kind shares.

    Shared on purpose. An imported body goes through the same exporters, the same
    ``mesh_report`` and the same ``mesh_signature`` as one we generated, so a reference
    part and a designed part are described in one vocabulary and can be compared. The
    only thing an import adds is ``provenance``: where the geometry came from, whether
    it is exact, and — always — that no feature history was recovered.
    """
    # These three exits carry a tree too, and deliberately blame no operation: the
    # document ran to completion and broke at export or measurement, so naming a feature
    # as the culprit would be an invention. The rows still say which operations ran and
    # which their guards dropped, which is the part that is true.
    try:
        meta, written = recipes.export(part, label, targets, seed=source_hash)
    except Exception as e:
        traceback.print_exc()
        _write(workdir, _failure("export_failed", f"export failed ({type(e).__name__})",
                                 doc, steps, label, part=part, scope=scope))
        return 1

    if not os.path.exists(stl_path):
        _write(workdir, _failure("export_failed", "the geometry engine produced no mesh",
                                 doc, steps, label, part=part, scope=scope))
        return 1

    try:
        mesh = validation.mesh_report(stl_path)
        metrics = validation.measure(part)
        signature = validation.mesh_signature(stl_path)
    except Exception as e:
        traceback.print_exc()
        _write(workdir, _failure("geometry_failed",
                                 f"could not measure the result ({type(e).__name__})",
                                 doc, steps, label, part=part, scope=scope))
        return 1

    # The per-part classification HE-1 built but never published: one entry per body,
    # keyed by the same `part_key` the scene manifest uses, carrying its fitted axis, the
    # face filling each role, and whether it is a surface of revolution. HE-7's render
    # recipes read it to decide which similarity warnings would be false ones.
    #
    # Additive and best-effort, like the scene tree below. A body OCCT will not classify
    # must not cost a sound solid its build: classification is evidence, and thin
    # evidence is not a defect.
    try:
        metrics["parts"] = part_targets.describe(part)
    except Exception:
        traceback.print_exc()

    # HE-2. Here, in the killable child, because a Python deadline in the parent cannot
    # interrupt an OpenCascade call already running — Gate 1B established that and the
    # kill path exists because of it. If the group dies mid-measurement no result.json is
    # written at all, which is the honest outcome: the parent reports a timeout and
    # nothing grades on a half-measured build.
    measurements = None
    if wanted:
        try:
            measurements = measure.run(part, wanted, source_hash=source_hash)
        except Exception:
            # Evidence is additive. Losing it must not turn a sound solid into a failed
            # build — the checks that wanted it grade `unverified`, which is what an
            # absent measurement has always meant upstream.
            traceback.print_exc()
            measurements = None

    # The semantic tree, and the ids that let a click in the viewport find a row in it.
    # It has to happen here rather than in the backend for one reason: this is the only
    # process that holds the built `part`, and how many bodies the GLB will contain is a
    # property of that object — `Compound.children`, measured, not `solids()`.
    scene = None
    try:
        bodies = manifest.bodies_of(part)
        scope = scope or (doc.name if doc is not None else label)
        scene = manifest.compose(
            scope=scope, label=label, bodies=bodies,
            features=manifest.plan(doc, steps, scope=scope) if doc is not None else [])
        keys = [n["glb_pick_key"] for n in scene["nodes"] if n["kind"] == "body"]
        glb_path = targets.get("glb")
        if glb_path and "glb" in written and os.path.exists(glb_path):
            landed = manifest.tag_glb(glb_path, keys)
            # Whatever the exporter actually did wins. A row promising a pick key the
            # GLB does not carry would highlight nothing when clicked, which reads as a
            # broken viewport rather than as an honest "not selectable".
            for node, key in zip([n for n in scene["nodes"] if n["kind"] == "body"], landed):
                if not key:
                    node["glb_pick_key"] = None
                    node["selectable"] = False
        else:
            for node in scene["nodes"]:
                if node["kind"] == "body":
                    node["glb_pick_key"] = None
                    node["selectable"] = False
        manifest.write(os.path.join(workdir, "scene-manifest.json"), scene)
    except Exception:
        # Geometry succeeded; the tree is an extra. Losing it must not turn a good
        # build into a failed one.
        traceback.print_exc()
        scene = None

    # No verdict here, and no size caps: those are policy, and policy stays in the
    # parent. This process only produces geometry and says what it measured.
    payload = {
        "ok": True,
        "meta": meta,
        "metrics": metrics,
        "mesh": mesh,
        "params": resolved,
        "peak_rss_bytes": _peak_rss_bytes(),
        # Both are identities, and they answer different questions. source_hash says
        # "this is the same request"; mesh_signature says "this is the same shape".
        # Byte hashes of the artifacts say neither — STEP carries a wall-clock
        # timestamp and 3MF is a ZIP, both measured at Gate 0.
        "source_hash": source_hash,
        "mesh_signature": signature,
        "formats": written,
    }
    if measurements is not None:
        payload["measurements"] = measurements
    if provenance is not None:
        payload["provenance"] = provenance
    if scene is not None:
        payload["scene_manifest"] = scene
    _write(workdir, payload)
    return 0


def serve() -> int:
    """Warm-worker mode: import once, then build many times.

    Measured at Gate 2: importing OCP costs 1.42 s while the hanger's geometry costs
    0.048 s, so ~97% of a small build is an import the previous build already paid
    for. This loop is what stops paying it twice.

    It is a *process* pool rather than a fork pool, and that is not a stylistic
    choice. The obvious design — import OCP once in a zygote, then fork per build —
    was measured and all three trial forks hung for the full 60 s timeout having
    produced nothing: a fork carries only the calling thread, and OCCT becomes
    multi-threaded on its first *build* (1 thread through every import, 16 after the
    first build). Forking before that first build is the only fork-safe moment, and it
    hands every child the first-build cost the zygote was supposed to amortise. These
    workers are long-lived anyway, so the import is paid twice per container rather
    than once per build, which is the saving a zygote was for.

    The protocol is one workdir path per line on stdin, and the result goes back
    through ``result.json`` exactly as in one-shot mode — the parent's reading code
    is the same either way, and the module docstring's reason for files over pipes
    still holds. Nothing is written to stdout that the parent parses.

    This loop never exits on a job failure. A worker that died on one bad request
    would hand the next caller a cold start and quietly undo the point of the pool;
    :func:`_run_job` has already written a structured result by the time we get here.
    """
    # Sizing the OCCT thread pool happens at first *use*, not at import, and the
    # affinity mask is already applied — so the first build a worker does is also
    # what fixes its pool to the slice it was given. Doing that here means the cost
    # lands at startup instead of on whoever is unlucky enough to be first.
    try:
        _prewarm = recipes.build("helmet_hanger_v1", recipes.resolve_params("helmet_hanger_v1", {}))
        del _prewarm
    except Exception:
        # A failed pre-warm is not fatal: the worker still serves, it is just cold.
        traceback.print_exc()

    print("ready", flush=True)
    for line in sys.stdin:
        workdir = line.strip()
        if not workdir:
            continue
        if workdir == "QUIT":
            return 0
        try:
            _run_job(workdir)
        except BaseException:
            traceback.print_exc()
            try:
                _write(workdir, {"ok": False, "error_code": "geometry_failed",
                                 "message": "the geometry engine failed"})
            except Exception:
                traceback.print_exc()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--serve":
        return serve()
    if len(argv) != 2:
        print("usage: worker_main.py <workdir> | --serve", file=sys.stderr)
        return 2
    return _run_job(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
