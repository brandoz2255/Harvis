"""Pixel checks on the page images of a rendered document. Pure Pillow: no model, no network.

``check_pages`` in docs_check reads the text of a rendered page; this module looks at the picture. Per page:

* **blank**: almost nothing but the background colour is drawn;
* **contrast**: text that is hard to read against what is behind it;
* **edge**: content that runs to the very edge of the page.

The background is the most common colour of the page. "Ink" is any pixel that differs from it. Contrast is read at
the edges of the drawing, where the darkest and lightest values in a small window meet: for text that is the text
colour against its background, and a pale fill on a white page (a card with a soft tint) has a gentle edge that is
far outnumbered by the edges of the text on it. ``check_pixels`` never raises: a page that cannot be read is skipped.
"""
from __future__ import annotations

import io
import logging
from typing import Callable, Optional, Sequence

from PIL import Image, ImageChops, ImageFilter

from .docs_check import issue

log = logging.getLogger(__name__)

MAX_PAGES = 20
MIN_SIDE = 100                    # a page image smaller than this in either direction is a thumbnail, too small to judge
MAX_WIDTH = 1600                  # wider page images are shrunk first, so the checks stay fast
INK_DIFF = 24                     # a pixel this much (of 255) off the background colour in any channel is ink
BLANK_INK = 0.0002                # at most this share of ink: the page is blank
SPARSE_INK = 0.003                # less than this: nearly blank
EDGE_RANGE = 16                   # local light/dark spread that counts as the edge of something drawn
EDGE_STRONG = 48                  # spread that counts as content at the page edge
MIN_EDGE_SHARE = 0.0005           # fewer edge pixels than this share of the page: no text to measure
WARN_CONTRAST, ERROR_CONTRAST = 3.0, 1.5
RULE_LENGTH = 64                  # a straight edge run this long (a power of two) is a rule, bar edge or border, not a letter
RULE_THICK = 8                    # edge bands thinner than this (a 1-3 px line is about 5-7 px wide) are rules
EDGE_BAND = 0.012                 # outer share of the page in which drawn content counts as touching the edge
EDGE_MIN_PIXELS = 25
_WINDOW = 5


