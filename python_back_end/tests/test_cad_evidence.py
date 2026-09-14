"""The rules that keep a measurement from lying (HE-3).

Loaded by file path for the same reason ``test_cad_conformance`` is: the module under
test depends on pydantic and nothing else, and importing ``owui_compat`` would drag
fastapi and asyncpg in so a pure-schema test could fail for reasons unrelated to the
schema.

What is actually being defended here is one distinction that the rest of the tranche
rests on: **absent is not zero, and unresolved is not wrong.** Every test below is a
way that distinction could be lost in transit.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec, unlike the sibling conformance test's loader. The module
    # uses `from __future__ import annotations`, so every annotation is a string and
    # pydantic resolves them by looking its own module up in `sys.modules` — a module
    # that is executed but never registered leaves `Measurement` permanently
    # half-built. The real import path (`from . import cad_evidence`) never hits this.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ev = _load("cad_evidence")

# The shape the engine actually emits, copied from a live `/cad/v2/build` response for
# the `good` jar fixture rather than invented. A hand-written stand-in would drift from
# the wire format and this whole file would then be testing itself.
GOOD_FIT = {
    "measurement_id": "fit",
    "kind": "radial_clearance",
    "target": {"a": {"part_key": "name:lid", "face_role": "bore_cylinder"},
               "b": {"part_key": "name:jar_body", "face_role": "outer_cylinder"}},
    "resolution": {"resolved": True, "candidates_considered": 1,
                   "method": "coaxial_radius_difference", "method_version": "1",
                   "reason": None},
    "value": 0.15,
    "unit": "mm",
    "basis": "radial",
    "method": "coaxial_radius_difference",
    "method_version": "1",
    "numeric_error_bound": 2e-07,
    "diagnostic": {},
    "diametral_mm": 0.3,
    "source_hash": "h_good",
}


# The resolver stamps its own version inside `resolution`, separate from the
# measurement method's version outside it. This fixture went a whole tranche without
# it, and because `parse` drops a malformed entry silently, the mismatch cost *every*
# measurement on *every* build while conformance reported the honest-looking
# `unverified`. The two tests below pin both halves so it cannot happen again.

def test_the_resolver_version_the_engine_stamps_is_part_of_the_contract():
    """`cad-engine/targets.py` writes `resolution.method_version` on every record. The
    model forbids extra keys, so a field it does not declare is not ignored — it drops
    the measurement. This asserts the declared side matches what the engine sends."""
    [m] = ev.parse([GOOD_FIT])
    assert m.resolution.method_version == "1"


def test_a_build_from_an_engine_older_than_the_resolver_still_parses():
    """The reason it is defaulted rather than required: a build made before HE-1 has no
    resolver version, and an absent one must read as unknown rather than cost the
    measurement beside it."""
    old = dict(GOOD_FIT)
    old["resolution"] = {k: v for k, v in GOOD_FIT["resolution"].items()
                         if k != "method_version"}
    [m] = ev.parse([old])
    assert m.value == 0.15
    assert m.resolution.method_version == "0"


def _rec(**over):
    d = dict(GOOD_FIT)
    d.update(over)
    return d


# ---------------------------------------------------------------------------
# 1. absent is not zero
# ---------------------------------------------------------------------------

def test_an_unmeasured_value_survives_the_round_trip_as_none():
    """The single most damaging coercion available. Zero interference is a *good*
    result; unknown interference is no result. If the schema defaulted `value` to 0.0
    a build the engine could not measure would grade as a perfect fit."""
    raw = _rec(measurement_id="overlap", kind="interference_volume", unit="mm3",
               value=None, basis=None, diametral_mm=None,
               resolution={"resolved": False, "candidates_considered": 0,
                           "method": "fuzzy_boolean_common",
                           "reason": "no body is keyed 'name:lid' in this build"})
    [m] = ev.parse([raw])
    assert m.value is None
    assert m.resolution.resolved is False
    assert "name:lid" in m.resolution.reason


def test_a_value_on_an_unresolved_target_is_refused_outright():
    """A number with no resolution behind it is exactly the shape a plausible wrong
    answer takes, so the model refuses to hold one at all — and `parse` drops it
    rather than letting it through as evidence."""
    bad = _rec(resolution={"resolved": False, "candidates_considered": 2,
                           "method": "coaxial_radius_difference",
                           "reason": "ambiguous"})
    with pytest.raises(Exception):
        ev.Measurement.model_validate(bad)
    assert ev.parse([bad]) == []


def test_no_measurements_and_an_empty_list_both_mean_nothing_was_measured():
    """Every build made before this gate is in this state. It is not an error."""
    assert ev.parse(None) == []
    assert ev.parse([]) == []


def test_a_non_list_is_an_error_not_an_empty_answer():
    """Silently reading a malformed payload as "measured nothing" would hide a real
    engine or transport fault behind a verdict of `unverified`."""
    with pytest.raises(ValueError):
        ev.parse({"fit": GOOD_FIT})


# ---------------------------------------------------------------------------
# 2. one bad record must not cost the good ones
# ---------------------------------------------------------------------------

def test_a_malformed_entry_drops_itself_and_nothing_else():
    got = ev.parse([GOOD_FIT, {"nonsense": True}, "not a dict",
                    _rec(measurement_id="wall", value=2.5, diametral_mm=None)])
    assert [m.measurement_id for m in got] == ["fit", "wall"]


def test_a_duplicate_id_is_dropped_because_which_number_failed_must_be_answerable():
    got = ev.parse([GOOD_FIT, _rec(value=9.9)])
    assert len(got) == 1
    assert got[0].value == 0.15


def test_the_cap_bounds_what_one_build_can_persist():
    many = [_rec(measurement_id=f"m{i}") for i in range(ev.MAX_MEASUREMENTS + 25)]
    assert len(ev.parse(many)) == ev.MAX_MEASUREMENTS


def test_an_unknown_field_from_a_newer_engine_drops_the_record_not_the_build():
    """`extra="forbid"` means a field this backend has never heard of makes the record
    unreadable. That is the intended direction — an unrecognised key could be carrying
    the basis or the tolerance, and grading around it would be guessing."""
    assert ev.parse([_rec(some_future_field=1)]) == []


# ---------------------------------------------------------------------------
# 3. a number is only as good as its basis and its units
# ---------------------------------------------------------------------------

def test_a_clearance_carries_both_readings_because_speech_does_not_say_which():
    [m] = ev.parse([GOOD_FIT])
    assert (m.value, m.diametral_mm) == (0.15, 0.3)
    assert m.basis == "radial"


def test_a_thickness_carries_no_diametral_reading():
    """Doubling a 2.5 mm wall gives 5.0 mm of nothing. The second number appears only
    where it means something, so a grader cannot pick the wrong one."""
    [m] = ev.parse([_rec(measurement_id="wall", kind="local_thickness", value=2.5,
                         diametral_mm=None)])
    assert m.diametral_mm is None


def test_an_unknown_unit_is_refused():
    assert ev.parse([_rec(unit="inch")]) == []


def test_infinities_and_nans_never_enter_the_store():
    assert ev.parse([_rec(value=float("inf"))]) == []
    assert ev.parse([_rec(value=float("nan"))]) == []
    assert ev.parse([_rec(numeric_error_bound=float("nan"))]) == []


def test_a_negative_error_bound_is_refused():
    """An error bound is a magnitude. A negative one would make
    `within_numerical_error` narrower than exact, quietly re-enabling the `failed`
    verdict it exists to suppress."""
    assert ev.parse([_rec(numeric_error_bound=-1e-6)]) == []


# ---------------------------------------------------------------------------
# 4. within numerical error is unverified, never failed
# ---------------------------------------------------------------------------

def test_a_reading_inside_the_kernel_error_band_is_not_a_defect():
    [m] = ev.parse([_rec(value=0.15 + 1e-8, numeric_error_bound=2e-07)])
    assert m.within_numerical_error(0.15) is True


def test_a_reading_outside_the_band_is_distinguishable_from_correct():
    [m] = ev.parse([_rec(value=0.05)])
    assert m.within_numerical_error(0.15) is False


def test_an_unmeasured_value_is_not_within_error_of_anything():
    """Otherwise "we could not measure it" would pass every tolerance ever written."""
    [m] = ev.parse([_rec(value=None,
                         resolution={"resolved": False, "candidates_considered": 0,
                                     "method": "coaxial_radius_difference",
                                     "reason": "not coaxial"})])
    assert m.within_numerical_error(0.15) is False


# ---------------------------------------------------------------------------
# 5. provenance, and the display rule that depends on it
# ---------------------------------------------------------------------------

def test_stamping_binds_the_rows_without_touching_the_source_hash():
    """If the backend overwrote `source_hash` from its own copy, the check below would
    pass by construction instead of by evidence — the two values would agree because
    one was copied from the other."""
    stored = ev.stamp(ev.parse([GOOD_FIT]), revision_id="rev-1", build_id="bld-1")
    assert stored[0]["revision_id"] == "rev-1"
    assert stored[0]["build_id"] == "bld-1"
    assert stored[0]["source_hash"] == "h_good"


def test_a_measurement_is_shown_only_under_the_geometry_it_was_taken_on():
    stored = ev.stamp(ev.parse([GOOD_FIT]), revision_id="rev-1", build_id="bld-1")
    assert len(ev.visible_for(stored, "h_good")) == 1
    # The revision was edited; this number describes the shape from before the edit.
    assert ev.visible_for(stored, "h_after_edit") == []


def test_a_record_with_no_source_hash_is_never_displayed():
    """It came from an engine that did not report one, so nothing can confirm which
    geometry it describes — and an unconfirmable number rendered beside a part reads
    exactly like a confirmed one."""
    stored = ev.stamp(ev.parse([_rec(source_hash=None)]),
                      revision_id="rev-1", build_id="bld-1")
    assert ev.visible_for(stored, "h_good") == []


def test_nothing_is_displayed_when_the_revision_has_no_hash_to_match_against():
    stored = ev.stamp(ev.parse([GOOD_FIT]), revision_id="rev-1", build_id="bld-1")
    assert ev.visible_for(stored, None) == []


def test_stored_records_are_json_safe():
    import json
    stored = ev.stamp(ev.parse([GOOD_FIT]), revision_id="rev-1", build_id="bld-1")
    assert json.loads(json.dumps(stored)) == stored


def test_by_id_indexes_what_the_grader_asks_for_by_name():
    stored = ev.stamp(ev.parse([GOOD_FIT, _rec(measurement_id="wall", value=2.5)]),
                      revision_id="r", build_id="b")
    idx = ev.by_id(stored)
    assert set(idx) == {"fit", "wall"}
    assert idx["wall"]["value"] == 2.5


# ---------------------------------------------------------------------------
# 6. the flag
# ---------------------------------------------------------------------------

def test_the_tranche_is_off_unless_the_operator_turns_it_on(monkeypatch):
    monkeypatch.delenv(ev.FLAG, raising=False)
    assert ev.evidence_enabled() is False
    monkeypatch.setenv(ev.FLAG, "true")
    assert ev.evidence_enabled() is True
    monkeypatch.setenv(ev.FLAG, "no")
    assert ev.evidence_enabled() is False
