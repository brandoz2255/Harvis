"""Native-shape slide bodies for cards, quadrants, charts and tables.

Each ``draw_*`` fills the rectangle ``area = (left, top, width, height)`` in
inches and never draws outside it: fonts shrink with the item count and text is
cut with an ellipsis rather than left to overflow.
"""
from __future__ import annotations

import math

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from .docs_blocks import Run, plain_text
from .docs_chips import ACCENT, CARD, INK, LINE, MUTED, SERIES, TONE_TINTS, tone_color
from .docs_metrics import wrap
from .docs_pptx_kit import CENTER, MIDDLE, RIGHT, box, muted, rgb, text, write_runs
from .docs_rich import Card, Chart, Quadrant

Area = tuple[float, float, float, float]


MAX_CARDS = 12


def draw_cards(slide, cards: list[Card], area: Area) -> None:
    left, top, width, height = area
    title = getattr(cards, "title", "")
    hidden = max(len(cards) - MAX_CARDS, 0)
    cards = cards[:MAX_CARDS]
    n = len(cards)
    if not n:
        return
    if title:
        text(slide, left, top, width, 0.4, title, 18, bold=True, min_size=12)
        top += 0.45
        height -= 0.45
    if hidden:                                           # room for the "+N more" line under the grid
        height -= 0.32
        muted(slide, left, top + height + 0.02, width, 0.3, f"… {hidden} more", 12, min_size=9)
    cols = 1 if n == 1 else 2 if n in (2, 4) else 4 if n > 9 else 3
    rows = math.ceil(n / cols)
    gap = 0.25
    cw = (width - gap * (cols - 1)) / cols
    ch = max(min((height - gap * (rows - 1)) / rows, 3.0), 0.2)
    scale = min(1.0, ch / 2.2)
    for i, card in enumerate(cards):
        x, y = left + (i % cols) * (cw + gap), top + (i // cols) * (ch + gap)
        box(slide, x, y, cw, ch, fill=CARD, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        badge = min(0.46, ch * 0.3)
        b = box(slide, x + 0.2, y + 0.2, badge, badge, fill=ACCENT, shape=MSO_SHAPE.OVAL)
        text(slide, 0, 0, badge, badge, str(i + 1), 16 * scale, color="FFFFFF", bold=True, align=CENTER,
             anchor=MIDDLE, shape=b, min_size=9, wrap=False)
        text(slide, x + 0.3 + badge, y + 0.15, cw - badge - 0.5, badge + 0.1, card.title, 20 * scale, bold=True,
             anchor=MIDDLE, min_size=10)
        bottom = y + ch - 0.08                           # nothing below this line: what does not fit is left out
        cursor = y + 0.25 + badge + 0.1
        if card.highlight:
            hh = 0.5 * scale + 0.1
            if cursor + hh <= bottom:
                text(slide, x + 0.2, cursor, cw - 0.4, hh, card.highlight, 16 * scale, color=ACCENT, bold=True,
                     mono=True, anchor=MIDDLE, min_size=9)
                cursor += hh
        if card.detail and bottom - cursor >= 0.25:
            muted(slide, x + 0.2, cursor, cw - 0.4, bottom - cursor, card.detail, 14 * scale, min_size=9)


def draw_quadrant(slide, q: Quadrant, area: Area) -> None:
    left, top, width, height = area
    y = top
    if q.title:
        text(slide, left, y, width, 0.4, q.title, 18, bold=True, min_size=12)
        y += 0.45
    if q.y:
        muted(slide, left, y, width / 2, 0.3, "↑ " + q.y, 12, bold=True, min_size=9)
        y += 0.32
    x_cap = 0.34 if q.x else 0.0
    gap = 0.12
    cw, ch = (width - gap) / 2, max((top + height - y - x_cap - gap) / 2, 0.1)
    for i, (name, items) in enumerate(q.cells[:4]):
        x, cy = left + (i % 2) * (cw + gap), y + (i // 2) * (ch + gap)
        box(slide, x, cy, cw, ch, fill="E3F5F3" if i == 0 else CARD, line=LINE)
        label_h = min(0.4, ch - 0.1)
        if label_h >= 0.2:
            text(slide, x + 0.12, cy + 0.08, cw - 0.24, label_h, name, 16, color=ACCENT if i == 0 else INK,
                 bold=True, anchor=MIDDLE, min_size=10)
        if items and ch - 0.58 >= 0.3:                   # below that there is no room to read items
            body = "\n".join("• " + it for it in items)
            text(slide, x + 0.12, cy + 0.5, cw - 0.24, ch - 0.58, body, 15, min_size=9)
    if q.x:
        muted(slide, left + width / 2, top + height - x_cap, width / 2, x_cap, q.x + " →", 12, bold=True,
              align=RIGHT, min_size=9)


def draw_chart(slide, chart: Chart, area: Area) -> None:
    left, top, width, height = area
    if not chart.rows:
        muted(slide, left, top, width, 0.4, "No data", 14)
        return
    data = CategoryChartData()
    data.categories = [label for label, _v in chart.rows]
    series = chart.series[:1] if chart.type == "pie" else chart.series
    for j, name in enumerate(series):
        data.add_series(name, [vals[j] for _l, vals in chart.rows])
    kind = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS,
            "pie": XL_CHART_TYPE.PIE}[chart.type]
    frame = slide.shapes.add_chart(kind, Inches(left), Inches(top), Inches(width), Inches(height), data)
    ch = frame.chart
    ch.font.size = Pt(14 if len(chart.rows) <= 8 else 11)
    ch.font.color.rgb = rgb(INK)
    ch.has_title = bool(chart.title)
    if chart.title:
        ch.chart_title.text_frame.text = chart.title
        run = ch.chart_title.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold = Pt(16), True
        run.font.color.rgb = rgb(INK)
    ch.has_legend = chart.type == "pie" or len(series) > 1
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM if chart.type != "pie" else XL_LEGEND_POSITION.RIGHT
        ch.legend.include_in_layout = False
    plot = ch.plots[0]
    if chart.type == "pie":
        plot.vary_by_categories = True
        for i in range(len(chart.rows)):
            point = plot.series[0].points[i]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = rgb(SERIES[i % len(SERIES)])
        plot.has_data_labels = True
        plot.data_labels.show_percentage = True
        plot.data_labels.show_value = False
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = "0%", False
        return
    for j, s in enumerate(plot.series):
        color = rgb(SERIES[j % len(SERIES)])
        if chart.type == "line":
            s.format.line.color.rgb = color
            s.format.line.width = Pt(2.5)
            s.smooth = False
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = color
        else:
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = color
    if len(series) == 1 and len(chart.rows) <= 12:
        plot.has_data_labels = True
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = "#,##0.##", False
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb(LINE)
    ch.value_axis.format.line.fill.background()


def _col_widths(rows: list[list[str]], total: float) -> list[float]:
    cols = max(len(r) for r in rows)
    weight = [min(max(max((len(r[c]) if c < len(r) else 0) for r in rows), 6), 36) for c in range(cols)]
    widths = [total * w / sum(weight) for w in weight]
    floor = min(0.9, total / cols)
    widths = [max(w, floor) for w in widths]
    scale = total / sum(widths)
    return [w * scale for w in widths]


def draw_table(slide, rows: list[list[list[Run]]], tones: list[list], area: Area):
    """A native table; header row filled, status cells colored, rows that cannot fit become a "+N more" row."""
    left, top, width, height = area
    texts = [[plain_text(c) for c in r] for r in rows]
    cols = max(len(r) for r in rows)
    widths = _col_widths(texts, width)

    def row_heights(size: float, subset: list[int]) -> list[float]:
        out = []
        for ri in subset:
            lines = max(len(wrap(texts[ri][c], (widths[c] - 0.16) * 72, size, bold=ri == 0, max_lines=3) or [""])
                        for c in range(len(texts[ri])))
            out.append(lines * size * 1.2 / 72 + 0.12)
        return out

    # A row is never shorter than ~0.27in, so rows past what the area can hold are not even measured.
    pool = list(range(min(len(rows), max(int(height / 0.27) + 2, 2))))
    size = 14.0
    while size > 9 and sum(row_heights(size, pool)) > height:
        size -= 1
    pool_h = row_heights(size, pool)

    def take(budget: float) -> list[int]:               # leading rows that fit, always the header and one row
        chosen, used = [], 0.0
        for ri, h in zip(pool, pool_h):
            if len(chosen) >= 2 and used + h > budget:
                break
            chosen.append(ri)
            used += h
        return chosen

    chosen = take(height)
    if len(chosen) < len(rows):
        chosen = take(height - 0.3)                      # the "+N more" row needs its own room
    hidden = len(rows) - len(chosen)
    heights = row_heights(size, chosen)
    extra = 1 if hidden else 0
    shape = slide.shapes.add_table(len(chosen) + extra, cols, Inches(left), Inches(top), Inches(width),
                                   Inches(sum(heights) + 0.3 * extra))
    table = shape.table
    for c, w in enumerate(widths):
        table.columns[c].width = Inches(w)
    for r, h in enumerate(heights):
        table.rows[r].height = Inches(h)
    for r, ri in enumerate(chosen):
        for c in range(cols):
            cell = table.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(INK if ri == 0 else CARD if ri % 2 == 0 else "FFFFFF")
            cell.vertical_anchor = MIDDLE
            cell.text_frame.word_wrap = True
            tone = tones[ri][c] if ri < len(tones) and c < len(tones[ri]) else None
            if tone:
                cell.fill.fore_color.rgb = rgb(TONE_TINTS[tone])
            runs = rows[ri][c] if c < len(rows[ri]) else []
            cell_w = (widths[c] - 0.16) * 72
            if len(wrap(texts[ri][c], cell_w, size, bold=ri == 0)) > 3:             # cut, never overflow
                runs = [Run(" ".join(wrap(texts[ri][c], cell_w, size, bold=ri == 0, max_lines=3)))]
            write_runs(cell.text_frame.paragraphs[0], runs, size, "FFFFFF" if ri == 0 else tone_color(tone),
                       bold=ri == 0 or bool(tone))
    if hidden:
        last = table.cell(len(chosen), 0)
        last.merge(table.cell(len(chosen), cols - 1))
        table.rows[len(chosen)].height = Inches(0.3)
        write_runs(last.text_frame.paragraphs[0], [Run(f"… {hidden} more rows")], size, MUTED, italic=True)
    return shape
