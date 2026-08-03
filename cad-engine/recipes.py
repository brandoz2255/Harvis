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

import hashlib
import json
import math

from build123d import (
    BuildPart, Locations, Box, Cylinder, Axis, Mode, fillet,
)

import exporters

# Bumped when the meaning of a recipe's parameters changes, not when its geometry is
# refactored. It is mixed into :func:`canonical_source_hash`, so a bump invalidates
# every stored hash — which is the point: two builds that agree on the numbers but
# disagree on what the numbers mean are not the same build.
SCHEMA_VERSION = "0.1"


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
    # A generic interlocking studded building brick: a hollow rectangular shell with
    # a grid of studs on top and interlocking tubes underneath. Every dimension is a
    # parameter with a default chosen for this recipe, not copied from any
    # manufacturer's specification, and the recipe is named for what it is.
    "studded_brick_v1": {
        "studs_x":      ("int", 4, 1, 16),
        "studs_y":      ("int", 2, 1, 16),
        "pitch_mm":     ("float", 10, 4, 40),
        "body_h_mm":    ("float", 10, 3, 60),
        "wall_t_mm":    ("float", 1.6, 0.8, 6),
        "stud_d_mm":    ("float", 5, 1, 30),
        "stud_h_mm":    ("float", 2, 0.5, 10),
        "clearance_mm": ("float", 0.1, 0, 1),
    },
}

# How many disjoint solids a correct build of each recipe produces. Read by the
# server instead of the hardcoded 1 it used through Gate 1B: the count is a property
# of the recipe, and the moment a recipe legitimately returns two bodies, a
# hardcoded 1 turns a correct build into a 500.
RECIPE_SOLIDS = {
    "helmet_hanger_v1": 1,
    "studded_brick_v1": 1,
}

# Underside tube diameter as a fraction of the stud pitch. Not a parameter: it is
# fixed by the interlock geometry (the tube has to be gripped by four studs), and
# exposing it would let a caller ask for a tube that cannot touch any of them.
_TUBE_RATIO = 0.8

# Cost is expressed in default-hanger units: the stock part is 1.0 by construction.
#
# Measured in the pinned worker, not estimated: the worst request the bounds above
# permit scores 48.7 and builds in 0.040 s / 3332 triangles / 441 MiB peak, against
# 1.0 → 0.032 s / 1308 triangles / 429 MiB for the default. So for THIS recipe the
# per-parameter ranges already cap the work, and this gate can never fire — it is a
# backstop, and saying otherwise would be a safety claim the numbers don't support.
#
# It earns its place at Gate 2, where the studded brick's stud count multiplies
# boolean operations without any single parameter looking unreasonable.
MAX_COST = 150.0

# ...and Gate 2 also showed that one shared number cannot do the job, for the reason
# the comment above `_UNIT_AREA_MM2` already states: a cost of 1.0 means "as expensive
# as THIS recipe's default", so the same number buys wildly different amounts of work.
# The hanger's worst legal request scores 48.7 and builds in 0.040 s. The brick reaches
# 23.9 at 15.88 s and 31.2 at never — measured through the real HTTP path with each
# build pinned to its CPU slice:
#
#     grid    cost   solo wall   peak child RSS
#     10x10   12.2      7.30 s        663 MiB
#     12x12   17.6      8.60 s        831 MiB
#     14x14   23.9     15.88 s       1056 MiB
#     16x16   31.2   killed at the 20 s deadline, having produced nothing
#
# A single 150.0 admitted every one of those, including the one that cannot finish —
# and a cap that admits unfinishable work is not a cap. It burns a concurrency slot for
# the full 20 s and answers with a timeout, where the whole point is an immediate,
# honest refusal.
#
# 20.0 is the last brick value that keeps every admitted request finishable: it takes
# 12x12 (8.60 s solo; 10.8 s and 8.3 s for two at once, both inside the deadline) and
# refuses 14x14, whose 15.88 s leaves nothing for a loaded host. Memory is not what
# sets it — two concurrent 12x12 builds peaked the container at 1557 MiB against the
# 2 GiB limit, and `memory.events` has never once recorded an OOM (`max 0, oom 0`).
#
# A recipe absent from here falls back to MAX_COST, which stays the unreachable
# backstop it has always been for the hanger.
MAX_COST_BY_RECIPE = {
    "studded_brick_v1": 20.0,
}


