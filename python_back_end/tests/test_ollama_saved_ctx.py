"""A model's saved num_ctx is its real window (ollama_hosts._show_context)."""

import asyncio

from owui_compat import ollama_hosts as oh


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _Client:
    def __init__(self, body):
        self.body = body

    async def post(self, url, json=None):
        return _Resp(self.body)


def _show(body, base="http://h", tag="m:latest"):
    oh._ctx_cache.clear()
    oh._param_ctx.clear()
    asyncio.run(oh._show_context(_Client(body), base, tag))
    return oh._ctx_cache.get(f"{base}|{tag}"), oh._param_ctx.get(oh._tag(tag))


def test_saved_num_ctx_beats_the_cap():
    body = {"model_info": {"nemotron.context_length": 1048576},
            "parameters": 'num_ctx                        131072\nstop "<|im_end|>"'}
    assert _show(body) == (131072, 131072)


def test_saved_num_ctx_never_exceeds_what_the_model_was_trained_for():
    body = {"model_info": {"llama.context_length": 8192}, "parameters": "num_ctx 65536"}
    assert _show(body)[0] == 8192


def test_without_a_saved_value_the_cap_still_applies():
    body = {"model_info": {"qwen.context_length": 262144}, "parameters": 'stop "x"'}
    assert _show(body) == (oh.SERVED_CONTEXT_CAP, None)
