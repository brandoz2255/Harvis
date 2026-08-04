"""Gate 5b — CadIR.

The gate's success criterion is narrow and worth restating: the hanger and the brick
must both be **expressible as CadIR**, and both must still pass Gate 2's determinism and
measurement tests **unchanged**. The stop rule is that neither golden test may be
relaxed to accommodate the IR.

So the load-bearing test here is :func:`test_cadir_reproduces_the_recipe_geometry`,
which builds each part twice — once through ``recipes``, once through the interpreter —
and compares the measurements Gate 2 asserts on. If the IR were even slightly different
geometry, that is where it would show, and no amount of the IR being elegant would save
it.

Run: ``docker exec harvis-cad python -m pytest tests/test_cadir.py -q -p no:cacheprovider``
"""
from __future__ import annotations

import copy

import pytest

import recipes
from cadir import budget, expr, schema, templates
from cadir import interpret

RECIPES_UNDER_TEST = ["helmet_hanger_v1", "studded_brick_v1"]


# --- 1. the documents are valid, and agree with the recipes they replace ------

@pytest.mark.parametrize("name", RECIPES_UNDER_TEST)
def test_template_parses(name):
    doc = schema.parse(templates.TEMPLATES[name])
    assert doc.name == name
    assert doc.schema_version == schema.SCHEMA_VERSION


@pytest.mark.parametrize("name", RECIPES_UNDER_TEST)
def test_parameter_spec_matches_the_recipe(name):
    """The ranges are written out in both places on purpose — importing them would make
    the duplication invisible. This is the assertion that makes a drift a test failure."""
    doc = schema.parse(templates.TEMPLATES[name])
    ir = {p.name: (p.kind, p.default, p.min, p.max) for p in doc.parameters}
    py = {n: (k, float(d), float(lo), float(hi))
          for n, (k, d, lo, hi) in recipes.PARAM_SPEC[name].items()}
    assert {k: (v[0], float(v[1]), float(v[2]), float(v[3])) for k, v in ir.items()} == py


@pytest.mark.parametrize("name", RECIPES_UNDER_TEST)
def test_expected_solids_matches_the_recipe(name):
    doc = schema.parse(templates.TEMPLATES[name])
    assert doc.expected_solids == recipes.RECIPE_SOLIDS[name]


# --- 2. the geometry is the same. this is the gate. ---------------------------

def _measure(part):
    bb = part.bounding_box()
    c = part.center()
    return {
        "volume": round(part.volume, 3),
        "area": round(part.area, 3),
        "solids": len(part.solids()),
        "bbox": tuple(round(v, 4) for v in (bb.size.X, bb.size.Y, bb.size.Z)),
        "center": tuple(round(v, 4) for v in (c.X, c.Y, c.Z)),
    }


CASES = [
    ("helmet_hanger_v1", {}),
    ("helmet_hanger_v1", {"arm_len_mm": 90}),
    ("helmet_hanger_v1", {"screw_count": 0}),          # the guard's false branch
    ("helmet_hanger_v1", {"screw_count": 5, "plate_h_mm": 120}),
    ("helmet_hanger_v1", {"fillet_r_mm": 0}),          # the optional fillet clamps, not fails
    ("studded_brick_v1", {}),
    ("studded_brick_v1", {"studs_x": 1, "studs_y": 1}),  # no interlock tubes at all
    ("studded_brick_v1", {"studs_x": 6, "studs_y": 3}),
    ("studded_brick_v1", {"studs_x": 1, "studs_y": 4}),  # 1xN: the tube guard is false
    ("studded_brick_v1", {"pitch_mm": 16, "stud_d_mm": 9, "body_h_mm": 14}),
]


@pytest.mark.parametrize("name,params", CASES)
def test_cadir_reproduces_the_recipe_geometry(name, params):
    from_recipe = _measure(recipes.build(name, recipes.resolve_params(name, params)))

    doc = schema.parse(templates.TEMPLATES[name])
    resolved = budget.resolve_params(doc, params)
    env, steps, _cost = budget.check(doc, resolved)
    from_ir = _measure(interpret.build(doc, resolved, steps=steps, env=env))

    assert from_ir == from_recipe


