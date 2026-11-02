"""MCP-adjacent places where a user's URL could make the server send bytes to a private
address on a shared host: the wizard's connection test, the MCP client's address check, and
the media mirror. Nothing here opens a socket: name resolution, the inner network backend and
the plain client are replaced."""
import asyncio
import importlib
import os
import socket
import sys
from types import SimpleNamespace

import httpcore
import httpx
import pytest
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat import mcp_wizard  # noqa: E402
from plugins.hermes_ui import providers  # noqa: E402
from plugins.mcp import http_transport, media_capture  # noqa: E402
from plugins.mcp.protocol import McpError  # noqa: E402

PUBLIC_IP = "93.184.216.34"
ADMIN = SimpleNamespace(id=1)
USER = SimpleNamespace(id=7)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


# -- the MCP client's address check --------------------------------------------------

@pytest.mark.parametrize("ip", [
    "100.64.0.1", "100.100.1.1", "100.127.255.254",            # Tailscale / shared address space
    "::ffff:10.0.0.1", "::ffff:100.64.0.1", "::ffff:127.0.0.1", "::ffff:192.168.1.1",   # IPv4 in an IPv6 coat
    "10.0.0.1", "172.18.0.2", "192.168.1.1", "127.0.0.1", "::1", "fd00::1", "0.0.0.0", "224.0.0.1",
    "fe80::1%eth0", "not-an-address", "",
])
def test_non_public_addresses_are_refused_by_default(shared, ip):
    assert http_transport._classify(ip) is not None


@pytest.mark.parametrize("ip", ["169.254.169.254", "::ffff:169.254.169.254", "fe80::1", "fe80::1%eth0"])
@pytest.mark.parametrize("flag", [None, "1"])
def test_link_local_and_metadata_addresses_are_refused_even_with_the_flag(shared, monkeypatch, ip, flag):
    if flag:
        monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", flag)
    assert "never allowed" in http_transport._classify(ip)


@pytest.mark.parametrize("ip", ["100.64.0.1", "::ffff:100.64.0.1", "10.0.0.1", "192.168.1.1", "127.0.0.1", "::ffff:10.0.0.1"])
def test_the_operator_flag_still_opens_private_and_tailnet_addresses(shared, monkeypatch, ip):
    monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "1")
    assert http_transport._classify(ip) is None


@pytest.mark.parametrize("ip", [PUBLIC_IP, "2606:4700:4700::1111", "::ffff:93.184.216.34", "151.101.1.69"])
def test_public_addresses_pass(shared, ip):
    assert http_transport._classify(ip) is None


def test_the_connect_time_vet_refuses_a_tailnet_address(shared):
    with pytest.raises(McpError):
        http_transport._vet_address(__import__("ipaddress").ip_address("100.64.0.9"))


def test_an_mcp_url_that_resolves_to_the_tailnet_is_refused_without_the_flag(shared, monkeypatch):
    monkeypatch.setattr(http_transport.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", ("100.64.0.9", port))])
    with pytest.raises(McpError):
        run(http_transport.guard_url_async("http://tailnet.example/mcp"))
    monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "1")
    run(http_transport.guard_url_async("http://tailnet.example/mcp"))


# -- the operator flag is not for strangers ----------------------------------------------

@pytest.mark.parametrize("ip", ["100.64.0.9", "10.0.0.1", "127.0.0.1", "192.168.1.1", "::ffff:10.0.0.1"])
def test_the_operator_flag_never_opens_private_addresses_to_a_strict_caller(shared, monkeypatch, ip):
    monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "1")
    assert http_transport._classify(ip) is None
    assert http_transport._classify(ip, strict=True) is not None
    with pytest.raises(McpError):
        http_transport._vet_address_strict(__import__("ipaddress").ip_address(ip.replace("::ffff:", "")))


