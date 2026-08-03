"""Adaptive Workspace CAD client (Stage 2) — talks to the isolated build123d
sidecar (``cad-engine``) over the internal network.

The heavy OCP/OCCT kernel lives in its own container so its pins can't conflict
with the backend's torch/numpy stack. This module just: gates on an env flag,
maps the space's criteria (manifest.meta ``crit_*``) to recipe params, calls the
sidecar, and hands back the STL/STEP bytes + geometry metadata. No CAD runs here.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import uuid

import httpx

log = logging.getLogger(__name__)

RECIPE = "helmet_hanger_v1"
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
) -> dict:
    """Call the sidecar; return {meta, stl_bytes, step_bytes|None}.

    Raises :class:`CadError` on any failure, carrying the sidecar's structured code
    so the caller can tell "you asked for something impossible" apart from "the
    engine is down".

    Three nested deadlines, innermost first: the sidecar kills the build's process
    group at ``CAD_BUILD_DEADLINE_S`` + grace (20 s + 3 s by default), this client
    gives up at ``timeout`` (30 s), and nginx gives up after that. Each layer must
    outlast the one it depends on — a client that gives up first learns nothing and
    leaves the work running.
    """
    _reject_non_finite(params)
    build_id = build_id or uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{_cad_url()}/cad/execute",
                json={
                    "recipe": RECIPE,
                    "params": params,
                    "step": want_step,
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

    data = r.json()
    stl = base64.b64decode(data["stl_b64"]) if data.get("stl_b64") else b""
    step = base64.b64decode(data["step_b64"]) if data.get("step_b64") else None
    return {
        "meta": data.get("meta", {}),
        "stl_bytes": stl,
        "step_bytes": step,
        # Additive since Gate 1A: the sidecar now reports B-Rep validity, solid count
        # and a watertight-mesh verdict instead of only bbox + volume.
        "validation": data.get("validation") or {},
        "params": data.get("params") or {},
    }
