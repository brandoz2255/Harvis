"""What `normalize_document` is allowed to silently drop, and what it is not.

Runs in the backend container: `cad_generate` imports the `owui_compat` package, which
pulls in fastapi, so this is not a host-side test. Copy the tests in first —
`python_back_end/tests` is not bind-mounted.

The rule this file guards is narrow on purpose. Normalization exists so a model is not
rejected for saying "nothing" the long way; it must never become a place where a wrong
document is quietly turned into a different part.
"""

from __future__ import annotations

import pytest

from owui_compat.cad_generate import normalize_document


def _cyl(**kw):
    return {"op": "cylinder", "op_id": "bore", "radius": 5, "height": 30, **kw}


def test_a_null_field_is_dropped():
    assert normalize_document({"op": "box", "radius": None}) == {"op": "box"}


def test_an_empty_at_is_dropped():
    assert "at" not in normalize_document(_cyl(at={}))


def test_a_populated_at_survives():
    doc = normalize_document(_cyl(at={"positions": [[0, 0, 0]]}))
    assert doc["at"] == {"positions": [[0, 0, 0]]}


def test_optional_false_is_dropped_from_a_cylinder():
    """`optional` means "skip me rather than fail the build". Only a fillet has anything
    to degrade, and false is the default, so on a cylinder it is a no-op written down.

    Measured, and the reason this rule exists: across twenty live qwen3:4b runs of two
    prompts, `cylinder.optional` was the rejection in every single failure.
    """
    assert "optional" not in normalize_document(_cyl(optional=False))


def test_optional_true_is_NOT_dropped_from_a_cylinder():
    """There is no honest reading of it, so it stays a reported rejection rather than a
    quiet edit. Dropping it would answer 200 for a part whose author asked for something
    the format cannot do."""
    assert normalize_document(_cyl(optional=True))["optional"] is True


def test_optional_survives_on_a_fillet_either_way():
    for value in (True, False):
        op = {"op": "fillet", "op_id": "round", "radius": 2, "optional": value}
        assert normalize_document(op)["optional"] is value


def test_select_is_never_dropped_from_a_cylinder():
    """The one the Gate 7B commit argued about, and the answer has not changed: `select`
    names edges the author meant to pick. Discarding it builds a different part in
    silence, which is the failure this whole subsystem exists to avoid."""
    sel = {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}
    assert normalize_document(_cyl(select=sel))["select"] == sel


def test_the_document_itself_is_not_treated_as_an_operation():
    """The top level has no `op`, and a document-level `optional` is not a thing — but
    the guard is worth a test, because the rule is written as a recursive dict rule."""
    doc = {"schema_version": "0.1", "operations": [_cyl(optional=False)], "optional": False}
    out = normalize_document(doc)
    assert out["optional"] is False
    assert "optional" not in out["operations"][0]


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_only_the_boolean_false_is_dropped(value):
    """`optional: 0` is not `optional: false`. Coercing it would be normalization
    deciding what the model meant, which this function does not do."""
    out = normalize_document(_cyl(optional=value))
    assert ("optional" in out) is (value is not None)
