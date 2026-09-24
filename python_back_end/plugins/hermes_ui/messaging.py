"""Messaging page routes: the platform cards.

The catalog is the reference gateway's static platform list (33 entries).
Seven of them (``messaging_gateway.SUPPORTED_PLATFORMS``) run in the
messaging-gateway sidecar, driven by what each user saves here: the gateway
pulls the settings, starts an adapter per (platform, user), and this page
shows the adapter's real state. The rest are visible but ``unsupported``.

Secrets are encrypted at rest and only ever echoed back redacted, like
/api/env. Nothing here claims "connected" unless the gateway said so.

Shapes: front_end/hermes-desktop-ui/src/api/messaging.ts and types/hermes.ts.
Pairing and webhook subscriptions live in messaging_pairing.py; the gateway
side (config export, pairing requests, provider webhooks) in messaging_gateway.py.
"""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import messaging_gateway, providers, settings_store
from .messaging_gateway import GATEWAY_START_COMMAND, SUPPORTED_PLATFORMS
from .messaging_pairing import (  # noqa: F401 — re-exported for callers and tests
    PAIRING_KEY, WEBHOOKS_KEY, pairing, pairing_approve, pairing_dismiss, pairing_revoke, webhooks,
    webhooks_create, webhooks_delete, webhooks_enable, webhooks_set_enabled,
)
from .messaging_pairing import router as pairing_router
from .rest import _pool, _uid

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])
router.include_router(pairing_router)

_CATALOG_PATH = Path(__file__).with_name("messaging_catalog.json")
MESSAGING_KEY = "messaging"
MAX_ENV_CHARS = 4000
TEST_MESSAGE = "Hello from Harvis — messaging is set up."

# What the Messaging page needs to know per platform beyond the catalog.
SETUP_HINTS: dict[str, str] = {
    "telegram": "Create a bot with @BotFather, paste its token, then press Start on the bot in Telegram. "
                "Add your numeric user id (from @userinfobot) to answer immediately; otherwise approve yourself "
                "under Pairing after your first message.",
    "discord": "Create an application at discord.com/developers, add a bot, enable the Message Content intent, "
               "invite it to your server, then paste the bot token.",
    "slack": "Create a Slack app with Socket Mode on: paste the bot token (xoxb-) and the app-level token (xapp-) "
             "with connections:write.",
    "matrix": "Log the bot account in once to get an access token (Element: Settings > Help & About > Access Token). "
              "Unencrypted rooms only; invites from allowed users are joined automatically.",
    "email": "Use a dedicated mailbox. Gmail and Outlook need an app password. Every unread mail from an allowed "
             "sender becomes a request and the answer goes back as a reply in the same thread.",
    "whatsapp_cloud": "Meta for Developers > WhatsApp > API setup: copy the phone number id and a permanent access "
                      "token, choose any verify token, then register the webhook URL shown below.",
    "signal": "Link signal-cli to a spare number, run it as signal-cli daemon --http in a container on the Harvis "
              "network, and enter its URL. Its HTTP port has no password, so never publish it. Harvis never holds "
              "the Signal keys.",
}


@lru_cache(maxsize=1)
def catalog() -> list[dict[str, Any]]:
    with _CATALOG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def catalog_entry(platform_id: str) -> dict[str, Any]:
    entry = next((e for e in catalog() if e["id"] == platform_id), None)
    if entry is None:
        raise HTTPException(404, f"unknown platform: {platform_id}")
    return entry


@lru_cache(maxsize=1)
def channel_keys() -> frozenset[str]:
    return frozenset(v["key"] for entry in catalog() for v in entry["env_vars"])


def redact(value: str) -> str:
    return ("…" + value[-4:]) if len(value) > 8 else "••••"


def _not_run_message(name: str) -> str:
    return f"Harvis does not run the {name} adapter yet; settings are saved for when it does."


def _gateway_stopped_message() -> str:
    return messaging_gateway.problem()


# ── platforms ────────────────────────────────────────────────────────────────

