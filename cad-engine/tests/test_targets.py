"""HE-1 — the semantic target resolver, and the cases it must refuse.

Two halves, and the second matters more. The first proves the resolver finds the right
face on the jar. The second proves it *declines* on geometry where no rule can honestly
pick one: a tapered bore, two bores the same size, a body with no round face at all.

An unresolved target grades ``unverified`` upstream. A wrongly-resolved one grades
``failed`` — with a number, on the wrong feature. That is the failure this gate exists to
make impossible, so every refusal below is a passing test, not a limitation.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import cadir  # noqa: E402
import targets  # noqa: E402
import validation  # noqa: E402
from cadir import interpret as cadir_interpret  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "jar"


def _build(document: dict):
    doc = cadir.parse(document)
    resolved = cadir.resolve_params(doc, {})
    env, steps, _cost = cadir.check(doc, resolved)
    return cadir_interpret.build(doc, resolved, steps=steps, env=env)


def _fixture(variant: str):
    return _build(json.loads((FIXTURES / f"{variant}.json").read_text()))


def _synthetic(name: str, operations: list[dict], expected_solids: int = 1):
    """A one-off document, written inline because these bodies exist only to be refused.
    Promoting them to checked-in fixtures would imply someone might want to build one."""
    return _build({
        "schema_version": cadir.SCHEMA_VERSION,
        "name": name,
        "parameters": [],
        "operations": operations,
        "expected_solids": expected_solids,
    })


def _by_key(part) -> dict[str, targets.PartGeometry]:
    return {pg.key: pg for pg in targets.parts_of(part)}


# --- 1. the jar resolves, on the keys the rest of the system already uses --------

@pytest.fixture(scope="module")
def good():
    return _by_key(_fixture("good"))


def test_the_bodies_are_keyed_the_way_the_scene_manifest_keys_them(good):
    """Not a second identity system. `manifest.part_key` is what the tree row, the GLB
    pick key and the per-part colour are already built on, so a measurement reported
    against one of these keys lands on a part the user can see."""
    assert set(good) == {"name:jar_body", "name:lid"}


def test_both_bodies_fit_a_vertical_primary_axis(good):
    for key, pg in good.items():
        assert pg.axis_resolution.resolved, key
        assert pg.axis_direction == pytest.approx((0.0, 0.0, 1.0), abs=1e-9), key


def test_the_neck_wall_is_two_exact_radii_and_not_a_gap_search(good):
    """The whole reason face roles exist. A global minimum distance between non-adjacent
    faces finds the narrowest gap anywhere in the body — across the bore, 35 mm — not the
    2.5 mm of material the spec is about."""
    body = good["name:jar_body"]
    outer, outer_res = body.face("outer_cylinder")
    bore, bore_res = body.face("bore_cylinder")
    assert outer_res.resolved and bore_res.resolved
    assert outer.radius == pytest.approx(20.0, abs=1e-9)
    assert bore.radius == pytest.approx(17.5, abs=1e-9)
    assert outer.radius - bore.radius == pytest.approx(2.5, abs=1e-9)


def test_orientation_separates_the_bore_from_the_outer_wall(good):
    """Both are cylinders on the same axis. What tells them apart is which side the
    material is on, which survives the boolean that cut one of them."""
    body = good["name:jar_body"]
    assert body.face("outer_cylinder")[0].outward is True
    assert body.face("bore_cylinder")[0].outward is False


def test_the_three_plane_roles_land_on_the_three_planes(good):
    body = good["name:jar_body"]
    opening = body.face("opening_plane")[0]
    floor = body.face("cavity_floor")[0]
    base = body.face("base_underside")[0]
    # Axial coordinates are measured from the axis origin at the underside, z = -57.5.
    assert base.axial == pytest.approx(0.0, abs=1e-6)
    assert floor.axial == pytest.approx(4.0, abs=1e-6)
    assert opening.axial == pytest.approx(115.0, abs=1e-6)
    # ...so the base is 4 mm and the cavity is 111 mm deep, both exactly.
    assert floor.axial - base.axial == pytest.approx(4.0, abs=1e-6)
    assert opening.axial - floor.axial == pytest.approx(111.0, abs=1e-6)


def test_the_lid_opens_downward_and_the_roles_follow_the_geometry(good):
    """The lid is the same cup upside down. Nothing here keys on 'up' — the opening is
    whichever end is annular, which is why one rule serves both bodies."""
    lid = good["name:lid"]
    opening = lid.face("opening_plane")[0]
    floor = lid.face("cavity_floor")[0]
    base = lid.face("base_underside")[0]
    assert opening.axial == pytest.approx(0.0, abs=1e-6)     # z = 52, the open end
    assert floor.axial == pytest.approx(5.5, abs=1e-6)       # z = 57.5, skirt depth
    assert base.axial == pytest.approx(8.0, abs=1e-6)        # z = 60, the closed top
    assert floor.axial - opening.axial == pytest.approx(5.5, abs=1e-6)


def test_both_bodies_are_recognised_as_solids_of_revolution(good):
    """HE-7 suppresses perceptual-duplicate warnings on symmetric parts. Two views of a
    jar are legitimately near-identical, and calling that a defect would be noise."""
    assert all(pg.rotationally_symmetric for pg in good.values())


def test_every_face_carries_the_numerical_error_it_was_measured_with(good):
    for pg in good.values():
        for face in pg.faces:
            assert face.tolerance > 0
            assert face.tolerance < 1e-3


# --- 2. the refusals ------------------------------------------------------------

def test_a_tapered_bore_is_not_reported_as_a_cylinder():
    """A cone has no single radius. Averaging one out of it would produce a wall
    thickness that is wrong everywhere except one height."""
    part = _synthetic("tapered", [
        {"op": "cylinder", "op_id": "body", "radius": 20, "height": 40},
        {"op": "cone", "op_id": "taper", "bottom_radius": 17.5, "top_radius": 14,
         "height": 42, "mode": "subtract"},
    ])
    pg = _by_key(part)["slot:0"]
    face, res = pg.face("bore_cylinder")
    assert face is None
    assert not res.resolved
    assert "inward-facing coaxial cylinder" in res.reason


def test_two_bores_the_same_size_are_ambiguous_rather_than_arbitrary():
    """Both are 'the smallest' within numerical error. Picking one would be a coin flip
    wearing a rule's clothes."""
    part = _synthetic("double_wall", [
        {"op": "cylinder", "op_id": "body", "radius": 30, "height": 40},
        {"op": "cylinder", "op_id": "bore_a", "radius": 17.5, "height": 18,
         "mode": "subtract", "at": {"positions": [[0, 0, -11]]}},
        {"op": "cylinder", "op_id": "bore_b", "radius": 17.5002, "height": 18,
         "mode": "subtract", "at": {"positions": [[0, 0, 11]]}},
    ])
    pg = _by_key(part)["slot:0"]
    face, res = pg.face("bore_cylinder")
    assert face is None
    assert not res.resolved
    assert "distinguishable" in res.reason
    assert res.candidates_considered == 2


