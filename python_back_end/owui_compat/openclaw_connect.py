"""Link your own OpenClaw — an OPTIONAL external agent, modeled on `hermes_connect.py`.

Hermes is the recommended agent. OpenClaw is legacy: Harvis no longer bundles a gateway, so
this is only for someone who already runs one. They save the gateway's URL + token, verify it,
and Chat can then route to it (model `openclaw-external`, see `hermes_chat.py`). It is never
the default and never falls back to anything: unlinked means nothing here runs.

Storage: settings.integrations.openclaw_external = {url, token_enc, verified_at, last_error}
(RMW, no migration). The token is Fernet-encrypted at rest and NEVER returned to the client.
URL rules and the shared-host SSRF guard are Hermes's own (`hermes_connect`), not a copy.

The gateway speaks websockets on its main port; its OpenAI-compatible HTTP API is on the same
port when `gateway.http.endpoints.chatCompletions` is on. A pasted ws://host:18789 is therefore
read as http://host:18789, so the address a user already has works unchanged.
"""

from __future__ import annotations

import json
import logging
from time import time
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from plugins.hermes_ui import providers

from . import hermes_connect as _hc

logger = logging.getLogger(__name__)

_KEY = "openclaw_external"  # settings.integrations.openclaw_external
_AUTH_FAILED = "Authentication failed — check the gateway token."
_REDIRECT_ERROR = _hc._REDIRECT_ERROR


def _enc(token: str) -> str:
    return _hc._enc(token)


def _dec(enc: str) -> Optional[str]:
    return _hc._dec(enc)


def normalize_url(url: str) -> str:
    """ws://host:port → http://host:port (wss → https); http(s) untouched; trailing / dropped."""
    u = (url or "").strip()
    for ws, http in (("wss://", "https://"), ("ws://", "http://")):
        if u.lower().startswith(ws):
            u = http + u[len(ws):]
            break
    return u.rstrip("/")


async def _read_raw(pool, user_id) -> dict:
    """Internal — the stored {url, token_enc, verified_at, last_error}. May contain the cipher."""
    if not pool or not user_id:
        return {}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT settings FROM owui_user_settings WHERE user_id=$1", int(user_id))
        if not row or not row["settings"]:
            return {}
        s = row["settings"]
        if isinstance(s, str):
            s = json.loads(s)
        v = (s.get("integrations") or {}).get(_KEY)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


