"""A deck block to a .pptx: 16:9, themed, a designed title slide, then bullet, section, column, big-number or figure slides."""
from __future__ import annotations

import io

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from pptx.util import Inches

from .docs_blocks import Block, Run, csv_table, inline_runs, parse_blocks, plain_text, split_notes
from .docs_metrics import fit_size, wrap
from .docs_parse import ParsedDoc
from .docs_pptx_graph import draw_flow, draw_timeline
from .docs_pptx_kit import BOTTOM, LEFT, MIDDLE, box, clamp_to_slide, rgb, text
from .docs_pptx_layouts import (
    BODY_BOTTOM, BODY_TOP, BODY_W, COL_BODY_TOP, COL_GAP, COL_HEAD_H, COL_HEAD_TOP, COL_W, COVER_SUB_TOP, COVER_TITLE_H,
    COVER_TITLE_TOP, COVER_W, COVER_X, LAYOUT_COLUMNS, LAYOUT_CONTENT, LAYOUT_SECTION, LAYOUT_TITLE, LAYOUT_TITLE_ONLY,
    MARGIN_L, SECTION_TITLE_H, SECTION_TITLE_TOP, SLIDE_H, SLIDE_W, TITLE_H, TITLE_TOP, draw_cards, draw_chart,
    draw_quadrant, draw_table, muted_t, prepare_master, write_themed_runs)
from .docs_theme import DEFAULT_THEME, Theme, body_size, classify_slide, get_theme, text_stats, width_factor

BODY_H = BODY_BOTTOM - BODY_TOP
MAX_LEVEL = 4
DEFAULT_START = 22                                # largest bullet size on a slide that also holds a figure
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


def _bullet_plan(lines: list, width_in: float, height_in: float, start: int = DEFAULT_START, factor: float = 1.0):
    """The largest bullet size (from ``start`` down) whose wrapped text fits; at the smallest size trailing lines are dropped.

    ``factor`` is how much wider than the width estimate the body face runs (see ``docs_theme.width_factor``)."""
    def cost(size: float, row) -> float:
        runs, level, _k, _s = row
        w = (width_in - 0.45 * (level + 1)) * 72 / factor
        return (len(wrap(plain_text(runs), w, size - 2 * level)) * (size - 2 * level) * 1.2 + size * 0.45) / 72

    # No row costs less than ~10pt, so lines past what the box can hold are never measured.
    limit = int(height_in * 72 / 10) + 1
    if len(lines) <= limit:
        for size in range(max(start, 12), 11, -1):
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


def _fill_text(placeholder, lines: list, top: float, height: float, theme: Theme = DEFAULT_THEME, *,
               left: float = MARGIN_L, width: float = BODY_W, start: int = DEFAULT_START) -> float:
    size, lines = _bullet_plan(lines, width, height, start, width_factor(theme.body_font))
    placeholder.left, placeholder.top = Inches(left), Inches(top)
    placeholder.width, placeholder.height = Inches(width), Inches(height)
    frame = placeholder.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    for i, (runs, level, bullet, style) in enumerate(lines):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.level = level
        _bullet(p, bullet)
        write_themed_runs(p, runs, size - 2 * level, theme.ink, theme, **style)
    return size


def _draw_figure(slide, block: Block, area, theme: Theme = DEFAULT_THEME) -> None:
    if block.kind == "table":
        if block.rows:
            draw_table(slide, block.rows, block.tones, area, theme)
        return
    kind = block.rich
    if kind == "csv":
        csv = csv_table(block.data)
        if csv.rows:
            draw_table(slide, csv.rows, csv.tones, area, theme)
    elif kind == "cards":
        draw_cards(slide, block.data, area, theme)
    elif kind == "timeline":
        draw_timeline(slide, block.data, area)
    elif kind == "quadrant":
        draw_quadrant(slide, block.data, area, theme)
    elif kind == "chart":
        draw_chart(slide, block.data, area, theme)
    elif kind == "flow":
        draw_flow(slide, block.data, area)


MAX_FIGURES = 3                                  # more would each get a strip too thin to read
MIN_FIGURE_H = 3.0                               # a lone figure keeps this much of the slide (2in each when several)


