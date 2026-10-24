"""A provider 4xx inside the agent loop reaches the run card as the provider's reason,
not as httpx's status line."""

import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration import runner  # noqa: E402


class _FailingRouter:
    def __init__(self, exc):
        self.exc = exc

    async def complete(self, **_):
        raise self.exc


def _final_summary(tmp_path, exc):
    async def go():
        return [e async for e in runner.SubAgentRunner(_FailingRouter(exc)).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="read the file",
            model_name="gemma3:4b", workspace_path=str(tmp_path),
        )]

    events = asyncio.run(go())
    return [e for e in events if e.type == "agent_end"][-1].data["summary"]


def _status_error(code, body):
    req = httpx.Request("POST", "http://host.docker.internal:11434/v1/chat/completions")
    return httpx.HTTPStatusError("status line", request=req, response=httpx.Response(code, json=body, request=req))


def test_a_400_shows_the_providers_reason(tmp_path):
    summary = _final_summary(tmp_path, _status_error(400, {"error": "gemma3:4b does not support tools"}))
    assert "gemma3:4b does not support tools" in summary
    assert "Client error" not in summary and "host.docker.internal" not in summary


def test_a_404_shows_the_model_sentence(tmp_path):
    summary = _final_summary(tmp_path, _status_error(404, {"error": "model 'ghost:1b' not found"}))
    assert "That model is not available" in summary and "ghost:1b" in summary


def test_other_errors_keep_their_old_text(tmp_path):
    assert _final_summary(tmp_path, RuntimeError("disk full")).endswith("disk full")
    assert "stopped responding" in _final_summary(tmp_path, httpx.ReadTimeout(""))


def test_a_provider_401_names_the_api_key_not_the_harvis_session(tmp_path):
    summary = _final_summary(tmp_path, _status_error(401, {"error": {"message": "invalid api key"}}))
    assert "API key" in summary and "session expired" not in summary
