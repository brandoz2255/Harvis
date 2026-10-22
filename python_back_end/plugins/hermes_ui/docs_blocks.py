"""Markdown for documents: blocks and inline runs, shared by every exporter.

One small reader instead of the ``markdown`` package, because the Word, PowerPoint
and PDF writers all need the same structure (nested list levels, header-row
tables, bold/italic/code runs) and because nothing here may pass raw HTML
through: the PDF is rendered from these blocks with everything escaped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .docs_chips import chip_tone
from .docs_parse import is_divider, split_row
from .docs_rich import RICH_KINDS, CsvData, parse_rich


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: Optional[str] = None


@dataclass
class Block:
    kind: str                       # heading | para | list | table | code | quote | rule | rich | math
    level: int = 0                  # heading level
    runs: list[Run] = field(default_factory=list)
    items: list["ListItem"] = field(default_factory=list)
    rows: list[list[list[Run]]] = field(default_factory=list)   # table: row -> cell -> runs
    text: str = ""                  # code body, math TeX, or a rich block's source
    lang: str = ""
    rich: str = ""                  # rich: timeline | chart | quadrant | cards | flow | csv
    data: Any = None                # rich: the dataclass from docs_rich
    tones: list[list[Optional[str]]] = field(default_factory=list)   # table: chip tone per cell


@dataclass
class ListItem:
    level: int
    ordered: bool
    runs: list[Run]
    number: int = 1
    checked: Optional[bool] = None  # a "- [ ]" / "- [x]" checklist item


_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"!?\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_BOLD_ITALIC = re.compile(r"\*\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*\*|(?<![\w_])___(?=[^\s_])(.+?)(?<=[^\s_])___(?![\w_])")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_MATH = re.compile(r"(?<![\\$\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?![\w$])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>$])")
_SAFE_HREF = re.compile(r"^(?:https?://|mailto:)", re.I)
_PATTERNS = (_CODE, _MATH, _LINK, _BOLD_ITALIC, _BOLD, _STRIKE, _ITALIC)

_CONTROLS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")        # not legal in XML, so not in any office file


def strip_controls(text: str) -> str:
    return _CONTROLS.sub("", text or "")


_CHECK_RE = re.compile(r"^\[([ xX])\](?:\s+(.*))?$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)")


def inline_runs(text: str, *, bold: bool = False, italic: bool = False, href: Optional[str] = None) -> list[Run]:
    """Split a line of markdown into styled runs; nesting inherits the outer style."""
    return _runs_of(strip_controls(text), bold, italic, href)


def _runs_of(text: str, bold: bool, italic: bool, href: Optional[str]) -> list[Run]:
    best = None
    for pattern in _PATTERNS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[1].start()):
            best = (pattern, m)
    if best is None:
        plain = _ESCAPED.sub(r"\1", text)
        return [Run(plain, bold, italic, False, href)] if plain else []
    pattern, m = best
    out = _runs_of(text[:m.start()], bold, italic, href)
    if pattern is _CODE or pattern is _MATH:             # inline TeX is printed as its source, monospaced
        out.append(Run(m.group(1), bold, italic, True, href))
    elif pattern is _LINK:
        target = m.group(2)
        if text[m.start()] == "!":                      # an image: its alt text, never a fetch
            out.extend(_runs_of(m.group(1), bold, italic, href))
        else:
            out.extend(_runs_of(m.group(1) or target, bold, italic,
                                href=target if _SAFE_HREF.match(target) else href))
    elif pattern is _BOLD_ITALIC:
        out.extend(_runs_of(m.group(1) or m.group(2), True, True, href))
    elif pattern is _BOLD:
        out.extend(_runs_of(m.group(1) or m.group(2), True, italic, href))
    elif pattern is _ITALIC:
        out.extend(_runs_of(m.group(1) or m.group(2), bold, True, href))
    else:                                                # ~~strike~~ has no run style: keep the words
        out.extend(_runs_of(m.group(1), bold, italic, href))
    out.extend(_runs_of(text[m.end():], bold, italic, href))
    return out


def plain_text(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


def _level_of(indent: str, stack: list[int]) -> int:
    width = len(indent.replace("\t", "    "))
    while stack and stack[-1] > width:
        stack.pop()
    if not stack or stack[-1] < width:
        stack.append(width)
    return len(stack) - 1


def _read_math(lines: list[str], i: int) -> Optional[tuple[str, int]]:
    """(TeX, next line) for a ``$$`` display block opening at ``lines[i]``; None if it never closes."""
    first = lines[i].strip()[2:]
    if "$$" in first:
        return first.split("$$", 1)[0].strip(), i + 1
    body = [first] if first.strip() else []
    for j in range(i + 1, len(lines)):
        if "$$" in lines[j]:
            head = lines[j].split("$$", 1)[0]
            if head.strip():
                body.append(head)
            return "\n".join(b.rstrip() for b in body).strip(), j + 1
        body.append(lines[j])
    return None


def table_block(rows: list[list[list[Run]]]) -> Block:
    """A table block; the header row has no chips, a body cell that is a status word has one."""
    tones = [[None] * len(rows[0])] + [[chip_tone(plain_text(c)) for c in r] for r in rows[1:]] if rows else []
    return Block("table", rows=rows, tones=tones)


def csv_table(data: CsvData) -> Block:
    """A rich csv block as a table: cells are the raw text, not markdown."""
    return table_block([[[Run(c)] if c else [] for c in row] for row in data.rows])


def parse_blocks(markdown: str) -> list[Block]:
    """Headings, paragraphs, nested lists, tables, fenced code, quotes and rules."""
    lines = strip_controls(markdown).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append(Block("para", runs=inline_runs(" ".join(s.strip() for s in para))))
            para.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            flush()
            mark, lang, body = fence.group(1), fence.group(2), []
            i += 1
            while i < len(lines) and not (lines[i].strip().startswith(mark[0] * len(mark))
                                          and not lines[i].strip().strip(mark[0])):
                body.append(lines[i])
                i += 1
            text = "\n".join(body)
            if lang.lower() in RICH_KINDS:
                blocks.append(Block("rich", text=text, lang=lang.lower(), rich=lang.lower(),
                                    data=parse_rich(lang.lower(), text)))
            else:
                blocks.append(Block("code", text=text, lang=lang))
            i += 1
            continue
        if line.strip().startswith("$$"):
            math = _read_math(lines, i)
            if math:
                flush()
                if math[0]:
                    blocks.append(Block("math", text=math[0]))
                i = math[1]
                continue
        if not line.strip():
            flush()
            i += 1
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", level=len(heading.group(1)), runs=inline_runs(heading.group(2))))
            i += 1
            continue
        if _RULE_RE.match(line):
            flush()
            blocks.append(Block("rule"))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and is_divider(lines[i + 1]) and "|" in lines[i + 1]:
            flush()
            rows = [split_row(line)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            width = len(rows[0])
            blocks.append(table_block([[inline_runs(c) for c in (r + [""] * width)[:width]] for r in rows]))
            continue
        if line.lstrip().startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].strip())
                i += 1
            blocks.append(Block("quote", runs=inline_runs(" ".join(q for q in quote if q))))
            continue
        item = _LIST_RE.match(line)
        if item:
            flush()
            items, stack, counters = [], [], {}
            while i < len(lines):
                m = _LIST_RE.match(lines[i])
                if m:
                    level = _level_of(m.group(1), stack)
                    ordered = m.group(2)[0].isdigit()
                    # Deeper counters restart when a shallower item arrives.
                    for deeper in [k for k in counters if k > level]:
                        del counters[deeper]
                    kind, count = counters.get(level, (ordered, 0))
                    count = count + 1 if kind == ordered else 1      # bullets then numbers: count restarts
                    counters[level] = (ordered, count)
                    text, checked = m.group(3).strip(), None
                    check = _CHECK_RE.match(text)
                    if check:
                        checked, text = check.group(1) in "xX", (check.group(2) or "").strip()
                    items.append(ListItem(level, ordered, inline_runs(text), count, checked))
                    i += 1
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    items[-1].runs.extend(inline_runs(" " + lines[i].strip()))   # wrapped item text
                    i += 1
                else:
                    break
            blocks.append(Block("list", items=items))
            continue
        para.append(line)
        i += 1
    flush()
    return blocks


_NOTES_RE = re.compile(r"^\s*notes?\s*:\s*(.*)$", re.I)


def split_notes(body: str) -> tuple[str, str]:
    """(slide body without its speaker notes, the notes). Notes run from a ``Notes:``
    line until a blank line or the next list/heading/table line."""
    keep: list[str] = []
    notes: list[str] = []
    in_notes = False
    for line in body.split("\n"):
        m = _NOTES_RE.match(line)
        if m:
            in_notes = True
            if m.group(1).strip():
                notes.append(m.group(1).strip())
        elif in_notes and line.strip() and not _LIST_RE.match(line) and not line.lstrip().startswith(("#", "|")):
            notes.append(line.strip())
        else:
            in_notes = False
            keep.append(line)
    return "\n".join(keep).strip(), " ".join(notes)
