"""Semantic targets: which body, which face, which axis (HE-1).

Every measurement in HE-2 has to name what it measured, and a positional solid index
cannot do that. OCCT does not promise solid ordering across a boolean, and "solids[1]"
was never able to say *the lid* or *the neck bore* in the first place. A number bound to
the wrong feature is worse than no number, because it grades ``failed`` with confidence.

So this module resolves two kinds of handle:

* **bodies**, by reusing the identity the build already assigns — :func:`manifest.part_key`
  on :func:`manifest.bodies_of` order. No second identity system, and the key a
  measurement reports is the same key the scene manifest, the GLB pick key and the
  explorer row already use.
* **faces**, by *classifying the geometry itself*. Exact OpenCascade surface
  introspection: a cylindrical face reports its fitted axis and radius, a planar face its
  plane and normal, and both report their true area. Nothing here is author-named or
  model-named, so "Whole bodies only" stays true in the UI — the roles below are
  server-derived and never cross into selection.

**Resolution is total and deterministic.** Every rule returns a
:class:`Resolution` saying whether it resolved, how many candidates it looked at, and,
when it did not, why. Zero candidates and two indistinguishable candidates both fail the
same way. An unresolved target grades ``unverified`` upstream — never ``failed`` — which
is the same rule the conformance grader already applies to check kinds it does not know.

**Face orientation is what separates a bore from an outer wall.** A cylindrical surface's
geometric normal points away from its axis; a face whose orientation is ``REVERSED`` has
been flipped, so its material side is outward and the face bounds a hole. That is exact
and survives the boolean that produced it, unlike anything derived from the builder.
"""
from __future__ import annotations

import math

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import (GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane,
                         GeomAbs_Sphere, GeomAbs_SurfaceOfRevolution, GeomAbs_Torus)
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

import manifest

METHOD_VERSION = "1"

FACE_ROLES = (
    "outer_cylinder",
    "bore_cylinder",
    "opening_plane",
    "cavity_floor",
    "base_underside",
)

# Two coaxial cylindrical faces at the same radius are one feature the topology happened
# to split (a seam, a groove, a boolean edge). Merging them below this keeps a split
# bore from reading as two competing candidates.
RADIUS_MERGE_MM = 1e-6

# ...and two candidates that survive merging but differ by less than this are not
# distinguishable by "largest" or "smallest". Picking one would be a coin flip dressed as
# a rule, so the target goes unresolved instead. A real counterbore differs by far more.
AMBIGUITY_RADIUS_MM = 1e-3

# How far a face's axis may lie from the part's primary axis and still be called coaxial.
# Faces built by the same document are exactly coaxial; this is float noise headroom, not
# a design tolerance.
AXIS_ANGLE_TOL = 1e-7          # radians between unit directions
AXIS_OFFSET_TOL_MM = 1e-6

# A plane counts as perpendicular to the primary axis when its normal is parallel to it.
PLANE_NORMAL_TOL = 1e-7

# Areas are compared against closed-form discs and annuli. This is a *relative* bound: an
# exact disc matches to machine precision, and a face carrying a fillet or a notch does
# not, which is the distinction the roles depend on.
AREA_REL_TOL = 1e-3

# Two planes closer together than this along the axis are the same extreme.
AXIAL_MERGE_MM = 1e-6