@pytest.mark.parametrize("name,params", CASES)
def test_resolved_parameters_match_the_recipe(name, params):
    doc = schema.parse(templates.TEMPLATES[name])
    assert budget.resolve_params(doc, params) == recipes.resolve_params(name, params)


# --- 3. determinism, on the same terms Gate 2 set ------------------------------

@pytest.mark.parametrize("name", RECIPES_UNDER_TEST)
def test_canonical_hash_is_stable(name):
    doc = schema.parse(templates.TEMPLATES[name])
    resolved = budget.resolve_params(doc, {})
    a = schema.canonical_source_hash(doc, resolved)
    b = schema.canonical_source_hash(schema.parse(templates.TEMPLATES[name]), resolved)
    assert a == b and len(a) == 64


def test_canonical_hash_covers_the_document_not_only_the_parameters():
    """A recipe name identified the geometry when geometry lived in Python. A CadIR
    document *is* the geometry, so two revisions with identical parameters and different
    operations must not collide."""
    payload = copy.deepcopy(templates.HELMET_HANGER_V1)
    doc_a = schema.parse(payload)
    resolved = budget.resolve_params(doc_a, {})
    payload["operations"][1]["size"] = ["arm_len_mm", "arm_w_mm", "arm_h_mm * 1"]
    doc_b = schema.parse(payload)
    assert schema.canonical_source_hash(doc_a, resolved) != schema.canonical_source_hash(doc_b, resolved)


@pytest.mark.parametrize("name", RECIPES_UNDER_TEST)
def test_two_independent_builds_agree(name):
    doc = schema.parse(templates.TEMPLATES[name])
    resolved = budget.resolve_params(doc, {})
    assert _measure(interpret.build(doc, resolved)) == _measure(interpret.build(doc, resolved))


# --- 4. no eval, ever ----------------------------------------------------------

REJECTED = [
    "__import__('os').system('id')",
    "open('/etc/passwd').read()",
    "().__class__",
    "plate_t_mm.__class__",
    "[x for x in range(10)]",
    "lambda: 1",
    "plate_t_mm[0]",
    "print(1)",
    "float('nan')",
    "2 ** 2 ** 2 ** 2",
    "plate_t_mm ** plate_w_mm",
    "1 if 2 else 3",
    "{'a': 1}",
    "'string'",
    "not plate_t_mm",
    "plate_t_mm := 3",
]


@pytest.mark.parametrize("source", REJECTED)
def test_formula_grammar_rejects(source):
    with pytest.raises(expr.ExprError):
        expr.compile_expr(source)


ACCEPTED = [
    ("1 + 2 * 3", {}, 7.0),
    ("-a / 2", {"a": 8}, -4.0),
    ("max(0.5, min(a, b / 2 - 0.5))", {"a": 3, "b": 8}, 3.0),
    ("max(0.5, min(a, b / 2 - 0.5))", {"a": 30, "b": 8}, 3.5),
    ("abs(0 - a)", {"a": 4}, 4.0),
    ("a ** 2", {"a": 3}, 9.0),
]


@pytest.mark.parametrize("source,env,want", ACCEPTED)
def test_formula_grammar_accepts(source, env, want):
    assert expr.evaluate(expr.compile_expr(source), env) == want


def test_division_by_zero_is_a_caller_error_not_a_crash():
    with pytest.raises(expr.ExprError) as e:
        expr.evaluate(expr.compile_expr("1 / a"), {"a": 0})
    assert e.value.code == "invalid_expr"


def test_unknown_name_is_rejected_at_parse_time_not_at_build_time():
    payload = copy.deepcopy(templates.HELMET_HANGER_V1)
    payload["operations"][0]["size"][0] = "plate_thickness_mm"
    with pytest.raises(expr.ExprError) as e:
        schema.parse(payload)
    assert e.value.code == "unknown_symbol"


def test_a_comparison_cannot_be_used_as_a_dimension():
    with pytest.raises(expr.ExprError):
        expr.evaluate(expr.compile_expr("a > 1"), {"a": 4})


def test_derived_values_cannot_reference_themselves_or_later_ones():
    payload = copy.deepcopy(templates.STUDDED_BRICK_V1)
    payload["derived"][0]["value"] = "cavity_h * 2"   # cavity_h is declared later
    with pytest.raises(expr.ExprError) as e:
        schema.parse(payload)
    assert e.value.code == "unknown_symbol"


