"""The shared document palette and the status chips a table cell can be.

One palette for the pptx shapes, the SVG figures and the PDF so a deck and its
PDF read as the same design. Colors are bare hex (no leading ``#``).
"""
from __future__ import annotations

import re
from typing import Optional

INK = "10243B"
GROUND = "FFFFFF"
DARK = "0E1E33"
ACCENT = "14A098"
ACCENT2 = "2F6FDE"
MUTED = "5B6B7F"
CARD = "F2F5F9"
LINE = "D5DCE6"
SERIES = (ACCENT, ACCENT2, "F2A93B", "C8372D", "7A5AF8", "6B7686")

_TONES = {
    "done": "green", "complete": "green",
    "in progress": "blue", "doing": "blue",
    "not started": "gray", "todo": "gray", "to do": "gray",
    "blocked": "red", "at risk": "red", "critical": "red",
    "high": "red", "medium": "amber", "low": "gray",
}
TONE_COLORS = {"green": "1E8E5A", "blue": "2F6FDE", "gray": "6B7686",
               "red": "C8372D", "orange": "D9622B", "amber": "A86B00"}
TONE_TINTS = {"green": "E3F4EB", "blue": "E4EDFC", "gray": "EBEEF2",
              "red": "FBE7E5", "orange": "FCEBDF", "amber": "FBF0D9"}


def chip_tone(text: str) -> Optional[str]:
    """The chip tone of a whole table cell, or None when it is ordinary text."""
    key = re.sub(r"\s+", " ", (text or "").replace("*", "").replace("_", " ")).strip().lower()
    return _TONES.get(key)


def tone_color(tone: Optional[str], default: str = INK) -> str:
    return TONE_COLORS.get(tone or "", default)
