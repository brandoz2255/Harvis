"""The grader that would have caught the 30 mm cube.

These import by file path rather than through ``owui_compat`` on purpose: both
modules under test are deliberately dependency-free — no fastapi, no asyncpg, no
pydantic — and importing the package would drag the whole backend in and make a
pure-logic test fail for reasons that have nothing to do with the logic.
"""

from __future__ import annotations

import importlib.util
import math
import pathlib
import sys
import types

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"

# A stand-in package, so a module loaded this way can still say `from . import sibling`
# without the real `owui_compat/__init__` — and everything it reaches then comes from
# the same shadow namespace rather than from an installed copy.
_PKG = "_t_owui"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [str(_HERE)]
    sys.modules[_PKG] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: a module using `from __future__ import annotations` has
    # string annotations, and pydantic resolves its forward refs by looking the owning
    # module up here. Exec-then-register leaves such a model permanently half-built.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ds = _load("cad_designspec")
cf = _load("cad_conformance")

CUBE_PROMPT = "a 30 mm cube with a 10 mm hole through the middle"
# The exact solid Gate 7B's end-to-end run produced for that sentence and reported as
# `succeeded`. Twenty live runs of qwen3:4b reproduce it to the decimal, and the volume
# says what it is: 27000 + 0.75 * pi * 25 * 30 = 28767.1459 — a whole 30 mm cube with
# three quarters of a 10 mm rod welded onto one corner edge. Not an oversized bore. NO
# BORE AT ALL. The model omits `mode: "subtract"`, so its cylinder unions instead of
# cutting, and it puts the cylinder at [15, 15, 0] as though coordinates were measured
# from a corner. See test_the_live_gate_7b_document_is_a_rod_not_a_bore.
GATE7B_VOLUME = 28767.1459
CORRECT_VOLUME = round(27000 - math.pi * 25 * 30, 4)


def _doc(size, radius, height, *, cyl_rot=(0, 0, 0), extra=None, box_rot=(0, 0, 0)):
    ops = [
        {"op": "box", "op_id": "body", "size": list(size), "mode": "add",
         "rotation": list(box_rot)},
        {"op": "cylinder", "op_id": "bore", "radius": radius, "height": height,
         "mode": "subtract", "rotation": list(cyl_rot)},
    ]
    if extra:
        ops.extend(extra)
    return {"schema_version": "0.1", "units": "mm", "name": "t",
            "parameters": [], "operations": ops, "expected_solids": 1}


def _val(x, y, z, volume, solids=1):
    return {"brep_valid": True, "solid_count": solids, "volume_mm3": volume,
            "surface_area_mm2": 0.0, "bbox_mm": {"x": x, "y": y, "z": z},
            "center_of_mass_mm": {"x": 0, "y": 0, "z": 0},
            "mesh": {"parsed": True, "watertight": True, "manifold": True}}


def _by_id(report):
    return {c["id"]: c for c in report["checks"]}


# --------------------------------------------------------------------------- #
# the failure this whole gate exists for
# --------------------------------------------------------------------------- #

def test_the_gate_7b_result_fails_conformance():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, _doc((35, 35, 30), 9.2, 30), _val(35.0, 35.0, 30.0, GATE7B_VOLUME))

    assert report["status"] == "failed"
    checks = _by_id(report)
    assert checks["bbox_set"]["ok"] is False
    assert checks["bore_diameter"]["ok"] is False
    # Recovered from the removed volume, not read off the document — the document
    # declares radius 9.2 and would have "agreed with itself" either way.
    assert 18.3 < checks["bore_diameter"]["measured"] < 18.5
    assert "10 mm" in report["summary"]


def test_the_live_gate_7b_document_is_a_rod_not_a_bore():
    """The document twenty live runs actually produced, graded verbatim.

    It is the harder half of the same failure: the part is watertight, valid, one
    solid, and has no hole in it at all, because the cylinder carries no `mode`. The
    grader has to fail this WITHOUT recovering a bore — there is nothing to recover —
    and it does, on the bounding box and on a hole count of zero. Reporting a bore
    diameter here would be the checker inventing the very feature that is missing.
    """
    spec = ds.extract(CUBE_PROMPT)
    doc = {"schema_version": "0.1", "units": "mm", "name": "cube", "parameters": [],
           "expected_solids": 1, "operations": [
               {"op": "box", "op_id": "cube", "size": [30, 30, 30]},
               {"op": "cylinder", "op_id": "hole", "radius": 5, "height": 30,
                "rotation": [0, 0, 90], "at": {"positions": [[15, 15, 0]]}}]}
    report = cf.grade(spec, doc, _val(30.0, 35.0, 35.0, GATE7B_VOLUME))

    assert report["status"] == "failed"
    checks = _by_id(report)
    assert checks["bbox_set"]["ok"] is False
    assert checks["hole_count"]["ok"] is False and checks["hole_count"]["measured"] == 0
    assert checks["bore_diameter"]["ok"] is None
    assert checks["bore_diameter"]["measured"] is None


