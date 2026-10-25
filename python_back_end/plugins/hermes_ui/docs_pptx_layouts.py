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
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from .docs_blocks import Run, plain_text
from .docs_chips import TONE_TINTS, tone_color
from .docs_metrics import wrap
from .docs_pptx_kit import CENTER, MIDDLE, RIGHT, box, rgb, text, write_runs
from .docs_rich import Card, Chart, Quadrant
from .docs_theme import DEFAULT_THEME, Theme, restyle_theme_xml

Area = tuple[float, float, float, float]

# The slide, in inches. The master and layouts of every deck are laid out to these (see ``prepare_deck``), so
# Reset Slide in PowerPoint or LibreOffice puts a placeholder back where the writer put it.
SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN_L, BODY_W, BODY_TOP, BODY_BOTTOM = 0.7, 11.9, 1.75, 6.95
TITLE_TOP, TITLE_H = 0.35, 1.0
COL_GAP = 0.5
COL_W = (BODY_W - COL_GAP) / 2
COL_HEAD_TOP, COL_HEAD_H, COL_BODY_TOP = BODY_TOP, 0.5, BODY_TOP + 0.55
COVER_X, COVER_TITLE_TOP, COVER_TITLE_H, COVER_W = 0.9, 1.7, 2.5, 11.5
COVER_SUB_TOP, COVER_SUB_H = 4.6, 0.8
SECTION_TITLE_TOP, SECTION_TITLE_H = 2.6, 1.8
SECTION_SUB_TOP = 4.6
# Layouts of python-pptx's stock template that the writer uses.
LAYOUT_TITLE, LAYOUT_CONTENT, LAYOUT_SECTION, LAYOUT_COLUMNS, LAYOUT_TITLE_ONLY = 0, 1, 2, 3, 5


def muted_t(slide, l, t, w, h, content: str, size: float = 14, *, theme: Theme = DEFAULT_THEME, **kw) -> float:
    """``docs_pptx_kit.muted`` in the theme's secondary text color."""
    return text(slide, l, t, w, h, content, size, color=theme.muted, **kw)


def write_themed_runs(paragraph, runs: list[Run], size: float, color, theme: Theme = DEFAULT_THEME, **kw) -> None:
    """``write_runs``, with hyperlinks in the theme's link colour, ``accent2`` (the kit writes them in the stock teal)."""
    write_runs(paragraph, runs, size, color, **kw)
    for r in paragraph.runs:
        if r.hyperlink.address:
            r.font.color.rgb = rgb(theme.accent2)


MAX_CARDS = 12