class Resolution:
    """Why a target did or did not bind. Carried on every measurement, so a number the
    grader refuses to trust says so in the same record as the number."""

    __slots__ = ("resolved", "candidates_considered", "method", "method_version", "reason")

    def __init__(self, resolved: bool, candidates: int, method: str,
                 reason: str | None = None):
        self.resolved = resolved
        self.candidates_considered = candidates
        self.method = method
        self.method_version = METHOD_VERSION
        self.reason = reason

    def as_dict(self) -> dict:
        return {
            "resolved": self.resolved,
            "candidates_considered": self.candidates_considered,
            "method": self.method,
            "method_version": self.method_version,
            "reason": self.reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Resolution {self.method} resolved={self.resolved} reason={self.reason}>"


class Face:
    """One classified face. ``kind`` is ``"cylinder"`` or ``"plane"``; everything else is
    exact geometry read off the surface, never inferred from the operation that made it."""

    __slots__ = ("kind", "radius", "origin", "direction", "area", "outward",
                 "tolerance", "axial")

    def __init__(self, kind, *, radius, origin, direction, area, outward, tolerance,
                 axial=None):
        self.kind = kind
        self.radius = radius
        self.origin = origin          # (x, y, z) a point on the axis / in the plane
        self.direction = direction    # unit (x, y, z): cylinder axis, or plane normal
        self.area = area
        self.outward = outward        # material is on the inside of this surface
        self.tolerance = tolerance    # BRep_Tool.Tolerance — the numerical error bound
        self.axial = axial            # signed position along the part's primary axis

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "radius_mm": None if self.radius is None else round(self.radius, 6),
            "origin_mm": [round(v, 6) for v in self.origin],
            "direction": [round(v, 9) for v in self.direction],
            "area_mm2": round(self.area, 6),
            "outward": self.outward,
            "tolerance_mm": round(self.tolerance, 9),
            "axial_mm": None if self.axial is None else round(self.axial, 6),
        }


# --- vector helpers -------------------------------------------------------------
# Three-tuples rather than gp_Vec, because these numbers cross into JSON and a value the
# result carries should be the same object the rule compared.

def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _parallel(a, b, tol=AXIS_ANGLE_TOL) -> bool:
    """Direction-agnostic: an axis pointing +z and one pointing -z are the same axis."""
    return _norm(_cross(a, b)) <= tol


def _point_to_line(point, origin, direction) -> float:
    d = _sub(point, origin)
    return _norm(_cross(d, direction))


# --- face classification --------------------------------------------------------

def _faces(shape):
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        # Current() hands back a TopoDS_Shape; every face API below needs the cast, and
        # skipping it fails at call time rather than here.
        yield TopoDS.Face_s(exp.Current())
        exp.Next()


def _area(face) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return float(props.Mass())


def classify_faces(shape) -> list[Face]:
    """Every cylindrical and planar face of one body, with its exact fitted geometry.

    Other surface types are skipped rather than approximated. A cone is not a cylinder
    with an average radius, and reporting one as the other is precisely the class of
    confident-but-wrong number this module exists to prevent — a tapered bore must leave
    ``bore_cylinder`` unresolved.
    """
    out: list[Face] = []
    for face in _faces(shape):
        surf = BRepAdaptor_Surface(face)
        kind = surf.GetType()
        reversed_ = face.Orientation() == TopAbs_REVERSED
        tol = float(BRep_Tool.Tolerance_s(face))
        if kind == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            axis = cyl.Axis()
            loc, dir_ = axis.Location(), axis.Direction()
            out.append(Face(
                "cylinder",
                radius=float(cyl.Radius()),
                origin=(loc.X(), loc.Y(), loc.Z()),
                direction=(dir_.X(), dir_.Y(), dir_.Z()),
                area=_area(face),
                # A cylinder's geometric normal points away from its axis. FORWARD means
                # the solid is on the inside — an outer wall. REVERSED means the solid is
                # outside the surface — a hole.
                outward=not reversed_,
                tolerance=tol,
            ))
        elif kind == GeomAbs_Plane:
            pln = surf.Plane()
            axis = pln.Axis()
            loc, dir_ = axis.Location(), axis.Direction()
            out.append(Face(
                "plane",
                radius=None,
                origin=(loc.X(), loc.Y(), loc.Z()),
                direction=(dir_.X(), dir_.Y(), dir_.Z()),
                area=_area(face),
                outward=not reversed_,
                tolerance=tol,
            ))
    return out


def _revolved_kinds(shape) -> bool:
    """True when every face is a surface of revolution or a plane — the shapes for which
    'rotationally symmetric' can even be asked."""
    allowed = {GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Cone, GeomAbs_Sphere,
               GeomAbs_Torus, GeomAbs_SurfaceOfRevolution}
    for face in _faces(shape):
        if BRepAdaptor_Surface(face).GetType() not in allowed:
            return False
    return True


