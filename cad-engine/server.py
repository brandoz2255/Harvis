"""Harvis CAD engine — an isolated build123d sidecar (Stage 2).

Runs the OCP/OCCT geometry kernel in its OWN container so its pinned
build123d==0.9.1 + cadquery-ocp stack never touches the backend's numpy<2 /
torch environment. The backend calls this over the internal network with a
recipe name + params; only VETTED named recipes run (no arbitrary code). It
returns a real STL/STEP (base64) + geometry metadata.

Internal network only — no host port, no auth secret needed beyond being
unreachable from outside the Docker network. Stateless.

Gate 1A hardening, in the order a request meets it:

1. body size cap, before the JSON parser sees anything
2. strict schema — unknown fields forbidden, every param a finite number
3. recipe allowlist
4. parameter resolution: unknown names rejected, ranges enforced (recipes.py)
5. admission control: static cost estimate charged BEFORE geometry starts
6. geometry
7. output caps: triangle count, artifact sizes, total scratch usage
8. geometry validation — B-Rep validity, solid count, watertight mesh
9. structured error codes with SAFE detail

Point 9 matters more than it looks. The old handler interpolated ``str(e)``, which
is how a tempdir path ended up in a 500 body during the Gate 0 baseline. Full
detail now goes to the log; the caller gets a code and a repairable sentence.

Gate 1B adds the two things 1A explicitly could not do, and both live outside this
module: geometry runs in a killable child process (:mod:`runner`) under a
server-owned deadline, and concurrency is capped up front (:mod:`admission`). This
file keeps every policy decision — cost, caps, validation verdict, encoding — and
hands the child nothing but a recipe and its parameters.

What is still NOT here: HTTP-disconnect detection. A client that hangs up mid-build
does not stop the build; only the deadline or an explicit cancel does. Saying
otherwise would repeat the mistake Gate 1B exists to correct.
"""
from __future__ import annotations

import base64
import contextlib
import logging
import math
import os
import uuid
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

import admission
import exporters
import pool as worker_pool
import recipes
import runner
import validation

log = logging.getLogger("cad-engine")


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the warm workers with the server, and stop them with it.

    One worker per concurrency slot, each pinned to the CPU slice a build on that
    slot would have got anyway — ``cpu_slice`` rotates, so asking for
    ``MAX_CONCURRENT`` of them hands out disjoint slices rather than stacking every
    worker on the same CPU.

    Sizing it to the admission cap is what keeps the pool from changing any
    behaviour except latency: admission control already refuses the N+1th build with
    a 429, so a pool of N can never be the thing that makes a caller wait. If it is
    ever empty anyway — a worker being replaced — ``runner`` falls back to the cold
    spawn, which is exactly what every build did before this existed.

    Shutdown is in a ``finally`` because a worker outliving the server is a leaked
    process, and this container's whole point is that geometry cannot outlive its
    supervisor.
    """
    worker_pool.init(
        admission.MAX_CONCURRENT,
        [runner.cpu_slice(admission.MAX_CONCURRENT)
         for _ in range(admission.MAX_CONCURRENT)],
    )
    try:
        yield
    finally:
        worker_pool.shutdown()


app = FastAPI(title="Harvis CAD engine", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Limits. Every one of these is a refusal, never a silent truncation.
# ---------------------------------------------------------------------------
MAX_BODY_BYTES = 64 * 1024          # a recipe call is a few hundred bytes
MAX_PARAMS = 32
MAX_TRIANGLES = 400_000             # ~20 MB of binary STL
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_WORKDIR_BYTES = 96 * 1024 * 1024

# What this endpoint asks the worker for, and it is not a parameter. The response
# carries exactly `stl_b64` and `step_b64`; a caller who could request GLB would get a
# 200 with no way to receive it. Gate 3's /cad/v2/build is where formats become the
# caller's choice, because that is where the response can carry them.
_EXECUTE_FORMATS = ("stl", "step")


def _strict_number(v: Any) -> float:
    """Reject at the schema boundary what the clamps cannot survive.

    ``bool`` is a subclass of ``int``, so without the first check ``true`` would
    silently mean 1 mm. Non-finite values are the headline reason this function
    exists: Python's ``min``/``max`` propagate NaN instead of clamping it, and a
    single NaN froze the whole worker for 46 s.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("must be a number")
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("must be a finite number (NaN and Infinity are rejected)")
    return f


Number = Annotated[float, BeforeValidator(_strict_number), Field(allow_inf_nan=False)]
ParamName = Annotated[str, Field(min_length=1, max_length=48)]


class ExecReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe: str = Field(min_length=1, max_length=64)
    params: dict[ParamName, Number] = Field(default_factory=dict, max_length=MAX_PARAMS)
    step: bool = True
    # Caller-chosen handle for POST /cad/cancel/{build_id}. Optional, so existing
    # callers keep working under extra="forbid" — they simply cannot cancel. There
    # is no cad_builds table until Gate 3, so the registry is in-memory and a build
    # id means nothing once the request that owns it returns.
    build_id: str | None = Field(default=None, min_length=1, max_length=64)


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message})


@app.exception_handler(RequestValidationError)
async def _on_validation_error(request: Request, exc: RequestValidationError):
    """Answer schema failures in the same structured shape as everything else, and
    at 400 rather than FastAPI's 422 — the caller's job is identical either way and
    one shape is easier to handle honestly."""
    first = (exc.errors() or [{}])[0]
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body") or "request"
    return JSONResponse(
        status_code=400,
        content={"detail": {
            "error_code": "invalid_request",
            "message": f"{loc}: {first.get('msg', 'invalid value')}",
        }},
    )


@app.middleware("http")
async def _cap_body(request: Request, call_next):
    """Refuse an oversized body before the JSON parser allocates for it."""
    raw = request.headers.get("content-length")
    if raw and raw.isdigit() and int(raw) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": {
                "error_code": "body_too_large",
                "message": f"request body exceeds {MAX_BODY_BYTES} bytes",
            }},
        )
    return await call_next(request)


try:
    import importlib.metadata as _md
    _BUILD123D_VERSION = _md.version("build123d")
except Exception:  # pragma: no cover — a packaging accident must not break /health
    _BUILD123D_VERSION = "unknown"


@app.get("/health")
def health():
    """Deliberately answers from the parent's own state only.

    The two format keys are separate on purpose. ``formats`` is what ``/cad/execute``
    actually returns and has not changed; ``formats_available`` is what the geometry
    worker can now write, which since Gate 2 includes GLB and 3MF. Collapsing them into
    one list would advertise, on the endpoint that cannot deliver them, a capability
    that only Gate 3's ``/cad/v2/build`` will expose.
    """
    return {
        "ok": True,
        "recipes": list(recipes.RECIPES.keys()),
        "formats": list(_EXECUTE_FORMATS),
        "formats_available": list(exporters.FORMATS),
        "schema_version": recipes.SCHEMA_VERSION,
        "active_builds": admission.active(),
        "max_concurrent": admission.MAX_CONCURRENT,
        "deadline_s": runner.DEADLINE_S,
        "build123d_version": _BUILD123D_VERSION,
        # Honest about which lane is actually serving builds. `null` means warm
        # workers are off (or failed to start) and every build pays the 1.42 s OCP
        # import — correct, just slower, and worth being able to see from outside.
        "worker_pool": (p.stats() if (p := worker_pool.get_pool()) is not None else None),
    }


@app.post("/cad/cancel/{build_id}")
def cancel(build_id: str):
    """Stop a build the caller named via ``build_id``.

    Returns ``cancelling`` when a live process was signalled and ``unknown`` when
    there is nothing to stop — which covers both a bad id and a build that finished
    a moment ago. The two are indistinguishable from here, and pretending otherwise
    would need the Gate 3 build table.
    """
    handle = runner.get_handle(build_id)
    if handle is None:
        raise _err(404, "unknown_build", "no build is running under that id")
    return {"ok": True, "status": "cancelling" if handle.cancel() else "unknown"}


def _dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


@app.post("/cad/execute")
def execute(req: ExecReq):
    if req.recipe not in recipes.RECIPES:
        raise _err(400, "unknown_recipe", f"unknown recipe: {req.recipe}")

    # --- everything below the geometry line is cheap and runs first ---
    try:
        resolved = recipes.resolve_params(req.recipe, req.params or {})
    except recipes.ParamError as e:
        raise _err(400, e.code, e.message)

    cost = recipes.estimate_cost(req.recipe, resolved)
    cap = recipes.cost_cap(req.recipe)
    if cost > cap:
        raise _err(
            400, "too_complex",
            f"estimated complexity {cost} exceeds the cap of {cap}",
        )

    # A slot is taken BEFORE the child is spawned, so a saturated engine costs a
    # rejected request rather than a process. Non-blocking on purpose: a caller
    # waiting in a queue it cannot see is the kind of hidden latency Gate 1B exists
    # to remove.
    build_id = req.build_id or uuid.uuid4().hex
    try:
        with admission.slot():
            return _run_and_encode(req, resolved, cost, build_id)
    except admission.QueueFull as e:
        raise _err(429, "queue_full", str(e))
    except runner.BuildTimeout as e:
        log.warning("build %s hit the deadline for recipe=%s", build_id, req.recipe)
        raise _err(504, "build_timeout", str(e))
    except runner.BuildCancelled:
        # 409, not a 5xx: nothing failed. The caller asked for this.
        raise _err(409, "build_cancelled", "the build was cancelled")
    except runner.BuildFailed as e:
        status = 400 if e.code in ("unknown_param", "param_out_of_range") else 500
        raise _err(status, e.code, e.message)
    except HTTPException:
        raise
    except Exception as e:  # nothing should reach here; if it does, stay safe
        log.exception("unhandled failure for recipe=%s", req.recipe)
        raise _err(500, "internal_error", f"unexpected failure ({type(e).__name__})")


