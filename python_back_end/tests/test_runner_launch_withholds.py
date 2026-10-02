"""An auto launch may run commands only where dispatch_tool sends them to the
chat's isolated container; everywhere else exec and run_tests stay withheld."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration import runner  # noqa: E402
from workspace.orchestration.runner import _default_system, _launch_withholds  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_on(monkeypatch):
    monkeypatch.delenv("HARVIS_BUILD_ISOLATED_RUNNER", raising=False)


def test_user_launches_withhold_nothing():
    assert _launch_withholds("user", None) == set()


def test_auto_launch_without_a_sandbox_cannot_run_commands():
    assert _launch_withholds("auto", None) == {"exec", "run_tests"}
    assert _launch_withholds("auto", "") == {"exec", "run_tests"}


def test_auto_launch_in_a_sandbox_can_run_commands():
    assert _launch_withholds("auto", "sess-1") == set()


@pytest.mark.parametrize("off", ["0", "false", "no", "off"])
def test_isolated_runner_off_withholds_again(monkeypatch, off):
    monkeypatch.setenv("HARVIS_BUILD_ISOLATED_RUNNER", off)
    assert _launch_withholds("auto", "sess-1") == {"exec", "run_tests"}


def test_offer_matches_dispatch_routing(monkeypatch):
    # Whatever the flag says, exec is offered only when dispatch_tool would isolate it.
    for env in ("", "1", "0", "off", "garbage"):
        monkeypatch.setenv("HARVIS_BUILD_ISOLATED_RUNNER", env)
        for sid in (None, "sess-1"):
            isolated = bool(sid) and runner._isolated_runner_enabled()
            assert ("exec" not in _launch_withholds("auto", sid)) == isolated


def test_prompt_follows_the_offer():
    assert "run exec / run_tests" in _default_system("coder", _launch_withholds("auto", "sess-1"))
    assert "cannot run commands" in _default_system("coder", _launch_withholds("auto", None))
