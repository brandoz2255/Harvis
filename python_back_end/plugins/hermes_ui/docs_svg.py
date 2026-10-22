"""Rich blocks as inline SVG strings, drawn in pure Python for the PDF and Word exports.

``svg_markup`` returns one ``<svg>`` element. Every string is escaped, text is
measured with docs_metrics so a label is wrapped or cut with an ellipsis rather
than left to spill, and only plain shapes are used (rect, line, circle, polygon,
path, text) because WeasyPrint draws those faithfully.
"""
from __future__ import annotations

from html import escape
from typing import Optional

from .docs_chips import ACCENT, ACCENT2, CARD, INK, LINE, MUTED
from .docs_metrics import ellipsize, side_label, text_width, wrap
from .docs_rich import Card, Quadrant, Timeline, timeline_layout

FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"
MONO = "DejaVu Sans Mono, Consolas, monospace"
PAD = 16
MAX_TIMELINE_ROWS, MAX_CARDS, MAX_CHART_ROWS, MAX_FLOW_NODES = 30, 24, 60, 60   # a figure is a picture, not a database


def _c(color: str) -> str:
    return "none" if color == "none" else f"#{color}"


class Canvas:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def rect(self, x, y, w, h, fill="none", stroke="none", rx=0, sw=1, dash: Optional[str] = None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" rx="{rx}" '
                          f'fill="{_c(fill)}" stroke="{_c(stroke)}" stroke-width="{sw}"{d}/>')

    def line(self, x1, y1, x2, y2, stroke=LINE, sw=1, dash: Optional[str] = None) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                          f'stroke="{_c(stroke)}" stroke-width="{sw}"{d}/>')

    def circle(self, cx, cy, r, fill="none", stroke="none", sw=1) -> None:
        self.parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{_c(fill)}" stroke="{_c(stroke)}" '
                          f'stroke-width="{sw}"/>')

    def poly(self, points: list[tuple[float, float]], fill="none", stroke="none", sw=1) -> None:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(f'<polygon points="{pts}" fill="{_c(fill)}" stroke="{_c(stroke)}" '
                          f'stroke-width="{sw}"/>')

    def polyline(self, points: list[tuple[float, float]], stroke: str, sw=2) -> None:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(f'<polyline points="{pts}" fill="none" stroke="{_c(stroke)}" stroke-width="{sw}" '
                          'stroke-linejoin="round"/>')

    def path(self, d: str, fill="none", stroke="none", sw=1, dash: Optional[str] = None) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<path d="{d}" fill="{_c(fill)}" stroke="{_c(stroke)}" stroke-width="{sw}"{dash_attr}/>')

    def text(self, x, y_mid, s: str, size=13, fill=INK, bold=False, anchor="start", mono=False) -> None:
        """Text vertically centered on ``y_mid`` (the baseline sits a third of a size lower)."""
        if not s:
            return
        self.parts.append(
            f'<text x="{x:.1f}" y="{y_mid + size * 0.35:.1f}" font-size="{size}" fill="{_c(fill)}" '
            f'font-weight="{"bold" if bold else "normal"}" text-anchor="{anchor}" '
            f'font-family="{MONO if mono else FONT}">{escape(s)}</text>')

    def lines(self, x, y_top, lines: list[str], size=13, fill=INK, bold=False, leading=1.35, mono=False) -> float:
        for i, s in enumerate(lines):
            self.text(x, y_top + size * leading * (i + 0.5), s, size, fill, bold, mono=mono)
        return y_top + size * leading * len(lines)

    def svg(self, width: float, height: float, out_w: Optional[float] = None, out_h: Optional[float] = None) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.1f} {height:.1f}" '
                f'width="{out_w or width:.1f}" height="{out_h or height:.1f}">' + "".join(self.parts) + "</svg>")


