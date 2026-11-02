"""Streaming notebook answers over Server-Sent Events.

Retrieval, history, chat settings, the grounding floor and the prompt are exactly the ones the
non-streaming chat uses (``RAGChatService``); only generation differs: it posts to Ollama's
``/api/chat`` with ``stream: true`` and forwards each token as it arrives.

Events (``event: <name>`` plus a ``data:`` JSON line that also carries ``"type": <name>``):

``sources``  the passages the model is given, numbered like the ``[SOURCE n]`` markers it may write, and
             ``context``: which sources were read as summaries or left out (null when none were)
``reasoning``  a piece of the model's thinking (only when the request asked for reasoning)
``delta``    ``{"text": ...}``, a piece of the answer as the model wrote it (raw markers)
``done``     the final answer, markers renumbered ``[1] [2]...`` with the matching citations;
             this is what was saved, and the text the UI should swap in
``error``    ``{"message": ...}``; nothing was saved

The caller must have checked the person's role (``access.require_access(..., "chat")``) before streaming starts.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

from . import rag_chat
from .citations import snippet
from .grounding import REFUSAL_TEXT, is_grounded, min_similarity
from .models import ChunkWithScore, Citation, NotebookChatRequest
from .rag_answer import resolve_answer
from .rag_limits import NUM_CTX
from .rag_prompt import compose_messages, num_predict_for

logger = logging.getLogger(__name__)

DISCONNECT_POLL_SECONDS = 0.25
NO_MODEL_MESSAGE = (
    "I couldn't reach any language model. Check that Ollama is running with at least one model pulled."
)

StreamFn = Callable[[str, str, List[Dict[str, str]], Dict[str, Any], float], AsyncIterator[Tuple[str, str]]]
DisconnectFn = Callable[[], Awaitable[bool]]


class LocatedCitation(Citation):
    """Kept for callers that import it; ``Citation`` itself now carries the offsets."""


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 else None


def locator_of(metadata: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    """``start_char``, ``end_char`` and ``page`` from a chunk's metadata; None where unknown."""
    meta = metadata or {}
    page = _int_or_none(meta.get("page"))
    return {
        "start_char": _int_or_none(meta.get("start_char")),
        "end_char": _int_or_none(meta.get("end_char")),
        "page": page if page else None,
    }


def citation_payload(citation: Any, metadata: Optional[Dict[str, Any]] = None, index: Optional[int] = None) -> Dict[str, Any]:
    """JSON-ready citation: the legacy keys plus ``start_char``, ``end_char`` and ``snippet``.

    Offsets come from the citation when it carries them, else from the chunk ``metadata``.
    """
    located = locator_of(metadata)
    for key in ("start_char", "end_char"):
        own = _int_or_none(getattr(citation, key, None))
        if own is not None:
            located[key] = own
    quote = getattr(citation, "quote", None)
    payload: Dict[str, Any] = {
        "source_id": str(citation.source_id) if citation.source_id else None,
        "source_title": citation.source_title,
        "chunk_id": str(citation.chunk_id) if citation.chunk_id else None,
        "page": citation.page if citation.page is not None else located["page"],
        "section": citation.section,
        "quote": quote,
        "snippet": getattr(citation, "snippet", None) or quote,
        "start_char": located["start_char"],
        "end_char": located["end_char"],
    }
    if index is not None:
        payload["index"] = index
    return payload


def source_payloads(chunks: List[ChunkWithScore]) -> List[Dict[str, Any]]:
    """One entry per passage in the prompt; ``n`` is its ``[SOURCE n]`` number."""
    out = []
    for n, found in enumerate(chunks, 1):
        chunk = found.chunk
        meta = chunk.metadata or {}
        located = locator_of(meta)
        out.append({
            "n": n,
            "source_id": str(chunk.source_id),
            "source_title": found.source_title,
            "chunk_id": str(chunk.id),
            "page": located["page"],
            "section": meta.get("section"),
            "snippet": snippet(chunk.content),
            "start_char": located["start_char"],
            "end_char": located["end_char"],
        })
    return out


def sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps({'type': event, **data}, default=str)}\n\n"


# ─── model output ──────────────────────────────────────────────────────────────

