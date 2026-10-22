"""Spreadsheet formulas from a document nobody has vetted.

``is_safe_formula`` decides whether a ``=...`` cell may be written to an xlsx as
a live formula: a closed list of worksheet functions, no external references and
no way to reach out (WEBSERVICE, HYPERLINK, DDE pipes). ``evaluate`` reads the
common arithmetic subset so a CSV carries numbers instead of formula text, which
another program would execute or show raw.
"""
from __future__ import annotations

import math
import re
from typing import Callable, Optional

SAFE_FUNCTIONS = frozenset((
    "SUM SUMIF SUMIFS SUMPRODUCT AVERAGE AVERAGEIF MIN MAX COUNT COUNTA COUNTIF COUNTIFS MEDIAN PRODUCT "
    "ROUND ROUNDUP ROUNDDOWN ABS INT MOD POWER SQRT IF IFERROR AND OR NOT LEN LEFT RIGHT MID TRIM UPPER "
    "LOWER CONCAT CONCATENATE TEXT VLOOKUP HLOOKUP INDEX MATCH TODAY NOW DATE YEAR MONTH DAY"
).split())

_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_FORBIDDEN = re.compile(r"[\[\]|@{}\\]|\bhttps?:|\bfile:", re.I)


def is_safe_formula(formula: str) -> bool:
    if len(formula) > 1000 or _FORBIDDEN.search(formula):
        return False
    # Quoted text is not code: "SUM(" inside a string is only text.
    code = re.sub(r'"(?:[^"]|"")*"', '""', formula)
    return all(name.upper() in SAFE_FUNCTIONS for name in _NAME.findall(code))


# ---- evaluator: numbers, cell refs, ranges, + - * / ^, % and a few functions ----

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)"
                    r"|([A-Za-z_][A-Za-z0-9_.]*)(?=\s*\()|(.))")


class FormulaError(Exception):
    pass


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _ref(ref: str) -> tuple[int, int]:
    m = re.match(r"\$?([A-Za-z]+)\$?(\d+)$", ref)
    if not m:
        raise FormulaError(ref)
    return int(m.group(2)) - 1, _col_index(m.group(1))


def _flat(args: list) -> list[float]:
    out: list[float] = []
    for a in args:
        out.extend(a if isinstance(a, list) else [a])
    return out


_FUNCS: dict[str, Callable[[list], float]] = {
    "SUM": lambda a: sum(_flat(a)),
    "AVERAGE": lambda a: sum(_flat(a)) / len(_flat(a)),
    "MIN": lambda a: min(_flat(a)),
    "MAX": lambda a: max(_flat(a)),
    "COUNT": lambda a: float(len(_flat(a))),
    "PRODUCT": lambda a: math.prod(_flat(a)),
    "ABS": lambda a: abs(_flat(a)[0]),
    "ROUND": lambda a: round(_flat(a)[0], int(_flat(a)[1]) if len(_flat(a)) > 1 else 0),
}


def evaluate(formula: str, cell: Callable[[int, int], Optional[float]], depth: int = 0) -> float:
    """Value of ``=...`` using ``cell(row, col)`` for references (None when empty or text).

    Raises FormulaError for anything outside the subset."""
    if depth > 20:
        raise FormulaError("circular")
    tokens: list[tuple[str, str]] = []
    pos, src = 0, formula.lstrip("=")
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            tokens.append(("num", m.group(1)))
        elif m.group(2):
            tokens.append(("ref", m.group(2)))
        elif m.group(3):
            tokens.append(("fn", m.group(3).upper()))
        elif m.group(4) and not m.group(4).isspace():
            tokens.append(("op", m.group(4)))
    i = 0

    def peek() -> tuple[str, str]:
        return tokens[i] if i < len(tokens) else ("end", "")

    def take() -> tuple[str, str]:
        nonlocal i
        i += 1
        return tokens[i - 1]

    def expr():
        v = term()
        while peek() in (("op", "+"), ("op", "-")):
            v = v + term() if take()[1] == "+" else v - term()
        return v

    def term():
        v = power()
        while peek() in (("op", "*"), ("op", "/")):
            if take()[1] == "*":
                v = v * power()
            else:
                d = power()
                if d == 0:
                    raise FormulaError("div0")
                v = v / d
        return v

    def power():
        v = unary()
        if peek() == ("op", "^"):
            take()
            v = v ** unary()
        return v

    def unary():
        if peek() == ("op", "-"):
            take()
            return -unary()
        if peek() == ("op", "+"):
            take()
        return atom()

    def atom():
        kind, text = take() if tokens[i:] else ("end", "")
        if kind == "num":
            v = float(text)
        elif kind == "ref":
            if ":" in text:
                a, b = text.split(":")
                (r1, c1), (r2, c2) = _ref(a), _ref(b)
                if (abs(r2 - r1) + 1) * (abs(c2 - c1) + 1) > 100000:
                    raise FormulaError("range")
                v = [x for r in range(min(r1, r2), max(r1, r2) + 1) for c in range(min(c1, c2), max(c1, c2) + 1)
                     if (x := cell(r, c)) is not None]
                return v
            r, c = _ref(text)
            x = cell(r, c)
            v = 0.0 if x is None else x
        elif kind == "fn":
            if take() != ("op", "("):
                raise FormulaError("call")
            args = []
            if peek() != ("op", ")"):
                args.append(expr())
                while peek() == ("op", ","):
                    take()
                    args.append(expr())
            if take() != ("op", ")") or text not in _FUNCS:
                raise FormulaError(text)
            try:
                v = _FUNCS[text](args)
            except (ValueError, ZeroDivisionError, IndexError) as exc:
                raise FormulaError(text) from exc
        elif (kind, text) == ("op", "("):
            v = expr()
            if take() != ("op", ")"):
                raise FormulaError("paren")
        else:
            raise FormulaError("syntax")
        while peek() == ("op", "%"):
            take()
            v = v / 100
        return v

    try:
        result = expr()
        if i != len(tokens) or isinstance(result, list):
            raise FormulaError("syntax")
        return float(result)
    except (TypeError, OverflowError, ValueError, RecursionError) as exc:
        raise FormulaError(str(exc)) from exc


# ---- cell values ----

_NUMBER = re.compile(
    r"^(?P<open>\()?\s*(?P<sign>-)?\s*(?P<cur>\$)?\s*(?P<sign2>-)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"\s*(?P<pct>%)?\s*(?P<close>\))?$")


def parse_number(raw: str) -> Optional[tuple[float, Optional[str]]]:
    """(value, Excel number format) for ``1,200`` / ``$40`` / ``12%`` / ``(300)`` / ``-4.5``; else None.

    Digit strings that are identifiers (``007``, a 16-digit card or phone number) stay text."""
    m = _NUMBER.match(raw.strip())
    if not m or bool(m.group("open")) != bool(m.group("close")):
        return None
    num = m.group("num")
    plain = num.replace(",", "")
    if (re.match(r"0\d", plain) and "," not in num) or len(plain.replace(".", "")) > 15:
        return None
    value = float(plain)
    if m.group("open") or m.group("sign") or m.group("sign2"):
        value = -value
    decimals = "." in num
    if m.group("pct"):
        value, fmt = value / 100, ("0.0%" if decimals else "0%")
    elif m.group("cur"):
        fmt = "$#,##0.00" if decimals else "$#,##0"
    elif "," in num:
        fmt = "#,##0.00" if decimals else "#,##0"
    else:
        fmt = None
    return (int(value) if value == int(value) and not m.group("pct") else value), fmt
