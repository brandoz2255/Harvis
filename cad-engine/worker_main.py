"""The child process that actually runs geometry (Gate 1B).

One of these per build. It is spawned by :mod:`runner` into its own process group
so it can be killed outright, which is the whole point of Gate 1B: OCP holds the
GIL through native OpenCascade calls, so geometry running inside the server process
cannot be interrupted by anything — not a timeout, not a cancelled future, not a
dropped connection. Measured at Gate 0: one malformed request starved ``/health``
for 43.269 s.

Contract with the parent, deliberately file-based rather than pipe-based:

* ``argv[1]`` is a workdir the PARENT created and the PARENT removes.
* ``<workdir>/job.json``   in   ``{"recipe": str, "params": {...}, "step": bool,
  "formats": ["stl", "step", ...]}``
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

import exporters  # noqa: E402
import recipes  # noqa: E402
import validation  # noqa: E402


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
        recipe = job["recipe"]
        params = job.get("params") or {}
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
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "invalid_job",
                         "message": f"the job description could not be read "
                                    f"({type(e).__name__})"})
        return 2

    targets = {f: os.path.join(workdir, f"part.{f}") for f in formats}
    stl_path = targets["stl"]

    try:
        resolved = recipes.resolve_params(recipe, params)
    except recipes.ParamError as e:
        # Reachable only if the parent's identical check was bypassed. Still
        # answered structurally rather than as a crash.
        _write(workdir, {"ok": False, "error_code": e.code, "message": e.message})
        return 1

    try:
        part = recipes.build(recipe, resolved)
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "geometry_failed",
                         "message": f"geometry engine failed ({type(e).__name__})"})
        return 1

    source_hash = recipes.canonical_source_hash(recipe, resolved)

    try:
        meta, written = recipes.export(part, recipe, targets, seed=source_hash)
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "export_failed",
                         "message": f"export failed ({type(e).__name__})"})
        return 1

    if not os.path.exists(stl_path):
        _write(workdir, {"ok": False, "error_code": "export_failed",
                         "message": "the geometry engine produced no mesh"})
        return 1

    try:
        mesh = validation.mesh_report(stl_path)
        metrics = validation.measure(part)
        signature = validation.mesh_signature(stl_path)
    except Exception as e:
        traceback.print_exc()
        _write(workdir, {"ok": False, "error_code": "geometry_failed",
                         "message": f"could not measure the result ({type(e).__name__})"})
        return 1

    # No verdict here, and no size caps: those are policy, and policy stays in the
    # parent. This process only produces geometry and says what it measured.
    _write(workdir, {
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
    })
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
