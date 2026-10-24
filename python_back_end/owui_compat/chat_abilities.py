"""What this install can do, told to the chat model in one short note.

A plain chat turn gives the model no tools, and the house prompt says not to claim
anything it cannot see a tool for. The result was a model that honestly answered
"I can't make a PowerPoint" on an install that makes real .pptx files, because the
wording detector had missed the request. This note closes that gap: it lists the
features the operator enabled and says they count as available even though none of
them is a tool call the model can see.

The list is data. Each entry is an ``Ability`` with a cheap synchronous
``available()``; a feature that is off on this install is left out of the note, so
the model is never told about something it cannot deliver. Other modules add their
own entries with ``register`` (the schedule and memory features do) instead of
editing this file.

``inject_abilities`` is the one call chat_completion makes. PRODUCT_FACTS is left
alone on purpose: it is shared with the sub-agent runner, where real tools exist.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

from .doc_bridge import DOC_PROMPT_MARKER

logger = logging.getLogger(__name__)

# The note starts with this line. inject_abilities uses it to stay idempotent, and
# doc_guard uses it to cut the note back out when it re-asks with the document prompt.
NOTE_HEADING = "## What this Harvis install can do"


@dataclass(frozen=True)
class Ability:
    id: str
    summary: str
    example_phrase: str
    available: Callable[[], bool] = lambda: True


def _image_on() -> bool:
    try:
        from image.harvis_image import _image_gen_enabled

        return bool(_image_gen_enabled())
    except Exception:
        return False


def _connectors_on() -> bool:
    try:
        from .chat_tools import chat_connectors_enabled

        return bool(chat_connectors_enabled())
    except Exception:
        return False


_ABILITIES: list[Ability] = [
    Ability("docs", "real .pptx, .docx, .xlsx and PDF files",
            "make me a slide deck about volcanoes"),
    Ability("research", "cited deep research",
            "deep research on solar panel efficiency"),
    Ability("browse", "driving a website",
            "open instagram and scroll my feed"),
    Ability("agent", "sandboxed agent runs",
            "use the agent to install ripgrep"),
    Ability("image", "image generation",
            "generate an image of a fox in snow", _image_on),
    Ability("connectors", "reading connected services",
            "list my GitHub repos", _connectors_on),
]

_NOTE_MAX = 900  # it rides on every chat turn; small models run at num_ctx 8192
_cache: tuple[tuple[str, ...], str] | None = None


def register(entry: Ability) -> None:
    """Add an ability, or replace the one with the same id. Other modules call this
    at import time so this file never has to know about their features."""
    global _cache
    for i, existing in enumerate(_ABILITIES):
        if existing.id == entry.id:
            _ABILITIES[i] = entry
            break
    else:
        _ABILITIES.append(entry)
    _cache = None


def abilities() -> list[Ability]:
    return list(_ABILITIES)


def _is_on(entry: Ability) -> bool:
    try:
        return bool(entry.available())
    except Exception:
        return False


_HEAD = (
    NOTE_HEADING + "\n"
    "The operator enabled these. They are available even though they are not tool "
    "calls you can see:\n"
)
_TAIL = (
    "Never say you cannot make a file, and never offer only an outline or script "
    "instead. With no document-format instructions this turn, say you can and ask the "
    "user to resend as \"make me a <deck|document|spreadsheet|PDF> about ...\". Posters, flyers, logos and video are not supported here. If a "
    "feature needs a particular phrase, give that exact phrase; never call it impossible."
)


def render_note() -> str:
    """The note for the abilities that are on right now (about 600-900 characters).
    Cached per process, keyed on which entries are on so a flipped flag shows up."""
    global _cache
    on = [a for a in _ABILITIES if _is_on(a)]
    key = tuple(a.id for a in on)
    if _cache and _cache[0] == key:
        return _cache[1]
    note = _HEAD + "".join(f"- {a.summary}: \"{a.example_phrase}\"\n" for a in on) + _TAIL
    if len(note) > _NOTE_MAX:
        # Entries other modules registered pushed it past the budget: keep the phrase
        # for documents only, which is the one the tail line depends on.
        short = "".join(
            f"- {a.summary}" + (f": \"{a.example_phrase}\"" if a.id == "docs" else "") + "\n" for a in on
        )
        note = _HEAD + short + _TAIL
    if len(note) > _NOTE_MAX:
        logger.warning("chat_abilities: note is %d chars, over the %d budget", len(note), _NOTE_MAX)
    _cache = (key, note)
    return note


def abilities_enabled() -> bool:
    return os.getenv("HARVIS_CHAT_ABILITIES", "1").strip().lower() not in {"0", "false", "off"}


def strip_note(text: str) -> str:
    """``text`` without the note, for a caller that is about to add the document prompt."""
    start = text.find(NOTE_HEADING)
    if start < 0:
        return text
    end = text.find("\n## ", start + len(NOTE_HEADING))
    return text[:start].rstrip("\n") + (text[end:] if end >= 0 else "")


def inject_abilities(owui_body: dict) -> None:
    """Append the note to the turn's first system message, in place. Never raises.

    Skipped on a voice (``harvis_plain``) turn, on a turn that already carries the
    document prompt (it says the opposite of "resend as /deck"), and when the note is
    already there, which keeps it safe on the deep copy a grounded retry makes.
    """
    try:
        if not abilities_enabled() or owui_body.get("harvis_plain") is True:
            return
        messages = owui_body.get("messages")
        if not isinstance(messages, list) or not messages:
            return
        systems = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        if any(isinstance(m.get("content"), str) and DOC_PROMPT_MARKER in m["content"] for m in systems):
            return
        note = render_note()
        if not systems:
            messages.insert(0, {"role": "system", "content": note.strip()})
            return
        first = systems[0].get("content")
        if isinstance(first, str) and NOTE_HEADING not in first:
            systems[0]["content"] = first + "\n\n" + note
    except Exception:
        logger.warning("chat_abilities: could not inject the note", exc_info=True)
