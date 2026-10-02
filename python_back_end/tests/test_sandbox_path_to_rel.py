"""The file tools accept the /workspace/... paths the chat sandbox shows the model,
and the traversal check still applies to what is left."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration.tools import _sandbox_path_to_rel, dispatch_tool  # noqa: E402


def test_sandbox_prefix_becomes_relative():
    assert _sandbox_path_to_rel({"path": "/workspace/fib.py"})["path"] == "fib.py"
    assert _sandbox_path_to_rel({"path": "/workspace/src/a.py"})["path"] == "src/a.py"
    assert _sandbox_path_to_rel({"path": "/workspace"})["path"] == "."


def test_other_paths_are_untouched():
    for p in ("fib.py", "/etc/passwd", "/workspaces/x", "/workspace-other/x"):
        assert _sandbox_path_to_rel({"path": p})["path"] == p
    assert _sandbox_path_to_rel({"command": "ls"}) == {"command": "ls"}


def test_edit_file_writes_a_sandbox_path_into_the_workspace(tmp_path):
    out, ok = asyncio.run(dispatch_tool(str(tmp_path), "edit_file",
                                        {"path": "/workspace/fib.py", "content": "print(1)\n"}))
    assert ok, out
    assert (tmp_path / "fib.py").read_text() == "print(1)\n"


def test_traversal_through_the_prefix_is_still_refused(tmp_path):
    out, ok = asyncio.run(dispatch_tool(str(tmp_path), "edit_file",
                                        {"path": "/workspace/../escape.py", "content": "x"}))
    assert not ok and "outside your workspace" in out
    assert not (tmp_path.parent / "escape.py").exists()
