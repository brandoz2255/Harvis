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

from .docs_blocks import Block, ListItem, Run, csv_table, inline_runs, parse_blocks, split_notes
from .docs_chips import ACCENT, DARK, INK, MUTED, TONE_COLORS, TONE_TINTS
from .docs_fonts import font_stack, has_real_italic, has_real_mono_italic
from .docs_parse import ParsedDoc
from .docs_rich import rich_as_rows
from .docs_svg import svg_markup, svg_size

DOC_FIT = (640, 880, 640)           # layout width, tallest figure, shown width: an A4 page holds about 950px of it
DECK_FIT = (860, 430, 1120)
_CHECK = {True: "\u2611", False: "\u2610"}

def _fonts() -> tuple[str, str]:
    """(body, code) font-family lists; a CJK font is added when the image has one, so asked for on first use."""
    return (font_stack("DejaVu Sans", "Helvetica Neue", "Helvetica", "Arial", "sans-serif"),
            font_stack("DejaVu Sans Mono", "Consolas", "monospace"))


def _base_css() -> str:
    body_font, mono_font = _fonts()
    return f"""
body {{ font-family: {body_font}; color: #1f2937; line-height: 1.5; margin: 0; }}
a {{ color: #1d4ed8; text-decoration: none; }}
code {{ font-family: {mono_font}; font-size: 0.9em; background: #f1f5f9; padding: 0 2px; }}
pre {{ font-family: {mono_font}; font-size: 8.5pt; background: #f1f5f9; padding: 8px 10px; border-radius: 3px;
       white-space: pre-wrap; word-wrap: break-word; page-break-inside: avoid; }}
pre code {{ background: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.6em 0; }}
th, td {{ border: 1px solid #cbd5e1; padding: 4px 8px; text-align: left; vertical-align: top; }}
th {{ background: #dde7f3; }}
tr {{ page-break-inside: avoid; }}
blockquote {{ margin: 0.6em 0; padding-left: 12px; border-left: 3px solid #94a3b8; color: #475569; }}
hr {{ border: 0; border-top: 1px solid #cbd5e1; }}
h1, h2, h3, h4 {{ page-break-after: avoid; line-height: 1.25; }}
li.task {{ list-style: none; margin-left: -1.3em; }}
.chip {{ display: inline-block; padding: 0 7px; border-radius: 9px; font-size: 0.85em; font-weight: bold; }}
.math {{ font-family: {mono_font}; text-align: center; white-space: pre-wrap; margin: 0.7em 0; padding: 6px;
         background: #f1f5f9; border-radius: 3px; }}
figure.rich {{ margin: 0.8em 0; page-break-inside: avoid; }}
figure.rich svg {{ display: block; }}
{"".join(f".chip-{t} {{ color: #{c}; background: #{TONE_TINTS[t]}; }}" for t, c in TONE_COLORS.items())}
"""

def _doc_css() -> str:
    body_font, _ = _fonts()
    return f"""
@page {{ size: A4; margin: 22mm 20mm 24mm;
         @bottom-center {{ content: counter(page) " / " counter(pages); font: 8pt {body_font}; color: #64748b; }} }}
body {{ font-size: 10.5pt; }}
h1 {{ font-size: 24pt; margin: 0 0 0.5em; }}
h2 {{ font-size: 16pt; margin: 1.3em 0 0.4em; padding-bottom: 3px; border-bottom: 1px solid #cbd5e1; }}
h3 {{ font-size: 13pt; margin: 1em 0 0.3em; }}
h4 {{ font-size: 11pt; margin: 0.9em 0 0.3em; }}
p {{ margin: 0.5em 0; }}
"""

def _deck_css() -> str:
    body_font, _ = _fonts()
    return f"""
@page {{ size: 13.333in 7.5in; margin: 0.6in 0.8in 0.7in;
         @bottom-right {{ content: counter(page); font: 10pt {body_font}; color: #64748b; }} }}
body {{ font-size: 18pt; }}
.slide {{ page-break-after: always; }}
.slide:last-child {{ page-break-after: auto; }}
.slide h1 {{ font-size: 30pt; margin: 0 0 0.5em; padding-bottom: 0.2em; border-bottom: 4px solid #{ACCENT}; color: #{INK}; }}
@page first {{ margin: 0.6in 0.8in 0.7in; background: #{DARK}; @bottom-right {{ content: none; }} }}
.slide.first {{ page: first; padding-top: 1.7in; width: 8.3in; }}
.slide.first h1 {{ font-size: 44pt; border: 0; margin-bottom: 0.2em; color: #fff; }}
.slide.first p, .slide.first li {{ font-size: 22pt; color: #{MUTED}; }}
.slide.first p:first-of-type {{ color: #{ACCENT}; }}
.slide h2, .slide h3 {{ font-size: 20pt; margin: 0.6em 0 0.2em; }}
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


def build_html(doc: ParsedDoc, title: str) -> str:
    if doc.kind == "deck":
        slides = []
        for i, s in enumerate(doc.sections):
            body = parse_blocks(split_notes(s.body)[0])
            heading = escape(s.title or (title if i == 0 else ""))
            slides.append(f'<section class="slide{" first" if i == 0 else ""}">'
                          f"{f'<h1>{heading}</h1>' if heading else ''}{blocks_html(body, min_heading=2, fit=DECK_FIT)}</section>")
        css, content = _deck_css(), "\n".join(slides)
    else:
        parts = [f"<h1>{escape(title)}</h1>"]
        for s in doc.sections:
            if s.title:
                parts.append(f"<h2>{_runs(inline_runs(s.title))}</h2>")
            parts.append(blocks_html(parse_blocks(s.body), min_heading=3))
        css, content = _doc_css(), "\n".join(parts)
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f"<style>{_base_css()}{css}{_ITALIC_FALLBACK if not (has_real_italic() and has_real_mono_italic()) else ''}</style></head><body>{content}</body></html>")


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
