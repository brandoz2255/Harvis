"""GatewayRunner: settings sync, inbound -> backend -> reply, and the pairing gate.

The backend is a fake bridge; adapters are in-memory. No network.
"""

import asyncio

import httpx
import pytest

import config as config_mod
from bridge import HarvisBridge
from config import GatewayConfig, env_fallback_specs
from gateway import GatewayRunner
from messaging_types import NO_USER_ERROR, InboundMessage, InboundResponse, Platform, RunStatus, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter


def _cfg(**kw):
    base = dict(backend_url="http://backend:8000", gateway_token="tok", enabled_platforms=(),
                poll_interval_s=0.01, poll_timeout_s=1, sync_interval_s=60, control_port=0, stub_enabled=False)
    base.update(kw)
    return GatewayConfig(**base)


class Recorder(BasePlatformAdapter):
    allowed_users_key = "ALLOWED"

    def __init__(self, spec):
        super().__init__(Platform(spec.platform), spec)
        self.sent = []

    async def start(self):
        self._mark_connected()
        await self._stop_event.wait()

    async def stop(self):
        self._stop_event.set()

    async def send_text(self, target, text, reply_to_message_id=None):
        self.sent.append((target.chat_id, text, reply_to_message_id))


class FakeBridge:
    def __init__(self, inbound_error=None, specs=None):
        self.inbound_error = inbound_error
        self.specs = specs
        self.posted, self.pairings, self.terminal = [], [], []

    async def fetch_config(self):
        return self.specs

    async def post_inbound(self, msg):
        self.posted.append(msg)
        if self.inbound_error:
            return InboundResponse(ok=False, error=self.inbound_error)
        return InboundResponse(ok=True, workspace_id="ws1")

    async def wait_for_terminal(self, workspace_id):
        return RunStatus(workspace_id=workspace_id, status="completed", final_summary="the answer")

    async def notify_terminal(self, workspace_id):
        self.terminal.append(workspace_id)

    async def request_pairing(self, **kw):
        self.pairings.append(kw)
        return {"ok": True, "request_id": "a1b2c3"}


def _msg(sender="555"):
    src = SessionSource(platform=Platform.TELEGRAM, chat_id=sender, sender_id=sender, sender_display_name="Ann",
                        is_dm=True)
    return InboundMessage(source=src, message_id="m1", text="hi")


@pytest.mark.asyncio
async def test_allowlisted_sender_is_answered_as_the_owner():
    bridge = FakeBridge()
    runner = GatewayRunner(_cfg(), bridge)
    ad = Recorder(AdapterSpec("telegram", 7, {"ALLOWED": "555"}))
    await runner.process_inbound(ad, _msg("555"))
    assert bridge.posted[0].fallback_user_id == 7
    assert ad.sent == [("555", "the answer", "m1")] and bridge.terminal == ["ws1"]


@pytest.mark.asyncio
async def test_unknown_sender_gets_a_pairing_code_once_and_nothing_is_relayed():
    bridge = FakeBridge(inbound_error=NO_USER_ERROR)
    runner = GatewayRunner(_cfg(), bridge)
    ad = Recorder(AdapterSpec("telegram", 7, {}))
    await runner.process_inbound(ad, _msg("999"))
    await runner.process_inbound(ad, _msg("999"))
    assert bridge.posted[0].fallback_user_id is None
    assert [p["owner_user_id"] for p in bridge.pairings] == [7, 7]  # request refreshed, notice not repeated
    assert len(ad.sent) == 1 and "a1b2c3" in ad.sent[0][1] and "the answer" not in ad.sent[0][1]


@pytest.mark.asyncio
async def test_env_adapter_without_owner_ignores_strangers_silently():
    bridge = FakeBridge(inbound_error=NO_USER_ERROR)
    runner = GatewayRunner(_cfg(), bridge)
    ad = Recorder(AdapterSpec("telegram", None, {}, source="env"))
    await runner.process_inbound(ad, _msg("999"))
    assert ad.sent == [] and bridge.pairings == []


