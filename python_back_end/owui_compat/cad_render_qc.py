"""Quality control for render evidence (HE-7).

**Nothing in this module can decide a conformance verdict.** Renders corroborate;
measurements decide. The worst thing a check here can say is "this picture is not worth
keeping", and the second worst is a warning printed beside a picture that is.

Three corrections from the review are built into the shape of the file:

**QC runs on the object-mask pass, never on the beauty pass.** The beauty pass carries a
thick cartoon outline, a gradient ground, shadows and translucency — every one of which
defeats "compare against the background colour". The mask is flat per-part id colour on
a reserved background, no lighting and no outline, so counting it is arithmetic rather
than interpretation.

**A perceptual duplicate is a warning, never a rejection.** A jar is a surface of
revolution: its front and its rear views are *supposed* to be nearly identical, and
rejecting one would delete a legitimate view for being correct. When the engine reported
the part rotationally symmetric the warning is suppressed outright.

**Nothing is decoded before it is bounded.** Dimensions come out of the IHDR header,
which is 8 bytes at a known offset, and an image that is too large is refused before
Pillow ever allocates for it.
"""
from __future__ import annotations

import io
import logging
import struct

logger = logging.getLogger(__name__)

# The mask pass paints the scene black and every body a palette colour, so black is
# "nothing here". It is reserved: `cad_render_recipes` never issues it to a part.
BACKGROUND = (0, 0, 0)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A capture is 1280x960 today. The ceiling is generous enough that a retina client or a
# future contact sheet still fits, and small enough that a decode cannot be used to
# exhaust the backend — which is the whole reason it is read from the header first.
MAX_EDGE = 8192
MAX_PIXELS = 16_000_000

# Antialiasing puts a thin band of blended colour along every silhouette, and those
# pixels land nearest to *some* palette entry. A body has to own more than this fraction
# of the frame before it counts as visible, so an edge blend can never invent a part.
MIN_PART_FRACTION = 0.002

# Below this the picture is empty; above it the part is cropped or the camera is inside
# it. Both are framing faults, and framing is the client's to retry.
COVERAGE_MIN = 0.08
COVERAGE_MAX = 0.92

# Two 64-bit dHashes this close are the same picture to a human eye.
DHASH_NEAR = 4


class RenderQcError(ValueError):
    """The bytes are not a mask this module is willing to look at."""


def png_dimensions(blob: bytes) -> tuple[int, int]:
    """Width and height straight out of the IHDR, without decoding anything.

    A PNG's first chunk is required by the format to be IHDR, and its first eight data
    bytes are the two dimensions big-endian. Reading them costs 24 bytes and tells us
    whether decoding is safe — which is the order those two things have to happen in.
    """
    if not blob.startswith(_PNG_MAGIC):
        raise RenderQcError("not a PNG")
    if len(blob) < 33 or blob[12:16] != b"IHDR":
        raise RenderQcError("PNG has no IHDR header")
    width, height = struct.unpack(">II", blob[16:24])
    if width <= 0 or height <= 0:
        raise RenderQcError("PNG reports a zero dimension")
    if width > MAX_EDGE or height > MAX_EDGE or width * height > MAX_PIXELS:
        raise RenderQcError(
            f"mask is {width}x{height}, over the {MAX_EDGE}px / {MAX_PIXELS}px limit")
    return width, height


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = (hex_colour or "").strip().lstrip("#")
    if len(h) != 6:
        raise RenderQcError(f"palette colour {hex_colour!r} is not #rrggbb")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _decode(blob: bytes):
    """Bounded decode to an (h, w, 3) uint8 array."""
    from PIL import Image
    import numpy as np

    png_dimensions(blob)
    # Pillow's own bomb guard stays on and is tightened to our ceiling, so a file whose
    # header lied still cannot get past the decoder.
    prev = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(blob)) as im:
            im.load()
            return np.asarray(im.convert("RGB"), dtype=np.uint8)
    finally:
        Image.MAX_IMAGE_PIXELS = prev