def _linear(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(a: int, b: int) -> float:
    """WCAG contrast ratio between two grey levels (0-255)."""
    hi, lo = sorted((_linear(a), _linear(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _background(img: Image.Image) -> tuple[int, int, int]:
    """The most common colour, in 3-bit-per-channel buckets, as the average of what fell in the winning bucket."""
    colors = img.getcolors(maxcolors=img.width * img.height) or []
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for n, (r, g, b) in colors:
        acc = buckets.setdefault((r >> 3, g >> 3, b >> 3), [0, 0, 0, 0])
        acc[0] += n
        acc[1] += n * r
        acc[2] += n * g
        acc[3] += n * b
    n, r, g, b = max(buckets.values(), key=lambda a: a[0])
    return round(r / n), round(g / n), round(b / n)


def _ink(img: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """A 0/255 mask of the pixels that differ from the background."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg))
    r, g, b = diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v > INK_DIFF else 0)


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _edges(gray: Image.Image):
    """(max filter, min filter, spread) of the grey page over a small window."""
    top = gray.filter(ImageFilter.MaxFilter(_WINDOW))
    bottom = gray.filter(ImageFilter.MinFilter(_WINDOW))
    return top, bottom, ImageChops.subtract(top, bottom)


def _shift(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    """``mask`` moved by (dx, dy), the space left over black (no wrap-around)."""
    out = Image.new("L", mask.size, 0)
    out.paste(mask, (dx, dy))
    return out


def _grow(mask: Image.Image, length: int, horizontal: bool, erode: bool) -> Image.Image:
    """Erode (a pixel survives only if the next ``length`` pixels along the axis are set; marks the start of each run)
    or dilate (a set pixel spreads over the next ``length`` pixels) a 0/255 mask along one axis. ``length`` is a power
    of two: each step doubles the reach."""
    step = 1
    while step < length:
        shifted = _shift(mask, -step if erode else step, 0) if horizontal else _shift(mask, 0, -step if erode else step)
        mask = ImageChops.darker(mask, shifted) if erode else ImageChops.lighter(mask, shifted)
        step *= 2
    return mask


def _long_runs(mask: Image.Image, horizontal: bool) -> Image.Image:
    """The pixels of ``mask`` that lie on a straight run of at least RULE_LENGTH set pixels along one axis."""
    return _grow(_grow(mask, RULE_LENGTH, horizontal, True), RULE_LENGTH, horizontal, False)


def _without_rules(keep: Image.Image) -> Image.Image:
    """``keep`` (a 0/255 edge mask) minus the thin straight bands in it: gridlines, axes, borders and the straight
    sides of bars. They are long and a few pixels wide; a letter, or the line of text it sits in, is neither."""
    out = keep
    for horizontal in (True, False):
        runs = _long_runs(keep, horizontal)
        thick = _grow(_grow(runs, RULE_THICK, not horizontal, True), RULE_THICK, not horizontal, False)
        out = ImageChops.subtract(out, ImageChops.subtract(runs, thick))
    return out


def _text_contrast(top: Image.Image, bottom: Image.Image, spread: Image.Image, area: int) -> Optional[float]:
    """The median contrast ratio across the edges of the drawing (rules such as gridlines left out), or None when
    there is too little left to measure."""
    keep = _without_rules(spread.point(lambda v: 255 if v >= EDGE_RANGE else 0))
    if _count(keep) < area * MIN_EDGE_SHARE:
        return None
    pairs = Image.merge("RGB", (top, bottom, keep)).getcolors(maxcolors=2 * 256 * 256) or []
    ratios = sorted((contrast_ratio(hi, lo), n) for n, (hi, lo, k) in pairs if k)
    half, seen = sum(n for _r, n in ratios) / 2, 0
    for ratio, n in ratios:
        seen += n
        if seen >= half:
            return ratio
    return None


def _touching(spread: Image.Image) -> list[str]:
    """Sides of the page whose outer band holds drawn content. The filter leaves the outermost two pixels as they
    were, so the band starts just inside them; a flat colour that runs off the page has no edges and is ignored."""
    strong = spread.point(lambda v: 255 if v >= EDGE_STRONG else 0)
    w, h = strong.size
    band_x, band_y = max(3, round(w * EDGE_BAND)), max(3, round(h * EDGE_BAND))
    lo = _WINDOW // 2
    strips = {"left": (lo, lo, lo + band_x, h - lo), "right": (w - lo - band_x, lo, w - lo, h - lo),
              "top": (lo, lo, w - lo, lo + band_y), "bottom": (lo, h - lo - band_y, w - lo, h - lo)}
    return [side for side, box in strips.items() if _count(strong.crop(box)) >= EDGE_MIN_PIXELS]


def check_page(png: bytes) -> Optional[dict]:
    """{ink, contrast, touching} measured on one page image (contrast is None when there is no text to measure);
    None for an image too small to judge."""
    img = Image.open(io.BytesIO(png))
    img.load()
    if min(img.size) < MIN_SIDE:
        return None
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, max(1, round(img.height * MAX_WIDTH / img.width))), Image.LANCZOS)
    if img.mode in ("RGBA", "LA", "P"):                            # transparent areas are the paper, not black
        img = img.convert("RGBA")
        paper = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(paper, img)
    rgb = img.convert("RGB")
    area = rgb.width * rgb.height
    bg = _background(rgb)
    ink = _count(_ink(rgb, bg)) / area
    if ink <= BLANK_INK:
        return {"ink": ink, "contrast": None, "touching": []}
    top, bottom, spread = _edges(rgb.convert("L"))
    return {"ink": ink, "contrast": _text_contrast(top, bottom, spread, area), "touching": _touching(spread)}


def check_pixels(pngs: Sequence[bytes], label: Callable[[int], str], *, last_may_be_short: bool = False) -> list[dict]:
    """Findings for the page images ``pngs`` (page ``i`` is ``label(i)``).

    ``last_may_be_short`` is for documents that flow onto pages: their last page is rarely full, so it is only
    reported when it is blank."""
    out: list[dict] = []
    for i, png in enumerate(list(pngs)[:MAX_PAGES]):
        where = label(i)
        try:
            page = check_page(png)
        except Exception:                                           # noqa: BLE001 - one unreadable image is not the check
            log.warning("pixel check skipped %s", where, exc_info=True)
            continue
        if page is None:
            continue
        if page["ink"] <= BLANK_INK:
            out.append(issue("error", where, "The page is blank: nothing is drawn on it"))
            continue
        if page["ink"] < SPARSE_INK and not (last_may_be_short and i == len(pngs) - 1):
            out.append(issue("warn", where, "The page is nearly blank: almost nothing is drawn on it"))
        ratio = page["contrast"]
        if ratio is not None and ratio < WARN_CONTRAST:
            out.append(issue("error" if ratio < ERROR_CONTRAST else "warn", where,
                             f"The text is hard to read: its contrast with the background is about {ratio:.1f} to 1 "
                             f"(at least {WARN_CONTRAST:.0f} to 1 reads). Use a darker text colour or a lighter background"))
        if page["touching"]:
            out.append(issue("warn", where, f"Content runs to the {' and '.join(page['touching'])} edge of the page. "
                                            "Leave a margin, or shorten what is on it"))
    return out