def test_strict_applies_to_a_non_admin_on_a_shared_host_only(shared, local, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert http_transport.strict_for(7) is True
    assert http_transport.strict_for(1) is False
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    assert http_transport.strict_for(7) is False


def test_a_strict_save_refuses_a_private_name_even_with_the_flag(shared, monkeypatch):
    monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setattr(http_transport.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", ("172.18.0.2", port))])
    with pytest.raises(McpError):
        run(http_transport.guard_url_async("http://ollama:11434/mcp", True))
    run(http_transport.guard_url_async("http://ollama:11434/mcp", False))


def test_a_strict_refusal_does_not_tell_an_existing_internal_name_from_a_missing_one(shared, monkeypatch):
    def getaddrinfo(host, port, *a, **k):
        if host == "pgsql":
            return [(2, 1, 6, "", ("172.18.0.2", port))]
        raise socket.gaierror("no such name")

    monkeypatch.setattr(http_transport.socket, "getaddrinfo", getaddrinfo)
    texts = set()
    for host in ("pgsql", "nope-xyz", "169.254.169.254"):
        with pytest.raises(McpError) as excinfo:
            run(http_transport.guard_url_async(f"http://{host}/mcp", True))
        texts.add(str(excinfo.value))
    assert len(texts) == 1 and "pgsql" not in texts.copy().pop() and "172.18" not in texts.copy().pop()


def test_an_admin_keeps_the_detailed_refusal_text(shared, monkeypatch):
    monkeypatch.setattr(http_transport.socket, "getaddrinfo", lambda host, port, *a, **k: [(2, 1, 6, "", ("172.18.0.2", port))])
    with pytest.raises(McpError, match="pgsql"):
        run(http_transport.guard_url_async("http://pgsql/mcp"))


def test_a_strict_session_gets_a_strict_transport_and_the_runtime_derives_it_from_the_user(shared):
    session = http_transport.HttpMcpSession("https://public.example/mcp", strict=True)
    try:
        assert session._client._transport._strict is True
    finally:
        run(session.close())
    assert http_transport.HttpMcpSession("https://public.example/mcp")._client._transport._strict is False


def test_the_oauth_flow_uses_the_strict_client_for_a_non_admin(shared, monkeypatch):
    from plugins.mcp import oauth_discovery as disc

    seen = []
    monkeypatch.setattr(disc, "_client", lambda strict=False: (seen.append(strict), http_transport.guarded_client(strict=strict))[1])
    with pytest.raises(Exception):
        run(disc.register_client({"registration_endpoint": "http://pgsql:5432/r", "issuer": "x"}, "http://h/cb", strict=True))
    assert seen == [True]


# -- the wizard's connection test ----------------------------------------------------

class FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self, reply):
        self.reply = reply
        self.sent = bytearray()

    async def read(self, max_bytes, timeout=None):
        data, self.reply = self.reply[:max_bytes], self.reply[max_bytes:]
        return data

    async def write(self, buffer, timeout=None):
        self.sent += buffer

    async def aclose(self):
        pass

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None


class FakeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, reply=b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"):
        self.reply = reply
        self.calls = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        return FakeStream(self.reply)

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@pytest.fixture
def dns(monkeypatch):
    def script(table):
        queues = {h: [list(a) for a in v] for h, v in table.items()}

        async def getaddrinfo(self, host, port, **_kwargs):
            if host not in queues:
                raise socket.gaierror("no such name")
            q = queues[host]
            ips = q.pop(0) if len(q) > 1 else q[0]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)

    return script


@pytest.fixture
def net(monkeypatch):
    """The guarded client dials a fake backend; the plain client answers from ``plain``."""
    state = SimpleNamespace(fake=FakeBackend(), plain=[])
    real_transport = providers.guarded_transport
    real_client = httpx.AsyncClient

    def handler(request):
        state.plain.append(str(request.url))
        return httpx.Response(200)

    class Client(real_client):
        def __init__(self, *a, **k):
            k.setdefault("transport", httpx.MockTransport(handler))
            super().__init__(*a, **k)

    monkeypatch.setattr(providers, "guarded_transport",
                        lambda network_backend=None, vet=providers._require_global: real_transport(state.fake, vet))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return state


@pytest.fixture
def mcp_test():
    router = APIRouter()
    mcp_wizard.register_mcp_wizard_routes(router, lambda: None)
    endpoint = next(r.endpoint for r in router.routes if getattr(r, "path", "") == "/api/owui/mcp/test")

    def call(user, url):
        return run(endpoint(mcp_wizard.McpTestBody(url=url, transport="http"), SimpleNamespace(app=None), user))

    return call


@pytest.mark.parametrize("url", [
    "http://ollama:11434/", "http://pgsql:5432/", "http://backend:8000/api/users", "http://openclaw:18789/",
    "http://127.0.0.1:8000/", "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.9/", "http://100.100.1.1:8080/mcp", "http://[::ffff:10.0.0.1]/", "http://[::1]/", "http://localhost:8000/",
    "http://printer/", "http://nas.local/", "http://unresolvable.example/",
])
def test_a_guarded_user_cannot_probe_the_private_network_through_the_wizard(shared, dns, net, mcp_test, url):
    dns({})
    with pytest.raises(HTTPException) as excinfo:
        mcp_test(USER, url)
    assert excinfo.value.status_code == 400
    assert net.fake.calls == [] and net.plain == []


def test_the_refusal_names_no_internal_address(shared, dns, net, mcp_test):
    dns({"corp.example": [["10.9.8.7"]]})
    with pytest.raises(HTTPException) as excinfo:
        mcp_test(USER, "http://corp.example/")
    assert "10.9.8.7" not in str(excinfo.value.detail)


