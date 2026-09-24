"""Messaging page <-> gateway sidecar contract: live states, settings export,
pairing requests, test messages and provider webhook relay. The gateway and
the database are faked; nothing here opens a socket."""
import asyncio
import copy
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import messaging, messaging_gateway, messaging_pairing, settings_store  # noqa: E402

USER = {"id": 7}


class FakeRequest:
    def __init__(self, body=None, query=None, headers=None):
        self._body = body
        self.query_params = query or {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=None))
        self.headers = headers or {}

    async def json(self):
        return self._body

    async def body(self):
        return self._body or b""


def run(coro):
    return asyncio.run(coro)


def http_status(coro):
    with pytest.raises(HTTPException) as info:
        run(coro)
    return info.value.status_code


@pytest.fixture
def section(monkeypatch):
    data: dict[int, dict] = {}

    async def read_section(pool, uid):
        return copy.deepcopy(data.setdefault(uid, {}))

    async def write_patch(pool, uid, patch):
        data.setdefault(uid, {}).update(copy.deepcopy(patch))
        return copy.deepcopy(data[uid])

    monkeypatch.setattr(settings_store, "read_section", read_section)
    monkeypatch.setattr(settings_store, "write_patch", write_patch)
    monkeypatch.setattr(messaging.providers, "_encrypt", lambda v: "enc(" + v + ")")
    monkeypatch.setattr(messaging.providers, "_decrypt", lambda v: v[4:-1] if v.startswith("enc(") else v)
    monkeypatch.setenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "false")
    monkeypatch.delenv("HARVIS_PUBLIC_URL", raising=False)
    return data


@pytest.fixture
def gateway(monkeypatch):
    """A fake gateway: ``state['status']`` is what /status returns (None = not running)."""
    state = {"status": None, "resyncs": 0, "sent": []}

    async def status(force=False):
        return state["status"]

    async def resync():
        state["resyncs"] += 1
        return state["status"] is not None

    async def send_test(key, text):
        state["sent"].append((key, text))
        return {"ok": True, "message": f"sent via {key}"}

    monkeypatch.setattr(messaging_gateway, "status", status)
    monkeypatch.setattr(messaging_gateway, "resync", resync)
    monkeypatch.setattr(messaging_gateway, "send_test", send_test)
    return state


def _adapter(platform, owner, state="connected", error=None, source="settings", test=True):
    return {"platform": platform, "owner_user_id": owner, "state": state, "error": error, "since": 0,
            "display": "@bot", "source": source, "fingerprint": "abc", "has_test_target": test}


def _row(listing, pid):
    return next(p for p in listing["platforms"] if p["id"] == pid)


