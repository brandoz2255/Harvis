"""Backend-side CadIR admission control.

These test what ``owui_compat.cad_ir`` claims to do and nothing more. It is not a
validator — the sidecar's ``cadir.parse`` is — so there is deliberately no test here
asserting that a well-formed document is "valid". The assertions are: the obviously
impossible is refused, and a document the engine would accept is not refused here.
"""
from __future__ import annotations

import copy

import pytest

from owui_compat import cad_ir

HANGER = {
    "schema_version": "0.1",
    "units": "mm",
    "name": "helmet_hanger_v1",
    "expected_solids": 1,
    "parameters": [
        {"name": "plate_t_mm", "kind": "float", "default": 6, "min": 1, "max": 40},
    ],
    "operations": [
        {"op": "box", "op_id": "back_plate", "size": ["plate_t_mm", 40, 44],
         "at": {"positions": [["plate_t_mm / 2", 0, 0]]}},
        {"op": "cylinder", "op_id": "screw_holes", "radius": 2, "height": 18,
         "rotation": [0, 90, 0], "mode": "subtract", "when": "screw_count >= 1",
         "at": {"count": [1, 1, "screw_count"], "pitch": [0, 0, 14],
                "center": ["plate_t_mm / 2", 0, 0]}},
        {"op": "fillet", "op_id": "root_fillet", "radius": "max(0.5, fillet_r_mm)",
         "select": {"filter_by": "Y", "sort_by": "X", "take": [0, 2]}, "optional": True},
    ],
}


def _doc(**changes):
    d = copy.deepcopy(HANGER)
    d.update(changes)
    return d


def test_a_real_document_passes():
    assert cad_ir.check_document(copy.deepcopy(HANGER)) is not None


def test_formula_strings_are_not_second_guessed():
    """This layer does not own the grammar. A formula it cannot evaluate — and one
    using a call it has no table for — must pass through to the engine."""
    d = _doc()
    d["operations"][0]["size"] = ["max(1, plate_t_mm)", "width * 2", 44]
    assert cad_ir.check_document(d) is not None


@pytest.mark.parametrize("payload,code", [
    ("not a document", "invalid_document"),
    (["operations"], "invalid_document"),
    # An empty object carries no *unknown* field, so the first thing it fails is the
    # version check — which is the honest answer to "what is wrong with {}".
    ({}, "unsupported_schema"),
])
def test_non_documents_are_refused(payload, code):
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(payload)
    assert exc.value.code == code


def test_an_unknown_top_level_field_is_refused():
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(_doc(acceptance=[]))
    assert exc.value.code == "unknown_field"


def test_an_unsupported_schema_version_is_refused():
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(_doc(schema_version="0.2"))
    assert exc.value.code == "unsupported_schema"


def test_inches_are_refused():
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(_doc(units="in"))
    assert exc.value.code == "unsupported_units"


def test_an_unknown_operation_is_refused():
    d = _doc()
    d["operations"][0]["op"] = "loft"
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "unknown_op"


def test_an_empty_operation_list_is_refused():
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(_doc(operations=[]))
    assert exc.value.code == "invalid_document"


def test_too_many_operations_are_refused():
    d = _doc(operations=[HANGER["operations"][0]] * (cad_ir.MAX_OPERATIONS + 1))
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "document_too_large"


def test_an_oversized_document_is_refused():
    d = _doc()
    d["name"] = "x" * (cad_ir.MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "document_too_large"


def test_an_overlong_formula_is_refused():
    d = _doc()
    d["operations"][0]["size"] = ["1 + " * 200 + "1", 40, 44]
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "invalid_formula"


def test_a_nan_dimension_is_refused():
    """The headline risk of the whole lane, refused at one more boundary. It is caught
    by the JSON serialisation check, which is why the code is document-level."""
    d = _doc()
    d["operations"][0]["size"] = [float("nan"), 40, 44]
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "invalid_document"


@pytest.mark.parametrize("rotation", [[0, 90], [0, "90", 0], [0, True, 0], "90"])
def test_a_malformed_rotation_is_refused(rotation):
    """A rotation is three plain numbers, never a formula — it reaches the kernel as a
    transform, not a dimension. A *non-finite* one is caught earlier by the
    serialisation check, so these are the cases only this check catches."""
    d = _doc()
    d["operations"][1]["rotation"] = rotation
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "invalid_document"


def test_a_bool_dimension_is_refused():
    """``True`` is an ``int`` in Python and would otherwise pass as the dimension 1."""
    d = _doc()
    d["operations"][0]["size"] = [True, 40, 44]
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "invalid_formula"


def test_a_literal_instance_bomb_is_refused_before_dispatch():
    d = _doc()
    d["operations"][1]["at"] = {"count": [64, 64, 1], "pitch": [10, 10, 0],
                                "center": [0, 0, 0]}
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_document(d)
    assert exc.value.code == "budget_exceeded"


def test_a_formula_valued_count_is_left_to_the_engine():
    """The honest limit: this layer has no parameter environment, so it cannot bound a
    computed count and does not pretend to. The engine's budget does that."""
    d = _doc()
    d["operations"][1]["at"] = {"count": ["studs_x", "studs_y", 1],
                                "pitch": [10, 10, 0], "center": [0, 0, 0]}
    assert cad_ir.check_document(d) is not None


@pytest.mark.parametrize("params,code", [
    ({"plate_t_mm": float("nan")}, "invalid_param"),
    ({"plate_t_mm": float("inf")}, "invalid_param"),
    ({"plate_t_mm": "6"}, "invalid_param"),
    ({"plate_t_mm": True}, "invalid_param"),
    ({6: 6}, "invalid_param"),
    ("not a map", "invalid_param"),
])
def test_bad_params_are_refused(params, code):
    with pytest.raises(cad_ir.CadIRError) as exc:
        cad_ir.check_params(params)
    assert exc.value.code == code


def test_good_params_pass():
    assert cad_ir.check_params({"plate_t_mm": 6, "screw_count": 2}) == \
        {"plate_t_mm": 6, "screw_count": 2}


def test_the_error_carries_a_structured_code():
    """The route layer needs to tell an impossible request apart from a down engine."""
    err = cad_ir.CadIRError("unknown_op", "unknown operation 'loft'")
    assert err.code == "unknown_op"
    assert "unknown_op" in str(err)
