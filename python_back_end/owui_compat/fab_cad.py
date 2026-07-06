"""Adaptive Workspace CAD client (Stage 2) — talks to the isolated build123d
sidecar (``cad-engine``) over the internal network.

The heavy OCP/OCCT kernel lives in its own container so its pins can't conflict
with the backend's torch/numpy stack. This module just: gates on an env flag,
maps the space's criteria (manifest.meta ``crit_*``) to recipe params, calls the
sidecar, and hands back the STL/STEP bytes + geometry metadata. No CAD runs here.
"""
from __future__ import annotations

import base64
import os

import httpx

RECIPE = "helmet_hanger_v1"
_TRUTHY = {"1", "true", "yes", "on"}

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
        return f if f > 0 else default
    except (TypeError, ValueError):
        return default


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
            lo, hi = _LIMITS[k]
            p[k] = max(lo, min(hi, fv))
    p["screw_count"] = max(0, min(6, int(p.get("screw_count", 2))))
    return p


async def execute(params: dict, want_step: bool = True, timeout: float = 30.0) -> dict:
    """Call the sidecar; return {meta, stl_bytes, step_bytes|None}. Raises on failure."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{_cad_url()}/cad/execute",
            json={"recipe": RECIPE, "params": params, "step": want_step},
        )
        r.raise_for_status()
        data = r.json()
    stl = base64.b64decode(data["stl_b64"]) if data.get("stl_b64") else b""
    step = base64.b64decode(data["step_b64"]) if data.get("step_b64") else None
    return {"meta": data.get("meta", {}), "stl_bytes": stl, "step_bytes": step}
