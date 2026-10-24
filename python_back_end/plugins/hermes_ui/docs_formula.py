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


# ---- evaluator: numbers, text, cell refs, ranges, arithmetic, comparisons and a few functions ----

# Written in a fresh pass: a closed grammar (no eval), each node a small function that is run only when
# its value is needed, so the branch IF does not take is never calculated.
_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|(\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)"
                    r"|([A-Za-z_][A-Za-z0-9_.]*)(?=\s*\()|\"((?:[^\"]|\"\")*)\"|(<=|>=|<>|[A-Za-z_][A-Za-z0-9_.]*|.))")
_COMPARISONS = ("=", "<>", "<", ">", "<=", ">=")
MAX_RANGE_CELLS = 100000


class FormulaError(Exception):
    """The formula has an error value a spreadsheet would show (``div0``, ``value``, ``na``, ``ref``): IFERROR
    catches these."""


class Unknowable(FormulaError):
    """The value cannot be known here: a syntax the evaluator does not read, a function only a real spreadsheet
    program can calculate, a missing stored value, or a circular reference. IFERROR must not turn these into
    its fallback, because the real value may be anything."""


class Blank(float):
    """An empty cell read by reference: 0 in arithmetic, and equal to "" in a comparison."""

    def __eq__(self, other):
        return other == "" or float.__eq__(self, other) is True

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = float.__hash__


BLANK = Blank(0.0)


class _Range(list):
    """The cells of a range in row-major order, empty ones as None, and its shape."""
    rows = cols = 0


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _ref(ref: str) -> tuple[int, int]:
    m = re.match(r"\$?([A-Za-z]+)\$?(\d+)$", ref)
    if not m:
        raise Unknowable(ref)
    return int(m.group(2)) - 1, _col_index(m.group(1))


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num(x) -> float:
    """A value as a number the way a spreadsheet reads one in arithmetic: text must look like a number."""
    if isinstance(x, list):
        raise FormulaError("range")
    if isinstance(x, str):
        try:
            return float(x.replace(",", "").strip())
        except ValueError:
            raise FormulaError("value") from None
    return 0.0 if x is None else float(x)


def _truth(x) -> bool:
    if isinstance(x, list):
        raise FormulaError("range")
    if isinstance(x, str):
        if x.strip().upper() in ("TRUE", "FALSE"):
            return x.strip().upper() == "TRUE"
        raise FormulaError("value")
    return bool(x)


def _flat(args: list) -> list[float]:
    """Numbers to aggregate: everything in a range that is a number (text and blanks are skipped), and each
    plain argument read as a number."""
    out: list[float] = []
    for a in args:
        if isinstance(a, list):
            out.extend(float(x) for x in a if _is_number(x))
        else:
            out.append(_num(a))
    return out


def _rank(v):
    if isinstance(v, bool):
        return 2, v
    if isinstance(v, str):
        return 1, v.lower()
    return 0, float(v)


def _compare(op: str, a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        raise FormulaError("range")
    if isinstance(a, Blank) and isinstance(b, str):
        a = ""
    if isinstance(b, Blank) and isinstance(a, str):
        b = ""
    ka, kb = _rank(a), _rank(b)
    return {"=": ka == kb, "<>": ka != kb, "<": ka < kb, ">": ka > kb, "<=": ka <= kb, ">=": ka >= kb}[op]


def _criterion(crit) -> Callable[[object], bool]:
    """A SUMIF/COUNTIF test: 5, ">5", "<>x", "Food" (any case, * and ? match text)."""
    if isinstance(crit, str):
        m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", crit, re.S)
        op, rest = m.group(1) or "=", m.group(2)
        try:
            target = float(rest.replace(",", ""))
        except ValueError:
            target = rest
    else:
        op, target = "=", _num(crit)
    wild = None
    if isinstance(target, str) and op in ("=", "<>") and ("*" in target or "?" in target):
        wild = re.compile("".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in target) + r"\Z",
                          re.I | re.S)

    def test(v) -> bool:
        if isinstance(target, str):
            if target == "" and op == "=":
                return v is None or v == ""
            if target == "" and op == "<>":                  # "<>" alone means "not empty"
                return v is not None and v != ""
            if not isinstance(v, str):
                return op == "<>"
            hit = bool(wild.match(v)) if wild else _compare("=", v, target)
            return hit if op == "=" else not hit if op == "<>" else _compare(op, v, target)
        return _is_number(v) and _compare(op, v, target)

    return test


