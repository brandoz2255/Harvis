"""The no-progress guard must not cut off write → run → read the error → fix, and
when it does trip, the user still gets an answer rather than the stop line."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration import runner  # noqa: E402


def _call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c-{name}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}},
    ]}


class ScriptedRouter:
    def __init__(self, turns, answer="Here is your fire script."):
        self.turns = list(turns)
        self.answer = answer
        self.calls = 0

    async def complete(self, *, tools, **_):
        self.calls += 1
        if not tools:  # the tools-removed answer round
            return {"role": "assistant", "content": self.answer}
        return self.turns.pop(0) if self.turns else {"role": "assistant", "content": self.answer}


def _run(tmp_path, monkeypatch, turns, **kw):
    async def fake_dispatch(ws, name, args, **_):
        if name in ("apply_patch", "write"):
            p = tmp_path / args["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"])
            return f"Wrote {args['path']}", True
        if name == "exec":
            return "fire.sh: line 60: rand: unbound variable\n", True
        return "file body", True

    monkeypatch.setattr(runner, "dispatch_tool", fake_dispatch)
    router = ScriptedRouter(turns)

    async def go():
        return [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="make a fire script",
            model_name="m", workspace_path=str(tmp_path), **kw,
        )]

    return asyncio.run(go()), router


def _tools(events):
    return [e.data.get("tool") for e in events if e.type == "tool_call"]


def test_running_the_code_is_not_idle(tmp_path, monkeypatch):
    # The real trace: write, chmod/check, run (errors), read it back, then fix it.
    turns = [
        _call("write", path="apps/fire/fire.sh", content="v1"),
        _call("exec", command="bash -n fire.sh"),
        _call("exec", command="timeout 3 bash fire.sh"),
        _call("read_file", path="apps/fire/fire.sh"),
        _call("write", path="apps/fire/fire.sh", content="v2 fixed"),
        _call("finish", summary="Fixed and working."),
    ]
    events, _ = _run(tmp_path, monkeypatch, turns)
    assert _tools(events).count("write") == 2  # it got to make the fix
    assert (tmp_path / "apps/fire/fire.sh").read_text() == "v2 fixed"


def test_guard_trip_still_answers(tmp_path, monkeypatch):
    # Real churn (re-reading without running or editing) still stops — with an answer.
    turns = [_call("write", path="a.txt", content="x")] + [
        _call("read_file", path=f"a{i}.txt") for i in range(8)
    ]
    events, router = _run(tmp_path, monkeypatch, turns)
    finals = [e for e in events if e.type == "agent_end"]
    summary = finals[-1].data.get("summary", "")
    assert "Here is your fire script." in summary
    assert "idle steps" not in summary
    assert _tools(events).count("read_file") == runner._MAX_IDLE_STEPS


def test_answer_shows_what_ran(tmp_path, monkeypatch):
    # The model answers with a feature list; the user must still see it ran and the output.
    turns = [
        _call("write", path="greet.py", content="print('hi')"),
        _call("exec", command="python3 greet.py"),
        _call("finish", summary="Upgraded the script with rainbow colours."),
    ]
    events, _ = _run(tmp_path, monkeypatch, turns)
    summary = [e for e in events if e.type == "agent_end"][-1].data["summary"]
    assert summary.startswith("Upgraded the script")
    assert "**Ran** `python3 greet.py` (ran OK)" in summary
    assert "rand: unbound variable" in summary


def test_run_output_is_cleaned_and_not_repeated():
    out = "\x1b[2J\x1b[1;33mHello, David!\x1b[0m\r\n" + "".join(f"frame {i}\n" for i in range(50))
    shown = runner._with_run_output("Done.", ("bash fire.sh", out, True))
    assert "\x1b" not in shown and "Hello, David!" in shown and "more lines" in shown
    quoted = "Created and ran it. Output:\nHello, David! Your script is working."
    assert runner._with_run_output(quoted, ("python3 greet.py", "Hello, David! Your script is working.\n", True)) == quoted
    assert runner._with_run_output("Here is the file.", None) == "Here is the file."
