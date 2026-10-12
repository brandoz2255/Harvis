"""web-fetch refuses every address that is not globally routable, on the first
URL and on every redirect hop. No socket is opened: DNS and the transport are faked."""
import asyncio
import os
import sys

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import openclaw_proxy as proxy  # noqa: E402


@pytest.mark.parametrize("ip", ["10.0.0.5", "172.17.0.1", "192.168.4.1", "127.0.0.1", "169.254.169.254",
                                "100.100.12.34", "0.0.0.0", "::1", "fd00::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_internal_literals_are_refused(ip):
    with pytest.raises(HTTPException):
        proxy._ensure_resolved_addresses_public(ip)


def test_public_literal_passes():
    proxy._ensure_resolved_addresses_public("93.184.216.34")


def test_hostname_resolving_inside_is_refused(monkeypatch):
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("100.101.23.45", 0))])
    with pytest.raises(HTTPException):
        proxy._ensure_resolved_addresses_public("tailnet.example")


def test_redirect_onto_an_internal_host_is_refused(monkeypatch):
    def resolve(host, port):
        return [(0, 0, 0, "", ("10.0.0.9" if host == "pgsql" else "93.184.216.34", 0))]

    monkeypatch.setattr(proxy.socket, "getaddrinfo", resolve)
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"Location": "http://pgsql:5432/"})

    transport = proxy._PublicOnlyTransport()
    transport._inner = httpx.MockTransport(handler)

    async def go():
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            await client.get("https://example.com/")

    with pytest.raises(HTTPException):
        asyncio.run(go())
    assert seen == ["example.com"]
