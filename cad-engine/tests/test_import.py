"""Gate 8B — imported reference geometry, and everything we refuse to parse.

Two halves, and the split matters. The refusal half runs without OCP at all, because
:mod:`importers` imports build123d lazily: the refusals *are* the security surface —
they decide which bytes a C++ parser ever sees — and a suite that needed a 1.4 s kernel
import to exercise them is a suite that gets skipped.

The load half does the opposite: it writes real files with build123d and reads them
back, because the one claim worth proving about an import is what the geometry actually
turns out to be. STEP comes back as an exact solid with its volume intact; STL comes
back as a ``Face`` with no volume at all. Those two facts are why `import_verdict`
exists, and asserting them here is what stops someone "fixing" it later.

Nothing in this file asserts recovered features, because nothing produces them. A STEP
file carries a solved B-Rep and no history, and a mesh carries neither.

Run: ``docker exec harvis-cad python -m pytest tests/test_import.py -q -p no:cacheprovider``
"""
from __future__ import annotations

import os
import pathlib
import re
import struct
import zipfile

import pytest

import importers
import validation

BOX = (10.0, 20.0, 30.0)          # 6000 mm³, and every digit of it exact
BOX_VOLUME = BOX[0] * BOX[1] * BOX[2]
BOX_AREA = 2 * (10 * 20 + 10 * 30 + 20 * 30)   # 2200 mm²


# --- refusals: no OCP required ------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("part.step", "step"), ("part.STP", "step"), ("part.stp", "step"),
    ("mesh.stl", "stl"), ("MESH.STL", "stl"),
    ("thing.3mf", "3mf"),
    ("solid.brep", "brep"), ("solid.brp", "brep"),
])
def test_extension_picks_the_reader(name, kind):
    assert importers.kind_for(name) == kind


@pytest.mark.parametrize("name", [
    "scene.glb", "scene.gltf", "mesh.obj",
    "design.f3d", "part.sldprt", "part.ipt",
    "legacy.iges", "legacy.igs",
])
def test_named_formats_are_refused_with_their_reason(name):
    """These are declined on purpose, and the message has to say which and why.

    GLB is the one that surprises people, because the engine *exports* it. build123d
    writes glTF and does not read it, so accepting a .glb here would mean adding a
    parser to the one container whose whole argument is that it has very few.
    """
    with pytest.raises(importers.ImportRejected) as exc:
        importers.kind_for(name)
    assert exc.value.code == "import_unsupported_format"
    ext = os.path.splitext(name)[1].lstrip(".")
    assert ext.lower() in exc.value.message.lower()


def test_unknown_extension_lists_what_is_supported():
    with pytest.raises(importers.ImportRejected) as exc:
        importers.kind_for("notes.txt")
    for fmt in ("STEP", "STL", "3MF", "BREP"):
        assert fmt in exc.value.message


@pytest.mark.parametrize("name", ["../../etc/passwd.step", "/etc/passwd.step"])
def test_a_path_is_still_only_read_for_its_extension(name):
    """`kind_for` looks at nothing but the suffix, so a path cannot smuggle a reader.

    Containment itself is enforced twice more — the parent writes only a basename into
    the workdir, and the child refuses a job whose asset name is not its own basename.
    This asserts the first layer does not quietly do something else.
    """
    assert importers.kind_for(name) == "step"


def test_error_codes_covers_every_code_the_module_raises():
    """The HTTP layer answers 400 for exactly these and 500 for anything else.

    A new refusal added without listing it in ERROR_CODES would tell the user their
    perfectly fixable file caused a server error — so the list is checked against the
    source rather than trusted.
    """
    # Explicit encoding, not the platform default: importing OCP sets the C locale, so
    # this same read succeeds when the file is run alone and raises UnicodeDecodeError
    # on the module's em-dashes once any other test in the suite has pulled in the
    # geometry kernel first.
    src = pathlib.Path(importers.__file__).read_text(encoding="utf-8")
    raised = set(re.findall(r'ImportRejected\(\s*\n?\s*"([a-z_]+)"', src))
    assert raised <= importers.ERROR_CODES, raised - importers.ERROR_CODES
    assert importers.ERROR_CODES <= raised, importers.ERROR_CODES - raised


def test_empty_file_is_refused(tmp_path):
    p = tmp_path / "empty.step"
    p.write_bytes(b"")
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("step", str(p))
    assert exc.value.code == "import_malformed"


