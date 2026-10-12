"""MCP OAuth against a mocked authorization server: discovery, registration, PKCE,
state handling, token exchange, refresh, the SSRF guard, and the Hermes flow store."""
import asyncio
import base64
import hashlib
import json
import logging
import os
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import mcp_oauth_flows as flows  # noqa: E402
from plugins.hermes_ui import rest_mcp  # noqa: E402
from plugins.mcp import auth as mcp_auth  # noqa: E402
from plugins.mcp import http_transport, oauth, oauth_discovery as disc  # noqa: E402
from plugins.mcp.protocol import McpAuthRequired, McpError  # noqa: E402
from plugins.mcp.types import AuthMethod, McpServerConfig, Transport  # noqa: E402

RESOURCE = "https://mcp.example/mcp"
CHALLENGE = ('Bearer realm="mcp", resource_metadata="https://mcp.example/.well-known/'
             'oauth-protected-resource/mcp", scope="read write"')
ADDRS = {"mcp.example": "93.184.216.34", "auth.example": "151.101.1.69", "other.example": "151.101.2.69",
         "evil.example": "10.0.0.5", "meta.example": "169.254.169.254"}
REDIRECT = "https://harvis.example/hermes-api/api/mcp/oauth/callback"


def run(coro):
    return asyncio.run(coro)


class MemoryStorage:
    """Stands in for PgTokenStorage: one dict per (user, server), shared across instances."""
    rows: dict = {}

    def __init__(self, *, pool, user_id, server_name):
        self.key = (int(user_id), server_name)

    async def get_tokens(self):
        row = self.rows.get(self.key, {}).get("tokens")
        if row is None:
            return None
        data = dict(row["data"])
        data["expires_in"] = max(int(row["expires_at"] - time.time()), 0) if row["expires_at"] else None
        if data["expires_in"] is None:
            data.pop("expires_in")
        return data

    async def set_tokens(self, tokens):
        exp = tokens.get("expires_in")
        self.rows.setdefault(self.key, {})["tokens"] = {
            "data": dict(tokens), "expires_at": time.time() + int(exp) if exp is not None else None}

    async def get_client_info(self):
        return self.rows.get(self.key, {}).get("client")

    async def set_client_info(self, info):
        self.rows.setdefault(self.key, {})["client"] = dict(info)

    async def clear(self):
        self.rows.pop(self.key, None)