def _fill_body(slide, placeholder, blocks: list[Block], theme: Theme = DEFAULT_THEME) -> None:
    lines = _text_lines(blocks)
    all_figures = [b for b in blocks if b.kind in _FIGURES]
    figures = all_figures[:MAX_FIGURES if not lines else MAX_FIGURES - 1]      # beside text each needs more room
    area_top, area_bottom = BODY_TOP, BODY_BOTTOM
    if len(all_figures) > len(figures):
        area_bottom -= 0.35
        muted_t(slide, MARGIN_L, area_bottom + 0.05, BODY_W, 0.3, f"… {len(all_figures) - len(figures)} more not shown",
                12, min_size=9, theme=theme)
    caption = len(figures) == 1 and len(lines) <= 2 and all(not k or k == "none" for _r, _l, k, _s in lines)
    if not lines:
        placeholder._element.getparent().remove(placeholder._element)
    elif caption:
        placeholder._element.getparent().remove(placeholder._element)
        for runs, *_rest in lines:
            muted_t(slide, MARGIN_L, area_top - 0.05, BODY_W, 0.4, plain_text(runs), 16, min_size=11, theme=theme)
            area_top += 0.42
    else:
        height = area_bottom - BODY_TOP
        start = DEFAULT_START
        if figures:                                   # text yields to the figures, which keep a readable share
            keep = (MIN_FIGURE_H if len(figures) == 1 else 2.0 * len(figures)) + 0.2 * (len(figures) - 1) + 0.15
            height = max(min(0.5 * len(lines) + 0.3, BODY_H * 0.55, height - keep), 0.6)
        else:                                         # a slide of text alone is read from across a room
            start = max(body_size(*text_stats(blocks)), DEFAULT_START)
        _fill_text(placeholder, lines, BODY_TOP, height, theme, start=start)
        area_top = BODY_TOP + height + 0.15
    if not figures:
        return
    share = max((area_bottom - area_top - 0.2 * (len(figures) - 1)) / len(figures), 0.5)
    for k, fig in enumerate(figures):
        _draw_figure(slide, fig, (MARGIN_L, area_top + k * (share + 0.2), BODY_W, share), theme)


def _title_runs(title, runs: list[Run], size: float, min_size: float, width: float, height: float,
                color: str, theme: Theme = DEFAULT_THEME, anchor=MIDDLE) -> None:
    full = plain_text(runs)
    used, lines = fit_size(full, (width - 0.2) * 72 / width_factor(theme.heading_font), (height - 0.1) * 72, size,
                           min_size, bold=True)
    if " ".join(lines) != " ".join(full.split()):            # still too long at the smallest size: cut it
        runs = [Run(" ".join(lines))]
    frame = title.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    p = frame.paragraphs[0]
    p.alignment = LEFT
    write_themed_runs(p, runs, used, color, theme, bold=True)


def _cover_ground(slide, theme: Theme) -> tuple[str, bool]:
    """Paint a title or section slide's background; returns (text color on it, whether it is the dark one)."""
    dark = theme.title_style == "dark"
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(theme.dark if dark else theme.ground)
    return (theme.ground if dark else theme.ink), dark