# --- 5. the document itself is validated --------------------------------------

def test_unknown_field_is_rejected():
    payload = copy.deepcopy(templates.HELMET_HANGER_V1)
    payload["operations"][0]["colour"] = "red"
    with pytest.raises(Exception):
        schema.parse(payload)


def test_duplicate_op_id_is_rejected():
    payload = copy.deepcopy(templates.HELMET_HANGER_V1)
    payload["operations"][1]["op_id"] = "back_plate"
    with pytest.raises(Exception) as e:
        schema.parse(payload)
    assert "duplicate" in str(e.value)


def test_a_leading_fillet_is_rejected():
    payload = copy.deepcopy(templates.HELMET_HANGER_V1)
    payload["operations"] = [payload["operations"][-1]] + payload["operations"][:-1]
    with pytest.raises(Exception) as e:
        schema.parse(payload)
    assert "fillet" in str(e.value)


def test_unknown_parameter_is_an_error_not_a_shrug():
    doc = schema.parse(templates.HELMET_HANGER_V1)
    with pytest.raises(budget.ParamError) as e:
        budget.resolve_params(doc, {"arm_length_mm": 90})
    assert e.value.code == "unknown_param"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_parameter_is_rejected_before_any_clamp(bad):
    doc = schema.parse(templates.HELMET_HANGER_V1)
    with pytest.raises(budget.ParamError) as e:
        budget.resolve_params(doc, {"arm_len_mm": bad})
    assert e.value.code == "invalid_param"


# --- 6. the budget refuses what cannot finish ---------------------------------

def test_budget_admits_12x12_and_refuses_14x14():
    """The cap is the Gate 2 measurement, not a guess: 12x12 built in 8.60 s and 14x14
    in 15.88 s against a 20 s deadline, so 14x14 is work that cannot be relied on to
    finish and must be refused immediately rather than time out."""
    doc = schema.parse(templates.STUDDED_BRICK_V1)

    ok = budget.resolve_params(doc, {"studs_x": 12, "studs_y": 12})
    _env, _steps, cost = budget.check(doc, ok)
    assert cost <= budget.MAX_COST

    too_big = budget.resolve_params(doc, {"studs_x": 14, "studs_y": 14})
    with pytest.raises(budget.BudgetError) as e:
        budget.check(doc, too_big)
    assert e.value.cost > budget.MAX_COST


def test_budget_charges_for_the_branch_that_will_actually_run():
    """A guarded operation that will be skipped must not be charged for. A 1xN brick
    has no interlock tubes, and pricing them would refuse builds that do no such work."""
    doc = schema.parse(templates.STUDDED_BRICK_V1)
    _e, steps, _c = budget.check(doc, budget.resolve_params(doc, {"studs_x": 1, "studs_y": 8}))
    assert [op.op_id for op, _ in steps] == ["shell", "cavity", "studs"]


def test_the_plan_expands_to_the_instance_counts_the_recipe_builds():
    doc = schema.parse(templates.STUDDED_BRICK_V1)
    _e, steps, _c = budget.check(doc, budget.resolve_params(doc, {"studs_x": 4, "studs_y": 3}))
    counts = {op.op_id: len(pts) for op, pts in steps}
    assert counts == {
        "shell": 1, "cavity": 1,
        "studs": 12,                 # 4 x 3
        "interlock_tubes": 6,        # 3 x 2
        "interlock_bores": 6,
    }


def test_hanger_screw_positions_match_the_recipe_formula():
    """The recipe writes -h/2 + h*(i+1)/(n+1); the IR writes a centred array at pitch
    h/(n+1). Asserting they are the same set of numbers is cheaper than trusting the
    algebra, and it is the one place the IR restates a recipe rather than copying it."""
    doc = schema.parse(templates.HELMET_HANGER_V1)
    for n in (1, 2, 3, 5, 6):
        resolved = budget.resolve_params(doc, {"screw_count": n})
        _env, steps, _c = budget.check(doc, resolved)
        got = sorted(round(z, 9) for op, pts in steps if op.op_id == "screw_holes" for _x, _y, z in pts)
        h = resolved["plate_h_mm"]
        want = sorted(round(-h / 2 + h * (i + 1) / (n + 1), 9) for i in range(n))
        assert got == want, f"screw_count={n}"
