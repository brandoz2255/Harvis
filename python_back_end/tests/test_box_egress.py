"""A chat's box has no network of its own: the internet comes only through the
box-egress proxy socket, every failure ends with no network at all, and the
backend shows the box's apps through a ``docker exec`` tunnel instead of a
shared Docker network.

    python -m pytest tests/test_box_egress.py -q
"""
from __future__ import annotations

import asyncio
import socket
import struct
import threading

import httpx
import pytest
from docker.errors import APIError, NotFound

from workspace import box_tunnel
from workspace import terminal_container as tc


class _Containers:
    def __init__(self, fail_with=None):
        self.runs = []
        self.removed = []
        self._fail_with = fail_with

    def get(self, name):
        if self.runs:
            box = self

            class Left:
                def remove(self, force=False):
                    box.removed.append(name)
            return Left()
        raise NotFound("no such box")

    def run(self, image, **kwargs):
        self.runs.append(kwargs)
        if self._fail_with and "storage_opt" in kwargs:
            raise self._fail_with
        return object()


class _Named:
    def __init__(self, names):
        self.names = set(names)

    def get(self, name):
        if name not in self.names:
            raise NotFound(name)
        return object()


class _Client:
    def __init__(self, volumes=(), networks=(), fail_with=None):
        self.containers = _Containers(fail_with)
        self.volumes = _Named(volumes)
        self.networks = _Named(networks)


def _manager(client, monkeypatch, tmp_path):
    m = tc.WorkspaceTerminalManager.__new__(tc.WorkspaceTerminalManager)
    m._client = client
    m._own_mounts = None
    m._terminals = {}

    async def host_path_of(path):
        return "/host" + path
    monkeypatch.setattr(m, "host_path_of", host_path_of)
    return m


def _spawn(client, monkeypatch, tmp_path, egress="web", disk="10G"):
    monkeypatch.setattr(tc, "_RUNNER_EGRESS", egress)
    monkeypatch.setattr(tc, "_RUNNER_DISK", disk)
    monkeypatch.setattr(tc, "_disk_cap_unsupported", False)
    monkeypatch.setattr(tc, "_RUNNER_PROFILE", f"sudo-v2-{egress}")
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    asyncio.run(_manager(client, monkeypatch, tmp_path)._spawn_isolated("vc:s1", "s1", str(ws)))
    return client.containers.runs[-1], "/host" + str(ws)


# ─── what the box is started with ─────────────────────────────────────────────

def test_web_box_has_no_network_and_reaches_out_only_through_the_proxy(monkeypatch, tmp_path):
    vol = tc._EGRESS_VOLUME["web"]
    run, src = _spawn(_Client(volumes=[vol]), monkeypatch, tmp_path, "web")
    assert run["network"] == "none"
    assert run["volumes"] == {src: {"bind": "/workspace", "mode": "rw"},
                              vol: {"bind": "/run/harvis-egress", "mode": "ro"}}
    env = run["environment"]
    assert env["https_proxy"] == env["HTTP_PROXY"] == "http://127.0.0.1:3128"
    assert "127.0.0.1" in env["no_proxy"]
    assert "UNIX-CONNECT:/run/harvis-egress/proxy.sock" in run["command"][-1]
    assert "bind=127.0.0.1" in run["command"][-1]
    assert run["labels"]["harvis.runner_profile"] == "sudo-v2-web"
    assert run["storage_opt"] == {"size": "10G"}


def test_packages_box_mounts_the_registry_only_socket(monkeypatch, tmp_path):
    vol = tc._EGRESS_VOLUME["packages"]
    run, _ = _spawn(_Client(volumes=[vol]), monkeypatch, tmp_path, "packages")
    assert run["network"] == "none"
    assert run["volumes"][vol]["bind"] == "/run/harvis-egress"


@pytest.mark.parametrize("egress, client", [
    ("web", _Client()),                                   # box-egress not running
    ("none", _Client(volumes=[tc._EGRESS_VOLUME["web"]])),
    ("open", _Client()),                                  # bridge network missing
])
def test_every_failure_ends_with_no_network_and_no_proxy(monkeypatch, tmp_path, egress, client):
    run, src = _spawn(client, monkeypatch, tmp_path, egress)
    assert run["network"] == "none"
    assert list(run["volumes"]) == [src]
    assert "https_proxy" not in run["environment"]
    assert run["command"] == ["sh", "-c", "tail -f /dev/null"]


def test_open_mode_still_uses_the_old_bridge_when_asked(monkeypatch, tmp_path):
    run, _ = _spawn(_Client(networks=[tc._RUNNER_NETWORK]), monkeypatch, tmp_path, "open")
    assert run["network"] == tc._RUNNER_NETWORK
    assert "https_proxy" not in run["environment"]


