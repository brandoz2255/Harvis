"""A sheet block to .xlsx and .csv: real numbers, live formulas, a bold frozen header."""
from __future__ import annotations

import csv
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .docs_blocks import inline_runs, plain_text
from .docs_formula import FormulaError, evaluate, is_safe_formula, parse_number
from .docs_parse import ParsedDoc, Sheet

_BAD_NAME = re.compile(r"[\[\]:*?/\\]")
_HEADER_FILL = PatternFill("solid", fgColor="DDE7F3")
_RULE = Border(bottom=Side(style="thin", color="8AA4C8"))
# Models bold whole total cells (**=SUM(B2:B4)**, **2700**): still a formula or a number, shown bold.
_WHOLE_BOLD = re.compile(r"^\s*(\*\*|__)(.+)\1\s*$")


def _unwrap(raw: str) -> tuple[str, bool]:
    m = _WHOLE_BOLD.match(raw)
    return (m.group(2).strip(), True) if m else (raw, False)


def _sheet_name(raw: str, index: int, used: set[str]) -> str:
    """Excel's rules: at most 31 characters, none of []:*?/\\, no edge apostrophes, unique."""
    name = re.sub(r"\s+", " ", _BAD_NAME.sub(" ", raw or "")).strip().strip("'").strip()[:31].strip().strip("'")
    name = name or f"Sheet{index}"
    base, n = name, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


def clean_text(raw: str) -> tuple[str, bool]:
    """(cell text without markdown marks, whether the whole cell was bold)."""
    runs = inline_runs(raw.replace("<br>", "\n").replace("<br/>", "\n"))
    return plain_text(runs), len(runs) == 1 and runs[0].bold


def _is_formula(raw: str) -> bool:
    return raw.strip().startswith("=") and len(raw.strip()) > 1


def build_xlsx(doc: ParsedDoc) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for n, sheet in enumerate(doc.sheets, 1):
        ws = wb.create_sheet(_sheet_name(sheet.name, n, used))
        widths: dict[int, int] = {}
        for ri, row in enumerate(sheet.rows, 1):
            for ci, original in enumerate(row, 1):
                cell = ws.cell(row=ri, column=ci)
                shown = 10
                raw, wrapped = _unwrap(original)
                if wrapped and ri > 1 and (_is_formula(raw) or parse_number(raw)):
                    cell.font = Font(bold=True)
                else:
                    raw = original
                if _is_formula(raw) and ri > 1:
                    text = raw.strip()
                    cell.value = text
                    if not is_safe_formula(text):          # unknown function or an external reference
                        cell.data_type = "s"
                else:
                    number = parse_number(raw) if ri > 1 else None
                    if number:
                        cell.value, fmt = number
                        if fmt:
                            cell.number_format = fmt
                        shown = len(str(raw)) + 2
                    else:
                        text, bold = clean_text(raw)
                        cell.value = text or None
                        cell.data_type = "s" if text.startswith("=") else cell.data_type
                        if bold:
                            cell.font = Font(bold=True)
                        shown = max((len(x) for x in text.split("\n")), default=0) + 2
                        if len(text) > 60:
                            cell.alignment = Alignment(wrap_text=True, vertical="top")
                if ri == 1:
                    cell.font = Font(bold=True)
                    cell.fill = _HEADER_FILL
                    cell.border = _RULE
                widths[ci] = max(widths.get(ci, 0), shown)
        for ci, w in widths.items():
            ws.column_dimensions[get_column_letter(ci)].width = min(max(w, 8), 60)
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _number_text(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(round(value, 10))


def build_csv(sheet: Sheet) -> bytes:
    """The sheet as CSV, UTF-8 with a BOM so Excel reads accents. Formulas are computed,
    never written out as ``=...`` text, which another program would run or show raw."""
    rows = sheet.rows
    cache: dict[tuple[int, int], object] = {}
    busy: set[tuple[int, int]] = set()

    def value(r: int, c: int):
        """The cell as a number (formulas evaluated), or None when empty or text."""
        key = (r, c)
        if key in cache:
            return cache[key]
        raw = _unwrap(rows[r][c])[0] if r < len(rows) and c < len(rows[r]) else ""
        if key in busy:
            raise FormulaError("circular")
        busy.add(key)
        try:
            if r > 0 and _is_formula(raw):
                result = evaluate(raw, value)
            else:
                parsed = parse_number(raw) if r > 0 else None
                result = parsed[0] if parsed else None
        finally:
            busy.discard(key)
        cache[key] = result
        return result

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    for r, row in enumerate(rows):
        line = []
        for c, raw in enumerate(row):
            if r > 0 and _is_formula(_unwrap(raw)[0]):
                try:
                    line.append(_number_text(value(r, c)))
                except (FormulaError, ZeroDivisionError, TypeError):
                    line.append("#VALUE!")
                continue
            text = clean_text(raw)[0]
            # A text cell that opens like a formula is quoted so a spreadsheet shows it as text.
            line.append("'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not parse_number(text) else text)
        writer.writerow(line)
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")
