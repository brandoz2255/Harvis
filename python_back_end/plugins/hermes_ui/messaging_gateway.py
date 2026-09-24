"""The backend's side of the messaging-gateway sidecar.

Two directions, one shared secret (``MESSAGING_GATEWAY_TOKEN``):

* Gateway -> backend (``/api/messaging/gateway/*``, token-checked): the
  gateway pulls every user's enabled, fully-configured platforms with their
  secrets decrypted, and files pairing requests for senders it does not know.
* Backend -> gateway (control port, ``MESSAGING_GATEWAY_URL``): the Messaging
  page reads live adapter state, saving settings asks for an immediate
  resync, "Send test message" and provider webhooks are relayed through.

Provider webhooks (``/api/messaging/webhooks/{platform}``) are the only
unauthenticated routes; the adapter verifies the provider's own signature.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import providers, settings_store
from .store import SETTINGS_KEY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messaging", tags=["messaging"])

# Mirror of plugins/messaging-gateway/supervisor.py SUPPORTED_PLATFORMS (minus stub):
# used when the gateway is unreachable so cards still say "supported, stopped".
SUPPORTED_PLATFORMS: tuple[str, ...] = ("telegram", "slack", "discord", "matrix", "email", "whatsapp_cloud", "signal")
WEBHOOK_PLATFORMS: tuple[str, ...] = ("whatsapp_cloud",)
GATEWAY_START_COMMAND = "COMPOSE_PROFILES=messaging docker compose up -d harvis-messaging-gateway"
MESSAGING_KEY = "messaging"
PAIRING_KEY = "pairing"
MAX_PENDING = 50
STATUS_CACHE_S = 3.0
_STATUS_TIMEOUT_S = 2.0


def gateway_url() -> str:
    return (os.getenv("MESSAGING_GATEWAY_URL") or "http://harvis-messaging-gateway:18800").rstrip("/")


def gateway_token() -> str:
    return os.getenv("MESSAGING_GATEWAY_TOKEN", "")


def public_url() -> str:
    return (os.getenv("HARVIS_PUBLIC_URL") or "").strip().rstrip("/")


def webhook_url(platform: str) -> Optional[str]:
    base = public_url()
    return f"{base}/api/messaging/webhooks/{platform}" if base and platform in WEBHOOK_PLATFORMS else None


# ── backend -> gateway ───────────────────────────────────────────────────────

_status_cache: dict[str, Any] = {"at": 0.0, "value": None, "problem": None}


async def _call(method: str, path: str, *, timeout: float = 5.0, **kwargs) -> Optional[httpx.Response]:
    token = gateway_token()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, gateway_url() + path, headers={"X-Gateway-Token": token}, **kwargs)
    except httpx.HTTPError as e:
        logger.debug("gateway %s %s unreachable: %s", method, path, e.__class__.__name__)
        return None


def _problem_for(r: Optional[httpx.Response]) -> Optional[str]:
    """Why the gateway's status is unavailable, in words the Messaging page can show."""
    if not gateway_token():
        return ("Messaging needs a shared secret: set MESSAGING_GATEWAY_TOKEN in the Harvis .env (any long random "
                f"string), recreate the backend, then start the gateway with: {GATEWAY_START_COMMAND}")
    if r is None:
        return f"The messaging gateway is not running. Start it with: {GATEWAY_START_COMMAND}"
    if r.status_code == 401:
        return "The messaging gateway rejected the backend's token: MESSAGING_GATEWAY_TOKEN must match in both containers."
    if r.status_code == 404:
        return ("The messaging gateway is running an older build without the settings API. "
                "Restart it: docker restart harvis-messaging-gateway")
    if r.status_code != 200:
        return f"The messaging gateway answered http {r.status_code}."
    return None


async def status(force: bool = False) -> Optional[dict]:
    """The gateway's /status, or None when it is not running / not reachable."""
    now = time.time()
    if not force and now - _status_cache["at"] < STATUS_CACHE_S:
        return _status_cache["value"]
    r = await _call("GET", "/status", timeout=_STATUS_TIMEOUT_S)
    problem = _problem_for(r)
    value = None
    if problem is None:
        try:
            value = r.json()
        except ValueError:
            problem = "The messaging gateway returned a non-JSON status."
    _status_cache.update(at=now, value=value if isinstance(value, dict) else None, problem=problem)
    return _status_cache["value"]


def problem() -> str:
    """Last reason the gateway was unusable; call after ``status()``."""
    return _status_cache.get("problem") or _problem_for(None) or ""


async def resync() -> bool:
    """Ask the gateway to pull settings now; False when it is not running."""
    r = await _call("POST", "/resync", timeout=5.0)
    _status_cache["at"] = 0.0
    return r is not None and r.status_code == 200


async def send_test(key: str, text: str) -> dict:
    r = await _call("POST", "/send-test", timeout=20.0, json={"key": key, "text": text})
    if r is None or r.status_code != 200:
        return {"ok": False, "message": _problem_for(r) or f"gateway answered http {r.status_code}"}
    data = r.json()
    return {"ok": bool(data.get("ok")), "message": str(data.get("message") or "")}


def adapter_for(gw: Optional[dict], platform: str, owner: int) -> Optional[dict]:
    """This user's adapter status, else the env-configured one for the platform."""
    adapters = (gw or {}).get("adapters") or {}
    return adapters.get(f"{platform}:{owner}") or adapters.get(f"{platform}:env")


# ── config export (gateway -> backend) ───────────────────────────────────────

