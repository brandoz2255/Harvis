"""Documents and decks to PDF through weasyprint.

The HTML is built from the shared block reader with every string escaped, so no
markup written by the model reaches the renderer. weasyprint is also given a URL
fetcher that refuses everything but ``data:`` URLs: a document cannot make the
server fetch an address.
"""
from __future__ import annotations

from html import escape
from typing import Optional

from weasyprint import HTML

try:                                    # WeasyPrint 68+
    from weasyprint import URLFetcher
except ImportError:                     # older: a plain function is the fetcher
    URLFetcher = None

from .docs_blocks import Block, ListItem, Run, csv_table, inline_runs, parse_blocks, plain_text, split_notes
from .docs_chips import TONE_COLORS, TONE_TINTS
from .docs_fonts import font_stack, has_real_italic, has_real_mono_italic
from .docs_parse import ParsedDoc
from .docs_rich import rich_as_rows
from .docs_svg import svg_markup, svg_size
from .docs_theme import (
    DEFAULT_THEME, Theme, body_size, classify_slide, column_size, font_candidates, font_generic, get_theme, text_stats)

DOC_FIT = (640, 880, 640)           # layout width, tallest figure, shown width: an A4 page holds about 950px of it
DECK_FIT = (860, 430, 1120)
_CHECK = {True: "\u2611", False: "\u2610"}

def _fonts(theme: Theme = DEFAULT_THEME) -> tuple[str, str]:
    """(body, code) font-family lists; a CJK font is added when the image has one, so asked for on first use.

    The theme's body face comes first, then the faces that can stand in for it, then the old DejaVu defaults, so
    a document on a host without the theme's font still draws (as DejaVu) rather than failing."""
    return (font_stack(*font_candidates(theme.body_font), "DejaVu Sans", "Helvetica Neue", "Helvetica", "Arial",
                       font_generic(theme.body_font)),
            font_stack("DejaVu Sans Mono", "Consolas", "monospace"))


def _heading_font(theme: Theme) -> str:
    return font_stack(*font_candidates(theme.heading_font), "DejaVu Sans", "Helvetica Neue", "Helvetica", "Arial",
                      font_generic(theme.heading_font))


def _base_css(theme: Theme = DEFAULT_THEME) -> str:
    body_font, mono_font = _fonts(theme)
    return f"""
body {{ font-family: {body_font}; color: #{theme.ink}; line-height: 1.5; margin: 0; }}
h1, h2, h3, h4 {{ font-family: {_heading_font(theme)}; color: #{theme.ink}; }}
a {{ color: #{theme.accent2}; text-decoration: none; }}
code {{ font-family: {mono_font}; font-size: 0.9em; background: #{theme.card}; padding: 0 2px; }}
pre {{ font-family: {mono_font}; font-size: 8.5pt; background: #{theme.card}; padding: 8px 10px; border-radius: 3px;
       white-space: pre-wrap; word-wrap: break-word; page-break-inside: avoid; }}
pre code {{ background: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.6em 0; }}
th, td {{ border: 1px solid #{theme.line}; padding: 4px 8px; text-align: left; vertical-align: top; }}
th {{ background: #{theme.tint}; }}
tr {{ page-break-inside: avoid; }}
blockquote {{ margin: 0.6em 0; padding-left: 12px; border-left: 3px solid #{theme.accent}; color: #{theme.muted}; }}
hr {{ border: 0; border-top: 1px solid #{theme.line}; }}
h1, h2, h3, h4 {{ page-break-after: avoid; line-height: 1.25; }}
li.task {{ list-style: none; margin-left: -1.3em; }}
.chip {{ display: inline-block; padding: 0 7px; border-radius: 9px; font-size: 0.85em; font-weight: bold; }}
.math {{ font-family: {mono_font}; text-align: center; white-space: pre-wrap; margin: 0.7em 0; padding: 6px;
         background: #{theme.card}; border-radius: 3px; }}
figure.rich {{ margin: 0.8em 0; page-break-inside: avoid; }}
figure.rich svg {{ display: block; }}
{"".join(f".chip-{t} {{ color: #{c}; background: #{TONE_TINTS[t]}; }}" for t, c in TONE_COLORS.items())}
"""

def _doc_css(theme: Theme = DEFAULT_THEME) -> str:
    body_font, _ = _fonts(theme)
    return f"""
@page {{ size: A4; margin: 22mm 20mm 24mm;
         @bottom-center {{ content: counter(page) " / " counter(pages); font: 8pt {body_font}; color: #{theme.muted}; }} }}
body {{ font-size: 10.5pt; }}
h1 {{ font-size: 24pt; margin: 0 0 0.5em; }}
h2 {{ font-size: 16pt; margin: 1.3em 0 0.4em; padding-bottom: 3px; border-bottom: 1px solid #{theme.line}; }}
h3 {{ font-size: 13pt; margin: 1em 0 0.3em; }}
h4 {{ font-size: 11pt; margin: 0.9em 0 0.3em; }}
p {{ margin: 0.5em 0; }}
"""

