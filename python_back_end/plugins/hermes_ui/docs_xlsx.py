"""A sheet block to .xlsx and .csv: real numbers, live formulas, a bold frozen header.

An xlsx with formulas is sent through the document sandbox's /recalc (docs_render_client.recalc_xlsx) so the
file carries each formula's value, not only its text: a viewer that does not calculate (a phone preview, a
parser, python's openpyxl) then shows numbers. When the sandbox is down the unrecalculated bytes are returned.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .docs_blocks import inline_runs, plain_text
from .docs_formula import FormulaError, RecursionUnknowable, Unknowable, evaluate_any, is_safe_formula
from .docs_number import parse_number
from .docs_parse import ParsedDoc, Sheet

_BAD_NAME = re.compile(r"[\[\]:*?/\\]")
_HEADER_FILL = PatternFill("solid", fgColor="DDE7F3")
_RULE = Border(bottom=Side(style="thin", color="8AA4C8"))
# Models bold whole total cells (**=SUM(B2:B4)**, **2700**): still a formula or a number, shown bold.
_WHOLE_BOLD = re.compile(r"^\s*(\*\*|__)(.+)\1\s*$")
_COUNTING = re.compile(r"^=\s*COUNT(?:A|IF|IFS)?\s*\(", re.I)     # a count is a plain number, whatever the column shows
log = logging.getLogger(__name__)


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


def _carry_formats(ws, typed: dict[int, list[tuple[int, Optional[str]]]], formulas: list[tuple[int, int, str]]) -> None:
    """A formula cell shows its result the way the column shows its numbers: the format of the nearest typed number
    above it (or below, when none is above), so a currency column's total is currency and not 1234.5."""
    for ri, ci, text in formulas:
        near = typed.get(ci)
        if not near or _COUNTING.match(text):
            continue
        _row, fmt = min(near, key=lambda t: (abs(t[0] - ri), t[0] > ri))
        if fmt:
            ws.cell(row=ri, column=ci).number_format = fmt


def _recalc_enabled() -> bool:
    return os.environ.get("DOCS_XLSX_RECALC", "1").strip().lower() not in ("0", "off", "false", "no")


def _recalculated(plain: bytes) -> bytes:
    """``plain`` after the sandbox calculated every formula, or ``plain`` itself when it cannot."""
    if not _recalc_enabled():
        return plain
    try:
        from .docs_render_client import recalc_xlsx     # not at the top: it reads the environment and opens sockets
        fresh = recalc_xlsx(plain)
        if not fresh:
            return plain
        names = [load_workbook(io.BytesIO(b), read_only=True).sheetnames for b in (plain, fresh)]
        if names[0] != names[1]:                        # a recalculation that renamed or dropped a sheet is not ours
            log.warning("recalculated workbook has different sheets; keeping the original")
            return plain
        return fresh
    except Exception:                                   # noqa: BLE001 - values are a nicety; the export must succeed
        log.warning("xlsx recalculation failed; exporting without cached values", exc_info=True)
        return plain


def build_xlsx(doc: ParsedDoc) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    live = False
    for n, sheet in enumerate(doc.sheets, 1):
        ws = wb.create_sheet(_sheet_name(sheet.name, n, used))
        widths: dict[int, int] = {}
        typed: dict[int, list[tuple[int, Optional[str]]]] = {}      # column -> (row, number format) of typed numbers
        formulas: list[tuple[int, int, str]] = []                   # (row, column, text) of live formulas
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
                    if is_safe_formula(text):
                        formulas.append((ri, ci, text))
                    else:                                  # unknown function or an external reference
                        cell.data_type = "s"
                else:
                    number = parse_number(raw) if ri > 1 else None
                    if number:
                        cell.value, fmt = number
                        typed.setdefault(ci, []).append((ri, fmt))
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
        _carry_formats(ws, typed, formulas)
        live = live or bool(formulas)
    out = io.BytesIO()
    wb.save(out)
    return _recalculated(out.getvalue()) if live else out.getvalue()


def _number_text(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(round(value, 10))


def _result_text(v) -> str:
    """A formula's result as the cell would show it: a number, TRUE/FALSE, or its text."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return v if isinstance(v, str) else _number_text(v)


def _csv_text(text: str) -> str:
    """A text cell that opens like a formula is quoted so a spreadsheet shows it as text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not parse_number(text) else text


def build_csv(sheet: Sheet) -> bytes:
    """The sheet as CSV, UTF-8 with a BOM so Excel reads accents. Formulas are computed,
    never written out as ``=...`` text, which another program would run or show raw."""
    rows = sheet.rows
    cache: dict[tuple[int, int], object] = {}
    failed: dict[tuple[int, int], tuple[type, tuple]] = {}      # cells whose formula raised, so each is worked out once
    busy: set[tuple[int, int]] = set()

    def value(r: int, c: int):
        """What a formula reads from the cell: a number (formulas evaluated), its text, or None when empty.
        An error is remembered like a value: IFERROR catches it, and without this every read of the cell
        would run its formula again, doubling the work for each row that reads the one above."""
        key = (r, c)
        if key in cache:
            return cache[key]
        if key in failed:
            kind, args = failed[key]
            raise kind(*args)                           # a fresh exception: re-raising one grows its traceback
        raw = _unwrap(rows[r][c])[0] if r < len(rows) and c < len(rows[r]) else ""
        if key in busy:
            raise Unknowable("circular")
        busy.add(key)
        try:
            if r > 0 and _is_formula(raw):
                result = evaluate_any(raw, value)
            else:
                parsed = parse_number(raw) if r > 0 else None
                result = parsed[0] if parsed else (clean_text(raw)[0] or None)
        except (FormulaError, ZeroDivisionError, TypeError, OverflowError, ValueError) as exc:
            if not isinstance(exc, RecursionUnknowable):        # too deep just now says nothing about the cell
                failed[key] = (type(exc), exc.args)
            raise
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
                    result = value(r, c)
                    line.append(_csv_text(result) if isinstance(result, str) else _result_text(result))
                except (FormulaError, ZeroDivisionError, TypeError, OverflowError, ValueError):
                    line.append("#VALUE!")
                continue
            line.append(_csv_text(clean_text(raw)[0]))
        writer.writerow(line)
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")
