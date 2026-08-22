"""Can the selected model actually see an image?

Screenshot-to-code is worthless on a text-only model: it produces a confident
page built from the *filename*. So when a turn carries images, we check the model
first and refuse with an actionable message rather than hallucinating a UI.

The check is deliberately asymmetric. We block ONLY on positive evidence that a
model cannot see — an installed Ollama tag whose /api/show capabilities list
omits "vision". Everything else (an unreachable model server, a cloud model whose
catalog declares nothing, a name we don't recognize) is allowed through with a
warning, because guessing "no vision" from silence would break working setups.

Cloud catalogs in this repo do not carry a vision flag (see the `capabilities`
gap tracked for the free-provider work), so the cloud side is a curated name
table plus that permissive default.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Cloud/hosted families known to accept images. Matched as substrings against a
# lowercased model id, so "openai/gpt-4o-mini" and "gpt-4o" both hit.
_KNOWN_VISION = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision", "gpt-5", "o3", "o4-mini",
    "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",
    "gemini", "kimi-k2.5", "kimi-latest", "moonshot-v1-vision",
    "llava", "bakllava", "moondream", "minicpm-v", "internvl", "pixtral",
    "-vl", "vision", "grok-2-vision", "grok-4", "mistral-small-3",
    "llama-3.2-11b", "llama-3.2-90b", "llama-4",
)

# Families we are confident are text-only. Kept short on purpose: a wrong entry
# here blocks a turn that would have worked.
_KNOWN_TEXT_ONLY = (
    "qwen2.5-coder", "qwen3-coder", "deepseek-coder", "codellama",
    "starcoder", "codegemma", "text-embedding",
)


def _name_verdict(model: str) -> Optional[bool]:
    low = model.lower()
    if any(tok in low for tok in _KNOWN_VISION):
        return True
    if any(tok in low for tok in _KNOWN_TEXT_ONLY):
        return False
    return None


def _ollama_verdict(model: str) -> Optional[bool]:
    """True/False from Ollama's own capability report; None when we can't ask.

    model_capabilities() returns [] both for "unreachable" and "unknown tag", so
    an empty list is treated as no-answer. A reachable Ollama always reports at
    least ["completion"] for a tag it has.
    """
    try:
        from vison_models.llm_connector import list_ollama_models, model_capabilities
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("vision gate: llm_connector unavailable: %s", exc)
        return None

    try:
        installed = list_ollama_models()
    except Exception as exc:
        logger.warning("vision gate: could not list Ollama models: %s", exc)
        return None
    if model not in (installed or []):
        return None

    caps = model_capabilities(model) or []
    if not caps:
        return None
    return "vision" in caps


async def model_can_see(model_name: str) -> tuple[Optional[bool], str]:
    """(verdict, reason). True = has vision, False = proven text-only, None = unknown."""
    model = (model_name or "").strip()
    if not model:
        return None, "no model name was given"

    verdict = await asyncio.to_thread(_ollama_verdict, model)
    if verdict is True:
        return True, f"{model} reports vision support"
    if verdict is False:
        return False, f"{model} is installed locally and does not report vision support"

    named = _name_verdict(model)
    if named is True:
        return True, f"{model} is a known vision-capable model"
    if named is False:
        return False, f"{model} is a code/text-only model family"
    return None, f"nothing is known about whether {model} accepts images"


def _vision_and_tools() -> list[str]:
    """Installed tags that can BOTH see an image and call a tool.

    Vision alone is not enough for a Build turn: the runner always offers a tool
    schema, and Ollama rejects that outright for a model without tool support
    ("gemma3:12b does not support tools", HTTP 400). Recommending a vision-only
    tag would send the user from one dead end to another.
    """
    try:
        from vison_models.llm_connector import list_ollama_models, model_capabilities
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("vision gate: llm_connector unavailable: %s", exc)
        return []
    out: list[str] = []
    for tag in list_ollama_models() or []:
        caps = model_capabilities(tag) or []
        if "vision" in caps and "tools" in caps:
            out.append(tag)
    return out


async def suggest_vision_models(limit: int = 4) -> list[str]:
    """Installed models that can actually run a Build turn on a screenshot."""
    try:
        found = await asyncio.to_thread(_vision_and_tools)
    except Exception as exc:
        logger.debug("vision gate: could not list vision models: %s", exc)
        return []
    return list(found)[:limit]


def _plural(items: list[str]) -> str:
    return ", ".join(items)


async def build_refusal(model_name: str, reason: str, image_count: int) -> dict:
    """The payload for the error event when images meet a blind model."""
    installed = await suggest_vision_models()
    if installed:
        fix = (
            "Pick a vision-capable model in the composer — "
            f"{_plural(installed)} {'is' if len(installed) == 1 else 'are'} "
            "already installed. "
        )
    else:
        fix = (
            "No installed model can both see an image and call tools. Pull one "
            "(`ollama pull gemma4:e4b`), or connect a cloud model that accepts "
            "images (Claude, GPT-4o, Gemini, Kimi K2.5) in Settings → API Keys. "
        )
    noun = "the attached image" if image_count == 1 else f"the {image_count} attached images"
    return {
        "message": (
            f"{model_name or 'The selected model'} cannot see {noun}, so this "
            f"turn would be answered from the file name alone."
        ),
        "fix_hint": fix + f"Reason: {reason}.",
    }


_SAFE_TAG = re.compile(r"^[A-Za-z0-9._:/-]+$")


def looks_like_model_tag(value: str) -> bool:
    """Guard for anything we interpolate into a user-facing hint."""
    return bool(value) and bool(_SAFE_TAG.match(value))