class FakeAS:
    """The protected resource and its authorization server, as one MockTransport handler."""

    def __init__(self):
        self.seen: list[httpx.Request] = []
        self.token_forms: list[dict] = []
        self.registrations: list[dict] = []
        self.registration_endpoint = "https://auth.example/register"
        self.token_status = 200
        self.token_body = None
        self.challenge = CHALLENGE
        self.issued = 0
        self.as_extra: dict = {}
        self.prm_authorization_servers = ["https://auth.example/tenant1"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        url = str(request.url)
        if url == RESOURCE and request.method == "POST":
            return httpx.Response(401, headers={"WWW-Authenticate": self.challenge}) if self.challenge is not None \
                else httpx.Response(401)
        if url == "https://mcp.example/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={
                "resource": RESOURCE, "authorization_servers": self.prm_authorization_servers,
                "scopes_supported": ["fallback"]})
        if url == "https://auth.example/.well-known/oauth-authorization-server/tenant1":
            meta = {"issuer": "https://auth.example/tenant1",
                    "authorization_endpoint": "https://auth.example/authorize",
                    "token_endpoint": "https://auth.example/token",
                    "code_challenge_methods_supported": ["S256"], **self.as_extra}
            if self.registration_endpoint:
                meta["registration_endpoint"] = self.registration_endpoint
            return httpx.Response(200, json=meta)
        if url == "https://auth.example/register":
            self.registrations.append(json.loads(request.content))
            return httpx.Response(201, json={"client_id": "client-123"})
        if url == "https://auth.example/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            if self.token_body is not None or self.token_status != 200:
                return httpx.Response(self.token_status, json=self.token_body or {})
            self.issued += 1
            return httpx.Response(200, json={
                "access_token": f"ACCESS-{self.issued}", "refresh_token": f"REFRESH-{self.issued}",
                "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(404)


@pytest.fixture
def server(monkeypatch):
    fake = FakeAS()

    def getaddrinfo(host, port, *a, **kw):
        if host in ADDRS:
            return [(2, 1, 6, "", (ADDRS[host], port))]
        try:
            import ipaddress
            ipaddress.ip_address(host)
            return [(2, 1, 6, "", (host, port))]
        except ValueError:
            raise OSError(f"no such host {host}")
    monkeypatch.setattr(http_transport.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setattr(disc, "_client", lambda: http_transport.guarded_client(
        timeout=5, transport=http_transport.GuardedTransport(inner=httpx.MockTransport(fake))))
    monkeypatch.setattr(oauth, "PgTokenStorage", MemoryStorage)
    MemoryStorage.rows = {}
    oauth._pending.clear()
    oauth._refresh_locks.clear()
    flows._FLOWS.clear()
    return fake


def cfg(user_id=7, name="notion", url=RESOURCE):
    return McpServerConfig(user_id=user_id, server_name=name, transport=Transport.STREAMABLE_HTTP, url=url,
                           auth_method=AuthMethod.OAUTH)


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# ─── discovery ───────────────────────────────────────────────────────────────

def test_discovery_follows_the_401_challenge_to_the_authorization_server(server):
    meta = run(disc.discover(RESOURCE))
    assert meta["authorization_endpoint"] == "https://auth.example/authorize"
    assert meta["resource"] == RESOURCE
    assert meta["scopes"] == "read write"  # the challenge's scope beats the document's
    urls = [str(r.url) for r in server.seen]
    assert "https://mcp.example/.well-known/oauth-protected-resource/mcp" in urls
    # RFC 8414: the well-known segment goes before the issuer's path
    assert "https://auth.example/.well-known/oauth-authorization-server/tenant1" in urls


def test_discovery_without_a_challenge_uses_the_well_known_locations(server):
    server.challenge = None
    meta = run(disc.discover(RESOURCE))
    assert meta["token_endpoint"] == "https://auth.example/token" and meta["scopes"] == "fallback"


def test_discovery_with_no_metadata_says_what_to_do(server):
    server.prm_authorization_servers = ["https://other.example"]
    with pytest.raises(oauth.OAuthError) as exc:
        run(disc.discover(RESOURCE))
    assert exc.value.code == disc.CODE_NO_METADATA and "token" in str(exc.value)


def test_a_server_without_s256_is_refused(server):
    server.as_extra = {"code_challenge_methods_supported": ["plain"]}
    with pytest.raises(oauth.OAuthError, match="S256"):
        run(disc.discover(RESOURCE))


def test_a_javascript_authorize_endpoint_is_refused(server):
    server.as_extra = {"authorization_endpoint": "javascript:alert(1)"}
    with pytest.raises(oauth.OAuthError, match="http"):
        run(disc.discover(RESOURCE))


def test_www_authenticate_parsing():
    got = disc.parse_www_authenticate('Bearer realm="a", resource_metadata="https://x/y", scope="a b", error=invalid_token')
    assert got == {"realm": "a", "resource_metadata": "https://x/y", "scope": "a b", "error": "invalid_token"}
    assert disc.parse_www_authenticate(None) == {}


# ─── authorize: registration, PKCE, state ────────────────────────────────────

def test_authorization_registers_a_public_client_and_builds_a_pkce_url(server):
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    q = query(begun["authorize_url"])
    assert begun["authorize_url"].startswith("https://auth.example/authorize?")
    assert (q["response_type"], q["client_id"], q["redirect_uri"]) == ("code", "client-123", REDIRECT)
    assert q["code_challenge_method"] == "S256" and q["state"] == begun["state"]
    assert q["resource"] == RESOURCE and q["scope"] == "read write"
    reg = server.registrations[0]
    assert reg["redirect_uris"] == [REDIRECT] and reg["token_endpoint_auth_method"] == "none"
    assert len(begun["state"]) >= 30


def test_the_code_exchange_proves_the_verifier_the_challenge_came_from(server):
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    q = query(begun["authorize_url"])
    done = run(oauth.complete_authorization(begun["state"], "the-code", None))
    assert done == {"server_name": "notion", "user_id": 7}
    form = server.token_forms[0]
    assert form["grant_type"] == "authorization_code" and form["code"] == "the-code"
    assert form["redirect_uri"] == REDIRECT and form["client_id"] == "client-123" and form["resource"] == RESOURCE
    digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
    assert digest == q["code_challenge"]
    stored = MemoryStorage.rows[(7, "notion")]["tokens"]["data"]
    assert stored["access_token"] == "ACCESS-1" and stored["harvis_token_endpoint"] == "https://auth.example/token"


def test_state_is_single_use(server):
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    run(oauth.complete_authorization(begun["state"], "c", None))
    with pytest.raises(oauth.OAuthError, match="no longer pending"):
        run(oauth.complete_authorization(begun["state"], "c", None))
    assert len(server.token_forms) == 1


def test_a_made_up_state_is_refused_before_any_request(server):
    with pytest.raises(oauth.OAuthError):
        run(oauth.complete_authorization("guessed", "c", None))
    assert server.token_forms == [] and server.seen == []


def test_state_expires(server, monkeypatch):
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    oauth._pending[begun["state"]]["started"] -= oauth.PENDING_TTL_S + 5
    with pytest.raises(oauth.OAuthError, match="no longer pending"):
        run(oauth.complete_authorization(begun["state"], "c", None))
    assert server.token_forms == []


def test_state_belongs_to_one_user_and_one_server(server):
    begun = run(oauth.begin_authorization(cfg(user_id=7, name="notion"), None, REDIRECT))
    assert oauth.pending_owner(begun["state"]) == (7, "notion")
    done = run(oauth.complete_authorization(begun["state"], "c", None))
    # tokens land on the user and server the state was minted for, whoever carried it back
    assert (7, "notion") in MemoryStorage.rows and (8, "notion") not in MemoryStorage.rows
    assert done["user_id"] == 7


def test_starting_again_replaces_the_old_authorization(server):
    first = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    second = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    assert oauth.pending_owner(first["state"]) is None and oauth.pending_owner(second["state"])


def test_registered_client_is_reused_until_the_redirect_changes(server):
    run(oauth.begin_authorization(cfg(), None, REDIRECT))
    run(oauth.begin_authorization(cfg(), None, REDIRECT))
    assert len(server.registrations) == 1
    run(oauth.begin_authorization(cfg(), None, "https://other.example/cb"))
    assert len(server.registrations) == 2


def test_no_registration_endpoint_asks_for_a_client_id(server):
    server.registration_endpoint = None
    with pytest.raises(oauth.OAuthError) as exc:
        run(oauth.begin_authorization(cfg(), None, REDIRECT))
    assert exc.value.code == disc.CODE_NO_REGISTRATION and REDIRECT in str(exc.value)


def test_a_manual_client_id_stands_in_for_registration(server):
    server.registration_endpoint = None
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT, client_id=" my-id ", client_secret="my-secret"))
    assert query(begun["authorize_url"])["client_id"] == "my-id" and server.registrations == []
    run(oauth.complete_authorization(begun["state"], "c", None))
    assert server.token_forms[0]["client_id"] == "my-id" and server.token_forms[0]["client_secret"] == "my-secret"
    # remembered: the next Connect does not ask again
    again = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    assert query(again["authorize_url"])["client_id"] == "my-id"


def test_a_server_with_no_url_cannot_authorize(server):
    with pytest.raises(oauth.OAuthError):
        run(oauth.begin_authorization(cfg(url=None), None, REDIRECT))


# ─── tokens: header, refresh ─────────────────────────────────────────────────

def _authorized(server):
    begun = run(oauth.begin_authorization(cfg(), None, REDIRECT))
    run(oauth.complete_authorization(begun["state"], "c", None))
    server.token_forms.clear()


def _expire():
    MemoryStorage.rows[(7, "notion")]["tokens"]["expires_at"] = time.time() - 5


def test_the_bearer_header_is_attached_for_oauth_servers(server):
    _authorized(server)
    assert run(mcp_auth.resolve_auth_headers(cfg(), object())) == {"Authorization": "Bearer ACCESS-1"}
    assert server.token_forms == []  # still fresh, no refresh


def test_an_unauthorized_server_says_connect_not_a_bare_401(server):
    with pytest.raises(McpAuthRequired):
        run(mcp_auth.resolve_auth_headers(cfg(), object()))


def test_an_expired_token_is_refreshed_and_the_new_one_stored(server):
    _authorized(server)
    _expire()
    token = run(oauth.ensure_access_token(cfg(), object()))
    form = server.token_forms[0]
    assert token == "ACCESS-2"
    assert (form["grant_type"], form["refresh_token"], form["client_id"]) == ("refresh_token", "REFRESH-1", "client-123")
    assert form["resource"] == RESOURCE
    stored = MemoryStorage.rows[(7, "notion")]["tokens"]["data"]
    assert stored["access_token"] == "ACCESS-2" and stored["refresh_token"] == "REFRESH-2"


def test_a_refresh_that_omits_the_refresh_token_keeps_the_old_one(server):
    _authorized(server)
    _expire()
    server.token_body = {"access_token": "NEW", "expires_in": 60}
    assert run(oauth.ensure_access_token(cfg(), object())) == "NEW"
    assert MemoryStorage.rows[(7, "notion")]["tokens"]["data"]["refresh_token"] == "REFRESH-1"


def test_concurrent_calls_refresh_once(server):
    _authorized(server)
    _expire()

    async def go():
        return await asyncio.gather(*[oauth.ensure_access_token(cfg(), object()) for _ in range(4)])
    tokens = run(go())
    assert tokens == ["ACCESS-2"] * 4 and len(server.token_forms) == 1


def test_a_failed_refresh_means_connect_again(server):
    _authorized(server)
    _expire()
    server.token_status, server.token_body = 400, {"error": "invalid_grant"}
    assert run(oauth.ensure_access_token(cfg(), object())) is None


def test_expired_with_no_refresh_token_means_connect_again(server):
    _authorized(server)
    MemoryStorage.rows[(7, "notion")]["tokens"]["data"].pop("refresh_token")
    _expire()
    assert run(oauth.ensure_access_token(cfg(), object())) is None


def test_forget_drops_the_grant(server):
    _authorized(server)
    run(oauth.forget(cfg(), object()))
    assert run(oauth.ensure_access_token(cfg(), object())) is None


# ─── the SSRF guard ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("registration_endpoint", "https://meta.example/register"),
    ("token_endpoint", "https://evil.example/token"),
])
def test_metadata_cannot_aim_a_request_at_a_private_address(server, field, value):
    server.as_extra = {field: value}
    if field == "registration_endpoint":
        server.registration_endpoint = value
    with pytest.raises(McpError, match="resolves to"):
        run(oauth.begin_authorization(cfg(), None, REDIRECT) if field == "registration_endpoint" else _begin_and_finish())