def _sumif(a: list) -> float:
    if len(a) < 2 or len(a) > 3:
        raise Unknowable("SUMIF")
    if not isinstance(a[0], list) or (len(a) > 2 and not isinstance(a[2], list)):
        raise FormulaError("SUMIF")
    test, sums = _criterion(a[1]), a[2] if len(a) > 2 else a[0]
    return sum(float(sums[i]) for i, v in enumerate(a[0]) if test(v) and i < len(sums) and _is_number(sums[i]))


def _countif(a: list) -> float:
    if len(a) != 2:
        raise Unknowable("COUNTIF")
    if not isinstance(a[0], list):
        raise FormulaError("COUNTIF")
    test = _criterion(a[1])
    return float(sum(1 for v in a[0] if test(v)))


def _vlookup(a: list):
    if not 3 <= len(a) <= 4:
        raise Unknowable("VLOOKUP")
    if not isinstance(a[1], _Range):
        raise FormulaError("VLOOKUP")
    key, table, col = a[0], a[1], int(_num(a[2]))
    exact = len(a) > 3 and not _truth(a[3])
    if not 1 <= col <= table.cols:
        raise FormulaError("ref")
    found = None
    for i in range(table.rows):
        row = table[i * table.cols:(i + 1) * table.cols]
        first = row[0]
        if first is None or _rank(first)[0] != _rank(key)[0]:
            continue
        if exact:
            if _compare("=", first, key):
                found = row
                break
        elif _compare("<=", first, key):
            found = row                      # sorted ascending: the last row not past the key
    if found is None:
        raise FormulaError("na")
    return BLANK if found[col - 1] is None else found[col - 1]


_FUNCS: dict[str, Callable[[list], object]] = {
    "SUM": lambda a: sum(_flat(a)),
    "AVERAGE": lambda a: sum(_flat(a)) / len(_flat(a)),
    "MIN": lambda a: min(_flat(a)),
    "MAX": lambda a: max(_flat(a)),
    "COUNT": lambda a: float(len(_flat(a))),
    "PRODUCT": lambda a: math.prod(_flat(a)),
    "ABS": lambda a: abs(_flat(a)[0]),
    "ROUND": lambda a: round(_flat(a)[0], int(_flat(a)[1]) if len(_flat(a)) > 1 else 0),
    "AND": lambda a: all(_truth(x) for v in a for x in (v if isinstance(v, list) else [v]) if x is not None),
    "OR": lambda a: any(_truth(x) for v in a for x in (v if isinstance(v, list) else [v]) if x is not None),
    "NOT": lambda a: not _truth(a[0]),
    "SUMIF": _sumif,
    "COUNTIF": _countif,
    "VLOOKUP": _vlookup,
}
_LAZY = frozenset(("IF", "IFERROR"))
SUPPORTED = frozenset(_FUNCS) | _LAZY
# Functions a document may use that only a real spreadsheet program can calculate. A workbook that went through
# the sandbox's /recalc carries their values; one that did not shows them when it is opened.
RECALC_ONLY = SAFE_FUNCTIONS - SUPPORTED
_AGGREGATES = frozenset(("SUM", "AVERAGE", "MIN", "MAX", "COUNT", "PRODUCT"))
# What IFERROR turns into its fallback: the error values a spreadsheet shows. Unknowable is re-raised first.
_CAUGHT = (FormulaError, ZeroDivisionError, ValueError, OverflowError)


