"""The experimental Cloudflare Tunnel (plugins/tunnel): the Access token check,
nginx's per-request check, the Access-email sign-in rules, and the gate for
Cloudflare traffic that skipped the Access entrance.

Cloudflare is never contacted: the Access keys are a locally generated RSA pair
handed to ``access._keys``.
"""
import asyncio
import os
import sys
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import jwk, jwt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.exposure import mode, signup  # noqa: E402
from plugins.tunnel import access, origin  # noqa: E402
from plugins.tunnel.routes import create_tunnel_router  # noqa: E402

TEAM = "lab.cloudflareaccess.com"
AUD = "a" * 64
STRONG = "s" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("HARVIS_EXPOSURE", "HARVIS_BUILD_SPACE_ACCESS", "HARVIS_SETUP_CODE",
                "HARVIS_CF_ACCESS_TEAM_DOMAIN", "HARVIS_CF_ACCESS_AUD", "JWT_SECRET",
                "HARVIS_CF_ACCESS_ALLOWED_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    access._jwks.update(keys=None, at=0.0, forced_at=float("-inf"))


def _keypair(kid):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    public = jwk.construct(pub, "RS256").to_dict()
    public.update(kid=kid, use="sig", alg="RS256")
    return pem, {"keys": [public]}


PEM, JWKS = _keypair("k1")
PEM2, JWKS2 = _keypair("k2")


def _token(pem=PEM, kid="k1", **overrides):
    now = int(time.time())
    claims = {"aud": [AUD], "iss": f"https://{TEAM}", "email": "Ada@Lab.edu",
              "iat": now, "exp": now + 600}
    claims.update(overrides)
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def cf(monkeypatch):
    """Access configured, keys served from memory; records each key fetch."""
    monkeypatch.setenv("HARVIS_CF_ACCESS_TEAM_DOMAIN", f"https://{TEAM.upper()}/")
    monkeypatch.setenv("HARVIS_CF_ACCESS_AUD", AUD)
    served = {"keys": JWKS, "fetches": []}

    async def fake_keys(force=False):
        served["fetches"].append(force)
        return served["keys"]

    monkeypatch.setattr(access, "_keys", fake_keys)
    return served


def run(coro):
    return asyncio.run(coro)


# ─── mode ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exposure", ["tunnel", "lan+tunnel"])
def test_tunnel_needs_access_configured(monkeypatch, exposure):
    monkeypatch.setenv("HARVIS_EXPOSURE", exposure)
    monkeypatch.setenv("JWT_SECRET", STRONG)
    assert any("HARVIS_CF_ACCESS" in p for p in mode.startup_problems())
    monkeypatch.setenv("HARVIS_CF_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("HARVIS_CF_ACCESS_AUD", AUD)
    assert mode.startup_problems() == []


def test_lan_plus_tunnel_is_shared_and_has_a_tunnel(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "LAN+Tunnel")
    assert mode.exposure() == "lan+tunnel"
    assert mode.shared() and mode.tunnel_on()
    assert not mode.build_space_open_to_all()
    assert mode.describe()["tunnel"] is True
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert not mode.tunnel_on() and mode.describe()["tunnel"] is False


def test_describe_shows_no_secret_values(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    monkeypatch.setenv("HARVIS_SETUP_CODE", "code-value-123")
    monkeypatch.setenv("JWT_SECRET", STRONG)
    text = repr(mode.describe())
    assert "code-value-123" not in text and STRONG not in text


# ─── Cloudflare Access token ─────────────────────────────────────────────────


def test_valid_token_passes_and_email_is_normalised(cf):
    claims = run(access.verify(_token()))
    assert claims and access.email_of(claims) == "ada@lab.edu"


@pytest.mark.parametrize("bad", [
    {"aud": ["another-app"]},
    {"iss": "https://other.cloudflareaccess.com"},
    {"exp": int(time.time()) - 60},
])
def test_token_for_another_app_team_or_time_is_refused(cf, bad):
    assert run(access.verify(_token(**bad))) is None


def test_token_signed_by_someone_else_is_refused(cf):
    assert run(access.verify(_token(pem=PEM2))) is None


def test_no_access_config_refuses_everything(monkeypatch):
    monkeypatch.setenv("HARVIS_CF_ACCESS_TEAM_DOMAIN", TEAM)  # AUD missing
    assert run(access.verify(_token())) is None


def test_rotated_key_triggers_one_refetch(cf):
    cf["keys"] = JWKS  # cache holds only k1; Cloudflare has moved to k2
    token = _token(pem=PEM2, kid="k2")

    async def rotate(force=False):
        cf["fetches"].append(force)
        return JWKS2 if force else JWKS

    access._keys, original = rotate, access._keys
    try:
        assert run(access.verify(token))
    finally:
        access._keys = original
    assert cf["fetches"] == [False, True]


def test_unknown_key_ids_cannot_make_us_hammer_cloudflare(cf):
    for n in range(5):
        assert run(access.verify(_token(pem=PEM2, kid=f"forged-{n}"))) is None
    assert cf["fetches"].count(True) == 1


@pytest.mark.parametrize("missing", ["aud", "exp"])
def test_token_without_audience_or_expiry_is_refused(cf, missing):
    now = int(time.time())
    claims = {"aud": [AUD], "iss": f"https://{TEAM}", "email": "ada@lab.edu", "iat": now, "exp": now + 600}
    del claims[missing]
    assert run(access.verify(jwt.encode(claims, PEM, algorithm="RS256", headers={"kid": "k1"}))) is None


def test_a_key_the_library_cannot_read_refuses_instead_of_crashing(cf):
    cf["keys"] = {"keys": [{"kty": "EC", "kid": "k1", "crv": "P-256", "x": "AA", "y": "AA"}]}
    assert run(access.verify(_token())) is None


def test_a_host_clock_slightly_behind_still_accepts_fresh_tokens(cf):
    assert run(access.verify(_token(nbf=int(time.time()) + 10)))


def test_garbage_token_is_refused_without_refetch(cf):
    assert run(access.verify("not-a-jwt")) is None
    assert cf["fetches"] == [False]


# ── named people (HARVIS_CF_ACCESS_ALLOWED_EMAILS) ──────────────────────────

def test_allow_list_refuses_a_valid_token_for_someone_else(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", " ADA@lab.edu , grace@lab.edu,")
    assert run(access.verify(_token()))  # Ada@Lab.edu, case and spaces ignored
    assert run(access.verify(_token(email="grace@lab.edu")))
    assert run(access.verify(_token(email="mallory@lab.edu"))) is None
    assert run(access.verify(_token(email="ada@lab.edu.evil.com"))) is None
    assert run(access.verify(_token(email=None))) is None  # service token: no person
    assert run(access.verify(_token(email="\u212aate@lab.edu"))) is None  # Kelvin sign lowers to k
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", "kate@lab.edu")
    assert run(access.verify(_token(email="\u212aate@lab.edu"))) is None


def test_allow_list_domain_entry(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", "@lab.edu")
    assert run(access.verify(_token(email="anyone@lab.edu")))
    assert run(access.verify(_token(email="anyone@sub.lab.edu"))) is None
    assert run(access.verify(_token(email="anyone@evil-lab.edu"))) is None


def test_no_allow_list_keeps_the_regular_profile(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", " , ")
    assert access.allowed_emails() == frozenset()
    assert run(access.verify(_token(email="anyone@anywhere.org")))


def test_allow_list_reaches_every_tunnel_check(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", "grace@lab.edu")
    assert _client().get("/api/tunnel/verify", headers={access.HEADER: _token()}).status_code == 403
    with pytest.raises(HTTPException):
        run(signup.before_signup("ada@lab.edu", {access.HEADER: _token()}))
    assert _origin_app().get("/api/ping", headers={"CF-Ray": "abc", access.HEADER: _token()}).status_code == 403
    ok = _client().get("/api/tunnel/verify", headers={access.HEADER: _token(email="grace@lab.edu")})
    assert ok.status_code == 204 and ok.headers["x-harvis-access-email"] == "grace@lab.edu"


def test_describe_counts_the_allow_list_without_listing_it(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    monkeypatch.setenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", "ada@lab.edu,grace@lab.edu")
    card = mode.describe()
    assert card["access_allowed_emails"] == 2 and "ada@lab.edu" not in repr(card)


# ─── /api/tunnel/verify (nginx auth_request) ─────────────────────────────────


def _client():
    app = FastAPI()
    app.include_router(create_tunnel_router())
    return TestClient(app)


def test_tunnel_verify_lets_a_valid_token_through(cf):
    r = _client().get("/api/tunnel/verify", headers={"Cf-Access-Jwt-Assertion": _token()})
    assert r.status_code == 204
    assert r.headers["x-harvis-access-email"] == "ada@lab.edu"


def test_tunnel_verify_stops_missing_and_forged_tokens(cf):
    c = _client()
    assert c.get("/api/tunnel/verify").status_code == 403
    forged = _token(pem=PEM2)
    assert c.get("/api/tunnel/verify", headers={"Cf-Access-Jwt-Assertion": forged}).status_code == 403


def test_tunnel_verify_stops_everything_when_access_is_not_set_up():
    r = _client().get("/api/tunnel/verify", headers={"Cf-Access-Jwt-Assertion": _token()})
    assert r.status_code == 403


def test_tunnel_signup_must_use_the_access_email(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    headers = {access.HEADER: _token()}
    run(signup.before_signup(" ADA@lab.edu ", headers))
    with pytest.raises(HTTPException) as exc:
        run(signup.before_signup("mallory@lab.edu", headers))
    assert "ada@lab.edu" in exc.value.detail


def test_tunnel_signup_needs_an_access_email(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    service_token = _token(email=None)  # Cloudflare service tokens carry no email
    with pytest.raises(HTTPException):
        run(signup.before_signup("anyone@lab.edu", {access.HEADER: service_token}))


def test_tunnel_signup_with_a_bad_access_token_is_refused(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    with pytest.raises(HTTPException):
        run(signup.before_signup("ada@lab.edu", {access.HEADER: _token(pem=PEM2)}))


# ── sign-in through the tunnel ──────────────────────────────────────────────

def test_tunnel_login_is_bound_to_the_access_email(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    headers = {access.HEADER: _token()}
    run(signup.before_login("ada@lab.edu", headers))
    with pytest.raises(HTTPException) as exc:
        run(signup.before_login("admin@lab.edu", headers))
    assert exc.value.status_code == 403 and "ada@lab.edu" in exc.value.detail
    with pytest.raises(HTTPException):
        run(signup.before_login("ada@lab.edu", {access.HEADER: _token(email=None)}))
    with pytest.raises(HTTPException):
        run(signup.before_login("ada@lab.edu", {access.HEADER: _token(pem=PEM2)}))


def test_login_without_an_access_token_is_unchanged(cf, monkeypatch):
    run(signup.before_login("admin@lab.edu", {access.HEADER: _token()}))  # local install
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    run(signup.before_login("admin@lab.edu", {}))  # from this computer, not through Cloudflare


# ── Cloudflare traffic that skipped the nginx:8081 entrance ─────────────────

def _origin_app():
    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    from starlette.websockets import WebSocket

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.add_middleware(origin.TunnelOriginGate)
    return TestClient(app)


def test_origin_gate_is_inert_outside_tunnel_mode(cf, monkeypatch):
    client = _origin_app()
    assert client.get("/api/ping", headers={"CF-Ray": "abc"}).status_code == 200
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert client.get("/api/ping", headers={"CF-Ray": "abc"}).status_code == 200


@pytest.mark.parametrize("exposure", ["tunnel", "lan+tunnel"])
def test_origin_gate_refuses_cloudflare_traffic_without_access(cf, monkeypatch, exposure):
    monkeypatch.setenv("HARVIS_EXPOSURE", exposure)
    client = _origin_app()
    assert client.get("/api/ping").status_code == 200  # this computer, no Cloudflare stamp
    assert client.get("/api/ping", headers={"CF-Ray": "abc"}).status_code == 403
    forged = {"CF-Ray": "abc", access.HEADER: _token(pem=PEM2)}
    assert client.get("/api/ping", headers=forged).status_code == 403
    good = {"CF-Ray": "abc", access.HEADER: _token()}
    assert client.get("/api/ping", headers=good).status_code == 200
    with client.websocket_connect("/api/ws", headers=good) as sock:
        assert sock.receive_text() == "hi"
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws", headers={"CF-Ray": "abc"}) as sock:
            sock.receive_text()
    assert exc.value.code == 4403


def test_origin_gate_reads_the_first_access_header_like_verify(cf, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    client = _origin_app()
    two = [("CF-Ray", "abc"), (access.HEADER, _token(pem=PEM2)), (access.HEADER, _token())]
    assert client.get("/api/ping", headers=two).status_code == 403


def test_sandbox_apps_do_not_forward_the_access_token():
    rest = pytest.importorskip("plugins.hermes_ui.rest_sandbox_apps")
    assert access.HEADER in rest._DROP_REQ
