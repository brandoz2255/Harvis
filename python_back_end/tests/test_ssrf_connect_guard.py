"""The SSRF guard that runs at connect time, and the external-Hermes routes that use it.

``refuse_private_url`` resolves a name once and httpx resolves it again to connect, so a
name that answers public and then private used to deliver the request to an internal host.
The guard resolves the name itself and dials the address it vetted. Nothing here opens a
socket: getaddrinfo and the inner network backend are replaced."""
import asyncio
import os
import socket
import sys
from types import SimpleNamespace

import httpcore
import httpx
import pytest
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat import hermes_chat, hermes_connect  # noqa: E402
from plugins.hermes_ui import providers  # noqa: E402
from plugins.hermes_ui.providers import EndpointValidationError  # noqa: E402

ADMIN = SimpleNamespace(id=1)
USER = SimpleNamespace(id=7)
PUBLIC_IP = "93.184.216.34"
OK = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"


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


def _info(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, 0))


@pytest.fixture
def dns(monkeypatch):
    """dns(["1.2.3.4"], ["10.0.0.1"]) answers the first lookup, then the second; the last repeats."""
    def script(*answers):
        queue = list(answers)
        seen = []

        async def getaddrinfo(self, host, port, **_kwargs):
            seen.append(host)
            ips = queue.pop(0) if len(queue) > 1 else queue[0]
            return [_info(ip) for ip in ips]

        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
        return seen

    return script


class FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self, reply):
        self.reply = reply
        self.sent = bytearray()
        self.tls_hostname = None

    async def read(self, max_bytes, timeout=None):
        data, self.reply = self.reply[:max_bytes], self.reply[max_bytes:]
        return data

    async def write(self, buffer, timeout=None):
        self.sent += buffer

    async def aclose(self):
        pass

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_hostname = server_hostname
        return self

    def get_extra_info(self, info):
        return None


class FakeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, reply=OK, fail_first=0):
        self.reply = reply
        self.fail_first = fail_first
        self.calls = []
        self.streams = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        if len(self.calls) <= self.fail_first:
            raise httpcore.ConnectError("refused")
        stream = FakeStream(self.reply)
        self.streams.append(stream)
        return stream

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


def _client(backend, **kwargs):
    return httpx.AsyncClient(transport=providers.guarded_transport(backend), trust_env=False, **kwargs)


# -- the backend ---------------------------------------------------------------

@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.1.5", "169.254.169.254",
                                "::ffff:127.0.0.1", "::ffff:10.0.0.1", "100.64.0.1", "::1", "fd00::1"])
def test_the_backend_refuses_a_name_that_resolves_to_a_private_address(dns, ip):
    dns([ip])
    inner = FakeBackend()
    with pytest.raises(EndpointValidationError, match="not allowed on a shared server"):
        run(providers._GuardedBackend(inner).connect_tcp("evil.example.com", 80))
    assert inner.calls == []


def test_the_backend_refuses_when_any_answer_is_private(dns):
    dns([PUBLIC_IP, "10.0.0.5"])
    inner = FakeBackend()
    with pytest.raises(EndpointValidationError):
        run(providers._GuardedBackend(inner).connect_tcp("mixed.example.com", 80))
    assert inner.calls == []


def test_the_backend_refuses_a_private_ip_literal(dns):
    dns(["10.0.0.5"])
    inner = FakeBackend()
    with pytest.raises(EndpointValidationError):
        run(providers._GuardedBackend(inner).connect_tcp("10.0.0.5", 80))
    assert inner.calls == []


def test_the_backend_connects_with_the_vetted_ip_not_the_name(dns):
    dns([PUBLIC_IP])
    inner = FakeBackend()
    stream = run(providers._GuardedBackend(inner).connect_tcp("api.example.com", 443))
    assert inner.calls == [(PUBLIC_IP, 443)]
    assert stream is inner.streams[0]


def test_the_backend_tries_the_next_vetted_address_when_one_will_not_connect(dns):
    dns(["2606:2800:220:1:248:1893:25c8:1946", PUBLIC_IP])
    inner = FakeBackend(fail_first=1)
    run(providers._GuardedBackend(inner).connect_tcp("api.example.com", 80))
    assert [host for host, _ in inner.calls] == ["2606:2800:220:1:248:1893:25c8:1946", PUBLIC_IP]


def test_the_backend_reports_an_unresolvable_name_as_a_connect_error(monkeypatch):
    async def getaddrinfo(self, host, port, **_kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)
    with pytest.raises(httpcore.ConnectError):
        run(providers._GuardedBackend(FakeBackend()).connect_tcp("nope.example.com", 80))