def test_two_bores_that_genuinely_differ_do_resolve():
    """The counterpart to the test above: a real counterbore is not ambiguous, and the
    ambiguity guard must not refuse it."""
    part = _synthetic("counterbore", [
        {"op": "cylinder", "op_id": "body", "radius": 30, "height": 40},
        {"op": "cylinder", "op_id": "bore_a", "radius": 10, "height": 18,
         "mode": "subtract", "at": {"positions": [[0, 0, -11]]}},
        {"op": "cylinder", "op_id": "bore_b", "radius": 20, "height": 18,
         "mode": "subtract", "at": {"positions": [[0, 0, 11]]}},
    ])
    pg = _by_key(part)["slot:0"]
    face, res = pg.face("bore_cylinder")
    assert res.resolved
    assert face.radius == pytest.approx(10.0, abs=1e-9)


def test_a_body_with_no_round_face_has_no_primary_axis():
    """And therefore no axis-dependent target. Defaulting to Z would be an assumption
    made on the caller's behalf, and every measurement downstream would inherit it."""
    part = _synthetic("plain_box", [
        {"op": "box", "op_id": "block", "size": [40, 30, 20]},
    ])
    pg = _by_key(part)["slot:0"]
    assert not pg.axis_resolution.resolved
    assert "no cylindrical face" in pg.axis_resolution.reason
    for role in targets.FACE_ROLES:
        face, res = pg.face(role)
        assert face is None, role
        assert not res.resolved, role
    assert pg.rotationally_symmetric is False


