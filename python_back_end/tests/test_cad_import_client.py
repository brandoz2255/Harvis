"""Gate 8B: the backend half of the import lane, in the parts that need no engine.

Everything here is a refusal that happens *before* the HTTP hop, which is the only
reason it can be tested without the sidecar: an unreadable extension, an empty file,
one over the cap. Those are the cases where a round trip would buy nothing, and the
point of asserting them is that the local refusal carries the same ``error_code`` the
engine would have used — a client that has to branch on which layer caught it has two
error models for one failure.

What is deliberately NOT here: any test of a successful import. That needs the real
OCCT readers, and stubbing them would prove only that the stub returns what it was
told to. The successful path is verified in the engine's own ``tests/test_import.py``
and end to end through the route.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_cad_import_client.py -q
"""
from __future__ import annotations

import asyncio

import pytest

from owui_compat import fab_cad


def call(name: str, data: bytes, **kw):
    return asyncio.run(fab_cad.import_asset(name, data, **kw))


def test_the_readable_list_is_shorter_than_the_writable_one():
    """GLB and glTF are exports only, and the asymmetry has to be visible.

    build123d writes glTF and ships no reader for it; neither ``trimesh`` nor
    ``pygltflib`` is installed in the engine. One list serving both directions would
    promise a round trip that does not exist, so a picker built from ``KNOWN_FORMATS``
    would offer GLB and refuse every GLB a user then chose.
    """
    assert "glb" in fab_cad.KNOWN_FORMATS
    assert "glb" not in fab_cad.KNOWN_IMPORT_KINDS
    assert "gltf" not in fab_cad.KNOWN_IMPORT_KINDS


@pytest.mark.parametrize("name,kind", [
    ("part.step", "step"), ("part.STEP", "step"), ("part.stp", "step"),
    ("part.stl", "stl"), ("part.3mf", "3mf"),
    ("part.brep", "brep"), ("part.brp", "brep"),
])
def test_an_extension_maps_onto_the_reader_the_engine_switches_on(name, kind):
    """``.stp`` is "step" here for the same reason it is there: the revision's
    provenance and the build's have to say the same word for the same reader, or the
    two cannot be compared at all."""
    assert fab_cad.import_kind_for(name) == kind


@pytest.mark.parametrize("name", ["part.glb", "part.gltf", "part.obj", "part", "part."])
def test_anything_else_is_refused_by_name_before_a_byte_moves(name):
    assert fab_cad.import_kind_for(name) is None
    with pytest.raises(fab_cad.CadError) as e:
        call(name, b"x" * 16)
    assert e.value.code == "import_unsupported_format"
    # The refusal names what it will take. "Unsupported format" alone leaves the user
    # guessing at a list they cannot see.
    assert ".step" in e.value.message


def test_an_empty_file_is_refused_here_rather_than_parsed_there():
    with pytest.raises(fab_cad.CadError) as e:
        call("part.step", b"")
    assert e.value.code == "import_empty"


def test_an_oversized_file_never_crosses_the_internal_network():
    """The engine re-checks and its answer is the one that counts. This one exists so
    32 MB is not copied to a container that is going to refuse it."""
    too_big = fab_cad.MAX_IMPORT_BYTES + 1
    with pytest.raises(fab_cad.CadError) as e:
        call("part.stl", b"\0" * too_big)
    assert e.value.code == "import_too_large"
    assert str(too_big) in e.value.message


def test_an_unwritable_export_format_is_refused_rather_than_dropped():
    with pytest.raises(fab_cad.CadError) as e:
        call("part.step", b"ISO-10303-21;", formats=["dxf"])
    assert e.value.code == "unknown_format"


def test_one_decoder_serves_both_the_build_and_the_import_reply():
    """A second copy of the multipart/error decode is how the two paths drift, and the
    one that drifts is always the newer one. Asserting the shared helper is reachable
    from both is cheap; discovering later that an import lost its structured
    ``error_code`` is not."""
    import inspect
    assert callable(fab_cad._decode_build_response)
    for fn in (fab_cad.execute, fab_cad.import_asset):
        assert "_decode_build_response" in inspect.getsource(fn), fn.__name__
