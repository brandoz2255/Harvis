"""Vetted parametric CAD recipes for the Adaptive Workspace fabrication lane.
No arbitrary code execution — only NAMED recipe functions run, each taking a
plain params dict. build123d produces a real BREP solid (exact geometry, fillets,
STEP-capable), not a mesh approximation."""
from __future__ import annotations
from build123d import (
    BuildPart, Locations, Box, Cylinder, Axis, Mode, fillet, export_stl, export_step,
)


def _f(p, k, d):
    try:
        return float(p.get(k, d))
    except (TypeError, ValueError):
        return float(d)


def helmet_hanger_v1(p: dict):
    """Wall-mounted hanger: back plate + cantilever arm + upturned hook + screw
    holes. Parametric on plate/arm/hook dims and screw count. X = outward from the
    wall, Z = up, Y = width. The wall joint (cantilever root) is at x=plate_t."""
    plate_t = _f(p, "plate_t_mm", 6)
    plate_w = _f(p, "plate_w_mm", 40)
    plate_h = _f(p, "plate_h_mm", 44)
    arm_len = _f(p, "arm_len_mm", 100)
    arm_w = _f(p, "arm_w_mm", 12)
    arm_h = _f(p, "arm_h_mm", 8)
    hook_h = _f(p, "hook_h_mm", 18)
    fillet_r = _f(p, "fillet_r_mm", 3)
    screw_d = _f(p, "screw_d_mm", 4)
    try:
        screw_count = int(p.get("screw_count", 2) or 0)
    except (TypeError, ValueError):
        screw_count = 2
    # Clamp at the boundary that actually runs the geometry: each screw is an OCP
    # boolean cut, so an unclamped count is unbounded compute (DoS). We never trust
    # the caller's clamp alone. Dimensions are bounded to sane ranges too.
    screw_count = max(0, min(6, screw_count))
    plate_t = min(max(plate_t, 1), 40)
    plate_w = min(max(plate_w, 5), 300)
    plate_h = min(max(plate_h, 5), 300)
    arm_len = min(max(arm_len, 10), 500)
    arm_w = min(max(arm_w, 2), 80)
    arm_h = min(max(arm_h, 2), 80)
    hook_h = min(max(hook_h, 2), 150)

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


def run(recipe: str, params: dict, stl_path: str, step_path: str | None = None) -> dict:
    fn = RECIPES.get(recipe)
    if fn is None:
        raise ValueError(f"unknown recipe: {recipe}")
    part = fn(params or {})
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
