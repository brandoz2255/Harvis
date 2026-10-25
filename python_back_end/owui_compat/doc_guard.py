"""A safety net for the turn where the document detector missed and the model refused.

The router prepares a document turn only when the wording detector recognises the
request. When it does not ("my teacher wants slides, can u help"), the model sees an
ordinary chat turn, and a small model answers "I can't create PowerPoint files" or
offers an outline. This module watches those turns after the fact. If the user's
words look like a file request and the answer is a refusal or an outline offer, it
asks the same lane again with the document prompt in place and appends the result
under the original answer, after a ``---`` line, before ``[DONE]``.

The user sees the refusal and then a real document. That is the price of a net that
needs no new detector rule; every firing is logged so each miss can become one.

Wrapped around the native, cloud and Hermes return paths in chat_completion, outside
the Sources and connector trailers. Turns that already carry the document prompt, and
turns whose words are not about a file, are returned untouched.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re

from fastapi.responses import JSONResponse, StreamingResponse

from .doc_bridge import DOC_PROMPT_MARKER, doc_system_prompt

logger = logging.getLogger(__name__)

_BUDGET_S = 75.0
_SCAN_CHARS = 4_000
_TRAILER_JOIN = "\n\n---\n\n"
_GROUP_PREFIX = "[Group chat:"

# Words that could be asking for a file. Deliberately loose: the answer still has to
# refuse or offer an outline before anything happens.
_FILE_RE = re.compile(
    r"\b(slides?|slide[\s-]*shows?|slideshows?|deck|presentation|powerpoint|power[\s-]*point|pptx?|"
    r"spreadsheet|excel|xlsx?|csv|pdf|docx|word|document|report)\b",
    re.I,
)
# ...and asking for one. The verb has to govern the file word, a few words apart:
# "summarize this document", "what does this word mean, can you help" and "write a
# python script to convert a csv" must not pass, so "can", "help", "get" and "do" are
# not asks on their own and a long gap between verb and noun does not count.
# A file word followed by one of these is a modifier ("a pdf reader", "presentation
# skills", "excel formulas"), not the thing being asked for.
_MODIFIED = (
    r"(?![\s-]+(?:readers?|viewers?|editors?|skills?|formulas?|functions?|tutorials?|courses?|classes|"
    r"software|apps?|programs?|librar(?:y|ies)|converters?|tools?|shortcuts?|anxiety|jokes?)\b)"
)
_NOUN = (
    r"(?:slides?|slide[\s-]*shows?|slideshows?|deck|presentation|powerpoint|power[\s-]*point|pptx?|"
    r"spreadsheet|excel|xlsx?|csv|pdf|docx|word|document|report)\b" + _MODIFIED
)
_STRONG_NOUN = (
    r"(?:slides?|slide[\s-]*shows?|slideshows?|deck|presentation|powerpoint|power[\s-]*point|pptx?|spreadsheet)\b"
    + _MODIFIED
)
_GAP = r"(?:\W+\w+){0,5}?\W+"
_ASK_RE = re.compile(
    r"\b(?:make|create|write|draft|generate|build|produce|prepare|compose|design|need|needs|want|wants|"
    r"wanna|get\s+me|give\s+me)\b" + _GAP + _NOUN
    # "turn this into slides", "convert it to a pdf", "export that as a spreadsheet"
    + r"|\b(?:turn|convert|export)\b" + _GAP + r"(?:into|to|as)\b" + _GAP.replace("{0,5}?", "{0,2}?") + _NOUN
    # "help me with my presentation"
    + r"|\bhelp(?:\s+me)?\s+(?:with|on)\b" + _GAP.replace("{0,5}?", "{0,2}?") + _NOUN
    # a message that opens with the thing itself: "slides on dogs", "a deck about space"
    + r"|^\W*(?:an?\s+|some\s+|the\s+)?" + _STRONG_NOUN
    # "slides pls"
    + r"|\b" + _STRONG_NOUN + _GAP.replace("{0,5}?", "{0,3}?") + r"(?:pls|plz|please)\b",
    re.I,
)

_FILE_WORDS = r"(?:file|slides?|deck|presentation|pptx|powerpoint|documents?|pdf|spreadsheet|docx|xlsx)"
# From the verb to the file word only a few plain words may pass, and none of them can
# be "of", "about" or "summary": "create a summary of the document" is not a refusal
# to make a document. The speaker is the assistant ("I", "this chat"), not a library.
_REFUSAL_RE = re.compile(
    r"\b(?:i|i'm|i am|we|this (?:chat|assistant|model|app)|harvis)\b[^.!?\n]{0,40}?"
    r"(?:cannot|can't|can not|unable to|don't have|do not have|no (?:visible )?tool)"
    # Stems, not words: "a tool for creating presentation files" must match too.
    # One clause: no sentence end and no "but" between the negation and the verb.
    r"(?:(?!\bbut\b)[^.!?\n]){0,80}?(?:creat\w*|generat\w*|mak(?:e|ing)|produc\w*|export\w*|build\w*)"
    r"(?:\W+(?!(?:of|about|summary|summaries|summar\w+|on|from|that|which|to|for)\b)\w+){0,4}?"
    rf"\W+{_FILE_WORDS}",
    re.I,
)
# Outlines meant for a presentation or document, not any "script" or "template".
_OFFER_NOUN = (
    r"(?:outline|slide[\s-]*by[\s-]*slide\s+(?:outline|breakdown|plan|version|structure|summary)|(?:speaker|presentation|slide|deck|talk)\s+(?:script|notes)|"
    r"(?:slide|deck|presentation|document|report)\s+(?:template|structure)|text (?:version|format))"
)
_OFFER_RE = re.compile(
    rf"(?:here(?:'s| is| are)|i can (?:give|provide|offer|write|draft|share)|i(?:'ll| will) "
    rf"(?:give|provide|offer|write|draft|share)|instead,? (?:i can|here))\b.{{0,60}}\b{_OFFER_NOUN}"
    # Pasting is only an offer when an outline or slides are what gets pasted.
    rf"|\b{_OFFER_NOUN}\b.{{0,80}}\b(?:copy|paste)\b.{{0,60}}\b(?:into|to|in)\s+(?:powerpoint|google\s+slides|"
    r"keynote|word|excel|google\s+docs|canva)\b"
    r"|\b(?:copy|paste)\b.{0,60}\b(?:into|to|in)\s+(?:powerpoint|google\s+slides|keynote|canva)\b",
    re.I,
)
# A fence tagged with a programming language: the answer is code, not an outline.
_CODE_FENCE_RE = re.compile(
    r"^ {0,3}(?:`{3,}|~{3,})\s*(?!harvis-doc|text|markdown|md|plain|txt)[a-z][\w+#-]*",
    re.I | re.M,
)

_KIND_WORDS = (
    ("deck", re.compile(r"\b(slides?|slide[\s-]*shows?|slideshows?|deck|presentation|power[\s-]*point|pptx?)\b", re.I)),
    ("sheet", re.compile(r"\b(spreadsheet|excel|xlsx?|csv)\b", re.I)),
    ("pdf", re.compile(r"\bpdf\b", re.I)),
    ("doc", re.compile(r"\b(docx|word|document|report)\b", re.I)),
)


def guard_enabled() -> bool:
    return os.getenv("HARVIS_DOC_GUARD", "1").strip().lower() not in {"0", "false", "off"}


def looks_like_file_request(user_text: str) -> bool:
    return bool(user_text and _FILE_RE.search(user_text) and _ASK_RE.search(user_text))


# A conversion is named by its target: "convert a word doc to pdf" is a PDF, not a document.
_CONVERT_VERB_RE = re.compile(r"\b(?:convert|converting|turn|turning|export|exporting|transform|save|saving|change)\b", re.I)
_TARGET_RE = re.compile(r"\b(?:to|into|as)\b", re.I)
# A file word that a topic marker directly follows ("slides on how to turn a report into a pdf", "report
# on how we can turn ...") is the thing being asked for; the conversion is only its subject. The marker
# must sit right after the file word (one qualifier allowed: "word doc on"), not anywhere before the verb.
_TOPIC_GAP_RE = re.compile(
    r"^[\w-]+(?:\s+[\w-]+)?\s+(?:on|about|covering|regarding|explaining|how|why|what)\b", re.I)
# "convert it", "turn this": the object points back at an earlier file, so the conversion target wins.
_PRONOUN_OBJECT_RE = re.compile(r"\s+(?:it|this|that|them|these|those)\b", re.I)


def _first_kind(text: str) -> tuple[str, int] | None:
    """The kind whose file word comes first in ``text`` and where it starts, or None."""
    best: tuple[str, int] | None = None
    for kind, pattern in _KIND_WORDS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[1]):
            best = (kind, m.start())
    return best


def kind_from_text(user_text: str) -> str:
    """The document kind to make for the user's message; ``doc`` if none.

    Normally the file word that comes first. With a conversion verb, the file word after
    "to", "into" or "as" wins, because that is what the user wants out of it, unless a file
    word comes first with a topic word ("on", "about", "how") right after it and the verb's object
    is not a pronoun ("convert it").
    """
    verb = _CONVERT_VERB_RE.search(user_text)
    first = _first_kind(user_text)
    if (verb and first and first[1] < verb.start() and _TOPIC_GAP_RE.match(user_text[first[1]:verb.start()])
            and not _PRONOUN_OBJECT_RE.match(user_text, verb.end())):
        verb = None
    if verb:
        for target in _TARGET_RE.finditer(user_text, verb.end()):
            found = _first_kind(user_text[target.end():])
            if found:
                return found[0]
    found = _first_kind(user_text)
    return found[0] if found else "doc"


def fire_reason(answer: str) -> str | None:
    """``refusal`` or ``offer`` when the answer should be re-asked with the document prompt, else None.

    An answer with a fenced block in a programming language is a how-to or a script, so an outline
    offer inside it does not count, and neither does a refusal that comes after the code ("run this,
    I can't run commands here"). A refusal that leads, with the script as its consolation ("I can't
    create PDF files, but here's a script"), still counts: the user asked for a file and got none.
    """
    if not answer or "harvis-doc" in answer.lower():
        return None
    fence = _CODE_FENCE_RE.search(answer)
    before = answer[:fence.start()] if fence else answer
    if _REFUSAL_RE.search(re.sub(r"\s+", " ", before.replace("’", "'"))):
        return "refusal"
    if fence:
        return None
    return "offer" if _OFFER_RE.search(re.sub(r"\s+", " ", answer.replace("’", "'"))) else None


def should_fire(answer: str) -> bool:
    """A refusal to make a file, or an outline offered in its place with no real document."""
    return fire_reason(answer) is not None


def _has_doc_prompt(messages: list) -> bool:
    return any(
        isinstance(m, dict) and m.get("role") == "system"
        and isinstance(m.get("content"), str) and DOC_PROMPT_MARKER in m["content"]
        for m in messages
    )


def _last_user_index(messages: list) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], dict) and messages[i].get("role") == "user":
            return i
    return -1


def _user_text(messages: list) -> str:
    i = _last_user_index(messages)
    if i < 0:
        return ""
    content = messages[i].get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def doc_turn_body(owui_body: dict, kind: str) -> dict | None:
    """A copy of the turn rewritten as a document turn, or None with no user message.

    The block vocabulary and the abilities note are cut out of the system message
    (the first says colon fences are fine, the second says to ask the user to resend),
    and the document prompt goes right before the question, where the router puts it.
    """
    from .chat_abilities import strip_note
    from .chat_completion import BLOCK_VOCABULARY

    body = copy.deepcopy(owui_body)
    messages = body.get("messages")
    idx = _last_user_index(messages) if isinstance(messages, list) else -1
    if idx < 0:
        return None
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system" and isinstance(m.get("content"), str):
            m["content"] = strip_note(m["content"].replace(BLOCK_VOCABULARY, ""))
    messages.insert(idx, {"role": "system", "content": doc_system_prompt(kind)})
    body["stream"] = False
    return body


def _answer_text(response) -> str:
    data = response
    if not isinstance(data, dict):
        raw = getattr(response, "body", None)
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except Exception:
            return ""
    choices = (data or {}).get("choices") or []
    text = ((choices[0].get("message") or {}).get("content")) if choices else None
    return text if isinstance(text, str) else ""


_FENCE_LINE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(.*)$")


def open_fence_closer(answer: str) -> str:
    """The line that closes a code fence the answer left open, or "".

    The Hermes transcript reads fences line by line, so a refusal that ends inside an
    unclosed fence would swallow the document after it as more code.
    """
    open_fence = None
    for line in answer.split("\n"):
        m = _FENCE_LINE_RE.match(line)
        if not m:
            continue
        run = m.group(1)
        if open_fence is None:
            open_fence = run
        elif run[0] == open_fence[0] and len(run) >= len(open_fence) and not m.group(2).strip():
            open_fence = None
    return open_fence or ""


async def _trailer(owui_body: dict, lane, user_text: str, answer: str, complete: bool = True) -> str:
    """The text to append, or "" when this answer is fine or the second try failed.

    ``complete`` is False when ``answer`` is only the start of a longer reply, in which
    case nothing can be said about fences left open at its end."""
    reason = fire_reason(answer)
    if not reason:
        return ""
    kind = kind_from_text(user_text)
    # The user's words stay out of the logs: kind, reason and length are enough to find a miss.
    logger.info("doc_guard fired (kind=%s, reason=%s, message_chars=%d)", kind, reason, len(user_text))
    body = doc_turn_body(owui_body, kind)
    if body is None:
        return ""
    try:
        text = _answer_text(await asyncio.wait_for(lane(body), timeout=_BUDGET_S)).strip()
    except asyncio.TimeoutError:
        logger.warning("doc_guard: the document retry took longer than %ds", int(_BUDGET_S))
        return ""
    except Exception:
        logger.warning("doc_guard: the document retry failed", exc_info=True)
        return ""
    if not text:
        return ""
    if "harvis-doc" not in text.lower():
        logger.info("doc_guard: the retry answer carries no harvis-doc block")
    closer = open_fence_closer(answer) if complete else ""
    return (("\n" + closer) if closer else "") + _TRAILER_JOIN + text


def _sse_chunk(text: str) -> bytes:
    payload = {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class _Collector:
    """The first few thousand characters of ``delta.content`` from an SSE byte stream.

    Buffers across chunk boundaries (a frame can be split mid-line) and stops
    collecting once it has enough, so a long answer is not held in memory.
    """

    def __init__(self) -> None:
        self._buf = b""
        self._parts: list[str] = []
        self._len = 0

    def feed(self, chunk: bytes) -> None:
        if self._len >= _SCAN_CHARS:
            self._buf = b""
            return
        self._buf += chunk
        while b"\n" in self._buf:
            line, _, self._buf = self._buf.partition(b"\n")
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == b"[DONE]":
                continue
            try:
                data = json.loads(payload)
            except Exception:
                continue
            for choice in data.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if isinstance(piece, str) and piece:
                    self._parts.append(piece)
                    self._len += len(piece)

    def text(self) -> str:
        return "".join(self._parts)[:_SCAN_CHARS]

    @property
    def complete(self) -> bool:
        """The whole reply fit inside the window, so the text is not a cut-off prefix."""
        return self._len < _SCAN_CHARS


async def _stream_with_trailer(body_iterator, owui_body: dict, lane, user_text: str):
    """Pass the SSE through and, on a refusal, splice the document in before [DONE].

    The trailer has to precede [DONE] because every client stops reading there. If
    [DONE] never arrives (upstream error, client disconnect) nothing is added: the
    retry is worth losing, and awaiting inside a closing generator raises.
    """
    seen = _Collector()
    sent = False
    async for chunk in body_iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        seen.feed(chunk)
        if not sent and b"data: [DONE]" in chunk:
            head, _, tail = chunk.partition(b"data: [DONE]")
            if head:
                yield head
            sent = True
            trailer = await _trailer(owui_body, lane, user_text, seen.text(), seen.complete)
            if trailer:
                yield _sse_chunk(trailer)
            yield b"data: [DONE]" + tail
            continue
        yield chunk


def _append(data: dict, trailer: str):
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    msg["content"] = (msg.get("content") or "") + trailer
    choices[0]["message"] = msg
    return data


async def _guard_json(response, owui_body: dict, lane, user_text: str):
    if isinstance(response, dict):
        trailer = await _trailer(owui_body, lane, user_text, _answer_text(response))
        return (_append(response, trailer) or response) if trailer else response
    raw = getattr(response, "body", None)
    if not raw:
        return response
    data = json.loads(raw)
    trailer = await _trailer(owui_body, lane, user_text, _answer_text(data))
    data = _append(data, trailer) if trailer else None
    return JSONResponse(content=data, status_code=response.status_code) if data else response


async def append_doc_guard(request, response, owui_body: dict, lane, user_text: str | None = None):
    """Wrap one lane's reply so a refusal to make a file is followed by the real thing.

    ``lane`` is the coroutine function that answers a body on this lane (the same
    closure a grounded retry uses). ``user_text`` is the user's own words before any
    injection; without it the last user message is read, which may carry attachments
    and web results. Never raises; anything unexpected returns the reply untouched.
    """
    try:
        messages = owui_body.get("messages") if isinstance(owui_body, dict) else None
        if not guard_enabled() or not isinstance(messages, list) or _has_doc_prompt(messages):
            return response
        text = user_text if isinstance(user_text, str) and user_text.strip() else _user_text(messages)
        # doc_bridge leaves group-room turns alone; so does the net.
        if text.lstrip().startswith(_GROUP_PREFIX) or _user_text(messages).lstrip().startswith(_GROUP_PREFIX):
            return response
        if not looks_like_file_request(text):
            return response
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return await _guard_json(response, owui_body, lane, text)
        return StreamingResponse(
            _stream_with_trailer(body_iterator, owui_body, lane, text),
            status_code=response.status_code,
            media_type=response.media_type or "text/event-stream",
            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
        )
    except Exception:
        logger.warning("doc_guard: could not wrap the reply", exc_info=True)
        return response