def test_oversize_file_is_refused_before_it_is_hashed(tmp_path, monkeypatch):
    """The cap is checked against the stat size, so a huge file is never read."""
    monkeypatch.setattr(importers, "MAX_ASSET_BYTES", 1024)
    p = tmp_path / "big.stl"
    p.write_bytes(b"\0" * 4096)
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("stl", str(p))
    assert exc.value.code == "import_too_large"


def test_a_step_extension_over_non_step_bytes_is_refused(tmp_path):
    """Content is checked against what the extension claimed.

    Without this, a ZIP named .step would be handed to the STEP reader — a file
    choosing which parser gets to look at it is precisely the thing to prevent.
    """
    p = tmp_path / "trojan.step"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("step", str(p))
    assert exc.value.code == "import_malformed"


def _binary_stl(count: int, body: bytes) -> bytes:
    return b"\0" * 80 + struct.pack("<I", count) + body


def test_an_stl_header_that_lies_is_refused(tmp_path):
    """Header says 1000 triangles, file holds one. OCCT would allocate on the claim."""
    p = tmp_path / "liar.stl"
    p.write_bytes(_binary_stl(1000, b"\0" * 50))
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("stl", str(p))
    assert exc.value.code == "import_malformed"
    assert "1000" in exc.value.message


def test_an_stl_over_the_triangle_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(importers, "MAX_STL_TRIANGLES", 4)
    p = tmp_path / "dense.stl"
    p.write_bytes(_binary_stl(8, b"\0" * (8 * 50)))
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("stl", str(p))
    assert exc.value.code == "import_too_complex"


def test_a_truncated_stl_is_refused(tmp_path):
    p = tmp_path / "stub.stl"
    p.write_bytes(b"\0" * 40)
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("stl", str(p))
    assert exc.value.code == "import_malformed"


def test_a_3mf_that_is_not_a_zip_is_refused(tmp_path):
    p = tmp_path / "fake.3mf"
    p.write_bytes(b"not a container at all")
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("3mf", str(p))
    assert exc.value.code == "import_malformed"


def test_a_decompression_bomb_is_refused(tmp_path):
    """Read from the central directory. Nothing is inflated to find this out."""
    p = tmp_path / "bomb.3mf"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("3D/3dmodel.model", "A" * (8 * 1024 * 1024))
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("3mf", str(p))
    assert exc.value.code in ("import_malformed", "import_too_large")


def test_too_many_zip_entries_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(importers, "MAX_ZIP_ENTRIES", 4)
    p = tmp_path / "many.3mf"
    with zipfile.ZipFile(p, "w") as zf:
        for i in range(10):
            zf.writestr(f"part{i}.xml", "x")
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("3mf", str(p))
    assert exc.value.code == "import_too_complex"


def test_an_unsafe_member_path_is_refused(tmp_path):
    p = tmp_path / "escape.3mf"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("../../etc/passwd", "x")
    with pytest.raises(importers.ImportRejected) as exc:
        importers.precheck("3mf", str(p))
    assert exc.value.code == "import_malformed"
    assert "unsafe member path" in exc.value.message


def test_precheck_records_the_digest_and_size(tmp_path):
    p = tmp_path / "mesh.stl"
    blob = _binary_stl(1, b"\0" * 50)
    p.write_bytes(blob)
    facts = importers.precheck("stl", str(p))
    import hashlib
    assert facts["sha256"] == hashlib.sha256(blob).hexdigest()
    assert facts["bytes"] == len(blob)
    assert facts["declared_triangles"] == 1


def test_an_assembly_is_refused_rather_than_silently_truncated():
    """Keeping shapes[0] would drop the rest of the user's file without saying so."""
    with pytest.raises(importers.ImportRejected) as exc:
        importers._as_one_shape(["a", "b", "c"])
    assert exc.value.code == "import_unsupported_format"
    assert "3 separate bodies" in exc.value.message


def test_no_geometry_is_refused():
    with pytest.raises(importers.ImportRejected) as exc:
        importers._as_one_shape([])
    assert exc.value.code == "import_empty"


# --- loading: needs the kernel ------------------------------------------------

@pytest.fixture(scope="module")
def box():
    from build123d import Box
    return Box(*BOX)


def _write(part, path, fmt):
    from build123d import Mesher, export_step, export_stl
    if fmt == "step":
        export_step(part, path)
    elif fmt == "stl":
        export_stl(part, path)
    elif fmt == "3mf":
        m = Mesher()
        m.add_shape(part)
        m.write(path)
    else:                                   # pragma: no cover
        raise AssertionError(fmt)


