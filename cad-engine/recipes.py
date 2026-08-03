"""Vetted parametric CAD recipes for the Adaptive Workspace fabrication lane.
No arbitrary code execution — only NAMED recipe functions run, each taking a
plain params dict. build123d produces a real BREP solid (exact geometry, fillets,
STEP-capable), not a mesh approximation.

Gate 1A adds a declared parameter spec per recipe. Every value is checked for
finiteness and range BEFORE any geometry runs, because ``min``/``max`` propagate
NaN silently: ``max(nan, 10)`` is ``nan`` and ``min(nan, 500)`` is ``nan``, so the
old clamps handed a NaN straight to OpenCascade. Measured cost of that: the worker
burned 1-2 cores for 46 s and, because OCP holds the GIL through the native call,
every other request — ``/health`` included — was starved for 43 s of it. One
malformed request was enough. See docs/plans/2026-08-03-local-cad-baseline.md.

This layer never trusts the HTTP schema in front of it. If a non-finite value
reaches ``_finite`` it means the schema was bypassed, and we raise rather than
clamp.
"""
from __future__ import annotations

import math

from build123d import (
    BuildPart, Locations, Box, Cylinder, Axis, Mode, fillet, export_stl, export_step,
)


class ParamError(ValueError):
    """A parameter the caller can fix. Carries a structured code so the HTTP layer
    can answer with something repairable instead of a stack trace."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BudgetError(ValueError):
    """Admission control refused the request before geometry started."""

    def __init__(self, message: str, cost: float, cap: float):
        super().__init__(message)
        self.message = message
        self.cost = cost
        self.cap = cap


# name -> (kind, default, lo, hi). This is the whole public surface of a recipe:
# anything not listed here is rejected rather than ignored, so a typo'd parameter
# stops silently producing the default part.
PARAM_SPEC: dict[str, dict[str, tuple[str, float, float, float]]] = {
    "helmet_hanger_v1": {
        "plate_t_mm":  ("float", 6, 1, 40),
        "plate_w_mm":  ("float", 40, 5, 300),
        "plate_h_mm":  ("float", 44, 5, 300),
        "arm_len_mm":  ("float", 100, 10, 500),
        "arm_w_mm":    ("float", 12, 2, 80),
        "arm_h_mm":    ("float", 8, 2, 80),
        "hook_h_mm":   ("float", 18, 2, 150),
        "fillet_r_mm": ("float", 3, 0, 20),
        "screw_d_mm":  ("float", 4, 1, 20),
        "screw_count": ("int", 2, 0, 6),
    },
}

# Cost is expressed in default-hanger units: the stock part is 1.0 by construction.
#
# Measured in the pinned worker, not estimated: the worst request the bounds above
# permit scores 48.7 and builds in 0.040 s / 3332 triangles / 441 MiB peak, against
# 1.0 → 0.032 s / 1308 triangles / 429 MiB for the default. So for THIS recipe the
# per-parameter ranges already cap the work, and this gate can never fire — it is a
# backstop, and saying otherwise would be a safety claim the numbers don't support.
#
# It earns its place at Gate 2, where the studded brick's stud count multiplies
# boolean operations without any single parameter looking unreasonable. Recalibrate
# the cap there against measured builds.
MAX_COST = 150.0


def _finite(recipe: str, name: str, value, spec: tuple[str, float, float, float]) -> float | int:
    """Validate one parameter. Rejects non-finite and out-of-range values, then
    clamps anyway — the clamp is a no-op for admitted input and the last line of
    defence if this function is ever reached by another path."""
    kind, default, lo, hi = spec
    if value is None:
        value = default

    # bool is a subclass of int; accepting it would let `true` mean 1 mm.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParamError(
            "invalid_param",
            f"{name} must be a number, got {type(value).__name__}",
        )

    f = float(value)
    if not math.isfinite(f):
        raise ParamError(
            "invalid_param",
            f"{name} must be a finite number (NaN and Infinity are rejected)",
        )
    if f < lo or f > hi:
        raise ParamError(
            "param_out_of_range",
            f"{name} must be between {lo} and {hi} (got {f})",
        )

    if kind == "int":
        i = int(f)
        if i != f:
            raise ParamError("invalid_param", f"{name} must be a whole number (got {f})")
        return max(int(lo), min(int(hi), i))
    return min(max(f, lo), hi)


def resolve_params(recipe: str, params: dict | None) -> dict:
    """Validated, defaulted, in-range parameters for a recipe. Unknown names are an
    error, not a shrug: silently ignoring them meant a caller could ask for
    ``arm_length_mm`` and get the default part back with a cheerful 200."""
    spec = PARAM_SPEC.get(recipe)
    if spec is None:
        raise ParamError("unknown_recipe", f"unknown recipe: {recipe}")
    params = params or {}

    unknown = sorted(set(params) - set(spec))
    if unknown:
        raise ParamError(
            "unknown_param",
            f"unknown parameter(s) for {recipe}: {', '.join(unknown[:8])}",
        )

    return {name: _finite(recipe, name, params.get(name), s) for name, s in spec.items()}


def _area_proxy_mm2(p: dict) -> float:
    """Summed face area of the recipe's primitives — the quantity that actually
    drives tessellation, and therefore triangle count, artifact size and time.

    Bounding volume was the obvious first choice and it is wrong: scaling the
    hanger to every upper bound multiplies volume by 385 while build time moves
    0.032 s → 0.040 s. Area moves by 49, and triangle count by 2.5.
    """
    t, w, h = p["plate_t_mm"], p["plate_w_mm"], p["plate_h_mm"]
    al, aw, ah = p["arm_len_mm"], p["arm_w_mm"], p["arm_h_mm"]
    hook = p["hook_h_mm"]
    plate = 2 * w * h + 2 * t * (w + h)
    arm = 2 * al * aw + 2 * ah * (al + aw)
    lip = 2 * ah * aw + 2 * hook * (ah + aw)
    # each screw hole is a boolean cut whose wall is the tessellated surface
    screws = p["screw_count"] * math.pi * p["screw_d_mm"] * t
    return plate + arm + lip + screws


def _defaults(recipe: str) -> dict:
    return {name: spec[1] for name, spec in PARAM_SPEC[recipe].items()}


# The unit of cost: the stock hanger, derived from the spec rather than pasted in as
# a constant, so changing a default can't silently rescale every stored estimate.
# Measured B-Rep area of that part is 9237.80 mm²; the proxy reads ~9782.8 because it
# ignores the boolean overlaps and the root fillet. Fine for a ratio.
_UNIT_AREA_MM2 = {r: _area_proxy_mm2(_defaults(r)) for r in PARAM_SPEC}


def estimate_cost(recipe: str, resolved: dict) -> float:
    """Static complexity estimate, computed from already-validated parameters and
    charged BEFORE geometry starts. Cheap arithmetic only — if this needed to build
    anything to decide, it would not be admission control."""
    unit = _UNIT_AREA_MM2.get(recipe)
    if unit:
        return round(_area_proxy_mm2(resolved) / unit, 3)
    return 1.0


def helmet_hanger_v1(p: dict):
    """Wall-mounted hanger: back plate + cantilever arm + upturned hook + screw
    holes. Parametric on plate/arm/hook dims and screw count. X = outward from the
    wall, Z = up, Y = width. The wall joint (cantilever root) is at x=plate_t.

    Expects parameters already through :func:`resolve_params`."""
    plate_t = p["plate_t_mm"]
    plate_w = p["plate_w_mm"]
    plate_h = p["plate_h_mm"]
    arm_len = p["arm_len_mm"]
    arm_w = p["arm_w_mm"]
    arm_h = p["arm_h_mm"]
    hook_h = p["hook_h_mm"]
    fillet_r = p["fillet_r_mm"]
    screw_d = p["screw_d_mm"]
    screw_count = p["screw_count"]

    with BuildPart() as bp:
        with Locations((plate_t / 2, 0, 0)):
            Box(plate_t, plate_w, plate_h)
        # cantilever arm outward at z=0
        with Locations((plate_t + arm_len / 2, 0, 0)):
            Box(arm_len, arm_w, arm_h)
        # upturned hook lip at the tip (the helmet strap loops over it)
        with Locations((plate_t + arm_len - arm_h / 2, 0, hook_h / 2 + arm_h / 2)):
            Box(arm_h, arm_w, hook_h)
        # mounting screw holes through the plate (vertical line)
        if screw_count >= 1:
            zs = [(-plate_h / 2 + plate_h * (i + 1) / (screw_count + 1)) for i in range(screw_count)]
            with Locations(*[(plate_t / 2, 0, z) for z in zs]):
                Cylinder(radius=max(0.5, screw_d / 2), height=plate_t * 3, rotation=(0, 90, 0), mode=Mode.SUBTRACT)

    part = bp.part
    # fillet the arm/plate root joint (the highest-stress region) — robust
    try:
        root = part.edges().filter_by(Axis.Y).sort_by(Axis.X)
        r = max(0.5, min(fillet_r, arm_h / 2 - 0.5))
        part = fillet(root[:2], radius=r)
    except Exception:
        pass
    return part


RECIPES = {"helmet_hanger_v1": helmet_hanger_v1}


def build(recipe: str, resolved: dict):
    """Run one vetted recipe against already-validated parameters."""
    fn = RECIPES.get(recipe)
    if fn is None:
        raise ParamError("unknown_recipe", f"unknown recipe: {recipe}")
    return fn(resolved)


def export(part, recipe: str, stl_path: str, step_path: str | None = None) -> dict:
    """Write the artifacts and return the frozen ``meta`` shape. Kept byte-for-byte
    compatible with what the backend already consumes — Gate 3 adds a v2 endpoint
    rather than changing this."""
    export_stl(part, stl_path)
    if step_path:
        try:
            export_step(part, step_path)
        except Exception:
            step_path = None
    bb = part.bounding_box()
    return {
        "recipe": recipe,
        "bbox_mm": [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
        "volume_mm3": round(part.volume, 1),
        "step": bool(step_path),
    }


def run(recipe: str, params: dict, stl_path: str, step_path: str | None = None) -> dict:
    """Validate -> build -> export in one call. Retained for callers that do not need
    the intermediate part; the server uses the three steps separately so it can run
    admission control and validation between them."""
    resolved = resolve_params(recipe, params)
    return export(build(recipe, resolved), recipe, stl_path, step_path)