def _begin_and_finish():
    async def go():
        begun = await oauth.begin_authorization(cfg(), None, REDIRECT)
        return await oauth.complete_authorization(begun["state"], "c", None)
    return go()


def test_an_authorization_server_on_a_private_address_is_never_contacted(server):
    server.prm_authorization_servers = ["https://evil.example"]
    with pytest.raises(McpError, match="private address"):
        run(disc.discover(RESOURCE))
    assert not any(r.url.host == "evil.example" for r in server.seen)


def test_a_literal_metadata_address_is_refused(server):
    server.prm_authorization_servers = ["http://169.254.169.254"]
    with pytest.raises(McpError, match="never allowed"):
        run(disc.discover(RESOURCE))


def test_a_redirect_onto_a_private_host_is_refused_mid_flow(server, monkeypatch):
    def handler(request):
        if request.url.host == "mcp.example":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:5432/"})
        return httpx.Response(200, json={})
    monkeypatch.setattr(disc, "_client", lambda: http_transport.guarded_client(
        transport=http_transport.GuardedTransport(inner=httpx.MockTransport(handler))))
    with pytest.raises(McpError, match="loopback"):
        run(disc.discover(RESOURCE))


# ─── nothing secret in logs or errors ────────────────────────────────────────

def test_token_failures_do_not_echo_the_response_body(server, caplog):
    _authorized(server)
    _expire()
    server.token_status = 400
    server.token_body = {"error": "invalid_grant", "debug": "echoed REFRESH-1 and ACCESS-1"}
    caplog.set_level(logging.DEBUG)
    assert run(oauth.ensure_access_token(cfg(), object())) is None
    assert "REFRESH-1" not in caplog.text and "ACCESS-1" not in caplog.text
    with pytest.raises(oauth.OAuthError) as exc:
        run(oauth._token_request("https://auth.example/token", {"grant_type": "x"}))
    assert "ACCESS-1" not in str(exc.value) and "invalid_grant" in str(exc.value)


