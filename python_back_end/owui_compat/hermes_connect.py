"""Hermes Agent connection modes — "Bring your Hermes into Harvis".

The Hermes integration is reframed around USER-OWNED Hermes first:

  1. Import an existing Hermes profile  → populates the local per-user sidecar home
     (handled in `hermes_import.py`); routing stays the LOCAL sidecar.
  2. Connect an external Hermes Agent   → this module: store a per-user API URL + optional
     token (Fernet-encrypted), verify health, and route Chat to that external server.
  3. Harvis-managed fallback            → fresh local sidecar profile (Advanced/Experimental).

Routing is binary: an external URL that's been verified → Chat proxies there; otherwise the
local sidecar runs (with whatever profile — imported or managed-fresh). Build needs workspace
access the external server doesn't have, so Build is marked unavailable while external is active.

Storage: settings.integrations.hermes_external = {url, token_enc, verified_at, last_error} (RMW,
no migration). The token is Fernet-encrypted at rest and NEVER returned to the client.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

_KEY = "hermes_external"  # settings.integrations.hermes_external


def _enc(token: str) -> str:
    from main import encrypt_api_key
    return encrypt_api_key(token)


def _dec(enc: str) -> Optional[str]:
    try:
        from main import decrypt_api_key
        return decrypt_api_key(enc)
    except Exception:
        return None


def _valid_url(url: str) -> bool:
    # A self-hosted Hermes Agent may legitimately live on localhost / a private LAN (it's the
    # user's OWN service, routing their OWN prompts), so private IPs are allowed here — unlike
    # untrusted web fetch. We only require a well-formed http(s) URL.
    try:
        p = urlparse((url or "").strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


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
        v = ((s.get("integrations") or {}).get(_KEY))
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


async def _write_raw(pool, user_id, value: Optional[dict]) -> None:
    """RMW that preserves ALL sibling settings keys; None clears the external config."""
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


async def external_status(pool, user_id) -> dict:
    """Public status — NEVER includes the token. `connected` = a URL is saved + verified."""
    raw = await _read_raw(pool, user_id)
    if not raw or not raw.get("url"):
        return {"connected": False, "url": None, "token_saved": False, "verified_at": None, "last_error": None}
    return {
        "connected": bool(raw.get("verified_at")),
        "url": raw.get("url"),
        "token_saved": bool(raw.get("token_enc")),
        "verified_at": raw.get("verified_at"),
        "last_error": raw.get("last_error"),
    }


async def is_external_active(pool, user_id) -> bool:
    """True when a verified external Hermes is configured → Chat routes there, Build is off."""
    raw = await _read_raw(pool, user_id)
    return bool(raw.get("url") and raw.get("verified_at"))


async def resolve_external_target(pool, user_id) -> Optional[dict]:
    """{base_url, token} for a verified external Hermes, else None (→ caller uses local sidecar)."""
    raw = await _read_raw(pool, user_id)
    if not (raw.get("url") and raw.get("verified_at")):
        return None
    tok = _dec(raw["token_enc"]) if raw.get("token_enc") else None
    return {"base_url": raw["url"].rstrip("/"), "token": tok}


async def _probe(url: str, token: Optional[str]) -> dict:
    """Health-probe an external Hermes Agent API server. Tries /health then /v1/models."""
    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            for path in ("/health", "/v1/models"):
                try:
                    r = await client.get(f"{base}{path}", headers=headers)
                    if r.status_code < 400:
                        return {"ok": True}
                    if r.status_code in (401, 403):
                        return {"ok": False, "error": "Authentication failed — check the token."}
                except httpx.RequestError:
                    continue
        return {"ok": False, "error": "Could not reach the Hermes Agent API at that URL."}
    except Exception as e:
        return {"ok": False, "error": f"Probe failed: {type(e).__name__}"}


def register_hermes_connect_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/integrations/hermes-external")
    async def hermes_external_get(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        return await external_status(pool, int(user.id))

    @router.post("/api/owui/integrations/hermes-external")
    async def hermes_external_save(request: Request, user=Depends(get_current_user)):
        """Save the external Hermes Agent URL (+ optional token). Does NOT verify — call /verify.
        A new URL clears any prior verification (you must re-verify)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        url = (body.get("url") or "").strip()
        token = body.get("token")  # optional; '' or None = no token / keep existing
        if not _valid_url(url):
            raise HTTPException(status_code=400, detail="A valid http(s) URL is required")
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)
        prior = await _read_raw(pool, uid)
        entry = {"url": url, "verified_at": None, "last_error": None}
        # Token handling: a non-empty string replaces it; explicit null clears it; omitted keeps
        # the prior token ONLY if the URL is unchanged (a new host must not reuse an old token).
        if isinstance(token, str) and token.strip():
            entry["token_enc"] = _enc(token.strip())
        elif token is None and prior.get("url") == url and prior.get("token_enc"):
            entry["token_enc"] = prior["token_enc"]
        await _write_raw(pool, uid, entry)
        return await external_status(pool, uid)

    @router.post("/api/owui/integrations/hermes-external/verify")
    async def hermes_external_verify(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)
        raw = await _read_raw(pool, uid)
        if not raw.get("url"):
            raise HTTPException(status_code=400, detail="No external Hermes URL saved")
        token = _dec(raw["token_enc"]) if raw.get("token_enc") else None
        res = await _probe(raw["url"], token)
        from time import time as _t
        raw["verified_at"] = int(_t()) if res.get("ok") else None
        raw["last_error"] = None if res.get("ok") else res.get("error")
        await _write_raw(pool, uid, raw)
        return {"ok": bool(res.get("ok")), "error": res.get("error"), **(await external_status(pool, uid))}

    @router.post("/api/owui/integrations/hermes-external/disconnect")
    async def hermes_external_disconnect(request: Request, user=Depends(get_current_user)):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        await _write_raw(pool, int(user.id), None)
        return {"connected": False}
