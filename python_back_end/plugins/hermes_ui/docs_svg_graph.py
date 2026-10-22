"""The chart and flow drawings for docs_svg, split out to keep each module small."""
from __future__ import annotations

import math

from .docs_chips import ACCENT, INK, LINE, MUTED, SERIES
from .docs_metrics import ellipsize, fmt_num, nice_ticks, text_width, wrap
from .docs_rich import Chart, Flow
from .docs_svg import MAX_CHART_ROWS, MAX_FLOW_NODES, PAD, Canvas, arrow_head, heading, more_note

_BACK = "C8372D"


def chart_svg(chart: Chart, W: float) -> tuple[Canvas, float]:
    c = Canvas()
    y = heading(c, chart.title, "", W)
    if not chart.rows:
        c.text(PAD, y + 12, "No data", 13, MUTED)
        return c, y + 40
    hidden = max(len(chart.rows) - MAX_CHART_ROWS, 0)
    if hidden:
        chart = Chart(chart.title, chart.type, chart.series, chart.rows[:MAX_CHART_ROWS])
    if chart.type == "pie":
        return _pie(c, chart, W, y)
    multi = len(chart.series) > 1
    if multi:
        x = PAD
        for k, name in enumerate(chart.series):
            name = ellipsize(name, W - 2 * PAD - 15, 12)
            if x > PAD and x + 15 + text_width(name, 12) > W - PAD:        # wrap the legend, never run off the edge
                x, y = PAD, y + 18
            c.rect(x, y + 3, 10, 10, SERIES[k % len(SERIES)], rx=2)
            c.text(x + 15, y + 8, name, 12, MUTED)
            x += 15 + text_width(name, 12) + 18
        y += 24
    plot_l, plot_r, plot_t, plot_h = PAD + 44, W - PAD, y + 8, 220.0
    values = [v for _l, vals in chart.rows for v in vals]
    ticks = nice_ticks(min(values), max(values))
    lo, hi = ticks[0], ticks[-1]
    span = (hi - lo) or 1.0

    def ypos(v: float) -> float:
        return plot_t + plot_h - (v - lo) / span * plot_h

    for t in ticks:
        c.line(plot_l, ypos(t), plot_r, ypos(t), LINE if t else MUTED)
        c.text(plot_l - 6, ypos(t), fmt_num(t), 11, MUTED, anchor="end")
    n, k = len(chart.rows), len(chart.series)
    slot = (plot_r - plot_l) / n
    zero = ypos(0)
    label_every = 1 if n * k <= 24 else 0
    for i, (label, vals) in enumerate(chart.rows):
        cx = plot_l + slot * (i + 0.5)
        c.text(cx, plot_t + plot_h + 16, ellipsize(label, slot - 4, 12), 12, INK, anchor="middle")
        if chart.type == "line":
            continue
        group = slot * 0.72
        bw = group / k
        for j, v in enumerate(vals):
            x = cx - group / 2 + j * bw
            top, bottom = min(ypos(v), zero), max(ypos(v), zero)
            c.rect(x + 1, top, max(bw - 2, 1), max(bottom - top, 1), SERIES[j % len(SERIES)], rx=2)
            if label_every and bw >= 22:
                c.text(x + bw / 2, (top - 8) if v >= 0 else bottom + 8, fmt_num(v), 11, INK, anchor="middle")
    if chart.type == "line":
        for j in range(k):
            pts = [(plot_l + slot * (i + 0.5), ypos(vals[j])) for i, (_l, vals) in enumerate(chart.rows)]
            color = SERIES[j % len(SERIES)]
            c.polyline(pts, color, 2.5)
            for (px, py), (_l, vals) in zip(pts, chart.rows):
                c.circle(px, py, 4, color, "FFFFFF", 1.5)
                if n * k <= 14:
                    c.text(px, py - 12, fmt_num(vals[j]), 11, INK, anchor="middle")
    end = plot_t + plot_h + 34
    if hidden:
        end = more_note(c, end - 8, hidden, W, "more rows not shown")
    return c, end + PAD


