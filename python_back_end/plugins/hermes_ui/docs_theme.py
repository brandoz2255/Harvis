"""Themes for decks and documents, and the slide layouts that read them.

A ``Theme`` is the one place a document's look is decided: the palette, the heading and body font, and whether
the title slide is dark or light. The pptx, PDF and docx writers all read the same tokens, so a deck and its PDF
come out as the same design. The ``harvis`` preset is the palette of ``docs_chips`` (what every export used before
themes existed); a ``theme:`` line in the block header picks another preset by name, and an unknown name is the
default rather than an error. Colors are bare hex (no leading ``#``).

This module also holds the decisions both a pptx slide and a PDF page make from a slide's content (is it a section
divider, two columns, a row of big numbers, and how large may its text be), so the two stay in step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

from .docs_blocks import Block, Run, inline_runs, plain_text
from .docs_chips import ACCENT, ACCENT2, CARD, DARK, GROUND, INK, LINE, MUTED, SERIES

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    heading_font: str
    body_font: str
    ink: str                    # headings, body text, table header fill
    ground: str                 # slide background
    dark: str                   # title and section slide background
    accent: str                 # badges, rules, big numbers, headings of columns and quadrants
    accent2: str                # links (in the pptx, PDF and docx alike, and the theme's hlink), second series
    muted: str                  # secondary text on the ground
    card: str                   # card and zebra-row fill
    line: str                   # hairlines and borders
    tint: str                   # table header fill in documents
    on_dark: str                # secondary text on ``dark``
    accent_on_dark: str         # accent text on ``dark``
    series: tuple[str, ...] = SERIES
    accent_tint: str = "E3F5F3"  # the highlighted cell of a quadrant
    title_style: str = "dark"   # "dark": the title slide sits on ``dark``; "light": on ``ground``
    decor: bool = False         # the accent bar under slide titles and the squares on the title slide


DEFAULT_THEME = Theme(
    "harvis", "Harvis", "Calibri", "Calibri", INK, GROUND, DARK, ACCENT, ACCENT2, MUTED, CARD, LINE,
    "DDE7F3", "A9B6C8", ACCENT)

PRESETS: dict[str, Theme] = {t.name: t for t in (
    DEFAULT_THEME,
    Theme("paper", "Paper", "Georgia", "Calibri", "2A2118", "FBF8F2", "2A2118", "B4532A", "3C6E5A", "6B5E50",
          "F1EBDF", "DDD3C2", "EADFCB", "CDBFA8", "E0875B",
          ("B4532A", "3C6E5A", "D9A441", "7C5A8F", "4E7C9B", "8C7B66"), accent_tint="F6E3D8", title_style="light"),
    Theme("slate", "Slate", "Arial", "Arial", "1B2635", "FFFFFF", "16253B", "2B6CB0", "C05621", "566377",
          "EEF2F7", "D3DBE6", "DCE6F2", "AFC0D8", "7FB2F0",
          ("2B6CB0", "C05621", "2F855A", "805AD5", "B7791F", "718096"), accent_tint="DDE9F7"),
    Theme("ember", "Ember", "Trebuchet MS", "Calibri", "211A17", "FFFFFF", "1E1715", "C2410C", "0F766E", "625650",
          "F6F1EE", "E3D9D3", "F0DFD5", "D2C0B6", "F59E6C",
          ("C2410C", "0F766E", "CA8A04", "9F1239", "4F46E5", "78716C"), accent_tint="FBE5D8"),
    Theme("forest", "Forest", "Cambria", "Calibri", "14281F", "F7FAF6", "10281D", "2F7D4F", "9A6B13", "4F6256",
          "E9F1EA", "CFDCD2", "D8E8DC", "A9C7B4", "7FCB9E",
          ("2F7D4F", "9A6B13", "2B6CB0", "A8442F", "6B5B95", "6B7F73"), accent_tint="DCEEE2"),
    Theme("mono", "Mono", "Arial", "Arial", "111111", "FFFFFF", "111111", "3A3A3A", "6B6B6B", "595959",
          "F2F2F2", "D4D4D4", "E2E2E2", "BDBDBD", "E0E0E0",
          ("222222", "6E6E6E", "A0A0A0", "444444", "8A8A8A", "C4C4C4"), accent_tint="E6E6E6", title_style="light"),
)}
THEME_NAMES = tuple(PRESETS)


def normalize_theme_name(name: Optional[str]) -> str:
    """What a ``theme:`` header value says, lowercased and unquoted ("" when absent)."""
    value = (name or "").split(" #")[0].strip()
    if len(value) >= 2 and value[0] in "\"'" and value.endswith(value[0]):
        value = value[1:-1]
    return value.strip().lower()


def get_theme(name: Optional[str]) -> Theme:
    """The preset called ``name``; anything else (None, "", a misspelling) is the default."""
    return PRESETS.get(normalize_theme_name(name), DEFAULT_THEME)


# ---- fonts -----------------------------------------------------------------------------------------------------

# The generic family a font falls back to, and metric-compatible faces that stand in for it where it is not
# installed (the PDF is drawn by this server, which rarely has Calibri or Georgia).
FONT_INFO = {
    "Calibri": ("sans-serif", ("Carlito",)),
    "Arial": ("sans-serif", ("Liberation Sans", "Arimo")),
    "Georgia": ("serif", ("Gelasio", "DejaVu Serif")),
    "Cambria": ("serif", ("Caladea", "DejaVu Serif")),
    "Trebuchet MS": ("sans-serif", ()),
}


def font_generic(family: str) -> str:
    return FONT_INFO.get(family, ("sans-serif", ()))[0]


# How much wider than the writers' width estimate (made for Calibri) a face runs, so titles in it are planned narrower.
WIDTH_FACTOR = {"Georgia": 1.1, "Trebuchet MS": 1.04, "Arial": 1.03}


def width_factor(family: str) -> float:
    return WIDTH_FACTOR.get(family, 1.0)


def font_candidates(family: str) -> tuple[str, ...]:
    """The family itself, then the faces that can stand in for it."""
    return (family, *FONT_INFO.get(family, ("sans-serif", ()))[1])


# ---- theme XML (shared by the pptx and docx parts) --------------------------------------------------------------

def restyle_theme_xml(blob: bytes, theme: Theme) -> bytes:
    """The DrawingML theme part with the theme's colour scheme and heading/body fonts written into it."""
    root = etree.fromstring(blob)
    root.set("name", f"Harvis {theme.label}")
    series = (list(theme.series) + list(SERIES))[:6]
    colors = {"dk1": theme.ink, "lt1": theme.ground, "dk2": theme.dark, "lt2": theme.card,
              "accent1": theme.accent, "accent2": theme.accent2, "accent3": series[2], "accent4": series[3],
              "accent5": series[4], "accent6": series[5], "hlink": theme.accent2, "folHlink": theme.muted}
    scheme = root.find(f".//{{{_A}}}clrScheme")
    if scheme is not None:
        scheme.set("name", f"Harvis {theme.label}")
        for slot, value in colors.items():
            el = scheme.find(f"{{{_A}}}{slot}")
            if el is None:
                continue
            for child in list(el):
                el.remove(child)
            etree.SubElement(el, f"{{{_A}}}srgbClr").set("val", value)
    fonts = root.find(f".//{{{_A}}}fontScheme")
    if fonts is not None:
        fonts.set("name", f"Harvis {theme.label}")
        for tag, face in (("majorFont", theme.heading_font), ("minorFont", theme.body_font)):
            latin = fonts.find(f"{{{_A}}}{tag}/{{{_A}}}latin")
            if latin is not None:
                latin.set("typeface", face)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# ---- what a slide's content calls for ---------------------------------------------------------------------------

