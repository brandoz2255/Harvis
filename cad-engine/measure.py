"""Targeted geometry measurements (HE-2).

Every function here answers one question about one named feature, and every one of them
replaced a proxy that would have answered a *different* question convincingly:

* clearance is **not** the minimum distance between two bodies. A correctly seated lid
  touches the rim, so that distance is 0 for a perfect fit and the check would report an
  interference. It is the difference between two fitted mating radii on a shared axis.
* concentricity is **not** centroid alignment. A lid tilted 2 degrees about a shared
  centre has the same centroid and is not concentric. It is an axis offset **and** an
  angular deviation, both reported, both required to pass.
* wall thickness is **not** the smallest gap between non-adjacent faces. That finds the
  narrowest place anywhere in the body, usually straight across the bore. It is one
  radius minus another at a named interface.
* cavity depth is **not** hull subtraction. It is the distance from the opening plane to
  the cavity floor along the part's own fitted axis.
* body height is **not** the assembly bounding box. A 100 mm jar under a 20 mm lid still
  measures 115 mm, so an assembly-box check passes exactly the part it should fail.

**Nothing here is allowed to invent a number.** A measurement whose target does not
resolve returns ``value: None`` with the resolver's reason. It never returns 0, because 0
is a legitimate reading for most of these kinds and the difference between "zero" and "we
could not tell" is the whole difference between a verdict and a guess.

**There is no deadline in this module.** A Python timeout cannot interrupt an in-progress
native OpenCascade call — this repo established that in Gate 1B, and :mod:`runner` kills
the whole process group instead. Measurement runs inside that same killable child and
shares its deadline. Anything unmeasured when the group dies is reported
``measurement_incomplete`` by the parent and grades ``unverified``, never a partial fail.
"""
from __future__ import annotations

import math
import traceback

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopTools import TopTools_ListOfShape

import measure_spec
import targets

METHOD_VERSION = "1"


def _record(req, *, value, unit, basis=None, resolution=None, method=None,
            error_bound=0.0, diagnostic=None, extra=None) -> dict:
    """One :class:`Measurement`, in the shape HE-3 persists and HE-5 grades.

    ``value: None`` and a resolution that did not resolve travel together — a caller
    reading only the value still cannot mistake "unmeasured" for a reading, because the
    value is absent rather than zero.
    """
    spec = measure_spec.KINDS[req.kind]
    out = {
        "measurement_id": req.measurement_id,
        "kind": req.kind,
        "target": _target_of(req),
        "resolution": (resolution or targets.Resolution(True, 1, method or spec["method"])).as_dict(),
        "value": None if value is None else round(float(value), 6),
        "unit": unit or spec["unit"],
        "basis": basis if basis is not None else spec["basis"],
        "method": method or spec["method"],
        "method_version": METHOD_VERSION,
        "numeric_error_bound": round(float(error_bound), 9),
        "diagnostic": diagnostic or {},
    }
    if extra:
        out.update(extra)
    return out


def _target_of(req) -> dict:
    shape = measure_spec.KINDS[req.kind]["pair"]
    if shape == "part_axis":
        return {"part_key": req.part_key, "axis": req.axis}
    if shape == "none":
        return {}
    return {"a": req.a, "b": req.b}


def _unresolved(req, reason: str, method: str | None = None, candidates: int = 0) -> dict:
    spec = measure_spec.KINDS[req.kind]
    res = targets.Resolution(False, candidates, method or spec["method"], reason)
    return _record(req, value=None, unit=spec["unit"], resolution=res, method=method)


# --- lookups ---------------------------------------------------------------------

def _part(by_key, part_key, req, role_hint=""):
    pg = by_key.get(part_key)
    if pg is None:
        return None, _unresolved(
            req, f"no body is keyed {part_key!r} in this build"
                 + (f" (needed for {role_hint})" if role_hint else ""))
    return pg, None