def test_the_backend_refuses_unix_sockets():
    with pytest.raises(EndpointValidationError):
        run(providers._GuardedBackend(FakeBackend()).connect_unix_socket("/var/run/docker.sock"))


# -- through a real httpx client ------------------------------------------------

def test_a_name_that_rebinds_between_the_check_and_the_connect_sends_nothing(shared, dns):
    seen = dns([PUBLIC_IP], ["10.0.0.5"])  # 1st lookup: refuse_private_url; 2nd: the connect
    inner = FakeBackend()

    async def scenario():
        await providers.refuse_private_url("http://rebind.example.com/v1")
        async with _client(inner) as client:
            await client.post("http://rebind.example.com/v1/chat/completions", json={"secret": "body"})

    with pytest.raises(EndpointValidationError):
        run(scenario())
    assert len(seen) == 2
    assert inner.calls == [] and inner.streams == []


def test_a_public_answer_is_delivered_to_the_vetted_address(dns):
    dns([PUBLIC_IP])
    inner = FakeBackend()

    async def scenario():
        async with _client(inner) as client:
            return await client.get("http://api.example.com/v1/models")

    assert run(scenario()).status_code == 200
    assert inner.calls == [(PUBLIC_IP, 80)]
    assert b"Host: api.example.com" in bytes(inner.streams[0].sent)


def test_tls_is_still_verified_against_the_name_not_the_address(dns):
    dns([PUBLIC_IP])
    inner = FakeBackend()

    async def scenario():
        async with _client(inner) as client:
            await client.get("https://api.example.com/v1/models")

    run(scenario())
    assert inner.calls == [(PUBLIC_IP, 443)]
    assert inner.streams[0].tls_hostname == "api.example.com"


def test_guarded_clients_ignore_proxy_environment_and_do_not_follow_redirects(monkeypatch, dns):
    monkeypatch.setenv("HTTP_PROXY", "http://10.0.0.9:3128")
    monkeypatch.setenv("http_proxy", "http://10.0.0.9:3128")
    dns([PUBLIC_IP])
    inner = FakeBackend(reply=b"HTTP/1.1 302 Found\r\nLocation: http://10.0.0.5/admin\r\nContent-Length: 0\r\n\r\n")
    make = providers.guarded_transport
    monkeypatch.setattr(providers, "guarded_transport", lambda: make(inner))

    async def scenario():
        async with providers.guarded_client(timeout=5.0) as client:
            assert client.trust_env is False and client.follow_redirects is False
            return await client.get("http://api.example.com/v1/models")

    assert run(scenario()).status_code == 302
    assert inner.calls == [(PUBLIC_IP, 80)]  # not the proxy, and the redirect target was never dialled


# -- the private attribute the guard depends on ----------------------------------

def test_httpx_still_keeps_its_network_backend_where_the_guard_expects_it():
    """guarded_transport() sets httpx's pool backend through a private attribute. If a
    dependency bump moves it this fails here, not silently in production."""
    pool = httpx.AsyncHTTPTransport()._pool
    assert isinstance(pool._network_backend, httpcore.AsyncNetworkBackend)
    assert isinstance(providers.guarded_transport()._pool._network_backend, providers._GuardedBackend)


def test_guarded_transport_fails_loudly_when_the_attribute_is_gone(monkeypatch):
    class Bare:
        _pool = object()

    monkeypatch.setattr(providers.httpx, "AsyncHTTPTransport", Bare)
    with pytest.raises(RuntimeError, match="SSRF guard"):
        providers.guarded_transport()


# -- external Hermes: save, verify, dispatch --------------------------------------

PRIVATE_URLS = ["http://ollama:11434", "http://127.0.0.1:8642", "http://10.0.0.5/admin?",
                "http://10.0.0.5/admin?x=1", "http://100.64.0.1:8642", "http://169.254.169.254"]
PUBLIC_URL = f"http://{PUBLIC_IP}:8642"


class _NoClient:
    def __init__(self, *args, **kwargs):
        raise AssertionError("no connection may be opened")


@pytest.fixture
def stored(monkeypatch):
    rows = {}

    async def read_raw(pool, user_id):
        return dict(rows.get(int(user_id), {}))

    async def write_raw(pool, user_id, value):
        if value is None:
            rows.pop(int(user_id), None)
        else:
            rows[int(user_id)] = dict(value)

    monkeypatch.setattr(hermes_connect, "_read_raw", read_raw)
    monkeypatch.setattr(hermes_connect, "_write_raw", write_raw)
    monkeypatch.setattr(hermes_connect, "_enc", lambda v: "enc(" + v + ")")
    monkeypatch.setattr(hermes_connect, "_dec", lambda v: v[4:-1])
    return rows