def test_step_round_trips_as_an_exact_solid(box, tmp_path):
    """The load-bearing claim about STEP: the volume survives, to every digit."""
    p = str(tmp_path / "part.step")
    _write(box, p, "step")
    facts = importers.precheck("step", p)
    shape, prov = importers.load("step", p, facts=facts)

    assert prov["exact"] is True
    assert prov["solid_count"] == 1
    assert prov["recovered_features"] is False
    assert prov["sha256"] == facts["sha256"]
    assert abs(shape.volume - BOX_VOLUME) < 1e-6


def test_step_provenance_says_the_history_did_not_come_with_it(box, tmp_path):
    """An exact body is not an editable feature tree, and the note has to say so."""
    p = str(tmp_path / "part.step")
    _write(box, p, "step")
    _shape, prov = importers.load("step", p, facts=importers.precheck("step", p))
    assert any("history" in n for n in prov["notes"])


def test_stl_comes_back_as_a_face_with_no_volume(box, tmp_path):
    """This is why imports get their own verdict.

    An STL is a triangle soup. Asserting "one solid, positive volume" on it — which is
    exactly what the authored-geometry verdict does — would fail a perfectly good file
    for being an STL.
    """
    p = str(tmp_path / "mesh.stl")
    _write(box, p, "stl")
    shape, prov = importers.load("stl", p, facts=importers.precheck("stl", p))

    assert prov["exact"] is False
    assert prov["solid_count"] == 0
    assert abs(shape.area - BOX_AREA) < 1e-3


def test_3mf_is_rebuilt_into_a_solid_by_lib3mf(box, tmp_path):
    """A closed shell goes in and a solid comes out — measured, not assumed.

    3MF sits between the two: mesh resolution, but lib3mf hands back something OCCT
    treats as a solid. `exact` stays False because the triangles are whatever the
    exporter chose, and the volume is a tessellation of the original, not the original.
    """
    p = str(tmp_path / "part.3mf")
    _write(box, p, "3mf")
    shape, prov = importers.load("3mf", p, facts=importers.precheck("3mf", p))

    assert prov["exact"] is False
    assert prov["solid_count"] == 1
    # A box tessellates without loss; a curve would not, which is why this tolerance
    # is not a general claim about 3MF fidelity.
    assert abs(shape.volume - BOX_VOLUME) < 1e-3


def test_a_corrupt_step_body_reports_the_format_not_occt_internals(tmp_path):
    """Structurally plausible, semantically garbage. The message must stay safe."""
    p = tmp_path / "corrupt.step"
    p.write_bytes(b"ISO-10303-21;\nHEADER;\n" + b"#1=NONSENSE(#2);\n" * 20 + b"END;")
    facts = importers.precheck("step", str(p))
    with pytest.raises(importers.ImportRejected) as exc:
        importers.load("step", str(p), facts=facts)
    assert exc.value.code == "import_malformed"
    assert str(tmp_path) not in exc.value.message


# --- the verdict that goes with them ------------------------------------------

def test_import_verdict_does_not_demand_a_volume_from_a_mesh():
    metrics = {"brep_valid": False, "solid_count": 0, "volume_mm3": 0.0,
               "bbox_mm": {"x": 10.0, "y": 20.0, "z": 30.0}}
    ok, problems = validation.import_verdict(metrics, {"parsed": True,
                                                       "watertight": False},
                                             exact=False)
    assert ok, problems


def test_import_verdict_still_demands_a_valid_solid_from_a_step():
    metrics = {"brep_valid": False, "solid_count": 1, "volume_mm3": 6000.0,
               "bbox_mm": {"x": 10.0, "y": 20.0, "z": 30.0}}
    ok, problems = validation.import_verdict(metrics, {}, exact=True)
    assert not ok
    assert any("B-Rep" in p for p in problems)


def test_import_verdict_refuses_a_degenerate_bounding_box():
    """The one check that survives for every format: it has to measure as something."""
    metrics = {"brep_valid": True, "solid_count": 1, "volume_mm3": 1.0,
               "bbox_mm": {"x": 10.0, "y": 0.0, "z": 30.0}}
    ok, problems = validation.import_verdict(metrics, {}, exact=False)
    assert not ok
    assert any("bounding box y" in p for p in problems)


def test_the_authored_verdict_would_have_failed_that_same_mesh():
    """The negative control. Without it, the previous tests prove nothing new.

    If `verdict` also passed an STL's metrics, `import_verdict` would be a redundant
    copy rather than a different policy.
    """
    metrics = {"brep_valid": False, "solid_count": 0, "volume_mm3": 0.0,
               "bbox_mm": {"x": 10.0, "y": 20.0, "z": 30.0}}
    ok, _problems = validation.verdict(metrics, {"parsed": True, "watertight": False},
                                       expected_solids=1)
    assert not ok