def arrow_head(c: Canvas, x, y, dx, dy, fill, size=8) -> None:
    """A filled triangle with its tip at (x, y) pointing along (dx, dy)."""
    norm = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / norm, dy / norm
    bx, by = x - ux * size, y - uy * size
    c.poly([(x, y), (bx - uy * size * 0.45, by + ux * size * 0.45), (bx + uy * size * 0.45, by - ux * size * 0.45)], fill)


def heading(c: Canvas, title: str, subtitle: str, W: float) -> float:
    y = PAD
    if title:
        c.text(PAD, y + 11, ellipsize(title, W - 2 * PAD, 17, bold=True), 17, INK, True)
        y += 30
    if subtitle:
        c.text(PAD, y + 7, ellipsize(subtitle, W - 2 * PAD, 12), 12, MUTED)
        y += 22
    return y


def more_note(c: Canvas, y: float, hidden: int, W: float, noun: str = "more") -> float:
    c.text(PAD + 6, y + 10, f"… {hidden} {noun}", 12, MUTED)
    return y + 24


def timeline_svg(t: Timeline, W: float) -> tuple[Canvas, float]:
    c = Canvas()
    y = heading(c, t.title, t.subtitle, W)
    hidden = max(len(t.items) - MAX_TIMELINE_ROWS, 0)
    if hidden:
        t = Timeline(t.title, t.subtitle, t.items[:MAX_TIMELINE_ROWS], t.scaled)
    rows, ticks = timeline_layout(t)
    label_w = min(W * 0.3, max([text_width(i.label, 13, bold=True) for i in t.items] + [80]) + 10)
    x0, x1 = PAD + label_w + 8, W - PAD
    bx0, bx1 = x0 + 14, x1 - 14
    head = 26 if ticks else 4
    row_h = 40
    body_top = y + head
    for k, (tick, text) in enumerate(ticks):
        x = bx0 + tick * (bx1 - bx0)
        c.line(x, body_top - 4, x, body_top + len(rows) * row_h, LINE)
        c.text(min(x, W - PAD - 28) if k else x, y + 10, text, 11, MUTED, anchor="start")
    for i, (item, (a, b)) in enumerate(zip(t.items, rows)):
        top = body_top + i * row_h
        if i % 2 == 0:
            c.rect(PAD, top, W - 2 * PAD, row_h, CARD)
        mid = top + row_h / 2
        color = ACCENT2 if item.key else ACCENT
        c.text(PAD + 6, mid, ellipsize(item.label, label_w - 8, 13, bold=item.key), 13, INK, item.key)
        xa = bx0 + a * (bx1 - bx0)
        if b is None:
            c.poly([(xa, mid - 10), (xa + 10, mid), (xa, mid + 10), (xa - 10, mid)], color)
            lo, hi = xa - 10, xa + 10
        else:
            xb = bx0 + b * (bx1 - bx0)
            c.rect(xa, mid - 9, max(xb - xa, 4), 18, color, rx=5)
            lo, hi = xa, max(xb, xa + 4)
        when = item.when
        tw = text_width(when, 11, bold=item.key)
        x, anchor = side_label(lo, hi, tw, x0, W - PAD)
        if anchor == "inside":
            c.text(x, mid, ellipsize(when, hi - lo - 12, 11), 11, "FFFFFF", item.key)
        else:
            c.text(x, mid, when, 11, color if item.key else MUTED, item.key, anchor)
    end = body_top + len(rows) * row_h
    if hidden:
        end = more_note(c, end + 4, hidden, W)
    return c, end + PAD