def test_successful_flow_logs_no_token(server, caplog):
    caplog.set_level(logging.DEBUG)
    _authorized(server)
    assert "ACCESS-" not in caplog.text and "REFRESH-" not in caplog.text and "the-code" not in caplog.text


# ─── the Hermes flow store and routes ────────────────────────────────────────

class FakeRequest:
    def __init__(self, headers=None, pool=True):
        self.headers = headers or {"host": "harvis.example", "x-forwarded-proto": "https"}
        self.url = SimpleNamespace(scheme="http")
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=object() if pool else None))
        self._body = {}

    async def json(self):
        return self._body


@pytest.fixture
def registry(monkeypatch, server):
    from plugins.mcp import server_registry

    class Registry:
        def __init__(self, pool):
            pass

        async def get(self, uid, name):
            return cfg(user_id=uid, name=name) if name in ("notion", "stdio-ish") and name != "stdio-ish" else (
                cfg(user_id=uid, name=name, url=None) if name == "stdio-ish" else None)
    monkeypatch.setattr(server_registry, "McpServerRegistry", Registry)

    async def connected(pool, user_id, name):
        connected.calls.append((user_id, name))
        return [{"name": "search", "description": "find"}]
    connected.calls = []
    monkeypatch.setattr(flows, "_mark_connected", connected)
    return connected


