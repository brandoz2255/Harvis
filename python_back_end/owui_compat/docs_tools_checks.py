"""What is wrong with a harvis-doc source, said so an author can fix it (docs_validate).

The exporters never raise on a sloppy block: they skip the line, keep the text, or fall
back to plain paragraphs. That keeps a download alive and hides the loss, so an agent
that cannot see the file never learns that its third chart row was dropped. This module
reads the same source the same way the exporters do and lists, in plain sentences, what
they would silently lose. It does not parse a second grammar: it runs the exporters'
own parsers (docs_parse, docs_rich, docs_formula) and compares their output to the lines.
"""
from __future__ import annotations

import re
from typing import Optional

from plugins.hermes_ui.docs_export import FORMATS, MAX_SOURCE_BYTES, ExportError, parse_for_export
from plugins.hermes_ui.docs_formula import is_safe_formula
from plugins.hermes_ui.docs_parse import KINDS, parse_harvis_doc, strip_fence
from plugins.hermes_ui.docs_rich import RICH_KINDS, parse_number, parse_rich, parse_timeline

_OPEN = re.compile(r"^\s*(`{3,})\s*harvis-doc\s*$", re.I)
_CLOSE = re.compile(r"^\s*`{3,}\s*$")
_RICH_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_-]*)\s*$")
_RULE = re.compile(r"^\s*-{3,}\s*$")
_ALIASES = {"slides": "deck", "presentation": "deck", "pptx": "deck", "spreadsheet": "sheet",
            "xlsx": "sheet", "excel": "sheet", "csv": "sheet"}
_META_KEYS = {"chart": ("title", "type", "series"), "quadrant": ("title", "x", "y")}
_MAX_PROBLEMS = 25


def _clip(text: str, n: int = 50) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _fence_problems(lines: list[str]) -> list[str]:
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None:
        return []
    m = _OPEN.match(lines[first])
    if not m:
        return []
    out = []
    last = next((i for i in range(len(lines) - 1, first, -1) if lines[i].strip()), None)
    if last is None or not _CLOSE.match(lines[last]):
        out.append(f"The block opened with {len(m.group(1))} backticks and harvis-doc is never closed. "
                   f"End it with a line of {len(m.group(1))} backticks.")
    if len(m.group(1)) == 3 and any(_RICH_FENCE.match(ln) and _RICH_FENCE.match(ln).group(2)
                                    for ln in lines[first + 1:]):
        out.append("The outer fence is three backticks, the same as the chart/timeline/code blocks inside it, "
                   "so the first inner block would close the document. Open and close the document with four backticks.")
    return out


def _header_problems(text: str) -> list[str]:
    lines = text.split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.strip()), None)
    if i is None or not _RULE.match(lines[i]):
        return ["There is no header. Start with a line of ---, then kind:, title: and outline: lines, then ---."]
    kind: Optional[str] = None
    title = False
    for ln in lines[i + 1:]:
        if _RULE.match(ln):
            break
        pair = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$", ln)
        if pair and pair.group(1).lower() in ("kind", "type"):
            kind = pair.group(2).split(" #")[0].strip().strip("\"'").lower()
        elif pair and pair.group(1).lower() == "title" and pair.group(2).strip():
            title = True
    else:
        return ["The header is never closed. Add a second line of --- after the outline."]
    out = []
    if kind is None:
        out.append("The header has no kind: line, so this is read as a doc. Use kind: deck, doc, sheet or pdf.")
    elif kind not in KINDS:
        if kind in _ALIASES:
            out.append(f"kind: {kind} is read as {_ALIASES[kind]}. Write kind: {_ALIASES[kind]}.")
        else:
            out.append(f"Unknown kind '{_clip(kind, 20)}', read as a doc. Use deck, doc, sheet or pdf.")
    if not title:
        out.append("The header has no title: line.")
    return out