def cost_cap(recipe: str) -> float:
    """The complexity ceiling for one recipe. Per-recipe because cost is normalized
    per-recipe; sharing one number across both would price the brick in hanger units."""
    return MAX_COST_BY_RECIPE.get(recipe, MAX_COST)


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


def _check_studded_brick_v1(p: dict) -> None:
    """Reject brick parameter *combinations* that no per-parameter range can catch.

    Each bound in :data:`PARAM_SPEC` is individually reasonable; several of them
    together are not. A 4 mm pitch with a 30 mm stud diameter passes every range check
    and asks OpenCascade to fuse 256 mutually-overlapping cylinders into a shell they
    are all larger than. That is the class of request Gate 0 measured the cost of, so
    it is refused here — cheaply, before a process is spawned — rather than left to
    the deadline.
    """
    nx, ny = p["studs_x"], p["studs_y"]
    pitch, body_h, wall = p["pitch_mm"], p["body_h_mm"], p["wall_t_mm"]
    stud_d, clr = p["stud_d_mm"], p["clearance_mm"]

    def bad(msg: str):
        raise ParamError("incompatible_params", msg)

    if stud_d + 2 * clr >= pitch:
        bad(f"stud_d_mm + 2×clearance_mm ({stud_d + 2 * clr:g}) must be less than "
            f"pitch_mm ({pitch:g}), or adjacent studs merge")
    if body_h <= wall + 1:
        bad(f"body_h_mm ({body_h:g}) must exceed wall_t_mm + 1 ({wall + 1:g}), "
            "or there is no cavity under the roof")
    if 2 * wall + 2 * clr + 1 >= pitch * min(nx, ny):
        bad(f"wall_t_mm ({wall:g}) is too thick for a {nx}×{ny} brick at "
            f"pitch_mm {pitch:g} — the walls would meet in the middle")
    if nx > 1 and ny > 1:
        # Tubes exist only on a grid; a 1×N brick has no interlock feature at all,
        # which is honest rather than a silent omission — it also has nothing to grip.
        if wall + clr >= 0.6 * pitch:
            bad(f"wall_t_mm + clearance_mm ({wall + clr:g}) leaves no room for the "
                f"interlock tubes at pitch_mm {pitch:g}")
        if _TUBE_RATIO * pitch - stud_d - 2 * clr < 0.8:
            bad(f"stud_d_mm ({stud_d:g}) is too large at pitch_mm {pitch:g}: the "
                "interlock tube wall would be under 0.8 mm")


_CROSS_CHECKS = {"studded_brick_v1": _check_studded_brick_v1}


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

    resolved = {name: _finite(recipe, name, params.get(name), s) for name, s in spec.items()}

    check = _CROSS_CHECKS.get(recipe)
    if check is not None:
        check(resolved)
    return resolved