def test_a_guarded_user_reaches_a_public_server_through_the_connect_guard(shared, dns, net, mcp_test):
    dns({"mcp.example": [[PUBLIC_IP]]})
    out = mcp_test(USER, "http://mcp.example/mcp")
    assert out["ok"] is True
    assert net.fake.calls == [(PUBLIC_IP, 80)] and net.plain == []


def test_a_name_that_rebinds_after_the_wizards_check_is_not_dialled(shared, dns, net, mcp_test):
    dns({"rebind.example": [[PUBLIC_IP], ["10.0.0.5"]]})
    out = mcp_test(USER, "http://rebind.example/mcp")
    assert out["ok"] is False and "Blocked" in out["detail"] and "10.0.0.5" not in out["detail"]
    assert net.fake.calls == [] and net.plain == []


def test_a_public_server_that_redirects_inward_is_not_followed(shared, dns, net, mcp_test):
    dns({"mcp.example": [[PUBLIC_IP]]})
    net.fake.reply = b"HTTP/1.1 302 Found\r\nLocation: http://10.0.0.5/\r\nContent-Length: 0\r\n\r\n"
    out = mcp_test(USER, "http://mcp.example/mcp")
    assert out["status"] == 302 and net.fake.calls == [(PUBLIC_IP, 80)]


def test_admins_keep_the_internal_service_exemption_on_a_shared_host(shared, net, mcp_test):
    out = mcp_test(ADMIN, "http://ollama:11434/")
    assert out["ok"] is True and net.plain == ["http://ollama:11434/"] and net.fake.calls == []


def test_admins_still_cannot_probe_a_loopback_literal(shared, net, mcp_test):
    with pytest.raises(HTTPException):
        mcp_test(ADMIN, "http://127.0.0.1:8000/")
    assert net.plain == []


def test_a_local_install_keeps_the_internal_service_exemption_for_every_user(local, net, mcp_test):
    out = mcp_test(USER, "http://ollama:11434/")
    assert out["ok"] is True and net.plain == ["http://ollama:11434/"] and net.fake.calls == []


# -- the media mirror ---------------------------------------------------------------

@pytest.fixture
def mirror(monkeypatch):
    fetched, saved = [], []

    async def fetch(url, name):
        fetched.append(url)
        return b"\x89PNG bytes"

    async def save(pool, workspace_id, kind, path=None, content_bytes=None):
        saved.append((workspace_id, path))
        return "art-1"

    async def emit(*a, **k):
        return None

    monkeypatch.setattr(media_capture, "_fetch", fetch)
    # `workspace.workspace_router` is also an attribute of the package (an APIRouter), so fetch the module itself
    monkeypatch.setattr(importlib.import_module("workspace.workspace_router"), "_db_save_artifact", save)
    monkeypatch.setattr(importlib.import_module("workspace.terminal_container"), "emit_terminal_event", emit)
    return SimpleNamespace(fetched=fetched, saved=saved)


TEXT = "Here you go: http://pgsql:5432/secret.png and http://169.254.169.254/latest/x.png"


def test_a_guarded_users_mcp_result_is_never_mirrored(shared, mirror):
    text, saved = run(media_capture.mirror_media_urls(TEXT, pool=object(), workspace_id="w1", user_id=7))
    assert (text, saved) == (TEXT, []) and mirror.fetched == [] and mirror.saved == []


def test_a_call_with_no_known_user_is_not_mirrored_on_a_shared_host(shared, mirror):
    text, saved = run(media_capture.mirror_media_urls(TEXT, pool=object(), workspace_id="w1"))
    assert saved == [] and mirror.fetched == []


def test_an_admins_mcp_result_is_still_mirrored_on_a_shared_host(shared, mirror):
    text, saved = run(media_capture.mirror_media_urls(TEXT, pool=object(), workspace_id="w1", user_id=1))
    assert saved and mirror.fetched and mirror.saved[0][0] == "w1"
    assert "/api/workspace/artifact/art-1/raw" in text


def test_a_local_install_still_mirrors_for_every_user(local, mirror):
    _text, saved = run(media_capture.mirror_media_urls(TEXT, pool=object(), workspace_id="w1", user_id=7))
    assert saved and mirror.fetched
    _text, saved = run(media_capture.mirror_media_urls(TEXT, pool=object(), workspace_id="w1"))
    assert saved


def test_both_mcp_callers_pass_the_user_to_the_mirror():
    import inspect

    from plugins.mcp import sidecar_bridge, tool_bridge

    for mod in (tool_bridge, sidecar_bridge):
        source = inspect.getsource(mod)
        call = source[source.index("mirror_media_urls("):]
        assert "user_id" in call[:400], mod.__name__