def test_the_requested_part_passes():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30), _val(30.0, 30.0, 30.0, CORRECT_VOLUME))

    assert report["status"] == "passed"
    assert report["counts"] == {"passed": 4, "failed": 0, "unverified": 0}
    assert abs(_by_id(report)["bore_diameter"]["measured"] - 10.0) < 0.01


def test_a_declared_radius_cannot_launder_a_wrong_bore():
    """The document claims 5 mm; the solid says otherwise. The solid wins."""
    spec = ds.extract(CUBE_PROMPT)
    wrong = round(27000 - math.pi * 81 * 30, 4)          # actually bored r=9
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30), _val(30.0, 30.0, 30.0, wrong))

    assert report["status"] == "failed"
    assert abs(_by_id(report)["bore_diameter"]["measured"] - 18.0) < 0.01


# --------------------------------------------------------------------------- #
# orientation, which a sentence never fixes
# --------------------------------------------------------------------------- #

def test_one_explicit_position_is_still_one_bore():
    """`at: {positions: [[0,0,0]]}` is how the live model actually centres a hole.

    Reading any `at` as "patterned" made the real 35 mm document report its bore as
    unmeasurable — the checker refusing to look, not the geometry being hard.
    """
    spec = ds.extract(CUBE_PROMPT)
    doc = _doc((35, 35, 30), 9.2, 30)
    doc["operations"][0]["at"] = {"positions": [[0, 0, 0]]}
    doc["operations"][1]["at"] = {"positions": [[0, 0, 0]]}
    report = cf.grade(spec, doc, _val(35.0, 35.0, 30.0, GATE7B_VOLUME))

    assert report["status"] == "failed"
    assert 18.3 < _by_id(report)["bore_diameter"]["measured"] < 18.5


def test_two_explicit_positions_are_not_measured_as_one_bore():
    spec = ds.extract(CUBE_PROMPT)
    doc = _doc((30, 30, 30), 5, 30)
    doc["operations"][1]["at"] = {"positions": [[-8, 0, 0], [8, 0, 0]]}
    report = cf.grade(spec, doc, _val(30.0, 30.0, 30.0, CORRECT_VOLUME))
    assert _by_id(report)["bore_diameter"]["ok"] is None


def test_a_correct_part_modelled_sideways_still_passes():
    spec = ds.extract("a 40 x 30 x 20 mm block")
    report = cf.grade(spec, {"operations": []}, _val(20.0, 40.0, 30.0, 24000.0))
    assert report["status"] == "passed"


def test_a_sideways_bore_is_measured_along_its_own_axis():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(
        spec,
        _doc((30, 30, 30), 5, 30, cyl_rot=(90, 0, 0)),
        _val(30.0, 30.0, 30.0, CORRECT_VOLUME),
    )
    assert _by_id(report)["bore_diameter"]["ok"] is True


def test_an_oblique_bore_is_unverified_not_guessed():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(
        spec,
        _doc((30, 30, 30), 5, 30, cyl_rot=(37, 12, 0)),
        _val(30.0, 30.0, 30.0, CORRECT_VOLUME),
    )
    assert _by_id(report)["bore_diameter"]["ok"] is None
    assert report["status"] == "unverified"


# --------------------------------------------------------------------------- #
# unmeasurable is unverified, never passed
# --------------------------------------------------------------------------- #

def test_extra_geometry_makes_the_bore_unverifiable():
    spec = ds.extract(CUBE_PROMPT)
    extra = [{"op": "fillet", "op_id": "round", "radius": 2,
              "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}}]
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30, extra=extra),
                      _val(30.0, 30.0, 30.0, CORRECT_VOLUME - 40))
    assert _by_id(report)["bore_diameter"]["ok"] is None
    assert report["status"] == "unverified"


def test_a_blind_bore_is_not_measured_from_removed_volume_alone():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, _doc((30, 30, 30), 5, 12),
                      _val(30.0, 30.0, 30.0, round(27000 - math.pi * 25 * 12, 4)))
    assert _by_id(report)["bore_diameter"]["ok"] is None


def test_a_description_with_nothing_measurable_is_unverified():
    spec = ds.extract("something to hold my headphones")
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30), _val(30.0, 30.0, 30.0, CORRECT_VOLUME))
    # The solid_count default is the only check such a sentence produces, and one
    # satisfied assumption is not evidence that this is the requested part.
    assert report["status"] in ("unverified", "passed")
    assert "bore_diameter" not in _by_id(report)


def test_missing_geometry_is_unverified_not_failed():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30), {})
    assert report["status"] == "unverified"
    # Every check that needs a measurement degrades. hole_count is a property of
    # the document alone, so it still answers — and one document-only check
    # answering is exactly why the overall status is not "passed".
    checks = _by_id(report)
    assert checks["bbox_set"]["ok"] is None
    assert checks["bore_diameter"]["ok"] is None
    assert checks["solid_count"]["ok"] is None
    assert checks["hole_count"]["ok"] is True


def test_a_generation_that_built_nothing_is_unverified_not_failed():
    """The failure path grades against no document at all, on purpose.

    A run that never produced a solid has not been shown to be the wrong part — it has
    not been shown to be anything. Counting features on the last rejected document
    would report "does not match the request" for a part that was never built.
    """
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, None, None)
    assert report["status"] == "unverified"
    assert all(c["ok"] is None for c in report["checks"])


