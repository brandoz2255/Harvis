"""The rich blocks a harvis-doc can hold, read into plain dataclasses for export.

A mirror of the TypeScript reader (the shared spec lives with the panel code):
every block is line based and tolerant. A malformed line is skipped or kept as
plain text, never raised, so a small model's slip costs one row and not the file.
"""
from __future__ import annotations

import csv
import io
import math
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

RICH_KINDS = ("timeline", "chart", "quadrant", "cards", "flow", "csv")

_META = re.compile(r"^([A-Za-z]+)\s*:\s*(.*)$")
_MONTHS = {m: i for i, names in enumerate(
    ("jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july",
     "aug august", "sep sept september", "oct october", "nov november", "dec december"), 1)
    for m in names.split()}


def _meta(line: str, keys: tuple[str, ...]) -> Optional[tuple[str, str]]:
    if "|" in line or "->" in line:
        return None
    m = _META.match(line)
    return (m.group(1).lower(), m.group(2).strip()) if m and m.group(1).lower() in keys else None


# ---- timeline ----

@dataclass
class TimelineItem:
    label: str
    start_text: str = ""
    end_text: str = ""
    key: bool = False
    start: Optional[date] = None
    end: Optional[date] = None

    @property
    def is_span(self) -> bool:
        return bool(self.end_text)

    @property
    def when(self) -> str:
        if self.end_text:
            return f"{self.start_text} to {self.end_text}"
        return self.start_text


@dataclass
class Timeline:
    title: str = ""
    subtitle: str = ""
    items: list[TimelineItem] = field(default_factory=list)
    scaled: bool = False                       # every date parsed: draw to scale


_YEARS = range(1900, 2201)                      # outside this a date is a typo; date arithmetic must stay in range


def _next_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:                           # Feb 29 into a common year
        return d.replace(year=d.year + 1, day=28)


def parse_date(text: str, today: Optional[date] = None) -> Optional[tuple[date, bool]]:
    """(date, the text named a year) for ISO, "Oct 26", "Oct 26 2026", "26 Oct"; else None."""
    found = _parse_date(text, today)
    return found if found and found[0].year in _YEARS else None


def _parse_date(text: str, today: Optional[date] = None) -> Optional[tuple[date, bool]]:
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", (text or "").strip().rstrip("."), flags=re.I)
    s = re.sub(r"(?<=[A-Za-z])\.", "", s)                    # "Oct. 26"
    s = re.sub(r"\s+", " ", s.replace(",", " ")).strip()
    year_now = (today or date.today()).year
    try:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])), True
        m = re.fullmatch(r"([A-Za-z]+) (\d{1,2})(?: (\d{4}))?", s)
        if m and m[1].lower() in _MONTHS:
            return date(int(m[3] or year_now), _MONTHS[m[1].lower()], int(m[2])), bool(m[3])
        m = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)(?: (\d{4}))?", s)
        if m and m[2].lower() in _MONTHS:
            return date(int(m[3] or year_now), _MONTHS[m[2].lower()], int(m[1])), bool(m[3])
    except ValueError:
        return None
    return None


def parse_timeline(body: str) -> Timeline:
    t = Timeline()
    explicit_end: dict[int, bool] = {}
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        meta = _meta(line, ("title", "subtitle"))
        if meta:
            setattr(t, meta[0], meta[1])
            continue
        parts = [p.strip() for p in line.split("|")]
        key = parts[0].startswith("*")
        label = parts[0].lstrip("*").strip()
        if not label or len(parts) < 2 or not parts[1]:      # an item needs a date
            continue
        item = TimelineItem(label, parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "", key)
        a = parse_date(item.start_text)
        b = parse_date(item.end_text) if item.end_text else None
        if a:
            item.start = a[0]
        if b:
            item.end = b[0]
            if a and item.end < item.start and not b[1]:
                item.end = _next_year(item.end)
            if a and item.end < item.start:
                item.start, item.end = item.end, item.start
        t.items.append(item)
    t.scaled = bool(t.items) and all(
        i.start is not None and (not i.end_text or i.end is not None) for i in t.items)
    return t