async def load_all_messaging(pool) -> list[tuple[int, dict]]:
    """(user_id, messaging section) for every user who saved one."""
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, settings->$1->$2 AS messaging FROM owui_user_settings "
            "WHERE settings->$1 ? $2", SETTINGS_KEY, MESSAGING_KEY)
    out = []
    for row in rows:
        raw = row["messaging"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                continue
        if isinstance(raw, dict):
            out.append((int(row["user_id"]), raw))
    return out


def _plain(value: Any) -> str:
    if isinstance(value, dict):
        enc = value.get("enc")
        try:
            return providers._decrypt(enc) if isinstance(enc, str) and enc else ""
        except Exception:  # noqa: BLE001 — a bad key must not break every other adapter
            logger.warning("messaging: could not decrypt a stored secret; skipping it")
            return ""
    return value if isinstance(value, str) else ""


def adapter_specs(user_id: int, section: dict, catalog: list[dict]) -> list[dict]:
    """Specs for the gateway: enabled, supported platforms with every required var set."""
    specs = []
    for entry in catalog:
        pid = entry["id"]
        saved = section.get(pid)
        if pid not in SUPPORTED_PLATFORMS or not isinstance(saved, dict) or not saved.get("enabled"):
            continue
        env = {k: _plain(v) for k, v in (saved.get("env") or {}).items() if isinstance(k, str)}
        env = {k: v for k, v in env.items() if v}
        if any(k not in env for k in entry.get("required_env") or []):
            continue
        specs.append({"platform": pid, "user_id": user_id, "env": env, "updated_at": saved.get("updated_at")})
    return specs


def _require_gateway_token(x_gateway_token: str = Header(default="")) -> None:
    from plugins.messaging.routes import require_gateway_token
    require_gateway_token(x_gateway_token)


@router.get("/gateway/config", dependencies=[Depends(_require_gateway_token)])
async def gateway_config(request: Request):
    from .messaging import catalog
    adapters: list[dict] = []
    for user_id, section in await load_all_messaging(request.app.state.pg_pool):
        adapters.extend(adapter_specs(user_id, section, catalog()))
    return {"adapters": adapters, "generated_at": time.time()}


# ── pairing requests (gateway -> backend) ────────────────────────────────────

async def add_pending(pool, owner: int, platform: str, sender_id: str, sender_name: Optional[str],
                      chat_id: Optional[str]) -> str:
    """Queue a pairing request for the owner; one per (platform, sender)."""
    raw = await settings_store.get_key(pool, owner, PAIRING_KEY, {})
    state = raw if isinstance(raw, dict) else {}
    pending = [r for r in state.get("pending") or [] if isinstance(r, dict)]
    approved = [r for r in state.get("approved") or [] if isinstance(r, dict)]
    for row in pending:
        if row.get("platform") == platform and str(row.get("user_id")) == sender_id:
            return str(row.get("request_id") or "")
    request_id = secrets.token_hex(3)
    pending.append({"platform": platform, "request_id": request_id, "user_id": sender_id,
                    "user_name": sender_name or sender_id, "chat_id": chat_id, "created": time.time()})
    state["pending"], state["approved"] = pending[-MAX_PENDING:], approved
    await settings_store.set_key(pool, owner, PAIRING_KEY, state)
    return request_id


@router.post("/gateway/pairing-request", dependencies=[Depends(_require_gateway_token)])
async def gateway_pairing_request(request: Request):
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    try:
        owner = int(body.get("owner_user_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "owner_user_id must be an integer")
    platform = str(body.get("platform") or "")[:64]
    sender_id = str(body.get("sender_id") or "")[:200]
    if not platform or not sender_id:
        raise HTTPException(400, "platform and sender_id are required")
    request_id = await add_pending(request.app.state.pg_pool, owner, platform, sender_id,
                                   str(body.get("sender_name") or "")[:200] or None,
                                   str(body.get("chat_id") or "")[:200] or None)
    return {"ok": True, "request_id": request_id}


# ── provider webhooks (public) ───────────────────────────────────────────────

@router.get("/webhooks/{platform}")
async def webhook_verify(platform: str, request: Request):
    if platform not in WEBHOOK_PLATFORMS:
        raise HTTPException(404, "no webhook receiver for that platform")
    r = await _call("GET", f"/webhook/{platform}", timeout=5.0, params=dict(request.query_params))
    if r is None:
        raise HTTPException(503, "messaging gateway is not running")
    if r.status_code != 200:
        raise HTTPException(403, "verification rejected")
    return PlainTextResponse(r.text)


@router.post("/webhooks/{platform}")
async def webhook_event(platform: str, request: Request):
    if platform not in WEBHOOK_PLATFORMS:
        raise HTTPException(404, "no webhook receiver for that platform")
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "payload too large")
    forward = {
        "method": "POST",
        "query": dict(request.query_params),
        "headers": {k: v for k, v in request.headers.items() if k.lower().startswith("x-") or k.lower() == "content-type"},
        "body_b64": base64.b64encode(raw).decode(),
    }
    r = await _call("POST", f"/webhook/{platform}", timeout=10.0, json=forward)
    if r is None:
        raise HTTPException(503, "messaging gateway is not running")
    if r.status_code != 200:
        raise HTTPException(403, "event rejected")
    return {"ok": True}


async def resync_soon() -> None:
    """Fire-and-forget resync after a settings save; never blocks the request for long."""
    try:
        await asyncio.wait_for(resync(), timeout=4.0)
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
        pass
