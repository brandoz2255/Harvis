"""Adaptive Workspace CAD client (Stage 2) — talks to the isolated build123d
sidecar (``cad-engine``) over the internal network.

The heavy OCP/OCCT kernel lives in its own container so its pins can't conflict
with the backend's torch/numpy stack. This module just: gates on an env flag,
maps the space's criteria (manifest.meta ``crit_*``) to recipe params, calls the
sidecar, and hands back the STL/STEP bytes + geometry metadata. No CAD runs here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import uuid

import httpx

from . import cad_ir

log = logging.getLogger(__name__)

# What this client will read off the wire in one response, independent of what the
# engine says it is sending. The engine caps itself at the same number; this one
# exists because a client that trusts a server's self-imposed limit has no limit.
MAX_RESPONSE_BYTES = 96 * 1024 * 1024

# The engine's grammar description, per engine URL. Not a TTL cache: the answer is a
# property of the running image, so the only event that can change it is a restart of
# one side or the other, and both clear this.
_SCHEMA_CACHE: dict[str, dict] = {}

# The recipe the Adaptive Space lane builds. It stays the default rather than becoming
# a required argument because that lane's criteria (`crit_arm_length_mm` and friends)
# only describe a hanger — but since Gate 2 there is a second recipe, so `execute()`
# takes the name and validates it instead of hardcoding one.
DEFAULT_RECIPE = "helmet_hanger_v1"
RECIPE = DEFAULT_RECIPE  # retained: existing callers import this name

# Recipes this client will ask for. A local allowlist, not a mirror of the sidecar's:
# the sidecar's own allowlist is the one that must hold, and duplicating it here means
# a typo costs a rejected call instead of a network round trip and a 400.
KNOWN_RECIPES = ("helmet_hanger_v1", "studded_brick_v1")

# Formats this client will ask /cad/v2/build for, for the same reason as above.
KNOWN_FORMATS = ("stl", "step", "glb", "3mf")

# What /cad/v2/import will READ, which is deliberately not KNOWN_FORMATS. GLB and glTF
# are missing on purpose: build123d writes glTF and ships no reader for it, and neither
# `trimesh` nor `pygltflib` is installed in the engine. Advertising one list for both
# directions would promise a round trip that does not exist, so a caller that offers
# "import a model" from KNOWN_FORMATS would be offering something that always fails.
KNOWN_IMPORT_KINDS = ("step", "stp", "stl", "3mf", "brep", "brp")

# Mirrors the engine's `importers.MAX_ASSET_BYTES` default. Checked here so an
# oversized upload is refused before 32 MB crosses the internal network; the engine
# re-checks, and its refusal is the one that counts on a deployment that raised
# `CAD_IMPORT_MAX_BYTES` without telling the backend.
MAX_IMPORT_BYTES = int(os.environ.get("CAD_IMPORT_MAX_BYTES", 32 * 1024 * 1024))

# Extension → the name the engine's importer switches on, mirroring its `_EXT_KIND`.
# Recording `.stp` as "step" keeps the revision's provenance and the build's saying the
# same word for the same reader, which is what makes the two comparable at all.
IMPORT_KIND_ALIASES = {"stp": "step", "brp": "brep"}

_TRUTHY = {"1", "true", "yes", "on"}


def import_kind_for(name: str) -> str | None:
    """The canonical reader name for a filename, or None if we will not read it.

    Extension only, like the engine's own :func:`importers.kind_for`. Sniffing the
    content to choose a parser would let the file pick which C++ reader gets it; the
    engine's `precheck` is what confirms the bytes match the extension's claim.
    """
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    if ext not in KNOWN_IMPORT_KINDS:
        return None
    return IMPORT_KIND_ALIASES.get(ext, ext)


class CadError(RuntimeError):
    """A sidecar failure with the structured code it reported.

    Exists so the route layer can surface something repairable instead of the raw
    ``httpx.HTTPStatusError``, whose string form carries the internal sidecar URL
    into a user-facing 502.

    ``scene_manifest`` rides along when the engine managed to describe the tree it was
    attempting before the geometry broke. It is the one case where a failure carries
    structure worth keeping: the workspace has to show which operation went wrong, and
    a failed build leaves no GLB to derive that from. Absent on every other failure,
    which is honest — an engine that never started knows nothing about the part.
    """

    def __init__(self, code: str, message: str, status: int | None = None,
                 scene_manifest: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.scene_manifest = scene_manifest

    def __str__(self) -> str:  # what the route interpolates into its 502
        return f"{self.message} [{self.code}]"

# Per-param clamp ranges (mm / count) — the numeric trust boundary for overrides.
_LIMITS = {
    "arm_len_mm": (10, 500), "arm_w_mm": (2, 80), "arm_h_mm": (2, 80),
    "plate_t_mm": (1, 40), "plate_w_mm": (5, 300), "plate_h_mm": (5, 300),
    "hook_h_mm": (2, 150), "fillet_r_mm": (0, 20), "screw_d_mm": (1, 20),
    "screw_count": (0, 6),
}


def cad_enabled() -> bool:
    return (os.getenv("HARVIS_ADAPTIVE_CAD_ENABLED") or "").strip().lower() in _TRUTHY


def _cad_url() -> str:
    return (os.getenv("HARVIS_ADAPTIVE_CAD_URL") or "http://harvis-cad:8000").rstrip("/")


def cad_status() -> str:
    """Honest tool status for the dock: 'ready' when the operator has enabled the
    engine, otherwise 'disabled'. Execution-time failures are surfaced honestly;
    we don't do a live HTTP probe on every manifest read."""
    return "ready" if cad_enabled() else "disabled"