@pytest.mark.asyncio
async def test_resync_keeps_running_adapters_when_backend_blips():
    bridge = FakeBridge(specs=[AdapterSpec("telegram", 7, {"T": "1"})])
    runner = GatewayRunner(_cfg(), bridge)
    runner.supervisor._factory = Recorder
    out = await runner.resync()
    assert out["backend_reachable"] and out["started"] == ["telegram:7"]
    bridge.specs = None  # backend unreachable
    out = await runner.resync()
    assert not out["backend_reachable"] and [a.key for a in runner.supervisor.adapters()] == ["telegram:7"]
    bridge.specs = []  # backend says: user disabled it
    out = await runner.resync()
    assert out["stopped"] == ["telegram:7"]
    await runner.supervisor.stop_all()


class Failing(Recorder):
    async def send_text(self, target, text, reply_to_message_id=None):
        raise RuntimeError("Telegram refused the message (403). Open the bot and press Start once.")


@pytest.mark.asyncio
async def test_send_test_reports_a_failed_send_instead_of_success():
    ad = Failing(AdapterSpec("telegram", 7, {"ALLOWED": "555"}))
    ad._mark_connected()
    ad._last_target = _msg("555").source
    ok, message = await ad.send_test("ping")
    assert not ok and "press Start" in message


def test_whatsapp_allowlist_matches_formatted_numbers():
    from platforms.whatsapp_cloud import WhatsAppCloudAdapter
    ad = WhatsAppCloudAdapter(AdapterSpec("whatsapp_cloud", 3, {"WHATSAPP_ALLOWED_USERS": "+1 555-000 1111, abc"}))
    assert ad.fallback_user_for("15550001111") == 3 and ad.fallback_user_for("15550002222") is None
    target = ad.default_test_target()
    assert target.chat_id == "15550001111" and target.sender_display_name == "+15550001111"


def test_signal_allowlist_normalises_numbers_and_keeps_uuids():
    from platforms.signal import SignalAdapter
    uuid = "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
    ad = SignalAdapter(AdapterSpec("signal", 4, {"SIGNAL_ALLOWED_USERS": f"+1 555-000 1111,{uuid}"}))
    assert ad.fallback_user_for("+15550001111") == 4 and ad.fallback_user_for(uuid) == 4
    assert ad.default_test_target().chat_id == "+15550001111"


def test_env_fallback_uses_catalog_keys(monkeypatch):
    for key in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "EAAB")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    specs = env_fallback_specs(_cfg(enabled_platforms=("whatsapp_cloud", "telegram", "nope")))
    assert [(s.platform, s.source) for s in specs] == [("whatsapp_cloud", "env")]
    assert specs[0].env == {"WHATSAPP_ACCESS_TOKEN": "EAAB", "WHATSAPP_PHONE_NUMBER_ID": "123"}
    assert set(config_mod.ENV_FALLBACK_KEYS["whatsapp_cloud"]) >= {"WHATSAPP_VERIFY_TOKEN", "WHATSAPP_ALLOWED_USERS"}


@pytest.mark.asyncio
async def test_bridge_fetch_config_parses_rows_and_returns_none_on_refusal():
    replies = {"status": 200}

    def handler(request):
        assert request.headers["X-Gateway-Token"] == "tok"
        if replies["status"] != 200:
            return httpx.Response(replies["status"], json={"detail": "no"})
        return httpx.Response(200, json={"adapters": [
            {"platform": "telegram", "user_id": 7, "env": {"TELEGRAM_BOT_TOKEN": "1:a", "X": None}},
            {"platform": ""}, "junk"]})

    bridge = HarvisBridge(_cfg())
    async with bridge:
        bridge._client = httpx.AsyncClient(base_url="http://backend:8000", headers={"X-Gateway-Token": "tok"},
                                           transport=httpx.MockTransport(handler))
        specs = await bridge.fetch_config()
        assert [(s.key, s.env, s.source) for s in specs] == [("telegram:7", {"TELEGRAM_BOT_TOKEN": "1:a"}, "settings")]
        replies["status"] = 401
        assert await bridge.fetch_config() is None
    await asyncio.sleep(0)
