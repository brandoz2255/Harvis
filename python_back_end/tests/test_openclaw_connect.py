"""Link your own OpenClaw: save, verify, disconnect, and use it from Chat.

Modeled on the external-Hermes tests in test_ssrf_connect_guard.py. Nothing here opens a
socket: the stored settings and httpx are replaced."""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat import hermes_chat, openclaw_connect  # noqa: E402
from plugins.hermes_ui import providers  # noqa: E402

ADMIN = SimpleNamespace(id=1)
USER = SimpleNamespace(id=7)
OTHER = SimpleNamespace(id=8)
PUBLIC_URL = "http://93.184.216.34:18789"
LAN_URL = "http://10.0.0.5:18789"
TOKEN = "gw-token-123"


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

    monkeypatch.setattr(openclaw_connect, "_read_raw", read_raw)
    monkeypatch.setattr(openclaw_connect, "_write_raw", write_raw)
    monkeypatch.setattr(openclaw_connect, "_enc", lambda v: "enc(" + v + ")")
    monkeypatch.setattr(openclaw_connect, "_dec", lambda v: v[4:-1])
    return rows


def _routes():
    router = APIRouter()
    openclaw_connect.register_openclaw_connect_routes(router, lambda: None)
    return {(m, r.path.rsplit("/", 1)[-1]): r.endpoint for r in router.routes for m in r.methods}


def _request(body=None):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))

    async def json_body():
        return body or {}

    request.json = json_body
    return request


def _get(user):
    return run(_routes()[("GET", "openclaw-external")](_request(), user))


def _save(user, url, token=None, **extra):
    body = {"url": url, **({"token": token} if token is not None else {}), **extra}
    return run(_routes()[("POST", "openclaw-external")](_request(body), user))


def _verify(user):
    return run(_routes()[("POST", "verify")](_request(), user))


def _disconnect(user):
    return run(_routes()[("POST", "disconnect")](_request(), user))


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def _gateway(monkeypatch, script):
    """Replace httpx.AsyncClient with a gateway answering `script[(METHOD, path)]` with a status
    code, or raising when the entry is an exception. A missing entry is a transport error."""
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def _answer(self, method, url, headers, body):
            path = "/" + url.split("/", 3)[3]
            calls.append((method, path, dict(headers or {}), body))
            answer = script.get((method, path), httpx.ConnectError("refused"))
            if isinstance(answer, Exception):
                raise answer
            return _Resp(*answer) if isinstance(answer, tuple) else _Resp(answer)

        async def get(self, url, headers=None):
            return await self._answer("GET", url, headers, None)

        async def post(self, url, headers=None, json=None):
            return await self._answer("POST", url, headers, json)

    monkeypatch.setattr(openclaw_connect.httpx, "AsyncClient", Client)
    return calls


MODELS, CHAT, HEALTH = ("GET", "/v1/models"), ("POST", "/v1/chat/completions"), ("GET", "/health")


# -- save / verify / disconnect ----------------------------------------------------------

def test_save_verify_and_disconnect(local, stored, monkeypatch):
    calls = _gateway(monkeypatch, {MODELS: 200})
    saved = _save(USER, LAN_URL, TOKEN)
    assert saved["state"] == "saved" and saved["connected"] is False and saved["token_saved"] is True
    assert stored[7]["token_enc"] == "enc(" + TOKEN + ")"

    result = _verify(USER)
    assert result["ok"] is True and result["connected"] is True and result["state"] == "linked"
    assert stored[7]["verified_at"] and stored[7]["last_error"] is None
    assert calls[0][2]["Authorization"] == "Bearer " + TOKEN

    assert _disconnect(USER) == {"connected": False, "state": "not_linked"}
    assert stored == {}
    assert _get(USER)["state"] == "not_linked"