def _title_slide(prs, section, fallback_title: str, theme: Theme = DEFAULT_THEME):
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE])
    fg, dark = _cover_ground(slide, theme)
    width = 8.3 if theme.decor else COVER_W            # the squares, when asked for, take the right of the slide
    sub_color = theme.accent_on_dark if dark else theme.accent
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = (Inches(COVER_X), Inches(COVER_TITLE_TOP), Inches(width),
                                                        Inches(COVER_TITLE_H))
    _title_runs(title, inline_runs(section.title or fallback_title), 48, 26, width, COVER_TITLE_H, fg, theme,
                anchor=BOTTOM)
    box(slide, COVER_X + 0.05, COVER_SUB_TOP - 0.2, 1.2, 0.07, fill=sub_color)
    lines = _text_lines(parse_blocks(split_notes(section.body)[0]))
    sub = slide.placeholders[1]
    if lines:
        sub.left, sub.top, sub.width, sub.height = (Inches(COVER_X), Inches(COVER_SUB_TOP), Inches(width),
                                                    Inches(0.8))
        p = sub.text_frame.paragraphs[0]
        p.alignment = LEFT
        sub.text_frame.word_wrap = True
        write_themed_runs(p, lines[0][0], 24, sub_color, theme)
        meta = " · ".join(plain_text(r) for r, *_x in lines[1:4])
        if meta:
            text(slide, COVER_X, COVER_SUB_TOP + 0.85, width, 0.5, meta, 14, color=theme.on_dark if dark else theme.muted,
                 min_size=10)
    else:
        sub._element.getparent().remove(sub._element)
    if theme.decor:
        for i, colour in enumerate((theme.accent, theme.accent2, theme.muted, theme.accent)):
            box(slide, 9.75 + (i % 2) * 1.6, 2.15 + (i // 2) * 1.6, 1.45, 1.45, fill=colour)
    return slide


def _slide_title(slide, section, theme: Theme) -> None:
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = (Inches(MARGIN_L), Inches(TITLE_TOP), Inches(BODY_W),
                                                        Inches(TITLE_H))
    _title_runs(title, inline_runs(section.title), 32, 22, BODY_W, TITLE_H, theme.ink, theme)
    if theme.decor:
        box(slide, MARGIN_L + 0.05, 1.42, 0.9, 0.06, fill=theme.accent)


def _content_slide(prs, section, blocks: list[Block], theme: Theme = DEFAULT_THEME):
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    _slide_title(slide, section, theme)
    _fill_body(slide, slide.placeholders[1], blocks, theme)
    clamp_to_slide(slide, SLIDE_W, SLIDE_H)
    return slide


def _section_slide(prs, section, number: int, theme: Theme = DEFAULT_THEME):
    """A divider: the title large on the dark (or light) ground, over a small running number."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_SECTION])
    fg, dark = _cover_ground(slide, theme)
    accent = theme.accent_on_dark if dark else theme.accent
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = (Inches(COVER_X), Inches(SECTION_TITLE_TOP), Inches(COVER_W),
                                                        Inches(SECTION_TITLE_H))
    _title_runs(title, inline_runs(section.title), 44, 26, COVER_W, SECTION_TITLE_H, fg, theme, anchor=BOTTOM)
    kicker = slide.placeholders[1]
    kicker.left, kicker.top = Inches(COVER_X), Inches(SECTION_TITLE_TOP - 0.95)
    kicker.width, kicker.height = Inches(COVER_W), Inches(0.8)
    kicker.text_frame.vertical_anchor = BOTTOM
    p = kicker.text_frame.paragraphs[0]
    p.alignment = LEFT
    write_themed_runs(p, [Run(f"{number:02d}")], 28, accent, theme, bold=True)
    box(slide, COVER_X + 0.05, SECTION_TITLE_TOP + SECTION_TITLE_H + 0.2, 1.2, 0.07, fill=accent)
    clamp_to_slide(slide, SLIDE_W, SLIDE_H)
    return slide


def _columns_slide(prs, section, groups: list, theme: Theme = DEFAULT_THEME):
    """Two columns, each a heading over text, in the layout's two content placeholders."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_COLUMNS])
    _slide_title(slide, section, theme)
    height = BODY_BOTTOM - COL_BODY_TOP
    for i, (head, blocks) in enumerate(groups):
        x = MARGIN_L + i * (COL_W + COL_GAP)
        text(slide, x, COL_HEAD_TOP, COL_W, COL_HEAD_H, plain_text(head), 22, color=theme.accent, bold=True,
             anchor=MIDDLE, min_size=14)
        box(slide, x + 0.05, COL_HEAD_TOP + COL_HEAD_H + 0.02, COL_W - 0.1, 0.02, fill=theme.line)
        lines = _text_lines(blocks)
        _fill_text(slide.placeholders[i + 1], lines, COL_BODY_TOP, height, theme, left=x, width=COL_W,
                   start=min(max(body_size(*text_stats(blocks)), DEFAULT_START), 28))
    clamp_to_slide(slide, SLIDE_W, SLIDE_H)
    return slide


def _stats_slide(prs, section, groups: list, theme: Theme = DEFAULT_THEME):
    """One to three big numbers, each on a card with its caption beneath."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])
    _slide_title(slide, section, theme)
    n, gap = len(groups), 0.4
    width = (BODY_W - gap * (n - 1)) / n
    top, height = BODY_TOP + 0.25, 3.9
    for i, (number, caption) in enumerate(groups):
        x = MARGIN_L + i * (width + gap)
        box(slide, x, top, width, height, fill=theme.card, line=theme.line, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
            radius=0.04)
        text(slide, x + 0.3, top + 0.35, width - 0.6, 1.7, plain_text(number), 80, color=theme.accent, bold=True,
             anchor=BOTTOM, min_size=36, wrap=False)
        if caption:
            text(slide, x + 0.3, top + 2.2, width - 0.6, height - 2.5, plain_text(caption), 24, color=theme.ink,
                 min_size=14)
    clamp_to_slide(slide, SLIDE_W, SLIDE_H)
    return slide


def build_pptx(doc: ParsedDoc, title: str) -> bytes:
    theme = get_theme(getattr(doc, "theme", ""))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    prepare_master(prs, theme)
    prs.core_properties.title = title
    prs.core_properties.author = "Harvis"
    dividers = 0
    for i, section in enumerate(doc.sections):
        body, notes = split_notes(section.body)
        if i == 0:
            slide = _title_slide(prs, section, title, theme)
        else:
            blocks = parse_blocks(body)
            kind = classify_slide(blocks, bool(section.title))
            if kind.kind == "section":
                dividers += 1
                slide = _section_slide(prs, section, dividers, theme)
            elif kind.kind == "columns":
                slide = _columns_slide(prs, section, kind.groups, theme)
            elif kind.kind == "stats":
                slide = _stats_slide(prs, section, kind.groups, theme)
            else:
                slide = _content_slide(prs, section, blocks, theme)
        if notes:
            slide.notes_slide.notes_text_frame.text = plain_text(inline_runs(notes))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
