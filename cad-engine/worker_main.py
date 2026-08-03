"""The child process that actually runs geometry (Gate 1B).

One of these per build. It is spawned by :mod:`runner` into its own process group
so it can be killed outright, which is the whole point of Gate 1B: OCP holds the
GIL through native OpenCascade calls, so geometry running inside the server process
cannot be interrupted by anything — not a timeout, not a cancelled future, not a
dropped connection. Measured at Gate 0: one malformed request starved ``/health``
for 43.269 s.

Contract with the parent, deliberately file-based rather than pipe-based:

* ``argv[1]`` is a workdir the PARENT created and the PARENT removes.
* ``<workdir>/job.json``   in   ``{"recipe": str, "params": {...}, "step": bool}``
* ``<workdir>/part.stl``   out  binary STL
* ``<workdir>/part.step``  out  STEP, when requested
* ``<workdir>/result.json`` out ``{"ok": true, ...}`` or ``{"ok": false, "error_code", "message"}``
* stdout/stderr go to ``<workdir>/worker.log``; nothing is written to a pipe.

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

import recipes
import validation


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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: worker_main.py <workdir>", file=sys.stderr)
        return 2
    workdir = argv[1]

    try:
        with open(os.path.join(workdir, "job.json"), encoding="utf-8") as fh:
            job = json.load(fh)
        recipe = job["recipe"]
        params = job.get("params") or {}
        want_step = bool(job.get("step", True))
    except Exception:
        traceback.print_exc()
        return 2

    stl_path = os.path.join(workdir, "part.stl")
    step_path = os.path.join(workdir, "part.step") if want_step else None

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

    try:
        meta = recipes.export(part, recipe, stl_path, step_path)
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
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
