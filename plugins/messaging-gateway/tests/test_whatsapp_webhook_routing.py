"""WhatsApp webhook events go to the one connected adapter whose phone number id they name.

Real WhatsAppCloudAdapter instances with the Graph call replaced; no network.
"""

import asyncio
import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from control import ControlServer
from platforms.base import AdapterSpec
from platforms.whatsapp_cloud import WhatsAppCloudAdapter
from supervisor import AdapterSupervisor

H = {"X-Gateway-Token": "tok"}


class OfflineWhatsApp(WhatsAppCloudAdapter):
    """Connects unless the token is 'bogus', as Meta would reject it."""

    async def start(self):
        if self._token == "bogus" or any(not v for v in (self._token, self._phone_id, self._verify_token)):
            self._mark_error("Meta rejected the access token or phone number id")
            return
        if self._signature_required and not self._app_secret:
            self._mark_error("missing WHATSAPP_APP_SECRET.")
            return
        self._mark_connected("+1 555")
        await self._stop_event.wait()


def _spec(owner, *, token="good", phone="PNID", secret="", source="settings"):
    env = {"WHATSAPP_ACCESS_TOKEN": token, "WHATSAPP_PHONE_NUMBER_ID": phone, "WHATSAPP_VERIFY_TOKEN": "vt"}
    if secret:
        env["WHATSAPP_APP_SECRET"] = secret
    return AdapterSpec("whatsapp_cloud", owner, env, source=source)


def _event(phone="PNID", text="private note"):
    return json.dumps({"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone},
        "contacts": [{"wa_id": "15551234567", "profile": {"name": "Ann"}}],
        "messages": [{"from": "15551234567", "id": "wamid.1", "type": "text", "text": {"body": text}}],
    }}]}]}).encode()


def _post(client, raw, secret=None):
    headers = {}
    if secret:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhook/whatsapp_cloud", headers=H,
                       json={"headers": headers, "body_b64": base64.b64encode(raw).decode()})


async def _setup(*specs):
    inbound = []

    async def on_inbound(adapter, msg):
        inbound.append((adapter.owner_user_id, msg.text))

    sup = AdapterSupervisor(on_inbound, factory=OfflineWhatsApp)

    async def resync():
        return {"ok": True}

    await sup.sync(list(specs))
    await asyncio.sleep(0.01)
    return sup, ControlServer(token="tok", port=0, supervisor=sup, resync=resync), inbound


@pytest.mark.asyncio
async def test_attacker_adapter_with_bogus_token_cannot_take_the_victims_events():
    sup, ctl, inbound = await _setup(_spec(7, token="bogus"), _spec(9, secret="s3cret"))
    assert sup.get("whatsapp_cloud:7").status()["state"] == "error"
    with TestClient(ctl.app) as c:
        assert _post(c, _event(), "s3cret").status_code == 200
    assert inbound == [(9, "private note")]
    await sup.stop_all()


@pytest.mark.asyncio
async def test_settings_adapter_without_app_secret_never_connects_or_accepts_unsigned_events():
    sup, ctl, inbound = await _setup(_spec(7))
    assert sup.get("whatsapp_cloud:7").status()["state"] == "error"
    adapter = sup.get("whatsapp_cloud:7")
    adapter._mark_connected()  # even if it were connected, an unsigned body is dropped
    assert not await adapter.handle_webhook(_event(), {}, {})
    with TestClient(ctl.app) as c:
        assert _post(c, _event()).status_code == 403
    assert inbound == []
    await sup.stop_all()


@pytest.mark.asyncio
async def test_bad_signature_is_dropped_and_good_one_accepted():
    sup, ctl, inbound = await _setup(_spec(9, secret="s3cret"))
    with TestClient(ctl.app) as c:
        assert _post(c, _event(), "wrong").status_code == 403
        assert _post(c, _event()).status_code == 403
        assert _post(c, _event(), "s3cret").status_code == 200
    assert inbound == [(9, "private note")]
    await sup.stop_all()


@pytest.mark.asyncio
async def test_env_adapter_may_still_run_unsigned():
    sup, ctl, inbound = await _setup(_spec(None, source="env"))
    with TestClient(ctl.app) as c:
        assert _post(c, _event()).status_code == 200
    assert len(inbound) == 1
    await sup.stop_all()


@pytest.mark.asyncio
async def test_two_connected_adapters_claiming_one_id_are_both_refused():
    sup, ctl, inbound = await _setup(_spec(7, secret="a"), _spec(9, secret="b"))
    with TestClient(ctl.app) as c:
        assert _post(c, _event(), "a").status_code == 409
        assert _post(c, _event(), "b").status_code == 409
    assert inbound == []
    await sup.stop_all()


@pytest.mark.asyncio
async def test_event_for_a_different_id_goes_only_to_its_adapter():
    sup, ctl, inbound = await _setup(_spec(7, phone="ONE", secret="a"), _spec(9, phone="TWO", secret="b"))
    with TestClient(ctl.app) as c:
        assert _post(c, _event("TWO"), "b").status_code == 200
        assert _post(c, _event("TWO"), "a").status_code == 403  # signed for the wrong app
        assert _post(c, _event("NONE"), "a").status_code == 403
    assert inbound == [(9, "private note")]
    await sup.stop_all()
