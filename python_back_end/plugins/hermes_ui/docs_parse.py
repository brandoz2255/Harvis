"""Python reading of a ``harvis-doc`` block, for export.

A mirror of front_end/hermes-desktop-ui/src/lib/harvis-doc.ts (parseHarvisDoc):
the same header, the same slide / section / sheet splitting, the same title
fallbacks, so the file a person downloads has the parts they watched arrive.
Keep the two in step. Like the TypeScript, it tolerates a truncated prefix and
never raises; whether a truncated document is worth exporting is for the caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

KINDS = ("deck", "doc", "pdf", "sheet")

_FENCE_RE = re.compile(r"^\s*-{3,}\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_CODE_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass
class Section:
    title: str = ""
    body: str = ""


@dataclass
class Sheet:
    name: str = ""
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ParsedDoc:
    kind: str = "doc"
    title: str = ""
    outline: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    sheets: list[Sheet] = field(default_factory=list)
    header_complete: bool = True
    theme: str = ""             # the ``theme:`` header value, lowercased; "" when absent (docs_theme falls back to default)


def _normalize_kind(value: str) -> str:
    v = value.strip().lower()
    if v in ("deck", "slides", "presentation", "pptx"):
        return "deck"
    if v in ("sheet", "spreadsheet", "xlsx", "excel", "csv"):
        return "sheet"
    return "pdf" if v == "pdf" else "doc"


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] in "\"'" and v.endswith(v[0]):
        return v[1:-1]
    return v


def strip_fence(source: str) -> str:
    """Drop an outer ````harvis-doc fence if the caller left it on."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^\s*`{3,}\s*harvis-doc\s*$", lines[0], re.I):
        lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and re.match(r"^\s*`{3,}\s*$", lines[-1]):
            lines.pop()
    return "\n".join(lines)


def _parse_header(source: str):
    """(closed, kind, outline, rest, title, theme)"""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not _FENCE_RE.match(lines[i]):
        return True, "doc", [], "\n".join(lines[i:]), "", ""

    kind, title, theme, outline, in_outline = "doc", "", "", [], False
    theme_at = -1
    for j in range(i + 1, len(lines)):
        line = lines[j]
        if _FENCE_RE.match(line):
            # Small models copy a "<body>" placeholder from the prompt; it is never content.
            rest = [ln for ln in lines[j + 1:] if not _BODY_TAG_RE.match(ln)]
            return True, kind, outline, "\n".join(rest), title, theme
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if in_outline and item:
            label = _unquote(item.group(1))
            if label:
                outline.append(label)
            continue
        pair = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not pair:
            continue
        key, value = pair.group(1).lower(), pair.group(2)
        in_outline = False
        if key in ("kind", "type"):
            # "kind: deck   # deck | doc | ..." is how the prompt's own example reads.
            kind = _normalize_kind(_unquote(value.split(" #")[0]))
        elif key == "title":
            title = _unquote(value)
        elif key == "theme":
            theme, theme_at = _unquote(value.split(" #")[0]).strip().lower(), j
        elif key in ("outline", "sections", "slides", "sheets"):
            inline = re.match(r"^\[(.*?)\]?\s*$", value.strip())
            if inline and value.strip():
                outline.extend(x for x in (_unquote(p) for p in inline.group(1).split(",")) if x)
            else:
                in_outline = True
    # Still inside the header: the last line may be half a word, so a trailing outline
    # item with no newline after it yet is not counted.
    if not source.endswith("\n") and in_outline and outline:
        outline.pop()
    if not source.endswith("\n") and theme_at == len(lines) - 1:      # "theme: pap" so far: not a name yet
        theme = ""
    return False, kind, outline, "", title, theme


def _split_slides(body: str) -> list[Section]:
    slides: list[list[str]] = [[]]
    in_code = False
    for line in body.split("\n"):
        if _CODE_FENCE_OPEN.match(line):
            in_code = not in_code
        heading = None if in_code else _HEADING_RE.match(line)
        if not in_code and _FENCE_RE.match(line):
            slides.append([])
        elif heading and len(heading.group(1)) <= 2 and any(x.strip() for x in slides[-1]):
            slides.append([line])                    # small models forget the `---`: a new title is a new slide
        else:
            slides[-1].append(line)
    out = []
    for lines in slides:
        text = "\n".join(lines).strip()
        if not text:
            continue
        first = text.split("\n")
        heading = _HEADING_RE.match(first[0])
        out.append(Section(heading.group(2), "\n".join(first[1:]).strip()) if heading else Section("", text))
    return out


def _split_sections(body: str) -> list[Section]:
    sections: list[Section] = []
    current: tuple[str, list[str]] | None = None
    lead: list[str] = []
    in_code = False
    for line in body.split("\n"):
        # A `## ` inside a code fence is code, not a section (the TypeScript has no fence state).
        if _CODE_FENCE_OPEN.match(line):
            in_code = not in_code
        heading = None if in_code else _HEADING_RE.match(line)
        if heading and len(heading.group(1)) == 2:
            if current:
                sections.append(Section(current[0], "\n".join(current[1]).strip()))
            current = (heading.group(2), [])
        elif current:
            current[1].append(line)
        elif not (heading and len(heading.group(1)) == 1):
            lead.append(line)
    if current:
        sections.append(Section(current[0], "\n".join(current[1]).strip()))
    intro = "\n".join(lead).strip()
    return [Section("", intro), *sections] if intro else sections


_BODY_TAG_RE = re.compile(r"^\s*</?body>\s*$", re.IGNORECASE)


def split_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


def is_divider(line: str) -> bool:
    return bool(_DIVIDER_RE.match(line))


def parse_sheet_table(body: str) -> list[list[str]]:
    return [split_row(line) for line in body.split("\n") if "|" in line and not _DIVIDER_RE.match(line)]


def parse_harvis_doc(source: str) -> ParsedDoc:
    """Parse a whole or partial block body. Never raises."""
    closed, kind, outline, body, title, theme = _parse_header(strip_fence(source or ""))
    if not closed:
        return ParsedDoc(kind=kind, title=title, outline=outline, header_complete=False, theme=theme)

    sections = _split_slides(body) if kind == "deck" else _split_sections(body)
    if not title:
        h1 = next((m for m in (_HEADING_RE.match(line) for line in body.split("\n")) if m and len(m.group(1)) == 1), None)
        title = h1.group(2) if h1 else (sections[0].title if sections else "")
    sections = [s for i, s in enumerate(sections) if s.title or s.body or i == len(sections) - 1]

    sheets: list[Sheet] = []
    if kind == "sheet":
        for i, s in enumerate(x for x in sections if x.title or "|" in x.body):
            sheets.append(Sheet(s.title or (outline[i] if i < len(outline) else f"Sheet{i + 1}"),
                                parse_sheet_table(s.body)))
    return ParsedDoc(kind=kind, title=title, outline=outline, sections=sections, sheets=sheets, theme=theme)