def timeline_layout(t: Timeline, max_ticks: int = 12):
    """Fractions in [0, 1] across the chart: (rows [(from, to or None for a diamond)], ticks [(at, text)])."""
    n = len(t.items)
    if not n:
        return [], []
    if not t.scaled:
        slot = 1 / n
        rows = [((i + 0.05) * slot, (i + 0.95) * slot) if it.is_span else ((i + 0.5) * slot, None)
                for i, it in enumerate(t.items)]
        return rows, []
    first = min(i.start for i in t.items)
    last = max((i.end + timedelta(days=1)) if i.end else i.start + timedelta(days=1) for i in t.items)
    span = max((last - first).days, 1)
    rows = []
    for it in t.items:
        if it.end:
            rows.append(((it.start - first).days / span, ((it.end - first).days + 1) / span))
        else:
            rows.append((((it.start - first).days + 0.5) / span, None))
    weeks = math.ceil(span / 7)
    stride = max(math.ceil(weeks / max_ticks), 1) * 7
    ticks = []
    d = 0
    while d <= span and len(ticks) <= max_ticks + 1:
        day = first + timedelta(days=d)
        ticks.append((d / span, f"{day.strftime('%b')} {day.day}"))
        d += stride
    return rows, ticks


# ---- chart ----

@dataclass
class Chart:
    title: str = ""
    type: str = "bar"                          # bar | line | pie
    series: list[str] = field(default_factory=list)
    rows: list[tuple[str, list[float]]] = field(default_factory=list)


def parse_number(token: str) -> Optional[float]:
    s = re.sub(r"[\s$€£¥%,]", "", token or "")
    factor = 1.0
    if s[-1:] in ("k", "K"):
        factor, s = 1e3, s[:-1]
    if not re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)", s):
        return None
    try:
        v = float(s) * factor
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_chart(body: str) -> Chart:
    c = Chart()
    names: list[str] = []
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        meta = _meta(line, ("title", "type", "series"))
        if meta:
            key, value = meta
            if key == "title":
                c.title = value
            elif key == "type":
                v = value.lower()
                c.type = "line" if v.startswith("line") else "pie" if v in ("pie", "donut", "doughnut") else "bar"
            else:
                names = [s.strip() for s in value.split(",") if s.strip()]
            continue
        if ":" not in line:
            continue
        label, rest = line.rsplit(":", 1)
        # A comma is a thousands mark only when exactly three digits follow it.
        values = [v for v in (parse_number(tok) for tok in re.split(r",(?!\d{3}(?!\d))", rest)) if v is not None]
        if label.strip() and values:
            c.rows.append((label.strip(), values))
    width = max([len(names), *(len(v) for _l, v in c.rows)] or [0])
    c.series = [names[i] if i < len(names) else f"Series {i + 1}" for i in range(width)]
    if len(c.series) == 1 and not names:
        c.series = [c.title or "Value"]
    c.rows = [(label, v + [0.0] * (width - len(v))) for label, v in c.rows]
    return c


# ---- quadrant ----

@dataclass
class Quadrant:
    title: str = ""
    x: str = ""
    y: str = ""
    cells: list[tuple[str, list[str]]] = field(default_factory=list)   # top-left, top-right, bottom-left, bottom-right


def parse_quadrant(body: str) -> Quadrant:
    q = Quadrant()
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        meta = _meta(line, ("title", "x", "y"))
        if meta:
            setattr(q, meta[0], meta[1])
            continue
        name, _sep, rest = line.partition(":")
        if name.strip() and len(q.cells) < 4:
            q.cells.append((name.strip(), [s.strip() for s in rest.split(",") if s.strip()]))
    while len(q.cells) < 4:
        q.cells.append(("", []))
    return q


# ---- cards ----

@dataclass
class Card:
    title: str
    highlight: str = ""
    detail: str = ""


class CardList(list):
    """The cards of a block, plus its title (a leading ``title: X`` line); still a plain list of Card."""
    title: str = ""


def parse_cards(body: str) -> CardList:
    out = CardList()
    first = True
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        meta = _meta(line, ("title",)) if first else None     # only the first line can name the block
        first = False
        if meta:                                      # an empty "title:" means no title and is not a card either
            out.title = meta[1]
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts[0]:
            out.append(Card(parts[0], parts[1] if len(parts) > 1 else "", " | ".join(p for p in parts[2:] if p)))
    return out


# ---- flow ----

@dataclass
class Flow:
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    back_edges: list[tuple[str, str]] = field(default_factory=list)
    layers: list[list[str]] = field(default_factory=list)


