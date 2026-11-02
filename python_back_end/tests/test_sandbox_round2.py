"""Round-2 sandbox hardening: persistent terminal volume options, the default terminal
network name and its fallback, and write_text refusing planted links."""

import asyncio
import importlib
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import sandbox  # noqa: E402


# ─── F19: persistent volume must not be reset to root by Docker's copy-up ────

class _Containers:
    def __init__(self):
        self.runs = []

    def get(self, name):
        from docker.errors import NotFound
        raise NotFound("none")

    def run(self, image, command=None, **kw):
        self.runs.append((image, command, kw))
        return object()


class _Networks:
    def __init__(self, present):
        self.present = present
        self.asked = []

    def get(self, name):
        from docker.errors import NotFound
        self.asked.append(name)
        if name not in self.present:
            raise NotFound("no such network")
        return object()


class _Client:
    def __init__(self, networks=("ws-term-net",)):
        self.containers = _Containers()
        self.images = type("I", (), {"get": staticmethod(lambda n: object())})()
        self.networks = _Networks(networks)

    def ping(self):
        return True


def _manager(networks=("ws-term-net",)):
    from workspace.terminal_container import WorkspaceTerminalManager

    m = WorkspaceTerminalManager.__new__(WorkspaceTerminalManager)
    m._client = _Client(networks)
    m._terminals = {}
    m._own_mounts = []
    return m


def _runs(m):
    runs = m._client.containers.runs
    chown = [r for r in runs if r[1] and r[1][0] == "chown"][0][2]
    main = [r for r in runs if r[1] == ["sh", "-c", "tail -f /dev/null"]][0][2]
    return chown, main


@pytest.fixture
def term(monkeypatch):
    import workspace.terminal_container as tc

    monkeypatch.setattr(tc, "_NETWORK", "ws-term-net")
    monkeypatch.setattr(tc, "_PERSISTENT", True)
    return tc


def test_persistent_workspace_volume_is_mounted_nocopy(term):
    m = _manager()
    asyncio.run(m._spawn("ws-1"))
    chown, main = _runs(m)
    (vol,) = main["volumes"].values()
    assert vol["bind"] == "/workspace" and "nocopy" in vol["mode"].split(",") and vol["mode"].startswith("rw")
    (cvol,) = chown["volumes"].values()
    assert cvol["bind"] == "/workspace" and "nocopy" in cvol["mode"].split(",")


def test_the_volume_is_chowned_before_the_terminal_starts(term):
    m = _manager()
    asyncio.run(m._spawn("ws-1"))
    first = m._client.containers.runs[0]
    assert first[1][0] == "chown" and first[1][-1] == "/workspace"


# ─── F19 follow-up: default terminal network and graceful fallback ───────────