async def _write_raw(pool, user_id, value: Optional[dict]) -> None:
    """RMW that preserves ALL sibling settings keys (incl. hermes_external); None clears the link."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", int(user_id)
            )
            settings = {}
            if row and row["settings"]:
                settings = row["settings"]
                if isinstance(settings, str):
                    settings = json.loads(settings)
            integrations = settings.get("integrations")
            if not isinstance(integrations, dict):
                integrations = {}
            if value is None:
                integrations.pop(_KEY, None)
            else:
                integrations[_KEY] = value
            settings["integrations"] = integrations
            settings.setdefault("ui", {})
            await conn.execute(
                "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                "VALUES ($1, $2::jsonb, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                int(user_id), json.dumps(settings),
            )


def _state(raw: dict) -> str:
    """not_linked (nothing saved) / saved (never verified) / linked (verified) / error (last verify failed)."""
    if not raw.get("url"):
        return "not_linked"
    if raw.get("verified_at"):
        return "linked"
    return "error" if raw.get("last_error") else "saved"


async def external_status(pool, user_id) -> dict:
    """Public status — NEVER includes the token. `connected` = a URL is saved + verified."""
    raw = await _read_raw(pool, user_id)
    if not raw.get("url"):
        return {"connected": False, "state": "not_linked", "url": None, "token_saved": False,
                "verified_at": None, "last_error": None}
    return {
        "connected": bool(raw.get("verified_at")),
        "state": _state(raw),
        "url": raw.get("url"),
        "token_saved": bool(raw.get("token_enc")),
        "verified_at": raw.get("verified_at"),
        "last_error": raw.get("last_error"),
    }


async def is_openclaw_linked(pool, user_id) -> bool:
    """True when this user has a verified external OpenClaw."""
    raw = await _read_raw(pool, user_id)
    return bool(raw.get("url") and raw.get("verified_at"))


async def resolve_openclaw_target(pool, user_id) -> Optional[dict]:
    """{base_url, token, guarded} for a verified external OpenClaw, else None. Like Hermes, the
    saved URL is re-checked for a guarded user (it may predate the shared-host rules) and a
    refused one raises EndpointValidationError instead of being dialled."""
    raw = await _read_raw(pool, user_id)
    if not (raw.get("url") and raw.get("verified_at")):
        return None
    await _hc.guard_external_url(raw["url"], user_id)
    tok = _dec(raw["token_enc"]) if raw.get("token_enc") else None
    return {"base_url": raw["url"].rstrip("/"), "token": tok, "guarded": providers.url_guarded(int(user_id))}


async def _probe(url: str, token: Optional[str], guarded: bool = False) -> dict:
    """Probe an external OpenClaw gateway's OpenAI-compatible HTTP API, VALIDATING the token.

    1. GET /v1/models — authenticated and free; a 2xx proves URL and token.
    2. If the gateway has no /v1/models (404/405), POST /v1/chat/completions with an empty
       message list: it is rejected as a bad request (4xx) without running an agent turn, but
       a 401/403 still proves the token, and a 404/405 says the endpoint is switched off.
    3. /health only decides which error to show: reachable but no HTTP API vs unreachable.
       /health is public, so it never counts as verified.

    ``guarded`` follows no redirects and dials public addresses only, as for Hermes."""
    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        if guarded:
            providers.plain_http_url(url)
            await providers.refuse_private_url(url)
        client = (providers.guarded_client(timeout=8.0) if guarded
                  else httpx.AsyncClient(timeout=8.0, follow_redirects=True))
        async with client:
            reached = False
            for method, path, kw in (
                ("get", "/v1/models", {}),
                ("post", "/v1/chat/completions", {"json": {"model": "openclaw", "messages": []}}),
            ):
                try:
                    r = await getattr(client, method)(f"{base}{path}", headers=headers, **kw)
                except httpx.RequestError:
                    continue
                reached = True
                if guarded and 300 <= r.status_code < 400:
                    return {"ok": False, "error": _REDIRECT_ERROR}
                if r.status_code in (401, 403):
                    return {"ok": False, "error": _AUTH_FAILED}
                if method == "get" and r.status_code < 400:
                    # The gateway also serves its web UI on this port; an HTML page here is the UI's
                    # catch-all answering for a switched-off API, and it never looked at the token.
                    if "html" in str((getattr(r, "headers", None) or {}).get("content-type", "")).lower():
                        continue
                    return {"ok": True}
                if method == "post" and r.status_code not in (404, 405) and r.status_code < 500:
                    return {"ok": True}  # 4xx here = the endpoint parsed and rejected our empty body
            if not reached:
                try:
                    r = await client.get(f"{base}/health", headers=headers)
                    reached = r.status_code < 400
                except httpx.RequestError:
                    pass
            if reached:
                return {"ok": False, "error": "Reached the gateway, but its OpenAI-compatible HTTP API is off. "
                                              "Turn on gateway.http.endpoints.chatCompletions in OpenClaw, then verify again."}
            return {"ok": False, "error": "Could not reach an OpenClaw gateway at that URL."}
    except providers.EndpointValidationError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Probe failed: {type(e).__name__}"}


def register_openclaw_connect_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/integrations/openclaw-external")
    async def openclaw_external_get(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        return await external_status(pool, int(user.id))

    @router.post("/api/owui/integrations/openclaw-external")
    async def openclaw_external_save(request: Request, user=Depends(get_current_user)):
        """Save the OpenClaw gateway URL (+ token). Does NOT verify — call /verify. A new URL
        clears any prior verification."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        url = normalize_url(body.get("url") or "")
        token = body.get("token")  # blank/omitted = keep the existing one (same URL only)
        if not _hc._valid_url(url):
            raise HTTPException(status_code=400, detail="A valid http(s) or ws(s) URL is required")
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)
        try:
            await _hc.guard_external_url(url, uid)
        except providers.EndpointValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        prior = await _read_raw(pool, uid)
        entry = {"url": url, "verified_at": None, "last_error": None}
        # A non-empty string replaces the token; otherwise the prior one is kept ONLY if the URL
        # is unchanged (a new host must not inherit an old token). Clearing it = Disconnect.
        if isinstance(token, str) and token.strip():
            entry["token_enc"] = _enc(token.strip())
        elif prior.get("url") == url and prior.get("token_enc"):
            entry["token_enc"] = prior["token_enc"]
        await _write_raw(pool, uid, entry)
        return await external_status(pool, uid)

    @router.post("/api/owui/integrations/openclaw-external/verify")
    async def openclaw_external_verify(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)
        raw = await _read_raw(pool, uid)
        if not raw.get("url"):
            raise HTTPException(status_code=400, detail="No OpenClaw URL saved")
        token = _dec(raw["token_enc"]) if raw.get("token_enc") else None
        res = await _probe(raw["url"], token, providers.url_guarded(uid))
        raw["verified_at"] = int(time()) if res.get("ok") else None
        raw["last_error"] = None if res.get("ok") else res.get("error")
        await _write_raw(pool, uid, raw)
        return {"ok": bool(res.get("ok")), "error": res.get("error"), **(await external_status(pool, uid))}

    @router.post("/api/owui/integrations/openclaw-external/disconnect")
    async def openclaw_external_disconnect(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        await _write_raw(pool, int(user.id), None)
        return {"connected": False, "state": "not_linked"}
