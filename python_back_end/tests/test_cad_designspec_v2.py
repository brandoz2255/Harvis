"""The checks that can fail, and the binding that keeps them pointed at real bodies (HE-4).

Two things are under test and they fail in different ways. The extractor turns a
sentence into checks, and its failure mode is *reaching* — claiming a requirement the
sentence never stated, which fails correct parts. The binder turns a logical role into
a part key, and its failure mode is *guessing* — pointing a real measurement at the
wrong body, which is the only outcome worse than measuring nothing.

Loaded through a stand-in package for the same reason the conformance suite is: these
modules answer for themselves with no fastapi, no asyncpg and no database behind them,
and importing the real `owui_compat` would let a pure-logic test fail for reasons that
have nothing to do with the logic.
"""

from __future__ import annotations

import importlib.util
import os
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
v2 = _load("cad_designspec_v2")
mp = _load("cad_measure_plan")
ev = _load("cad_evidence")

JAR = ("a jar with a removable lid - body 115 mm tall, 2.5 mm neck wall, 4 mm base; "
       "the lid is a separate part with a hollow skirt 5.5 mm deep, concentric with "
       "the neck, 0.3 mm clearance.")

# The HE-0 fixture's operations, trimmed to the field the binder reads. Copied from
# `cad-engine/tests/fixtures/jar/good.json` rather than invented, so a rename there
# breaks this test instead of silently decoupling it.
JAR_DOC = {"operations": [
    {"op_id": "body_outer", "component": "jar_body"},
    {"op_id": "body_bore", "component": "jar_body", "mode": "subtract"},
    {"op_id": "lid_outer", "component": "lid"},
    {"op_id": "lid_skirt_bore", "component": "lid", "mode": "subtract"},
]}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(v2.FLAG, "1")


def _ids(spec):
    return [c["id"] for c in spec["checks"]]


def _by_id(spec):
    return {c["id"]: c for c in spec["checks"]}


# ---------------------------------------------------------------------------
# 1. the flag, which is the whole safety story of this gate
# ---------------------------------------------------------------------------

def test_the_v2_checks_are_absent_until_the_operator_turns_them_on(monkeypatch):
    """`cad_conformance` grades a check kind it has no handler for as `unverified`, and
    a build needs zero unverified checks to grade `passed`. Shipping these before HE-5's
    handlers exist would turn every currently-passing build into an unverified one — so
    off is not caution, it is the only correct default until the graders land."""
    monkeypatch.delenv(v2.FLAG, raising=False)
    spec = ds.extract(JAR)
    assert spec["extractor"] == "regex/v1"
    assert not any(c["kind"] in v2._SUPERSEDES or "measure" in c
                   for c in spec["checks"])


def test_the_two_modules_cannot_disagree_about_the_flag():
    """The flag name is written down twice — once here, once in `cad_evidence` — because
    importing that module would drag pydantic into a file-path-loaded test. This is what
    stops the copies drifting into a state where half the tranche is on."""
    assert v2.FLAG == ev.FLAG
    for value in ("1", "true", "TRUE", "yes", "on", "0", "no", "off", "", "  "):
        os.environ[v2.FLAG] = value
        try:
            assert v2.enabled() is ev.evidence_enabled(), value
        finally:
            del os.environ[v2.FLAG]


def test_v1_alone_reads_the_jar_as_a_single_115_mm_envelope(monkeypatch):
    """The state of the world before this gate, recorded so the improvement is legible.
    Two of these three are wrong about a jar and the third is silent about all of it."""
    monkeypatch.delenv(v2.FLAG, raising=False)
    spec = ds.extract(JAR)
    assert _by_id(spec)["bbox_has_height"]["expected"] == 115.0
    assert _by_id(spec)["bbox_has_depth"]["expected"] == 5.5
    assert _by_id(spec)["solid_count"]["expected"] == 1


# ---------------------------------------------------------------------------
# 2. the seven kinds the plan names
# ---------------------------------------------------------------------------

def test_the_jar_sentence_produces_every_check_the_gate_promised(on):
    spec = ds.extract(JAR)
    assert spec["extractor"] == "regex/v2"
    got = _ids(spec)
    for cid in ("part_height", "base_thickness", "wall_thickness", "cavity_depth",
                "fit_clearance", "axis_offset", "angular_deviation", "part_count",
                "interference_volume"):
        assert cid in got, cid
    assert spec["unknowns"] == []


