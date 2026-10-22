"""What the rich blocks of a harvis-doc lose when they are read.

``scan_rich`` finds the blocks, ``dropped_lines`` says which of a block's lines the
real parser (docs_rich) did not keep, and ``is_empty`` names blocks that parsed to
nothing at all. The same functions serve /check and scripts/doc_eval.py, so the eval
and the app agree on what "kept every line" means.
"""
from __future__ import annotations

import csv
import re

from .docs_rich import (RICH_KINDS, _meta, parse_cards, parse_chart, parse_csv, parse_flow, parse_quadrant,
                        parse_rich, parse_timeline)

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)")
_CHART_TYPES = ("bar", "line", "pie", "donut", "doughnut")


def scan_rich(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """([(kind, body)], problems) for the fenced rich blocks in ``text``, closing fences as docs_blocks reads them."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[tuple[str, str]] = []
    problems: list[str] = []
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if not m:
            i += 1
            continue
        mark, lang, body = m.group(1), m.group(2).lower(), []
        i += 1
        while i < len(lines) and not (lines[i].strip().startswith(mark[0] * len(mark))
                                      and not lines[i].strip().strip(mark[0])):
            body.append(lines[i])
            i += 1
        if i >= len(lines):
            if lang in RICH_KINDS:
                problems.append(f"{lang} block never closed")
        elif lang in RICH_KINDS:
            blocks.append((lang, "\n".join(body)))
        i += 1
    return blocks, problems


def _chart_line_kept(line: str) -> bool:
    meta = _meta(line, ("title", "type", "series"))
    if meta:
        return meta[0] != "type" or meta[1].strip().lower() in _CHART_TYPES
    parsed = parse_chart(line)
    if not parsed.rows:
        return False
    tokens = [t for t in re.split(r",(?!\d{3}(?!\d))", line.rsplit(":", 1)[1]) if t.strip()]
    return len(parsed.rows[0][1]) == len(tokens)          # a value that is not a number is dropped quietly


def _kept(kind: str, line: str) -> bool:
    if kind == "timeline":
        t = parse_timeline(line)
        return bool(t.items or t.title or t.subtitle)
    if kind == "chart":
        return _chart_line_kept(line)
    if kind == "quadrant":
        if _meta(line, ("title", "x", "y")):
            return True
        return bool(line.partition(":")[0].strip())
    if kind == "cards":
        # only the block's first line can be its title; anywhere else "title: X" is drawn as a card named "title: X",
        # so read the line after an empty leading title, as it sits in the block
        return bool(parse_cards("title:\n" + line))
    if kind == "flow":
        return bool(parse_flow(line).edges)
    return True


def dropped_lines(kind: str, body: str) -> list[str]:
    """The non-blank lines of a block body that the reader in docs_rich did not keep, in order."""
    lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
    if not lines:
        return ["(empty block)"]
    if kind == "csv":
        kept = parse_csv(body).rows
        widths = {len(r) for r in csv.reader(lines, skipinitialspace=True)}
        out = [] if len(lines) == len(kept) else ["(rows lost while reading the csv)"]
        return out + (["(csv rows differ in width)"] if len(widths) > 1 else [])
    skip = 1 if kind == "cards" and _meta(lines[0], ("title",)) else 0      # a leading "title:" names the block, even empty
    out = [ln for ln in lines[skip:] if not _kept(kind, ln)]
    if kind == "quadrant":
        rows = [ln for ln in lines if not _meta(ln, ("title", "x", "y")) and ln.partition(":")[0].strip()]
        out += rows[4:]                                    # a fifth cell has nowhere to go
    return out


def late_card_titles(body: str) -> list[str]:
    """The "title:" lines of a cards block after its first line. They are drawn as cards, not as the block's title."""
    lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
    return [ln for ln in lines[1:] if _meta(ln, ("title",)) and "|" not in ln]


def is_empty(kind: str, body: str) -> bool:
    """True when the block parses to nothing drawable."""
    data = parse_rich(kind, body)
    if kind == "timeline":
        return not data.items
    if kind == "chart":
        return not data.rows
    if kind == "quadrant":
        return not any(name or items for name, items in data.cells)
    if kind == "cards":
        return not data
    if kind == "flow":
        return not data.nodes
    return not data.rows
