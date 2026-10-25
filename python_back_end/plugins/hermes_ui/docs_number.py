"""A spreadsheet cell typed as text: is it a number, and in what Excel number format."""
from __future__ import annotations

import re
from typing import Optional

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
