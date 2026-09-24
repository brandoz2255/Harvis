"""Supervisor reconcile + control-port auth, with fake adapters (no network)."""

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

import supervisor as sup_mod
from control import ControlServer
from messaging_types import Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter
from supervisor import AdapterSupervisor


class FakeAdapter(BasePlatformAdapter):
    allowed_users_key = "ALLOWED"
    instances: list = []

    def __init__(self, spec):
        super().__init__(Platform(spec.platform), spec)
        self.sent: list = []
        FakeAdapter.instances.append(self)

    async def start(self):
        if self.spec.get("TOKEN") == "bad":
            self._mark_error("rejected token")
            return
        self._mark_connected("fake")
        await self._stop_event.wait()

    async def stop(self):
        self._stop_event.set()
        self._mark_disconnected()

    async def send_text(self, target, text, reply_to_message_id=None):
        self.sent.append((target.chat_id, text))

    def default_test_target(self):
        return SessionSource(platform=self.platform, chat_id="c1", sender_id="s1", sender_display_name="S1", is_dm=True)


class WebhookAdapter(FakeAdapter):
    def verify_webhook(self, query):
        return query.get("hub.challenge") if query.get("hub.verify_token") == "vt" else None

    async def handle_webhook(self, raw, headers, query):
        self.sent.append(("webhook", raw, headers.get("x-sig")))
        return json.loads(raw).get("ours", False)


async def _noop(adapter, msg):
    return None


@pytest.fixture(autouse=True)
def _reset():
    FakeAdapter.instances = []


@pytest.mark.asyncio
async def test_sync_starts_restarts_and_stops_on_fingerprint_change():
    sup = AdapterSupervisor(_noop, factory=FakeAdapter)
    tg = AdapterSpec("telegram", 7, {"TOKEN": "a"})
    changed = await sup.sync([tg])
    assert changed["started"] == ["telegram:7"]
    await asyncio.sleep(0)
    assert sup.get("telegram:7").status()["state"] == "connected"

    changed = await sup.sync([AdapterSpec("telegram", 7, {"TOKEN": "b"})])
    assert changed["restarted"] == ["telegram:7"] and len(FakeAdapter.instances) == 2

    changed = await sup.sync([AdapterSpec("telegram", 7, {"TOKEN": "b"})])
    assert changed == {"started": [], "restarted": [], "stopped": []}

    changed = await sup.sync([])
    assert changed["stopped"] == ["telegram:7"] and sup.adapters() == []
    await sup.stop_all()


@pytest.mark.asyncio
async def test_settings_spec_beats_env_spec_and_unsupported_is_skipped():
    sup = AdapterSupervisor(_noop, factory=FakeAdapter)
    env = AdapterSpec("slack", None, {"TOKEN": "env"}, source="env")
    settings = AdapterSpec("slack", None, {"TOKEN": "settings"}, source="settings")
    await sup.sync([env, settings, AdapterSpec("sms", 1, {})])
    assert list(sup.status()["adapters"]) == ["slack:env"]
    assert sup.get("slack:env").spec.get("TOKEN") == "settings"
    await sup.stop_all()


@pytest.mark.asyncio
async def test_failed_adapter_is_reported_and_not_restarted_within_backoff(monkeypatch):
    sup = AdapterSupervisor(_noop, factory=FakeAdapter)
    bad = AdapterSpec("discord", 3, {"TOKEN": "bad"})
    await sup.sync([bad])
    await asyncio.sleep(0.01)
    st = sup.status()["adapters"]["discord:3"]
    assert st["state"] == "error" and st["error"] == "rejected token"
    changed = await sup.sync([bad])
    assert changed["restarted"] == []
    monkeypatch.setattr(sup_mod, "RETRY_AFTER_S", 0.0)
    changed = await sup.sync([bad])
    assert changed["restarted"] == ["discord:3"]
    await sup.stop_all()


@pytest.mark.asyncio
async def test_build_failure_shows_as_error_status():
    def boom(spec):
        raise ImportError("no such lib")
    sup = AdapterSupervisor(_noop, factory=boom)
    await sup.sync([AdapterSpec("matrix", 5, {})])
    st = sup.status()["adapters"]["matrix:5"]
    assert st["state"] == "error" and "no such lib" in st["error"] and st["owner_user_id"] == 5


def _control(factory=FakeAdapter, token="tok"):
    sup = AdapterSupervisor(_noop, factory=factory)
    resync_calls = []

    async def resync():
        resync_calls.append(1)
        return {"ok": True}

    ctl = ControlServer(token=token, port=0, supervisor=sup, resync=resync)
    return sup, ctl, resync_calls


def test_control_requires_token_except_health():
    sup, ctl, _ = _control()
    with TestClient(ctl.app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/status").status_code == 401
        assert c.get("/status", headers={"X-Gateway-Token": "wrong"}).status_code == 401
        assert c.get("/status", headers={"X-Gateway-Token": "tok"}).json()["ok"] is True
    _, ctl_no_token, _ = _control(token="")
    with TestClient(ctl_no_token.app) as c:
        assert c.get("/status", headers={"X-Gateway-Token": "tok"}).status_code == 503


@pytest.mark.asyncio
async def test_control_send_test_and_resync():
    sup, ctl, resync_calls = _control()
    await sup.sync([AdapterSpec("telegram", 7, {"TOKEN": "a"})])
    await asyncio.sleep(0)
    h = {"X-Gateway-Token": "tok"}
    with TestClient(ctl.app) as c:
        r = c.post("/send-test", json={"key": "telegram:7", "text": "hi"}, headers=h).json()
        assert r["ok"] is True and "S1" in r["message"]
        assert sup.get("telegram:7").sent == [("c1", "hi")]
        r = c.post("/send-test", json={"key": "telegram:9"}, headers=h).json()
        assert r["ok"] is False
        assert c.post("/resync", headers=h).json()["ok"] is True and resync_calls
    await sup.stop_all()


@pytest.mark.asyncio
async def test_control_webhook_verify_and_relay():
    sup, ctl, _ = _control(factory=WebhookAdapter)
    await sup.sync([AdapterSpec("whatsapp_cloud", 2, {"TOKEN": "a"})])
    await asyncio.sleep(0)
    h = {"X-Gateway-Token": "tok"}
    with TestClient(ctl.app) as c:
        r = c.get("/webhook/whatsapp_cloud", params={"hub.verify_token": "vt", "hub.challenge": "123"}, headers=h)
        assert r.status_code == 200 and r.text == "123"
        assert c.get("/webhook/whatsapp_cloud", params={"hub.verify_token": "no"}, headers=h).status_code == 403
        body = base64.b64encode(b'{"ours": true}').decode()
        r = c.post("/webhook/whatsapp_cloud", json={"headers": {"X-Sig": "s"}, "body_b64": body}, headers=h)
        assert r.status_code == 200
        assert sup.get("whatsapp_cloud:2").sent[-1] == ("webhook", b'{"ours": true}', "s")
        body = base64.b64encode(b'{"ours": false}').decode()
        assert c.post("/webhook/whatsapp_cloud", json={"body_b64": body}, headers=h).status_code == 403
        assert c.post("/webhook/telegram", json={"body_b64": body}, headers=h).status_code == 403
    await sup.stop_all()
