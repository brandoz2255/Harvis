"""The SSRF guard runs on every hop: a public MCP URL that redirects onto a
private, loopback or link-local address is refused at the redirect, and the
session client is built on that guarded transport."""
import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.mcp import http_transport  # noqa: E402
from plugins.mcp.protocol import McpError  # noqa: E402

ADDRS = {
    "public.example": "93.184.216.34",
    "mirror.example": "151.101.1.69",
    "evil.example": "10.0.0.5",
    "meta.example": "169.254.169.254",
    "loop.example": "127.0.0.1",
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def getaddrinfo(host, port, *a, **kw):
        if host not in ADDRS:
            raise OSError(f"no such host {host}")
        return [(2, 1, 6, "", (ADDRS[host], port))]
    monkeypatch.setattr(http_transport.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


def _client(redirects: dict, seen: list) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        target = redirects.get(request.url.host)
        if target:
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(200, json={"ok": True})
    return http_transport.guarded_client(
        transport=http_transport.GuardedTransport(inner=httpx.MockTransport(handler)))


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("host, reason", [
    ("evil.example", "private"), ("loop.example", "loopback"), ("meta.example", "link-local"),
])
def test_redirect_to_an_internal_address_is_refused(host, reason):
    seen = []

    async def go():
        async with _client({"public.example": f"http://{host}/mcp"}, seen) as client:
            await client.get("http://public.example/mcp")
    with pytest.raises(McpError) as exc:
        run(go())
    assert reason in str(exc.value)
    # The first hop was sent, the refused hop never was.
    assert seen == ["public.example"]


def test_redirect_between_public_hosts_is_followed():
    seen = []

    async def go():
        async with _client({"public.example": "https://mirror.example/mcp"}, seen) as client:
            return await client.get("http://public.example/mcp")
    resp = run(go())
    assert resp.status_code == 200 and seen == ["public.example", "mirror.example"]


def test_direct_private_request_is_refused_before_sending():
    seen = []

    async def go():
        async with _client({}, seen) as client:
            await client.post("http://evil.example/mcp", json={})
    with pytest.raises(McpError):
        run(go())
    assert seen == []


def test_redirect_loops_are_bounded():
    seen = []

    async def go():
        async with _client({"public.example": "https://mirror.example/a",
                            "mirror.example": "https://public.example/b"}, seen) as client:
            await client.get("http://public.example/mcp")
    with pytest.raises(httpx.TooManyRedirects):
        run(go())
    assert len(seen) == http_transport._MAX_REDIRECTS + 1


def test_session_client_is_guarded_and_follows_redirects():
    async def go():
        session = http_transport.HttpMcpSession("https://public.example/mcp")
        try:
            client = session._client
            assert isinstance(client._transport, http_transport.GuardedTransport)
            assert client.follow_redirects is True
            assert client.max_redirects == http_transport._MAX_REDIRECTS
        finally:
            await session.close()
    run(go())
