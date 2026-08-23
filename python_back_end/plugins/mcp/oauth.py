"""OAuth 2.1 client for remote MCP servers — discovery, registration, PKCE.

A hosted MCP server that answers 401 tells you, in ``WWW-Authenticate``, where
its metadata lives. From there the whole dance is discoverable and needs no
per-vendor code: read the protected-resource document, read the authorization
server's document, register Harvis as a client if the server supports dynamic
registration, then run an authorization-code exchange with PKCE.

Harvis has a browser in front of it, so the redirect flow is the one that
works: the user clicks Authorize, approves at the vendor, and the vendor sends
them back to ``/api/owui/mcp/oauth/callback``. There is no client secret — the
public-client + S256 combination is what OAuth 2.1 asks of an app that cannot
keep one, and it is what MCP servers advertise.

State lives in memory between the two halves of the flow, deliberately: the
PKCE verifier is a single-use secret with a lifetime of about a minute, and
writing it to Postgres would give it a longer life than the thing it protects.
A backend restart mid-authorization means clicking Authorize again.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from .protocol import McpError
from .token_storage import PgTokenStorage
from .types import McpServerConfig

logger = logging.getLogger(__name__)

CLIENT_NAME = "Harvis"
CLIENT_URI = "https://github.com/brandoz2255/Harvis"

# An access token this close to expiry is treated as already gone: a refresh
# costs one request, a 401 mid-tool-call costs the user their turn.
_REFRESH_MARGIN_S = 60
_HTTP_TIMEOUT = 20.0
# Authorizations that were started and never finished are swept at this age.
_PENDING_TTL_S = 600

# state -> pending authorization. Module-level: one backend process owns the
# whole flow, and the window is under a minute.
_pending: dict[str, dict] = {}


class OAuthError(McpError):
    """Discovery, registration or token exchange failed."""


# -- discovery -------------------------------------------------------------


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


async def _get_json(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    try:
        resp = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.debug("oauth: %s unreachable (%s)", url, exc)
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def discover(resource_url: str) -> dict:
    """Metadata for the server behind ``resource_url``.

    Returns ``{"resource": ..., "scopes": ..., **authorization_server_metadata}``.
    """
    parts = urlsplit(resource_url)
    origin = _origin(resource_url)
    path = parts.path.rstrip("/")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        prm = None
        # RFC 9728 puts the path after the well-known segment; servers that
        # host one MCP endpoint often also answer the bare form.
        for candidate in (
            f"{origin}/.well-known/oauth-protected-resource{path}",
            f"{origin}/.well-known/oauth-protected-resource",
        ):
            prm = await _get_json(client, candidate)
            if prm:
                break

        issuers = list((prm or {}).get("authorization_servers") or [])
        if not issuers:
            # No protected-resource document: assume the server is its own
            # authorization server, which is the common single-host shape.
            issuers = [origin]

        as_meta = None
        chosen = ""
        for issuer in issuers:
            base = issuer.rstrip("/")
            for candidate in (
                f"{base}/.well-known/oauth-authorization-server",
                f"{base}/.well-known/openid-configuration",
            ):
                as_meta = await _get_json(client, candidate)
                if as_meta and as_meta.get("authorization_endpoint"):
                    chosen = base
                    break
            if as_meta and as_meta.get("authorization_endpoint"):
                break

    if not as_meta or not as_meta.get("authorization_endpoint"):
        raise OAuthError(
            f"{resource_url} asks for authorization but publishes no OAuth "
            "metadata Harvis can follow — paste a token as a credential instead"
        )
    if not as_meta.get("token_endpoint"):
        raise OAuthError(f"{chosen} advertises no token endpoint")

    meta = dict(as_meta)
    meta["issuer"] = as_meta.get("issuer") or chosen
    meta["resource"] = (prm or {}).get("resource") or resource_url
    meta["scopes"] = " ".join((prm or {}).get("scopes_supported") or as_meta.get("scopes_supported") or [])
    return meta


# -- dynamic client registration -------------------------------------------


async def _register_client(meta: dict, redirect_uri: str) -> dict:
    endpoint = meta.get("registration_endpoint")
    if not endpoint:
        raise OAuthError(
            f"{meta.get('issuer')} does not support dynamic client registration, "
            "so Harvis cannot register itself — paste a token as a credential instead"
        )
    body = {
        "client_name": CLIENT_NAME,
        "client_uri": CLIENT_URI,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if meta.get("scopes"):
        body["scope"] = meta["scopes"]
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.post(endpoint, json=body)
        except httpx.HTTPError as exc:
            raise OAuthError(f"could not reach {endpoint}: {exc}") from exc
    if resp.status_code >= 400:
        raise OAuthError(
            f"client registration was refused ({resp.status_code}): {resp.text[:300]}"
        )
    try:
        info = resp.json()
    except ValueError as exc:
        raise OAuthError("client registration returned a non-JSON body") from exc
    if not info.get("client_id"):
        raise OAuthError("client registration returned no client_id")
    info["harvis_redirect_uri"] = redirect_uri
    return info


async def _client_for(storage: PgTokenStorage, meta: dict, redirect_uri: str) -> dict:
    """A registered client for this (user, server), reused across authorizations.

    Re-registers when the redirect URI changes — a client registered against
    ``http://localhost:9000`` is useless once the app is reached by any other
    origin, and reusing it produces an ``invalid_redirect_uri`` that reads like
    a Harvis bug.
    """
    info = await storage.get_client_info()
    if info and info.get("client_id") and info.get("harvis_redirect_uri") == redirect_uri:
        return info
    info = await _register_client(meta, redirect_uri)
    await storage.set_client_info(info)
    return info


# -- PKCE ------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce() -> tuple[str, str]:
    verifier = _b64url(os.urandom(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _sweep() -> None:
    cutoff = time.time() - _PENDING_TTL_S
    for state in [s for s, p in _pending.items() if p.get("started", 0) < cutoff]:
        _pending.pop(state, None)


# -- the flow --------------------------------------------------------------


async def begin_authorization(
    cfg: McpServerConfig, pool, redirect_uri: str
) -> dict:
    """Start an authorization. Returns ``{"authorize_url": ..., "state": ...}``."""
    if not cfg.url:
        raise OAuthError(f"'{cfg.server_name}' has no URL to authorize against")
    _sweep()
    meta = await discover(cfg.url)
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    client = await _client_for(storage, meta, redirect_uri)

    verifier, challenge = _pkce()
    state = _b64url(secrets.token_bytes(24))
    params = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if meta.get("scopes"):
        params["scope"] = meta["scopes"]
    # RFC 8707: without this a token can come back audience-scoped to the wrong
    # resource, and the MCP server rejects it with a 401 that explains nothing.
    if meta.get("resource"):
        params["resource"] = meta["resource"]

    _pending[state] = {
        "started": time.time(),
        "verifier": verifier,
        "meta": meta,
        "client": client,
        "redirect_uri": redirect_uri,
        "user_id": cfg.user_id,
        "server_name": cfg.server_name,
    }
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    return {
        "authorize_url": f"{meta['authorization_endpoint']}{sep}{urlencode(params)}",
        "state": state,
        "server_name": cfg.server_name,
    }


async def complete_authorization(state: str, code: str, pool) -> dict:
    """Exchange the code for tokens and store them. Returns the server name."""
    pending = _pending.pop((state or "").strip(), None)
    if pending is None:
        raise OAuthError(
            "that authorization is no longer pending — it may have expired or "
            "already been used. Click Authorize again."
        )
    meta, client = pending["meta"], pending["client"]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "client_id": client["client_id"],
        "code_verifier": pending["verifier"],
    }
    if client.get("client_secret"):
        form["client_secret"] = client["client_secret"]
    if meta.get("resource"):
        form["resource"] = meta["resource"]

    tokens = await _token_request(meta["token_endpoint"], form)
    storage = PgTokenStorage(
        pool=pool, user_id=pending["user_id"], server_name=pending["server_name"]
    )
    tokens["harvis_token_endpoint"] = meta["token_endpoint"]
    tokens["harvis_resource"] = meta.get("resource") or ""
    await storage.set_tokens(tokens)
    logger.info(
        "mcp oauth: authorized %s for user %s",
        pending["server_name"],
        pending["user_id"],
    )
    return {"server_name": pending["server_name"], "user_id": pending["user_id"]}


async def _token_request(endpoint: str, form: dict) -> dict:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.post(
                endpoint,
                data=form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise OAuthError(f"could not reach {endpoint}: {exc}") from exc
    if resp.status_code >= 400:
        raise OAuthError(f"token request failed ({resp.status_code}): {resp.text[:300]}")
    try:
        tokens = resp.json()
    except ValueError as exc:
        raise OAuthError("token endpoint returned a non-JSON body") from exc
    if not tokens.get("access_token"):
        raise OAuthError("token endpoint returned no access_token")
    return tokens


async def ensure_access_token(cfg: McpServerConfig, pool) -> Optional[str]:
    """A usable access token, refreshed if the stored one has run out.

    Returns None when the user has never authorized this server, which the
    caller turns into "click Authorize" rather than a bare 401.
    """
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    tokens = await storage.get_tokens()
    if not tokens or not tokens.get("access_token"):
        return None

    # get_tokens() rewrites expires_in to seconds remaining, so this is the
    # live figure even after a restart.
    remaining = tokens.get("expires_in")
    fresh = remaining is None or int(remaining) > _REFRESH_MARGIN_S
    if fresh:
        return str(tokens["access_token"])

    refresh_token = tokens.get("refresh_token")
    endpoint = tokens.get("harvis_token_endpoint")
    if not refresh_token or not endpoint:
        # Expired with no way to renew. Returning the dead token would produce
        # a 401; returning None produces "authorize again", which is the truth.
        return None

    client_info = await storage.get_client_info() or {}
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_info.get("client_id") or "",
    }
    if client_info.get("client_secret"):
        form["client_secret"] = client_info["client_secret"]
    if tokens.get("harvis_resource"):
        form["resource"] = tokens["harvis_resource"]
    try:
        renewed = await _token_request(endpoint, form)
    except OAuthError as exc:
        logger.warning("mcp oauth: refresh failed for %s — %s", cfg.server_name, exc)
        return None
    renewed.setdefault("refresh_token", refresh_token)
    renewed["harvis_token_endpoint"] = endpoint
    renewed["harvis_resource"] = tokens.get("harvis_resource") or ""
    await storage.set_tokens(renewed)
    return str(renewed["access_token"])


async def forget(cfg: McpServerConfig, pool) -> None:
    """Drop a server's stored authorization."""
    storage = PgTokenStorage(pool=pool, user_id=cfg.user_id, server_name=cfg.server_name)
    await storage.clear()
