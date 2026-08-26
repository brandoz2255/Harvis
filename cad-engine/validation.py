"""Geometry validation for the CAD sidecar (Gate 1A).

Everything here uses primitives that are ALREADY installed with build123d 0.9.1 /
cadquery-ocp 7.8.1.1 — no new dependency. Until now the sidecar reported only bbox
and volume, so a request could get ``ok: true`` back with an invalid or non-watertight
solid and nothing would say so.

Two independent checks, because they answer different questions:

* :func:`measure` asks OpenCascade about the exact B-Rep — is the topology valid, is it
  one solid, what are its mass properties.
* :func:`mesh_report` asks the *exported triangles* whether they form a closed manifold
  surface, which is what a slicer actually consumes. A valid B-Rep can still tessellate
  into a mesh with holes.

Neither is a printability claim and neither is a strength claim. Valid geometry is not
printable; printable is not strong. Keep those three statements separate.
"""
from __future__ import annotations

import hashlib
import struct

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

# STL stores float32, so coincident vertices written by adjacent face triangulations
# can differ in the last bits. Quantise to 1 micron before pairing edges — finer than
# any FDM/SLA process resolves, coarser than float32 noise on a 500 mm part.
_VERTEX_QUANTUM = 1e-3


def _solid_count(shape) -> int:
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def measure(part) -> dict:
    """Exact B-Rep metrics. Raises only if OCP itself fails, which the caller treats
    as a geometry failure rather than a validation verdict."""
    shape = part.wrapped

    surf = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, surf)
    vol = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol)
    com = vol.CentreOfMass()
    bb = part.bounding_box()

    return {
        "brep_valid": bool(BRepCheck_Analyzer(shape, True).IsValid()),
        "solid_count": _solid_count(shape),
        "volume_mm3": round(float(part.volume), 4),
        "surface_area_mm2": round(float(surf.Mass()), 4),
        "bbox_mm": {
            "x": round(float(bb.size.X), 4),
            "y": round(float(bb.size.Y), 4),
            "z": round(float(bb.size.Z), 4),
        },
        # Where the box is, not just how big it is (HE-1). The extents alone cannot say
        # whether a lid sits above a rim or through it, and `bounding_box()` already
        # computed both corners — the old shape discarded them.
        "bbox_min_mm": {
            "x": round(float(bb.min.X), 4),
            "y": round(float(bb.min.Y), 4),
            "z": round(float(bb.min.Z), 4),
        },
        "bbox_max_mm": {
            "x": round(float(bb.max.X), 4),
            "y": round(float(bb.max.Y), 4),
            "z": round(float(bb.max.Z), 4),
        },
        "center_of_mass_mm": {
            "x": round(float(com.X()), 4),
            "y": round(float(com.Y()), 4),
            "z": round(float(com.Z()), 4),
        },
    }


def _quant(v: float) -> int:
    return int(round(v / _VERTEX_QUANTUM))


def mesh_report(stl_path: str) -> dict:
    """Triangle-level report read straight off the exported binary STL.

    Returns ``parsed: False`` rather than guessing if the file is not the binary STL
    layout we write — an honest "unknown" beats a fabricated verdict. ``watertight``
    and ``manifold`` are ``None`` in that case, which is why :class:`ValidationReport`
    types them as optional.
    """
    with open(stl_path, "rb") as fh:
        blob = fh.read()

    if len(blob) < 84:
        return {"parsed": False, "reason": "file shorter than an STL header"}
    count = struct.unpack("<I", blob[80:84])[0]
    if len(blob) != 84 + 50 * count:
        # ASCII STL, or a truncated write. Either way we will not pretend to a verdict.
        return {"parsed": False, "reason": "not the expected binary STL layout"}

    edges: dict[tuple[int, ...], int] = {}
    degenerate = 0
    for i in range(count):
        off = 84 + 50 * i + 12  # skip the per-facet normal
        vx = struct.unpack_from("<9f", blob, off)
        a = (_quant(vx[0]), _quant(vx[1]), _quant(vx[2]))
        b = (_quant(vx[3]), _quant(vx[4]), _quant(vx[5]))
        c = (_quant(vx[6]), _quant(vx[7]), _quant(vx[8]))
        if a == b or b == c or a == c:
            degenerate += 1
            continue
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u <= v else (v, u)
            edges[key] = edges.get(key, 0) + 1

    open_edges = sum(1 for n in edges.values() if n == 1)
    over_shared = sum(1 for n in edges.values() if n > 2)
    return {
        "parsed": True,
        "triangle_count": count,
        "degenerate_triangles": degenerate,
        "open_edges": open_edges,
        "non_manifold_edges": over_shared,
        # closed surface: every edge shared by exactly two triangles
        "watertight": open_edges == 0 and over_shared == 0 and count > 0,
        # manifold is the weaker property: no edge shared by three or more
        "manifold": over_shared == 0 and count > 0,
    }