def start(user=7, name="notion", request=None, **kw):
    return run(flows.start(object(), user, name, request or FakeRequest(), **kw))


def test_redirect_uri_comes_from_the_forwarded_origin(monkeypatch):
    monkeypatch.delenv("HARVIS_PUBLIC_URL", raising=False)
    assert flows.redirect_uri(FakeRequest()) == REDIRECT
    monkeypatch.setenv("HARVIS_PUBLIC_URL", "https://pub.example/")
    assert flows.redirect_uri(FakeRequest()) == "https://pub.example/hermes-api/api/mcp/oauth/callback"


def test_start_returns_a_flow_the_tab_can_open_and_poll(registry):
    flow = start()
    assert flow["status"] == "authorization_required" and flow["server_name"] == "notion"
    assert flow["authorization_url"].startswith("https://auth.example/authorize?") and flow["error"] is None
    assert flows.get(7, flow["flow_id"])["status"] == "authorization_required"


def test_the_callback_approves_the_flow_and_hands_back_the_tools(registry):
    flow = start()
    state = query(flow["authorization_url"])["state"]
    ok, detail = run(flows.complete(object(), state, "the-code"))
    assert (ok, detail) == (True, "notion")
    done = flows.get(7, flow["flow_id"])
    assert done["status"] == "approved" and done["tools"] == [{"name": "search", "description": "find"}]
    assert done["authorization_url"] is None
    assert registry.calls == [(7, "notion")]


def test_another_user_cannot_see_or_cancel_my_flow(registry):
    flow = start()
    assert flows.get(8, flow["flow_id"]) is None
    assert flows.cancel(8, flow["flow_id"]) is None
    assert flows.get(7, flow["flow_id"]) is not None