class ThinkFilter:
    """Splits inline ``<think>...</think>`` from streamed text, even when a tag spans two pieces."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._thinking = False

    def feed(self, text: str) -> List[Tuple[str, str]]:
        """``[(kind, text)]`` with kind ``content`` or ``reasoning``; empty pieces are dropped."""
        self._buffer += text
        out: List[Tuple[str, str]] = []
        while True:
            tag = self.CLOSE if self._thinking else self.OPEN
            kind = "reasoning" if self._thinking else "content"
            at = self._buffer.find(tag)
            if at >= 0:
                if at:
                    out.append((kind, self._buffer[:at]))
                self._buffer = self._buffer[at + len(tag):]
                self._thinking = not self._thinking
                continue
            # Hold back the end of the buffer if it could be the start of the tag.
            keep = 0
            for size in range(min(len(tag) - 1, len(self._buffer)), 0, -1):
                if tag.startswith(self._buffer[-size:]):
                    keep = size
                    break
            emit = self._buffer[:len(self._buffer) - keep]
            if emit:
                out.append((kind, emit))
            self._buffer = self._buffer[len(self._buffer) - keep:]
            return out

    def flush(self) -> List[Tuple[str, str]]:
        kind = "reasoning" if self._thinking else "content"
        rest, self._buffer = self._buffer, ""
        return [(kind, rest)] if rest else []


class ModelUnavailable(Exception):
    """This model could not be used here (not installed, refused, or errored before answering)."""


async def ollama_chat_stream(
    base_url: str, model: str, messages: List[Dict[str, str]], options: Dict[str, Any], timeout: float
) -> AsyncIterator[Tuple[str, str]]:
    """Yield ``("content" | "reasoning", text)`` from Ollama ``/api/chat`` as the model writes it.

    ``timeout`` bounds the wait for each piece, not the whole answer. A refused connection
    raises ``httpx.ConnectError`` so the caller can stop trying a dead host.
    """
    payload = {"model": model, "messages": messages, "stream": True, "think": False, "options": options}
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        async with client.stream("POST", f"{base_url}/api/chat", json=payload) as response:
            if response.status_code != 200:
                raise ModelUnavailable(f"{model} answered HTTP {response.status_code}")
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("error"):
                    raise ModelUnavailable(str(obj["error"])[:200])
                reply = obj.get("message") or {}
                if reply.get("thinking"):
                    yield "reasoning", reply["thinking"]
                if reply.get("content"):
                    yield "content", reply["content"]
                if obj.get("done"):
                    return


@dataclass
class _Run:
    content: List[str] = field(default_factory=list)
    reasoning: List[str] = field(default_factory=list)
    used_model: str = ""
    gone: bool = False  # the client left
    started: bool = False  # a delta has been sent, so another model can no longer take over
    broken: str = ""  # why the stream died after it started


class _Watch:
    """Asks whether the client is still there, at most a few times a second."""

    def __init__(self, is_disconnected: Optional[DisconnectFn]) -> None:
        self._fn = is_disconnected
        self._next = 0.0

    async def gone(self) -> bool:
        if self._fn is None:
            return False
        now = time.monotonic()
        if now < self._next:
            return False
        self._next = now + DISCONNECT_POLL_SECONDS
        try:
            return bool(await self._fn())
        except Exception:
            return False


async def _generate(
    service: Any,
    messages: List[Dict[str, str]],
    model: str,
    options: Dict[str, Any],
    run: _Run,
    *,
    stream_fn: StreamFn,
    watch: _Watch,
    include_reasoning: bool,
) -> AsyncIterator[str]:
    """Yield ``delta``/``reasoning`` events, trying the same models and hosts as the JSON chat.

    Models are tried in order until one writes something. Once a delta has been sent no other
    model can take over, so a failure after that is recorded in ``run.broken``.
    """
    models = await asyncio.to_thread(service._models_to_try, model, service.allowed_models)
    hosts = [rag_chat.OLLAMA_URL]
    if rag_chat.CLOUD_OLLAMA_URL:  # only when an operator configured one; the prompt carries source text
        hosts.append(rag_chat.CLOUD_OLLAMA_URL)

    for base_url in hosts:
        for name in models:
            splitter = ThinkFilter()
            attempt_reasoning: List[str] = []

            def route(pieces: List[Tuple[str, str]]) -> List[str]:
                events = []
                for kind, text in pieces:
                    if kind == "content":
                        if not run.content and not text.strip():
                            continue  # leading blank lines
                        text = text if run.content else text.lstrip()
                        run.content.append(text)
                        run.started = True
                        events.append(sse("delta", {"text": text}))
                    else:
                        attempt_reasoning.append(text)
                        if include_reasoning:
                            events.append(sse("reasoning", {"text": text}))
                return events

            try:
                async for kind, text in stream_fn(base_url, name, messages, options, _llm_timeout()):
                    if await watch.gone():
                        run.gone = True
                        return
                    for event in route(splitter.feed(text) if kind == "content" else [(kind, text)]):
                        yield event
                for event in route(splitter.flush()):
                    yield event
            except httpx.ConnectError:
                logger.warning("Ollama at the configured host is not reachable")
                break
            except Exception as exc:
                if run.started:
                    run.broken = f"The model stopped answering: {str(exc)[:200] or type(exc).__name__}"
                    return
                logger.warning("Streaming with %s failed: %s", name, exc)
                continue

            if "".join(run.content).strip():
                run.used_model = name
                run.reasoning = attempt_reasoning
                return
            logger.warning("Model %s produced no answer text; trying the next model", name)


def _llm_timeout() -> float:
    return float(rag_chat.LLM_TIMEOUT)


# ─── the stream ────────────────────────────────────────────────────────────────

async def stream_notebook_answer(
    service: Any,
    notebook: Any,
    user_id: int,
    request: NotebookChatRequest,
    *,
    is_disconnected: Optional[DisconnectFn] = None,
    stream_fn: Optional[StreamFn] = None,
    redact: bool = False,
) -> AsyncIterator[str]:
    """SSE text for one grounded answer; the exchange is saved only if it finishes.

    ``redact`` is for the chat_only role: the ``sources`` event and the final citations carry
    no text copied from a source.
    """
    from .access import redact_citation

    def _clean(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [redact_citation(i) for i in items] if redact else items

    stream_fn = stream_fn or ollama_chat_stream
    notebook_id: UUID = notebook.id
    watch = _Watch(is_disconnected)
    include_reasoning = bool(request.include_reasoning)

    try:
        config = await service.load_config(notebook_id, user_id)
        history = await service.load_history(notebook_id, user_id)  # before this turn is saved
        found = await service.retrieve(
            notebook_id, user_id, request.message, history=history, top_k=request.top_k,
            source_ids=request.source_ids, summary_source_ids=request.summary_source_ids,
            allow_overview=True, model=request.model
        )
    except Exception:
        logger.error("Notebook stream: retrieval failed", exc_info=True)
        yield sse("error", {"message": "Something went wrong searching this notebook."})
        return

    chunks: List[ChunkWithScore] = found.chunks
    if not chunks:
        if found.empty_reply:
            saved = await service._save_exchange(
                notebook_id, user_id, request.message, found.empty_reply, model_used=request.model
            )
            yield sse("sources", {"sources": [], "context": found.report})
            yield sse("delta", {"text": found.empty_reply})
            yield sse("done", _done(found.empty_reply, [], request.model, saved.id, empty=True, context=found.report))
            return
        if found.embedded:
            reply = await service._chat_empty_notebook(notebook_id, user_id, request)
            yield sse("sources", {"sources": []})
            yield sse("delta", {"text": reply.answer})
            yield sse("done", _done(reply.answer, [], request.model, reply.message_id, empty=True))
            return
        logger.warning("Could not get query embedding, streaming without RAG")
        from .rag_chat import CHAT_SYSTEM_NO_SOURCES
        messages = compose_messages(CHAT_SYSTEM_NO_SOURCES, "", history, request.message)
    elif not found.floor_exempt and not is_grounded(chunks):
        logger.info("Refusing: best passage below similarity floor %.2f (notebook %s)", min_similarity(), notebook_id)
        saved = await service._save_exchange(
            notebook_id, user_id, request.message, REFUSAL_TEXT, model_used=request.model
        )
        yield sse("sources", {"sources": []})
        yield sse("delta", {"text": REFUSAL_TEXT})
        yield sse("done", _done(REFUSAL_TEXT, [], request.model, saved.id, refused=True))
        return
    else:
        messages = service.build_messages(notebook, chunks, history, request.message, config)

    yield sse("sources", {"sources": _clean(source_payloads(chunks)), "context": found.report})

    options = {
        "temperature": 0.7,
        "top_p": 0.9,
        "num_predict": num_predict_for(config) or rag_chat.DEFAULT_NUM_PREDICT,
        "num_ctx": NUM_CTX,
    }
    run = _Run()
    async for event in _generate(
        service, messages, request.model, options, run,
        stream_fn=stream_fn, watch=watch, include_reasoning=include_reasoning,
    ):
        yield event
    if run.gone:
        logger.info("Client left the notebook stream; nothing saved")
        return
    if run.broken:
        yield sse("error", {"message": run.broken})
        return
    if not run.used_model:
        yield sse("error", {"message": NO_MODEL_MESSAGE})
        return

    answer = "".join(run.content).strip()
    text, citations, unsupported = resolve_answer(answer, chunks)
    by_chunk = {str(c.chunk.id): c.chunk.metadata or {} for c in chunks}
    located = [
        c.model_copy(update={
            "start_char": c.start_char if c.start_char is not None else locator_of(by_chunk.get(str(c.chunk_id)))["start_char"],
            "end_char": c.end_char if c.end_char is not None else locator_of(by_chunk.get(str(c.chunk_id)))["end_char"],
            "snippet": c.snippet or c.quote,
        })
        for c in citations
    ]
    reasoning = "".join(run.reasoning).strip() or None
    message_id = None
    try:
        saved = await service._save_exchange(
            notebook_id, user_id, request.message, text,
            reasoning=reasoning if include_reasoning else None,
            citations=located, model_used=run.used_model,
        )
        message_id = saved.id
    except Exception:
        logger.error("Notebook stream: could not save the exchange", exc_info=True)
    payloads = _clean([citation_payload(c, by_chunk.get(str(c.chunk_id)), i) for i, c in enumerate(located, 1)])
    yield sse("done", _done(
        text, payloads, run.used_model, message_id, unsupported=unsupported,
        reasoning=reasoning if include_reasoning else None, saved=message_id is not None, context=found.report,
    ))


def _done(
    answer: str, citations: List[Dict[str, Any]], model: str, message_id: Any, *,
    refused: bool = False, unsupported: bool = False, empty: bool = False,
    reasoning: Optional[str] = None, saved: bool = True, context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "answer": answer,
        "citations": citations,
        "model_used": model,
        "message_id": str(message_id) if message_id else None,
        "refused": refused,
        "unsupported": unsupported,
        "empty_notebook": empty,
        "reasoning": reasoning,
        "saved": saved,
        "context": context,
    }
