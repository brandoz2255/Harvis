"""Build-session method pack injection for screenshot → code turns."""

from __future__ import annotations

import os
import re

from .prompts import build_method_pack_prompt, default_stack

_TRUTHY = {"1", "true", "yes", "on"}

_SCREENSHOT_HINT = re.compile(
    r"\b(screenshot|mockup|figma|replicate\s+(this|the)\s+ui|ui\s+from\s+(this\s+)?image|"
    r"convert\s+(this\s+)?(image|screenshot)|screenshot\s*[- ]?to\s*[- ]?code|"
    r"build\s+(this|the)\s+(page|ui|layout)|html\s+from\s+(this\s+)?(image|screenshot))\b",
    re.I,
)


def vision_self_check_enabled() -> bool:
    return (os.getenv("HARVIS_VISION_SELF_CHECK_ENABLED") or "").strip().lower() in _TRUTHY


def looks_like_screenshot_task(brief: str, *, has_image: bool) -> bool:
    if not has_image:
        return False
    text = brief or ""
    if _SCREENSHOT_HINT.search(text):
        return True
    # Image-only / short brief: treat as screenshot-to-code by default in Build.
    stripped = text.strip()
    if len(stripped) < 40:
        return True
    return False


def detect_stack(brief: str) -> str:
    t = (brief or "").lower()
    if "bootstrap" in t:
        return "bootstrap"
    if "ionic" in t:
        return "ionic"
    if re.search(r"\bvue\b", t):
        return "vue"
    if re.search(r"\breact\b", t):
        return "react"
    if "plain html" in t or "html_css" in t or "no tailwind" in t:
        return "html_css"
    # Read at call time, not import time: the default follows
    # HARVIS_PREVIEW_ALLOW_CDN, and a module-level constant would freeze it.
    return default_stack()


def screenshot_to_code_brief_addon(brief: str, *, has_image: bool) -> str:
    """Return an additive brief block, or empty string when the pack should not apply."""
    if not looks_like_screenshot_task(brief, has_image=has_image):
        return ""
    stack = detect_stack(brief)
    pack = build_method_pack_prompt(stack, verify_enabled=vision_self_check_enabled())
    return (
        "\n\n[Screenshot-to-code method pack — follow these rules for this turn]\n"
        + pack
        + "\n[End method pack]\n"
    )
