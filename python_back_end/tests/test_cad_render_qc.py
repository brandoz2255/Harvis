"""Render QC: what a picture can and cannot be blamed for (HE-7).

The old check for a blank render compared the frame against a background colour, on the
beauty pass, which carries a thick cartoon outline, a gradient ground and shadows. It
could be fooled in both directions. Every test here is a case that check either got
wrong or could not express at all.

The invariant the whole gate rests on is asserted first and last: **no finding in this
module can fail a build.** `render_blank` refuses to keep one picture. Everything else is
a warning printed beside a picture that is kept.

Loaded by file path for the same reason as the conformance tests: the module under test
has no fastapi, asyncpg or pydantic in it, and importing the package would make a
pure-logic test fail for reasons unrelated to the logic.
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import struct
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


qc = _load("cad_render_qc")

pytest.importorskip("PIL", reason="Pillow is what decodes the mask")
pytest.importorskip("numpy", reason="the coverage arithmetic runs on numpy")

BODY = "node_aaaaaaaaaaaaaaaa"
LID = "node_bbbbbbbbbbbbbbbb"
PALETTE = {BODY: "#FF0000", LID: "#00FF00"}

W, H = 160, 120


def _png(draw) -> bytes:
    """A mask of the size the viewport produces, painted by `draw(pixels)`."""
    from PIL import Image
    import numpy as np

    px = np.zeros((H, W, 3), dtype=np.uint8)
    draw(px)
    out = io.BytesIO()
    Image.fromarray(px, mode="RGB").save(out, format="PNG")
    return out.getvalue()


def _rect(px, colour, x0, y0, x1, y1):
    px[y0:y1, x0:x1] = colour


def _blank() -> bytes:
    return _png(lambda px: None)


def _one_body(frac=0.4, colour=(255, 0, 0)) -> bytes:
    """One body filling roughly `frac` of the frame."""
    side = int((W * H * frac) ** 0.5)
    return _png(lambda px: _rect(px, colour, 10, 10, 10 + side, 10 + side))


# ---------------------------------------------------------------------------
# Bounded before decoded
# ---------------------------------------------------------------------------

def test_dimensions_come_out_of_the_header_not_the_decoder():
    assert qc.png_dimensions(_blank()) == (W, H)


def test_a_declared_giant_is_refused_before_a_single_pixel_is_allocated():
    """The IHDR is 25 bytes in and says how big the image claims to be. A file that
    claims 30000x30000 is refused there — Pillow is never asked to open it, so the
    allocation the refusal is protecting against never happens."""
    blob = bytearray(_blank())
    blob[16:24] = struct.pack(">II", 30000, 30000)
    with pytest.raises(qc.RenderQcError) as e:
        qc.png_dimensions(bytes(blob))
    assert "limit" in str(e.value)


def test_a_header_that_lies_still_cannot_get_past_the_decoder():
    """The dimension guard is on the header, so a file whose header understates its
    real size would slip past it. Pillow's own bomb guard is tightened to the same
    ceiling for exactly that case, and restored afterwards."""
    from PIL import Image
    before = Image.MAX_IMAGE_PIXELS
    qc.mask_report(_one_body(), PALETTE)
    assert Image.MAX_IMAGE_PIXELS == before


def test_something_that_is_not_a_png_is_refused_by_name():
    with pytest.raises(qc.RenderQcError):
        qc.png_dimensions(b"GIF89a" + b"\x00" * 40)


# ---------------------------------------------------------------------------
# What the mask says
# ---------------------------------------------------------------------------

def test_an_empty_frame_is_rejected_and_says_so_in_one_finding():
    report = qc.mask_report(_blank(), PALETTE)
    assert report["coverage"] == 0.0
    assert report["visible_parts"] == []

    found = qc.verdicts(report, expected_visible_parts=[BODY, LID])
    assert [f["code"] for f in found] == ["render_blank"]
    assert qc.rejected(found)["code"] == "render_blank"


def test_a_blank_frame_does_not_also_get_scolded_for_framing():
    """0% coverage is outside the framing band too. Reporting both would read as two
    problems where there is one, and the framing retry would run on a picture that has
    nothing to reframe."""
    found = qc.verdicts(qc.mask_report(_blank(), PALETTE))
    assert len(found) == 1


def test_each_body_is_counted_separately_by_its_own_colour():
    blob = _png(lambda px: (_rect(px, (255, 0, 0), 0, 0, 80, 60),
                            _rect(px, (0, 255, 0), 80, 0, 120, 60)))
    report = qc.mask_report(blob, PALETTE)
    assert report["visible_parts"] == sorted([BODY, LID])
    assert report["part_coverage"][BODY] == pytest.approx(0.25, abs=0.01)
    assert report["part_coverage"][LID] == pytest.approx(0.125, abs=0.01)


def test_an_antialiased_edge_cannot_invent_a_body():
    """The thing that makes exact-colour counting useless. Along a silhouette the renderer
    blends, and those blended pixels are nearest to *some* palette entry — an exact-match
    counter would drop the whole border, and a nearest-match counter with no floor would
    report a body that is not in the picture. The area floor is what stops the second.

    The band here is a one-pixel hairline down 30 rows: 30 of 19200 pixels, 0.16%, under
    the 0.2% floor. That is the ratio a boundary actually has — at a 1280x960 capture a
    one-pixel edge a thousand rows long is 0.08% of the frame — and a floor low enough to
    let a genuinely thin part through (a lid seen edge-on is nearer 1%) is the same floor.
    """
    def draw(px):
        _rect(px, (255, 0, 0), 20, 20, 120, 100)
        _rect(px, (40, 200, 40), 119, 20, 120, 50)   # the blend down the shared edge
    report = qc.mask_report(_png(draw), PALETTE)
    assert report["visible_parts"] == [BODY]


def test_a_thin_part_the_floor_must_not_swallow():
    """The other side of the same number. A lid seen edge-on is a sliver, and a floor set
    high enough to be comfortable about edge blends would delete it from the report."""
    def draw(px):
        _rect(px, (255, 0, 0), 20, 20, 120, 100)
        _rect(px, (0, 255, 0), 20, 12, 120, 20)      # an 8px-tall lid: 4% of the frame
    report = qc.mask_report(_png(draw), PALETTE)
    assert report["visible_parts"] == sorted([BODY, LID])


def test_a_body_the_recipe_expected_and_did_not_get_is_a_warning_not_a_rejection():
    report = qc.mask_report(_one_body(), PALETTE)
    found = qc.verdicts(report, expected_visible_parts=[BODY, LID])
    assert qc.rejected(found) is None
    miss = next(f for f in found if f["code"] == "render_unexpected_parts")
    assert miss["severity"] == "warn"
    assert miss["missing"] == [LID]
    assert miss["unexpected"] == []


def test_a_body_in_the_picture_that_the_recipe_did_not_expect_is_named_too():
    blob = _png(lambda px: (_rect(px, (255, 0, 0), 0, 0, 80, 60),
                            _rect(px, (0, 255, 0), 80, 0, 130, 60)))
    found = qc.verdicts(qc.mask_report(blob, PALETTE), expected_visible_parts=[BODY])
    extra = next(f for f in found if f["code"] == "render_unexpected_parts")
    assert extra["unexpected"] == [LID]
    assert extra["missing"] == []


def test_a_well_framed_picture_of_what_was_asked_for_reports_nothing():
    blob = _png(lambda px: (_rect(px, (255, 0, 0), 10, 10, 110, 100),
                            _rect(px, (0, 255, 0), 110, 10, 140, 100)))
    found = qc.verdicts(qc.mask_report(blob, PALETTE),
                        expected_visible_parts=[BODY, LID])
    assert found == []


def test_a_part_filling_the_whole_frame_is_a_framing_warning():
    blob = _png(lambda px: _rect(px, (255, 0, 0), 0, 0, W, H))
    found = qc.verdicts(qc.mask_report(blob, PALETTE), expected_visible_parts=[BODY])
    codes = [f["code"] for f in found]
    assert "render_framing" in codes
    assert qc.rejected(found) is None


def test_a_speck_in_the_corner_is_a_framing_warning_not_a_blank():
    """Coverage above zero means something was rendered, so the honest verdict is that
    the camera is wrong — a retry can fix that, and deleting the picture cannot."""
    blob = _png(lambda px: _rect(px, (255, 0, 0), 0, 0, 12, 12))
    found = qc.verdicts(qc.mask_report(blob, PALETTE), expected_visible_parts=[BODY])
    assert [f["code"] for f in found] == ["render_framing"]


# ---------------------------------------------------------------------------
# Similarity is a warning, and sometimes not even that
# ---------------------------------------------------------------------------

def test_two_pictures_of_the_same_framing_hash_the_same():
    a, b = _one_body(), _one_body()
    assert qc.hamming(qc.dhash(a), qc.dhash(b)) == 0


def test_a_genuinely_different_view_does_not_read_as_a_duplicate():
    tall = _png(lambda px: _rect(px, (255, 0, 0), 60, 5, 100, 115))
    wide = _png(lambda px: _rect(px, (255, 0, 0), 5, 45, 155, 75))
    assert qc.hamming(qc.dhash(tall), qc.dhash(wide)) > qc.DHASH_NEAR


def test_a_duplicate_is_a_warning_and_never_a_rejection():
    report = qc.mask_report(_one_body(), PALETTE)
    found = qc.verdicts(report, expected_visible_parts=[BODY],
                        sibling_dhashes={"ev_overview": report["dhash"]})
    dup = next(f for f in found if f["code"] == "render_similar")
    assert dup["severity"] == "warn"
    assert dup["similar_to"] == ["ev_overview"]
    assert qc.rejected(found) is None


def test_a_symmetric_part_gets_no_duplicate_warning_at_all():
    """A jar is a surface of revolution. Its front and its rear are the same picture
    because the part is the same from both sides, and warning about that would be
    warning about the geometry being right."""
    report = qc.mask_report(_one_body(), PALETTE)
    found = qc.verdicts(report, expected_visible_parts=[BODY],
                        sibling_dhashes={"ev_overview": report["dhash"]},
                        rotationally_symmetric=True)
    assert [f["code"] for f in found] == []


def test_the_contact_sheet_is_exempt_from_similarity():
    """It is a composite of four views that each have their own recipe, so it is
    supposed to look like them. Comparing it to them would report its purpose."""
    report = qc.mask_report(_one_body(), PALETTE)
    found = qc.verdicts(report, expected_visible_parts=[BODY],
                        sibling_dhashes={"ev_overview": report["dhash"]},
                        exempt_from_similarity=True)
    assert [f["code"] for f in found] == []


def test_similarity_is_only_reported_against_pictures_it_was_given():
    report = qc.mask_report(_one_body(), PALETTE)
    assert qc.verdicts(report, expected_visible_parts=[BODY],
                       sibling_dhashes={}) == []


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blob,expected", [
    (_blank(), [BODY, LID]),
    (_one_body(), [BODY, LID]),
    (_one_body(frac=0.99), [BODY]),
    (_png(lambda px: _rect(px, (255, 0, 0), 0, 0, 4, 4)), [BODY]),
])
def test_at_most_one_finding_is_ever_a_rejection(blob, expected):
    """And a rejection only ever means "do not keep this picture". There is no severity
    in this module that reaches a conformance verdict, which is the invariant the whole
    gate rests on: measurements decide whether the part is right, renders corroborate."""
    found = qc.verdicts(qc.mask_report(blob, PALETTE), expected_visible_parts=expected,
                        sibling_dhashes={"other": 0})
    rejects = [f for f in found if f["severity"] == "reject"]
    assert len(rejects) <= 1
    assert {f["severity"] for f in found} <= {"reject", "warn"}