def test_states_follow_the_gateway_not_the_settings(section, gateway):
    run(messaging.messaging_platform_update(
        "telegram", FakeRequest({"enabled": True, "env": {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFtoken"}}), USER))
    run(messaging.messaging_platform_update("matrix", FakeRequest({"enabled": True}), USER))
    assert gateway["resyncs"] == 2  # every save pings the gateway

    listing = run(messaging.messaging_platforms(FakeRequest(), USER))
    assert listing["gateway_reachable"] is False
    assert _row(listing, "telegram")["state"] == "gateway_stopped"
    assert _row(listing, "matrix")["state"] == "not_configured"
    assert _row(listing, "slack")["state"] == "disabled"
    assert _row(listing, "sms")["state"] == "unsupported" and _row(listing, "sms")["supported"] is False

    gateway["status"] = {"ok": True, "last_sync_ok": True, "adapters": {
        "telegram:7": _adapter("telegram", 7),
        "signal:env": _adapter("signal", None, state="error", error="daemon unreachable", source="env"),
        "slack:9": _adapter("slack", 9),
    }}
    listing = run(messaging.messaging_platforms(FakeRequest(), USER))
    tg = _row(listing, "telegram")
    assert tg["state"] == "connected" and tg["gateway_running"] and tg["can_test"] and tg["display"] == "@bot"
    sig = _row(listing, "signal")
    assert sig["state"] == "error" and sig["error_message"] == "daemon unreachable" and sig["enabled"] is True
    assert _row(listing, "slack")["state"] == "disabled"  # user 9's adapter is not ours
    assert _row(listing, "matrix")["state"] == "not_configured"
    assert "123456" not in str(listing)


def test_saved_but_not_yet_started_is_connecting_and_retrying_is_error(section, gateway):
    run(messaging.messaging_platform_update(
        "telegram", FakeRequest({"enabled": True, "env": {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFtoken"}}), USER))
    gateway["status"] = {"ok": True, "adapters": {}}
    assert _row(run(messaging.messaging_platforms(FakeRequest(), USER)), "telegram")["state"] == "connecting"
    gateway["status"]["adapters"]["telegram:7"] = _adapter("telegram", 7, state="retrying", error="network: ReadTimeout")
    row = _row(run(messaging.messaging_platforms(FakeRequest(), USER)), "telegram")
    assert row["state"] == "error" and row["error_message"].startswith("Reconnecting:")


def test_whatsapp_needs_public_url(section, gateway, monkeypatch):
    row = _row(run(messaging.messaging_platforms(FakeRequest(), USER)), "whatsapp_cloud")
    assert row["webhook_url"] is None and "HARVIS_PUBLIC_URL" in row["webhook_note"]
    assert [v["key"] for v in row["env_vars"] if v["required"]] == [
        "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN"]
    monkeypatch.setenv("HARVIS_PUBLIC_URL", "https://harvis.example.com/")
    row = _row(run(messaging.messaging_platforms(FakeRequest(), USER)), "whatsapp_cloud")
    assert row["webhook_url"] == "https://harvis.example.com/api/messaging/webhooks/whatsapp_cloud"
    assert row["webhook_note"] is None


def test_test_message_goes_through_the_gateway(section, gateway):
    run(messaging.messaging_platform_update(
        "telegram", FakeRequest({"enabled": True, "env": {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFtoken"}}), USER))
    res = run(messaging.messaging_platform_test("telegram", FakeRequest(), USER))
    assert res["ok"] is False and "docker compose" in res["message"]
    gateway["status"] = {"ok": True, "adapters": {"telegram:7": _adapter("telegram", 7)}}
    res = run(messaging.messaging_platform_test("telegram", FakeRequest(), USER))
    assert res["ok"] and gateway["sent"] == [("telegram:7", messaging.TEST_MESSAGE)]
    gateway["status"] = {"ok": True, "adapters": {"telegram:env": _adapter("telegram", None, source="env")}}
    run(messaging.messaging_platform_test("telegram", FakeRequest(), USER))
    assert gateway["sent"][-1][0] == "telegram:env"
    res = run(messaging.messaging_platform_test("sms", FakeRequest(), USER))
    assert res["ok"] is False and res["state"] == "unsupported"


def test_config_export_decrypts_only_enabled_and_complete_platforms(section):
    run(messaging.messaging_platform_update(
        "telegram", FakeRequest({"enabled": True, "env": {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFtoken",
                                                          "TELEGRAM_ALLOWED_USERS": "42"}}), USER))
    run(messaging.messaging_platform_update("matrix", FakeRequest({"enabled": True, "env": {"MATRIX_USER_ID": "@b:hs"}}), USER))
    run(messaging.messaging_platform_update("slack", FakeRequest({"enabled": False, "env": {"SLACK_BOT_TOKEN": "xoxb-1234567", "SLACK_APP_TOKEN": "xapp-1234567"}}), USER))
    specs = messaging_gateway.adapter_specs(7, section[7][messaging.MESSAGING_KEY], messaging.catalog())
    assert [s["platform"] for s in specs] == ["telegram"]
    assert specs[0]["user_id"] == 7
    assert specs[0]["env"] == {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFtoken", "TELEGRAM_ALLOWED_USERS": "42"}


def test_gateway_config_route_requires_the_shared_token(section, monkeypatch):
    monkeypatch.setenv("MESSAGING_GATEWAY_TOKEN", "shared-secret")
    with pytest.raises(HTTPException) as info:
        messaging_gateway._require_gateway_token("nope")
    assert info.value.status_code == 401
    messaging_gateway._require_gateway_token("shared-secret")
    monkeypatch.delenv("MESSAGING_GATEWAY_TOKEN")
    with pytest.raises(HTTPException) as info:
        messaging_gateway._require_gateway_token("shared-secret")
    assert info.value.status_code == 503

    async def rows(pool):
        return [(7, {"telegram": {"enabled": True, "env": {"TELEGRAM_BOT_TOKEN": {"enc": "enc(1:tok)", "tail": ""}}}}),
                (8, {"telegram": {"enabled": True, "env": {}}})]
    monkeypatch.setattr(messaging_gateway, "load_all_messaging", rows)
    out = run(messaging_gateway.gateway_config(FakeRequest()))
    assert out["adapters"] == [{"platform": "telegram", "user_id": 7, "env": {"TELEGRAM_BOT_TOKEN": "1:tok"}, "updated_at": None}]


def test_pairing_request_then_approve_links_the_sender(section, monkeypatch):
    links = []

    async def link_sender(pool, owner, platform, identifier, name):
        links.append(("link", owner, platform, identifier, name))

    async def unlink_sender(pool, owner, platform, identifier):
        links.append(("unlink", owner, platform, identifier))

    monkeypatch.setattr(messaging_pairing, "link_sender", link_sender)
    monkeypatch.setattr(messaging_pairing, "unlink_sender", unlink_sender)

    first = run(messaging_gateway.gateway_pairing_request(FakeRequest(
        {"owner_user_id": 7, "platform": "telegram", "sender_id": "555", "sender_name": "Ann", "chat_id": "555"})))
    again = run(messaging_gateway.gateway_pairing_request(FakeRequest(
        {"owner_user_id": 7, "platform": "telegram", "sender_id": "555"})))
    assert first["request_id"] == again["request_id"]  # one request per sender
    assert http_status(messaging_gateway.gateway_pairing_request(FakeRequest({"platform": "x", "sender_id": "1"}))) == 400

    listing = run(messaging.pairing(FakeRequest(), USER))
    assert len(listing["pending"]) == 1 and listing["pending"][0]["user_name"] == "Ann"
    approved = run(messaging.pairing_approve(FakeRequest({"platform": "telegram", "request_id": first["request_id"]}), USER))
    assert approved["user"]["user_id"] == "555"
    assert links == [("link", 7, "telegram", "555", "Ann")]
    run(messaging.pairing_revoke(FakeRequest({"platform": "telegram", "user_id": "555"}), USER))
    assert links[-1] == ("unlink", 7, "telegram", "555")
    run(messaging_gateway.gateway_pairing_request(FakeRequest({"owner_user_id": 7, "platform": "signal", "sender_id": "+1"})))
    rid = run(messaging.pairing(FakeRequest(), USER))["pending"][0]["request_id"]
    assert run(messaging.pairing_dismiss(FakeRequest({"platform": "signal", "request_id": rid}), USER)) == {"ok": True}
    assert run(messaging.pairing(FakeRequest(), USER))["pending"] == []


def test_public_webhook_relays_to_the_gateway(monkeypatch):
    calls = []

    class R:
        def __init__(self, status_code, text=""):
            self.status_code, self.text = status_code, text

    async def call(method, path, timeout=5.0, **kw):
        calls.append((method, path, kw))
        return R(200, "challenge-1") if method == "GET" else R(200)

    monkeypatch.setattr(messaging_gateway, "_call", call)
    r = run(messaging_gateway.webhook_verify("whatsapp_cloud", FakeRequest(query={"hub.challenge": "challenge-1"})))
    assert r.body == b"challenge-1"
    out = run(messaging_gateway.webhook_event("whatsapp_cloud", FakeRequest(
        body=b'{"entry": []}', headers={"X-Hub-Signature-256": "sha256=abc", "Cookie": "no"})))
    assert out == {"ok": True}
    forwarded = calls[-1][2]["json"]
    assert forwarded["body_b64"] and forwarded["headers"] == {"X-Hub-Signature-256": "sha256=abc"}
    assert http_status(messaging_gateway.webhook_event("telegram", FakeRequest(body=b"{}"))) == 404

    async def down(method, path, timeout=5.0, **kw):
        return None
    monkeypatch.setattr(messaging_gateway, "_call", down)
    assert http_status(messaging_gateway.webhook_event("whatsapp_cloud", FakeRequest(body=b"{}"))) == 503


def test_gateway_problem_names_the_actual_fix(monkeypatch):
    import httpx

    monkeypatch.delenv("MESSAGING_GATEWAY_TOKEN", raising=False)
    assert "set MESSAGING_GATEWAY_TOKEN" in messaging_gateway._problem_for(None)
    monkeypatch.setenv("MESSAGING_GATEWAY_TOKEN", "t")
    assert "not running" in messaging_gateway._problem_for(None)
    assert "must match" in messaging_gateway._problem_for(httpx.Response(401))
    assert "docker restart harvis-messaging-gateway" in messaging_gateway._problem_for(httpx.Response(404))
    assert messaging_gateway._problem_for(httpx.Response(200, json={})) is None

    async def outdated(method, path, **kw):
        return httpx.Response(404)

    monkeypatch.setattr(messaging_gateway, "_call", outdated)
    assert run(messaging_gateway.send_test("telegram:7", "hi")) == {
        "ok": False, "message": messaging_gateway._problem_for(httpx.Response(404))}
    messaging_gateway._status_cache["at"] = 0.0
    assert run(messaging_gateway.status(force=True)) is None and "older build" in messaging_gateway.problem()