class PartGeometry:
    """One body, classified: its primary axis, its faces, and the roles they fill.

    Built once per body per build. Resolution is memoised because HE-2 asks the same
    body for several roles and each answer must be the same answer every time.
    """

    def __init__(self, key: str, label: str, shape):
        self.key = key
        self.label = label
        self.shape = shape
        self.faces = classify_faces(shape)
        self.axis_origin: tuple[float, float, float] | None = None
        self.axis_direction: tuple[float, float, float] | None = None
        self.axis_resolution = self._fit_primary_axis()
        self.rotationally_symmetric = self._detect_symmetry()
        self._roles: dict[str, tuple[Face | None, Resolution]] = {}

    # -- primary axis ---------------------------------------------------------
    def _fit_primary_axis(self) -> Resolution:
        """Fit the part's primary axis from its coaxial cylindrical faces.

        Grouped by shared axis and chosen by total area, so a part with one big bore and
        one small cross-drilling picks the bore. A part with no cylindrical face has no
        primary axis at all, and every axis-dependent role then goes unresolved rather
        than falling back to Z — a default axis is an assumption, and this module does
        not make assumptions on the caller's behalf.
        """
        cylinders = [f for f in self.faces if f.kind == "cylinder"]
        if not cylinders:
            return Resolution(False, 0, "coaxial_cylinder_fit",
                              "the body has no cylindrical face to fit an axis to")

        groups: list[list[Face]] = []
        for face in cylinders:
            for group in groups:
                head = group[0]
                if (_parallel(face.direction, head.direction)
                        and _point_to_line(face.origin, head.origin,
                                           head.direction) <= AXIS_OFFSET_TOL_MM):
                    group.append(face)
                    break
            else:
                groups.append([face])

        groups.sort(key=lambda g: sum(f.area for f in g), reverse=True)
        best = groups[0]
        if len(groups) > 1:
            second = sum(f.area for f in groups[1])
            if abs(sum(f.area for f in best) - second) <= AREA_REL_TOL * second:
                return Resolution(False, len(groups), "coaxial_cylinder_fit",
                                  "two cylindrical axes carry the same area, so neither "
                                  "is the primary one")

        head = best[0]
        # Canonical sense, so two builds of the same body never report opposite
        # directions for the same axis. An axis has no inherent sense — OCCT hands back
        # whichever one the surface was constructed with, and a lid tilted 2 degrees came
        # back pointing *down*, which a naive comparison reads as 178 degrees of
        # deviation. Flipping so the dominant component is positive puts a nearly-vertical
        # axis in the same half-space as +Z however it was built. Consumers must still
        # compare direction-agnostically; this only stops the reported vector from
        # surprising a reader.
        d = head.direction
        dominant = max(range(3), key=lambda i: abs(d[i]))
        if d[dominant] < 0:
            d = (-d[0], -d[1], -d[2])
        self.axis_origin = head.origin
        self.axis_direction = d
        for face in self.faces:
            face.axial = _dot(_sub(face.origin, head.origin), d)
        return Resolution(True, len(groups), "coaxial_cylinder_fit")

    def _detect_symmetry(self) -> bool:
        """Whether this body is a solid of revolution about its primary axis.

        HE-7 needs it: two views of a symmetric part are legitimately near-identical, so
        a perceptual-duplicate warning on one is noise, not a finding.
        """
        if self.axis_direction is None or not _revolved_kinds(self.shape):
            return False
        for face in self.faces:
            if face.kind == "plane":
                if not _parallel(face.direction, self.axis_direction, PLANE_NORMAL_TOL):
                    return False
            elif not (_parallel(face.direction, self.axis_direction)
                      and _point_to_line(face.origin, self.axis_origin,
                                         self.axis_direction) <= AXIS_OFFSET_TOL_MM):
                return False
        return True

    # -- coaxial face sets ----------------------------------------------------
    def _coaxial_cylinders(self, outward: bool) -> list[list[Face]]:
        """Coaxial cylindrical faces of one facing, merged into radius groups and sorted
        by radius ascending."""
        if self.axis_direction is None:
            return []
        picked = [f for f in self.faces
                  if f.kind == "cylinder" and f.outward is outward
                  and _parallel(f.direction, self.axis_direction)
                  and _point_to_line(f.origin, self.axis_origin,
                                     self.axis_direction) <= AXIS_OFFSET_TOL_MM]
        groups: list[list[Face]] = []
        for face in sorted(picked, key=lambda f: f.radius):
            if groups and abs(groups[-1][0].radius - face.radius) <= RADIUS_MERGE_MM:
                groups[-1].append(face)
            else:
                groups.append([face])
        return groups

    def _perpendicular_planes(self) -> list[Face]:
        if self.axis_direction is None:
            return []
        return sorted((f for f in self.faces
                       if f.kind == "plane"
                       and _parallel(f.direction, self.axis_direction, PLANE_NORMAL_TOL)),
                      key=lambda f: f.axial)

    # -- roles ----------------------------------------------------------------
    def face(self, role: str) -> tuple[Face | None, Resolution]:
        if role not in FACE_ROLES:
            return None, Resolution(False, 0, "face_role", f"unknown face role: {role}")
        if role not in self._roles:
            self._roles[role] = self._resolve(role)
        return self._roles[role]

    def _resolve(self, role: str) -> tuple[Face | None, Resolution]:
        if not self.axis_resolution.resolved:
            return None, Resolution(False, 0, f"{role}/no_axis",
                                    self.axis_resolution.reason)
        if role == "outer_cylinder":
            return self._extreme_cylinder(outward=True, largest=True)
        if role == "bore_cylinder":
            return self._extreme_cylinder(outward=False, largest=False)
        return self._plane_role(role)

    def _extreme_cylinder(self, *, outward: bool, largest: bool):
        method = "coaxial_cylinder_extreme"
        groups = self._coaxial_cylinders(outward)
        if not groups:
            side = "outward" if outward else "inward"
            return None, Resolution(False, 0, method,
                                    f"the body has no {side}-facing coaxial cylinder")
        ordered = list(reversed(groups)) if largest else groups
        if len(ordered) > 1:
            gap = abs(ordered[0][0].radius - ordered[1][0].radius)
            if gap < AMBIGUITY_RADIUS_MM:
                return None, Resolution(False, len(groups), method,
                                        "two coaxial cylinders differ by less than "
                                        f"{AMBIGUITY_RADIUS_MM} mm, so neither is "
                                        "distinguishable as the extreme one")
        chosen = ordered[0]
        # One face stands for the group; radius and axis are shared by construction, and
        # the area is summed so a split face is not reported as half a wall.
        head = chosen[0]
        merged = Face(head.kind, radius=head.radius, origin=head.origin,
                      direction=head.direction, area=sum(f.area for f in chosen),
                      outward=head.outward,
                      tolerance=max(f.tolerance for f in chosen), axial=head.axial)
        return merged, Resolution(True, len(groups), method)

    def _plane_role(self, role: str):
        method = {"opening_plane": "extreme_annular_plane",
                  "cavity_floor": "bore_bounded_plane",
                  "base_underside": "extreme_disc_plane"}[role]
        planes = self._perpendicular_planes()
        if not planes:
            return None, Resolution(False, 0, method,
                                    "the body has no plane perpendicular to its axis")

        outer, outer_res = self.face("outer_cylinder")
        bore, bore_res = self.face("bore_cylinder")
        if outer is None:
            return None, Resolution(False, len(planes), method,
                                    f"no outer wall to measure a plane against: "
                                    f"{outer_res.reason}")

        r_out = outer.radius
        r_bore = bore.radius if bore is not None else 0.0
        disc = math.pi * r_out * r_out
        annulus = math.pi * (r_out * r_out - r_bore * r_bore)
        floor = math.pi * r_bore * r_bore

        lo, hi = planes[0].axial, planes[-1].axial
        extremes = [f for f in planes
                    if abs(f.axial - lo) <= AXIAL_MERGE_MM
                    or abs(f.axial - hi) <= AXIAL_MERGE_MM]
        interior = [f for f in planes if f not in extremes]

        def matches(face, expect):
            return expect > 0 and abs(face.area - expect) <= AREA_REL_TOL * expect

        if role == "opening_plane":
            if bore is None:
                return None, Resolution(False, len(planes), method,
                                        f"no bore to open into: {bore_res.reason}")
            hits = [f for f in extremes if matches(f, annulus)]
        elif role == "base_underside":
            hits = [f for f in extremes if matches(f, disc)]
        else:
            # A cavity floor is bounded by the bore and is not an end of the body — an
            # end face of that area would be a plain disc on a solid rod, which has no
            # cavity for it to floor.
            hits = [f for f in interior if matches(f, floor)]

        if not hits:
            return None, Resolution(False, len(planes), method,
                                    f"no perpendicular plane has the area a "
                                    f"{role.replace('_', ' ')} would have")
        if len(hits) > 1:
            return None, Resolution(False, len(planes), method,
                                    f"{len(hits)} planes could each be the "
                                    f"{role.replace('_', ' ')}")
        return hits[0], Resolution(True, len(planes), method)

    def as_dict(self) -> dict:
        roles = {}
        for role in FACE_ROLES:
            face, res = self.face(role)
            roles[role] = {"resolution": res.as_dict(),
                           "face": face.as_dict() if face is not None else None}
        return {
            "part_key": self.key,
            "component": self.label or None,
            "axis": {
                "resolution": self.axis_resolution.as_dict(),
                "origin_mm": ([round(v, 6) for v in self.axis_origin]
                              if self.axis_origin else None),
                "direction": ([round(v, 9) for v in self.axis_direction]
                              if self.axis_direction else None),
            },
            "rotationally_symmetric": self.rotationally_symmetric,
            "face_count": len(self.faces),
            "roles": roles,
        }


