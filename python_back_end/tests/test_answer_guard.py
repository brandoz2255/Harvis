"""owui_compat.answer_guard: a native chat turn never ends blank; Sources only under an answer."""

import asyncio
import json

from fastapi.responses import StreamingResponse

from owui_compat import answer_guard as ag
from owui_compat import chat_reach


def _sse(*deltas, done=True):
    out = [f"data: {json.dumps({'choices': [{'index': 0, 'delta': d}]})}\n\n".encode() for d in deltas]
    if done:
        out.append(b"data: [DONE]\n\n")
    return out


async def _iter(chunks):
    for c in chunks:
        yield c


def _resp(chunks):
    return StreamingResponse(_iter(chunks), media_type="text/event-stream")


async def _collect(resp):
    return b"".join([c async for c in resp.body_iterator]).decode()


def _run(first, retry_chunks=None, retry_dict=None):
    calls = []

    async def retry(extra):
        calls.append(extra)
        return retry_dict if retry_dict is not None else _resp(retry_chunks or _sse())

    out = asyncio.run(_collect_guard(first, retry))
    return out, calls


async def _collect_guard(first, retry):
    return await _collect(await ag.ensure_answer(_resp(first), retry))


def test_an_answer_passes_through_untouched():
    out, calls = _run(_sse({"content": "391"}))
    assert '"391"' in out and calls == [] and out.count("[DONE]") == 1


def test_reasoning_only_is_retried_with_thinking_off():
    out, calls = _run(_sse({"reasoning": "let me think..."}), _sse({"content": "It is 391."}))
    assert calls == [{"reasoning_effort": "none"}]
    assert "It is 391." in out and out.count("[DONE]") == 1 and out.rstrip().endswith("[DONE]")


def test_a_blank_reply_without_reasoning_retries_without_the_flag():
    _out, calls = _run(_sse({"content": "  "}), _sse({"content": "ok"}))
    assert calls == [{}]


def test_still_empty_says_so_in_a_sentence():
    out, _ = _run(_sse({"reasoning": "hmm"}), _sse({"reasoning": "hmm again"}))
    assert ag.NO_ANSWER in out


def test_an_upstream_error_is_left_alone():
    err = [f"data: {json.dumps({'error': {'message': 'boom'}})}\n\n".encode(), b"data: [DONE]\n\n"]
    out, calls = _run(err)
    assert calls == [] and "boom" in out and ag.NO_ANSWER not in out


def test_non_streamed_empty_answer_is_retried():
    first = {"choices": [{"message": {"role": "assistant", "content": "", "reasoning": "x"}}]}
    good = {"choices": [{"message": {"role": "assistant", "content": "391"}}]}
    calls = []

    async def retry(extra):
        calls.append(extra)
        return good

    assert asyncio.run(ag.ensure_answer(first, retry)) is good and calls == [{"reasoning_effort": "none"}]


def test_sources_only_under_a_real_answer():
    async def go(chunks):
        return b"".join([c async for c in chat_reach._stream_with_sources(_iter(chunks), "SOURCES-LIST")]).decode()

    assert "SOURCES-LIST" in asyncio.run(go(_sse({"content": "an answer"})))
    assert "SOURCES-LIST" not in asyncio.run(go(_sse({"reasoning": "only thinking"})))
    assert "SOURCES-LIST" not in asyncio.run(go(_sse({"content": ag.NO_ANSWER})))


def test_a_long_paste_is_not_searched_on_the_regex_alone():
    assert chat_reach._looks_pasted("Cyber Command\nNOTE: x\nBart left\nsplit\nbytes")
    assert chat_reach._looks_pasted("x" * 401)
    assert not chat_reach._looks_pasted("who is the ceo of anthropic")