def _pie(c: Canvas, chart: Chart, W: float, y: float) -> tuple[Canvas, float]:
    slices = [(label, vals[0]) for label, vals in chart.rows if vals and vals[0] > 0][:12]
    total = sum(v for _l, v in slices)
    r = 100.0
    cx, cy = PAD + r + 8, y + r + 8
    if not total:
        c.text(PAD, y + 12, "No positive values to chart", 13, MUTED)
        return c, y + 40
    angle = -math.pi / 2
    for i, (_label, v) in enumerate(slices):
        color = SERIES[i % len(SERIES)]
        sweep = v / total * 2 * math.pi
        if len(slices) == 1:
            c.circle(cx, cy, r, color)
        else:
            x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
            x2, y2 = cx + r * math.cos(angle + sweep), cy + r * math.sin(angle + sweep)
            c.path(f"M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} A{r},{r} 0 {1 if sweep > math.pi else 0} 1 "
                   f"{x2:.1f},{y2:.1f} Z", color, "FFFFFF", 2)
        angle += sweep
    lx, ly = cx + r + 36, y + 12
    for i, (label, v) in enumerate(slices):
        top = ly + i * 24
        c.rect(lx, top + 3, 12, 12, SERIES[i % len(SERIES)], rx=2)
        c.text(lx + 20, top + 9, ellipsize(f"{label}  {fmt_num(v)} ({v / total:.0%})", W - lx - 28 - PAD, 13), 13, INK)
    return c, max(cy + r, ly + len(slices) * 24) + PAD + 8


def flow_svg(flow: Flow, W: float) -> tuple[Canvas, float]:
    c = Canvas()
    if not flow.layers:
        return c, 2 * PAD
    if len(flow.nodes) > MAX_FLOW_NODES:
        raise ValueError("flow too large to draw")      # callers fall back to the edge table
    n_layers = len(flow.layers)
    gap = 46.0 if n_layers <= 5 else 28.0
    node_w = min(170.0, (W - 2 * PAD - gap * (n_layers - 1)) / n_layers)
    if node_w < 50:
        raise ValueError("flow too wide to draw")
    node_h, vgap = 46.0, 20.0
    tallest = max(len(layer) for layer in flow.layers)
    body_h = tallest * node_h + (tallest - 1) * vgap
    back_room = 30.0 if flow.back_edges else 0.0       # room above and below for dashed return edges
    pos: dict[str, tuple[float, float]] = {}
    for li, layer in enumerate(flow.layers):
        x = PAD + li * (node_w + gap)
        top = PAD + back_room + (body_h - (len(layer) * node_h + (len(layer) - 1) * vgap)) / 2
        for ni, label in enumerate(layer):
            pos[label] = (x, top + ni * (node_h + vgap))
    for a, b in flow.edges:
        if (a, b) in flow.back_edges:
            continue
        (ax, ay), (bx, by) = pos[a], pos[b]
        x1, y1, x2, y2 = ax + node_w, ay + node_h / 2, bx, by + node_h / 2
        c.line(x1, y1, x2 - 7, y2, MUTED, 1.6)
        arrow_head(c, x2, y2, x2 - x1, y2 - y1, MUTED)
    low = PAD + back_room + body_h
    for a, b in flow.back_edges:
        (ax, ay), (bx, by) = pos[a], pos[b]
        x1, x2 = ax + node_w / 2, bx + node_w / 2
        below = flow.layers[[a in layer for layer in flow.layers].index(True)][-1] == a
        sy, ty = (ay + node_h, by + node_h) if below else (ay, by)
        lane = low + back_room - 10 if below else PAD + 10
        c.path(f"M{x1:.1f},{sy:.1f} L{x1:.1f},{lane:.1f} L{x2:.1f},{lane:.1f} L{x2:.1f},{ty + (7 if below else -7):.1f}",
               "none", _BACK, 1.6, "5,4")
        arrow_head(c, x2, ty, 0, -1 if below else 1, _BACK)
    for li, layer in enumerate(flow.layers):
        for label in layer:
            x, y = pos[label]
            source = li == 0
            c.rect(x, y, node_w, node_h, ACCENT if source else "FFFFFF", ACCENT, rx=8, sw=1.6)
            size = 13
            lines = wrap(label, node_w - 14, size, bold=True, max_lines=2)
            for k, line in enumerate(lines):
                c.text(x + node_w / 2, y + node_h / 2 + (k - (len(lines) - 1) / 2) * size * 1.25, line, size,
                       "FFFFFF" if source else INK, True, "middle")
    return c, PAD * 2 + body_h + 2 * back_room
