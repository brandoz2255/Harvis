"""HE-2 — the measurements, and the proxies they replaced.

Every section below is an answer key the fixtures were built to provide. The point is
not that the numbers come out; it is that they come out where the *obvious* measurement
gets it wrong, which is why each section states the proxy it beats:

* a seated lid touches the rim, so whole-body distance reads 0 on a perfect fit
* a 0.5 mm lid offset moves the assembly centroid 0.067 mm
* a 2 degree tilt moves it 0.007 mm
* a 100 mm body under a 20 mm lid still measures 115 mm as an assembly

Each of those is asserted here alongside the real measurement, so a future change that
quietly reverts to a proxy fails on the comparison and not on a taste argument.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import cadir  # noqa: E402
import measure  # noqa: E402
import measure_spec  # noqa: E402
import targets  # noqa: E402
import validation  # noqa: E402
from cadir import interpret as cadir_interpret  # noqa: E402

from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "jar"

BODY = "name:jar_body"
LID = "name:lid"


def _build(document: dict):
    doc = cadir.parse(document)
    resolved = cadir.resolve_params(doc, {})
    env, steps, _cost = cadir.check(doc, resolved)
    return cadir_interpret.build(doc, resolved, steps=steps, env=env)


def _fixture(variant: str):
    return _build(json.loads((FIXTURES / f"{variant}.json").read_text()))


# The measurement set the jar prompt implies, written once. Every fixture is measured
# with the same list, because a check that only appears for the variant it catches
# proves nothing about the variants it does not.
REQUESTS = measure_spec.parse([
    {"measurement_id": "fit", "kind": "radial_clearance",
     "a": {"part_key": LID, "face_role": "bore_cylinder"},
     "b": {"part_key": BODY, "face_role": "outer_cylinder"}},
    {"measurement_id": "neck_wall", "kind": "local_thickness",
     "a": {"part_key": BODY, "face_role": "outer_cylinder"},
     "b": {"part_key": BODY, "face_role": "bore_cylinder"}},
    {"measurement_id": "base", "kind": "plane_gap",
     "a": {"part_key": BODY, "face_role": "base_underside"},
     "b": {"part_key": BODY, "face_role": "cavity_floor"}},
    {"measurement_id": "skirt", "kind": "plane_gap",
     "a": {"part_key": LID, "face_role": "opening_plane"},
     "b": {"part_key": LID, "face_role": "cavity_floor"}},
    {"measurement_id": "body_height", "kind": "part_extent",
     "part_key": BODY, "axis": "z"},
    {"measurement_id": "offset", "kind": "axis_offset",
     "a": {"part_key": BODY}, "b": {"part_key": LID}},
    {"measurement_id": "tilt", "kind": "angular_deviation",
     "a": {"part_key": BODY}, "b": {"part_key": LID}},
    {"measurement_id": "overlap", "kind": "interference_volume",
     "a": {"part_key": BODY}, "b": {"part_key": LID}},
    {"measurement_id": "bodies", "kind": "part_count"},
])


def _measured(variant: str) -> dict[str, dict]:
    part = _fixture(variant)
    return {r["measurement_id"]: r for r in measure.run(part, REQUESTS,
                                                        source_hash=f"h_{variant}")}


@pytest.fixture(scope="module")
def good():
    return _measured("good")


# --- 1. the clearance a distance query cannot see --------------------------------

def test_a_seated_lid_touches_the_rim_so_whole_body_distance_reads_zero():
    """The proxy this measurement replaces, run on the correct part.

    ``BRepExtrema_DistShapeShape`` between the two bodies returns 0 for the *good* jar,
    because a lid that fits is a lid that rests on something. A clearance check built on
    it would report the one correct fixture as an interference."""
    part = _fixture("good")
    a, b = [pg.shape for pg in targets.parts_of(part)]
    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    assert d.Value() == pytest.approx(0.0, abs=1e-9)


def test_radial_clearance_is_the_gap_between_the_mating_radii(good):
    fit = good["fit"]
    assert fit["resolution"]["resolved"]
    assert fit["value"] == pytest.approx(0.15, abs=1e-6)
    assert fit["unit"] == "mm"
    assert fit["basis"] == "radial"
    # Both, always. "0.3 mm clearance" in ordinary speech is diametral and the two differ
    # by a factor of two, so reporting one number silently halves or doubles the spec.
    assert fit["diametral_mm"] == pytest.approx(0.30, abs=1e-6)


def test_an_undersized_bore_reads_as_a_negative_clearance():
    """A press fit is a clearance with the sign flipped, and the sign is the defect.
    Reporting the absolute value would make ``bad_interference`` indistinguishable from
    a 0.1 mm slip fit."""
    fit = _measured("bad_interference")["fit"]
    assert fit["value"] == pytest.approx(-0.10, abs=1e-6)
    assert fit["diametral_mm"] == pytest.approx(-0.20, abs=1e-6)


def test_a_clearance_between_non_coaxial_cylinders_is_refused_not_guessed():
    """``bad_offset`` moves the lid 0.5 mm sideways. The two radii still subtract to a
    plausible-looking 0.15, and that number would be a lie: there is no single radial gap
    between cylinders that are not about the same line. Unresolved, never failed — the
    part *is* wrong, but ``axis_offset`` is the check that proves it."""
    fit = _measured("bad_offset")["fit"]
    assert fit["resolution"]["resolved"] is False
    assert fit["value"] is None, "an unmeasurable clearance must not be reported as 0"
    assert "shared axis" in fit["resolution"]["reason"]
    assert fit["diagnostic"]["axis_offset_mm"] == pytest.approx(0.5, abs=1e-6)


# --- 2. concentricity is two numbers, and a centroid is neither ------------------

def test_a_half_millimetre_offset_barely_moves_the_centroid():
    """The proxy, measured. The lid carries about a seventh of the assembly's mass, so
    displacing it 0.5 mm — more than three times the radial clearance — moves the
    assembly's centre of mass 0.067 mm. A concentricity check keyed on that would need a
    tolerance seven times tighter than the defect it is looking for."""
    good_com = validation.measure(_fixture("good"))["center_of_mass_mm"]
    off_com = validation.measure(_fixture("bad_offset"))["center_of_mass_mm"]
    moved = math.dist((good_com["x"], good_com["y"], good_com["z"]),
                      (off_com["x"], off_com["y"], off_com["z"]))
    assert moved < 0.5 / 3


def test_axis_offset_reports_the_displacement_itself():
    m = _measured("bad_offset")
    assert m["offset"]["value"] == pytest.approx(0.5, abs=1e-6)
    assert m["offset"]["unit"] == "mm"
    # A slide is not a tilt. Reporting one number for "concentricity" would conflate them.
    assert m["tilt"]["value"] == pytest.approx(0.0, abs=1e-6)


def test_a_two_degree_tilt_moves_the_centroid_by_seven_microns():
    """The same proxy against the other defect, and it does even worse: 7 microns, an
    order of magnitude below the tightest dimension in the part."""
    good_com = validation.measure(_fixture("good"))["center_of_mass_mm"]
    tilt_com = validation.measure(_fixture("bad_tilted"))["center_of_mass_mm"]
    moved = math.dist((good_com["x"], good_com["y"], good_com["z"]),
                      (tilt_com["x"], tilt_com["y"], tilt_com["z"]))
    assert moved < 0.015


def test_angular_deviation_reports_the_tilt_itself():
    m = _measured("bad_tilted")
    assert m["tilt"]["value"] == pytest.approx(2.0, abs=1e-6)
    assert m["tilt"]["unit"] == "deg"
    # A tilt about the lid's own centre does not move its axis through that centre, so
    # the offset stays 0. Both numbers are needed; either alone passes one of the two
    # broken fixtures.
    assert m["offset"]["value"] == pytest.approx(0.0, abs=1e-6)


def test_the_correct_jar_is_concentric_on_both_numbers(good):
    assert good["offset"]["value"] == pytest.approx(0.0, abs=1e-6)
    assert good["tilt"]["value"] == pytest.approx(0.0, abs=1e-6)


def test_an_axis_has_no_sense_so_the_angle_never_reads_178_degrees():
    """OCCT hands back whichever direction the surface was constructed with, and the
    tilted lid's came back pointing *down*. A signed comparison reads that as 178
    degrees of deviation on a 2 degree defect."""
    assert measure._axis_angle((0, 0, 1), (0, 0, -1)) == pytest.approx(0.0, abs=1e-9)
    assert measure._axis_angle((0, 0, 1), (1, 0, 0)) == pytest.approx(90.0, abs=1e-9)


# --- 3. thickness and depth, locally, at a named place ---------------------------

def test_the_neck_wall_is_two_radii_at_one_interface(good):
    wall = good["neck_wall"]
    assert wall["value"] == pytest.approx(2.5, abs=1e-6)
    assert wall["basis"] == "radial"
    # A thickness has no diametral reading. Doubling a 2.5 mm wall gives 5.0 mm of
    # nothing, and a grader that saw both numbers could pick the wrong one.
    assert "diametral_mm" not in wall


def test_a_thin_wall_is_measured_thin():
    assert _measured("bad_wall_thin")["neck_wall"]["value"] == pytest.approx(1.8, abs=1e-6)


def test_base_thickness_is_the_gap_the_first_plan_forgot_entirely(good):
    """Rev 1 of this tranche had no base check at all. It is the underside plane to the
    cavity floor, along the body's own axis."""
    assert good["base"]["value"] == pytest.approx(4.0, abs=1e-6)
    assert _measured("bad_base_thin")["base"]["value"] == pytest.approx(3.5, abs=1e-6)