def parts_of(part) -> list[PartGeometry]:
    """One :class:`PartGeometry` per body, keyed exactly as the scene manifest keys it.

    The dedupe rule is copied from :func:`manifest.compose` rather than re-derived: two
    components sharing a name fall back to slot keys there, and a measurement reporting a
    key the tree does not contain would be unattributable.
    """
    labels = manifest.bodies_of(part)
    children = list(getattr(part, "children", None) or [])
    out: list[PartGeometry] = []
    used: set[str] = set()
    for slot, label in enumerate(labels):
        key = manifest.part_key(label, slot)
        if key in used:
            key = f"slot:{slot}"
        used.add(key)
        source = children[slot] if slot < len(children) else part
        shape = getattr(source, "wrapped", None)
        if shape is None:
            continue
        out.append(PartGeometry(key, label, shape))
    return out


def describe(part) -> list[dict]:
    """The per-part block the build result carries: one entry per body, keyed by the same
    ``part_key`` the scene manifest uses.

    Best-effort per body. A body whose faces OCCT refuses to classify must not cost the
    other bodies their targets, and must not turn a successful build into a failed one —
    classification is evidence, and geometry that exists is still geometry when the
    evidence is thin.
    """
    out = []
    for pg in parts_of(part):
        try:
            out.append(pg.as_dict())
        except Exception as e:  # pragma: no cover - defensive
            out.append({
                "part_key": pg.key,
                "component": pg.label or None,
                "error": f"{type(e).__name__}",
                "roles": {},
            })
    return out


def part_extent(pg: "PartGeometry", axis: str) -> float | None:
    """A body's extent along a global axis, from its own bounding box.

    Part-scoped on purpose: the assembly box measures the assembly. A 100 mm jar under a
    20 mm lid still gives a 115 mm assembly, which is why a height check read off the
    assembly passes the part it should fail.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(pg.shape, box, True)
    if box.IsVoid():
        return None
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {"x": xmax - xmin, "y": ymax - ymin, "z": zmax - zmin}.get(axis)