def _num(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    # NaN fails every comparison, so `f > 0` already rejected it — but relying on that
    # is relying on an accident. Say it outright.
    return f if math.isfinite(f) and f > 0 else default


def params_from_meta(meta: dict | None, overrides: dict | None = None) -> dict:
    """Map the criteria the UI already gathers into recipe params. Geometry-only —
    material/load are for the stress analysis, not the shape."""
    meta = meta or {}
    p = {
        "arm_len_mm": _num(meta.get("crit_arm_length_mm"), 100),
        "arm_w_mm": _num(meta.get("crit_arm_width_mm"), 12),
        "arm_h_mm": _num(meta.get("crit_arm_height_mm"), 8),
        "plate_t_mm": 6,
        "plate_w_mm": 40,
        "plate_h_mm": 44,
        "hook_h_mm": 18,
        "fillet_r_mm": 3,
        "screw_d_mm": 4,
    }
    try:
        sc = int(meta.get("crit_screw_count") or 2)
        p["screw_count"] = max(0, min(6, sc))
    except (TypeError, ValueError):
        p["screw_count"] = 2
    # Client overrides are numeric-validated and clamped per key — never a
    # pass-through assignment (which would defeat the screw_count clamp above and
    # let a crafted request drive an unbounded OCP boolean loop on the sidecar).
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k not in _LIMITS:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            # Clamp order decides whether NaN survives, which is a terrible thing for
            # safety to depend on: `max(lo, min(hi, nan))` happens to return hi, while
            # the sidecar's `min(max(nan, lo), hi)` returns nan and hangs OpenCascade.
            # Drop non-finite values explicitly instead of trusting the argument order.
            if not math.isfinite(fv):
                continue
            lo, hi = _LIMITS[k]
            p[k] = max(lo, min(hi, fv))
    p["screw_count"] = max(0, min(6, int(p.get("screw_count", 2))))
    return p


def _reject_non_finite(params: dict) -> None:
    """Last check on this side of the wire. The sidecar rejects non-finite values too,
    and that layer is the one that must hold — but a value that cannot produce geometry
    should not cost a network round trip, and httpx would refuse to serialise it anyway
    with a bare ``ValueError`` that says nothing useful."""
    for k, v in (params or {}).items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CadError("invalid_param", f"{k} must be a number")
        if not math.isfinite(float(v)):
            raise CadError("invalid_param", f"{k} must be a finite number")


def _parse_multipart(content_type: str, body: bytes) -> tuple[dict, dict[str, bytes]]:
    """Read ``/cad/v2/build``'s response: one JSON part named ``result``, then one
    file part per format, named by the format.

    Deliberately strict and deliberately small. A general-purpose multipart reader
    handles nested bodies, transfer encodings and header continuations that this hop
    never produces — surface we would be maintaining for nothing. Both ends of this
    wire are ours, so anything not in the shape below is a bug or an impostor, and
    either way the right answer is to refuse rather than to cope.
    """
    marker = "boundary="
    if not content_type.startswith("multipart/form-data;") or marker not in content_type:
        raise CadError("bad_response", "the CAD engine did not answer with multipart")
    sep = b"--" + content_type.split(marker, 1)[1].strip().encode()

    if not body.startswith(sep + b"\r\n") or not body.endswith(sep + b"--\r\n"):
        raise CadError("bad_response", "the CAD engine's response was truncated")

    parts: dict[str, bytes] = {}
    for chunk in body[: -len(sep) - 4].split(sep + b"\r\n"):
        if not chunk:
            continue
        head, found, payload = chunk.partition(b"\r\n\r\n")
        if not found or not payload.endswith(b"\r\n"):
            raise CadError("bad_response", "a response part was malformed")
        name = None
        for line in head.decode("utf-8", "replace").split("\r\n"):
            key, _, value = line.partition(":")
            if key.strip().lower() == "content-disposition" and 'name="' in value:
                name = value.split('name="', 1)[1].split('"', 1)[0]
        if not name or name in parts:
            raise CadError("bad_response", "a response part was unnamed or repeated")
        parts[name] = payload[:-2]

    raw = parts.pop("result", None)
    if raw is None:
        raise CadError("bad_response", "the CAD engine sent no result part")
    try:
        result = json.loads(raw)
    except ValueError:
        raise CadError("bad_response", "the CAD engine's result part was not JSON")
    if not isinstance(result, dict):
        raise CadError("bad_response", "the CAD engine's result part was not an object")
    return result, parts


def _verify_artifacts(result: dict, files: dict[str, bytes]) -> None:
    """Cross-check the bytes against what the result part says they are.

    Not paranoia about the network — this is the same hash Gate 3 stores in
    ``cad_artifacts.sha256`` and re-checks on read. Computing it here, from the
    bytes that will actually be written, is what makes that stored value mean
    something; taking the engine's word for it would store a hash of bytes nobody
    ever verified.
    """
    refs = {}
    for ref in result.get("artifacts") or []:
        if isinstance(ref, dict) and isinstance(ref.get("format"), str):
            refs[ref["format"]] = ref

    if set(refs) != set(files):
        raise CadError("bad_response",
                       "the CAD engine's artifact list did not match the files sent")
    for fmt, blob in files.items():
        ref = refs[fmt]
        if ref.get("size_bytes") != len(blob):
            raise CadError("bad_response", f"the {fmt} artifact was the wrong length")
        if ref.get("sha256") != hashlib.sha256(blob).hexdigest():
            raise CadError("bad_response", f"the {fmt} artifact failed its checksum")


def _decode_build_response(r) -> tuple[dict, dict[str, bytes]]:
    """One reader for every build-shaped reply, whether it came from a recipe, a
    document or an imported file.

    Structured errors first, because the engine's ``error_code`` is the only thing
    that tells "your file is wrong" apart from "the engine is down", and a caller that
    lost it has nothing to show a user but a status number.
    """
    if r.status_code >= 400:
        code, message = "engine_error", "the CAD engine rejected the request"
        scene = None
        try:
            detail = (r.json() or {}).get("detail")
            if isinstance(detail, dict):
                code = detail.get("error_code") or code
                message = detail.get("message") or message
                # Only when the engine got far enough to know the shape of the part
                # it was building. `_err` puts nothing else structured in here, and
                # anything it does not recognise is dropped rather than stored.
                if isinstance(detail.get("scene_manifest"), dict):
                    scene = detail["scene_manifest"]
            elif isinstance(detail, str):
                message = detail
        except ValueError:
            pass
        raise CadError(code, message, status=r.status_code, scene_manifest=scene)

    if len(r.content) > MAX_RESPONSE_BYTES:
        raise CadError("response_too_large",
                       f"the CAD engine sent {len(r.content)} bytes")

    data, files = _parse_multipart(r.headers.get("content-type", ""), r.content)
    _verify_artifacts(data, files)
    return data, files


async def schema(timeout: float = 5.0) -> dict:
    """The engine's own description of the CadIR grammar.

    Fetched rather than kept here for the reason :mod:`cad_ir` says at length: the
    grammar lives in the sidecar image, and a copy on this side would drift the first
    time an operation gained a field. What comes back is derived from the engine's
    pydantic models at its import time, so it describes the language that container
    will actually parse — not the one this repository's source says it should.

    Cached for the process, keyed on the engine URL. The answer changes only when the
    image does, and a restart is what picks that up.
    """
    url = _cad_url()
    hit = _SCHEMA_CACHE.get(url)
    if hit is not None:
        return hit
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{url}/cad/schema")
    except httpx.HTTPError:
        raise CadError("engine_unreachable", "the CAD engine could not be reached")
    if r.status_code == 404:
        # An older engine image. Say which half is missing rather than reporting the
        # lane as broken — builds still work, only the grammar reference is absent.
        raise CadError("schema_unavailable",
                       "this CAD engine build does not publish the CadIR grammar")
    if r.status_code >= 400:
        raise CadError("engine_error", "the CAD engine rejected the schema request",
                       status=r.status_code)
    try:
        out = r.json()
    except ValueError:
        raise CadError("engine_error", "the CAD engine sent an unreadable schema")
    if not isinstance(out, dict):
        raise CadError("engine_error", "the CAD engine sent an unreadable schema")
    _SCHEMA_CACHE[url] = out
    return out


async def validate_document(document: dict, params: dict | None = None,
                            timeout: float = 10.0) -> dict:
    """Static-check a document without building it.

    The same function ``/cad/v2/build`` runs before it takes a concurrency slot, so a
    document that passes here fails only for reasons geometry can discover. It costs
    no worker and no OCP import, which is what makes it affordable to run at *propose*
    time — before a revision row and a build row exist for a document that was never
    going to build.

    Raises :class:`CadError` with the engine's structured code, exactly as
    :func:`execute` does, so a caller can hand a model the same repairable message it
    would have got from a failed build — several rounds earlier and for far less.
    """
    params = params or {}
    try:
        cad_ir.check_document(document)
        cad_ir.check_params(params)
    except cad_ir.CadIRError as e:
        raise CadError(e.code, e.message)
    _reject_non_finite(params)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{_cad_url()}/cad/validate",
                                  json={"document": document, "params": params})
    except httpx.HTTPError:
        raise CadError("engine_unreachable", "the CAD engine could not be reached")

    if r.status_code >= 400:
        code, message = "engine_error", "the CAD engine rejected the document"
        try:
            detail = (r.json() or {}).get("detail")
            if isinstance(detail, dict):
                code = detail.get("error_code") or code
                message = detail.get("message") or message
            elif isinstance(detail, str):
                message = detail
        except ValueError:
            pass
        raise CadError(code, message, status=r.status_code)
    try:
        return r.json() or {}
    except ValueError:
        raise CadError("engine_error", "the CAD engine sent an unreadable answer")