def _tokenize(src: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
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
        elif m.group(4) is not None:
            tokens.append(("str", m.group(4).replace('""', '"')))
        elif m.group(5) and not m.group(5).isspace():
            word = m.group(5)
            tokens.append(("name", word.upper()) if word[0].isalpha() or word[0] == "_" else ("op", word))
    return tokens


def _arith(op: str, a, b):
    def run():
        x, y = _num(a()), _num(b())
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "^":
            return x ** y
        if y == 0:
            raise FormulaError("div0")
        return x / y
    return run


class _Parse:
    """Recursive descent over the tokens. Each method returns a function that yields the value."""

    def __init__(self, tokens: list[tuple[str, str]], cell: Callable[[int, int], object]) -> None:
        self.tokens, self.i, self.cell = tokens, 0, cell

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.i] if self.i < len(self.tokens) else ("end", "")

    def take(self) -> tuple[str, str]:
        if self.i >= len(self.tokens):
            raise Unknowable("syntax")
        self.i += 1
        return self.tokens[self.i - 1]

    def compare(self):
        left = self.expr()
        kind, text = self.peek()
        if kind == "op" and text in _COMPARISONS:
            self.take()
            right = self.expr()
            return lambda: _compare(text, left(), right())
        return left

    def expr(self):
        v = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            v = _arith(self.take()[1], v, self.term())
        return v

    def term(self):
        v = self.power()
        while self.peek() in (("op", "*"), ("op", "/")):
            v = _arith(self.take()[1], v, self.power())
        return v

    def power(self):
        v = self.unary()
        if self.peek() == ("op", "^"):
            self.take()
            v = _arith("^", v, self.unary())
        return v

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            inner = self.unary()
            return lambda: -_num(inner())
        if self.peek() == ("op", "+"):
            self.take()
        return self.atom()

    def reference(self, text: str):
        if ":" not in text:
            r, c = _ref(text)

            def one():
                x = self.cell(r, c)
                return BLANK if x is None else x
            one.single = True        # a lone reference: aggregates skip it when it holds text, as for a range
            return one
        (r1, c1), (r2, c2) = (_ref(p) for p in text.split(":"))
        top, bottom, left, right = min(r1, r2), max(r1, r2), min(c1, c2), max(c1, c2)
        if (bottom - top + 1) * (right - left + 1) > MAX_RANGE_CELLS:
            raise Unknowable("range")

        def many():
            cells = _Range(self.cell(r, c) for r in range(top, bottom + 1) for c in range(left, right + 1))
            cells.rows, cells.cols = bottom - top + 1, right - left + 1
            return cells
        return many

    def call(self, name: str):
        if self.take() != ("op", "("):
            raise Unknowable("call")
        args = []
        if self.peek() != ("op", ")"):
            args.append(self.compare())
            while self.peek() == ("op", ","):
                self.take()
                args.append(self.compare())
        if self.take() != ("op", ")") or (name not in _FUNCS and name not in _LAZY):
            raise Unknowable(name)
        if name == "IF":
            if not 2 <= len(args) <= 3:
                raise Unknowable(name)
            return lambda: args[1]() if _truth(args[0]()) else (args[2]() if len(args) > 2 else False)
        if name == "IFERROR":
            if len(args) != 2:
                raise Unknowable(name)

            def guarded():
                try:
                    return args[0]()
                except Unknowable:
                    raise
                except _CAUGHT:
                    return args[1]()
            return guarded

        def read(a):
            x = a()
            if name in _AGGREGATES and getattr(a, "single", False):
                return _Range([None if isinstance(x, Blank) else x])
            return x

        def run():
            try:
                return _FUNCS[name]([read(a) for a in args])
            except (ValueError, ZeroDivisionError, IndexError) as exc:
                raise FormulaError(name) from exc
        return run

    def atom(self):
        kind, text = self.take()
        if kind == "num":
            value = float(text)
            v = lambda: value                                                  # noqa: E731
        elif kind == "str":
            v = lambda: text                                                   # noqa: E731
        elif kind == "ref":
            v = self.reference(text)
        elif kind == "fn":
            v = self.call(text)
        elif kind == "name" and text in ("TRUE", "FALSE"):
            v = lambda: text == "TRUE"                                         # noqa: E731
        elif (kind, text) == ("op", "("):
            v = self.compare()
            if self.take() != ("op", ")"):
                raise Unknowable("paren")
        else:
            raise Unknowable("syntax")
        while self.peek() == ("op", "%"):
            self.take()
            v = (lambda inner: lambda: _num(inner()) / 100)(v)
        return v


def evaluate_any(formula: str, cell: Callable[[int, int], object], depth: int = 0):
    """Value of ``=...`` as a float, text or bool, using ``cell(row, col)`` for references (a number, text,
    or None when empty).

    Raises FormulaError for anything outside the subset, and for an error a spreadsheet would show (``div0``)."""
    if depth > 20:
        raise Unknowable("circular")
    parser = _Parse(_tokenize(formula.lstrip("=")), cell)
    try:
        run = parser.compare()
        if parser.i != len(parser.tokens):
            raise Unknowable("syntax")
        result = run()
        if isinstance(result, list):
            raise Unknowable("syntax")
        return result
    except (TypeError, RecursionError) as exc:
        raise Unknowable(str(exc)) from exc
    except (OverflowError, ValueError) as exc:
        raise FormulaError(str(exc)) from exc


def evaluate(formula: str, cell: Callable[[int, int], object], depth: int = 0) -> float:
    """Value of ``=...`` as a number. Raises FormulaError for anything outside the subset, and when the
    result is text."""
    result = evaluate_any(formula, cell, depth)
    if isinstance(result, str):
        raise FormulaError("text")
    return float(result)


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
