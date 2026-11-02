"""Per-notebook chat settings: persona, answer style and answer length.

The block rendered here is appended *after* the grounding rules in the system prompt, and
says so, so a persona can change how an answer sounds but never lets it leave the sources.
"""
import re
from typing import Dict, Literal, Optional, get_args

ChatStyle = Literal["default", "learning_guide", "analyst", "custom"]
ChatLength = Literal["shorter", "default", "longer"]
STYLES = get_args(ChatStyle)
LENGTHS = get_args(ChatLength)
MAX_PERSONA_CHARS = 2000
MAX_LANGUAGE_CHARS = 40

DEFAULT_NUM_PREDICT = 512
_NUM_PREDICT = {"shorter": 256, "default": DEFAULT_NUM_PREDICT, "longer": 1024}

_STYLE_TEXT = {
    "learning_guide": (
        "Act as a patient tutor. Use simple wording, explain terms the sources assume the reader knows, "
        "build up from basics, and finish with one short question that checks understanding."
    ),
    "analyst": (
        "Act as a careful analyst. Lead with the conclusion, then list the evidence from the sources, "
        "and say plainly where the sources are thin, conflicting or silent."
    ),
}
_LENGTH_TEXT = {
    "shorter": "Keep the answer short: two or three sentences unless the question needs a list.",
    "longer": "Give a thorough answer with the detail and structure the sources support.",
}

# Chat-template control tokens and role headers have no business in a persona.
_CONTROL = re.compile(r"<\|[^|>]{0,40}\|>|</?(?:system|assistant|user|think)>|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", re.I)


def default_config() -> Dict[str, Optional[str]]:
    return {"persona": None, "style": "default", "length": "default", "output_language": None}


def clean_persona(text: Optional[str]) -> str:
    """The persona with control tokens removed, whitespace trimmed and length capped."""
    return _CONTROL.sub("", text or "").strip()[:MAX_PERSONA_CHARS].strip()


def normalize_style(style: Optional[str]) -> str:
    return style if style in STYLES else "default"


def normalize_length(length: Optional[str]) -> str:
    return length if length in LENGTHS else "default"


def normalize_config(raw: Optional[Dict[str, object]]) -> Dict[str, Optional[str]]:
    """A config dict from a manager or caller, with anything invalid reset to its default."""
    raw = raw or {}
    out = default_config()
    out["persona"] = clean_persona(raw.get("persona")) or None  # type: ignore[arg-type]
    out["style"] = normalize_style(raw.get("style"))  # type: ignore[arg-type]
    out["length"] = normalize_length(raw.get("length"))  # type: ignore[arg-type]
    lang = raw.get("output_language")
    out["output_language"] = lang.strip() if isinstance(lang, str) and lang.strip() else None
    return out


def render_style_block(persona: Optional[str], style: Optional[str], length: Optional[str]) -> str:
    """Extra system text for the style, persona and length; '' when everything is default."""
    style, length = normalize_style(style), normalize_length(length)
    lines = []
    if style == "custom":
        text = clean_persona(persona)
        if text:
            lines.append(f"The notebook owner described how you should answer:\n\"\"\"\n{text}\n\"\"\"")
    elif style in _STYLE_TEXT:
        lines.append(_STYLE_TEXT[style])
    if length in _LENGTH_TEXT:
        lines.append(_LENGTH_TEXT[length])
    if not lines:
        return ""
    return (
        "Style preferences (they change tone and format only; rules 1-6 above always win, and you "
        "still answer only from the sources and cite them):\n" + "\n".join(lines)
    )


def length_num_predict(length: Optional[str]) -> Optional[int]:
    """Token cap for a non-default length; None means the generator's own default."""
    n = _NUM_PREDICT[normalize_length(length)]
    return None if n == DEFAULT_NUM_PREDICT else n