def draw_cards(slide, cards: list[Card], area: Area, theme: Theme = DEFAULT_THEME) -> None:
    left, top, width, height = area
    title = getattr(cards, "title", "")
    hidden = max(len(cards) - MAX_CARDS, 0)
    cards = cards[:MAX_CARDS]
    n = len(cards)
    if not n:
        return
    if title:
        text(slide, left, top, width, 0.4, title, 18, color=theme.ink, bold=True, min_size=12)
        top += 0.45
        height -= 0.45
    if hidden:                                           # room for the "+N more" line under the grid
        height -= 0.32
        muted_t(slide, left, top + height + 0.02, width, 0.3, f"… {hidden} more", 12, min_size=9, theme=theme)
    cols = 1 if n == 1 else 2 if n in (2, 4) else 4 if n > 9 else 3
    rows = math.ceil(n / cols)
    gap = 0.25
    cw = (width - gap * (cols - 1)) / cols
    ch = max(min((height - gap * (rows - 1)) / rows, 3.0), 0.2)
    scale = min(1.0, ch / 2.2)
    for i, card in enumerate(cards):
        x, y = left + (i % cols) * (cw + gap), top + (i // cols) * (ch + gap)
        box(slide, x, y, cw, ch, fill=theme.card, line=theme.line, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        badge = min(0.46, ch * 0.3)
        b = box(slide, x + 0.2, y + 0.2, badge, badge, fill=theme.accent, shape=MSO_SHAPE.OVAL)
        text(slide, 0, 0, badge, badge, str(i + 1), 16 * scale, color="FFFFFF", bold=True, align=CENTER,
             anchor=MIDDLE, shape=b, min_size=9, wrap=False)
        text(slide, x + 0.3 + badge, y + 0.15, cw - badge - 0.5, badge + 0.1, card.title, 20 * scale, color=theme.ink,
             bold=True, anchor=MIDDLE, min_size=10)
        bottom = y + ch - 0.08                           # nothing below this line: what does not fit is left out
        cursor = y + 0.25 + badge + 0.1
        if card.highlight:
            hh = 0.5 * scale + 0.1
            if cursor + hh <= bottom:
                text(slide, x + 0.2, cursor, cw - 0.4, hh, card.highlight, 16 * scale, color=theme.accent, bold=True,
                     mono=True, anchor=MIDDLE, min_size=9)
                cursor += hh
        if card.detail and bottom - cursor >= 0.25:
            muted_t(slide, x + 0.2, cursor, cw - 0.4, bottom - cursor, card.detail, 14 * scale, min_size=9, theme=theme)


def draw_quadrant(slide, q: Quadrant, area: Area, theme: Theme = DEFAULT_THEME) -> None:
    left, top, width, height = area
    y = top
    if q.title:
        text(slide, left, y, width, 0.4, q.title, 18, color=theme.ink, bold=True, min_size=12)
        y += 0.45
    if q.y:
        muted_t(slide, left, y, width / 2, 0.3, "↑ " + q.y, 12, bold=True, min_size=9, theme=theme)
        y += 0.32
    x_cap = 0.34 if q.x else 0.0
    gap = 0.12
    cw, ch = (width - gap) / 2, max((top + height - y - x_cap - gap) / 2, 0.1)
    for i, (name, items) in enumerate(q.cells[:4]):
        x, cy = left + (i % 2) * (cw + gap), y + (i // 2) * (ch + gap)
        box(slide, x, cy, cw, ch, fill=theme.accent_tint if i == 0 else theme.card, line=theme.line)
        label_h = min(0.4, ch - 0.1)
        if label_h >= 0.2:
            text(slide, x + 0.12, cy + 0.08, cw - 0.24, label_h, name, 16, color=theme.accent if i == 0 else theme.ink,
                 bold=True, anchor=MIDDLE, min_size=10)
        if items and ch - 0.58 >= 0.3:                   # below that there is no room to read items
            body = "\n".join("• " + it for it in items)
            text(slide, x + 0.12, cy + 0.5, cw - 0.24, ch - 0.58, body, 15, color=theme.ink, min_size=9)
    if q.x:
        muted_t(slide, left + width / 2, top + height - x_cap, width / 2, x_cap, q.x + " →", 12, bold=True,
                align=RIGHT, min_size=9, theme=theme)


def draw_chart(slide, chart: Chart, area: Area, theme: Theme = DEFAULT_THEME) -> None:
    left, top, width, height = area
    if not chart.rows:
        muted_t(slide, left, top, width, 0.4, "No data", 14, theme=theme)
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
    ch.font.color.rgb = rgb(theme.ink)
    ch.has_title = bool(chart.title)
    if chart.title:
        ch.chart_title.text_frame.text = chart.title
        run = ch.chart_title.text_frame.paragraphs[0].runs[0]
        run.font.size, run.font.bold = Pt(16), True
        run.font.color.rgb = rgb(theme.ink)
    ch.has_legend = chart.type == "pie" or len(series) > 1
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM if chart.type != "pie" else XL_LEGEND_POSITION.RIGHT
        ch.legend.include_in_layout = False
    plot = ch.plots[0]
    colors = theme.series
    if chart.type == "pie":
        plot.vary_by_categories = True
        for i in range(len(chart.rows)):
            point = plot.series[0].points[i]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = rgb(colors[i % len(colors)])
        plot.has_data_labels = True
        plot.data_labels.show_percentage = True
        plot.data_labels.show_value = False
        plot.data_labels.number_format, plot.data_labels.number_format_is_linked = "0%", False
        return
    for j, s in enumerate(plot.series):
        color = rgb(colors[j % len(colors)])
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
    ch.value_axis.major_gridlines.format.line.color.rgb = rgb(theme.line)
    ch.value_axis.format.line.fill.background()


def _col_widths(rows: list[list[str]], total: float) -> list[float]:
    cols = max(len(r) for r in rows)
    weight = [min(max(max((len(r[c]) if c < len(r) else 0) for r in rows), 6), 36) for c in range(cols)]
    widths = [total * w / sum(weight) for w in weight]
    floor = min(0.9, total / cols)
    widths = [max(w, floor) for w in widths]
    scale = total / sum(widths)
    return [w * scale for w in widths]


def draw_table(slide, rows: list[list[list[Run]]], tones: list[list], area: Area, theme: Theme = DEFAULT_THEME):
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
            cell.fill.fore_color.rgb = rgb(theme.ink if ri == 0 else theme.card if ri % 2 == 0 else theme.ground)
            cell.vertical_anchor = MIDDLE
            cell.text_frame.word_wrap = True
            tone = tones[ri][c] if ri < len(tones) and c < len(tones[ri]) else None
            if tone:
                cell.fill.fore_color.rgb = rgb(TONE_TINTS[tone])
            runs = rows[ri][c] if c < len(rows[ri]) else []
            cell_w = (widths[c] - 0.16) * 72
            if len(wrap(texts[ri][c], cell_w, size, bold=ri == 0)) > 3:             # cut, never overflow
                runs = [Run(" ".join(wrap(texts[ri][c], cell_w, size, bold=ri == 0, max_lines=3)))]
            write_themed_runs(cell.text_frame.paragraphs[0], runs, size,
                              theme.ground if ri == 0 else tone_color(tone, theme.ink), theme, bold=ri == 0 or bool(tone))
    if hidden:
        last = table.cell(len(chosen), 0)
        last.merge(table.cell(len(chosen), cols - 1))
        table.rows[len(chosen)].height = Inches(0.3)
        write_runs(last.text_frame.paragraphs[0], [Run(f"… {hidden} more rows")], size, theme.muted, italic=True)
    return shape


# ---- the master and layouts the slides are built on --------------------------------------------------------------

_DARK_MAP = {"bg1": "dk2", "tx1": "lt1", "bg2": "dk1", "tx2": "lt2", "accent1": "accent1", "accent2": "accent2",
             "accent3": "accent3", "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
             "hlink": "hlink", "folHlink": "folHlink"}
_BODY_SIZES = (2800, 2400, 2000, 2000, 2000, 2000, 2000, 2000, 2000)


def _place(shape, left: float, top: float, width: float, height: float) -> None:
    shape.left, shape.top, shape.width, shape.height = Inches(left), Inches(top), Inches(width), Inches(height)


def _own_xfrm(shape) -> bool:
    return shape._element.spPr.find(qn("a:xfrm")) is not None


def _fill_xml(parent, hex_color: str) -> None:
    for old in parent.findall(qn("a:solidFill")):
        parent.remove(old)
    fill = parent.makeelement(qn("a:solidFill"), {})
    fill.append(fill.makeelement(qn("a:srgbClr"), {"val": hex_color}))
    parent.insert(0, fill)


def _level(shape, n: int = 1):
    """The ``a:lvlNpPr`` of a placeholder's own list style, created when the layout leaves it out."""
    lst = shape._element.txBody.find(qn("a:lstStyle"))
    lvl = lst.find(qn(f"a:lvl{n}pPr"))
    if lvl is None:
        lvl = lst.makeelement(qn(f"a:lvl{n}pPr"), {})
        lst.append(lvl)
    rpr = lvl.find(qn("a:defRPr"))
    if rpr is None:
        rpr = lvl.makeelement(qn("a:defRPr"), {})
        lvl.append(rpr)
    return lvl, rpr


def _style_level(shape, *, size: int, bold: bool | None = None, color: str | None = None, algn: str = "l") -> None:
    lvl, rpr = _level(shape)
    lvl.set("algn", algn)
    rpr.set("sz", str(size))
    if bold is not None:
        rpr.set("b", "1" if bold else "0")
    rpr.attrib.pop("cap", None)
    if color:
        _fill_xml(rpr, color)


def _master_styles(master, theme: Theme) -> None:
    styles = master._element.find(qn("p:txStyles"))
    title = styles.find(qn("p:titleStyle")).find(qn("a:lvl1pPr"))
    title.set("algn", "l")
    rpr = title.find(qn("a:defRPr"))
    rpr.set("sz", "3200")
    rpr.set("b", "1")
    for i, lvl in enumerate(styles.find(qn("p:bodyStyle"))):
        rpr = lvl.find(qn("a:defRPr"))
        if rpr is not None and i < len(_BODY_SIZES):
            rpr.set("sz", str(_BODY_SIZES[i]))
        font = lvl.find(qn("a:buFont"))
        if font is not None and lvl.find(qn("a:buClr")) is None:
            clr = lvl.makeelement(qn("a:buClr"), {})
            clr.append(clr.makeelement(qn("a:schemeClr"), {"val": "accent1"}))
            font.addprevious(clr)


def _dark_layout(layout) -> None:
    """Background and text colors swapped (the layout's own color map), so the layout sits on the theme's dark."""
    cSld = layout._element.find(qn("p:cSld"))
    if cSld.find(qn("p:bg")) is None:
        bg = cSld.makeelement(qn("p:bg"), {})
        ref = bg.makeelement(qn("p:bgRef"), {"idx": "1001"})
        ref.append(ref.makeelement(qn("a:schemeClr"), {"val": "bg1"}))
        bg.append(ref)
        cSld.insert(0, bg)
    ovr = layout._element.find(qn("p:clrMapOvr"))
    if ovr is None:
        ovr = layout._element.makeelement(qn("p:clrMapOvr"), {})
        layout._element.append(ovr)
    for child in list(ovr):
        ovr.remove(child)
    ovr.append(ovr.makeelement(qn("a:overrideClrMapping"), dict(_DARK_MAP)))


def _cover_layout(layout, theme: Theme, *, section: bool) -> None:
    """The title slide (``section=False``) and the section divider: a big left-aligned title over a short line."""
    dark = theme.title_style == "dark"
    if dark:
        _dark_layout(layout)
    sub_color = theme.accent_on_dark if dark else theme.accent
    width = 8.3 if theme.decor and not section else COVER_W
    title, sub = layout.placeholders[0], layout.placeholders[1]
    if section:
        _place(title, COVER_X, SECTION_TITLE_TOP, width, SECTION_TITLE_H)
        _place(sub, COVER_X, SECTION_TITLE_TOP - 0.95, width, 0.8)
        sub._element.nvSpPr.nvPr.find(qn("p:ph")).set("type", "subTitle")   # its role to the checks: a title-type slide
        _style_level(sub, size=2800, bold=True, color=sub_color)
        sub._element.txBody.find(qn("a:bodyPr")).set("anchor", "b")
    else:
        _place(title, COVER_X, COVER_TITLE_TOP, width, COVER_TITLE_H)
        _place(sub, COVER_X, COVER_SUB_TOP, width, COVER_SUB_H)
        _style_level(sub, size=2400, color=sub_color)
    title._element.txBody.find(qn("a:bodyPr")).set("anchor", "b")
    _style_level(title, size=4800 if not section else 4400, bold=True)


def _columns_layout(layout) -> None:
    left, right = layout.placeholders[1], layout.placeholders[2]
    height = BODY_BOTTOM - COL_BODY_TOP
    _place(left, MARGIN_L, COL_BODY_TOP, COL_W, height)
    _place(right, MARGIN_L + COL_W + COL_GAP, COL_BODY_TOP, COL_W, height)
    for ph in (left, right):
        for n, size in enumerate(_BODY_SIZES, 1):
            _, rpr = _level(ph, n)
            rpr.set("sz", str(min(size, 2400)))


def prepare_master(prs, theme: Theme = DEFAULT_THEME) -> None:
    """Make the stock 4:3 template a 13.333x7.5in, themed one.

    The theme part gets the theme's colors and fonts, every master and layout shape is stretched to the wide slide,
    and the layouts the writer uses (title, content, section, two columns, title only) are laid out exactly where
    the writer puts their placeholders, so Reset Slide in PowerPoint or LibreOffice changes nothing. The stock
    thumbnail (a picture of the empty template) is dropped."""
    master = prs.slide_master
    k = SLIDE_W / 10.0
    for part in (master, *prs.slide_layouts):
        for shape in part.shapes:
            if _own_xfrm(shape):
                shape.left, shape.width = int(shape.left * k), int(shape.width * k)
    for shape in master.placeholders:
        kind = str(shape.placeholder_format.type)
        if "TITLE" in kind:
            _place(shape, MARGIN_L, TITLE_TOP, BODY_W, TITLE_H)
        elif "BODY" in kind:
            _place(shape, MARGIN_L, BODY_TOP, BODY_W, BODY_BOTTOM - BODY_TOP)
    _master_styles(master, theme)
    layouts = prs.slide_layouts
    _cover_layout(layouts[LAYOUT_TITLE], theme, section=False)
    _cover_layout(layouts[LAYOUT_SECTION], theme, section=True)
    _columns_layout(layouts[LAYOUT_COLUMNS])
    theme_part = master.part.part_related_by(RT.THEME)
    theme_part._blob = restyle_theme_xml(theme_part.blob, theme)
    rels = prs.part.package._rels
    for rid in [rid for rid, rel in rels.items() if rel.reltype == RT.THUMBNAIL]:
        rels.pop(rid)
