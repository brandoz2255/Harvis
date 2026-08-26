"""What a measurement *request* looks like (HE-2), with no geometry kernel in sight.

Split from :mod:`measure` for the reason :mod:`cadir` states about itself: the server
validates and admits a build before spawning a child, and importing OCP there would undo
the 1.767 s-per-build saving the warm pool exists to deliver. So the grammar lives here,
where the server can read it, and the arithmetic lives in :mod:`measure`, where the shape
does.

The model never writes one of these. The server derives the request list from the
DesignSpec's checks, which are themselves server-extracted — the rule that keeps a model
from authoring both a part and its own acceptance criteria stays intact all the way down
to the measurement layer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"

FACE_ROLES = ("outer_cylinder", "bore_cylinder", "opening_plane", "cavity_floor",
              "base_underside")

Unit = Literal["mm", "deg", "mm3", "count"]
Basis = Literal["radial", "diametral"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaceRef(StrictModel):
    part_key: str = Field(min_length=1, max_length=128)
    face_role: Literal[FACE_ROLES]


class PartRef(StrictModel):
    part_key: str = Field(min_length=1, max_length=128)


class AxisRef(StrictModel):
    part_key: str = Field(min_length=1, max_length=128)
    axis_role: Literal["primary"] = "primary"


# Which kind takes which pair, and what it answers in. Declared as data so the server,
# the worker and the tests all read the same table instead of three copies of it.
KINDS: dict[str, dict] = {
    "local_thickness": {
        "pair": "face", "unit": "mm", "basis": "radial",
        "method": "coaxial_radius_difference",
        "what": "material between an outer wall and the bore behind it",
    },
    "radial_clearance": {
        "pair": "face", "unit": "mm", "basis": "radial",
        "method": "coaxial_radius_difference",
        "what": "the gap between two mating cylinders on a shared axis",
    },
    "plane_gap": {
        "pair": "face", "unit": "mm", "basis": None,
        "method": "axial_plane_distance",
        "what": "the distance between two planes along the part's own axis",
    },
    "part_extent": {
        "pair": "part_axis", "unit": "mm", "basis": None,
        "method": "part_bounding_extent",
        "what": "one body's size on one global axis",
    },
    "axis_offset": {
        "pair": "axis", "unit": "mm", "basis": None,
        "method": "fitted_axis_offset",
        "what": "how far apart two fitted axes are",
    },
    "angular_deviation": {
        "pair": "axis", "unit": "deg", "basis": None,
        "method": "fitted_axis_angle",
        "what": "the angle between two fitted axes",
    },
    "interference_volume": {
        "pair": "part", "unit": "mm3", "basis": None,
        "method": "fuzzy_boolean_common",
        "what": "how much material two bodies claim at the same time",
    },
    "part_count": {
        "pair": "none", "unit": "count", "basis": None,
        "method": "manifest_body_count",
        "what": "how many separate bodies the build produced",
    },
}

Kind = Literal[tuple(KINDS)]

# The default fuzzy tolerance for the interference boolean. OCCT needs *some* slack or
# two faces that touch exactly produce numerical slivers; too much and a real 0.05 mm
# press fit is absorbed. 1e-4 mm is two orders below the tightest fit this system
# measures and four above float64 noise on a 500 mm part.
DEFAULT_FUZZY_MM = 1e-4


class MeasurementRequest(StrictModel):
    """One thing to measure. ``a``/``b`` are typed loosely here and checked against
    :data:`KINDS` below, because a per-kind union would need eight classes to say what
    one validator says once."""

    measurement_id: str = Field(min_length=1, max_length=64,
                                pattern=r"^[a-z][a-z0-9_]*$")
    kind: Kind
    a: dict | None = None
    b: dict | None = None
    part_key: str | None = Field(default=None, min_length=1, max_length=128)
    axis: Literal["x", "y", "z"] | None = None
    fuzzy_mm: float = Field(default=DEFAULT_FUZZY_MM, gt=0, le=1.0)

    def model_post_init(self, _ctx) -> None:
        shape = KINDS[self.kind]["pair"]
        if shape == "face":
            FaceRef.model_validate(self.a or {})
            FaceRef.model_validate(self.b or {})
        elif shape == "axis":
            AxisRef.model_validate(self.a or {})
            AxisRef.model_validate(self.b or {})
        elif shape == "part":
            PartRef.model_validate(self.a or {})
            PartRef.model_validate(self.b or {})
        elif shape == "part_axis":
            if not self.part_key or self.axis is None:
                raise ValueError("part_extent needs a part_key and an axis")
        if shape != "part_axis" and (self.part_key or self.axis):
            raise ValueError(f"{self.kind} does not take part_key or axis")
        if shape in ("none",) and (self.a or self.b):
            raise ValueError(f"{self.kind} takes no target")


# A build may not ask for an unbounded number of these. Each one walks every face of a
# body, and the interference kind runs a boolean — so the cap is admission control, not
# tidiness.
MAX_MEASUREMENTS = 64


def parse(payload) -> list[MeasurementRequest]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("measurements must be a list")
    if len(payload) > MAX_MEASUREMENTS:
        raise ValueError(f"at most {MAX_MEASUREMENTS} measurements per build")
    out = [MeasurementRequest.model_validate(item) for item in payload]
    seen = set()
    for req in out:
        if req.measurement_id in seen:
            raise ValueError(f"duplicate measurement_id: {req.measurement_id}")
        seen.add(req.measurement_id)
    return out
