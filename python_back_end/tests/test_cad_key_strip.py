"""The deterministic half of CadIR repair: keys the engine says an operation cannot have.

Runs in the backend container — `cad_generate` imports the `owui_compat` package, which
pulls in fastapi. `python_back_end/tests` is not bind-mounted, so `docker cp` these in.

The rule is narrow and it is meant to stay narrow. This strips only what the sidecar has
already named, by field path, in its own rejection. It is not a second opinion about the
grammar and it never edits a document the engine has not ruled on.
"""

from __future__ import annotations

import asyncio

import pytest

from owui_compat.cad_generate import (
    GenerateError, strip_forbidden_keys, validate_document, validate_with_key_repair,
)


@pytest.fixture(scope="module")
def loop():
    """The repo's async convention — `pytest-asyncio` is not installed and
    `--strict-markers` would reject its marker (see tests/test_cad_store.py)."""
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.close()


SELECT = {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}


def _doc(**op_extra):
    return {
        "schema_version": "0.1", "units": "mm", "name": "plate", "expected_solids": 1,
        "parameters": [{"name": "w", "kind": "float", "default": 60, "min": 10, "max": 200}],
        "operations": [
            {"op": "box", "op_id": "base", "size": ["w", 40, 10]},
            {"op": "box", "op_id": "lip", "size": [10, 10, 5], **op_extra},
        ],
    }


def test_the_named_key_is_removed_from_the_named_operation():
    doc = _doc(select=SELECT)
    removed = strip_forbidden_keys(
        doc, "the document is not valid CadIR — operations.1.box.select: "
             "Extra inputs are not permitted")
    assert removed == ["lip.select"]
    assert "select" not in doc["operations"][1]
    assert doc["operations"][0] == {"op": "box", "op_id": "base", "size": ["w", 40, 10]}


def test_several_named_keys_in_one_message():
    """The sidecar joins up to eight field-addressed errors with '; '."""
    doc = _doc(select=SELECT, radius=5)
    removed = strip_forbidden_keys(
        doc, "the document is not valid CadIR — "
             "operations.1.box.select: Extra inputs are not permitted; "
             "operations.1.box.radius: Extra inputs are not permitted")
    assert sorted(removed) == ["lip.radius", "lip.select"]
    assert doc["operations"][1] == {"op": "box", "op_id": "lip", "size": [10, 10, 5]}


def test_a_different_rejection_removes_nothing():
    """Only 'Extra inputs are not permitted' is inert. A value that is out of range or a
    formula that names an undeclared symbol is a real disagreement and stays one."""
    doc = _doc(select=SELECT)
    assert strip_forbidden_keys(
        doc, "operations.1.box.size: List should have at least 3 items") == []
    assert doc["operations"][1]["select"] == SELECT


def test_the_operations_identity_is_never_stripped():
    doc = _doc(select=SELECT)
    for key in ("op", "op_id"):
        assert strip_forbidden_keys(
            doc, f"operations.1.box.{key}: Extra inputs are not permitted") == []
    assert doc["operations"][1]["op_id"] == "lip"


def test_an_out_of_range_index_is_ignored():
    doc = _doc(select=SELECT)
    assert strip_forbidden_keys(
        doc, "operations.9.box.select: Extra inputs are not permitted") == []
    assert doc["operations"][1]["select"] == SELECT


def test_a_key_that_is_not_there_is_not_reported_as_removed():
    doc = _doc()
    assert strip_forbidden_keys(
        doc, "operations.1.box.select: Extra inputs are not permitted") == []


def test_the_live_engine_accepts_the_stripped_document(loop):
    """The whole point, end to end against the real sidecar: a document the engine
    rejects for `select` on a box validates once the key is gone, with no model call."""
    with pytest.raises(GenerateError) as rejected:
        loop.run_until_complete(validate_document(_doc(select=SELECT)))
    assert rejected.value.code == "invalid_document"
    assert "operations.1.box.select" in rejected.value.message

    doc = _doc(select=SELECT)
    report, removed = loop.run_until_complete(validate_with_key_repair(doc))
    assert removed == ["lip.select"]
    assert isinstance(report, dict)


def test_a_rejection_it_cannot_mend_is_re_raised(loop):
    """A document broken in a way no key removal fixes must reach the repair loop
    unchanged — silently returning a report here would be the failure this guards."""
    doc = _doc()
    doc["operations"][1]["size"] = [10, 10]          # three items required
    with pytest.raises(GenerateError) as e:
        loop.run_until_complete(validate_with_key_repair(doc))
    assert e.value.code == "invalid_document"
