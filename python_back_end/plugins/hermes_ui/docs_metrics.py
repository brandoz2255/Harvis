"""Rough text measurement shared by the SVG figures and the pptx shapes.

Neither renderer can ask a font how wide a string is, so this estimates it
(on the wide side) and wraps, shrinks or truncates with an ellipsis, so a label
never runs past the box it was given. Sizes and widths share one unit.
"""
from __future__ import annotations

import math

ELLIPSIS = "…"


def text_width(text: str, size: float, *, bold: bool = False, mono: bool = False) -> float:
    return len(text) * size * (0.62 if mono else 0.58 if bold else 0.54)


def ellipsize(text: str, width: float, size: float, *, bold: bool = False, mono: bool = False) -> str:
    text = " ".join((text or "").split())
    if text_width(text, size, bold=bold, mono=mono) <= width:
        return text
    room = max(int(width / max(text_width("x", size, bold=bold, mono=mono), 0.01)) - 1, 0)
    return text[:room].rstrip() + ELLIPSIS if room else ELLIPSIS


def _chop(word: str, width: float, size: float, bold: bool, mono: bool) -> list[str]:
    per = max(int(width / max(text_width("x", size, bold=bold, mono=mono), 0.01)), 1)
    return [word[i:i + per] for i in range(0, len(word), per)] or [""]


def wrap(text: str, width: float, size: float, *, bold: bool = False, mono: bool = False,
         max_lines: int | None = None) -> list[str]:
    """Greedy word wrap; ``\\n`` starts a new line; past ``max_lines`` the last line ends in an ellipsis."""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for word in para.split():
            for piece in (_chop(word, width, size, bold, mono)
                          if text_width(word, size, bold=bold, mono=mono) > width else [word]):
                trial = f"{cur} {piece}".strip()
                if cur and text_width(trial, size, bold=bold, mono=mono) > width:
                    lines.append(cur)
                    cur = piece
                else:
                    cur = trial
        lines.append(cur)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max(max_lines, 1)]
        lines[-1] = ellipsize(lines[-1] + " " + ELLIPSIS, width, size, bold=bold, mono=mono)
        if not lines[-1].endswith(ELLIPSIS):
            lines[-1] = ellipsize(lines[-1], width, size, bold=bold, mono=mono)
    return lines


def fit_size(text: str, width: float, height: float, max_size: float, min_size: float, *,
             bold: bool = False, mono: bool = False, leading: float = 1.2) -> tuple[float, list[str]]:
    """Largest size in [min_size, max_size] whose wrapped text fits the box, and the lines.

    At ``min_size`` what still does not fit is truncated with an ellipsis."""
    size = max_size
    while size > min_size:
        lines = wrap(text, width, size, bold=bold, mono=mono)
        if len(lines) * size * leading <= height:
            return size, lines
        size -= 0.5
    rows = max(int(height / (min_size * leading)), 1)
    return min_size, wrap(text, width, min_size, bold=bold, mono=mono, max_lines=rows)


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round axis values from at or below ``lo`` to at or above ``hi``."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return [0.0, 1.0]
    lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(count, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.floor(lo / step) * step
    out, v = [], first
    while v < hi + step * 0.999 and len(out) < 40:
        out.append(round(v, 10))
        if v >= hi - 1e-12:
            break
        v += step
    return out


def fmt_num(value: float) -> str:
    if abs(value) >= 1000 and abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text or "0"


def side_label(lo: float, hi: float, width: float, low_edge: float, high_edge: float,
               gap: float = 6.0) -> tuple[float, str]:
    """Where a label ``width`` wide goes beside a bar spanning lo..hi without leaving low_edge..high_edge.

    Returns (x, 'start' | 'end' | 'inside'): right of the bar, else left of it, else inside it."""
    if hi + gap + width <= high_edge:
        return hi + gap, "start"
    if lo - gap - width >= low_edge:
        return lo - gap, "end"
    return lo + gap, "inside"
