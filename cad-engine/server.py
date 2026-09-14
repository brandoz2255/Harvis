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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

import admission
import cadir
import exporters
import importers
import measure_spec
import pool as worker_pool
import recipes
import runner
import schema_doc
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

# Gate 8B. An import's body IS a file, so the 64 KB ceiling above — sized for "a recipe
# call is a few hundred bytes" — would refuse every real upload. This is the per-route
# exception, and it is deliberately the only one: a route not named here gets the small
# cap, so adding an endpoint can never silently widen what the process will hold.
#
# The number is `importers.MAX_ASSET_BYTES` and not a second constant, because the
# refusal the caller actually cares about is the one `importers.precheck` issues with a
# reason attached. This cap exists to stop the bytes being *read* at all; letting it sit
# a little above the real limit means an oversize file is refused by the layer that can
# explain itself, not by a bare 413.
_IMPORT_PATH = "/cad/v2/import"
MAX_IMPORT_BODY_BYTES = importers.MAX_ASSET_BYTES + 64 * 1024
_BODY_CAPS = {_IMPORT_PATH: MAX_IMPORT_BODY_BYTES}


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

    # Exactly one of these two names the geometry. A recipe is a vetted Python
    # function; a document is CadIR the interpreter walks. Both nullable rather than
    # a tagged union because the discriminator would be a third field that can
    # disagree with the other two, and there is nothing for it to add.
    recipe: str | None = Field(default=None, min_length=1, max_length=64)
    document: dict | None = None
    params: dict[ParamName, Number] = Field(default_factory=dict, max_length=MAX_PARAMS)
    formats: list[str] = Field(default_factory=lambda: list(exporters.DEFAULT_FORMATS),
                               min_length=1, max_length=len(exporters.FORMATS))
    # A caller may ask for LESS time than the engine's own deadline, never more.
    # The nested-timeout layering (engine < client < nginx) only holds while the
    # innermost deadline is the shortest, so an unclamped field here would let a
    # request quietly invert it and strand work nobody is still waiting for.
    deadline_s: float | None = Field(default=None, gt=0, le=runner.DEADLINE_S)
    build_id: str | None = Field(default=None, min_length=1, max_length=64)
    # What node ids in the scene manifest are hashed from. Optional because the engine
    # has a fallback — the document's own `name` — and that fallback is exactly the
    # problem this field exists to let a caller avoid: `name` is written by whatever
    # authored the document, so renaming it between two turns reissues every id and
    # resets selection and the colours keyed on it. A caller that owns something stable
    # (a project id) sends it; one that does not sends nothing and keeps the old
    # behaviour. It never reaches the geometry — only the identity of its parts.
    scope: str | None = Field(default=None, min_length=1, max_length=128)
    # HE-2. What to measure on the result, in the grammar `measure_spec` owns. Checked
    # here so a malformed list is a 400 before a child is spawned — and checked again in
    # the worker, because the inner layer never trusts the outer one.
    measurements: list[dict] | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if (self.recipe is None) == (self.document is None):
            raise ValueError("give exactly one of recipe or document")
        return self

    @model_validator(mode="after")
    def _measurements_parse(self):
        measure_spec.parse(self.measurements)
        return self


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    """``extra`` carries structured detail that is safe to echo — today only
    ``scene_manifest``, so a failed build can still say which operation broke. Never a
    path, an argv or a host name; that rule is what keeps ``message`` free-text."""
    return HTTPException(status_code=status,
                         detail={"error_code": code, "message": message, **extra})


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
    """Refuse an oversized body before the JSON parser allocates for it.

    Header-based, so it only stops a caller that declares its size. That is enough for
    every JSON route, whose handlers let Starlette buffer the body — a chunked request
    with no ``content-length`` gets past here, which is why the import route reads its
    own body through :func:`_read_body_capped` instead of trusting this.
    """
    cap = _BODY_CAPS.get(request.url.path, MAX_BODY_BYTES)
    raw = request.headers.get("content-length")
    if raw and raw.isdigit() and int(raw) > cap:
        return JSONResponse(
            status_code=413,
            content={"detail": {
                "error_code": "body_too_large",
                "message": f"request body exceeds {cap} bytes",
            }},
        )
    return await call_next(request)


