"""An agent's exec in a chat sandbox streams into the chat's agent terminal tab
while it runs, and the tool loop still gets the same (result, ok) back."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui.runs import _Translator  # noqa: E402
from workspace.orchestration import runner  # noqa: E402
from workspace.terminal_container import exec_output_sink  # noqa: E402


async def _fake_exec():
    sink = exec_output_sink.get()
    sink("🔥 frame 1\n")
    await asyncio.sleep(0.3)
    sink("🔥 frame 2\n")
    return "🔥 frame 1\n🔥 frame 2\n", True


def test_exec_live_streams_then_returns():
    async def go():
        return [i async for i in runner._exec_live(_fake_exec(), command="bash fire.sh", command_id="r:1")]

    items = asyncio.run(go())
    assert items[0] == {"command_id": "r:1", "command": "bash fire.sh", "content": ""}
    streamed = "".join(i.get("content", "") for i in items if isinstance(i, dict))
    assert streamed == "🔥 frame 1\n🔥 frame 2\n"
    assert items[-2] == {"command_id": "r:1", "content": "", "ok": True}
    assert items[-1] == ("🔥 frame 1\n🔥 frame 2\n", True)
    # The first frame went out before the command finished, not all at the end.
    assert sum(1 for i in items if isinstance(i, dict) and i.get("content")) == 2


def test_sink_does_not_leak_out_of_the_run():
    async def go():
        async for _ in runner._exec_live(_fake_exec(), command="x", command_id="r:2"):
            pass
        return exec_output_sink.get()

    assert asyncio.run(go()) is None


def test_translator_feeds_the_agent_terminal():
    tr = _Translator("ws1", "http://h")
    first = tr.translate({"type": "exec_output", "command_id": "r:1", "command": "bash fire.sh", "content": ""})
    mid = tr.translate({"type": "exec_output", "command_id": "r:1", "content": "hi\n"})
    end = tr.translate({"type": "exec_output", "command_id": "r:1", "content": "", "ok": False})
    assert first == [("agent_terminal", {"process_id": "r:1", "chunk": "", "command": "bash fire.sh"})]
    assert mid == [("agent_terminal", {"process_id": "r:1", "chunk": "hi\n"})]
    assert end[0][1]["chunk"].strip() == "[finished with an error]"


def test_runner_streams_a_sandbox_exec(tmp_path, monkeypatch):
    import json

    async def fake_dispatch(ws, name, args, **kw):
        assert kw.get("session_id") == "hs-u1-test"
        if name == "exec":
            exec_output_sink.get()("it ran\n")
            return "it ran\n", True
        return "ok", True

    class Router:
        turns = [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "exec", "arguments": json.dumps({"command": "bash fire.sh"})}}]}]

        async def complete(self, *, tools, **_):
            return self.turns.pop(0) if (tools and self.turns) else {"role": "assistant", "content": "Done."}

    monkeypatch.setattr(runner, "dispatch_tool", fake_dispatch)

    async def go():
        return [e async for e in runner.SubAgentRunner(Router()).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="run the fire script",
            model_name="m", workspace_path=str(tmp_path), session_id="hs-u1-test", launch_mode="user",
        )]

    events = asyncio.run(go())
    live = [e.data for e in events if e.type == "exec_output"]
    assert live[0]["command"] == "bash fire.sh"
    assert "".join(d.get("content", "") for d in live) == "it ran\n"
    assert live[-1]["ok"] is True
    results = [e.data for e in events if e.type == "tool_result" and e.data.get("tool") == "exec"]
    assert results and results[0]["output"] == "it ran\n"