def cards_svg(cards: list[Card], W: float) -> tuple[Canvas, float]:
    c = Canvas()
    if not cards:
        return c, 2 * PAD
    top0 = heading(c, getattr(cards, "title", ""), "", W)
    hidden = max(len(cards) - MAX_CARDS, 0)
    cards = cards[:MAX_CARDS]
    cols = 1 if len(cards) == 1 else 2 if len(cards) in (2, 4) else 3
    gap, card_h = 14, 132
    card_w = (W - 2 * PAD - gap * (cols - 1)) / cols
    for i, card in enumerate(cards):
        x = PAD + (i % cols) * (card_w + gap)
        y = top0 + (i // cols) * (card_h + gap)
        c.rect(x, y, card_w, card_h, CARD, LINE, rx=8)
        c.circle(x + 26, y + 26, 13, ACCENT)
        c.text(x + 26, y + 26, str(i + 1), 13, "FFFFFF", True, "middle")
        c.text(x + 48, y + 26, ellipsize(card.title, card_w - 60, 15, bold=True), 15, INK, True)
        top = y + 52
        if card.highlight:
            c.text(x + 14, top + 8, ellipsize(card.highlight, card_w - 28, 13, mono=True), 13, ACCENT, True, mono=True)
            top += 24
        room = max(int((y + card_h - 10 - top) // 17), 1)
        c.lines(x + 14, top, wrap(card.detail, card_w - 28, 12, max_lines=room), 12, MUTED, leading=1.4)
    rows = -(-len(cards) // cols)
    end = top0 + rows * card_h + (rows - 1) * gap
    if hidden:
        end = more_note(c, end + 6, hidden, W)
    return c, end + PAD


def quadrant_svg(q: Quadrant, W: float) -> tuple[Canvas, float]:
    c = Canvas()
    y = heading(c, q.title, "", W)
    if q.y:
        c.text(PAD, y + 8, "↑ " + ellipsize(q.y, W / 2, 12, bold=True), 12, MUTED, True)
        y += 22
    gap, cell_h = 8, 150
    cell_w = (W - 2 * PAD - gap) / 2
    tints = ["E3F5F3", CARD, CARD, CARD]
    for i, (name, items) in enumerate(q.cells[:4]):
        x = PAD + (i % 2) * (cell_w + gap)
        top = y + (i // 2) * (cell_h + gap)
        c.rect(x, top, cell_w, cell_h, tints[i], LINE, rx=6)
        c.text(x + 12, top + 18, ellipsize(name, cell_w - 24, 14, bold=True), 14, ACCENT if i == 0 else INK, True)
        room = int((cell_h - 36) // 17)
        per_item = [wrap("• " + it, cell_w - 24, 12, max_lines=2) for it in items]
        lines = [ln for item_lines in per_item for ln in item_lines]
        if len(lines) > room:                           # keep whole items, and say how many were left out
            lines, shown = [], 0
            for item_lines in per_item:
                if len(lines) + len(item_lines) > room - 1:
                    break
                lines += item_lines
                shown += 1
            lines = (lines + [f"… +{len(items) - shown} more"])[:room]
        c.lines(x + 12, top + 32, lines, 12, INK, leading=1.4)
    y += 2 * cell_h + gap
    if q.x:
        c.text(W - PAD, y + 14, ellipsize(q.x, W / 2, 12, bold=True) + " →", 12, MUTED, True, "end")
        y += 24
    return c, y + PAD


def svg_markup(kind: str, data, width: float = 760, max_height: Optional[float] = None,
               out_width: Optional[float] = None) -> str:
    """One ``<svg>`` for a rich block laid out ``width`` wide and shown ``out_width`` wide (default the same),
    scaled down further when that would make it taller than ``max_height``."""
    from .docs_svg_graph import chart_svg, flow_svg

    drawers = {"timeline": timeline_svg, "cards": cards_svg, "quadrant": quadrant_svg,
               "chart": chart_svg, "flow": flow_svg}
    canvas, height = drawers[kind](data, width)
    scale = (out_width or width) / width
    if max_height:
        scale = min(scale, max_height / height)
    return canvas.svg(width, height, width * scale, height * scale)


def svg_size(markup: str) -> tuple[float, float]:
    """The width and height attributes ``svg_markup`` wrote."""
    import re

    m = re.search(r'width="([\d.]+)" height="([\d.]+)"', markup)
    return (float(m.group(1)), float(m.group(2))) if m else (760.0, 400.0)