def _rich_issues(kind: str, text: str) -> list[str]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out: list[str] = []
    if not lines:
        return ["it is empty"]
    if kind == "chart":
        from plugins.hermes_ui.docs_rich import _meta
        rows = 0
        for ln in lines:
            if _meta(ln, _META_KEYS["chart"]):
                continue
            label, _s, rest = ln.rpartition(":")
            values = [v for v in (parse_number(t) for t in re.split(r",(?!\d{3}(?!\d))", rest)) if v is not None]
            if _s and label.strip() and values:
                rows += 1
            else:
                out.append(f"line '{_clip(ln)}' is dropped (a chart line is 'Label: number, number')")
        if not rows:
            out.append("it has no data rows")
    elif kind == "timeline":
        for ln in lines:
            if ln.split("|")[0].lstrip("*").strip() == "" and not ln.lower().startswith(("title:", "subtitle:")):
                out.append(f"line '{_clip(ln)}' has no label and is dropped")
        t = parse_timeline(text)
        bad = [i.label for i in t.items if (i.start_text and i.start is None) or (i.end_text and i.end is None)]
        if bad:
            out.append(f"dates for {', '.join(_clip(b, 25) for b in bad[:3])} are not understood, so the "
                       "timeline is spaced evenly instead of drawn to scale (use Oct 26 or 2026-10-26)")
    elif kind == "quadrant":
        from plugins.hermes_ui.docs_rich import _meta
        cells = [ln for ln in lines if not _meta(ln, _META_KEYS["quadrant"]) and ln.partition(":")[0].strip()]
        if len(cells) > 4:
            out.append(f"only the first four cell lines are used; {len(cells) - 4} dropped")
        elif len(cells) < 4:
            out.append(f"it has {len(cells)} cell lines; the other {4 - len(cells)} cells are drawn empty")
    elif kind == "cards":
        if len(lines) > 6:
            out.append(f"{len(lines)} cards; 1 to 6 fit without wrapping")
    elif kind == "flow":
        for ln in lines:
            if not re.search(r"-+>|→", ln):
                out.append(f"line '{_clip(ln)}' has no -> so it is a lone box with no arrows")
    elif kind == "csv":
        if len(parse_rich("csv", text).rows) < 2:
            out.append("it has a header row but no data rows")
    return out


def _rich_problems(text: str) -> list[str]:
    out: list[str] = []
    lines = text.split("\n")
    counts: dict[str, int] = {}
    i = 0
    while i < len(lines):
        m = _RICH_FENCE.match(lines[i])
        if not m or not m.group(2):
            i += 1
            continue
        mark, lang = m.group(1), m.group(2).lower()
        body, i = [], i + 1
        while i < len(lines) and not (lines[i].strip().startswith(mark[0] * len(mark))
                                      and not lines[i].strip().strip(mark[0])):
            body.append(lines[i])
            i += 1
        closed = i < len(lines)
        i += 1
        if lang not in RICH_KINDS:
            continue
        counts[lang] = counts.get(lang, 0) + 1
        name = f"{lang} block {counts[lang]}"
        if not closed:
            out.append(f"The {name} is never closed with ```.")
            continue
        out.extend(f"In {name}: {p}." for p in _rich_issues(lang, "\n".join(body)))
    return out


def _formula_problems(doc) -> list[str]:
    out = []
    for sheet in doc.sheets:
        for ri, row in enumerate(sheet.rows, 1):
            if ri == 1:
                continue
            for ci, cell in enumerate(row, 1):
                raw = re.sub(r"^\s*(\*\*|__)(.+)\1\s*$", r"\2", cell).strip()
                if raw.startswith("=") and len(raw) > 1 and not is_safe_formula(raw):
                    out.append(f"Sheet '{_clip(sheet.name, 20)}' row {ri} column {ci}: '{_clip(raw, 40)}' uses a "
                               "function that is not allowed, so it is stored as text, not a formula.")
    return out


def _placeholder_problems(doc) -> list[str]:
    """Stand-in text (lorem ipsum, TBD, [Company Name]) the author has to replace; the same scan docs_check runs."""
    from plugins.hermes_ui.docs_check import check_placeholders

    return [f"{i['where']}: {i['message']}." for i in check_placeholders(doc)]


def validate_source(source) -> dict:
    """{ok, kind, title, parts, problems}. ``ok`` means no problems at all."""
    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "kind": None, "title": "", "parts": 0, "problems": ["The document is empty."]}
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return {"ok": False, "kind": None, "title": "", "parts": 0,
                "problems": [f"The document is larger than {MAX_SOURCE_BYTES // 1000} KB."]}
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    problems = _fence_problems(text.split("\n"))
    body = strip_fence(text)
    problems += _header_problems(body)
    doc = parse_harvis_doc(text)
    if doc.header_complete:
        try:
            parse_for_export(text, FORMATS[doc.kind][0])
        except ExportError as exc:
            problems.append(str(exc))
        problems += _rich_problems(body)
        if doc.kind == "sheet":
            problems += _formula_problems(doc)
        problems += _placeholder_problems(doc)
    parts = len(doc.sheets) if doc.kind == "sheet" else len(doc.sections)
    return {"ok": not problems, "kind": doc.kind, "title": doc.title, "parts": parts,
            "problems": problems[:_MAX_PROBLEMS]}