def _run_and_encode(req: ExecReq, resolved: dict, cost: float, build_id: str) -> dict:
    """Everything that needs the build's workdir, inside its lifetime.

    The workdir is created and destroyed by :func:`runner.run_build`; leaving this
    function by any path — return, cap breach, or a kill — removes it.
    """
    formats = list(_EXECUTE_FORMATS) if req.step else ["stl"]
    with runner.run_build(
        req.recipe, resolved, step=req.step, formats=formats, build_id=build_id
    ) as outcome:
        result = outcome.result
        meta = result["meta"]
        metrics = result["metrics"]
        mesh = result["mesh"]

        # Caps are enforced here, in the parent, on what the child actually wrote.
        # The child measures; it does not get to decide what is acceptable.
        used = _dir_bytes(outcome.workdir)
        if used > MAX_WORKDIR_BYTES:
            raise _err(500, "output_too_large",
                       f"scratch output {used} bytes exceeds {MAX_WORKDIR_BYTES}")

        tri = mesh.get("triangle_count") or 0
        if tri > MAX_TRIANGLES:
            raise _err(500, "output_too_large",
                       f"mesh has {tri} triangles, over the cap of {MAX_TRIANGLES}")

        # The expected solid count is a property of the recipe. It was hardcoded to 1
        # through Gate 1B, which was true of the only recipe there was; leaving it that
        # way would turn the first legitimately two-bodied recipe into a 500.
        expected = recipes.RECIPE_SOLIDS.get(req.recipe, 1)
        ok, problems = validation.verdict(metrics, mesh, expected_solids=expected)
        if not ok:
            # A bad solid must not be indistinguishable from a good one. The problem
            # strings are names and numbers — no paths, no argv, no host names.
            raise _err(500, "validation_failed", "; ".join(problems))

        stl_bytes = os.path.getsize(outcome.stl_path)
        if stl_bytes > MAX_ARTIFACT_BYTES:
            raise _err(500, "output_too_large",
                       f"STL is {stl_bytes} bytes, over the cap of {MAX_ARTIFACT_BYTES}")
        with open(outcome.stl_path, "rb") as fh:
            stl_b64 = base64.b64encode(fh.read()).decode("ascii")

        step_b64 = None
        if outcome.step_path:
            step_bytes = os.path.getsize(outcome.step_path)
            if step_bytes > MAX_ARTIFACT_BYTES:
                raise _err(500, "output_too_large",
                           f"STEP is {step_bytes} bytes, over the cap of {MAX_ARTIFACT_BYTES}")
            with open(outcome.step_path, "rb") as fh:
                step_b64 = base64.b64encode(fh.read()).decode("ascii")

        # `meta`, `stl_b64` and `step_b64` keep the exact shape the backend already
        # consumes (frozen in the Gate 0 baseline). `validation` and `params` are
        # additive — a v2 endpoint in Gate 3 is where the shape actually changes.
        return {
            "ok": True,
            "meta": meta,
            "stl_b64": stl_b64,
            "step_b64": step_b64,
            "params": result.get("params", resolved),
            "validation": {
                **metrics,
                "mesh": mesh,
                "estimated_cost": cost,
                "duration_ms": outcome.duration_ms,
                "peak_rss_bytes": result.get("peak_rss_bytes"),
                # Gate 2 identities. `source_hash` is what Gate 3's cad_revisions
                # compares on; `mesh_signature` is what proves two builds of the same
                # input produced the same shape. Neither is a hash of the files —
                # STEP embeds a wall-clock timestamp and 3MF is a ZIP, so byte
                # identity was measured to be the wrong test.
                "source_hash": result.get("source_hash"),
                "mesh_signature": result.get("mesh_signature"),
            },
        }
