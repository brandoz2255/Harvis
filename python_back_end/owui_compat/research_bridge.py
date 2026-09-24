"""Start a deep-research run when a chat message asks for one.

The main UI starts research from a toggle beside Send. Here the message itself
is the trigger: "deep research X", "/research X", "research X in depth",
"write a research report on X". The turn launches the same background job as
``POST /api/research/start`` and answers with the ``research_run`` marker the
OWUI ResearchRunCard renders (the Hermes facade follows it into the chat).

A second run in the same conversation builds on the first: when an earlier
assistant message names a research id (the marker, or the report link) and the
new request continues it, the saved report, findings and source URLs are handed
to the researcher as ``prior_*`` so it extends what it already found instead of
starting over.
"""
from __future__ import annotations

import html
import logging
import re
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from .workspace_bridge import _last_user_message, _messages_to_history, _openai_sse_lines

logger = logging.getLogger(__name__)

# Explicit asks only; "research" alone in a sentence is ordinary chat.
_TRIGGERS = (
    re.compile(r"^\s*/(?:deep-?)?research\b[:\s]*(?P<q>.*)$", re.I | re.S),
    re.compile(
        r"^\s*(?:(?:please|can you|could you|pls)\s+)?(?:do|run|start|kick off|perform)?\s*(?:a|an|some)?\s*"
        r"deep[\s-]?(?:research|dive)\s*(?:on|into|about|for|of|:)?\s*(?P<q>.*)$",
        re.I | re.S,
    ),
    re.compile(r"\bdeep[\s-]?research\b", re.I),
    re.compile(r"\b(?:write|make|create|generate)\s+(?:me\s+)?(?:a\s+)?(?:full\s+)?research\s+report\b", re.I),
    re.compile(r"\bresearch\b.{3,200}\b(?:in[\s-]depth|thoroughly|in detail|exhaustively)\b", re.I | re.S),
)

# "What is deep research?" asks about the feature; it isn't a request to run it.
_ABOUT_FEATURE = re.compile(r"^\s*(?:what|how|why|does|is|are|when)\b[^?]*\bdeep[\s-]?research\b[^?]*\?\s*$", re.I)
_RESEARCH_ID = re.compile(r"\brp-[0-9a-f]{12}\b")
_CONTINUE = re.compile(
    r"\b(?:more|deeper|further|follow[\s-]?up|continue|expand|extend|build on|dig|also|update|again)\b", re.I
)
_WORD = re.compile(r"[a-z0-9]{4,}")
_SKIP_MODELS = {"", "auto", "default", "user-pref", "dynamic", "harvis-workspace"}
_CLOUD_PREFIXES = ("anthropic/", "openai/", "moonshot/", "google/", "gemini/", "openrouter/")


def research_query(message: str) -> Optional[str]:
    """The topic to research, or None when the message isn't a research ask."""
    text = (message or "").strip()
    if not text or _ABOUT_FEATURE.match(text):
        return None
    for pattern in _TRIGGERS:
        m = pattern.search(text)
        if not m:
            continue
        q = (m.groupdict().get("q") or "").strip(" .:\n")
        if not q and text.startswith("/"):
            return None
        # A trigger with nothing after it ("deep research this") means the whole message.
        return q if len(q) >= 8 else text
    return None


def prior_research_id(history: list[dict]) -> Optional[str]:
    """The newest research id an earlier assistant turn mentioned."""
    for m in reversed(history[:-1]):
        if m.get("role") != "assistant":
            continue
        found = _RESEARCH_ID.findall(m.get("content") or "")
        if found:
            return found[-1]
    return None


def continues(query: str, prior_query: str) -> bool:
    """A follow-up asks for more, or is about the same thing."""
    if _CONTINUE.search(query):
        return True
    a, b = set(_WORD.findall(query.lower())), set(_WORD.findall(prior_query.lower()))
    return bool(a and b) and len(a & b) / len(a | b) >= 0.3


def _prior_context(handler, research_id: str, owner: str, query: str) -> dict:
    data = handler._get_session_json(research_id) or {}
    if data.get("owner") != owner or data.get("status") not in (None, "done"):
        return {}
    if not continues(query, str(data.get("query") or "")):
        return {}
    urls = {s.get("url") for s in data.get("sources") or [] if isinstance(s, dict) and s.get("url")}
    return {
        "prior_report": str(data.get("raw_report") or data.get("result") or ""),
        "prior_findings": list(data.get("raw_findings") or []),
        "prior_urls": urls,
    }


def _marker(research_id: str, query: str, prior: Optional[str]) -> str:
    attrs = f'researchid="{research_id}" query="{html.escape(query[:300], quote=True)}"'
    if prior:
        attrs += f' priorid="{prior}"'
    return f'<details type="research_run" {attrs}>\n<summary>Deep Research…</summary>\n</details>'


async def maybe_handle_research(request: Request, owui_body: dict, user) -> Optional[StreamingResponse]:
    """Launch a research run for an explicit ask; None falls through to normal chat."""
    mode = str(owui_body.get("harvis_mode") or "auto").strip().lower()
    if mode in ("agent", "orchestrate"):
        return None
    # An explicit False (a Hermes bot with web research switched off) keeps the
    # detector out of the turn entirely; absent/None still means "detect".
    if owui_body.get("harvis_research") is False:
        return None
    history = _messages_to_history(owui_body)
    query = research_query(_last_user_message(history))
    if owui_body.get("harvis_research") and not query:
        query = _last_user_message(history).strip() or None
    if not query:
        return None
    try:
        from deep_research.router import _handler, _resolve_research_model

        owner = str(getattr(user, "id", "") or "")
        model = str(owui_body.get("model") or "").strip()
        if model.lower() in _SKIP_MODELS or model.startswith(_CLOUD_PREFIXES):
            model = await _resolve_research_model(request, getattr(user, "id", None))
        prior_id = prior_research_id(history)
        prior = _prior_context(_handler, prior_id, owner, query) if prior_id else {}
        research_id = f"rp-{uuid.uuid4().hex[:12]}"
        _handler.start_research(
            session_id=research_id, query=query, llm_model=model, max_rounds=20, owner=owner, **prior
        )
    except Exception:
        logger.exception("owui research_bridge: could not start research")
        return None
    logger.info("owui research_bridge: started %s (prior=%s)", research_id, prior_id if prior else None)
    lines = _openai_sse_lines(research_id, _marker(research_id, query, prior_id if prior else None))

    async def _gen():
        for ln in lines:
            yield ln

    return StreamingResponse(
        _gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