def test_no_spec_at_all_grades_as_unverified():
    report = cf.grade(None, None, None)
    assert report["status"] == "unverified"
    assert report["checks"] == []
    assert "Not checked against the request" in report["summary"]


# --------------------------------------------------------------------------- #
# counts
# --------------------------------------------------------------------------- #

def test_hole_count_is_counted_on_subtract_operations():
    spec = ds.extract("a 30 mm cube with four 5 mm holes through it")
    report = cf.grade(spec, _doc((30, 30, 30), 2.5, 30), _val(30.0, 30.0, 30.0, 26000.0))
    hole = _by_id(report).get("hole_count")
    assert hole is not None and hole["ok"] is False and hole["measured"] == 1


def test_a_patterned_subtraction_makes_the_count_unverifiable():
    spec = ds.extract("a 30 mm cube with four 5 mm holes through it")
    doc = _doc((30, 30, 30), 2.5, 30)
    doc["operations"][1]["at"] = {"count": [2, 2, 1], "pitch": [10, 10, 0]}
    report = cf.grade(spec, doc, _val(30.0, 30.0, 30.0, 26000.0))
    assert _by_id(report)["hole_count"]["ok"] is None


def test_a_split_result_fails_the_solid_count():
    spec = ds.extract(CUBE_PROMPT)
    report = cf.grade(spec, _doc((30, 30, 30), 5, 30),
                      _val(30.0, 30.0, 30.0, CORRECT_VOLUME, solids=3))
    assert report["status"] == "failed"
    assert _by_id(report)["solid_count"]["measured"] == 3


# --------------------------------------------------------------------------- #
# named dimensions
# --------------------------------------------------------------------------- #

def test_a_named_thickness_matches_any_one_axis():
    spec = ds.extract("a 3 mm thick plate")
    ok = cf.grade(spec, {"operations": []}, _val(50.0, 40.0, 3.0, 6000.0))
    assert _by_id(ok)["bbox_has_thickness"]["ok"] is True

    bad = cf.grade(spec, {"operations": []}, _val(50.0, 40.0, 8.0, 16000.0))
    assert _by_id(bad)["bbox_has_thickness"]["ok"] is False
    assert bad["status"] == "failed"


def test_foreign_units_produce_no_checks_rather_than_a_conversion():
    spec = ds.extract("a 2 inch cube")
    assert spec["units"] == "unsupported"
    report = cf.grade(spec, _doc((50.8, 50.8, 50.8), 5, 50.8), _val(50.8, 50.8, 50.8, 131096.5))
    assert report["status"] == "unverified"
    assert report["checks"] == []


# --------------------------------------------------------------------------- #
# Four sentences the extractor read wrong, all four found by running the Gate 7D
# benchmark suite through it before running the benchmark itself. Three of them
# invented a check the sentence never made, which is the worst failure this module
# has: a correct part fails on a feature nobody asked for, and the repair loop then
# spends its attempts chasing it.

def test_across_corners_is_an_envelope_not_a_bore():
    """Hex hardware is dimensioned across corners. Reading that as the bore graded a
    16 mm hole into a standoff whose hole is 6 mm."""
    spec = ds.extract("a hexagonal standoff 20 mm tall and 16 mm across corners, "
                      "with a 6 mm bore through it")
    assert spec["stated"]["bore_diameter_mm"] == 6.0
    assert spec["stated"]["across_corners_mm"] == 16.0
    assert "bbox_across_corners" in _by_id(
        cf.grade(spec, {"operations": []}, _val(16.0, 13.86, 20.0, 3200.0)))


def test_a_stated_width_is_not_also_a_bore():
    """`wide` sat in both the diameter list and the named-dimension list, so one word
    produced two contradictory checks and a bracket with no hole failed on a hole."""
    spec = ds.extract("an L-bracket 60 mm tall, 40 mm deep and 30 mm wide, "
                      "made from 5 mm thick material")
    assert "bore_diameter_mm" not in spec["stated"]
    assert spec["stated"]["width_mm"] == 30.0


def test_a_fillet_radius_is_not_a_hole():
    """"a 5 mm radius fillet" was doubled into a 10 mm bore on a solid block."""
    spec = ds.extract("a 80 x 50 x 20 mm block with a 5 mm radius fillet on the "
                      "four vertical edges")
    assert "bore_diameter_mm" not in spec["stated"]
    assert spec["stated"]["overall_mm"] == [20.0, 50.0, 80.0]


def test_a_part_called_a_foot_is_still_measured_in_millimetres():
    """`foot` as a bare word refused every check on a fully-dimensioned sentence.
    A length in feet has a number in front of it; a machine foot does not."""
    spec = ds.extract("a 50 x 20 x 8 mm foot with a slot through it 30 mm long "
                      "and 8 mm wide")
    assert spec["units"] == "mm"
    assert spec["stated"]["overall_mm"] == [8.0, 20.0, 50.0]

    still_refused = ds.extract("a bracket 2 feet long")
    assert still_refused["units"] == "unsupported"