def _routes():
    router = APIRouter()
    hermes_connect.register_hermes_connect_routes(router, lambda: None)
    return {r.path.rsplit("/", 1)[-1]: r.endpoint for r in router.routes if "POST" in r.methods}


def _request(body=None):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))

    async def json():
        return body or {}

    request.json = json
    return request


def _save(user, url):
    return run(_routes()["hermes-external"](_request({"url": url}), user))


@pytest.mark.parametrize("url", PRIVATE_URLS + ["http://u:p@93.184.216.34/", f"{PUBLIC_URL}/?k=v", f"{PUBLIC_URL}/#x"])
def test_saving_a_private_or_unplain_hermes_url_is_refused_for_a_guarded_user(shared, stored, url):
    with pytest.raises(HTTPException) as info:
        _save(USER, url)
    assert info.value.status_code == 400
    assert stored == {}


def test_a_guarded_user_may_save_a_plain_public_hermes_url(shared, stored):
    assert _save(USER, PUBLIC_URL)["url"] == PUBLIC_URL
    assert stored[7]["url"] == PUBLIC_URL


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_admins_keep_private_hermes_urls_on_a_shared_host(shared, stored, url):
    assert _save(ADMIN, url)["url"] == url


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_a_local_install_keeps_private_hermes_urls_for_every_user(local, stored, url):
    assert _save(USER, url)["url"] == url


class _Reply:
    status_code = 200


