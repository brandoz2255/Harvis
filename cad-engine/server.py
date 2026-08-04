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
import hashlib
import json
import logging
import math
import os
import secrets
import uuid
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
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

# What /cad/execute asks the worker for, and it is not a parameter. That response
# carries exactly `stl_b64` and `step_b64`; a caller who could request GLB would get a
# 200 with no way to receive it. /cad/v2/build is where formats became the caller's
# choice, because that is where the response can carry them.
_EXECUTE_FORMATS = ("stl", "step")

# Every artifact in one v2 response, together. Each file is already capped at
# MAX_ARTIFACT_BYTES and the workdir at MAX_WORKDIR_BYTES, but v2 reads the files into
# memory to frame them, so the sum is what this process actually holds — and four
# formats each just under the per-file cap would be 128 MB against a 2 GB container.
MAX_RESPONSE_BYTES = MAX_WORKDIR_BYTES


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


class BuildV2Req(BaseModel):
    """What ``/cad/v2/build`` accepts. A superset of :class:`ExecReq` in capability,
    and a separate model rather than optional fields on that one so the frozen
    endpoint's schema cannot drift while this one grows."""

    model_config = ConfigDict(extra="forbid")

    recipe: str = Field(min_length=1, max_length=64)
    params: dict[ParamName, Number] = Field(default_factory=dict, max_length=MAX_PARAMS)
    formats: list[str] = Field(default_factory=lambda: list(exporters.DEFAULT_FORMATS),
                               min_length=1, max_length=len(exporters.FORMATS))
    # A caller may ask for LESS time than the engine's own deadline, never more.
    # The nested-timeout layering (engine < client < nginx) only holds while the
    # innermost deadline is the shortest, so an unclamped field here would let a
    # request quietly invert it and strand work nobody is still waiting for.
    deadline_s: float | None = Field(default=None, gt=0, le=runner.DEADLINE_S)
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