async def project_document(document: dict, params: dict | None = None, *,
                           spec: dict | None = None,
                           node_ids: dict[str, str] | None = None,
                           timeout: float = 10.0) -> dict:
    """The multi-file project behind a document, and its parameter dependency graph.

    Read-only: it emits and maps, builds nothing, and takes no concurrency slot, so a
    panel may ask on every revision without competing with geometry for a worker.

    It goes to the engine rather than slicing the document here for one reason that is
    not convenience. ``cad_ir`` says so in its own docstring: the backend holds no copy
    of the CadIR grammar and cannot import one, because the grammar lives in the sidecar
    image. A tree assembled on this side would be a *resemblance* of the source — close
    enough to read, and unable to promise that compiling it back yields the document the
    engine executed. The engine's ``decompose``/``compile_project`` pair is tested on
    exactly that round trip.

    Unlike :func:`validate_document` there is no local pre-check. A document the parser
    rejects is precisely the one someone needs to read, and refusing to describe it would
    blank the code panel exactly when it matters. The engine answers for it and marks the
    graph partial.

    Raises :class:`CadError` the same way every other call here does, so a caller can
    tell "the engine is down" from "the engine refused this" instead of quietly showing
    something it made up.
    """
    params = params or {}
    _reject_non_finite(params)

    body: dict = {"document": document, "params": params}
    if spec is not None:
        body["spec"] = spec
    if node_ids:
        body["node_ids"] = node_ids

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{_cad_url()}/cad/project", json=body)
    except httpx.HTTPError:
        raise CadError("engine_unreachable", "the CAD engine could not be reached")

    if r.status_code == 404:
        # An engine built before this route existed. Named separately because the fix is
        # a rebuild, not a retry, and "unreachable" would send someone to check the
        # network on a container that is answering fine.
        raise CadError("engine_outdated",
                       "this CAD engine has no /cad/project — rebuild it to read source",
                       status=404)
    if r.status_code >= 400:
        code, message = "engine_error", "the CAD engine rejected the document"
        try:
            detail = (r.json() or {}).get("detail")
            if isinstance(detail, dict):
                code = detail.get("error_code") or code
                message = detail.get("message") or message
            elif isinstance(detail, str):
                message = detail
        except ValueError:
            pass
        raise CadError(code, message, status=r.status_code)
    try:
        return r.json() or {}
    except ValueError:
        raise CadError("engine_error", "the CAD engine sent an unreadable answer")