# The deck page, in inches: the same margins the slides' placeholders use, so a PDF page is the pptx slide.
_PAGE_MARGIN = "0.6in 0.8in 0.7in"


def _deck_css(theme: Theme = DEFAULT_THEME) -> str:
    """One page per slide, 16:9. The title and section pages sit on ``theme.dark`` (or on the ground for a light theme),
    like the pptx; the accent bar under slide titles is a theme option, off unless the theme asks for it."""
    body_font, _ = _fonts(theme)
    dark = theme.title_style == "dark"
    cover_bg = theme.dark if dark else theme.ground
    fg, sub = (theme.ground, theme.accent_on_dark) if dark else (theme.ink, theme.accent)
    meta = theme.on_dark if dark else theme.muted
    bar = f"border-bottom: 4px solid #{theme.accent}; padding-bottom: 0.2em;" if theme.decor else ""
    squares = "".join(f".sq{i} {{ left: {9.75 + (i % 2) * 1.6 - 0.8:.2f}in; top: {2.15 + (i // 2) * 1.6 - 0.6:.2f}in; "
                      f"background: #{c}; }}"
                      for i, c in enumerate((theme.accent, theme.accent2, theme.muted, theme.accent)))
    return f"""
@page {{ size: 13.333in 7.5in; margin: {_PAGE_MARGIN}; background: #{theme.ground};
         @bottom-right {{ content: counter(page); font: 10pt {body_font}; color: #{theme.muted}; }} }}
@page cover {{ margin: {_PAGE_MARGIN}; background: #{cover_bg}; @bottom-right {{ content: none; }} }}
body {{ font-size: 20pt; }}
.slide {{ page-break-after: always; }}
.slide:last-child {{ page-break-after: auto; }}
.slide h1 {{ font-size: 32pt; margin: 0 0 0.5em; {bar} }}
.slide.first, .slide.section, .slide.closing {{ page: cover; }}
.slide.first h1, .slide.section h1, .slide.closing h1 {{ color: #{fg}; border: 0; padding: 0; line-height: 1.1; }}
.slide.first {{ padding-top: 2.8in; }}
.slide.first h1 {{ font-size: 48pt; margin-bottom: 0.3in; }}
.slide.first p, .slide.first li {{ font-size: 14pt; color: #{meta}; margin: 0.1em 0; }}
.slide.first p:first-of-type {{ font-size: 24pt; color: #{sub}; margin-top: 0.1in; }}
.slide.section {{ padding-top: 1.2in; }}
.slide.section h1 {{ font-size: 44pt; margin: 0 0 0.4in; }}
.slide.closing {{ padding-top: 2.4in; text-align: center; }}
.slide.closing h1 {{ font-size: 44pt; margin: 0; }}
.kicker {{ font-size: 28pt; font-weight: bold; color: #{sub}; margin-bottom: 1.15in; }}
.rule {{ width: 1.2in; height: 0.07in; background: #{sub}; }}
.sq {{ position: absolute; width: 1.45in; height: 1.45in; }}
{squares}
.slide h2, .slide h3 {{ font-size: 20pt; margin: 0.6em 0 0.2em; }}
.cols {{ display: flex; gap: 0.5in; }}
.cols .col {{ flex: 1; min-width: 0; }}
.cols h3 {{ margin: 0 0 0.3em; padding-bottom: 0.1em; color: #{theme.accent}; font-size: 22pt; border-bottom: 1px solid #{theme.line}; }}
.stats {{ display: flex; gap: 0.4in; margin-top: 0.3in; }}
.stat {{ flex: 1; min-width: 0; background: #{theme.card}; border: 1px solid #{theme.line}; border-radius: 0.12in;
         padding: 0.3in; min-height: 3.2in; }}
.stat .num {{ font-weight: bold; color: #{theme.accent}; line-height: 1.1; white-space: nowrap; margin-bottom: 0.2in; }}
.stat .num strong {{ font-weight: bold; }}
.stat .cap {{ font-size: 24pt; color: #{theme.ink}; line-height: 1.3; }}
li {{ margin: 0.25em 0; }}
p {{ margin: 0.4em 0; }}
th, td {{ font-size: 14pt; }}
"""


# Used only when the font in use (body or code) has no italic face of its own (docs_fonts.has_real_italic): each
# italic word is skewed, because weasyprint draws the upright face under an Oblique name and nothing slants it.
_ITALIC_FALLBACK = ".fi { display: inline-block; transform: skewX(-12deg); transform-origin: 0 75%; }"