def parse_flow(body: str) -> Flow:
    f = Flow()
    seen: set[tuple[str, str]] = set()
    known: set[str] = set()
    for raw in (body or "").split("\n"):
        chain = [s.strip() for s in re.split(r"\s*(?:-+>|=>|→|⟶)\s*", raw.strip()) if s.strip()]
        for label in chain:
            if label not in known:
                known.add(label)
                f.nodes.append(label)
        for a, b in zip(chain, chain[1:]):
            if a != b and (a, b) not in seen:
                seen.add((a, b))
                f.edges.append((a, b))
    _layer(f)
    return f


def _layer(f: Flow) -> None:
    """Break back edges found by a depth-first walk, then layer by longest path from a source."""
    out: dict[str, list[str]] = {n: [] for n in f.nodes}
    has_in = {b for _a, b in f.edges}
    for a, b in f.edges:
        out[a].append(b)
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    for root in [n for n in f.nodes if n not in has_in] + f.nodes:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(out[root]))]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((node, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(out[nxt])))
    forward = [e for e in f.edges if e not in back]
    f.back_edges = [e for e in f.edges if e in back]
    # Kahn's walk: with the back edges cut the rest is acyclic, so each node's layer is known once its
    # predecessors are placed. (Rescanning a list of the unplaced nodes per round is quadratic on a long chain.)
    succ: dict[str, list[str]] = {n: [] for n in f.nodes}
    waiting = {n: 0 for n in f.nodes}
    for a, b in forward:
        succ[a].append(b)
        waiting[b] += 1
    layer = {n: 0 for n in f.nodes}
    queue = deque(n for n in f.nodes if not waiting[n])
    while queue:
        n = queue.popleft()
        for m in succ[n]:
            layer[m] = max(layer[m], layer[n] + 1)
            waiting[m] -= 1
            if not waiting[m]:
                queue.append(m)
    f.layers = [[] for _ in range(max(layer.values(), default=-1) + 1)]
    for n in f.nodes:
        f.layers[layer[n]].append(n)


# ---- csv ----

@dataclass
class CsvData:
    rows: list[list[str]] = field(default_factory=list)       # first row is the header


def parse_csv(body: str) -> CsvData:
    try:
        rows = [r for r in csv.reader(io.StringIO(body or ""), skipinitialspace=True) if any(c.strip() for c in r)]
    except csv.Error:
        rows = [line.split(",") for line in (body or "").split("\n") if line.strip()]
    width = max((len(r) for r in rows), default=0)
    return CsvData([[c.strip() for c in r] + [""] * (width - len(r)) for r in rows])


_PARSERS = {"timeline": parse_timeline, "chart": parse_chart, "quadrant": parse_quadrant,
            "cards": parse_cards, "flow": parse_flow, "csv": parse_csv}
_EMPTY = {"timeline": Timeline, "chart": Chart, "quadrant": Quadrant, "cards": list, "flow": Flow, "csv": CsvData}


def parse_rich(kind: str, body: str):
    """The dataclass for a rich block's body. Never raises: a body that cannot be read is an empty one."""
    try:
        return _PARSERS[kind](body)
    except Exception:                                          # noqa: BLE001 - a bad block must not sink the export
        return _EMPTY[kind]()


def rich_as_rows(kind: str, data) -> list[list[str]]:
    """A header row and body rows that say what the block says, for formats that cannot draw it."""
    if kind == "csv":
        return data.rows
    if kind == "timeline":
        return [["Item", "When"], *([("* " if i.key else "") + i.label, i.when] for i in data.items)]
    if kind == "chart":
        from .docs_metrics import fmt_num
        return [["", *data.series], *([label, *(fmt_num(v) for v in vals)] for label, vals in data.rows)]
    if kind == "quadrant":
        return [["Quadrant", "Items"], *([name, ", ".join(items)] for name, items in data.cells if name or items)]
    if kind == "cards":
        return [["#", "Title", "Highlight", "Detail"],
                *([str(i), c.title, c.highlight, c.detail] for i, c in enumerate(data, 1))]
    if kind == "flow":
        return [["From", "To"], *([a, b] for a, b in data.edges)]
    return []


def caption_of(kind: str, data) -> str:
    """A one-line description: the block's own title, else what it is."""
    title = getattr(data, "title", "")
    return title or {"timeline": "Timeline", "chart": "Chart", "quadrant": "Priority grid",
                     "cards": "Cards", "flow": "Diagram", "csv": "Data"}[kind]