def test_skirt_depth_is_a_plane_pair_not_a_hull_subtraction(good):
    assert good["skirt"]["value"] == pytest.approx(5.5, abs=1e-6)
    assert _measured("bad_skirt_shallow")["skirt"]["value"] == pytest.approx(3.0, abs=1e-6)


def test_the_lid_opens_downward_and_the_same_rule_still_serves_it(good):
    """The opening plane is the annular extreme on the fitted axis, not "the top". The
    lid's opening faces down and its depth measures 5.5 all the same."""
    assert good["skirt"]["value"] > 0


# --- 4. body height, which an assembly box cannot answer -------------------------

def test_the_assembly_box_passes_the_broken_body_and_fails_the_correct_one():
    """The proxy, and it is worse than useless — it is backwards. A height check
    calibrated on "115 mm body" passes ``bad_body_short`` and fails ``good``."""
    good_z = validation.measure(_fixture("good"))["bbox_mm"]["z"]
    short_z = validation.measure(_fixture("bad_body_short"))["bbox_mm"]["z"]
    assert short_z == pytest.approx(115.0, abs=1e-3)
    assert good_z == pytest.approx(117.5, abs=1e-3), "the lid's top wall stands proud"


def test_part_extent_measures_the_body_alone(good):
    assert good["body_height"]["value"] == pytest.approx(115.0, abs=1e-6)
    assert _measured("bad_body_short")["body_height"]["value"] == pytest.approx(
        100.0, abs=1e-6)