def _face(by_key, ref, req):
    pg, miss = _part(by_key, ref.get("part_key"), req, ref.get("face_role", ""))
    if miss is not None:
        return None, None, miss
    face, res = pg.face(ref["face_role"])
    if face is None:
        return None, None, _record(req, value=None, unit=measure_spec.KINDS[req.kind]["unit"],
                                   resolution=res)
    return pg, face, None


# --- the kinds -------------------------------------------------------------------

def _radius_difference(by_key, req) -> dict:
    """``outer.radius - inner.radius`` on a shared axis. Serves both wall thickness
    (inside one body) and mating clearance (between two), because the arithmetic is the
    same and only the meaning differs.

    Order is the caller's: ``a`` is the surface at the larger radius. Getting it backwards
    yields a negative number rather than an absolute one, which is the honest answer — a
    negative clearance *is* an interference, and hiding the sign would hide the defect.
    """
    pg_a, face_a, miss = _face(by_key, req.a, req)
    if miss is not None:
        return miss
    pg_b, face_b, miss = _face(by_key, req.b, req)
    if miss is not None:
        return miss

    # Two radii only subtract meaningfully when they are radii about the same line. For a
    # clearance across two bodies this is the check that catches a lid measured against a
    # jar it is not even coaxial with — which would otherwise report a perfectly healthy
    # gap for a part that does not fit.
    angle = _axis_angle(face_a.direction, face_b.direction)
    offset = targets._point_to_line(face_b.origin, face_a.origin, face_a.direction)
    coaxial_tol = max(face_a.tolerance, face_b.tolerance) * 10 + 1e-6
    diagnostic = {
        "outer_radius_mm": round(face_a.radius, 6),
        "inner_radius_mm": round(face_b.radius, 6),
        "axis_angle_deg": round(angle, 9),
        "axis_offset_mm": round(offset, 9),
        "outer_part": pg_a.key,
        "inner_part": pg_b.key,
    }
    if angle > 1e-6 or offset > coaxial_tol:
        # Deliberately unverified rather than failed. The parts may well interfere, but
        # *this* measurement is not the one that proves it — axis_offset and
        # angular_deviation are, and they are separate checks with their own tolerances.
        return _record(
            req, value=None, unit="mm",
            resolution=targets.Resolution(
                False, 2, "coaxial_radius_difference",
                "the two cylinders are not on a shared axis, so the difference "
                "between their radii is not a distance through anything"),
            diagnostic=diagnostic)

    value = face_a.radius - face_b.radius
    bound = face_a.tolerance + face_b.tolerance
    # Stated in ordinary speech a fit clearance is usually diametral, and the two differ
    # by a factor of two. Reporting both is what stops a 0.3 mm spec from being silently
    # read as 0.15. A *thickness* has no diametral reading — doubling a 2.5 mm wall gives
    # 5.0 mm of nothing — so the second number appears only where it means something.
    extra = ({"diametral_mm": round(value * 2, 6)}
             if req.kind == "radial_clearance" else None)
    return _record(req, value=value, unit="mm", basis="radial",
                   error_bound=bound, diagnostic=diagnostic, extra=extra)


def _plane_gap(by_key, req) -> dict:
    """Signed distance between two planes, measured along the part's fitted axis.

    Along the *axis*, not along the plane normals: OCCT hands back whichever normal sense
    the surface was constructed with, so normal-relative distance flips sign for reasons
    that have nothing to do with the design.
    """
    pg_a, face_a, miss = _face(by_key, req.a, req)
    if miss is not None:
        return miss
    pg_b, face_b, miss = _face(by_key, req.b, req)
    if miss is not None:
        return miss
    if pg_a.key != pg_b.key:
        return _unresolved(req, "a plane gap is measured within one body; these two "
                                f"planes are on {pg_a.key} and {pg_b.key}",
                           method="axial_plane_distance")
    value = abs(face_a.axial - face_b.axial)
    return _record(req, value=value, unit="mm",
                   error_bound=face_a.tolerance + face_b.tolerance,
                   diagnostic={"a_axial_mm": round(face_a.axial, 6),
                               "b_axial_mm": round(face_b.axial, 6),
                               "part_key": pg_a.key})