def test_concentric_is_two_questions_not_one(on):
    """A lid sharing a centreline but tilted 2° is not concentric, and a lid tilted
    about its own centroid has an axis offset of zero. One number cannot say which of
    the two went wrong, so the word emits both checks or it means nothing."""
    ids = _ids(ds.extract("a lid concentric with the body"))
    assert "axis_offset" in ids and "angular_deviation" in ids


def test_a_lid_on_a_jar_is_two_parts_even_without_the_word_removable(on):
    """The sentence the user actually types. Requiring 'removable' or 'concentric'
    is how a fused disk passed as a lid: nothing in the answer key said otherwise."""
    spec = ds.extract("a lid on a jar")
    ids = _ids(spec)
    assert "part_count" in ids and "interference_volume" in ids
    assert "axis_offset" in ids and "angular_deviation" in ids
    assert spec["stated"]["separate_parts"] == 2
    assert spec["stated"]["coaxial"] is True
    assert "fit_clearance" not in ids
    assert any("slip-fit clearance was not stated" in a for a in spec["assumptions"])


def test_an_unstated_clearance_is_not_graded(on):
    """Shop default clearance lives on the pattern brief. Putting 0.3 mm into the
    answer key when the user never said it would fail a correct 0.2 mm lid."""
    spec = ds.extract("make me a bottle cap")
    assert "fit_clearance" not in _ids(spec)



def test_every_v2_check_carries_a_typed_tolerance_and_a_comparator(on):
    """The difference between a v1 check and a v2 one. A bare expected number cannot
    say whether 0.0 mm of interference is a floor, a ceiling or a target."""
    for c in ds.extract(JAR)["checks"]:
        if "measure" not in c:
            continue
        tol = c["tolerance"]
        assert tol["kind"] in ("symmetric", "asymmetric", "min_only", "max_only")
        assert tol["unit"] in ("mm", "deg", "mm3", "count")
        assert c["comparator"] in ("eq", "gte", "lte", "between")
        assert c["measurement_id"] == c["id"]


def test_a_ceiling_check_is_not_written_as_an_equality(on):
    """Interference of exactly 0.0 mm³ is unachievable — two faces that touch return
    numerical slivers. Comparing for equality would fail every correct assembly."""
    checks = _by_id(ds.extract(JAR))
    assert checks["interference_volume"]["comparator"] == "lte"
    assert checks["interference_volume"]["tolerance"]["plus"] > 0
    assert checks["part_count"]["comparator"] == "gte"


# ---------------------------------------------------------------------------
# 3. superseding v1, which is where a correct jar stopped failing
# ---------------------------------------------------------------------------

def test_the_part_scoped_height_replaces_the_assembly_envelope_claim(on):
    """`bbox_has_height` says one of the three assembly dimensions is 115. That is true
    of a 100 mm body under a 15 mm lid, which is exactly the defect `bad_body_short`
    encodes — so keeping both would grade the same sentence twice and let the weaker
    reading pass the part the stronger one caught."""
    spec = ds.extract(JAR)
    assert "part_height" in _ids(spec)
    assert "bbox_has_height" not in _ids(spec)


def test_the_skirt_depth_stops_being_an_envelope_dimension(on):
    """The sharper case. Nothing in a 115 mm jar assembly measures 5.5 mm, so v1's
    `bbox_has_depth` failed a *correct* part. v2 measures it where it exists — between
    the lid's opening plane and its cavity floor."""
    spec = ds.extract(JAR)
    assert "bbox_has_depth" not in _ids(spec)
    assert _by_id(spec)["cavity_depth"]["measure"]["kind"] == "plane_gap"


def test_a_removable_lid_stops_asserting_the_result_is_one_body(on):
    """v1 assumes one body unless the sentence says "two separate pieces", and "a
    removable lid" does not say that. The jar therefore carried `solid_count == 1` and
    would have failed as built. `part_count` is the same claim measured off the
    manifest, so it replaces rather than argues with it."""
    spec = ds.extract(JAR)
    assert "solid_count" not in _ids(spec)
    assert "solid_count" not in spec["stated"]
    assert spec["stated"]["separate_parts"] == 2


def test_an_envelope_dimension_that_is_not_the_same_number_survives(on):
    """Superseding is matched on the value as well as the name. A sentence that fixes
    both an overall height and a different part-scoped one is stating two facts, and
    dropping either would lose a requirement the user wrote."""
    spec = ds.extract("a 200 mm tall assembly; the body is 115 mm tall")
    ids = _ids(spec)
    assert "part_height" in ids
    assert any(i.startswith("bbox_has_") for i in ids)