def test_cancel_frees_the_state(registry):
    flow = start()
    state = query(flow["authorization_url"])["state"]
    assert flows.cancel(7, flow["flow_id"]) == {"ok": True, "status": "cancelled"}
    assert oauth.pending_owner(state) is None
    ok, _ = run(flows.complete(object(), state, "c"))
    assert ok is False and flows.get(7, flow["flow_id"])["status"] == "error"


def test_the_vendor_saying_no_marks_the_flow_failed(registry):
    flow = start()
    state = query(flow["authorization_url"])["state"]
    ok, detail = run(flows.complete(object(), state, "", "access_denied"))
    assert ok is False and detail == "access_denied"
    got = flows.get(7, flow["flow_id"])
    assert got["status"] == "error" and got["error"] == "access_denied"
    assert oauth.pending_owner(state) is None


def test_a_replayed_callback_does_not_resign_in(registry):
    flow = start()
    state = query(flow["authorization_url"])["state"]
    assert run(flows.complete(object(), state, "c"))[0] is True
    ok, detail = run(flows.complete(object(), state, "c"))
    assert ok is False and "no longer pending" in detail
    assert flows.get(7, flow["flow_id"])["status"] == "approved"


def test_an_old_flow_reads_as_expired(registry):
    flow = start()
    flows._FLOWS[flow["flow_id"]]["created"] -= flows.FLOW_TTL_S + 5
    got = flows.get(7, flow["flow_id"])
    assert got["status"] == "error" and "expired" in got["error"]
    assert oauth.pending_owner(query(flow["authorization_url"])["state"]) is None


def test_connecting_twice_replaces_the_first_flow(registry):
    first = start()
    second = start()
    assert flows.get(7, first["flow_id"]) is None
    assert flows.get(7, second["flow_id"])["status"] == "authorization_required"


def test_unregistered_server_asks_for_a_client_id_in_the_flow(registry, server):
    server.registration_endpoint = None
    flow = start()
    assert flow["status"] == "error" and flow["needs_client_id"] is True and "client ID" in flow["error"]
    retry = start(client_id="abc")
    assert retry["status"] == "authorization_required"
    assert query(retry["authorization_url"])["client_id"] == "abc"


def test_a_server_that_cannot_be_reached_is_an_error_flow_not_a_500(registry, server):
    server.prm_authorization_servers = ["https://evil.example"]
    flow = start()
    assert flow["status"] == "error" and "private" in flow["error"]


def test_unknown_and_local_servers_are_rejected(registry):
    with pytest.raises(HTTPException) as exc:
        start(name="nope")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        start(name="stdio-ish")
    assert exc.value.status_code == 400


def test_routes_round_trip(registry):
    user = {"id": 7}
    flow = run(rest_mcp.mcp_server_auth("notion", FakeRequest(), user))
    polled = run(rest_mcp.mcp_oauth_flow(flow["flow_id"], user))
    assert polled["status"] == "authorization_required"
    with pytest.raises(HTTPException) as exc:
        run(rest_mcp.mcp_oauth_flow(flow["flow_id"], {"id": 9}))
    assert exc.value.status_code == 404
    assert run(rest_mcp.mcp_oauth_flow_cancel(flow["flow_id"], user))["status"] == "cancelled"


def test_callback_route_is_open_and_escapes_what_the_vendor_sent(registry):
    class Req(FakeRequest):
        def __init__(self, q, pool=True):
            super().__init__(pool=pool)
            self.query_params = q
    page = run(rest_mcp.mcp_oauth_callback(Req({"error": "<script>alert(1)</script>"})))
    body = page.body.decode()
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body
    assert "Sign-in failed" in body
    assert "database is not ready" in run(rest_mcp.mcp_oauth_callback(Req({}, pool=False))).body.decode()
    flow = start()
    ok = run(rest_mcp.mcp_oauth_callback(Req({"state": query(flow["authorization_url"])["state"], "code": "c"})))
    assert "Connected" in ok.body.decode() and "harvis-mcp-oauth" in ok.body.decode()
    assert ok.headers["cache-control"] == "no-store"