def _reloaded(monkeypatch, **env):
    import workspace.terminal_container as tc

    for k in ("HARVIS_TERMINAL_NETWORK", "HARVIS_STACK_NAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    try:
        return importlib.reload(tc)._NETWORK
    finally:
        monkeypatch.undo()
        importlib.reload(tc)


def test_default_network_is_the_one_compose_creates(monkeypatch):
    assert _reloaded(monkeypatch) == "harvis_ws-term-net"


def test_default_network_follows_the_stack_name(monkeypatch):
    assert _reloaded(monkeypatch, HARVIS_STACK_NAME="lab") == "lab_ws-term-net"


def test_explicit_network_wins_over_the_default(monkeypatch):
    assert _reloaded(monkeypatch, HARVIS_TERMINAL_NETWORK="custom-net", HARVIS_STACK_NAME="lab") == "custom-net"


def test_a_blank_network_variable_falls_back_to_the_default(monkeypatch):
    assert _reloaded(monkeypatch, HARVIS_TERMINAL_NETWORK="  ") == "harvis_ws-term-net"


def test_the_terminal_joins_the_configured_network_when_it_exists(term):
    m = _manager(networks=("ws-term-net",))
    asyncio.run(m._spawn("ws-1"))
    assert _runs(m)[1]["network"] == "ws-term-net"


def test_a_missing_network_means_no_network_and_a_clear_log_line(term, caplog):
    m = _manager(networks=())
    with caplog.at_level(logging.WARNING, logger="workspace.terminal_container"):
        asyncio.run(m._spawn("ws-1"))
    assert _runs(m)[1]["network"] == "none"
    assert any("ws-term-net" in r.message and "none" in r.message for r in caplog.records)


def test_a_missing_network_never_lands_on_a_shared_harvis_network(term):
    m = _manager(networks=("harvis_openclaw-internal",))
    asyncio.run(m._spawn("ws-1"))
    assert _runs(m)[1]["network"] == "none"


def test_probe_stays_ready_but_says_the_network_is_missing(term):
    m = _manager(networks=())
    m._readiness = None
    m._readiness_ttl_s = 0
    rep = asyncio.run(m.probe(force=True))
    assert rep.ready and not rep.network_present and "ws-term-net" in rep.reason


# ─── F25: write_text refuses a link planted at the target ────────────────────

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("HARVIS_SANDBOX_ENABLED", raising=False)
    return tmp_path / "root"


VPATH = "/sandbox/sess-1/workspace/notes.txt"


def _plant(root, make):
    base = sandbox.ensure_dir(7, "sess-1")
    target = os.path.join(base, "notes.txt")
    make(target)
    return target


def _swap_in_after_resolve(monkeypatch, make_link):
    """resolve() realpaths a planted symlink away, so only a link swapped in between
    resolve() and open() reaches O_NOFOLLOW: plant it right after resolve() returns."""
    real_resolve = sandbox.resolve

    def resolve_then_swap(*a, **k):
        out = real_resolve(*a, **k)
        make_link(out[1])
        return out

    monkeypatch.setattr(sandbox, "resolve", resolve_then_swap)


def test_write_text_does_not_follow_a_symlink_swapped_in_after_resolve(root, tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    sandbox.ensure_dir(7, "sess-1")
    _swap_in_after_resolve(monkeypatch, lambda t: os.symlink(victim, t))
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, VPATH, "pwned")
    assert victim.read_text() == "keep me"
    assert os.path.islink(os.path.join(sandbox.session_dir(7, "sess-1"), "notes.txt"))


def test_write_text_does_not_follow_a_symlink_to_a_file_inside_the_sandbox(root, monkeypatch):
    base = sandbox.ensure_dir(7, "sess-1")
    inner = os.path.join(base, "inner.txt")
    open(inner, "w").write("inner")
    _swap_in_after_resolve(monkeypatch, lambda t: os.symlink(inner, t))
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, VPATH, "x")
    assert open(inner).read() == "inner"


def test_write_text_refuses_a_symlink_to_an_outside_file_even_without_a_race(root, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    _plant(root, lambda t: os.symlink(victim, t))
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, VPATH, "pwned")
    assert victim.read_text() == "keep me"


def test_write_text_refuses_a_non_regular_file_it_could_open(root):
    # With a reader attached, a fifo opens fine for writing: only S_ISREG stops it.
    target = _plant(root, lambda t: os.mkfifo(t))
    reader = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
    try:
        with pytest.raises(sandbox.SandboxError):
            sandbox.write_text(7, VPATH, "data")
        assert os.read(reader, 16) == b""  # nothing was written into the pipe
    finally:
        os.close(reader)


def test_write_text_still_writes_a_regular_file(root):
    sandbox.ensure_dir(7, "sess-1")
    assert sandbox.write_text(7, VPATH, "hello") == {"ok": True, "path": VPATH}
    assert sandbox.write_text(7, VPATH, "hi") == {"ok": True, "path": VPATH}
    base = sandbox.session_dir(7, "sess-1")
    assert open(os.path.join(base, "notes.txt")).read() == "hi"