# ---------------------------------------------------------------------------
# 4. what the extractor refuses to invent
# ---------------------------------------------------------------------------

def test_a_foreign_unit_still_disables_everything(on):
    """Carried forward from v1 unchanged, and it has to be: a silent x25.4 ships a part
    ten times too big, and v2 adds seven more checks that would carry the same error."""
    spec = ds.extract("a jar 4 inches tall with a 0.1 inch wall")
    assert spec["units"] == "unsupported"
    assert spec["checks"] == []


def test_a_bare_number_with_no_part_noun_does_not_become_a_part_height(on):
    """"115 mm tall" alone is an envelope statement, which v1 already reads correctly.
    Reading it a second time as a body height would invent a body the sentence never
    named and then measure a different part against it."""
    spec = ds.extract("a bracket 115 mm tall")
    assert "part_height" not in _ids(spec)
    assert "bbox_has_height" in _ids(spec)


def test_a_depth_on_an_unrecognised_noun_is_left_to_the_envelope_reading(on):
    spec = ds.extract("a plate with a 5 mm deep groove")
    assert "cavity_depth" not in _ids(spec)


def test_slip_fit_states_no_number_so_it_states_no_requirement(on):
    """A phrase with no dimension in it cannot produce a tolerance, and inventing a
    default clearance would grade a part against a number nobody chose."""
    assert "fit_clearance" not in _ids(ds.extract("a lid with a slip fit"))


def test_an_absurd_dimension_is_dropped_rather_than_carried(on):
    for text in ("a body 0 mm tall", "a body 99999 mm tall"):
        assert "part_height" not in _ids(ds.extract(text))


# ---------------------------------------------------------------------------
# 5. the assumption that is worth a factor of two
# ---------------------------------------------------------------------------

def test_a_bare_clearance_is_read_as_diametral_and_says_so(on):
    """Shop speech says "0.3 mm clearance" and means the gap on the diameter. Radial is
    the other reading and it is half the number. The choice is unavoidable; making it
    silently is not."""
    spec = ds.extract(JAR)
    assert spec["stated"]["fit_clearance_basis"] == "diametral"
    assert _by_id(spec)["fit_clearance"]["basis"] == "diametral"
    assert any("diametral" in a and "0.15" in a for a in spec["assumptions"])


def test_the_assumption_reaches_the_text_a_human_reads(on):
    """An assumption recorded in a field no surface renders is a silent decision."""
    assert "assumed:" in ds.describe(ds.extract(JAR))


def test_v1_specs_still_carry_the_field_so_readers_need_no_special_case(monkeypatch):
    monkeypatch.delenv(v2.FLAG, raising=False)
    assert ds.extract("a 30 mm cube")["assumptions"] == []


# ---------------------------------------------------------------------------
# 6. binding a role to a body — where a wrong answer is worse than none
# ---------------------------------------------------------------------------

def test_a_role_binds_to_the_key_the_manifest_will_use(on):
    """`manifest.part_key` keys a named component as `name:<name>`. The plan has to use
    the same string the engine will, or every measurement resolves against nothing."""
    bound = mp.bind_roles(JAR_DOC)
    assert bound == {"body": "name:jar_body", "lid": "name:lid"}


def test_the_jar_plan_names_a_real_body_for_every_measurable_check(on):
    plan = mp.plan(ds.extract(JAR), JAR_DOC)
    assert {r["measurement_id"] for r in plan} == {
        "part_height", "base_thickness", "wall_thickness", "cavity_depth",
        "fit_clearance", "axis_offset", "angular_deviation", "part_count",
        "interference_volume"}
    for req in plan:
        for ref in (req.get("a"), req.get("b")):
            if ref:
                assert ref["part_key"].startswith("name:")


def test_the_fit_is_measured_between_the_lid_bore_and_the_body_outside(on):
    """The measurement Rev 1 got wrong. A seated lid touches the rim, so whole-body
    minimum distance is 0.0 for a perfect fit — the two mating cylinders are the only
    pair that answers the question."""
    fit = next(r for r in mp.plan(ds.extract(JAR), JAR_DOC)
               if r["measurement_id"] == "fit_clearance")
    assert fit["a"] == {"part_key": "name:lid", "face_role": "bore_cylinder"}
    assert fit["b"] == {"part_key": "name:jar_body", "face_role": "outer_cylinder"}