@app.get("/cad/recipes")
def list_recipes():
    """Every recipe's parameter surface — name, kind, default, and range.

    Gate 4's Parameters panel needs bounds to draw a slider at all, and the only
    truthful source for them is :data:`recipes.PARAM_SPEC`, which is also what
    rejects an out-of-range build. A second copy in the frontend would be a second
    thing to keep in step, and the first time it drifted the UI would offer a value
    the engine refuses.
    """
    return {
        "schema_version": recipes.SCHEMA_VERSION,
        "units": "mm",
        "recipes": {
            name: {
                "parameters": [
                    {"name": p, "kind": kind, "default": default, "min": lo, "max": hi}
                    for p, (kind, default, lo, hi) in spec.items()
                ],
                "expected_solids": recipes.RECIPE_SOLIDS.get(name),
                "cost_cap": recipes.cost_cap(name),
            }
            for name, spec in recipes.PARAM_SPEC.items()
            if name in recipes.RECIPES
        },
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


def _enforce_output_caps(outcome, recipe: str, metrics: dict, mesh: dict) -> None:
    """Judge what the child actually wrote. The child measures; it never decides.

    Shared by both build endpoints on purpose. When these lived inside the v1
    response builder, adding v2 meant either duplicating them — and duplicated
    limits drift until one endpoint is the lenient one — or leaving v2 uncapped.
    """
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
    expected = recipes.RECIPE_SOLIDS.get(recipe, 1)
    ok, problems = validation.verdict(metrics, mesh, expected_solids=expected)
    if not ok:
        # A bad solid must not be indistinguishable from a good one. The problem
        # strings are names and numbers — no paths, no argv, no host names.
        raise _err(500, "validation_failed", "; ".join(problems))


def _read_capped(path: str, label: str) -> bytes:
    """Read one artifact, refusing rather than truncating if it is over the cap."""
    size = os.path.getsize(path)
    if size > MAX_ARTIFACT_BYTES:
        raise _err(500, "output_too_large",
                   f"{label} is {size} bytes, over the cap of {MAX_ARTIFACT_BYTES}")
    with open(path, "rb") as fh:
        return fh.read()


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

        _enforce_output_caps(outcome, req.recipe, metrics, mesh)

        stl_b64 = base64.b64encode(_read_capped(outcome.stl_path, "STL")).decode("ascii")
        step_b64 = None
        if outcome.step_path:
            step_b64 = base64.b64encode(
                _read_capped(outcome.step_path, "STEP")).decode("ascii")

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


# ---------------------------------------------------------------------------
# /cad/v2/build — the endpoint Gate 3 persists from.
#
# Two things v1 cannot do, and both are why this exists rather than v1 growing
# fields: the caller chooses formats, and the artifacts come back as bytes instead
# of base64. Base64 costs +33% on a hop that already carries the largest thing in
# the system; a 20 MB STL becomes 27 MB of JSON that then has to be parsed as one
# string before a single byte can be written to disk.
#
# v1 stays exactly as it is. It is the contract the Adaptive Space lane runs on,
# and freezing it is what lets this one change shape freely.
# ---------------------------------------------------------------------------

def _multipart(result: dict, artifacts: list[tuple[str, str, bytes]]) -> Response:
    """Frame the result and the raw artifacts as one ``multipart/form-data`` body.

    Each part is named by its format, so the client keys off ``name=`` and never has
    to parse a filename. The boundary is random per response because a boundary that
    appeared in the payload would silently split a file in half — with 32 bytes of
    ``secrets`` entropy that is not a risk worth a scan of every artifact.
    """
    boundary = secrets.token_hex(16)
    sep = f"--{boundary}".encode()
    chunks: list[bytes] = [
        sep, b"\r\n",
        b'Content-Disposition: form-data; name="result"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(result).encode("utf-8"), b"\r\n",
    ]
    for fmt, media, blob in artifacts:
        chunks += [
            sep, b"\r\n",
            f'Content-Disposition: form-data; name="{fmt}"; filename="part.{fmt}"\r\n'
            .encode(),
            f"Content-Type: {media}\r\n".encode(),
            f"Content-Length: {len(blob)}\r\n\r\n".encode(),
            blob, b"\r\n",
        ]
    chunks += [f"--{boundary}--\r\n".encode()]
    return Response(
        content=b"".join(chunks),
        media_type=f"multipart/form-data; boundary={boundary}",
        # The bytes are geometry, never markup, but this response is the one that
        # carries attacker-influenced *sizes* and reaches a browser-adjacent client.
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.post("/cad/v2/build")
def build_v2(req: BuildV2Req):
    if req.recipe not in recipes.RECIPES:
        raise _err(400, "unknown_recipe", f"unknown recipe: {req.recipe}")

    # Deduplicated, order preserved. Asking for stl twice is a caller bug, not a
    # reason to export twice — and STL is always built because the mesh report and
    # the mesh signature are computed from it.
    seen: dict[str, None] = {}
    for fmt in req.formats:
        if fmt not in exporters.FORMATS:
            raise _err(400, "unknown_format",
                       f"unknown format: {fmt} (have {', '.join(exporters.FORMATS)})")
        seen[fmt] = None
    wanted = list(seen)
    formats = wanted if "stl" in seen else ["stl", *wanted]

    try:
        resolved = recipes.resolve_params(req.recipe, req.params or {})
    except recipes.ParamError as e:
        raise _err(400, e.code, e.message)

    cost = recipes.estimate_cost(req.recipe, resolved)
    cap = recipes.cost_cap(req.recipe)
    if cost > cap:
        raise _err(400, "too_complex",
                   f"estimated complexity {cost} exceeds the cap of {cap}")

    build_id = req.build_id or uuid.uuid4().hex
    try:
        with admission.slot():
            return _build_and_frame(req, resolved, formats, wanted, cost, build_id)
    except admission.QueueFull as e:
        raise _err(429, "queue_full", str(e))
    except runner.BuildTimeout as e:
        log.warning("build %s hit the deadline for recipe=%s", build_id, req.recipe)
        raise _err(504, "build_timeout", str(e))
    except runner.BuildCancelled:
        raise _err(409, "build_cancelled", "the build was cancelled")
    except runner.BuildFailed as e:
        status = 400 if e.code in ("unknown_param", "param_out_of_range") else 500
        raise _err(status, e.code, e.message)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("unhandled failure for recipe=%s", req.recipe)
        raise _err(500, "internal_error", f"unexpected failure ({type(e).__name__})")


def _build_and_frame(req: BuildV2Req, resolved: dict, formats: list[str],
                     wanted: list[str], cost: float, build_id: str) -> Response:
    """Read every artifact inside the workdir's lifetime, then frame them.

    Reading into memory rather than streaming from disk is deliberate: the workdir
    dies with the ``with`` block, and a streaming response would still be reading
    from it after that. Bounded by MAX_RESPONSE_BYTES, which is why that cap exists.
    """
    with runner.run_build(
        req.recipe, resolved,
        step="step" in formats, formats=formats,
        deadline_s=req.deadline_s or runner.DEADLINE_S,
        build_id=build_id,
    ) as outcome:
        result = outcome.result
        metrics = result["metrics"]
        mesh = result["mesh"]
        _enforce_output_caps(outcome, req.recipe, metrics, mesh)

        blobs: list[tuple[str, str, bytes]] = []
        refs: list[dict] = []
        total = 0
        for fmt in wanted:
            path = outcome.artifacts.get(fmt)
            if not path or not os.path.exists(path):
                # The child was asked for it and did not write it. Silence here would
                # persist a revision whose artifact row has no bytes behind it.
                raise _err(500, "missing_artifact",
                           f"the worker did not produce the requested {fmt}")
            blob = _read_capped(path, fmt.upper())
            total += len(blob)
            if total > MAX_RESPONSE_BYTES:
                raise _err(500, "output_too_large",
                           f"artifacts total {total} bytes, over the cap of "
                           f"{MAX_RESPONSE_BYTES}")
            media = exporters.MEDIA_TYPES.get(fmt, "application/octet-stream")
            blobs.append((fmt, media, blob))
            refs.append({
                "format": fmt,
                "media_type": media,
                "size_bytes": len(blob),
                # Of the bytes as sent. cad_artifacts stores this and re-checks it on
                # read, which detects corruption in the store — it is never a rebuild
                # test, because STEP embeds a timestamp and 3MF is a ZIP.
                "sha256": hashlib.sha256(blob).hexdigest(),
            })

        return _multipart({
            "ok": True,
            "build_id": build_id,
            "recipe": req.recipe,
            "meta": result["meta"],
            "params": result.get("params", resolved),
            "artifacts": refs,
            "validation": {
                **metrics,
                "mesh": mesh,
                "estimated_cost": cost,
                "duration_ms": outcome.duration_ms,
                "peak_rss_bytes": result.get("peak_rss_bytes"),
                "source_hash": result.get("source_hash"),
                "mesh_signature": result.get("mesh_signature"),
            },
        }, blobs)
