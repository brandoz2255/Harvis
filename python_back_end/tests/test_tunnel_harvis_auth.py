"""HARVIS_TUNNEL_AUTH=harvis: the tunnel carries traffic, Harvis sign-in + approval decides.

No database needed. Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_tunnel_harvis_auth.py -q
"""
from __future__ import annotations

import asyncio

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from plugins.exposure import mode
from plugins.exposure import signup as shared_signup


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tunnel(monkeypatch):
    for key in ("HARVIS_CF_ACCESS_TEAM_DOMAIN", "HARVIS_CF_ACCESS_AUD", "HARVIS_SIGNUP_APPROVAL",
                "HARVIS_BUILD_SPACE_ACCESS", "HARVIS_TUNNEL_AUTH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan+tunnel")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    return monkeypatch


@pytest.mark.parametrize("raw,expected", [
    (None, "access"), ("", "access"), ("access", "access"), ("harvis", "harvis"),
    (" HARVIS ", "harvis"), ("harvsi", "access"), ("none", "access"),
])
def test_unknown_values_keep_cloudflare_access(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("HARVIS_TUNNEL_AUTH", raising=False)
    else:
        monkeypatch.setenv("HARVIS_TUNNEL_AUTH", raw)
    assert mode.tunnel_auth() == expected


def test_access_gate_only_in_tunnel_modes_with_access(tunnel):
    assert mode.access_gate_on()
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    assert not mode.access_gate_on()
    tunnel.setenv("HARVIS_EXPOSURE", "lan")
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "access")
    assert not mode.access_gate_on()


def test_harvis_mode_starts_without_access_settings(tunnel):
    assert any("HARVIS_CF_ACCESS_AUD" in p for p in mode.startup_problems())  # access mode, unchanged
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    assert mode.startup_problems() == []


def test_harvis_mode_refuses_to_start_without_approval_or_with_open_build_space(tunnel):
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    tunnel.setenv("HARVIS_SIGNUP_APPROVAL", "false")
    assert any("approval" in p for p in mode.startup_problems())
    tunnel.delenv("HARVIS_SIGNUP_APPROVAL")
    tunnel.setenv("HARVIS_BUILD_SPACE_ACCESS", "everyone")
    assert any("HARVIS_BUILD_SPACE_ACCESS" in p for p in mode.startup_problems())


def _client():
    from fastapi import FastAPI

    from plugins.tunnel import TunnelOriginGate, create_tunnel_router

    app = FastAPI()

    @app.get("/api/thing")
    async def ok():
        return PlainTextResponse("ok")

    app.add_middleware(TunnelOriginGate)
    app.include_router(create_tunnel_router())
    return TestClient(app)


def test_tunnel_entrance_in_each_mode(tunnel):
    cf = {"CF-Ray": "8f00000000000000-LAX", "CF-Connecting-IP": "203.0.113.9"}
    client = _client()
    # access: no Access token, no entry; the origin gate refuses Cloudflare traffic too.
    assert client.get("/api/tunnel/verify", headers=cf).status_code == 403
    assert client.get("/api/thing", headers=cf).status_code == 403
    # harvis: the entrance lets the request on to the Harvis sign-in.
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    assert client.get("/api/tunnel/verify", headers=cf).status_code == 204
    assert client.get("/api/thing", headers=cf).text == "ok"
    # harvis set but no tunnel mode: the entrance keeps the Access check (fail closed).
    tunnel.setenv("HARVIS_EXPOSURE", "lan")
    assert client.get("/api/tunnel/verify", headers=cf).status_code == 403


def test_access_email_rules_apply_only_in_access_mode(tunnel):
    from fastapi import HTTPException

    from plugins.tunnel import access

    forged = {access.HEADER: "not-a-real-token", "cf-ray": "x"}
    with pytest.raises(HTTPException):
        run(shared_signup.before_signup("jane@example.test", forged))
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    run(shared_signup.before_signup("jane@example.test", forged))
    run(shared_signup.before_login("jane@example.test", forged))


def test_exposure_card_says_which_gate(tunnel):
    tunnel.setenv("HARVIS_TUNNEL_AUTH", "harvis")
    assert mode.describe()["tunnel_auth"] == "harvis"
