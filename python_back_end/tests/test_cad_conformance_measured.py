"""Checks that can finally say `failed` and name the number (HE-5).

Every test here exists because the old grader could not have caught the thing it
describes. Before this gate a jar produced `unverified` whatever its dimensions were,
which reads in the UI as "fine, nothing to report" and gives a repair round nothing
to act on. The point of the gate is that a wrong part now fails *with the number*,
and — just as load-bearing — that a part nobody could measure still does not.

Loaded by file path for the same reason as :mod:`test_cad_conformance`: both modules
under test are free of fastapi, asyncpg and pydantic, and importing the package would
make a pure-logic test fail for reasons that have nothing to do with the logic.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

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


ds = _load("cad_designspec")
ev = _load("cad_evidence")
v2 = _load("cad_designspec_v2")
cf = _load("cad_conformance")

# Reached through `cf`, never loaded again. A second `_load` would build a second module
# object under the same `sys.modules` name, and the grader would keep calling the first
# one — so a monkeypatch here would silently patch nothing.
me = cf.measured

JAR = ("a jar with a removable lid - body 115 mm tall, 2.5 mm neck wall, 4 mm base; "
       "the lid is a separate part with a hollow skirt 5.5 mm deep, concentric with "
       "the neck, 0.3 mm clearance.")

# The assembly the plan's `bad_body_short` fixture builds: a 100 mm body under a 15 mm
# lid. Its bounding box is 115 mm — the number the sentence asked for — which is the
# whole reason a part-scoped height check had to exist.
REV = "11111111-1111-1111-1111-111111111111"
BUILD = "22222222-2222-2222-2222-222222222222"

SHORT_BODY_VALIDATION = {"brep_valid": True, "solid_count": 2, "volume_mm3": 1000.0,
                         "bbox_mm": {"x": 40.0, "y": 40.0, "z": 115.0}}


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv(v2.FLAG, "1")


def _m(mid, value, *, kind="plane_gap", unit="mm", resolved=True, basis=None,
       error=0.0, diametral=None, reason=None, candidates=1):
    """One engine measurement, in the shape `cad_evidence.stamp` stores."""
    out = {
        "measurement_id": mid, "kind": kind, "unit": unit, "value": value,
        "target": {"part_key": "name:jar_body"},
        "resolution": {"resolved": resolved, "candidates_considered": candidates,
                       "method": "coaxial_cylinder_fit/v1", "reason": reason},
        "diagnostic": {},
        "method": "plane_pair_axis_projection", "method_version": "v1",
        "numeric_error_bound": error,
    }
    if basis:
        out["basis"] = basis
    if diametral is not None:
        out["diametral_mm"] = diametral
    return out


def _good_jar_measurements():
    """The nine numbers a correct jar produces, one per check the sentence states."""
    return [
        _m("part_height", 115.0, kind="part_extent"),
        _m("base_thickness", 4.0),
        _m("wall_thickness", 2.5, kind="local_thickness", basis="radial"),
        _m("cavity_depth", 5.5),
        _m("fit_clearance", 0.15, kind="radial_clearance", basis="radial",
           diametral=0.3),
        _m("axis_offset", 0.0, kind="axis_offset"),
        _m("angular_deviation", 0.0, kind="angular_deviation", unit="deg"),
        _m("part_count", 2, kind="part_count", unit="count"),
        _m("interference_volume", 0.0, kind="interference_volume", unit="mm3"),
    ]


def _graded(measurements, spec=None, validation=None):
    return cf.grade(spec or ds.extract(JAR), None, validation or {}, measurements)


def _by_id(result):
    return {c["id"]: c for c in result["checks"]}


# --------------------------------------------------------------------------- #
# 1. the verdict a correct jar was never able to earn
# --------------------------------------------------------------------------- #

def test_a_correct_jar_passes_every_check(on):
    result = _graded(_good_jar_measurements())
    assert result["status"] == "passed"
    assert result["counts"] == {"passed": 9, "failed": 0, "unverified": 0}


def test_a_shallow_skirt_fails_and_says_by_how_much(on):
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "cavity_depth"]
    ms.append(_m("cavity_depth", 3.02))
    result = _graded(ms)
    assert result["status"] == "failed"
    bad = _by_id(result)["cavity_depth"]
    assert bad["ok"] is False and bad["measured"] == 3.02
    assert "3.02" in bad["detail"] and "5.5" in bad["detail"]
    # The summary is what the card shows without expanding anything, so the number
    # has to survive into it — "does not match the request" alone is the old verdict
    # with a new word on it.
    assert "3.02" in result["summary"]


def test_a_short_body_fails_while_the_assembly_bounding_box_is_still_right(on):
    """The defect the whole part-scoped height check exists for.

    100 mm body + 15 mm lid measures 115 mm as an assembly — exactly what was asked
    for — so every envelope check passes and the part is still wrong.
    """
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "part_height"]
    ms.append(_m("part_height", 100.0, kind="part_extent"))
    result = _graded(ms, validation=SHORT_BODY_VALIDATION)
    assert result["status"] == "failed"
    assert SHORT_BODY_VALIDATION["bbox_mm"]["z"] == 115.0
    assert _by_id(result)["part_height"]["measured"] == 100.0


# --------------------------------------------------------------------------- #
# 2. what it refuses to call wrong
# --------------------------------------------------------------------------- #

def test_a_check_with_no_measurement_is_unverified_not_failed(on):
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "wall_thickness"]
    result = _graded(ms)
    assert result["status"] == "unverified"
    got = _by_id(result)["wall_thickness"]
    assert got["ok"] is None and got["measured"] is None


def test_an_unresolved_target_is_unverified_and_says_why(on):
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "cavity_depth"]
    ms.append(_m("cavity_depth", None, resolved=False, candidates=2,
                 reason="two faces read as the cavity floor"))
    got = _by_id(_graded(ms))["cavity_depth"]
    assert got["ok"] is None
    assert "two faces" in got["detail"] and "2 candidate" in got["detail"]


def test_a_reading_inside_the_kernels_own_precision_cannot_be_failed(on):
    """A miss smaller than OCCT's tolerance on the faces involved is not a defect.

    Calling it `failed` would send a repair round chasing rounding, which is how a
    bounded repair budget gets spent on nothing.
    """
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "base_thickness"]
    ms.append(_m("base_thickness", 4.2, error=0.5))
    got = _by_id(_graded(ms))["base_thickness"]
    assert got["ok"] is None
    assert "precision" in got["detail"]


def test_numerical_error_does_not_rescue_a_genuinely_wrong_number(on):
    """The same escape hatch, on a part that really is wrong. 3.02 against 5.5 is
    2.48 out; no plausible face tolerance covers that."""
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "cavity_depth"]
    ms.append(_m("cavity_depth", 3.02, error=0.5))
    assert _by_id(_graded(ms))["cavity_depth"]["ok"] is False


def test_one_unmeasured_check_keeps_the_whole_build_off_passed(on):
    """Eight right answers and one unknown is not a pass. The invariant predates
    this gate and the new checks must not be the thing that breaks it."""
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "part_count"]
    result = _graded(ms)
    assert result["counts"]["passed"] == 8
    assert result["status"] == "unverified"


def test_a_grader_crash_is_unverified_not_a_failed_part(on, monkeypatch):
    def boom(check, index):
        raise RuntimeError("grader bug")
    monkeypatch.setattr(me, "grade_one", boom)
    result = _graded(_good_jar_measurements())
    assert result["status"] == "unverified"
    assert all(c["ok"] is None for c in result["checks"])


# --------------------------------------------------------------------------- #
# 3. radial is not diametral
# --------------------------------------------------------------------------- #

def test_a_diametral_requirement_is_graded_against_the_diametral_reading(on):
    """0.3 mm clearance stated on the diameter is 0.15 on the radius. Grading the
    radial number against the stated one would fail a perfectly-fitting lid."""
    result = _graded(_good_jar_measurements())
    fit = _by_id(result)["fit_clearance"]
    assert fit["ok"] is True and fit["measured"] == 0.3
    assert fit["basis"] == "diametral"


def test_a_radial_only_measurement_is_unverified_rather_than_halved(on):
    """The grader does not convert. Two places in the stack already decide what
    "0.3 mm clearance" means; a third would eventually disagree with both."""
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "fit_clearance"]
    ms.append(_m("fit_clearance", 0.15, kind="radial_clearance", basis="radial"))
    got = _by_id(_graded(ms))["fit_clearance"]
    assert got["ok"] is None
    assert "diameter" in got["detail"]


def test_a_wrong_fit_fails_on_the_diametral_number(on):
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "fit_clearance"]
    ms.append(_m("fit_clearance", 0.6, kind="radial_clearance", basis="radial",
                 diametral=1.2))
    got = _by_id(_graded(ms))["fit_clearance"]
    assert got["ok"] is False and got["measured"] == 1.2


# --------------------------------------------------------------------------- #
# 4. one-sided bands stay one-sided
# --------------------------------------------------------------------------- #

def test_zero_interference_passes_a_max_only_band(on):
    assert _by_id(_graded(_good_jar_measurements()))["interference_volume"]["ok"] is True


def test_a_sliver_of_boolean_noise_passes_and_a_real_overlap_does_not(on):
    base = [m for m in _good_jar_measurements()
            if m["measurement_id"] != "interference_volume"]
    noise = _graded(base + [_m("interference_volume", 0.005, kind="interference_volume",
                               unit="mm3")])
    real = _graded(base + [_m("interference_volume", 500.0, kind="interference_volume",
                              unit="mm3")])
    assert _by_id(noise)["interference_volume"]["ok"] is True
    assert _by_id(real)["interference_volume"]["ok"] is False


def test_a_third_body_does_not_fail_a_check_that_asked_for_at_least_two(on):
    """`min_only` is genuinely one-sided. A jar that came out as body, lid and a
    stray sliver has a problem, but it is not "too many parts" — and grading it
    against a symmetric band would report the wrong one."""
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "part_count"]
    ms.append(_m("part_count", 3, kind="part_count", unit="count"))
    assert _by_id(_graded(ms))["part_count"]["ok"] is True


# --------------------------------------------------------------------------- #
# 5. what the card can now show
# --------------------------------------------------------------------------- #

def test_a_graded_check_carries_its_typed_half(on):
    got = _by_id(_graded(_good_jar_measurements()))["cavity_depth"]
    assert got["tolerance"]["kind"] == "symmetric"
    assert got["comparator"] == "eq"
    assert got["measurement_id"] == "cavity_depth"
    assert got["target"]["part_key"] == "name:jar_body"
    assert got["method_version"] == "v1"
    assert got["numeric_error_bound"] == 0.0


def test_the_internal_measurement_plan_never_reaches_the_output(on):
    """`measure` is the role-based request the binder consumes — "the lid's bore
    against the body's outer wall". What the card must show is the *resolved*
    target; shipping both invites the UI to read the one that was never bound."""
    for check in _graded(_good_jar_measurements())["checks"]:
        assert "measure" not in check


def test_stated_but_unmeasurable_does_not_report_as_nothing_stated(on):
    """The badge defect this gate fixes. Nine requirements were read off the
    sentence; "nothing checkable was stated" is a different claim and a false one."""
    result = _graded([])
    assert result["status"] == "unverified"
    assert result["counts"]["unverified"] == 9
    assert "None of the stated requirements could be measured" in result["summary"]


# --------------------------------------------------------------------------- #
# 6. the split modules cannot drift apart
# --------------------------------------------------------------------------- #

def test_the_two_modules_agree_on_the_helpers_they_both_restate():
    assert cf._EPS == me._EPS
    for v in (0.0, 1, -2.5, True, "3", None, float("inf")):
        assert cf._num(v) == me._num(v)


def test_a_v1_spec_grades_exactly_as_it_did_before(on):
    """The flag is on and the sentence states nothing v2 can read, so the result has
    to be byte-identical to the pre-HE-5 one — including with `measurements` passed."""
    spec = ds.extract("a 30 mm cube with a 10 mm hole through the middle")
    doc = {"schema_version": "0.1", "units": "mm", "name": "t", "parameters": [],
           "expected_solids": 1, "operations": [
               {"op": "box", "op_id": "b", "size": [30, 30, 30], "mode": "add"},
               {"op": "cylinder", "op_id": "c", "radius": 5, "height": 30,
                "mode": "subtract"}]}
    val = {"brep_valid": True, "solid_count": 1, "volume_mm3": 27000 - 3.141592653589793 * 25 * 30,
           "bbox_mm": {"x": 30.0, "y": 30.0, "z": 30.0}}
    assert cf.grade(spec, doc, val) == cf.grade(spec, doc, val, _good_jar_measurements())


# --------------------------------------------------------------------------- #
# 7. the path production actually takes
# --------------------------------------------------------------------------- #

def test_the_good_jar_survives_the_evidence_contract_and_still_passes(on):
    """Everything above hands the grader dicts directly. This one goes the way
    `cad_router._run_build` goes — engine payload → `parse` → `stamp` → `grade` — so
    a shape the grader is happy with but the contract rejects shows up as a failing
    test rather than as nine silent `unverified`s in the running app.
    """
    parsed = ev.parse(_good_jar_measurements())
    assert len(parsed) == 9, "the evidence contract dropped a record the grader expects"
    stamped = ev.stamp(parsed, revision_id=REV, build_id=BUILD)
    result = cf.grade(ds.extract(JAR), None, {}, stamped)
    assert result["status"] == "passed"
    assert _by_id(result)["fit_clearance"]["measured"] == 0.3


def test_a_shallow_skirt_still_fails_after_the_round_trip(on):
    ms = [m for m in _good_jar_measurements() if m["measurement_id"] != "cavity_depth"]
    ms.append(_m("cavity_depth", 3.02))
    stamped = ev.stamp(ev.parse(ms), revision_id=REV, build_id=BUILD)
    result = cf.grade(ds.extract(JAR), None, {}, stamped)
    assert result["status"] == "failed"
    assert _by_id(result)["cavity_depth"]["measured"] == 3.02


def test_the_contract_rejects_a_value_with_no_resolution_behind_it(on):
    """The shape a plausible wrong answer takes. It must die at `parse`, which is why
    grading was moved after it — not be caught by the grader's own good manners."""
    rogue = dict(_m("cavity_depth", 5.5))
    rogue["resolution"] = dict(rogue["resolution"], resolved=False)
    assert ev.parse([rogue]) == []
    # and the good records beside it are not punished for it
    assert len(ev.parse([rogue] + _good_jar_measurements())) == 9
