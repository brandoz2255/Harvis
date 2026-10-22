"""Which fonts the document exporters can count on, asked of fontconfig once.

The backend image ships DejaVu Sans and little else, so two things have to be looked up rather
than assumed: a CJK font (without one, Chinese, Japanese and Korean text draws as boxes) and a
real italic face of the body font (``fonts-dejavu-core`` has none; ``fonts-dejavu-extra`` does).
Both answers are ``None``/``False`` when fontconfig is missing or says nothing, and every caller
has to work in that case.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from typing import Optional

BODY_FAMILY = "DejaVu Sans"
MONO_FAMILY = "DejaVu Sans Mono"

# Tried in this order; anything else that claims Chinese coverage is the last resort.
_CJK_PREFERRED = ("Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK", "Source Han Sans", "WenQuanYi Micro Hei",
                  "WenQuanYi Zen Hei", "Droid Sans Fallback", "AR PL")
_CJK_SKIP = re.compile(r"serif|mono|slab|\bhk\b", re.I)


def _fc(*args: str) -> str:
    try:
        done = subprocess.run(["fc-list" if args[0] == "list" else "fc-match", *args[1:]], capture_output=True,
                              text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


@lru_cache(maxsize=1)
def cjk_family() -> Optional[str]:
    """The name of an installed sans font that covers CJK text, or None."""
    families: list[str] = []
    for line in _fc("list", ":lang=zh-cn", "family").splitlines():
        for name in line.split(","):
            name = name.strip()
            if name and not _CJK_SKIP.search(name) and name not in families:
                families.append(name)
    for wanted in _CJK_PREFERRED:
        for name in families:
            if name.lower().startswith(wanted.lower()):
                return name
    return families[0] if families else None


def _has_italic_face(family: str) -> bool:
    for line in _fc("list", family, "family", "slant", "width").splitlines():
        head, _, rest = line.partition(":")
        slant, width = re.search(r"slant=(\d+)", rest), re.search(r"width=(\d+)", rest)
        if family in head.split(",") and slant and int(slant[1]) > 0 and (not width or int(width[1]) == 100):
            return True
    return False


@lru_cache(maxsize=1)
def has_real_italic() -> bool:
    """True when the body font has an italic or oblique face of its own.

    Without one, weasyprint writes the PDF with the upright face under an Oblique name: the text is labelled
    italic and drawn straight. ``fc-match`` cannot tell (fontconfig's synthetic rule reports the upright face as
    slanted), so the installed faces are listed instead."""
    return _has_italic_face(BODY_FAMILY)


@lru_cache(maxsize=1)
def has_real_mono_italic() -> bool:
    """The same question for the code font, which ``fonts-dejavu-core`` does give an Oblique face."""
    return _has_italic_face(MONO_FAMILY)


_GENERIC = {"sans-serif", "serif", "monospace"}


def font_stack(*families: str) -> str:
    """A CSS font-family list: the given families, with the CJK font (when one is installed) before the generic."""
    cjk = cjk_family()
    names = [f if f in _GENERIC else f'"{f}"' for f in families]
    if cjk:
        names.insert(len(names) - (1 if names and families[-1] in _GENERIC else 0), f'"{cjk}"')
    return ", ".join(names)
