"""The jar-with-lid fixture family — one correct part and seven wrong ones (HE-0).

Every later gate in the evidence tranche needs a part whose *right answer is known
before anything measures it*. A model-authored jar cannot serve: it changes between
runs, and a measurement that disagrees with it is then ambiguous between a broken
measurement and a broken part. These eight documents are authored here, built by the
engine directly with no model in the loop, and checked in as JSON so the test bed
cannot drift.

The JSON files next to this module are the fixtures of record. This module is how they
were written, and ``test_fixtures_build.py`` asserts that re-running it reproduces them
byte for byte — so a deliberate change is a visible diff and an accidental one is a
failing test.

**The shape.** A hollow cylindrical body with a flat floor, and a separate lid whose
skirt drops over the body's neck. That is the smallest part that exercises every
measurement HE-2 owes: two coaxial cylindrical faces per body (so a wall has a local
thickness), two parallel planar faces bounding a cavity (so a depth and a floor
thickness are exact plane pairs), a mating interface between two named parts (so a
clearance is a radius comparison rather than a body distance), and a second solid that
must stay a second solid (so "a separate lid" is checkable).

Two cuts are deliberately run 1 mm past the face they open onto. A cut that stops
exactly on the outer face is a coplanar boolean, and coplanar booleans are where OCCT
produces sliver faces that would make face classification a coin toss. Running past
costs nothing — the resulting faces are identical — and removes the coincidence.

**Every variant is wrong in exactly one way**, so a check that fires on the wrong
fixture has nowhere to hide:

    good                115 mm body, 2.5 neck wall, 4.0 base, separate lid,
                        5.5 skirt, concentric, 0.30 mm diametral clearance
    bad_skirt_shallow   skirt 3.0 mm
    bad_base_thin       base 3.5 mm
    bad_wall_thin       neck wall 1.8 mm
    bad_interference    lid bore 0.2 mm under the neck — a press fit, not a slip fit
    bad_tilted          lid tilted 2 deg about its OWN bbox centre, so the centroids
                        still agree and only a fitted axis can see it
    bad_offset          lid displaced 0.5 mm radially, same centroid z, same reason
    bad_body_short      body 100 mm — and the lid grown so the ASSEMBLY bbox is still
                        115 mm, which is the case an assembly-bbox height check passes
                        and a part-scoped one fails
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

# The nominal jar. Ranges are wide enough that every variant below is a legal value of
# the same document rather than a differently-shaped one — the fixtures differ in
# numbers, never in operations, so a measurement cannot be right on one and undefined
# on another.
BASE_PARAMS = {
    "body_h":     {"default": 115.0, "min": 20.0, "max": 400.0},
    "body_r":     {"default": 20.0,  "min": 5.0,  "max": 100.0},
    "neck_wall":  {"default": 2.5,   "min": 0.5,  "max": 20.0},
    "base_t":     {"default": 4.0,   "min": 0.5,  "max": 30.0},
    # Not derived from body_r + clearance, because bad_interference has to be able to
    # state a bore SMALLER than the neck it goes over, and a derived clearance would
    # have to go negative to say it.
    "lid_bore_r": {"default": 20.15, "min": 5.0,  "max": 110.0},
    "lid_wall":   {"default": 2.5,   "min": 0.5,  "max": 20.0},
    "skirt_depth": {"default": 5.5,  "min": 1.0,  "max": 40.0},
    "lid_top_t":  {"default": 2.5,   "min": 0.5,  "max": 40.0},
}

# Order matters: a derived value only sees the ones defined before it.
DERIVED = [
    ("bore_r",         "body_r - neck_wall"),
    ("body_z1",        "body_h / 2"),
    ("body_z0",        "-body_h / 2"),
    ("cavity_floor_z", "body_z0 + base_t"),
    # +1 so the bore breaks through the rim instead of ending coplanar with it.
    ("bore_h",         "body_h - base_t + 1"),
    ("bore_center_z",  "cavity_floor_z + bore_h / 2"),
    ("lid_r",          "lid_bore_r + lid_wall"),
    ("lid_h",          "skirt_depth + lid_top_t"),
    ("lid_z0",         "body_z1 - skirt_depth"),
    ("lid_center_z",   "lid_z0 + lid_h / 2"),
    # Same 1 mm overrun, opening the skirt onto the lid's underside.
    ("cav_h",          "skirt_depth + 1"),
    ("cav_center_z",   "lid_z0 - 1 + cav_h / 2"),
]

OPERATIONS = [
    {
        "op": "cylinder", "op_id": "body_outer", "component": "jar_body",
        "radius": "body_r", "height": "body_h",
        "at": {"positions": [[0, 0, 0]]},
    },
    {
        "op": "cylinder", "op_id": "body_bore", "component": "jar_body",
        "radius": "bore_r", "height": "bore_h", "mode": "subtract",
        "at": {"positions": [[0, 0, "bore_center_z"]]},
    },
    {
        "op": "cylinder", "op_id": "lid_outer", "component": "lid",
        "radius": "lid_r", "height": "lid_h",
        "at": {"positions": [[0, 0, "lid_center_z"]]},
    },
    {
        "op": "cylinder", "op_id": "lid_skirt_bore", "component": "lid",
        "radius": "lid_bore_r", "height": "cav_h", "mode": "subtract",
        "at": {"positions": [[0, 0, "cav_center_z"]]},
    },
]

# name -> (parameter overrides, placements, what is wrong with it)
VARIANTS: dict[str, tuple[dict, list, str]] = {
    "good": ({}, [], "nothing — this is the part the spec describes"),
    "bad_skirt_shallow": ({"skirt_depth": 3.0}, [], "skirt is 3.0 mm, spec says 5.5"),
    "bad_base_thin": ({"base_t": 3.5}, [], "base is 3.5 mm, spec says 4.0"),
    "bad_wall_thin": ({"neck_wall": 1.8}, [], "neck wall is 1.8 mm, spec says 2.5"),
    "bad_interference": (
        {"lid_bore_r": 19.9}, [],
        "lid bore is 0.1 mm under the neck radius — the parts overlap"),
    "bad_tilted": (
        {}, [{"component": "lid", "rotate": [2.0, 0.0, 0.0]}],
        "lid is tilted 2 deg; its centroid is unmoved, so only a fitted axis sees it"),
    "bad_offset": (
        {}, [{"component": "lid", "translate": [0.5, 0.0, 0.0]}],
        "lid is 0.5 mm off axis at the same centroid height"),
    "bad_body_short": (
        # 100 body + 20.5 lid - 5.5 engagement = 115.0 assembly. The body is 15 mm
        # short and the assembly bounding box is exactly right, which is the whole
        # point of this one.
        {"body_h": 100.0, "lid_top_t": 15.0}, [],
        "body is 100 mm, but the assembly bbox still reads 115 mm"),
}


def document(variant: str) -> dict:
    """The CadIR document for one variant, as a plain dict ready for ``cadir.parse``."""
    overrides, placements, _why = VARIANTS[variant]
    unknown = set(overrides) - set(BASE_PARAMS)
    if unknown:
        raise KeyError(f"{variant} overrides unknown parameter(s): {sorted(unknown)}")

    parameters = []
    for name, spec in BASE_PARAMS.items():
        value = overrides.get(name, spec["default"])
        if not (spec["min"] <= value <= spec["max"]):
            raise ValueError(f"{variant}: {name}={value} is outside its declared range")
        parameters.append({
            "name": name, "kind": "float", "default": value,
            "min": spec["min"], "max": spec["max"],
        })

    return {
        "schema_version": "0.3",
        "units": "mm",
        "name": f"jar_{variant}",
        "parameters": parameters,
        "derived": [{"name": n, "value": v} for n, v in DERIVED],
        "operations": [dict(op) for op in OPERATIONS],
        "placements": list(placements),
        "expected_solids": 2,
    }


def path_for(variant: str) -> pathlib.Path:
    return HERE / f"{variant}.json"


def load(variant: str) -> dict:
    return json.loads(path_for(variant).read_text())


def serialize(variant: str) -> str:
    return json.dumps(document(variant), indent=2, sort_keys=False) + "\n"


def write_all() -> list[pathlib.Path]:
    out = []
    for variant in VARIANTS:
        p = path_for(variant)
        p.write_text(serialize(variant))
        out.append(p)
    return out


if __name__ == "__main__":
    for p in write_all():
        print(p)