def test_a_role_the_document_does_not_have_produces_no_request(on):
    """Not a request against the nearest body. A check with no measurement grades
    `unverified`, which says "there is no lid here" — a different statement from "the
    lid is the wrong size", and the two must not be collapsed."""
    body_only = {"operations": [{"component": "jar_body"}]}
    ids = {r["measurement_id"] for r in mp.plan(ds.extract(JAR), body_only)}
    assert "fit_clearance" not in ids and "axis_offset" not in ids
    assert "wall_thickness" in ids


def test_two_bodies_that_both_read_as_a_lid_bind_to_neither(on):
    """Ambiguity is as unresolved as absence. Picking the first would be a coin flip
    reported as a measurement."""
    two_lids = {"operations": [{"component": "lid"}, {"component": "cap"},
                               {"component": "jar_body"}]}
    assert mp.bind_roles(two_lids) == {"body": "name:jar_body"}


def test_a_name_that_reads_as_both_parts_identifies_neither(on):
    assert mp.bind_roles({"operations": [{"component": "body_lid"}]}) == {}


def test_an_unnamed_component_is_not_bindable(on):
    """`part_key` falls back to `slot:<n>` for an unnamed body, and a slot number is not
    something a sentence can refer to."""
    assert mp.bind_roles({"operations": [{"component": ""}, {"op_id": "x"}]}) == {}


def test_component_names_are_matched_on_their_parts(on):
    for name, role in (("jar_body", "body"), ("Lid_Assembly", "lid"),
                       ("outer-jar", "body"), ("cap.top", "lid")):
        assert mp.bind_roles({"operations": [{"component": name}]}) == \
            {role: f"name:{name}"}


def test_a_missing_document_plans_only_what_needs_no_document(on):
    """A build can reach here before a document exists.

    Everything that names a body drops out, because there is nothing to name it
    against, and those checks grade `unverified`. `part_count` survives: counting the
    bodies that came out asks nothing of the document, so refusing to plan it would
    be caution, not honesty. No spec at all plans nothing.
    """
    assert [r["kind"] for r in mp.plan(ds.extract(JAR), None)] == ["part_count"]
    assert mp.plan(None, JAR_DOC) == []


def test_the_plan_is_bounded(on):
    """Each request walks every face of a body and the interference kind runs a boolean,
    so the cap is admission control rather than tidiness."""
    spec = {"checks": [{"id": f"m{i}", "measurement_id": f"m{i}",
                        "kind": "part_height",
                        "measure": {"kind": "part_extent", "role": "body", "axis": "z"}}
                       for i in range(mp.MAX_MEASUREMENTS + 10)]}
    assert len(mp.plan(spec, JAR_DOC)) == mp.MAX_MEASUREMENTS


def test_a_check_with_no_measure_block_is_skipped_not_guessed(on):
    """Every v1 check is in this state, and they travel in the same list."""
    spec = {"checks": [{"id": "bbox_set", "kind": "bbox_set", "expected": [1, 2, 3]}]}
    assert mp.plan(spec, JAR_DOC) == []


def test_the_wire_form_is_what_the_engine_grammar_accepts(on):
    """The plan is built in the backend and validated in the engine, which are separate
    images. This asserts the shapes agree, field for field, against the table in
    `measure_spec.KINDS` — reproduced here because that module ships in the other
    image and cannot be imported from this one."""
    shapes = {"local_thickness": "face", "radial_clearance": "face",
              "plane_gap": "face", "part_extent": "part_axis", "axis_offset": "axis",
              "angular_deviation": "axis", "interference_volume": "part",
              "part_count": "none"}
    for req in mp.plan(ds.extract(JAR), JAR_DOC):
        shape = shapes[req["kind"]]
        assert req["measurement_id"].replace("_", "a").isalnum()
        if shape == "face":
            assert set(req["a"]) == set(req["b"]) == {"part_key", "face_role"}
        elif shape == "axis":
            assert set(req["a"]) == set(req["b"]) == {"part_key", "axis_role"}
        elif shape == "part":
            assert set(req["a"]) == set(req["b"]) == {"part_key"}
        elif shape == "part_axis":
            assert req["axis"] in ("x", "y", "z") and "a" not in req
        else:
            assert "a" not in req and "part_key" not in req