def _recording_client(calls, label):
    class Client:
        def __init__(self, **kwargs):
            calls.append((label, kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, headers=None):
            calls.append(("get", url))
            return _Reply()

    return Client


def test_verify_refuses_a_stored_private_url_for_a_guarded_user_without_connecting(shared, stored, monkeypatch):
    stored[7] = {"url": "http://ollama:11434", "verified_at": None}  # saved before the rule existed
    monkeypatch.setattr(hermes_connect.httpx, "AsyncClient", _NoClient)
    result = run(_routes()["verify"](_request(), USER))
    assert result["ok"] is False and "not allowed on a shared server" in result["error"]
    assert stored[7]["verified_at"] is None


def test_verify_uses_the_guarded_client_and_no_redirects_for_a_guarded_user(shared, stored, monkeypatch):
    calls = []
    stored[7] = {"url": PUBLIC_URL, "verified_at": None}
    monkeypatch.setattr(hermes_connect.httpx, "AsyncClient", _NoClient)
    monkeypatch.setattr(providers, "guarded_client", _recording_client(calls, "guarded"))
    result = run(_routes()["verify"](_request(), USER))
    assert result["ok"] is True and result["connected"] is True
    assert calls[0] == ("guarded", {"timeout": 8.0})


@pytest.mark.parametrize("fixture_name,user", [("shared", ADMIN), ("local", USER)])
def test_verify_is_unchanged_for_admins_and_local_installs(request, stored, monkeypatch, fixture_name, user):
    request.getfixturevalue(fixture_name)
    calls = []
    stored[user.id] = {"url": "http://10.0.0.5:8642", "verified_at": None}
    monkeypatch.setattr(hermes_connect.httpx, "AsyncClient", _recording_client(calls, "plain"))
    monkeypatch.setattr(providers, "guarded_client", _NoClient)
    result = run(_routes()["verify"](_request(), user))
    assert result["ok"] is True
    assert calls[0] == ("plain", {"timeout": 8.0, "follow_redirects": True})
    assert calls[1] == ("get", "http://10.0.0.5:8642/v1/models")


def test_probe_reports_a_connect_time_refusal_without_falling_back_to_health(shared, monkeypatch, dns):
    dns([PUBLIC_IP], ["10.0.0.5"])  # public for the early check, private for the connect
    inner = FakeBackend()
    make = providers.guarded_transport
    monkeypatch.setattr(providers, "guarded_transport", lambda: make(inner))
    result = run(hermes_connect._probe("http://rebind.example.com", None, guarded=True))
    assert result["ok"] is False and "not allowed on a shared server" in result["error"]
    assert inner.calls == []


@pytest.mark.parametrize("path", ["/v1/models", "/health"])
def test_probe_does_not_count_a_redirect_as_a_verified_key_for_a_guarded_user(shared, monkeypatch, dns, path):
    dns([PUBLIC_IP])
    reply = b"HTTP/1.1 302 Found\r\nLocation: http://10.0.0.5/\r\nContent-Length: 0\r\n\r\n"

    class Backend(FakeBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            if path == "/health" and not self.calls:  # /v1/models cannot be reached at all
                self.calls.append((host, port))
                raise httpcore.ConnectError("refused")
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)

    inner = Backend(reply=reply)
    make = providers.guarded_transport
    monkeypatch.setattr(providers, "guarded_transport", lambda: make(inner))
    result = run(hermes_connect._probe("http://api.example.com", "token", guarded=True))
    assert result == {"ok": False, "error": hermes_connect._REDIRECT_ERROR}
    assert all(host == PUBLIC_IP for host, _ in inner.calls)  # the redirect target was never dialled


def _proxy(user_id, stream=False):
    return run(hermes_chat.proxy_hermes_chat({"messages": [], "stream": stream}, object(), user_id))


@pytest.fixture
def hermes_model(monkeypatch):
    async def model(pool, user_id):
        return "m"

    monkeypatch.setattr(hermes_chat, "resolve_hermes_model", model)


def test_dispatch_rechecks_a_stored_private_url_for_a_guarded_user(shared, stored, hermes_model, monkeypatch):
    stored[7] = {"url": "http://ollama:11434", "verified_at": 1}
    monkeypatch.setattr(hermes_chat.httpx, "AsyncClient", _NoClient)
    monkeypatch.setattr(hermes_chat, "guarded_client", _NoClient)
    with pytest.raises(EndpointValidationError):
        run(hermes_connect.resolve_external_target(object(), 7))
    response = _proxy(7)
    assert response.status_code == 400
    assert b"not allowed on a shared server" in response.body


def test_dispatch_refusal_streams_an_error_instead_of_the_sidecar(shared, stored, hermes_model, monkeypatch):
    stored[7] = {"url": "http://10.0.0.5/admin?", "verified_at": 1}
    monkeypatch.setattr(hermes_chat.httpx, "AsyncClient", _NoClient)
    monkeypatch.setattr(hermes_chat, "guarded_client", _NoClient)
    response = _proxy(7, stream=True)

    async def drain():
        return b"".join([c async for c in response.body_iterator])

    assert b"not allowed on a shared server" in run(drain())


class _JsonReply:
    status_code = 200

    def json(self):
        return {"ok": True}


def _post_client(calls, label):
    class Client:
        def __init__(self, **kwargs):
            calls.append((label, kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append(("post", url))
            return _JsonReply()

    return Client


def test_dispatch_uses_the_guarded_client_for_a_guarded_user(shared, stored, hermes_model, monkeypatch):
    calls = []
    stored[7] = {"url": PUBLIC_URL, "verified_at": 1, "token_enc": "enc(tok)"}
    monkeypatch.setattr(hermes_chat.httpx, "AsyncClient", _NoClient)
    monkeypatch.setattr(hermes_chat, "guarded_client", _post_client(calls, "guarded"))
    assert _proxy(7).status_code == 200
    assert calls == [("guarded", {"timeout": 180.0}), ("post", f"{PUBLIC_URL}/v1/chat/completions")]


@pytest.mark.parametrize("fixture_name,user_id", [("shared", 1), ("local", 7)])
def test_dispatch_is_unchanged_for_admins_and_local_installs(request, stored, hermes_model, monkeypatch,
                                                              fixture_name, user_id):
    request.getfixturevalue(fixture_name)
    calls = []
    stored[user_id] = {"url": "http://10.0.0.5:8642", "verified_at": 1}
    monkeypatch.setattr(hermes_chat.httpx, "AsyncClient", _post_client(calls, "plain"))
    monkeypatch.setattr(hermes_chat, "guarded_client", _NoClient)
    assert _proxy(user_id).status_code == 200
    assert calls == [("plain", {"timeout": 180.0}), ("post", "http://10.0.0.5:8642/v1/chat/completions")]


# -- cookbook error text ------------------------------------------------------------

def test_cookbook_pull_error_does_not_name_the_ollama_address(monkeypatch):
    from cookbook import client

    class Boom:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("could not reach http://10.9.8.7:11434")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(client.httpx, "AsyncClient", Boom)

    async def drain():
        return "".join([c async for c in client.ollama_pull_stream("http://10.9.8.7:11434", "m")])

    text = run(drain())
    assert "10.9.8.7" not in text and "ollama unreachable" in text