def _discord_state(app: Any) -> tuple[bool, str, str | None]:
    """(enabled, state, error_message) of the legacy in-process Discord bot."""
    if os.getenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "true").lower() != "true":
        return False, "disabled", "Discord is handed to the messaging-gateway sidecar."
    if os.getenv("DISCORD_WORKSPACE_ENABLED", "true").lower() in ("0", "false", "no"):
        return False, "disabled", None
    client = getattr(getattr(app, "state", None), "discord_client", None)
    if client is None:
        return True, "not_configured" if not os.getenv("DISCORD_BOT_TOKEN") else "startup_failed", None
    try:
        ready = bool(client.is_ready()) and not client.is_closed()
    except Exception:
        ready = False
    return True, "connected" if ready else "connecting", None


def _legacy_discord_active(app: Any) -> bool:
    return os.getenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "true").lower() == "true"


def _stored_var(saved: dict, key: str) -> tuple[bool, str | None]:
    """(is_set, redacted) for a per-user value; secrets keep only their tail."""
    value = (saved.get("env") or {}).get(key)
    if isinstance(value, dict):
        return bool(value.get("enc")), ("…" + value["tail"]) if value.get("tail") else "••••"
    if isinstance(value, str) and value:
        return True, redact(value)
    return False, None


_ADAPTER_STATES = {"starting": "connecting", "connected": "connected", "retrying": "error",
                   "error": "error", "stopped": "error"}


def _adapter_view(adapter: dict) -> tuple[str, str | None, str | None]:
    """(state, error_message, display) from one gateway adapter status."""
    state = _ADAPTER_STATES.get(str(adapter.get("state")), "connecting")
    error = adapter.get("error")
    if state == "error" and not error:
        error = "The adapter stopped; the gateway retries it within a minute."
    if adapter.get("state") == "retrying":
        error = f"Reconnecting: {error}"
    return state, error, adapter.get("display")


def platform_payload(entry: dict[str, Any], saved: dict, app: Any = None, gw: dict | None = None,
                     owner: int = 0) -> dict[str, Any]:
    pid = entry["id"]
    env_vars, set_keys = [], set()
    for var in entry["env_vars"]:
        value = os.getenv(var["key"], "") if pid in SUPPORTED_PLATFORMS else ""
        is_set, redacted = (True, redact(value)) if value else _stored_var(saved, var["key"])
        if is_set:
            set_keys.add(var["key"])
        env_vars.append({**var, "is_set": is_set, "redacted_value": redacted})
    configured = all(k in set_keys for k in entry["required_env"])
    supported = pid in SUPPORTED_PLATFORMS
    enabled = bool(saved.get("enabled"))
    adapter = messaging_gateway.adapter_for(gw, pid, owner) if supported else None
    display, can_test, runs_here = None, False, False
    if not supported:
        state, error = "unsupported", _not_run_message(entry["name"])
    elif adapter is not None:
        state, error, display = _adapter_view(adapter)
        can_test = bool(adapter.get("has_test_target")) and state == "connected"
        enabled = enabled or adapter.get("source") == "env"
    elif pid == "discord" and _legacy_discord_active(app):
        enabled, state, error = _discord_state(app)
        runs_here = True
        if state == "startup_failed":
            error = error or "The bot token is set but the bot did not start; check the backend log."
    elif not enabled:
        state, error = "disabled", None
    elif not configured:
        state, error = "not_configured", None
    elif gw is None:
        state, error = "gateway_stopped", _gateway_stopped_message()
    else:
        state, error = "connecting", None
    webhook = messaging_gateway.webhook_url(pid)
    webhook_note = None
    if pid in messaging_gateway.WEBHOOK_PLATFORMS and not webhook:
        webhook_note = ("This platform delivers messages by webhook, which needs a public HTTPS address. "
                        "Set HARVIS_PUBLIC_URL on the backend to show the URL to register.")
    return {
        "id": pid, "name": entry["name"], "description": entry["description"],
        "docs_url": entry["docs_url"], "env_vars": env_vars, "configured": configured,
        "enabled": enabled, "gateway_running": adapter is not None and state != "error", "state": state,
        "home_channel": None, "runs_on_harvis": runs_here, "supported": supported,
        "error_code": state if state in ("startup_failed", "gateway_stopped", "unsupported", "error") else None,
        "error_message": error, "updated_at": saved.get("updated_at"),
        "display": display, "can_test": can_test, "setup_hint": SETUP_HINTS.get(pid),
        "webhook_url": webhook, "webhook_note": webhook_note,
    }


