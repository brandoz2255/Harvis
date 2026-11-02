"""The Moonshot base URL is user input (``user_api_keys.api_url``), and the key is verified,
stored and then used for every Kimi call. On a shared host a non-admin's URL must only ever
be dialled at a public address; admins and local installs keep what they had. Nothing here
opens a socket: name resolution, the inner network backend and the official-platform client
are replaced."""
import asyncio
import os
import socket
import sys
from datetime import datetime
from types import SimpleNamespace

import httpcore
import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402  (imported before any test sets a shared exposure)
import moonshot_api  # noqa: E402
from owui_compat import cloud_chat  # noqa: E402
from plugins.hermes_ui import providers  # noqa: E402

PUBLIC_IP = "93.184.216.34"
SECRET = b'{"leak": "internal-secret-body"}'


def run(coro):
    return asyncio.run(coro)


def http_reply(status=200, body=b"{}"):
    return (f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body


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


@pytest.fixture
def dns(monkeypatch):
    """dns({"host": [["1.2.3.4"], ["10.0.0.1"]]}): a name that changes its answer; the last answer repeats."""
    def script(table):
        queues = {h: [list(a) for a in v] for h, v in table.items()}
        seen = []

        async def getaddrinfo(self, host, port, **_kwargs):
            seen.append(host)
            if host not in queues:
                raise socket.gaierror("no such name")
            q = queues[host]
            ips = q.pop(0) if len(q) > 1 else q[0]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
        return seen

    return script


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
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.streams = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        stream = FakeStream(self.reply)
        self.streams.append(stream)
        return stream

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@pytest.fixture
def net(monkeypatch):
    """The guarded transport dials a fake backend; the plain client (official platforms, admins,
    local installs) answers from ``plain`` instead of a socket."""
    state = SimpleNamespace(fake=FakeBackend(http_reply()), plain=[], plain_status=401, plain_body=b"{}")
    real_transport = providers.guarded_transport
    real_client = httpx.AsyncClient

    def transport(network_backend=None, vet=providers._require_global):
        return real_transport(state.fake, vet)

    def handler(request):
        state.plain.append(str(request.url))
        return httpx.Response(state.plain_status, content=state.plain_body)

    class Client(real_client):
        def __init__(self, *a, **k):
            k.setdefault("transport", httpx.MockTransport(handler))
            super().__init__(*a, **k)

    monkeypatch.setattr(providers, "guarded_transport", transport)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return state


def reply_with(net, status, body=b"{}"):
    net.fake.reply = http_reply(status, body)


# -- which client a base URL gets -----------------------------------------------

def _backend_of(client):
    return type(client._transport._pool._network_backend).__name__


def test_a_guarded_callers_custom_url_gets_the_connect_time_guard(shared):
    client = moonshot_api.moonshot_http_client("http://ollama:11434/v1", True)
    assert _backend_of(client) == "_GuardedBackend" and client.follow_redirects is False


def test_the_official_platforms_and_the_operators_url_keep_the_plain_client(shared, monkeypatch):
    for url in moonshot_api.MOONSHOT_PLATFORMS + (moonshot_api.MOONSHOT_BASE_URL,):
        assert _backend_of(moonshot_api.moonshot_http_client(url, True)) != "_GuardedBackend"


def test_admins_and_unguarded_callers_keep_the_plain_client_for_any_url(shared):
    assert _backend_of(moonshot_api.moonshot_http_client("http://10.0.0.5:8000/v1", False)) != "_GuardedBackend"


def test_a_caller_with_no_known_user_is_guarded_on_a_shared_host_and_not_locally(shared, monkeypatch):
    assert _backend_of(moonshot_api.moonshot_http_client("http://10.0.0.5/v1", None)) == "_GuardedBackend"
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    assert _backend_of(moonshot_api.moonshot_http_client("http://10.0.0.5/v1", None)) != "_GuardedBackend"


def test_user_guarded_follows_the_role_and_the_exposure(shared, monkeypatch):
    assert moonshot_api.user_guarded(7) is True
    assert moonshot_api.user_guarded(1) is False
    assert moonshot_api.user_guarded(None) is None
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    assert moonshot_api.user_guarded(7) is False


# -- verify at save time ------------------------------------------------------------

@pytest.mark.parametrize("url,name,ip", [
    ("http://ollama:11434/v1", "ollama", "172.18.0.3"),
    ("http://169.254.169.254/v1", "169.254.169.254", "169.254.169.254"),
    ("http://tailnet.example/v1", "tailnet.example", "100.100.1.1"),
    ("http://127.0.0.1:8000/v1", "127.0.0.1", "127.0.0.1"),
])
def test_verify_never_dials_a_private_custom_url_for_a_guarded_caller(shared, dns, net, url, name, ip):
    dns({name: [[ip]]})
    ok, base, err = run(moonshot_api.verify_moonshot_key("sk-test", url, guarded=True))
    assert ok is False and base == ""
    assert net.fake.calls == []
    assert not any(url in u for u in net.plain)


def test_verify_never_tells_a_guarded_caller_what_a_custom_server_answered(shared, dns, net):
    dns({"api.example": [[PUBLIC_IP]]})
    reply_with(net, 500, SECRET)
    ok, base, err = run(moonshot_api.verify_moonshot_key("sk-test", "https://api.example/v1", guarded=True))
    assert ok is False and "internal-secret-body" not in err and "500" in err
    assert net.fake.calls == [(PUBLIC_IP, 443)]


def test_verify_accepts_a_public_custom_url_for_a_guarded_caller(shared, dns, net):
    dns({"api.example": [[PUBLIC_IP]]})
    reply_with(net, 200)
    ok, base, err = run(moonshot_api.verify_moonshot_key("sk-test", "https://api.example/v1", guarded=True))
    assert (ok, base) == (True, "https://api.example/v1")


def test_verify_does_not_follow_a_redirect_into_the_private_network(shared, dns, net):
    dns({"api.example": [[PUBLIC_IP]]})
    net.fake.reply = (b"HTTP/1.1 302 Found\r\nLocation: http://10.0.0.5/v1/models\r\nContent-Length: 0\r\n\r\n")
    ok, base, err = run(moonshot_api.verify_moonshot_key("sk-test", "https://api.example/v1", guarded=True))
    assert ok is False and net.fake.calls == [(PUBLIC_IP, 443)]


def test_a_name_that_rebinds_to_a_private_address_after_the_check_is_not_dialled(shared, dns, net):
    dns({"rebind.example": [[PUBLIC_IP], ["10.0.0.5"]]})
    reply_with(net, 200)
    assert run(moonshot_api.verify_moonshot_key("sk-test", "https://rebind.example/v1", guarded=True))[0] is True
    assert net.fake.calls == [(PUBLIC_IP, 443)]
    ok, _base, _err = run(moonshot_api.verify_moonshot_key("sk-test", "https://rebind.example/v1", guarded=True))
    assert ok is False and net.fake.calls == [(PUBLIC_IP, 443)]


def test_verify_still_probes_the_official_platforms_for_a_guarded_caller(shared, net):
    net.plain_status = 200
    ok, base, _err = run(moonshot_api.verify_moonshot_key("sk-test", None, guarded=True))
    assert ok is True and base == moonshot_api.MOONSHOT_PLATFORMS[0]
    assert net.fake.calls == []


@pytest.mark.parametrize("guarded", [False, None])
def test_verify_for_admins_and_local_installs_dials_a_private_url_as_before(request, net, guarded):
    request.getfixturevalue("shared" if guarded is False else "local")
    net.plain_status = 200
    ok, base, _err = run(moonshot_api.verify_moonshot_key("sk-test", "http://192.168.1.50:8000/v1", guarded=guarded))
    assert ok is True and base == "http://192.168.1.50:8000/v1"
    assert net.plain == ["http://192.168.1.50:8000/v1/models"] and net.fake.calls == []


def test_an_admins_private_url_error_still_carries_the_upstream_text(shared, net):
    net.plain_status, net.plain_body = 500, b"upstream says boom"
    ok, _base, err = run(moonshot_api.verify_moonshot_key("sk-test", "http://192.168.1.50:8000/v1", guarded=False))
    assert ok is False and "upstream says boom" in err


# -- the save route ---------------------------------------------------------------------

class _Conn:
    def __init__(self):
        self.executed = []

    async def fetchrow(self, query, *args):
        if "RETURNING" in query:
            return {"id": 1, "provider_name": "moonshot", "api_url": args[3], "is_active": True,
                    "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1)}
        return None

    async def execute(self, query, *args):
        self.executed.append((query, args))


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def _save(user_id, api_url):
    pool = _Pool()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
    body = main.ApiKeyRequest(provider_name="moonshot", api_key="sk-test", api_url=api_url)
    user = SimpleNamespace(id=user_id, username="u", email="u@example.com")
    return pool, main.create_or_update_api_key(request, body, user)


@pytest.mark.parametrize("url", ["http://ollama:11434/v1", "http://169.254.169.254/v1", "http://10.0.0.5/v1", "http://100.64.1.1/v1"])
def test_saving_a_private_moonshot_url_is_refused_for_a_guarded_user(shared, dns, net, url):
    dns({"ollama": [["172.18.0.3"]]})
    pool, coro = _save(7, url)
    with pytest.raises(HTTPException) as excinfo:
        run(coro)
    assert excinfo.value.status_code == 400
    assert "172.18" not in str(excinfo.value.detail) and "ollama" not in str(excinfo.value.detail)
    assert net.fake.calls == [] and net.plain == [] and pool.conn.executed == []


def test_saving_a_private_moonshot_url_is_unchanged_for_admins(shared, net, monkeypatch):
    net.plain_status = 200
    monkeypatch.setattr("main.encrypt_api_key", lambda key: "enc", raising=False)
    pool, coro = _save(1, "http://192.168.1.50:8000/v1")
    saved = run(coro)
    assert saved.api_url == "http://192.168.1.50:8000/v1" and pool.conn.executed == []
    assert net.plain == ["http://192.168.1.50:8000/v1/models"]


# -- use time ---------------------------------------------------------------------------

def test_the_chat_client_refuses_a_private_stored_url_for_a_guarded_user(shared, dns, net):
    dns({"ollama": [["172.18.0.3"]]})
    client = moonshot_api.MoonshotClient("sk-test", "http://ollama:11434/v1", guarded=True)
    with pytest.raises(HTTPException) as excinfo:
        run(client.chat_completion("kimi-k2.5", [{"role": "user", "content": "hi"}]))
    assert excinfo.value.status_code == 400
    assert "172.18" not in str(excinfo.value.detail)
    assert net.fake.calls == []


def test_the_streaming_chat_client_refuses_a_private_stored_url_for_a_guarded_user(shared, dns, net):
    dns({"ollama": [["172.18.0.3"]]})
    client = moonshot_api.MoonshotClient("sk-test", "http://ollama:11434/v1", guarded=True)

    async def drain():
        return [c async for c in client.chat_completion_stream("kimi-k2.5", [{"role": "user", "content": "hi"}])]

    with pytest.raises(HTTPException) as excinfo:
        run(drain())
    assert excinfo.value.status_code == 400 and "172.18" not in str(excinfo.value.detail)
    assert net.fake.calls == []


def test_the_chat_client_sends_the_key_to_a_public_custom_url_for_a_guarded_user(shared, dns, net):
    dns({"api.example": [[PUBLIC_IP]]})
    reply_with(net, 200, b'{"choices":[{"message":{"content":"hello"}}]}')
    client = moonshot_api.MoonshotClient("sk-test", "https://api.example/v1", guarded=True)
    assert run(client.chat_completion("kimi-k2.5", [{"role": "user", "content": "hi"}])) == "hello"
    assert net.fake.calls == [(PUBLIC_IP, 443)]


def test_the_chat_client_is_unchanged_for_admins(shared, net):
    net.plain_status, net.plain_body = 200, b'{"choices":[{"message":{"content":"hello"}}]}'
    client = moonshot_api.MoonshotClient("sk-test", "http://192.168.1.50:8000/v1", guarded=False)
    assert run(client.chat_completion("kimi-k2.5", [{"role": "user", "content": "hi"}])) == "hello"
    assert net.plain == ["http://192.168.1.50:8000/v1/chat/completions"] and net.fake.calls == []


def test_a_client_built_without_a_user_is_guarded_on_a_shared_host(shared, dns, net):
    dns({"ollama": [["172.18.0.3"]]})
    client = moonshot_api.get_moonshot_client("sk-test", "http://ollama:11434/v1")
    with pytest.raises(HTTPException):
        run(client.chat_completion("kimi-k2.5", [{"role": "user", "content": "hi"}]))
    assert net.fake.calls == []


# -- the OpenAI-compatible proxy ---------------------------------------------------------

def test_the_chat_proxy_refuses_a_private_url_for_a_guarded_user(shared, dns, net):
    dns({"ollama": [["172.18.0.3"]]})
    out = run(cloud_chat._proxy_moonshot_api(
        {"messages": [{"role": "user", "content": "hi"}]}, "moonshot/kimi-k2.5", "sk-test",
        "http://ollama:11434/v1", True))
    assert out.status_code == 400 and b"172.18" not in out.body and net.fake.calls == []


def test_the_streaming_chat_proxy_refuses_a_private_url_for_a_guarded_user(shared, dns, net):
    dns({"ollama": [["172.18.0.3"]]})
    out = run(cloud_chat._proxy_moonshot_api(
        {"stream": True, "messages": [{"role": "user", "content": "hi"}]}, "moonshot/kimi-k2.5", "sk-test",
        "http://ollama:11434/v1", True))

    async def drain():
        return b"".join([c async for c in out.body_iterator])

    assert b"172.18" not in run(drain()) and net.fake.calls == []


def test_the_chat_proxy_uses_a_public_custom_url_for_a_guarded_user_and_a_private_one_for_an_admin(shared, dns, net):
    dns({"api.example": [[PUBLIC_IP]]})
    reply_with(net, 200, b'{"choices":[]}')
    msg = {"messages": [{"role": "user", "content": "hi"}]}
    out = run(cloud_chat._proxy_moonshot_api(msg, "moonshot/kimi-k2.5", "sk-test", "https://api.example/v1", True))
    assert out.status_code == 200 and net.fake.calls == [(PUBLIC_IP, 443)]
    net.plain_status, net.plain_body = 200, b'{"choices":[]}'
    out = run(cloud_chat._proxy_moonshot_api(msg, "moonshot/kimi-k2.5", "sk-test", "http://192.168.1.50:8000/v1", False))
    assert out.status_code == 200 and net.plain == ["http://192.168.1.50:8000/v1/chat/completions"]


def test_the_workspace_route_carries_the_users_base_url_and_guard_flag(shared):
    from workspace.orchestration import provider_route

    fields = {f for f in getattr(provider_route.ToolRoute, "__dataclass_fields__", {})}
    assert {"base_url", "guarded"} <= fields


# -- what a chat error tells a guarded caller about the endpoint ---------------------------

PROXY = "http://moonshot-proxy.internal:8080/v1"


def _chat_error(client, stream=False):
    async def call():
        if stream:
            return [c async for c in client.chat_completion_stream("kimi-k2.5", [{"role": "user", "content": "hi"}])]
        return await client.chat_completion("kimi-k2.5", [{"role": "user", "content": "hi"}])

    with pytest.raises(HTTPException) as excinfo:
        run(call())
    return excinfo.value


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", [401, 500])
def test_a_guarded_user_never_sees_the_operators_proxy_in_a_chat_error(shared, net, monkeypatch, stream, status):
    monkeypatch.setattr(moonshot_api, "MOONSHOT_BASE_URL", PROXY)
    net.plain_status, net.plain_body = status, SECRET
    err = _chat_error(moonshot_api.MoonshotClient("sk-test", PROXY, guarded=True), stream)
    assert "moonshot-proxy" not in str(err.detail) and "internal-secret-body" not in str(err.detail)
    assert str(status) in str(err.detail)


def test_an_admin_still_gets_the_full_moonshot_error(shared, net, monkeypatch):
    monkeypatch.setattr(moonshot_api, "MOONSHOT_BASE_URL", PROXY)
    net.plain_status = 401
    err = _chat_error(moonshot_api.MoonshotClient("sk-test", PROXY, guarded=False))
    assert "moonshot-proxy" in str(err.detail)


def test_a_guarded_user_on_moonshots_own_platform_keeps_the_helpful_401(shared, net):
    net.plain_status = 401
    err = _chat_error(moonshot_api.MoonshotClient("sk-test", "https://api.moonshot.ai/v1", guarded=True))
    assert "other console" in str(err.detail) or "separate platforms" in str(err.detail)