def test_the_token_never_comes_back(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    _save(USER, LAN_URL, TOKEN)
    for payload in (_get(USER), _verify(USER), _save(USER, LAN_URL)):
        text = json.dumps(payload)
        assert TOKEN not in text and "token_enc" not in text and "enc(" not in text
        assert payload["token_saved"] is True


def test_a_ws_address_is_read_as_http(local, stored):
    assert _save(USER, "ws://10.0.0.5:18789/")["url"] == LAN_URL
    assert _save(USER, "wss://claw.example.org")["url"] == "https://claw.example.org"


@pytest.mark.parametrize("url", ["", "not a url", "ftp://host/x", "10.0.0.5:18789"])
def test_a_malformed_url_is_refused(local, stored, url):
    with pytest.raises(HTTPException) as info:
        _save(USER, url)
    assert info.value.status_code == 400 and stored == {}


def test_resaving_the_same_url_keeps_the_token_but_a_new_url_drops_it(local, stored):
    _save(USER, LAN_URL, TOKEN)
    assert _save(USER, LAN_URL)["token_saved"] is True
    assert _save(USER, "http://10.0.0.6:18789")["token_saved"] is False


def test_resaving_clears_the_prior_verification(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    _save(USER, LAN_URL, TOKEN)
    _verify(USER)
    assert _save(USER, LAN_URL)["connected"] is False


def test_a_failed_verify_keeps_the_error_and_stays_unlinked(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 401})
    _save(USER, LAN_URL, "wrong")
    result = _verify(USER)
    assert result["ok"] is False and result["state"] == "error" and "token" in result["error"]
    assert stored[7]["verified_at"] is None and stored[7]["last_error"] == result["error"]
    assert run(openclaw_connect.is_openclaw_linked(None, 7)) is False


def test_verify_without_a_saved_url_is_a_400(local, stored):
    with pytest.raises(HTTPException) as info:
        _verify(USER)
    assert info.value.status_code == 400


# -- a link belongs to one user ----------------------------------------------------------

def test_another_user_cannot_see_or_use_the_link(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    _save(USER, LAN_URL, TOKEN)
    _verify(USER)
    assert _get(OTHER) == {"connected": False, "state": "not_linked", "url": None, "token_saved": False,
                           "verified_at": None, "last_error": None}
    assert run(openclaw_connect.is_openclaw_linked(None, 8)) is False
    assert run(openclaw_connect.resolve_openclaw_target(None, 8)) is None
    assert run(openclaw_connect.is_openclaw_linked(None, 7)) is True


def test_resolve_target_returns_the_decrypted_token_only_when_verified(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    _save(USER, LAN_URL + "/", TOKEN)
    assert run(openclaw_connect.resolve_openclaw_target(None, 7)) is None
    _verify(USER)
    assert run(openclaw_connect.resolve_openclaw_target(None, 7)) == {
        "base_url": LAN_URL, "token": TOKEN, "guarded": False}


# -- the private-URL guard behaves like Hermes -------------------------------------------

@pytest.mark.parametrize("url", [LAN_URL, "http://ollama:11434", "http://127.0.0.1:18789",
                                 "http://100.64.0.1:18789", f"{PUBLIC_URL}/?k=v", "http://u:p@93.184.216.34/"])
def test_a_guarded_user_cannot_save_a_private_or_unplain_url(shared, stored, url):
    with pytest.raises(HTTPException) as info:
        _save(USER, url)
    assert info.value.status_code == 400 and stored == {}


def test_a_guarded_user_may_save_a_plain_public_url(shared, stored):
    assert _save(USER, PUBLIC_URL)["url"] == PUBLIC_URL


def test_admins_and_local_installs_keep_private_urls(shared, stored, monkeypatch):
    assert _save(ADMIN, LAN_URL)["url"] == LAN_URL
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    assert _save(USER, LAN_URL)["url"] == LAN_URL


def test_verify_refuses_a_stored_private_url_for_a_guarded_user_without_connecting(shared, stored, monkeypatch):
    stored[7] = {"url": "http://ollama:11434", "verified_at": None}  # saved before the rule existed

    class NoClient:
        def __init__(self, *a, **k):
            raise AssertionError("no connection may be opened")

    monkeypatch.setattr(openclaw_connect.httpx, "AsyncClient", NoClient)
    result = _verify(USER)
    assert result["ok"] is False and "not allowed on a shared server" in result["error"]
    assert stored[7]["verified_at"] is None


def test_a_stored_private_url_is_not_resolved_for_a_guarded_user(shared, stored):
    stored[7] = {"url": "http://ollama:11434", "verified_at": 123}
    with pytest.raises(providers.EndpointValidationError):
        run(openclaw_connect.resolve_openclaw_target(None, 7))


def test_a_guarded_user_verifies_through_the_guarded_client_and_a_redirect_is_not_success(shared, stored, monkeypatch):
    seen = []

    class Client:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url, headers=None):
            return _Resp(302)

    async def public(_url):
        return None

    monkeypatch.setattr(openclaw_connect.httpx, "AsyncClient", lambda **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(providers, "guarded_client", Client)
    monkeypatch.setattr(providers, "refuse_private_url", public)
    stored[7] = {"url": PUBLIC_URL, "verified_at": None}
    result = _verify(USER)
    assert seen == [{"timeout": 8.0}]
    assert result["ok"] is False and "redirects" in result["error"]


# -- probe fallbacks ---------------------------------------------------------------------

def _probe(monkeypatch, script, token=TOKEN):
    calls = _gateway(monkeypatch, script)
    return run(openclaw_connect._probe(LAN_URL, token)), calls


def test_probe_models_answering_is_enough(monkeypatch):
    result, calls = _probe(monkeypatch, {MODELS: 200})
    assert result == {"ok": True} and [c[1] for c in calls] == ["/v1/models"]


def test_probe_the_web_ui_catch_all_page_is_not_a_verified_token(monkeypatch):
    html = (200, {"content-type": "text/html; charset=utf-8"})
    result, calls = _probe(monkeypatch, {MODELS: html, HEALTH: 200})
    assert result["ok"] is False and "chatCompletions" in result["error"]
    result, _ = _probe(monkeypatch, {MODELS: html, CHAT: 400})
    assert result == {"ok": True}  # the POST endpoint still proves it when it exists


def test_probe_a_rejected_token_is_not_a_fallback(monkeypatch):
    for status in (401, 403):
        result, calls = _probe(monkeypatch, {MODELS: status, CHAT: 200, HEALTH: 200})
        assert result["ok"] is False and "token" in result["error"] and len(calls) == 1


def test_probe_falls_back_to_the_chat_endpoint_when_there_is_no_models_route(monkeypatch):
    for models in (404, 405, httpx.ReadTimeout("slow")):
        result, calls = _probe(monkeypatch, {MODELS: models, CHAT: 400})
        assert result == {"ok": True}
        body = calls[-1][3]
        assert calls[-1][:2] == ("POST", "/v1/chat/completions") and body["messages"] == []  # no agent turn


def test_probe_the_chat_endpoint_still_proves_the_token(monkeypatch):
    result, _ = _probe(monkeypatch, {MODELS: 404, CHAT: 401})
    assert result["ok"] is False and "token" in result["error"]


def test_probe_reachable_gateway_with_the_http_api_off_says_so(monkeypatch):
    result, calls = _probe(monkeypatch, {MODELS: 404, CHAT: 404, HEALTH: 200})
    assert result["ok"] is False and "chatCompletions" in result["error"]
    assert [c[1] for c in calls] == ["/v1/models", "/v1/chat/completions"]  # it answered; no /health needed


def test_probe_health_only_tells_a_silent_api_from_a_dead_gateway(monkeypatch):
    result, calls = _probe(monkeypatch, {HEALTH: 200})
    assert result["ok"] is False and "chatCompletions" in result["error"]
    assert calls[-1][1] == "/health"


def test_probe_health_alone_never_counts_as_verified(monkeypatch):
    result, _ = _probe(monkeypatch, {HEALTH: 200}, token=None)
    assert result["ok"] is False


def test_probe_nothing_answering_is_unreachable(monkeypatch):
    result, _ = _probe(monkeypatch, {})
    assert result == {"ok": False, "error": "Could not reach an OpenClaw gateway at that URL."}


def test_probe_sends_no_authorization_header_without_a_token(monkeypatch):
    _, calls = _probe(monkeypatch, {MODELS: 200}, token=None)
    assert "Authorization" not in calls[0][2]


# -- using the link from Chat ------------------------------------------------------------

def test_the_openclaw_model_is_listed_only_for_a_verified_link(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    assert run(hermes_chat.openclaw_chat_model_entry(object(), 7)) is None
    _save(USER, LAN_URL, TOKEN)
    assert run(hermes_chat.openclaw_chat_model_entry(object(), 7)) is None  # saved, not verified
    _verify(USER)
    entry = run(hermes_chat.openclaw_chat_model_entry(object(), 7))
    assert entry["id"] == hermes_chat.OPENCLAW_CHAT_MODEL_ID == "openclaw-external"
    assert "Hermes" in entry["info"]["meta"]["description"]
    assert run(hermes_chat.openclaw_chat_model_entry(object(), 8)) is None
    assert run(hermes_chat.openclaw_chat_model_entry(None, 7)) is None


def test_the_openclaw_model_takes_the_agent_passthrough_lane():
    assert hermes_chat.is_hermes_chat_model("openclaw-external")
    assert hermes_chat.is_hermes_chat_model("hermes-agent")
    assert not hermes_chat.is_hermes_chat_model("qwen3:4b")


def test_chat_without_a_link_fails_cleanly_and_never_reaches_hermes(local, stored, monkeypatch):
    async def no_hermes(*a, **k):
        raise AssertionError("must not resolve a Hermes model")

    monkeypatch.setattr(hermes_chat, "resolve_hermes_model", no_hermes)
    resp = run(hermes_chat.proxy_hermes_chat({"model": "openclaw-external", "messages": []}, object(), 7))
    assert resp.status_code == 400
    assert "No OpenClaw is linked" in json.loads(resp.body)["error"]["message"]


def test_chat_goes_to_the_linked_gateway_with_the_users_token(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    _save(USER, LAN_URL, TOKEN)
    _verify(USER)
    sent = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append((url, headers, json))
            return SimpleNamespace(status_code=200, json=lambda: {"choices": []})

    monkeypatch.setattr(hermes_chat.httpx, "AsyncClient", Client)
    resp = run(hermes_chat.proxy_hermes_chat(
        {"model": "openclaw-external", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2},
        object(), 7))
    assert resp.status_code == 200
    url, headers, body = sent[0]
    assert url == LAN_URL + "/v1/chat/completions" and headers["Authorization"] == "Bearer " + TOKEN
    assert body == {"model": "openclaw", "messages": [{"role": "user", "content": "hi"}], "stream": False,
                    "temperature": 0.2}


# -- status card -------------------------------------------------------------------------

def _services(monkeypatch, user_id=7):
    from owui_compat.integrations_status import probe_services

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
    services, _models = run(probe_services(request, SimpleNamespace(id=user_id)))
    return services["openclaw"]


def test_status_reports_the_users_link_state_as_optional(local, stored, monkeypatch):
    _gateway(monkeypatch, {MODELS: 200})
    card = _services(monkeypatch)
    assert card["status"] == "available" and card["reason"] == "not_linked" and "Optional" in card["detail"]

    _save(USER, LAN_URL, TOKEN)
    assert _services(monkeypatch)["status"] == "needs_setup"

    _verify(USER)
    assert _services(monkeypatch) == {"status": "ready", "detail": "Linked (optional)", "reason": "linked"}
    assert _services(monkeypatch, 8)["reason"] == "not_linked"

    _gateway(monkeypatch, {MODELS: 401})
    _verify(USER)
    card = _services(monkeypatch)
    assert card["status"] == "error" and card["reason"] == "link_error" and "token" in card["detail"]