def _part_extent(by_key, req) -> dict:
    pg, miss = _part(by_key, req.part_key, req)
    if miss is not None:
        return miss
    value = targets.part_extent(pg, req.axis)
    if value is None:
        return _unresolved(req, f"{pg.key} has no bounding box to measure",
                           method="part_bounding_extent")
    bound = max((f.tolerance for f in pg.faces), default=1e-7) * 2
    return _record(req, value=value, unit="mm", error_bound=bound,
                   diagnostic={"part_key": pg.key, "axis": req.axis})


def _axis_angle(a, b) -> float:
    """Degrees between two axes, direction-agnostic.

    An axis has no sense — OCCT returned a lid tilted 2 degrees as an axis pointing
    *down*, and a signed comparison reads that as 178 degrees of deviation. Taking the
    absolute dot product is what makes a 2 degree tilt read as 2 degrees.
    """
    dot = abs(targets._dot(a, b)) / (targets._norm(a) * targets._norm(b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _axis_pair(by_key, req):
    pg_a, miss = _part(by_key, (req.a or {}).get("part_key"), req)
    if miss is not None:
        return None, None, miss
    pg_b, miss = _part(by_key, (req.b or {}).get("part_key"), req)
    if miss is not None:
        return None, None, miss
    for pg in (pg_a, pg_b):
        if not pg.axis_resolution.resolved:
            return None, None, _record(req, value=None,
                                       unit=measure_spec.KINDS[req.kind]["unit"],
                                       resolution=pg.axis_resolution)
    return pg_a, pg_b, None


def _axis_offset(by_key, req) -> dict:
    """Perpendicular distance between two fitted axes.

    Half of concentricity. On its own it passes a lid that is perfectly centred and
    tipped over, which is why :func:`_angular_deviation` is a separate measurement with
    its own tolerance rather than a component folded into this one.
    """
    pg_a, pg_b, miss = _axis_pair(by_key, req)
    if miss is not None:
        return miss
    d = targets._cross(pg_a.axis_direction, pg_b.axis_direction)
    between = targets._sub(pg_b.axis_origin, pg_a.axis_origin)
    if targets._norm(d) <= 1e-9:
        # Parallel: the distance from either origin to the other line is the offset.
        value = targets._point_to_line(pg_b.axis_origin, pg_a.axis_origin,
                                       pg_a.axis_direction)
    else:
        # Skew: the common perpendicular. Not simply the distance between origins, which
        # depends on where each surface happened to be constructed.
        value = abs(targets._dot(between, d)) / targets._norm(d)
    bound = max(max((f.tolerance for f in pg.faces), default=1e-7)
                for pg in (pg_a, pg_b)) * 2
    return _record(req, value=value, unit="mm", error_bound=bound,
                   diagnostic={"a_part": pg_a.key, "b_part": pg_b.key,
                               "parallel": targets._norm(d) <= 1e-9})


def _angular_deviation(by_key, req) -> dict:
    pg_a, pg_b, miss = _axis_pair(by_key, req)
    if miss is not None:
        return miss
    value = _axis_angle(pg_a.axis_direction, pg_b.axis_direction)
    # An angle is only as certain as the surface it was fitted to over the length it was
    # fitted across. A 0.1 micron face tolerance on a 8 mm skirt is worth ~7e-4 degrees.
    span = max(_axial_span(pg_a), _axial_span(pg_b), 1e-6)
    tol = max(max((f.tolerance for f in pg.faces), default=1e-7)
              for pg in (pg_a, pg_b))
    bound = math.degrees(math.atan2(tol, span))
    return _record(req, value=value, unit="deg", error_bound=bound,
                   diagnostic={"a_part": pg_a.key, "b_part": pg_b.key,
                               "fit_span_mm": round(span, 6)})


def _axial_span(pg) -> float:
    axials = [f.axial for f in pg.faces if f.axial is not None]
    return (max(axials) - min(axials)) if len(axials) > 1 else 0.0


def _interference_volume(by_key, req) -> dict:
    """How much material two bodies claim at the same time.

    Three deliberate details. ``SetFuzzyValue`` first, because two faces that touch
    exactly produce numerical slivers without it. ``IsDone()`` and a non-null shape as the
    status check, because ``BRepAlgoAPI_Common`` has **no** ``HasErrors`` in the pinned
    OCP 7.8.1.1 — probed, the whole status surface is Check / CheckInverted / FuzzyValue /
    IsDone / SetCheckInverted / SetFuzzyValue. And the result is a volume compared against
    a stated tolerance upstream, never against a literal 0.0: a curved non-axis-aligned
    pair returns noise, not a clean zero.
    """
    pg_a, miss = _part(by_key, (req.a or {}).get("part_key"), req)
    if miss is not None:
        return miss
    pg_b, miss = _part(by_key, (req.b or {}).get("part_key"), req)
    if miss is not None:
        return miss
    if pg_a.key == pg_b.key:
        return _unresolved(req, "a body cannot interfere with itself",
                           method="fuzzy_boolean_common")

    args = TopTools_ListOfShape()
    args.Append(pg_a.shape)
    tools = TopTools_ListOfShape()
    tools.Append(pg_b.shape)
    op = BRepAlgoAPI_Common()
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetFuzzyValue(req.fuzzy_mm)
    try:
        op.Build()
    except Exception:
        traceback.print_exc()
        return _unresolved(req, "the intersection boolean did not complete",
                           method="fuzzy_boolean_common")
    if not op.IsDone():
        return _unresolved(req, "the intersection boolean did not complete",
                           method="fuzzy_boolean_common")
    shape = op.Shape()
    if shape.IsNull():
        return _unresolved(req, "the intersection boolean produced no shape",
                           method="fuzzy_boolean_common")

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    value = max(0.0, float(props.Mass()))

    # An upper bound on the sliver a fuzzy-tolerance mismatch can manufacture: the
    # tolerance, spread over the smaller body's whole surface. Real interference on this
    # part is thousands of times larger; boolean noise is far smaller.
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(pg_a.shape, area)
    a_area = float(area.Mass())
    BRepGProp.SurfaceProperties_s(pg_b.shape, area)
    bound = req.fuzzy_mm * min(a_area, float(area.Mass()))

    return _record(req, value=value, unit="mm3", error_bound=bound,
                   diagnostic={"a_part": pg_a.key, "b_part": pg_b.key,
                               "fuzzy_mm": req.fuzzy_mm})


def _part_count(by_key, req) -> dict:
    return _record(req, value=len(by_key), unit="count",
                   diagnostic={"part_keys": sorted(by_key)})


_HANDLERS = {
    "local_thickness": _radius_difference,
    "radial_clearance": _radius_difference,
    "plane_gap": _plane_gap,
    "part_extent": _part_extent,
    "axis_offset": _axis_offset,
    "angular_deviation": _angular_deviation,
    "interference_volume": _interference_volume,
    "part_count": _part_count,
}


def run(part, requests, *, source_hash: str = "") -> list[dict]:
    """Take every requested measurement on one built part.

    One handler exception does not lose the others. A crash inside OCCT on a pathological
    body is exactly the case where the remaining measurements are still worth having, and
    the failed one says so in its own record rather than in a log the user never sees.
    """
    if not requests:
        return []
    by_key = {pg.key: pg for pg in targets.parts_of(part)}
    out = []
    for req in requests:
        try:
            record = _HANDLERS[req.kind](by_key, req)
        except Exception as e:
            traceback.print_exc()
            record = _unresolved(req, f"the measurement failed ({type(e).__name__})")
        if source_hash:
            # The source this number was taken from. HE-3 refuses to display a
            # measurement whose hash does not match the revision it is shown under, the
            # same binding discipline `save_render` already enforces on images.
            record["source_hash"] = source_hash
        out.append(record)
    return out