async def cancel(build_id: str, timeout: float = 5.0) -> bool:
    """Best-effort stop for a build this process started. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{_cad_url()}/cad/cancel/{build_id}")
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def execute(
    params: dict,
    want_step: bool = True,
    timeout: float = 30.0,
    build_id: str | None = None,
    recipe: str = DEFAULT_RECIPE,
    formats: list[str] | tuple[str, ...] | None = None,
    document: dict | None = None,
    scope: str | None = None,
    measurements: list[dict] | None = None,
) -> dict:
    """Call the sidecar; return {meta, artifacts, stl_bytes, step_bytes|None, ...}.

    Raises :class:`CadError` on any failure, carrying the sidecar's structured code
    so the caller can tell "you asked for something impossible" apart from "the
    engine is down".

    ``document`` builds a CadIR source instead of a named recipe; the two are
    mutually exclusive and ``recipe`` is ignored when a document is given. The
    engine still owns the grammar and the budget — what happens here is a coarse
    size/shape fence so a plainly malformed document costs nothing.

    ``measurements`` is the HE-2 request list. It travels with the build because the
    numbers have to be taken where the shape lives — inside the engine's killable
    child — and never on a re-import here, where the tessellation has already thrown
    away the exact surfaces every one of them is fitted to.

    ``scope`` is what the scene manifest's node ids are hashed from — pass something
    the *server* owns and that outlives a single build, such as the project id. Left
    unset, the engine falls back to the document's own ``name``, which is a field the
    authoring model writes: rename the document on the next turn and every part gets a
    new id, silently resetting selection and the colours keyed on it.

    Talks to ``/cad/v2/build``, which sends the artifacts as bytes. The frozen
    ``/cad/execute`` is still there and still correct; it base64s every file, which
    costs a third of the largest payload in the system on a hop where nothing needs
    the encoding. ``stl_bytes`` and ``step_bytes`` stay in the returned dict because
    the Adaptive Space route reads them by name — ``artifacts`` is how a caller
    reaches GLB or 3MF.

    Three nested deadlines, innermost first: the sidecar kills the build's process
    group at ``CAD_BUILD_DEADLINE_S`` + grace (20 s + 3 s by default), this client
    gives up at ``timeout`` (30 s), and nginx gives up after that. Each layer must
    outlast the one it depends on — a client that gives up first learns nothing and
    leaves the work running.
    """
    # Two source kinds. A recipe must name something the engine has compiled in, so
    # the allowlist is the whole check. A document has no name to check against — the
    # engine owns the grammar, and `cad_ir` here is only a coarse fence that refuses
    # the obviously-wrong before it costs a round trip. Neither layer is the other's
    # substitute: this one cannot see the budget, and the engine cannot see the DB.
    if document is not None:
        try:
            cad_ir.check_document(document)
            cad_ir.check_params(params)
        except cad_ir.CadIRError as e:
            raise CadError(e.code, e.message)
    elif recipe not in KNOWN_RECIPES:
        raise CadError("unknown_recipe", f"unknown recipe: {recipe}")
    _reject_non_finite(params)

    if formats is None:
        wanted = ["stl", "step"] if want_step else ["stl"]
    else:
        wanted = [f for f in formats if f in KNOWN_FORMATS]
        if not wanted:
            raise CadError("unknown_format", "no supported format was requested")

    build_id = build_id or uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{_cad_url()}/cad/v2/build",
                json={
                    # Exactly one source, matching BuildV2Req's own validator. Sending
                    # both would be refused, and sending the recipe alongside a
                    # document would quietly describe the wrong part.
                    **({"document": document} if document is not None
                       else {"recipe": recipe}),
                    "params": params,
                    "formats": wanted,
                    "build_id": build_id,
                    # Omitted rather than sent as null when the caller owns no stable
                    # scope, so the engine's own fallback stays the single definition
                    # of what happens then.
                    **({"scope": scope} if scope else {}),
                    # HE-2/HE-3. What to measure on the result, in the grammar the
                    # engine's `measure_spec` owns. Omitted rather than sent empty
                    # when there is nothing to ask: a build that requested no
                    # measurements must answer exactly what it answered before this
                    # gate, so the absence of the key is what keeps the old shape.
                    **({"measurements": measurements} if measurements else {}),
                },
            )
    except httpx.TimeoutException:
        # Reaching here means the sidecar's own deadline did not fire first, which
        # should be impossible with the defaults above and is worth a log line if it
        # ever happens. Cancel anyway rather than assume — since Gate 1B there is
        # finally something on the other end that can act on it.
        log.warning("cad build %s outlived the client timeout of %.0fs", build_id, timeout)
        await cancel(build_id)
        raise CadError("engine_timeout", f"the CAD engine did not answer within {timeout:.0f}s")
    except httpx.HTTPError:
        raise CadError("engine_unreachable", "the CAD engine could not be reached")

    data, files = _decode_build_response(r)

    return {
        "meta": data.get("meta", {}),
        # format -> bytes, every file the caller asked for.
        "artifacts": files,
        # Named accessors for the two the Adaptive Space route writes to disk. `stl`
        # is absent only if the caller excluded it, so this is `.get`, not `[...]`.
        "stl_bytes": files.get("stl", b""),
        "step_bytes": files.get("step"),
        # Additive since Gate 1A: the sidecar now reports B-Rep validity, solid count
        # and a watertight-mesh verdict instead of only bbox + volume.
        "validation": data.get("validation") or {},
        "params": data.get("params") or {},
        # The hashes Gate 3's cad_artifacts rows are built from — already verified
        # against the bytes above, so a caller can store them without re-hashing.
        "artifact_refs": data.get("artifacts") or [],
        "build_id": data.get("build_id") or build_id,
        # Which lane actually ran, as the engine reports it rather than as this
        # function assumed. `recipe` is the label either way — a recipe name, or the
        # document's own `name` — and is what `cad_revisions.recipe_name` records.
        "source_kind": data.get("source_kind") or "recipe",
        "recipe": data.get("recipe") or recipe,
        # UX-A. The semantic tree, and the pick keys that tie its body rows to nodes
        # inside the GLB above. It arrives in the JSON part rather than as a fifth
        # file because the workspace needs it on every read of this build, and making
        # it an artifact would mean a second authorized fetch to draw the tree that
        # describes the first. None on an older engine image, which reads as "this
        # build has no tree" — not as an empty one.
        "scene_manifest": data.get("scene_manifest"),
    }


async def import_asset(
    name: str,
    data: bytes,
    formats: list[str] | tuple[str, ...] | None = None,
    timeout: float = 60.0,
    build_id: str | None = None,
) -> dict:
    """Send an uploaded STEP/STL/3MF/BREP file to the engine and get a build back.

    ``name`` is the file's own name: its extension is what decides which reader runs,
    and it is the only thing about the name the engine uses. ``data`` is the bytes,
    sent as the request body verbatim — no base64, no multipart. Base64 would inflate
    a 32 MB asset to 43 MB before a JSON parser ever saw it, and multipart would add a
    parser to the one container whose argument is that it has very few.

    The timeout is longer than :func:`execute`'s because the work is different in kind:
    a recipe builds from numbers, while an import hands OCCT a file somebody else wrote
    and asks it to make sense of it. The engine's own deadline is still the innermost
    one, so a file that will not parse is killed there, not waited out here.

    What comes back is :func:`execute`'s dict plus ``provenance`` — where the geometry
    came from, which reader parsed it, and whether it is exact. There is no
    ``recovered_features`` and there is no branch that could produce one: a STEP is a
    solved body, not the sketches that made it.
    """
    kind = import_kind_for(name)
    if kind is None:
        # A local refusal with the same code the engine would use, so the caller has
        # one code to handle whichever layer caught it. The engine re-checks, and its
        # answer is the one that decides — this only saves a round trip for the
        # obviously-wrong, and names the alternatives while it is at it.
        raise CadError(
            "import_unsupported_format",
            f"Harvis cannot import "
            f"{os.path.splitext(name)[1].lower() or 'that file'} — "
            f"supported: {', '.join('.' + k for k in KNOWN_IMPORT_KINDS)}",
        )
    if not data:
        raise CadError("import_empty", "the uploaded file is empty")
    if len(data) > MAX_IMPORT_BYTES:
        raise CadError("import_too_large",
                       f"the file is {len(data)} bytes, over the cap of {MAX_IMPORT_BYTES}")

    wanted = [f for f in (formats or ("stl", "glb")) if f in KNOWN_FORMATS]
    if not wanted:
        raise CadError("unknown_format", "no supported format was requested")

    build_id = build_id or uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{_cad_url()}/cad/v2/import",
                params={"name": os.path.basename(name)[:128],
                        "formats": ",".join(wanted),
                        "build_id": build_id},
                content=data,
                headers={"content-type": "application/octet-stream"},
            )
    except httpx.TimeoutException:
        log.warning("cad import %s outlived the client timeout of %.0fs", build_id, timeout)
        await cancel(build_id)
        raise CadError("engine_timeout",
                       f"the CAD engine did not answer within {timeout:.0f}s")
    except httpx.HTTPError:
        raise CadError("engine_unreachable", "the CAD engine could not be reached")

    result, files = _decode_build_response(r)

    return {
        "meta": result.get("meta", {}),
        "artifacts": files,
        "stl_bytes": files.get("stl", b""),
        "step_bytes": files.get("step"),
        "validation": result.get("validation") or {},
        "params": {},
        "artifact_refs": result.get("artifacts") or [],
        "build_id": result.get("build_id") or build_id,
        "source_kind": result.get("source_kind") or "import",
        "recipe": result.get("recipe") or os.path.splitext(os.path.basename(name))[0],
        # The engine's own block, passed through unedited. Empty would be a lie — an
        # import with no provenance is exactly the thing this gate exists to prevent —
        # so an absent one is left absent for the caller to notice.
        "provenance": result.get("provenance"),
        # An import gets a tree too, and a shallow one: bodies, no features. There is
        # no document behind an imported file, so there are no ordered operations to
        # list — which is the honest shape for a part whose history was never ours.
        "scene_manifest": result.get("scene_manifest"),
    }