async def _saved(pool, uid: int) -> dict[str, dict]:
    raw = await settings_store.get_key(pool, uid, MESSAGING_KEY, {})
    return raw if isinstance(raw, dict) else {}


@router.get("/messaging/platforms")
async def messaging_platforms(request: Request, user=Depends(get_current_user_optimized)):
    pool, uid = _pool(request), _uid(user)
    saved = await _saved(pool, uid)
    gw = await messaging_gateway.status()
    return {
        "env_path": "harvis backend .env",
        "gateway_start_command": GATEWAY_START_COMMAND,
        "gateway_reachable": gw is not None,
        "gateway_error": None if gw is not None else _gateway_stopped_message(),
        "gateway_last_sync_ok": bool((gw or {}).get("last_sync_ok")),
        "public_url": messaging_gateway.public_url() or None,
        "platforms": [platform_payload(e, saved.get(e["id"]) or {}, request.app, gw, uid) for e in catalog()],
    }


def _store_value(var: dict, value: str) -> Any:
    if var.get("is_password"):
        return {"enc": providers._encrypt(value), "tail": value[-4:] if len(value) > 8 else ""}
    return value


@router.put("/messaging/platforms/{platform_id}")
async def messaging_platform_update(platform_id: str, request: Request, user=Depends(get_current_user_optimized)):
    entry = catalog_entry(platform_id)
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    known = {v["key"]: v for v in entry["env_vars"]}
    pool, uid = _pool(request), _uid(user)
    saved_all = await _saved(pool, uid)
    saved = dict(saved_all.get(platform_id) or {})
    env = dict(saved.get("env") or {})
    if "enabled" in body:
        saved["enabled"] = bool(body["enabled"])
    for key, value in (body.get("env") or {}).items():
        if key not in known:
            raise HTTPException(400, f"{key} is not a {entry['name']} setting")
        if not isinstance(value, str) or len(value) > MAX_ENV_CHARS:
            raise HTTPException(400, f"{key} must be a string under {MAX_ENV_CHARS} characters")
        if value.strip():
            env[key] = _store_value(known[key], value.strip())
        else:
            env.pop(key, None)
    for key in body.get("clear_env") or []:
        env.pop(str(key), None)
    saved["env"], saved["updated_at"] = env, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    saved_all[platform_id] = saved
    await settings_store.set_key(pool, uid, MESSAGING_KEY, saved_all)
    supported = platform_id in SUPPORTED_PLATFORMS
    applied = await messaging_gateway.resync() if supported else False
    if not supported:
        message = _not_run_message(entry["name"])
    elif applied:
        message = "Saved. The gateway is applying it now."
    else:
        message = f"Saved. {_gateway_stopped_message()}"
    return {"ok": True, "platform": platform_id, "runs_on_harvis": False, "supported": supported,
            "gateway_applied": applied, "message": message}


@router.post("/messaging/platforms/{platform_id}/test")
async def messaging_platform_test(platform_id: str, request: Request, user=Depends(get_current_user_optimized)):
    entry = catalog_entry(platform_id)
    pool, uid = _pool(request), _uid(user)
    saved = (await _saved(pool, uid)).get(platform_id) or {}
    gw = await messaging_gateway.status(force=True)
    payload = platform_payload(entry, saved, request.app, gw, uid)
    if not payload["supported"]:
        return {"ok": False, "message": _not_run_message(entry["name"]), "state": payload["state"]}
    if payload["runs_on_harvis"]:
        ok = payload["state"] == "connected"
        message = "The Discord bot is connected." if ok else (payload["error_message"] or f"Discord is {payload['state']}.")
        return {"ok": ok, "message": message, "state": payload["state"]}
    if gw is None:
        return {"ok": False, "message": _gateway_stopped_message(), "state": payload["state"]}
    if payload["state"] != "connected":
        return {"ok": False, "message": payload["error_message"] or f"{entry['name']} is {payload['state']}.",
                "state": payload["state"]}
    adapter = messaging_gateway.adapter_for(gw, platform_id, uid) or {}
    key = f"{platform_id}:{adapter.get('owner_user_id') if adapter.get('source') != 'env' else 'env'}"
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    text = str((body or {}).get("text") or TEST_MESSAGE)[:2000]
    result = await messaging_gateway.send_test(key, text)
    return {**result, "state": payload["state"]}