def _italic(r: Run, styled) -> str:
    if (has_real_mono_italic() if r.code else has_real_italic()):
        return f"<em>{styled(escape(r.text))}</em>"
    words = "</span> <span class=\"fi\">".join(styled(escape(w)) for w in r.text.split(" "))
    return f'<em><span class="fi">{words}</span></em>'


def _refuse_remote(url: str, *args, **kwargs):
    """The fetcher for WeasyPrint before 68: data: URLs only."""
    from weasyprint import default_url_fetcher

    if url.lower().startswith("data:"):
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError("PDF export does not fetch remote resources")


def _fetcher():
    return URLFetcher(allowed_protocols=("data",)) if URLFetcher is not None else _refuse_remote


def _runs(runs: list[Run]) -> str:
    out = []
    for r in runs:
        def styled(text: str, r=r) -> str:
            if r.code:
                text = f"<code>{text}</code>"
            if r.bold:
                text = f"<strong>{text}</strong>"
            return text
        text = _italic(r, styled) if r.italic else styled(escape(r.text))
        if r.href:
            text = f'<a href="{escape(r.href, quote=True)}">{text}</a>'
        out.append(text)
    return "".join(out)


def _list(items: list[ListItem]) -> str:
    out: list[str] = []
    stack: list[str] = []
    for it in items:
        tag = "ol" if it.ordered else "ul"
        while len(stack) > it.level + 1:
            out.append(f"</li></{stack.pop()}>")
        if len(stack) == it.level + 1:
            out.append("</li>")
        while len(stack) < it.level + 1:
            out.append(f"<{tag}>")
            stack.append(tag)
        if it.checked is None:
            out.append(f"<li>{_runs(it.runs)}")
        else:
            out.append(f'<li class="task">{_CHECK[it.checked]} {_runs(it.runs)}')
    out.extend(f"</li></{tag}>" for tag in reversed(stack))
    return "".join(out)


def _cell(runs: list[Run], tone) -> str:
    return f'<td><span class="chip chip-{tone}">{_runs(runs)}</span></td>' if tone else f"<td>{_runs(runs)}</td>"


