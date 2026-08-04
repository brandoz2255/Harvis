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

log = logging.getLogger(__name__)

# What this client will read off the wire in one response, independent of what the
# engine says it is sending. The engine caps itself at the same number; this one
# exists because a client that trusts a server's self-imposed limit has no limit.
MAX_RESPONSE_BYTES = 96 * 1024 * 1024

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

_TRUTHY = {"1", "true", "yes", "on"}


class CadError(RuntimeError):
    """A sidecar failure with the structured code it reported.

    Exists so the route layer can surface something repairable instead of the raw
    ``httpx.HTTPStatusError``, whose string form carries the internal sidecar URL
    into a user-facing 502.
    """

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

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
) -> dict:
    """Call the sidecar; return {meta, artifacts, stl_bytes, step_bytes|None, ...}.

    Raises :class:`CadError` on any failure, carrying the sidecar's structured code
    so the caller can tell "you asked for something impossible" apart from "the
    engine is down".

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
    if recipe not in KNOWN_RECIPES:
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
                    "recipe": recipe,
                    "params": params,
                    "formats": wanted,
                    "build_id": build_id,
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

    if r.status_code >= 400:
        code, message = "engine_error", "the CAD engine rejected the request"
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

    if len(r.content) > MAX_RESPONSE_BYTES:
        raise CadError("response_too_large",
                       f"the CAD engine sent {len(r.content)} bytes")

    data, files = _parse_multipart(r.headers.get("content-type", ""), r.content)
    _verify_artifacts(data, files)

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
    }
