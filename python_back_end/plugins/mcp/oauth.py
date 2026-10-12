"""OAuth 2.1 client for remote MCP servers — the authorization-code + PKCE flow.

Discovery and client registration live in ``oauth_discovery``; this module runs
the redirect dance and keeps the tokens usable afterwards.

Harvis has a browser in front of it, so the redirect flow is the one that works:
the user clicks Connect, approves at the vendor, and the vendor sends them back
to a Harvis callback. Harvis is a public client — PKCE S256 stands in for a
secret — unless the user supplied a client id/secret for a server that offers no
dynamic registration.

Authorizations in flight are kept in memory, deliberately: the PKCE verifier is a
single-use secret with a lifetime of minutes, and writing it to Postgres would
give it a longer life than the thing it protects. A backend restart mid-authorization
means clicking Connect again. ``state`` is the only credential the callback
carries, so it is 192 random bits, bound to one (user, server), usable once, and
refused after ``PENDING_TTL_S``.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from . import oauth_discovery as disc
from .oauth_discovery import CLIENT_NAME, CLIENT_URI, OAuthError, discover  # noqa: F401  (re-exported)
from .token_storage import PgTokenStorage
from .types import McpServerConfig

logger = logging.getLogger(__name__)

# An access token this close to expiry is treated as already gone: a refresh
# costs one request, a 401 mid-tool-call costs the user their turn.
_REFRESH_MARGIN_S = 60
PENDING_TTL_S = 600

# state -> pending authorization. One backend process owns the whole flow.
_pending: dict[str, dict] = {}
# (user, server) -> lock, so two tool calls that find an expired token refresh it once.
_refresh_locks: dict[tuple, asyncio.Lock] = {}


# -- PKCE ------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce() -> tuple[str, str]:
    verifier = _b64url(os.urandom(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _sweep() -> None:
    cutoff = time.time() - PENDING_TTL_S
    for state in [s for s, p in _pending.items() if p.get("started", 0) < cutoff]:
        _pending.pop(state, None)


# -- the flow --------------------------------------------------------------


async def _client_for(storage: PgTokenStorage, meta: dict, redirect_uri: str,
                      manual: Optional[dict]) -> dict:
    """The OAuth client to use for this (user, server).

    A client id the user typed in wins and is remembered. Otherwise a registered
    client is reused across authorizations — unless the redirect address changed,
    because a client registered against ``http://localhost:9000`` is useless once
    Harvis is reached at any other origin and reusing it produces an
    ``invalid_redirect_uri`` that reads like a Harvis bug.
    """
    if manual:
        info = {**manual, "harvis_redirect_uri": redirect_uri, "harvis_manual": True}
        await storage.set_client_info(info)
        return info
    info = await storage.get_client_info()
    if info and info.get("client_id") and (
        info.get("harvis_manual") or info.get("harvis_redirect_uri") == redirect_uri
    ):
        return info
    info = await disc.register_client(meta, redirect_uri)
    await storage.set_client_info(info)
    return info


async def begin_authorization(
    cfg: McpServerConfig, pool, redirect_uri: str, *,
    client_id: str = "", client_secret: str = "", www_authenticate: str = "",
) -> dict:
    """Start an authorization. Returns ``{"authorize_url", "state", "server_name"}``."""
    if not cfg.url:
        raise OAuthError(f"'{cfg.server_name}' has no URL to authorize against")
    _sweep()
    # One live authorization per (user, server): starting again replaces the old one.
    for old in [s for s, p in _pending.items()
                if p["user_id"] == cfg.user_id and p["server_name"] == cfg.server_name]:
        _pending.pop(old, None)

    meta = await discover(cfg.url, www_authenticate=www_authenticate or None)
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    manual = {"client_id": client_id.strip(), **({"client_secret": client_secret.strip()}
                                                 if client_secret.strip() else {})} if client_id.strip() else None
    client = await _client_for(storage, meta, redirect_uri, manual)

    verifier, challenge = _pkce()
    state = _b64url(secrets.token_bytes(24))
    params = {
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    if meta.get("scopes"):
        params["scope"] = meta["scopes"]
    # RFC 8707: without this a token can come back audience-scoped to the wrong
    # resource, and the MCP server rejects it with a 401 that explains nothing.
    if meta.get("resource"):
        params["resource"] = meta["resource"]

    _pending[state] = {
        "started": time.time(), "verifier": verifier, "meta": meta, "client": client,
        "redirect_uri": redirect_uri, "user_id": cfg.user_id, "server_name": cfg.server_name,
    }
    endpoint = meta["authorization_endpoint"]
    sep = "&" if "?" in endpoint else "?"
    return {"authorize_url": f"{endpoint}{sep}{urlencode(params)}", "state": state,
            "server_name": cfg.server_name}


def discard(state: str) -> Optional[dict]:
    """Forget a pending authorization (denied at the vendor, or cancelled). Returns it."""
    return _pending.pop((state or "").strip(), None)


def pending_owner(state: str) -> Optional[tuple[int, str]]:
    """(user_id, server_name) a live ``state`` belongs to, without consuming it."""
    p = _pending.get((state or "").strip())
    return (p["user_id"], p["server_name"]) if p else None


async def complete_authorization(state: str, code: str, pool) -> dict:
    """Exchange the code for tokens and store them. Single-use: ``state`` is consumed."""
    pending = _pending.pop((state or "").strip(), None)
    if pending is None or time.time() - pending["started"] > PENDING_TTL_S:
        raise OAuthError(
            "that authorization is no longer pending — it may have expired or "
            "already been used. Click Connect again.")
    meta, client = pending["meta"], pending["client"]
    form = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
        "client_id": client["client_id"], "code_verifier": pending["verifier"],
    }
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    if meta.get("resource"):
        form["resource"] = meta["resource"]

    tokens = await _token_request(meta["token_endpoint"], form)
    storage = PgTokenStorage(pool=pool, user_id=pending["user_id"], server_name=pending["server_name"])
    tokens["harvis_token_endpoint"] = meta["token_endpoint"]
    tokens["harvis_resource"] = meta.get("resource") or ""
    await storage.set_tokens(tokens)
    logger.info("mcp oauth: authorized %s for user %s", pending["server_name"], pending["user_id"])
    return {"server_name": pending["server_name"], "user_id": pending["user_id"]}


async def _token_request(endpoint: str, form: dict) -> dict:
    async with disc._client() as client:
        try:
            resp = await client.post(
                endpoint, data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise OAuthError(f"could not reach {endpoint}: {exc}") from exc
    if resp.status_code >= 400:
        raise OAuthError(f"token request failed ({resp.status_code}){disc._why(resp)}")
    try:
        tokens = resp.json()
    except ValueError as exc:
        raise OAuthError("token endpoint returned a non-JSON body") from exc
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise OAuthError("token endpoint returned no access_token")
    return tokens


async def ensure_access_token(cfg: McpServerConfig, pool) -> Optional[str]:
    """A usable access token, refreshed if the stored one has run out.

    Returns None when the user has never authorized this server (or the grant
    cannot be renewed), which the caller turns into "click Connect" rather than
    a bare 401.
    """
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    tokens = await storage.get_tokens()
    if not tokens or not tokens.get("access_token"):
        return None
    if _is_fresh(tokens):
        return str(tokens["access_token"])

    lock = _refresh_locks.setdefault((cfg.user_id, cfg.server_name), asyncio.Lock())
    async with lock:
        # Someone else may have refreshed while this call waited for the lock.
        tokens = await storage.get_tokens()
        if not tokens or not tokens.get("access_token"):
            return None
        if _is_fresh(tokens):
            return str(tokens["access_token"])
        return await _refresh(storage, cfg, tokens)


def _is_fresh(tokens: dict) -> bool:
    # get_tokens() rewrites expires_in to seconds remaining, so this is the
    # live figure even after a restart.
    remaining = tokens.get("expires_in")
    return remaining is None or int(remaining) > _REFRESH_MARGIN_S


async def _refresh(storage: PgTokenStorage, cfg: McpServerConfig, tokens: dict) -> Optional[str]:
    refresh_token, endpoint = tokens.get("refresh_token"), tokens.get("harvis_token_endpoint")
    if not refresh_token or not endpoint:
        # Expired with no way to renew. Returning the dead token would produce
        # a 401; returning None produces "connect again", which is the truth.
        return None
    client_info = await storage.get_client_info() or {}
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": client_info.get("client_id") or ""}
    if client_info.get("client_secret"):
        form["client_secret"] = client_info["client_secret"]
    if tokens.get("harvis_resource"):
        form["resource"] = tokens["harvis_resource"]
    try:
        renewed = await _token_request(endpoint, form)
    except OAuthError as exc:
        logger.warning("mcp oauth: refresh failed for %s — %s", cfg.server_name, exc)
        return None
    # Servers may rotate the refresh token or keep the old one.
    renewed.setdefault("refresh_token", refresh_token)
    renewed["harvis_token_endpoint"] = endpoint
    renewed["harvis_resource"] = tokens.get("harvis_resource") or ""
    await storage.set_tokens(renewed)
    return str(renewed["access_token"])


async def forget(cfg: McpServerConfig, pool) -> None:
    """Drop a server's stored authorization."""
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    await storage.clear()