def _table(block: Block) -> str:
    head, *body = block.rows
    tones = block.tones[1:] if block.tones else [[None] * len(head)] * len(body)
    rows = "".join(f"<tr>{''.join(_cell(c, tones[ri][ci] if ci < len(tones[ri]) else None) for ci, c in enumerate(r))}</tr>"
                   for ri, r in enumerate(body))
    return (f"<table><thead><tr>{''.join(f'<th>{_runs(c)}</th>' for c in head)}</tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _rich(b: Block, fit: tuple[float, Optional[float], float]) -> str:
    """The block as an inline SVG figure; if it cannot be drawn, as the table that says the same."""
    try:
        return f'<figure class="rich">{svg_markup(b.rich, b.data, fit[0], fit[1], fit[2])}</figure>'
    except Exception:                                   # noqa: BLE001 - a bad figure must not sink the PDF
        rows = rich_as_rows(b.rich, b.data)
        return _table(Block("table", rows=[[[Run(c)] for c in r] for r in rows])) if rows else ""


def blocks_html(blocks: list[Block], *, min_heading: int = 2,
                fit: tuple[float, Optional[float], float] = DOC_FIT) -> str:
    out = []
    for b in blocks:
        if b.kind == "heading":
            level = min(max(b.level, min_heading), 4)
            out.append(f"<h{level}>{_runs(b.runs)}</h{level}>")
        elif b.kind == "para":
            out.append(f"<p>{_runs(b.runs)}</p>")
        elif b.kind == "list":
            out.append(_list(b.items))
        elif b.kind == "table" and b.rows:
            out.append(_table(b))
        elif b.kind == "code":
            out.append(f"<pre><code>{escape(b.text)}</code></pre>")
        elif b.kind == "quote":
            out.append(f"<blockquote>{_runs(b.runs)}</blockquote>")
        elif b.kind == "rule":
            out.append("<hr>")
        elif b.kind == "math":
            out.append(f'<div class="math">{escape(b.text)}</div>')
        elif b.kind == "rich" and b.rich == "csv":
            csv = csv_table(b.data)
            out.append(_table(csv) if csv.rows else "")
        elif b.kind == "rich":
            out.append(_rich(b, fit))
    return "\n".join(out)


_STAT_WIDTH_PT = {1: 560.0, 2: 300.0, 3: 190.0}      # room for a big number on a card, by how many cards share the row


def _stat_size(text: str, count: int) -> float:
    """pt size for a big number: 72 when it fits the card, smaller (not below 32) for a long figure."""
    return max(32.0, min(72.0, _STAT_WIDTH_PT.get(count, 190.0) / (0.6 * max(len(text), 1))))


def _slide_size(blocks: list[Block]) -> Optional[int]:
    """The body size a slide of text alone is set at (docs_theme.body_size, as the pptx), None to keep the page default.

    Dense slides keep the page default: the PDF does not shrink text to fit, so a larger size could spill a page."""
    if any(b.kind in ("table", "rich") for b in blocks):
        return None
    size = body_size(*text_stats(blocks))
    return size if size > 22 else None


def _deck_slide(i: int, s, title: str, theme: Theme, dividers: int, last: bool = False) -> tuple[str, int]:
    """(html, dividers so far) of one slide; the same layout choices as the pptx writer (docs_theme.classify_slide)."""
    raw = split_notes(s.body)[0]
    body = parse_blocks(raw)
    heading = _runs(inline_runs(s.title)) if s.title else escape(title if i == 0 else "")
    h1 = f"<h1>{heading}</h1>" if heading else ""
    if i == 0:
        squares = "".join(f'<div class="sq sq{k}"></div>' for k in range(4)) if theme.decor else ""
        rule = '<div class="rule"></div>'
        return (f'<section class="slide first">{squares}{h1}{rule}{blocks_html(body, min_heading=2, fit=DECK_FIT)}</section>',
                dividers)
    kind = classify_slide(body, bool(s.title), raw, s.title, last)
    if kind.kind == "section":
        dividers += 1
        return (f'<section class="slide section"><div class="kicker">{dividers:02d}</div>{h1}<div class="rule"></div></section>',
                dividers)
    if kind.kind == "closing":
        return f'<section class="slide closing">{h1}</section>', dividers
    if kind.kind == "columns":
        size = column_size(kind.groups)
        cols = "".join(f'<div class="col"><h3>{_runs(head)}</h3>{blocks_html(blocks, min_heading=3, fit=DECK_FIT)}</div>'
                       for head, blocks in kind.groups)
        return f'<section class="slide">{h1}<div class="cols" style="font-size:{size}pt">{cols}</div></section>', dividers
    if kind.kind == "stats":
        n = len(kind.groups)
        cards = "".join(
            f'<div class="stat"><div class="num" style="font-size:{_stat_size(plain_text(num), n):.0f}pt">{_runs(num)}</div>'
            f'{f"<div class=cap>{_runs(cap)}</div>" if cap else ""}</div>' for num, cap in kind.groups)
        return f'<section class="slide">{h1}<div class="stats">{cards}</div></section>', dividers
    size = _slide_size(body)
    style = f' style="font-size:{size}pt"' if size else ""
    return f'<section class="slide"{style}>{h1}{blocks_html(body, min_heading=2, fit=DECK_FIT)}</section>', dividers


def build_html(doc: ParsedDoc, title: str) -> str:
    theme = get_theme(getattr(doc, "theme", ""))
    if doc.kind == "deck":
        slides, dividers = [], 0
        for i, s in enumerate(doc.sections):
            html, dividers = _deck_slide(i, s, title, theme, dividers, i == len(doc.sections) - 1)
            slides.append(html)
        css, content = _deck_css(theme), "\n".join(slides)
    else:
        parts = [f"<h1>{escape(title)}</h1>"]
        for s in doc.sections:
            if s.title:
                parts.append(f"<h2>{_runs(inline_runs(s.title))}</h2>")
            parts.append(blocks_html(parse_blocks(s.body), min_heading=3))
        css, content = _doc_css(theme), "\n".join(parts)
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f"<style>{_base_css(theme)}{css}{_ITALIC_FALLBACK if not (has_real_italic() and has_real_mono_italic()) else ''}</style></head><body>{content}</body></html>")


def build_pdf(doc: ParsedDoc, title: str) -> bytes:
    return HTML(string=build_html(doc, title), url_fetcher=_fetcher()).write_pdf()


MAX_PNG_PIXELS = 6_000_000                      # a figure is rendered in memory; bound it whatever the input


def svg_to_png(svg: str, scale: float = 3.0) -> bytes:
    """Render one ``svg_markup`` string to PNG bytes: weasyprint to a page the size of the figure, then pypdfium2."""
    import io

    import pypdfium2

    w, h = svg_size(svg)
    scale = min(scale, (MAX_PNG_PIXELS / max(w * h, 1.0)) ** 0.5)
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>@page {{ size: {w:.0f}px {h + 1:.0f}px; margin: 0 }}"
            f"body {{ margin: 0 }} svg {{ display: block }}</style></head><body>{svg}</body></html>")
    pdf = pypdfium2.PdfDocument(HTML(string=html, url_fetcher=_fetcher()).write_pdf())
    out = io.BytesIO()
    pdf[0].render(scale=scale).to_pil().save(out, format="PNG")
    return out.getvalue()