def canonical_source_hash(recipe: str, resolved: dict) -> str:
    """SHA-256 over the normalized (schema version + recipe name + sorted parameters).

    This is the identity Gate 3's ``cad_revisions`` compares on, and it exists because
    the obvious alternative — hashing the exported bytes — was measured to be wrong.
    STEP embeds ``FILE_NAME(…,'2026-08-03T05:55:27',…)``, a wall-clock timestamp at
    one-second resolution, so two identical builds either side of a second boundary
    produce different files; 3MF is a ZIP and differed across two writes inside the
    same second. A byte-identity gate would have passed in CI and failed in production
    on a slow build.

    Hashing the *input* has the property we actually want: it answers "is this the same
    build?" without building anything, and it cannot drift with the exporter.
    """
    params = {}
    for name in sorted(resolved):
        v = resolved[name]
        if isinstance(v, float):
            # -0.0 and 0.0 are equal but serialise differently, and a clamp at a lower
            # bound of 0 can produce either.
            v = 0.0 if v == 0 else float(v)
        params[name] = v
    payload = json.dumps(
        {"schema_version": SCHEMA_VERSION, "recipe": recipe, "params": params},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hanger_area_mm2(p: dict) -> float:
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


def _brick_area_mm2(p: dict) -> float:
    """Same idea for the brick, and here the count terms carry the weight.

    The hanger's cost moves with its dimensions. The brick's moves with how many
    features it has: a 16×16 grid is 256 stud fusions and 225 tube pairs, and none of
    the individual parameters looks unreasonable while asking for them. Studs and
    tubes are therefore counted, not approximated by the shell they sit on.
    """
    nx, ny = p["studs_x"], p["studs_y"]
    pitch, body_h, wall = p["pitch_mm"], p["body_h_mm"], p["wall_t_mm"]
    stud_d, stud_h, clr = p["stud_d_mm"], p["stud_h_mm"], p["clearance_mm"]

    length = nx * pitch - 2 * clr
    width = ny * pitch - 2 * clr
    outer = 2 * length * width + 2 * body_h * (length + width)

    inner_l, inner_w = length - 2 * wall, width - 2 * wall
    inner_h = body_h - wall
    cavity = inner_l * inner_w + 2 * inner_h * (inner_l + inner_w)

    studs = nx * ny * (math.pi * stud_d * stud_h + math.pi * stud_d ** 2 / 4)

    tubes = 0.0
    if nx > 1 and ny > 1:
        bore_d = stud_d + 2 * clr
        tubes = (nx - 1) * (ny - 1) * math.pi * (_TUBE_RATIO * pitch + bore_d) * inner_h

    return outer + cavity + studs + tubes


_AREA_PROXY = {
    "helmet_hanger_v1": _hanger_area_mm2,
    "studded_brick_v1": _brick_area_mm2,
}


def _defaults(recipe: str) -> dict:
    return {name: spec[1] for name, spec in PARAM_SPEC[recipe].items()}


# The unit of cost: each recipe's own stock part, derived from the spec rather than
# pasted in as a constant, so changing a default can't silently rescale every stored
# estimate. Measured B-Rep area of the stock hanger is 9237.80 mm²; the proxy reads
# ~9782.8 because it ignores the boolean overlaps and the root fillet. Fine for a
# ratio — and note that a cost of 1.0 means "as expensive as this recipe's default",
# not "as expensive as a hanger". The cap is shared, the units are not.
_UNIT_AREA_MM2 = {r: _AREA_PROXY[r](_defaults(r)) for r in PARAM_SPEC}


def estimate_cost(recipe: str, resolved: dict) -> float:
    """Static complexity estimate, computed from already-validated parameters and
    charged BEFORE geometry starts. Cheap arithmetic only — if this needed to build
    anything to decide, it would not be admission control."""
    proxy = _AREA_PROXY.get(recipe)
    unit = _UNIT_AREA_MM2.get(recipe)
    if proxy and unit:
        return round(proxy(resolved) / unit, 3)
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


def studded_brick_v1(p: dict):
    """A generic interlocking studded building brick.

    A hollow rectangular shell, closed on top, with an ``studs_x × studs_y`` grid of
    cylindrical studs on the roof and a matching grid of hollow tubes underneath that
    grip the studs of the brick below. Centred on the origin; Z is up.

    Two geometry choices worth stating, because both were failure modes before they
    were choices:

    * The tubes are built ``wall_t/2`` **taller** than the cavity, so they interpenetrate
      the roof instead of meeting it face-to-face. A coplanar fuse is exactly where
      OCCT produces a technically-valid shape with a seam the mesher then tessellates
      into open edges — and :func:`validation.verdict` would reject that as
      not-watertight rather than let it through.
    * Tubes exist only when both counts exceed one. A 1×N brick has nothing to grip
      and gets no underside feature at all. That is a real limitation of this recipe,
      not an oversight: real bar-shaped bricks use a different interlock, and inventing
      one here would be geometry nobody has checked.

    Expects parameters already through :func:`resolve_params`, which is also where the
    combinations this function cannot survive are refused.
    """
    nx, ny = int(p["studs_x"]), int(p["studs_y"])
    pitch = p["pitch_mm"]
    body_h = p["body_h_mm"]
    wall = p["wall_t_mm"]
    stud_d = p["stud_d_mm"]
    stud_h = p["stud_h_mm"]
    clr = p["clearance_mm"]

    length = nx * pitch - 2 * clr
    width = ny * pitch - 2 * clr
    cavity_h = body_h - wall
    tube_d = _TUBE_RATIO * pitch
    bore_d = stud_d + 2 * clr

    with BuildPart() as bp:
        Box(length, width, body_h)
        # hollow the underside, leaving the four side walls and a roof of `wall`
        with Locations((0, 0, -wall / 2)):
            Box(length - 2 * wall, width - 2 * wall, cavity_h, mode=Mode.SUBTRACT)

        studs = [
            ((i - (nx - 1) / 2) * pitch, (j - (ny - 1) / 2) * pitch, body_h / 2 + stud_h / 2)
            for i in range(nx) for j in range(ny)
        ]
        with Locations(*studs):
            Cylinder(radius=stud_d / 2, height=stud_h)

        if nx > 1 and ny > 1:
            # tube centres sit on the diagonals between four studs
            mids = [
                ((i + 0.5 - (nx - 1) / 2) * pitch, (j + 0.5 - (ny - 1) / 2) * pitch, -wall / 4)
                for i in range(nx - 1) for j in range(ny - 1)
            ]
            with Locations(*mids):
                Cylinder(radius=tube_d / 2, height=cavity_h + wall / 2)
            # the bore is blind: it stops at the roof underside, which is an existing
            # face of the part, so the cut adds no new plane.
            with Locations(*[(x, y, -wall) for x, y, _z in mids]):
                Cylinder(radius=bore_d / 2, height=body_h, mode=Mode.SUBTRACT)

    return bp.part


RECIPES = {
    "helmet_hanger_v1": helmet_hanger_v1,
    "studded_brick_v1": studded_brick_v1,
}


def build(recipe: str, resolved: dict):
    """Run one vetted recipe against already-validated parameters."""
    fn = RECIPES.get(recipe)
    if fn is None:
        raise ParamError("unknown_recipe", f"unknown recipe: {recipe}")
    return fn(resolved)


def export(part, recipe: str, targets: dict[str, str], *, seed: str = "") -> tuple[dict, list[str]]:
    """Write the requested artifacts; return the frozen ``meta`` shape and the list of
    formats that actually landed.

    ``meta`` keeps exactly the four keys the backend already consumes — including
    ``step``, which stays a bare boolean rather than becoming a list, because
    ``/cad/execute`` is frozen and Gate 3 is where the response shape changes.

    A format that fails to write is dropped from the returned list rather than raising.
    STEP behaved this way before Gate 2 and the reason generalises: a GLB the viewer
    cannot have is a degraded result, not a failed build, and the caller learns which
    formats it got instead of being told the part does not exist. STL is the exception
    — it is the mesh every downstream check reads, so its failure is the build's.
    """
    written: list[str] = []
    for fmt, path in targets.items():
        if fmt == "stl":
            exporters.write(fmt, part, path, seed=seed)
            written.append(fmt)
            continue
        try:
            exporters.write(fmt, part, path, seed=seed)
            written.append(fmt)
        except Exception:
            pass

    bb = part.bounding_box()
    meta = {
        "recipe": recipe,
        "bbox_mm": [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
        "volume_mm3": round(part.volume, 1),
        "step": "step" in written,
    }
    return meta, written
