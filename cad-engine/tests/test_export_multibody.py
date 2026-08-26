"""Every export format has to survive a part with more than one body.

Gate 2 verified all four exporters, and verified them on ``Box(10,20,30)`` — one solid.
That is why nobody saw this: :func:`exporters.write_3mf` passed a single deterministic
uuid to ``Mesher.add_shape``, and ``add_shape`` flattens a compound internally and stamps
that same uuid onto every mesh object it creates. lib3mf refuses the second one —

    Lib3MFException 5: A UUID is not unique within a package.

— so a document with two or more components could not produce a 3MF at all. The failure
surfaced as ``missing_artifact`` from ``/cad/v2/build``, which reads like the worker died
rather than like one writer raising, and the same request with ``formats: ["glb","stl"]``
succeeded, which made it look like a placements problem. It never was one: a three-body
document with **no** placements fails identically.

So the assertions here are deliberately about body count, not about placements, and they
run every format rather than only the one that broke — a per-write identifier is the kind
of thing another exporter could grow later.

Run: ``docker exec harvis-cad python -m pytest tests/test_export_multibody.py -q``
"""
from __future__ import annotations

import os

import pytest

import exporters
from cadir import interpret, schema
from cadir.budget import resolve_params


def _doc(count: int) -> dict:
    return {
        "schema_version": "0.3",
        "units": "mm",
        "name": f"{count}_bodies",
        "expected_solids": count,
        "parameters": [],
        "operations": [
            {
                "op_id": f"b{i}",
                "op": "box",
                "component": f"body_{i}",
                "size": [10, 10, 10],
                "at": {"positions": [[i * 30, 0, 0]]},
            }
            for i in range(count)
        ],
    }


def _build(count: int):
    doc = schema.parse(_doc(count))
    return interpret.build(doc, resolve_params(doc, {}))


@pytest.mark.parametrize("fmt", exporters.FORMATS)
@pytest.mark.parametrize("bodies", [1, 2, 3])
def test_every_format_writes_a_non_empty_file(fmt, bodies, tmp_path):
    """The regression, stated at its narrowest. ``bodies=1`` is the case Gate 2 covered
    and is included so a future change that fixes many bodies by breaking one is caught."""
    path = str(tmp_path / f"out.{fmt}")
    exporters.write(fmt, _build(bodies), path, seed=f"probe-{bodies}")
    assert os.path.getsize(path) > 0


def test_the_3mf_package_carries_one_mesh_per_body(tmp_path):
    """Not just "it wrote a file" — a writer that quietly emitted the first body and
    dropped the rest would pass the test above while losing two thirds of the part."""
    from build123d import Mesher

    path = str(tmp_path / "three.3mf")
    exporters.write_3mf(_build(3), path, seed="probe")
    assert len(Mesher().read(path)) == 3


def test_the_3mf_identifier_is_a_function_of_the_input_not_the_clock(tmp_path):
    """The property the per-body uuid replaced a per-write random one to get. Bytes are
    not compared — a 3MF is a ZIP and carries its own per-write metadata — so this
    asserts the two writes describe the same geometry, which is the Gate 2 contract."""
    from build123d import Mesher

    a, b = str(tmp_path / "a.3mf"), str(tmp_path / "b.3mf")
    exporters.write_3mf(_build(3), a, seed="same-seed")
    exporters.write_3mf(_build(3), b, seed="same-seed")
    va = sorted(round(s.volume, 6) for s in Mesher().read(a))
    vb = sorted(round(s.volume, 6) for s in Mesher().read(b))
    assert va == vb