def test_an_old_box_is_recreated_under_the_new_profile(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    client = _Client(volumes=[tc._EGRESS_VOLUME["web"]])
    removed = []

    class Old:
        status = "running"
        attrs = {"Mounts": [{"Destination": "/workspace", "Source": "/host" + str(ws)}],
                 "HostConfig": {}, "Config": {"Labels": {}}}   # a box from before: no profile label

        def remove(self, force=False):
            removed.append(True)
    client.containers.get = lambda name: Old()
    monkeypatch.setattr(tc, "_RUNNER_EGRESS", "web")
    monkeypatch.setattr(tc, "_RUNNER_PROFILE", "sudo-v2-web")
    asyncio.run(_manager(client, monkeypatch, tmp_path)._spawn_isolated("vc:s1", "s1", str(ws)))
    assert removed and client.containers.runs


# ─── the disk cap ─────────────────────────────────────────────────────────────

def test_docker_that_cannot_cap_disk_falls_back_once(monkeypatch, tmp_path):
    err = APIError("--storage-opt is supported only for overlay over xfs with 'pquota' mount option")
    client = _Client(volumes=[tc._EGRESS_VOLUME["web"]], fail_with=err)
    _spawn(client, monkeypatch, tmp_path, "web")
    first, second = client.containers.runs
    assert "storage_opt" in first and "storage_opt" not in second
    assert client.containers.removed == [first["name"]]
    assert tc._disk_cap_unsupported is True


def test_other_docker_errors_are_not_swallowed(monkeypatch, tmp_path):
    client = _Client(volumes=[tc._EGRESS_VOLUME["web"]], fail_with=APIError("image not found"))
    with pytest.raises(APIError):
        _spawn(client, monkeypatch, tmp_path, "web")
    assert len(client.containers.runs) == 1


def test_an_empty_disk_setting_means_no_cap(monkeypatch, tmp_path):
    run, _ = _spawn(_Client(volumes=[tc._EGRESS_VOLUME["web"]]), monkeypatch, tmp_path, "web", disk="")
    assert "storage_opt" not in run


# ─── the tunnel the backend uses to show a box's app ─────────────────────────

def _frame(kind: int, body: bytes) -> bytes:
    return bytes([kind, 0, 0, 0]) + struct.pack(">I", len(body)) + body


def _fake_exec(serve):
    """Stand in for docker exec: hand back one end of a socketpair and run `serve`
    on the other, which reads raw stdin and must write Docker-framed output."""
    calls = []

    def exec_socat(client, container, port):
        calls.append((container, port))
        ours, theirs = socket.socketpair()
        threading.Thread(target=serve, args=(theirs,), daemon=True).start()
        ours.setblocking(False)
        return ours, ours

    async def getter():
        return object()
    return exec_socat, getter, calls


def _http_app(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    body = b"<h1>hello from the box</h1>"
    head = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n")
    # split across frames, with a stderr frame in the middle that must be dropped
    sock.sendall(_frame(1, head) + _frame(2, b"socat: warning") + _frame(1, body[:5]) + _frame(1, body[5:]))
    sock.close()


def test_http_through_the_tunnel(monkeypatch):
    exec_socat, getter, calls = _fake_exec(_http_app)
    monkeypatch.setattr(box_tunnel, "_exec_socat", exec_socat)

    async def go():
        async with httpx.AsyncClient(transport=box_tunnel.transport(getter)) as c:
            return await c.get("http://harvis-vc-run-abc:7860/index.html")
    r = asyncio.run(go())
    assert r.status_code == 200 and r.text == "<h1>hello from the box</h1>"
    assert calls == [("harvis-vc-run-abc", 7860)]


def test_a_box_that_is_gone_is_a_connect_error(monkeypatch):
    def gone(client, container, port):
        raise NotFound("no such container")
    monkeypatch.setattr(box_tunnel, "_exec_socat", gone)

    async def getter():
        return object()

    async def go():
        async with httpx.AsyncClient(transport=box_tunnel.transport(getter)) as c:
            await c.get("http://harvis-vc-run-abc:7860/")
    with pytest.raises(httpx.ConnectError):
        asyncio.run(go())


def test_bad_ports_never_reach_docker(monkeypatch):
    monkeypatch.setattr(box_tunnel, "_exec_socat", lambda *a: pytest.fail("must not exec"))

    async def getter():
        return object()
    import httpcore
    for port in (0, 70000):
        with pytest.raises(httpcore.ConnectError):
            asyncio.run(box_tunnel.connect("harvis-vc-run-abc", port, getter))


def _echo(sock):
    while True:
        data = sock.recv(4096)
        if not data:
            break
        sock.sendall(_frame(1, data))
    sock.close()


def test_open_socket_carries_bytes_both_ways(monkeypatch):
    exec_socat, getter, _ = _fake_exec(_echo)
    monkeypatch.setattr(box_tunnel, "_exec_socat", exec_socat)

    async def go():
        sock, pump = await box_tunnel.open_socket("harvis-vc-run-abc", 7860, getter)
        reader, writer = await asyncio.open_connection(sock=sock)
        writer.write(b"GET /ws HTTP/1.1\r\n\r\n")
        await writer.drain()
        got = await asyncio.wait_for(reader.readexactly(20), 5)
        writer.close()
        await asyncio.wait_for(pump, 5)
        return got
    assert asyncio.run(go()) == b"GET /ws HTTP/1.1\r\n\r\n"


def test_the_app_proxy_uses_the_tunnel():
    from plugins.hermes_ui import rest_sandbox_apps as apps
    apps._client = None
    client = apps._http()
    try:
        assert isinstance(client._transport._pool._network_backend, box_tunnel._Backend)
    finally:
        asyncio.run(client.aclose())
        apps._client = None