# --- 5. interference, with a tolerance rather than an equality -------------------

def test_a_clearance_fit_has_no_interference(good):
    """Compared against the record's own error bound, never against 0.0. A curved,
    non-axis-aligned boolean returns numerical slivers, and an exact comparison would
    call every one of them a defect."""
    overlap = good["overlap"]
    assert overlap["value"] is not None
    assert overlap["value"] <= overlap["numeric_error_bound"]


def test_an_undersized_bore_produces_real_overlap():
    overlap = _measured("bad_interference")["overlap"]
    assert overlap["value"] > 10.0
    assert overlap["value"] > overlap["numeric_error_bound"] * 10


def test_a_displaced_lid_also_interferes():
    """0.5 mm of travel against 0.15 mm of clearance. Both broken-placement fixtures
    interfere, which is why interference alone cannot distinguish them — that is what
    ``axis_offset`` and ``angular_deviation`` are for."""
    assert _measured("bad_offset")["overlap"]["value"] > 10.0
    assert _measured("bad_tilted")["overlap"]["value"] > 10.0


def test_the_error_bound_scales_with_the_fuzzy_value(good):
    """``fuzzy_mm`` times the smaller participating surface area. It has to be reported,
    because "0 mm3" from a fuzzy boolean means "below this", not "exactly none"."""
    assert good["overlap"]["numeric_error_bound"] > 0


# --- 6. counting, and refusing ---------------------------------------------------

def test_the_jar_is_two_separate_bodies(good):
    assert good["bodies"]["value"] == 2
    assert good["bodies"]["unit"] == "count"