def body_size(lines: int, chars: int = 0) -> int:
    """The largest body text size, in pt, a slide with this much text starts from (the writer then fits it down).

    A slide with a few short lines is read from across a room, so it gets 28-32pt; a dense one keeps the usual 22."""
    size = 32 if lines <= 3 else 28 if lines <= 5 else 24 if lines <= 7 else 22
    if chars > 600:
        return min(size, 20)
    return min(size, 24) if chars > 400 else min(size, 28) if chars > 260 else size


def text_stats(blocks: list[Block]) -> tuple[int, int]:
    """(lines, characters) of the text in a slide body: list items, paragraphs, headings, quotes, code and math."""
    lines = chars = 0
    for b in blocks:
        if b.kind == "list":
            lines += len(b.items)
            chars += sum(len(plain_text(it.runs)) for it in b.items)
        elif b.kind in ("para", "heading", "quote"):
            lines += 1
            chars += len(plain_text(b.runs))
        elif b.kind in ("code", "math"):
            lines += len(b.text.split("\n"))
            chars += len(b.text)
    return lines, chars


@dataclass
class SlideKind:
    kind: str = "content"       # content | section | closing | columns | stats
    # columns: [(heading runs, blocks)] x 2; stats: [(number runs, caption runs)] x 1-3
    groups: list = field(default_factory=list)


_COLUMN_KINDS = {"heading", "para", "list", "quote", "code", "math"}
MAX_STATS = 3
COLUMN_MIN, COLUMN_MAX = 20, 24     # the PDF cannot shrink text to fit a page, so the pptx starts no larger either


def column_size(groups: list) -> int:
    """The size, in pt, both columns of a two-column slide start at (the pptx then fits it down); the PDF uses it as is."""
    blocks = [b for _head, body in groups for b in body]
    return min(max(body_size(*text_stats(blocks)), COLUMN_MIN), COLUMN_MAX)


