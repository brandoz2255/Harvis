"""Every native chat turn ends with an answer, never a blank bubble.

Thinking models (Nemotron, qwen3.x) sometimes spend the whole reply on reasoning and
stream no content at all; the reader saw nothing, or only the Sources list that
chat_reach appends. Measured on the PAIR router (2026-11-07): ``reasoning_effort:
"none"`` is the one switch it honours (14 tokens straight to the answer, against
~240 with thinking); ``think: false`` and ``chat_template_kwargs`` are ignored.

So: pass the stream through untouched, and if it ends with no content and no
upstream error, ask once more with thinking off and stream that answer in the same
reply. If that is empty too, say so in a plain sentence.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

NO_ANSWER = ("The model gave no answer this time (it spent its whole reply thinking). "
             "Retry, lower the thinking level, or pick another model.")

Retry = Callable[[dict], Awaitable[Any]]


class _Watch:
    """Reads an OpenAI SSE stream: did it carry content, reasoning, tool calls or an error?"""

    def __init__(self) -> None:
        self._buf = b""
        self.content = False
        self.reasoning = False
        self.error = False

    def feed(self, chunk: bytes) -> None:
        if self.content:
            return
        self._buf += chunk
        while b"\n" in self._buf:
            line, _, self._buf = self._buf.partition(b"\n")
            self._line(line.strip())

    def _line(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            return
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        if data.get("error"):
            self.error = True
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if str(delta.get("content") or "").strip() or delta.get("tool_calls"):
                self.content = True
            if delta.get("reasoning") or delta.get("reasoning_content"):
                self.reasoning = True


def _chunk(text: str) -> bytes:
    payload = {"object": "chat.completion.chunk",
               "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
    return f"data: {json.dumps(payload)}\n\n".encode()


def _dict_answer(data: Any) -> str:
    try:
        return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    except Exception:  # noqa: BLE001
        return ""


def _dict_reasoned(data: Any) -> bool:
    try:
        m = (data.get("choices") or [{}])[0].get("message") or {}
        return bool(m.get("reasoning") or m.get("reasoning_content"))
    except Exception:  # noqa: BLE001
        return False


def _no_think(reasoned: bool) -> dict:
    # Only a model that reasoned gets the effort flag: Ollama 400s it on any other model.
    return {"reasoning_effort": "none"} if reasoned else {}


async def _retry_stream(retry: Retry, extra: dict):
    """The retry's content as SSE chunks (its [DONE] dropped); yields (chunk, had_content)."""
    resp = await retry(extra)
    it = getattr(resp, "body_iterator", None)
    if it is None:
        text = _dict_answer(resp) if isinstance(resp, dict) else ""
        if text.strip():
            yield _chunk(text), True
        return
    watch = _Watch()
    async for c in it:
        if isinstance(c, str):
            c = c.encode()
        watch.feed(c)
        head, sep, _tail = c.partition(b"data: [DONE]")
        if head:
            yield head, watch.content
        if sep:
            break


async def _guarded(body_iterator, retry: Retry):
    watch = _Watch()
    done_tail = None
    async for chunk in body_iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode()
        watch.feed(chunk)
        if b"data: [DONE]" in chunk:
            head, _, tail = chunk.partition(b"data: [DONE]")
            if head:
                yield head
            done_tail = tail
            break
        yield chunk
    if not watch.content and not watch.error:
        logger.info("answer_guard: empty answer (reasoning=%s); retrying with thinking off", watch.reasoning)
        got = False
        try:
            async for c, had in _retry_stream(retry, _no_think(watch.reasoning)):
                got = got or had
                yield c
        except Exception as exc:  # noqa: BLE001 — the sentence below still answers
            logger.warning("answer_guard: retry failed: %s", exc.__class__.__name__)
        if not got:
            yield _chunk(NO_ANSWER)
    yield b"data: [DONE]" + (done_tail or b"\n\n")


async def ensure_answer(response: Any, retry: Retry) -> Any:
    """``response`` from the native lane, guarded. ``retry(extra)`` re-runs the same turn
    with ``extra`` merged into the request body. Never raises."""
    try:
        it = getattr(response, "body_iterator", None)
        if it is not None:
            return StreamingResponse(
                _guarded(it, retry), status_code=response.status_code,
                media_type=response.media_type or "text/event-stream",
                headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
            )
        if isinstance(response, dict) and response.get("choices") and not _dict_answer(response).strip() \
                and not (response["choices"][0].get("message") or {}).get("tool_calls"):
            logger.info("answer_guard: empty non-streamed answer; retrying with thinking off")
            again = await retry(_no_think(_dict_reasoned(response)))
            if isinstance(again, dict) and _dict_answer(again).strip():
                return again
            msg = response["choices"][0].setdefault("message", {"role": "assistant"})
            msg["content"] = NO_ANSWER
        return response
    except Exception:  # noqa: BLE001
        logger.warning("answer_guard: skipped", exc_info=True)
        return response