def test_an_unknown_part_key_is_unresolved_rather_than_absent():
    reqs = measure_spec.parse([{"measurement_id": "ghost", "kind": "part_extent",
                                "part_key": "name:handle", "axis": "z"}])
    rec = measure.run(_fixture("good"), reqs)[0]
    assert rec["resolution"]["resolved"] is False
    assert rec["value"] is None
    assert "name:handle" in rec["resolution"]["reason"]


def test_a_role_the_body_does_not_have_is_unresolved():
    """A plain box has no cylindrical face, so it has no primary axis and no role that
    depends on one. The measurement returns the resolver's own reason, unchanged."""
    part = _build({
        "schema_version": cadir.SCHEMA_VERSION,
        "name": "slab",
        "parameters": [],
        "operations": [{"op_id": "b1", "op": "box", "size": [20, 20, 20]}],
        "expected_solids": 1,
    })
    key = next(iter({pg.key for pg in targets.parts_of(part)}))
    reqs = measure_spec.parse([{"measurement_id": "wall", "kind": "local_thickness",
                                "a": {"part_key": key, "face_role": "outer_cylinder"},
                                "b": {"part_key": key, "face_role": "bore_cylinder"}}])
    rec = measure.run(part, reqs)[0]
    assert rec["resolution"]["resolved"] is False
    assert rec["value"] is None


def test_one_failing_handler_does_not_lose_the_others(monkeypatch):
    """A crash inside OCCT on a pathological body is exactly the case where the
    remaining measurements are still worth having."""
    def _boom(by_key, req):
        raise RuntimeError("kernel said no")

    monkeypatch.setitem(measure._HANDLERS, "part_count", _boom)
    out = measure.run(_fixture("good"), REQUESTS)
    by_id = {r["measurement_id"]: r for r in out}
    assert len(out) == len(REQUESTS)
    assert by_id["bodies"]["value"] is None
    assert "RuntimeError" in by_id["bodies"]["resolution"]["reason"]
    assert by_id["neck_wall"]["value"] == pytest.approx(2.5, abs=1e-6)


# --- 7. provenance and the record shape ------------------------------------------

def test_every_record_carries_its_method_and_source(good):
    for rec in good.values():
        assert rec["method"]
        assert rec["method_version"] == measure.METHOD_VERSION
        assert rec["source_hash"] == "h_good"
        assert rec["unit"] in ("mm", "deg", "mm3", "count")
        assert isinstance(rec["numeric_error_bound"], float)
        assert rec["target"] is not None


def test_a_record_is_json_safe(good):
    json.dumps(list(good.values()))


def test_no_measurements_means_no_work():
    assert measure.run(_fixture("good"), []) == []


# --- 8. the request grammar ------------------------------------------------------

def test_a_bare_object_is_not_a_measurement_list():
    with pytest.raises(ValueError):
        measure_spec.parse({"measurement_id": "x", "kind": "part_count"})


def test_duplicate_ids_are_refused():
    with pytest.raises(ValueError):
        measure_spec.parse([{"measurement_id": "a", "kind": "part_count"},
                            {"measurement_id": "a", "kind": "part_count"}])


def test_the_cap_is_admission_control_not_tidiness():
    over = [{"measurement_id": f"m{i}", "kind": "part_count"}
            for i in range(measure_spec.MAX_MEASUREMENTS + 1)]
    with pytest.raises(ValueError):
        measure_spec.parse(over)


def test_a_kind_gets_the_pair_shape_it_declares():
    # a face kind given axis refs
    with pytest.raises(ValueError):
        measure_spec.parse([{"measurement_id": "x", "kind": "plane_gap",
                             "a": {"part_key": BODY}, "b": {"part_key": LID}}])
    # part_extent without an axis
    with pytest.raises(ValueError):
        measure_spec.parse([{"measurement_id": "x", "kind": "part_extent",
                             "part_key": BODY}])
    # a part_key on a kind that takes faces
    with pytest.raises(ValueError):
        measure_spec.parse([{"measurement_id": "x", "kind": "part_count",
                             "part_key": BODY}])


def test_an_unknown_face_role_is_refused_by_name():
    with pytest.raises(ValueError):
        measure_spec.parse([{"measurement_id": "x", "kind": "local_thickness",
                             "a": {"part_key": BODY, "face_role": "the_shiny_bit"},
                             "b": {"part_key": BODY, "face_role": "bore_cylinder"}}])


def test_none_parses_to_nothing():
    assert measure_spec.parse(None) == []
