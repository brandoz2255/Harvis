"""A deck block to a .pptx: 16:9, a designed title slide, then bullet slides or one native-shape figure."""
from __future__ import annotations

import io

from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from pptx.util import Inches

from .docs_blocks import Block, Run, csv_table, inline_runs, parse_blocks, plain_text, split_notes
from .docs_chips import ACCENT, ACCENT2, DARK, INK
from .docs_metrics import fit_size, wrap
from .docs_parse import ParsedDoc
from .docs_pptx_graph import draw_flow, draw_timeline
from .docs_pptx_kit import BOTTOM, LEFT, MIDDLE, box, clamp_to_slide, muted, rgb, write_runs
from .docs_pptx_layouts import draw_cards, draw_chart, draw_quadrant, draw_table

SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN_L, BODY_W, BODY_TOP, BODY_BOTTOM = 0.7, 11.9, 1.75, 6.95
BODY_H = BODY_BOTTOM - BODY_TOP
MAX_LEVEL = 4
_FIGURES = ("table", "rich")


def _bullet(paragraph, kind: str) -> None:
    """kind: 'none' (plain text), 'num' (auto-numbered); anything else keeps the layout's bullet."""
    pPr = paragraph._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    if kind == "none":
        pPr.set("marL", "0")
        pPr.set("indent", "0")
        pPr.append(pPr.makeelement(qn("a:buNone"), {}))
    elif kind == "num":
        pPr.append(pPr.makeelement(qn("a:buAutoNum"), {"type": "arabicPeriod"}))


def _text_lines(blocks: list[Block]) -> list[tuple[list[Run], int, str, dict]]:
    """Everything that is not a figure, as (runs, level, bullet kind, style)."""
    lines = []
    for b in blocks:
        if b.kind == "list":
            for it in b.items:
                level = min(it.level, MAX_LEVEL)
                if it.checked is None:
                    lines.append((it.runs, level, "num" if it.ordered else "bullet", {}))
                else:
                    lines.append(([Run("☑ " if it.checked else "☐ "), *it.runs], level, "none", {}))
        elif b.kind == "para":
            lines.append((b.runs, 0, "none", {}))
        elif b.kind == "heading":
            lines.append((b.runs, 0, "none", {"bold": True}))
        elif b.kind == "quote":
            lines.append((b.runs, 0, "none", {"italic": True}))
        elif b.kind == "code":
            lines.extend(([Run(line, code=True)], 0, "none", {}) for line in b.text.split("\n"))
        elif b.kind == "math":
            lines.extend(([Run(line, code=True)], 0, "none", {}) for line in b.text.split("\n"))
    return lines


def _bullet_plan(lines: list, width_in: float, height_in: float):
    """The largest bullet size whose wrapped text fits; at the smallest size trailing lines are dropped."""
    def cost(size: float, row) -> float:
        runs, level, _k, _s = row
        w = (width_in - 0.45 * (level + 1)) * 72
        return (len(wrap(plain_text(runs), w, size - 2 * level)) * (size - 2 * level) * 1.2 + size * 0.45) / 72

    # No row costs less than ~10pt, so lines past what the box can hold are never measured.
    limit = int(height_in * 72 / 10) + 1
    if len(lines) <= limit:
        for size in range(22, 11, -1):
            if sum(cost(size, row) for row in lines) <= height_in:
                return size, lines
    kept, used = 0, 0.0
    for row in lines[:limit]:
        used += cost(12, row)
        if used > height_in and kept:
            break
        kept += 1
    rows = list(lines[:kept])
    if kept < len(lines):
        rows[-1] = ([Run("…")], 0, "none", {})
    return 12, rows


def _fill_text(placeholder, lines: list, top: float, height: float) -> float:
    size, lines = _bullet_plan(lines, BODY_W, height)
    placeholder.left, placeholder.top = Inches(MARGIN_L), Inches(top)
    placeholder.width, placeholder.height = Inches(BODY_W), Inches(height)
    frame = placeholder.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    for i, (runs, level, bullet, style) in enumerate(lines):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.level = level
        _bullet(p, bullet)
        write_runs(p, runs, size - 2 * level, **style)
    return size


def _draw_figure(slide, block: Block, area) -> None:
    if block.kind == "table":
        if block.rows:
            draw_table(slide, block.rows, block.tones, area)
        return
    kind = block.rich
    if kind == "csv":
        csv = csv_table(block.data)
        if csv.rows:
            draw_table(slide, csv.rows, csv.tones, area)
    elif kind == "cards":
        draw_cards(slide, block.data, area)
    elif kind == "timeline":
        draw_timeline(slide, block.data, area)
    elif kind == "quadrant":
        draw_quadrant(slide, block.data, area)
    elif kind == "chart":
        draw_chart(slide, block.data, area)
    elif kind == "flow":
        draw_flow(slide, block.data, area)


MAX_FIGURES = 3                                  # more would each get a strip too thin to read
MIN_FIGURE_H = 3.0                               # a lone figure keeps this much of the slide (2in each when several)


