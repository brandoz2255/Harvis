"""Plain, actionable sentences for a failed turn.

The raw cause (an HTTP body, a dict repr, a traceback) belongs in the log; the
person reading the chat needs to know what to do next.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

_BY_STATUS = {
    400: "The model could not handle that request. Try rewording it, or pick a different model.",
    401: "Your Harvis session expired. Sign in again, then retry.",
    403: "You do not have access to that model. Pick a different one, or ask the admin.",
    404: "That model is not available right now. Pick a different one from the model menu.",
    408: "The model took too long to respond. Retry in a moment.",
    413: "That message or its attachments are too large for this model. Shorten it and retry.",
    429: "The model is busy or you hit a usage limit. Wait a moment, then retry.",
}
_SERVER_DOWN = "The model server is not responding. Check that it is running, then retry."
_FALLBACK = "Something went wrong while answering. Retry, and check the Harvis logs if it keeps happening."


def detail_text(raw: Any) -> str:
    """The human sentence inside an error body: {"detail": ...}, {"error": {"message": ...}}, a dict repr."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] in "{[":
            try:
                raw = json.loads(text)
            except ValueError:
                return " ".join(text.split())
        else:
            return " ".join(text.split())
    if isinstance(raw, dict):
        for key in ("detail", "message", "error", "reason"):
            if key in raw and raw[key]:
                return detail_text(raw[key])
        return ""
    if isinstance(raw, list):
        return "; ".join(t for t in (detail_text(x) for x in raw) if t)
    return "" if raw is None else str(raw)


class TurnError(RuntimeError):
    """A failure that already carries the sentence to show; ``raw`` is for the log."""

    def __init__(self, message: str, raw: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.raw = raw or message
        self.status = status


def from_http(status: int, body: Any) -> TurnError:
    detail = detail_text(body)
    sentence = _BY_STATUS.get(status)
    if sentence is None:
        sentence = _SERVER_DOWN if status >= 500 else _FALLBACK
    # A 4xx body often names the real reason in a short sentence ("model 'x' not found").
    if status in (400, 404) and detail and len(detail) <= 160 and "{" not in detail and "Traceback" not in detail:
        sentence = f"{sentence} ({detail.rstrip('.')})"
    return TurnError(sentence, raw=f"HTTP {status}: {str(body)[:400]}", status=status)


def friendly(exc: BaseException) -> str:
    """The sentence for any exception a turn can raise."""
    if isinstance(exc, TurnError):
        return str(exc)
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return _SERVER_DOWN
    if isinstance(exc, httpx.TimeoutException):
        return _BY_STATUS[408]
    if isinstance(exc, httpx.RemoteProtocolError):
        return "The connection to the model dropped mid-answer. Retry."
    if isinstance(exc, httpx.HTTPStatusError):
        return from_http(exc.response.status_code, "").args[0]
    first = exc.args[0] if exc.args else None
    text = detail_text(first if isinstance(first, (dict, list)) else str(exc))
    # A message we raised ourselves (admission limits, "mixture of agents preset ...") is already a sentence;
    # anything that still looks like a payload or a Python repr is not.
    if text and len(text) <= 240 and not any(t in text for t in ("{'", '{"', "Traceback", "<class", "HTTP ")):
        return text if text.endswith((".", "!", "?", ")")) else text + "."
    return _FALLBACK