async def _read_body_capped(request: Request, cap: int) -> bytes:
    """Read the body a chunk at a time, refusing the moment it passes ``cap``.

    ``await request.body()`` would buffer the whole thing first and only then let us
    look at the length, which turns a missing ``content-length`` into "hold whatever
    the client sends". Streaming means the ceiling holds whether or not the caller
    declared a size, and an over-cap upload is refused after one chunk too many rather
    than after all of it.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise _err(413, "body_too_large", f"request body exceeds {cap} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


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
        # What /cad/v2/import will read, which is deliberately not the same list as
        # what the engine exports. GLB is on `formats_available` and absent here
        # because build123d writes glTF and does not read it — advertising one list
        # for both directions would promise a round trip that does not exist.
        "import_kinds": list(importers.KINDS),
        "import_max_bytes": importers.MAX_ASSET_BYTES,
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


@app.get("/cad/schema")
def cad_schema():
    """The CadIR grammar, for whatever is about to write one.

    Read off the pydantic models at import time — see :mod:`schema_doc` — so it cannot
    describe a language the engine does not parse. It exists because the model
    authoring a document may be reaching this lane through a tool call with no system
    prompt behind it, and a grammar nobody handed it is a grammar it will guess at.
    """
    return schema_doc.describe()


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


@app.get("/cad/recipes/{name}/source")
def recipe_source(name: str):
    """The recipe's CadIR document — the canonical parametric source for a part.

    Read-only, and deliberately not the execution path: ``/cad/execute`` and
    ``/cad/v2/build`` still run :mod:`recipes`, exactly as ``cadir.templates`` says.
    This route publishes what the part *is* so the studio can show it and list the
    features it declares; it does not change what runs.

    Separate from ``/cad/recipes`` rather than folded into it because the parameter
    surface is fetched on every capability probe and these documents are an order of
    magnitude larger. A tab nobody opened should not cost bytes on every mount.
    """
    doc = cadir.TEMPLATES.get(name)
    if doc is None or name not in recipes.RECIPES:
        # Same answer for "no such recipe" and "that recipe has no CadIR yet": from
        # the caller's side there is nothing to show either way.
        raise _err(404, "unknown_recipe", f"no CadIR source for recipe: {name}")

    # Parsed, not returned raw. It costs microseconds and it means this route cannot
    # publish a document the interpreter would reject — a Source tab showing something
    # unbuildable is worse than one showing nothing.
    try:
        cadir.parse(doc)
    except Exception as e:
        log.error("CadIR template %s does not parse: %s", name, type(e).__name__)
        raise _err(500, "invalid_template", "that template is not a valid CadIR document")

    return {
        "schema_version": cadir.SCHEMA_VERSION,
        "recipe": name,
        "units": doc.get("units", "mm"),
        "document": doc,
        # Every operation the document declares, in execution order. This is the
        # feature list — `op_id` is the author-stable name the Gate 5a spike concluded
        # a clicked face can be traced back to.
        #
        # `selectable` is false across the board and that is the honest answer, not a
        # placeholder: the spike proved the mapping is *possible* (one glTF primitive
        # per B-Rep face, in face order) but nothing emits a selection manifest yet.
        "features": [
            {
                "op_id": op.get("op_id") or f"{op.get('op')}#{i}",
                "op": op.get("op"),
                "mode": op.get("mode", "add"),
                "when": op.get("when"),
                "optional": bool(op.get("optional")),
                "selectable": False,
            }
            for i, op in enumerate(doc.get("operations") or [])
        ],
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


def _resolve_formats(requested: list[str]) -> tuple[list[str], list[str]]:
    """Validate and dedupe the requested formats. Returns (what to build, what to send).

    Order is preserved and duplicates collapse — asking for ``stl`` twice is a caller
    bug, not a reason to export twice. STL is always built even when it was not asked
    for, because the mesh report and the mesh signature are computed from it; it is
    simply left out of the second list, so an unasked-for STL never reaches the caller.
    """
    seen: dict[str, None] = {}
    for fmt in requested:
        if fmt not in exporters.FORMATS:
            raise _err(400, "unknown_format",
                       f"unknown format: {fmt} (have {', '.join(exporters.FORMATS)})")
        seen[fmt] = None
    wanted = list(seen)
    return (wanted if "stl" in seen else ["stl", *wanted]), wanted


def _enforce_output_caps(outcome, expected_solids: int, metrics: dict, mesh: dict,
                         provenance: dict | None = None) -> None:
    """Judge what the child actually wrote. The child measures; it never decides.

    Shared by every build endpoint on purpose. When these lived inside the v1
    response builder, adding v2 meant either duplicating them — and duplicated
    limits drift until one endpoint is the lenient one — or leaving v2 uncapped.

    The resource caps below apply to every source kind, because they are about what
    this process is willing to hold, which does not depend on where the geometry came
    from. The geometry verdict does: pass ``provenance`` and it switches to
    :func:`validation.import_verdict`, which drops the three checks that only make
    sense about a part we authored to a spec.
    """
    used = _dir_bytes(outcome.workdir)
    if used > MAX_WORKDIR_BYTES:
        raise _err(500, "output_too_large",
                   f"scratch output {used} bytes exceeds {MAX_WORKDIR_BYTES}")

    tri = mesh.get("triangle_count") or 0
    if tri > MAX_TRIANGLES:
        raise _err(500, "output_too_large",
                   f"mesh has {tri} triangles, over the cap of {MAX_TRIANGLES}")

    # The expected solid count is a property of the source, not of this function. It
    # was hardcoded to 1 through Gate 1B, which was true of the only recipe there was;
    # then it was looked up by recipe name, which is meaningless for a CadIR document
    # that has no name in RECIPE_SOLIDS. The caller knows which source it dispatched,
    # so the caller passes the number.
    if provenance is not None:
        ok, problems = validation.import_verdict(
            metrics, mesh, exact=bool(provenance.get("exact")))
    else:
        ok, problems = validation.verdict(metrics, mesh, expected_solids=expected_solids)
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

        _enforce_output_caps(outcome, recipes.RECIPE_SOLIDS.get(req.recipe, 1),
                             metrics, mesh)

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


def _validation_detail(exc: Exception, limit: int = 8) -> str:
    """Turn a pydantic ValidationError into field-addressed repair instructions."""
    errs = getattr(exc, "errors", None)
    try:
        items = errs() if callable(errs) else None
    except Exception:
        items = None
    if not items:
        return f"the document is not valid CadIR ({type(exc).__name__})"
    lines = []
    for err in items[:limit]:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        lines.append(f"{loc or '<document>'}: {err.get('msg', 'invalid')}")
    more = len(items) - len(lines)
    if more > 0:
        lines.append(f"(+{more} more)")
    return "the document is not valid CadIR — " + "; ".join(lines)


def _plan_document(document: dict, params: dict) -> tuple[object, dict, float, str, int, list]:
    """Parse, resolve and charge a CadIR document — all of it before a slot is taken.

    Everything here is arithmetic on validated numbers; :mod:`cadir.budget` is
    kernel-free precisely so this can run in the server process. A document that
    cannot finish is refused now, in milliseconds, instead of burning a concurrency
    slot for the full deadline and answering with a timeout.

    Takes the document and params rather than the request, because ``/cad/validate``
    runs exactly this and nothing else — and the point of that endpoint is that it is
    the *same* check, not a second implementation that could answer differently.
    """
    try:
        doc = cadir.parse(document)
    except (cadir.ExprError, cadir.ParamError) as e:
        raise _err(400, e.code, e.message)
    except Exception as e:
        # Pydantic names every field it walked. The caller sent this document, so
        # echoing back which of its own fields failed leaks nothing it does not
        # already have — and it is the only thing that makes a repair possible.
        # A generator told "not valid CadIR" can only guess; told "operations.1.op:
        # unexpected value" it can fix the line. Capped so a document that is wrong
        # everywhere does not answer with a wall of text.
        raise _err(400, "invalid_document", _validation_detail(e))

    try:
        resolved = cadir.resolve_params(doc, params or {})
        _env, steps, cost = cadir.check(doc, resolved)
    except cadir.ParamError as e:
        raise _err(400, e.code, e.message)
    except cadir.BudgetError as e:
        raise _err(400, "too_complex", e.message)
    except cadir.ExprError as e:
        raise _err(400, e.code, e.message)

    return doc, resolved, cost, doc.name, doc.expected_solids, steps


def _plan_recipe(req: BuildV2Req) -> tuple[None, dict, float, str, int]:
    if req.recipe not in recipes.RECIPES:
        raise _err(400, "unknown_recipe", f"unknown recipe: {req.recipe}")
    try:
        resolved = recipes.resolve_params(req.recipe, req.params or {})
    except recipes.ParamError as e:
        raise _err(400, e.code, e.message)

    cost = recipes.estimate_cost(req.recipe, resolved)
    cap = recipes.cost_cap(req.recipe)
    if cost > cap:
        raise _err(400, "too_complex",
                   f"estimated complexity {cost} exceeds the cap of {cap}")
    return None, resolved, cost, req.recipe, recipes.RECIPE_SOLIDS.get(req.recipe, 1)


class ValidateReq(BaseModel):
    """What ``/cad/validate`` accepts — a document and the parameters it would run with.

    No ``recipe`` arm: a recipe is a vetted Python function whose validity is not in
    question, and the caller that needs this endpoint is generating CadIR.
    """

    model_config = ConfigDict(extra="forbid")

    document: dict
    params: dict[ParamName, Number] = Field(default_factory=dict, max_length=MAX_PARAMS)


@app.post("/cad/validate")
def validate(req: ValidateReq):
    """Static-check a CadIR document without building anything.

    This is the same call ``/cad/v2/build`` makes before it takes a concurrency slot —
    literally the same function — so a document that passes here fails geometry only
    for reasons geometry can discover (a fillet radius the edges cannot take, a boolean
    that leaves the wrong solid count). A second, laxer validator would be worse than
    none: it would tell a generator its document was fine and let the engine disagree.

    It costs no worker, no slot and no OCP import, which is what makes a bounded repair
    loop affordable — a generated document can be corrected several times for less than
    one build.

    ``operations`` reports the *planned* instance count per operation, which is the
    number the budget charged for. An operation reporting ``0`` was skipped, either by
    its ``when`` guard or by a grid that resolved to no positions. That distinction is
    invisible in a document and is the most common way a generated part comes out
    missing a feature it clearly declares.
    """
    doc, resolved, cost, name, expected_solids, steps = _plan_document(
        req.document, req.params)

    planned = {op.op_id: len(pts) for op, pts in steps}
    return {
        "ok": True,
        "schema_version": cadir.SCHEMA_VERSION,
        "name": name,
        "units": doc.units,
        "expected_solids": expected_solids,
        "cost": cost,
        "cost_cap": cadir.budget.MAX_COST,
        "parameters": resolved,
        "operations": [
            {
                "op_id": op.op_id,
                "op": op.op,
                "mode": getattr(op, "mode", "add"),
                "instances": planned.get(op.op_id, 0),
                "skipped": planned.get(op.op_id, 0) == 0,
            }
            for op in doc.operations
        ],
    }


class ProjectReq(BaseModel):
    """What ``/cad/project`` accepts.

    ``spec`` and ``node_ids`` are context the document does not carry — the DesignSpec
    the revision was authored against, and the scene-manifest node id of each component's
    body. Both are optional: without them the project still compiles back to the
    document, it just cannot say which viewport node a part file draws.
    """

    model_config = ConfigDict(extra="forbid")

    document: dict
    params: dict[ParamName, Number] = Field(default_factory=dict, max_length=MAX_PARAMS)
    spec: dict | None = None
    node_ids: dict[ParamName, str] = Field(default_factory=dict, max_length=64)


@app.post("/cad/project")
def cad_project(req: ProjectReq):
    """A stored document as the multi-file project it is, plus its source graph.

    This is the read half of :mod:`cadir.project`. It builds nothing and takes no
    concurrency slot — it parses, emits and maps, so a panel can ask for it on every
    revision without competing with geometry for a worker.

    Two properties the caller may rely on:

    * every file is *real source*. ``compile_project`` reconstructs the stored document
      from this tree, and ``test_project.py`` asserts that round trip over every golden
      document. The old backend-side slice could not make that claim, which is why it
      was a decoration.
    * a document the parser **rejects** still gets a project and a feature list, with
      ``source_graph.complete: false``. The document a person most needs to read is the
      one that failed to build, and refusing to describe it would hide exactly the case
      the code panel exists for. What a partial graph does not contain is invented
      parameter edges — a consumer it could not resolve is absent, never guessed.

    ``obj`` is stripped from each file: it is the parsed form the compiler reads, it
    doubles the payload, and no reader needs it. An authoring path that wants to compile
    edits back will POST the files, not read them.
    """
    files = cadir.project.decompose(
        req.document, spec=req.spec, node_ids=dict(req.node_ids))

    # Resolution is best-effort on purpose. A document that cannot resolve its own
    # parameters is precisely the one whose graph is worth reading, and it still reports
    # every declared default — it just cannot say what a formula computed.
    resolved = None
    try:
        parsed = cadir.parse(req.document)
        resolved = cadir.resolve_params(parsed, req.params)
        try:
            # ``build_env`` is the interpreter's own function, so a derived value this
            # panel prints is the value the build used rather than a second opinion
            # computed here. It is nested because one derived formula that will not
            # evaluate outside a build should cost that one value — falling to the outer
            # handler would blank every parameter over it.
            resolved = cadir.build_env(parsed, resolved)
        except Exception:
            log.debug("cad/project: derived values did not evaluate", exc_info=True)
    except Exception:
        log.debug("cad/project: parameters did not resolve; graph will be partial",
                  exc_info=True)

    graph = cadir.project.source_graph(req.document, files, resolved)
    return {
        "ok": True,
        "source_version": cadir.project.SOURCE_VERSION,
        "schema_version": cadir.SCHEMA_VERSION,
        "files": [{k: v for k, v in f.items() if k != "obj"} for f in files],
        "source_graph": graph,
    }


@app.post("/cad/v2/build")
def build_v2(req: BuildV2Req):
    formats, wanted = _resolve_formats(req.formats)

    if req.document is not None:
        _doc, resolved, cost, label, expected_solids, _steps = _plan_document(
            req.document, req.params)
    else:
        _doc, resolved, cost, label, expected_solids = _plan_recipe(req)

    build_id = req.build_id or uuid.uuid4().hex
    try:
        with admission.slot():
            return _build_and_frame(resolved, formats, wanted, cost, build_id,
                                    label=label, expected_solids=expected_solids,
                                    document=req.document,
                                    deadline_s=req.deadline_s,
                                    scope=req.scope,
                                    measurements=req.measurements)
    except admission.QueueFull as e:
        raise _err(429, "queue_full", str(e))
    except runner.BuildTimeout as e:
        log.warning("build %s hit the deadline for source=%s", build_id, label)
        raise _err(504, "build_timeout", str(e))
    except runner.BuildCancelled:
        raise _err(409, "build_cancelled", "the build was cancelled")
    except runner.BuildFailed as e:
        status = 400 if e.code in ("unknown_param", "param_out_of_range",
                                   "invalid_document", "too_complex") else 500
        extra = {"scene_manifest": e.scene_manifest} if e.scene_manifest else {}
        raise _err(status, e.code, e.message, **extra)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("unhandled failure for source=%s", label)
        raise _err(500, "internal_error", f"unexpected failure ({type(e).__name__})")


def _build_and_frame(resolved: dict, formats: list[str],
                     wanted: list[str], cost: float, build_id: str, *,
                     label: str, expected_solids: int,
                     document: dict | None = None,
                     asset: tuple[str, bytes] | None = None,
                     deadline_s: float | None = None,
                     scope: str | None = None,
                     measurements: list[dict] | None = None) -> Response:
    """Read every artifact inside the workdir's lifetime, then frame them.

    Reading into memory rather than streaming from disk is deliberate: the workdir
    dies with the ``with`` block, and a streaming response would still be reading
    from it after that. Bounded by MAX_RESPONSE_BYTES, which is why that cap exists.

    Takes the three source kinds as plain arguments rather than a request model. It
    used to take ``BuildV2Req``, which was fine while that model described every
    caller; Gate 8B's import arrives as raw bytes with its filename in the query, has
    no such model, and would have needed either a fake one or a second copy of this
    function — and a second copy is how the two endpoints' caps drift apart.
    """
    with runner.run_build(
        label, resolved,
        document=document,
        asset=asset,
        step="step" in formats, formats=formats,
        deadline_s=deadline_s or runner.DEADLINE_S,
        build_id=build_id,
        scope=scope,
        measurements=measurements,
    ) as outcome:
        result = outcome.result
        metrics = result["metrics"]
        mesh = result["mesh"]
        # Only an import carries provenance, and its presence is what switches the
        # verdict. Reading it off the child's own result rather than off `asset`
        # keeps the decision anchored to what the worker actually parsed.
        provenance = result.get("provenance")
        _enforce_output_caps(outcome, expected_solids, metrics, mesh, provenance)

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

        payload = {
            "ok": True,
            "build_id": build_id,
            # The label whichever the source: a recipe name, the document's own `name`,
            # or the uploaded file's stem. The key stays `recipe` because the backend
            # and the store already read it and the other two are exactly as much of an
            # identifier.
            "recipe": label,
            "source_kind": ("import" if asset is not None
                            else "cadir" if document is not None else "recipe"),
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
                # HE-2, and present only when the caller asked for measurements — a build
                # that asked for none answers exactly what it answered before this gate.
                # `measurement_incomplete` says the child was asked and did not answer, so
                # every check that wanted a number grades `unverified`: a missing
                # measurement is an unknown, never a defect.
                **({"measurements": result["measurements"]}
                   if result.get("measurements") is not None else {}),
                **({"measurement_incomplete": True}
                   if measurements and result.get("measurements") is None else {}),
            },
        }
        if provenance is not None:
            # A top-level key, not folded into `validation`. Provenance is what the file
            # was — bytes, digest, parser, whether the geometry is exact — and it stays
            # true for the life of the artifact. `validation` is a verdict about one
            # build. The store persists them for different reasons.
            payload["provenance"] = provenance
        scene = result.get("scene_manifest")
        if scene is not None:
            # In the JSON part rather than as a fifth blob. It is a few kilobytes, the
            # backend needs it on every workspace read, and making it an artifact would
            # mean a second authorized fetch to draw the tree that describes the first.
            payload["scene_manifest"] = scene
        return _multipart(payload, blobs)


@app.post(_IMPORT_PATH)
async def import_v2(
    request: Request,
    name: str = Query(min_length=1, max_length=128,
                      description="the uploaded file's own name, used for its extension"),
    formats: str = Query(default="stl,glb",
                         description="comma-separated export formats"),
    deadline_s: float | None = Query(default=None, gt=0, le=runner.DEADLINE_S),
    build_id: str | None = Query(default=None, min_length=1, max_length=64),
):
    """Turn an uploaded STEP/STL/3MF/BREP file into a build, exactly like any other.

    **The body is the file** — raw bytes, no multipart, no base64, with the metadata in
    the query string. Base64 would inflate a 32 MB asset to 43 MB and then hand it to a
    JSON parser; multipart would add a parser dependency to the one container that must
    not grow parsers casually. Raw bytes need neither and are exactly what
    :func:`_read_body_capped` can bound as they arrive.

    The parsing happens in the killable child (:mod:`importers`, dispatched through
    ``worker_main``'s ``source_kind: "import"``), not here. That is the whole reason
    imports waited for Gate 1B: a malformed STEP is code from outside driving OCCT, and
    Gate 1B is what makes a build that will not finish stoppable. The server does the
    cheap refusals — extension, size, format list — and nothing else.

    What comes back is a normal ``/cad/v2/build`` response with a ``provenance`` block
    added and ``source_kind: "import"``. There is no ``recovered_features`` path and no
    branch that could set one: STEP arrives as exact reference geometry, meshes arrive
    as mesh bodies, and neither is a feature history. GLB and glTF are refused by name
    with the reason, because build123d ships no reader for them — they are an export
    format here, not an import one.
    """
    # Extension first: it costs nothing and it is the only thing that decides which
    # parser would run. `kind_for` also refuses a path, so `name` cannot escape the
    # workdir even before the child re-checks it.
    try:
        kind = importers.kind_for(name)
    except importers.ImportRejected as e:
        raise _err(400, e.code, e.message)

    formats_list = [f.strip() for f in formats.split(",") if f.strip()]
    if not formats_list:
        raise _err(400, "invalid_request", "formats must name at least one format")
    if len(formats_list) > len(exporters.FORMATS):
        raise _err(400, "invalid_request", "too many formats requested")
    build_formats, wanted = _resolve_formats(formats_list)

    data = await _read_body_capped(request, MAX_IMPORT_BODY_BYTES)
    if not data:
        raise _err(400, "import_empty", "the uploaded file is empty")
    if len(data) > importers.MAX_ASSET_BYTES:
        raise _err(413, "import_too_large",
                   f"the file is {len(data)} bytes, over the cap of "
                   f"{importers.MAX_ASSET_BYTES}")

    label = os.path.splitext(os.path.basename(name))[0] or "imported"
    bid = build_id or uuid.uuid4().hex
    try:
        with admission.slot():
            return _build_and_frame(
                {}, build_formats, wanted,
                # There is no static complexity to price: an import has no parameters
                # and no operation tree, and the only honest proxy for its cost is how
                # much file the parser has to read. Reported so the number means
                # something, never charged against a recipe's cap, which was calibrated
                # on authored geometry.
                float(len(data)), bid,
                label=label,
                # Unused on this path — `provenance` routes the verdict to
                # `import_verdict`, which does not assert a solid count. Passed as 1 so
                # the signature stays honest about being shared rather than growing an
                # optional that only one caller ever reads.
                expected_solids=1,
                asset=(os.path.basename(name), data),
                deadline_s=deadline_s,
            )
    except admission.QueueFull as e:
        raise _err(429, "queue_full", str(e))
    except runner.BuildTimeout as e:
        log.warning("import %s hit the deadline for %s (%d bytes)", bid, kind, len(data))
        raise _err(504, "build_timeout", str(e))
    except runner.BuildCancelled:
        raise _err(409, "build_cancelled", "the import was cancelled")
    except runner.BuildFailed as e:
        # A rejected or unreadable file is the caller's problem to fix, so it answers
        # 400 rather than 500. Every one of these codes originates in `importers` and
        # carries a sentence naming what was wrong with the file — the caller can act
        # on "that STL's header claims more triangles than the file holds"; it cannot
        # act on a 500.
        status = 400 if e.code in importers.ERROR_CODES else 500
        raise _err(status, e.code, e.message)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("unhandled failure importing %s", kind)
        raise _err(500, "internal_error", f"unexpected failure ({type(e).__name__})")