_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_SUFFIX = r"[kmb]|bn|[kmgt]b|ms|s|h|x"
_SPACED_UNIT = r"%|[kmbx]|[kmgt]b|ms|(?:sec|min|hr|mo|yr)s?|(?:second|minute|hour|day|week|month|year)s?"
# A figure: a number, with an optional sign or currency before it, a short suffix after it (%, x, M, ms, GB; or a unit
# after a space, like ``3 weeks``) and an optional ``/total``. The suffixes are an explicit list, so a label that merely
# contains a digit (``Q3``, ``Step 1:``) or is an acronym or ordinal (``2FA``, ``3D``, ``5G``, ``1st``, ``3am``) is not one.
_FIGURE_RE = re.compile(
    rf"^[~\u2248<>\u2264\u2265+\-\u2212\u00b1]?[$\u20ac\u00a3\u00a5]?{_NUMBER}"
    rf"(?:%|\u00d7|{_SUFFIX}|\s(?:{_SPACED_UNIT}))?(?:/{_NUMBER})?\+?$", re.I)


def _is_figure(text: str) -> bool:
    text = text.strip()
    return len(text) <= 14 and bool(_FIGURE_RE.match(text))


def is_stat(block: Block) -> bool:
    """A paragraph that is one short bold figure, like ``**42%**`` or ``**$1.2M**``."""
    if block.kind != "para" or not block.runs:
        return False
    if not all(r.bold and not r.code and not r.href for r in block.runs):
        return False
    return _is_figure(plain_text(block.runs))


def _is_figure_run(run: Run) -> bool:
    return run.bold and not run.code and not run.href and _is_figure(run.text)


MAX_CAPTION = 80


def _stat_groups(lines: list[list[Run]]) -> Optional[list]:
    """[(number runs, caption runs)] when the slide is only bold figures with a short caption each, else None.

    ``lines`` holds the inline runs of each source line. A card starts only at a line that opens with a bold figure;
    its caption is the rest of that line, or the one plain line right after a figure-only line (``**42%**``, then
    ``fewer incidents``). A figure in the middle of a line belongs to that sentence, so a slide written that way is
    an ordinary content slide and not two cards."""
    groups: list[list[list[Run]]] = []
    for runs in lines:
        if not runs:
            continue
        if _is_figure_run(runs[0]):
            if all(r.bold and not r.code and not r.href for r in runs) and _is_figure(plain_text(runs)):
                groups.append([runs, []])
            elif any(_is_figure_run(r) for r in runs[1:]):
                return None
            else:
                groups.append([[runs[0]], list(runs[1:])])
        elif groups and not groups[-1][1] and not any(_is_figure_run(r) for r in runs):
            groups[-1][1] = runs
        else:
            return None
    if not groups or len(groups) > MAX_STATS:
        return None
    out = []
    for number, caption in groups:
        caption = list(caption)
        if caption:
            caption[0] = Run(caption[0].text.lstrip(), caption[0].bold, caption[0].italic, caption[0].code, caption[0].href)
            caption[-1] = Run(caption[-1].text.rstrip(), caption[-1].bold, caption[-1].italic, caption[-1].code,
                              caption[-1].href)
        if len(plain_text(caption)) > MAX_CAPTION:
            return None
        out.append((number, caption))
    return out


def _source_lines(blocks: list[Block], body: Optional[str]) -> list[list[Run]]:
    """The inline runs of each source line of a slide made only of paragraphs.

    ``parse_blocks`` joins consecutive lines of a paragraph with spaces, so the line breaks are only known from the
    raw ``body``. Without it each paragraph counts as one line."""
    if body is None:
        return [b.runs for b in blocks]
    return [inline_runs(line.strip()) for line in body.split("\n") if line.strip()]


def _is_closing(title: str) -> bool:
    """A title that ends a talk rather than opens a part: ``Questions?``, ``Thank you!``."""
    return plain_text(inline_runs(title)).rstrip().endswith(("?", "!"))


def classify_slide(blocks: list[Block], has_title: bool = True, body: Optional[str] = None, title: str = "",
                   last: bool = False) -> SlideKind:
    """Which layout a (non-title) slide gets.

    * a title and nothing else is a section divider, or, when it is the last slide of the deck (``last``) or its
      ``title`` ends in ``?`` or ``!``, a closing slide: the title alone, with no running number;
    * exactly two ``###`` headings, each followed by text, are two columns;
    * paragraphs that open with one to three bold figures (each followed by a short caption) are big numbers.

    Anything else, and every slide with a figure or a table in it, is an ordinary content slide.

    ``body`` is the slide's raw markdown (without speaker notes); pass it so a bold figure in the middle of a line is
    not mistaken for the start of another card."""
    if not blocks:
        if not has_title:
            return SlideKind()
        return SlideKind("closing") if last or _is_closing(title) else SlideKind("section")
    if blocks[0].kind == "para" and blocks[0].runs and _is_figure_run(blocks[0].runs[0]):
        stats = _stat_groups(_source_lines(blocks, body)) if all(b.kind == "para" and b.runs for b in blocks) else None
        if stats:
            return SlideKind("stats", stats)
        return SlideKind()
    heads = [i for i, b in enumerate(blocks) if b.kind == "heading"]
    if len(heads) == 2 and heads[0] == 0 and all(b.kind in _COLUMN_KINDS for b in blocks):
        left, right = blocks[1:heads[1]], blocks[heads[1] + 1:]
        if left and right:
            return SlideKind("columns", [(blocks[0].runs, left), (blocks[heads[1]].runs, right)])
    return SlideKind()