def mesh_signature(stl_path: str) -> str | None:
    """A hash of the *geometry* an STL describes, independent of how it was encoded.

    Two builds of the same input can differ byte-for-byte and still be the same shape:
    float32 round-off moves coincident vertices in the last bits, and nothing fixes the
    order triangles are written in. This normalizes both — vertices quantised to the
    micron, each triangle rotated so its smallest vertex leads (which preserves winding,
    so a flipped normal is still a difference), then the whole set sorted — and hashes
    the result.

    Returns ``None`` when the file is not the binary STL layout we write, for the same
    reason :func:`mesh_report` returns ``parsed: False``: an honest "unknown" beats a
    fabricated verdict, and a caller comparing two ``None``s must not read that as a
    match.
    """
    with open(stl_path, "rb") as fh:
        blob = fh.read()
    if len(blob) < 84:
        return None
    count = struct.unpack("<I", blob[80:84])[0]
    if len(blob) != 84 + 50 * count:
        return None

    tris: list[tuple[tuple[int, int, int], ...]] = []
    for i in range(count):
        off = 84 + 50 * i + 12  # the per-facet normal is derived, not independent data
        vx = struct.unpack_from("<9f", blob, off)
        v = (
            (_quant(vx[0]), _quant(vx[1]), _quant(vx[2])),
            (_quant(vx[3]), _quant(vx[4]), _quant(vx[5])),
            (_quant(vx[6]), _quant(vx[7]), _quant(vx[8])),
        )
        k = v.index(min(v))
        tris.append((v[k], v[(k + 1) % 3], v[(k + 2) % 3]))

    tris.sort()
    h = hashlib.sha256()
    for tri in tris:
        for vert in tri:
            h.update(struct.pack("<3q", *vert))
    return h.hexdigest()


def verdict(metrics: dict, mesh: dict, expected_solids: int = 1) -> tuple[bool, list[str]]:
    """Fold the two reports into pass/fail plus the reasons. A failure here means the
    sidecar must NOT answer ``ok: true`` — the whole point of Gate 1A is that a bad
    solid stops being indistinguishable from a good one."""
    problems: list[str] = []
    if not metrics.get("brep_valid"):
        problems.append("B-Rep topology is not valid")
    if metrics.get("solid_count") != expected_solids:
        problems.append(
            f"expected {expected_solids} solid(s), got {metrics.get('solid_count')}"
        )
    v = metrics.get("volume_mm3")
    if not isinstance(v, (int, float)) or v != v or v <= 0:
        problems.append("volume is not a finite positive number")
    bb = metrics.get("bbox_mm") or {}
    for axis in ("x", "y", "z"):
        d = bb.get(axis)
        if not isinstance(d, (int, float)) or d != d or d <= 0:
            problems.append(f"bounding box {axis} extent is not a finite positive number")
    if mesh.get("parsed") and not mesh.get("watertight"):
        problems.append(
            f"exported mesh is not watertight ({mesh.get('open_edges')} open edge(s), "
            f"{mesh.get('non_manifold_edges')} non-manifold edge(s))"
        )
    return (not problems), problems


def import_verdict(metrics: dict, mesh: dict, *, exact: bool) -> tuple[bool, list[str]]:
    """The same job as :func:`verdict`, for geometry we did not author (Gate 8B).

    Running the authored-geometry verdict on an import would fail correct files for
    being what they are. Three of its checks assume a solid built to a spec:

    * **solid count** — the caller cannot state an expectation, because the file
      decides. A STEP carrying two bodies is not a defect; asserting "1" would reject
      it.
    * **volume** — an STL re-imports as a ``Face``. There is no volume to ask for. A
      triangle soup without one is exactly what an STL is.
    * **watertightness** — a reference mesh is allowed to be open. Scans and
      decimations routinely are, and they are still useful for alignment and scale.
      Calling an open one invalid would refuse the normal case.

    What survives is what stays meaningful. A bounding box must be finite and positive
    whatever the format: a file measuring zero on an axis gave us nothing to look at.
    B-Rep validity and a positive volume are asserted only when ``exact`` — the parser
    handed back a real solid (STEP, BREP, or a 3MF that lib3mf rebuilt into one), which
    is the one case where invalid topology means the file is broken rather than coarse.

    ``mesh`` is unused today and stays in the signature because the triangle report is
    the natural home for any future import check, and a caller that already passes it
    should not have to change when one arrives.
    """
    problems: list[str] = []
    bb = metrics.get("bbox_mm") or {}
    for axis in ("x", "y", "z"):
        d = bb.get(axis)
        if not isinstance(d, (int, float)) or d != d or d <= 0:
            problems.append(f"bounding box {axis} extent is not a finite positive number")

    if exact:
        if not metrics.get("brep_valid"):
            problems.append("B-Rep topology is not valid")
        v = metrics.get("volume_mm3")
        if not isinstance(v, (int, float)) or v != v or v <= 0:
            problems.append("volume is not a finite positive number")

    return (not problems), problems