def dhash(blob: bytes) -> int:
    """A 64-bit difference hash of the picture's structure.

    Row-adjacent brightness comparisons on a 9x8 thumbnail: it survives rescaling and
    mild recolouring, which is exactly what "is this the same view twice" needs. It is
    computed on the mask, so a lighting change cannot make two identical framings look
    like two different pictures.
    """
    from PIL import Image
    import numpy as np

    png_dimensions(blob)
    prev = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(blob)) as im:
            small = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    finally:
        Image.MAX_IMAGE_PIXELS = prev
    px = np.asarray(small, dtype=np.int16)
    bits = (px[:, 1:] > px[:, :-1]).flatten()
    out = 0
    for bit in bits:
        out = (out << 1) | int(bit)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def mask_report(blob: bytes, palette: dict[str, str]) -> dict:
    """What the mask actually shows, in the vocabulary the recipe used.

    ``palette`` maps a body's node id to the colour the recipe told the client to paint
    it. Every pixel is attributed to its nearest palette entry — background included —
    because a silhouette is antialiased and an exact-match count would drop the whole
    border. A body only counts as visible once it owns :data:`MIN_PART_FRACTION` of the
    frame, which is what keeps that blended border from inventing one.
    """
    import numpy as np

    px = _decode(blob)
    height, width = px.shape[0], px.shape[1]
    total = int(width) * int(height)

    keys = list(palette)
    # Background is entry 0 so "nearest palette colour" and "is this background" are one
    # comparison rather than two rules that could disagree.
    #
    # int32 throughout, not int16: a channel difference of 255 squares to 65025, which is
    # twice int16's ceiling. In int16 it wraps negative, every distance comes out wrong,
    # and a black frame reports as fully covered.
    colours = np.array([BACKGROUND] + [_rgb(palette[k]) for k in keys], dtype=np.int32)
    flat = px.reshape(-1, 3).astype(np.int32)
    # (pixels, entries) squared distance. Chunked so a 1280x960 frame against a dozen
    # bodies does not allocate a single enormous intermediate.
    nearest = np.empty(flat.shape[0], dtype=np.int32)
    step = 131_072
    for start in range(0, flat.shape[0], step):
        block = flat[start:start + step]
        d = ((block[:, None, :] - colours[None, :, :]) ** 2).sum(axis=2)
        nearest[start:start + step] = d.argmin(axis=1)

    counts = np.bincount(nearest, minlength=len(colours))
    background = int(counts[0])
    coverage = (total - background) / total if total else 0.0

    parts = {}
    for i, key in enumerate(keys, start=1):
        share = int(counts[i]) / total if total else 0.0
        if share >= MIN_PART_FRACTION:
            parts[key] = round(share, 6)

    return {
        "width": int(width),
        "height": int(height),
        "coverage": round(float(coverage), 6),
        "visible_parts": sorted(parts),
        "part_coverage": parts,
        "dhash": dhash(blob),
    }


def verdicts(report: dict, *, expected_visible_parts: list[str] | None = None,
             sibling_dhashes: dict[str, int] | None = None,
             rotationally_symmetric: bool = False,
             exempt_from_similarity: bool = False) -> list[dict]:
    """The QC findings for one mask. At most one of them is a rejection.

    ``sibling_dhashes`` maps the other recipes already stored for this build to their
    hashes. Similarity is only ever reported against pictures of the *same* build, which
    is the only comparison where "these two are the same view" means anything.
    """
    out: list[dict] = []

    if not report.get("visible_parts") and report.get("coverage", 0.0) <= 0.0:
        out.append({
            "code": "render_blank",
            "severity": "reject",
            "detail": "the mask contains no body at all — this is a picture of an empty "
                      "scene, not of the part",
        })
        # Nothing below can say anything useful about an empty frame, and reporting a
        # framing warning on top of a rejection reads as two problems where there is one.
        return out

    coverage = float(report.get("coverage", 0.0))
    if coverage < COVERAGE_MIN or coverage > COVERAGE_MAX:
        out.append({
            "code": "render_framing",
            "severity": "warn",
            "detail": (f"the part fills {coverage:.1%} of the frame, outside the "
                       f"{COVERAGE_MIN:.0%}–{COVERAGE_MAX:.0%} band"),
        })

    if expected_visible_parts is not None:
        want, got = set(expected_visible_parts), set(report.get("visible_parts") or [])
        if want != got:
            missing = sorted(want - got)
            extra = sorted(got - want)
            bits = []
            if missing:
                bits.append(f"{len(missing)} body(s) the recipe expected are not in it")
            if extra:
                bits.append(f"{len(extra)} body(s) are in it that the recipe did not "
                            "expect")
            out.append({
                "code": "render_unexpected_parts",
                "severity": "warn",
                "detail": "the picture does not show what the recipe said it would: "
                          + " and ".join(bits),
                "missing": missing,
                "unexpected": extra,
            })

    mine = report.get("dhash")
    if mine is not None and sibling_dhashes and not exempt_from_similarity:
        if rotationally_symmetric:
            # A surface of revolution photographed from two sides is the same picture
            # because the part is the same from two sides. Warning about it would be
            # warning about the geometry being correct.
            return out
        near = sorted(k for k, h in sibling_dhashes.items()
                      if hamming(int(h), int(mine)) <= DHASH_NEAR)
        if near:
            out.append({
                "code": "render_similar",
                "severity": "warn",
                "detail": "near-identical to " + ", ".join(near)
                          + " — a second angle would show more",
                "similar_to": near,
            })
    return out


def rejected(findings: list[dict]) -> dict | None:
    """The one finding that means "do not keep this picture", or None."""
    for f in findings or []:
        if f.get("severity") == "reject":
            return f
    return None