def _fill_body(slide, placeholder, blocks: list[Block]) -> None:
    lines = _text_lines(blocks)
    all_figures = [b for b in blocks if b.kind in _FIGURES]
    figures = all_figures[:MAX_FIGURES if not lines else MAX_FIGURES - 1]      # beside text each needs more room
    area_top, area_bottom = BODY_TOP, BODY_BOTTOM
    if len(all_figures) > len(figures):
        area_bottom -= 0.35
        muted(slide, MARGIN_L, area_bottom + 0.05, BODY_W, 0.3, f"… {len(all_figures) - len(figures)} more not shown",
              12, min_size=9)
    caption = len(figures) == 1 and len(lines) <= 2 and all(not k or k == "none" for _r, _l, k, _s in lines)
    if not lines:
        placeholder._element.getparent().remove(placeholder._element)
    elif caption:
        placeholder._element.getparent().remove(placeholder._element)
        for runs, *_rest in lines:
            muted(slide, MARGIN_L, area_top - 0.05, BODY_W, 0.4, plain_text(runs), 16, min_size=11)
            area_top += 0.42
    else:
        height = area_bottom - BODY_TOP
        if figures:                                   # text yields to the figures, which keep a readable share
            keep = (MIN_FIGURE_H if len(figures) == 1 else 2.0 * len(figures)) + 0.2 * (len(figures) - 1) + 0.15
            height = max(min(0.5 * len(lines) + 0.3, BODY_H * 0.55, height - keep), 0.6)
        _fill_text(placeholder, lines, BODY_TOP, height)
        area_top = BODY_TOP + height + 0.15
    if not figures:
        return
    share = max((area_bottom - area_top - 0.2 * (len(figures) - 1)) / len(figures), 0.5)
    for k, fig in enumerate(figures):
        _draw_figure(slide, fig, (MARGIN_L, area_top + k * (share + 0.2), BODY_W, share))


def _title_runs(title, runs: list[Run], size: float, min_size: float, width: float, height: float,
                color: str = INK) -> None:
    full = plain_text(runs)
    used, lines = fit_size(full, (width - 0.2) * 72, (height - 0.1) * 72, size, min_size, bold=True)
    if " ".join(lines) != " ".join(full.split()):            # still too long at the smallest size: cut it
        runs = [Run(" ".join(lines))]
    frame = title.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MIDDLE
    p = frame.paragraphs[0]
    p.alignment = LEFT
    write_runs(p, runs, used, color, bold=True)


def _title_slide(prs, section, fallback_title: str):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(DARK)
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = Inches(0.9), Inches(1.7), Inches(8.3), Inches(2.5)
    title.text_frame.vertical_anchor = BOTTOM
    _title_runs(title, inline_runs(section.title or fallback_title), 48, 26, 8.3, 2.5, "FFFFFF")
    title.text_frame.vertical_anchor = BOTTOM
    box(slide, 0.95, 4.4, 1.2, 0.07, fill=ACCENT)
    lines = _text_lines(parse_blocks(split_notes(section.body)[0]))
    sub = slide.placeholders[1]
    if lines:
        sub.left, sub.top, sub.width, sub.height = Inches(0.9), Inches(4.6), Inches(8.3), Inches(0.8)
        p = sub.text_frame.paragraphs[0]
        p.alignment = LEFT
        sub.text_frame.word_wrap = True
        write_runs(p, lines[0][0], 24, ACCENT)
        meta = " · ".join(plain_text(r) for r, *_x in lines[1:4])
        if meta:
            muted(slide, 0.9, 5.45, 8.3, 0.5, meta, 14, min_size=10)
            slide.shapes[-1].text_frame.paragraphs[0].runs[0].font.color.rgb = rgb("A9B6C8")
    else:
        sub._element.getparent().remove(sub._element)
    for i, colour in enumerate((ACCENT, ACCENT2, "1B3A5F", ACCENT)):
        box(slide, 9.75 + (i % 2) * 1.6, 2.15 + (i // 2) * 1.6, 1.45, 1.45, fill=colour)
    return slide


def _content_slide(prs, section):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = Inches(MARGIN_L), Inches(0.35), Inches(BODY_W), Inches(1.0)
    _title_runs(title, inline_runs(section.title), 32, 22, BODY_W, 1.0)
    box(slide, MARGIN_L + 0.05, 1.42, 0.9, 0.06, fill=ACCENT)
    body, _notes = split_notes(section.body)
    _fill_body(slide, slide.placeholders[1], parse_blocks(body))
    clamp_to_slide(slide, SLIDE_W, SLIDE_H)
    return slide


def build_pptx(doc: ParsedDoc, title: str) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    prs.core_properties.title = title
    prs.core_properties.author = "Harvis"
    for i, section in enumerate(doc.sections):
        slide = _title_slide(prs, section, title) if i == 0 else _content_slide(prs, section)
        notes = split_notes(section.body)[1]
        if notes:
            slide.notes_slide.notes_text_frame.text = plain_text(inline_runs(notes))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