def test_a_solid_rod_has_no_cavity_floor():
    """There is a disc at each end and nothing bounded by a bore. A rule that took 'the
    plane with the smallest area' would happily name one."""
    part = _synthetic("rod", [
        {"op": "cylinder", "op_id": "rod", "radius": 8, "height": 60},
    ])
    pg = _by_key(part)["slot:0"]
    assert pg.face("outer_cylinder")[1].resolved
    for role in ("bore_cylinder", "cavity_floor", "opening_plane"):
        assert not pg.face(role)[1].resolved, role
    # ...but the two end discs are both plausible undersides, and that is ambiguous too.
    face, res = pg.face("base_underside")
    assert face is None
    assert "could each be" in res.reason


def test_an_unknown_role_is_refused_by_name():
    part = _synthetic("rod2", [
        {"op": "cylinder", "op_id": "rod", "radius": 8, "height": 60},
    ])
    pg = _by_key(part)["slot:0"]
    face, res = pg.face("flange_face")
    assert face is None and not res.resolved
    assert "unknown face role" in res.reason


# --- 3. part-scoped extent, the thing an assembly box cannot say ----------------

def test_the_body_height_is_the_bodys_own_box_not_the_assemblys():
    """`bad_body_short` is a 100 mm jar. Its assembly measures 115 mm, and the correct
    jar measures 117.5 — so a height check read off the assembly passes the broken part
    and fails the good one, in that order."""
    short = _fixture("bad_body_short")
    good_part = _fixture("good")

    assert targets.part_extent(_by_key(short)["name:jar_body"], "z") == pytest.approx(100.0, abs=1e-6)
    assert targets.part_extent(_by_key(good_part)["name:jar_body"], "z") == pytest.approx(115.0, abs=1e-6)

    assert validation.measure(short)["bbox_mm"]["z"] == pytest.approx(115.0, abs=1e-3)
    assert validation.measure(good_part)["bbox_mm"]["z"] == pytest.approx(117.5, abs=1e-3)


def test_measure_still_answers_every_key_it_used_to():
    """HE-1 is additive or it is nothing: `cad_conformance` and the frontend both read
    these names, and a rename would change verdicts without changing geometry."""
    metrics = validation.measure(_fixture("good"))
    for key in ("brep_valid", "solid_count", "volume_mm3", "surface_area_mm2",
                "bbox_mm", "center_of_mass_mm"):
        assert key in metrics, key
    assert set(metrics["bbox_mm"]) == {"x", "y", "z"}
    # ...and now says where the box is, which the extents alone never could.
    assert metrics["bbox_min_mm"]["z"] == pytest.approx(-57.5, abs=1e-3)
    assert metrics["bbox_max_mm"]["z"] == pytest.approx(60.0, abs=1e-3)


def test_describe_is_json_safe_and_covers_every_body():
    blocks = targets.describe(_fixture("good"))
    assert [b["part_key"] for b in blocks] == ["name:jar_body", "name:lid"]
    json.dumps(blocks)  # must survive the trip into the build result
    for block in blocks:
        assert set(block["roles"]) == set(targets.FACE_ROLES)
        for role, entry in block["roles"].items():
            assert entry["resolution"]["method_version"] == targets.METHOD_VERSION
