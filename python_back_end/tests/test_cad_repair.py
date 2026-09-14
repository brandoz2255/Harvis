"""What a repair round is told, and when it stops being worth running (HE-9).

Two things changed in this gate and both are here because both were previously
invisible. The prompt now carries where each number came from, not just the number —
a model that is told "the depth is 3.02 and should be 5.5" still has to guess which
operation produced the depth, and the target is the only thing in the record that
answers that. And the loop now stops on the evidence rather than on the count: a round
that measured exactly what the round before it measured has not repaired anything, and
the round after it will not either.

The module is loaded by file path, the same way :mod:`test_cad_conformance` loads its
subject — the functions under test are pure, and the alternative is a pure-logic test
that fails because asyncpg is not configured.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"
_PKG = "_t_owui"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [str(_HERE)]
    sys.modules[_PKG] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load("cad_generate")


# A measured check, in the shape `cad_conformance.grade` emits: the check's own fields,
# then everything `grade_one` carried across from the engine's measurement record.
def _measured(**over) -> dict:
    row = {
        "id": "cavity_depth",
        "kind": "cavity_depth",
        "requirement": "the lid skirt is 5.5 mm deep",
        "tolerance": {"kind": "symmetric", "nominal": 5.5, "plus": 0.1,
                      "minus": 0.1, "unit": "mm"},
        "target": {"a": {"part_key": "lid", "face_role": "opening_plane"},
                   "b": {"part_key": "lid", "face_role": "cavity_floor"}},
        "method": "plane_gap",
        "method_version": "1",
        "unit": "mm",
        "ok": False,
        "measured": 3.02,
        "detail": "measured 3.02 mm, wanted 5.5 mm ±0.1 (out by 2.48 mm)",
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# What the failing line says
# ---------------------------------------------------------------------------

def test_the_line_names_the_faces_the_number_came_from():
    line = gen.describe_failed_check(_measured())
    assert "measured 3.02 mm, wanted 5.5 mm ±0.1" in line
    assert "lid/opening_plane → lid/cavity_floor" in line
    assert "plane_gap/v1" in line


def test_a_clearance_line_says_which_basis_it_is_stated_on():
    """Radial and diametral are one fit and two numbers.

    A model told "0.3 mm" with no basis halves it or doubles it at random, and the
    part it returns is wrong in a way the next measurement cannot distinguish from
    the last one.
    """
    line = gen.describe_failed_check(_measured(
        id="fit_clearance", kind="fit_clearance", basis="diametral",
        requirement="0.3 mm clearance", measured=0.04,
        detail="measured 0.04 mm, wanted 0.3 mm ±0.05 (out by 0.21 mm)"))
    assert "stated diametral" in line


def test_a_part_axis_target_reads_as_the_part_and_the_axis():
    line = gen.describe_failed_check(_measured(
        id="part_height", kind="part_height", method="part_extent",
        target={"part_key": "jar_body", "axis": "z"},
        requirement="the body is 115 mm tall"))
    assert "jar_body, z axis" in line


def test_a_v1_check_reads_exactly_as_it_always_did():
    """The recovered checks measure a bounding box and name no target.

    They have to come out of this function unchanged rather than acquiring an empty
    bracket at the end of every line — the whole point of the addition is that it
    says something, and a line that says "()" says less than nothing.
    """
    line = gen.describe_failed_check({
        "requirement": "the part is 40 mm wide",
        "detail": "measured 38.0, expected 40.0"})
    assert line == "- the part is 40 mm wide: measured 38.0, expected 40.0"


def test_the_prompt_carries_every_failing_check_and_nothing_else():
    report = {"checks": [_measured(), _measured(id="ok_one", ok=True),
                         _measured(id="not_measured", ok=None)]}
    prompt = gen.build_conformance_prompt("a jar with a lid", {"name": "jar"}, report)
    assert "lid/opening_plane → lid/cavity_floor" in prompt
    assert "ok_one" not in prompt and "not_measured" not in prompt


def test_the_structural_and_gap_wordings_survive_the_richer_lines():
    """Both were established by measurement and are the reason this function branches.

    A count that came out wrong cannot be fixed by changing a number, so the
    minimal-edit instruction is withheld; a floating feature is the one structural
    failure a number does fix, so it gets the arithmetic and "change nothing else".
    Enriching the failing lines must not have disturbed either.
    """
    gap = gen.build_conformance_prompt("a brick", {}, {"checks": [{
        "id": "solid_count", "kind": "solid_count", "requirement": "one solid",
        "ok": False, "measured": 2, "expected": 1, "detail": "measured 2, expected 1"}]})
    assert "H/2 + h/2" in gap and "change nothing else" in gap

    missing = gen.build_conformance_prompt("a brick", {}, {"checks": [{
        "id": "subtract_op_count", "kind": "subtract_op_count",
        "requirement": "one hole", "ok": False, "measured": 0, "expected": 1,
        "detail": "measured 0, expected 1"}]})
    assert "a different number will not fix it" in missing
    assert "do not restructure" not in missing


# ---------------------------------------------------------------------------
# When the loop stops
# ---------------------------------------------------------------------------

def test_a_closer_reading_is_progress():
    before = {"checks": [_measured(measured=3.02)]}
    after = {"checks": [_measured(measured=4.9)]}
    assert gen.repair_made_progress(before, after) is True


def test_the_identical_reading_is_not():
    report = {"checks": [_measured()]}
    assert gen.repair_made_progress(report, {"checks": [_measured()]}) is False


def test_a_movement_smaller_than_the_rounding_is_not():
    """Readings are rounded to six decimals before they are graded."""
    before = {"checks": [_measured(measured=3.02)]}
    after = {"checks": [_measured(measured=3.0200001)]}
    assert gen.repair_made_progress(before, after) is False


def test_moving_further_away_is_not_progress():
    before = {"checks": [_measured(measured=5.0)]}
    after = {"checks": [_measured(measured=2.0)]}
    assert gen.repair_made_progress(before, after) is False


def test_a_check_that_now_passes_is_progress_whatever_the_numbers_did():
    before = {"checks": [_measured(), _measured(id="other", ok=False, measured=1.0,
                                                tolerance={"kind": "symmetric",
                                                           "nominal": 4.0, "plus": 0.1,
                                                           "minus": 0.1, "unit": "mm"})]}
    after = {"checks": [_measured(), _measured(id="other", ok=True, measured=4.0,
                                               tolerance={"kind": "symmetric",
                                                          "nominal": 4.0, "plus": 0.1,
                                                          "minus": 0.1, "unit": "mm"})]}
    assert gen.repair_made_progress(before, after) is True


def test_a_failed_check_that_became_unverified_is_not_progress():
    """The reading was lost, not corrected.

    Going from a number that is wrong to no number at all is how a document becomes
    unmeasurable, and treating that as encouragement is how a loop spends its whole
    budget going blind. It reaches this function at all only in the mixed case — if
    every failing check went unverified the status is no longer `failed` and the loop
    has already returned.
    """
    before = {"checks": [_measured()]}
    after = {"checks": [_measured(ok=None, measured=None,
                                  detail="not measured: the target was not found")]}
    assert gen.repair_made_progress(before, after) is False


def test_a_check_that_was_passing_and_now_fails_is_not_progress():
    """A regression is movement, but it is not repair."""
    before = {"checks": [_measured(ok=True, measured=5.5)]}
    after = {"checks": [_measured(ok=False, measured=3.02)]}
    assert gen.repair_made_progress(before, after) is False


def test_a_check_the_previous_round_never_had_is_not_progress():
    assert gen.repair_made_progress({"checks": []}, {"checks": [_measured()]}) is False


def test_a_flat_expected_pair_is_compared_the_same_way():
    """v1 checks carry `expected` rather than a typed tolerance."""
    a = {"checks": [{"id": "h", "ok": False, "expected": 40.0, "measured": 30.0}]}
    b = {"checks": [{"id": "h", "ok": False, "expected": 40.0, "measured": 38.0}]}
    assert gen.repair_made_progress(a, b) is True
    assert gen.repair_made_progress(b, a) is False
