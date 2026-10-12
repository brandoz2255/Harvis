"""Finding out how to sign in to a remote MCP server, and registering Harvis there.

The MCP authorization spec chains four documents, and this module walks them the
way a Claude.ai connector does, with no per-vendor code:

1. The server's ``401`` carries ``WWW-Authenticate: Bearer resource_metadata=...``
   (RFC 9728). Without that header the well-known locations are tried.
2. The protected-resource document names the authorization server(s).
3. The authorization server's metadata (RFC 8414, or OpenID Connect discovery)
   gives the authorize, token and registration endpoints.
4. Dynamic client registration (RFC 7591) mints a client id for Harvis. Servers
   that do not offer it need a client id the user registered by hand.

Every request here goes through ``_client()``, whose transport re-runs the SSRF
guard on every hop, so a metadata document cannot point Harvis at the cluster.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .http_transport import guarded_client
from .protocol import McpError

logger = logging.getLogger(__name__)

CLIENT_NAME = "Harvis"
CLIENT_URI = "https://github.com/brandoz2255/Harvis"
HTTP_TIMEOUT = 20.0

CODE_NO_REGISTRATION = "client_registration_unsupported"
CODE_NO_METADATA = "no_oauth_metadata"


class OAuthError(McpError):
    """Discovery, registration or token exchange failed.

    ``code`` lets a caller tell "ask the user for a client id" from a plain failure.
    """

    def __init__(self, message: str, *, code: str = ""):
        super().__init__(message)
        self.code = code


def _client() -> httpx.AsyncClient:
    """The one place an HTTP client is made — tests swap this for a mock transport."""
    return guarded_client(timeout=HTTP_TIMEOUT)


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def require_http_url(url: str, what: str) -> str:
    """Reject anything that is not an http(s) address (e.g. ``javascript:``).

    The authorize URL is opened in the person's own browser rather than fetched
    by Harvis, so the SSRF guard does not apply to it — the scheme check does.
    """
    parts = urlsplit(str(url or ""))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise OAuthError(f"the {what} the server published is not an http(s) address")
    return str(url)


_PARAM = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?:"([^"]*)"|([^\s,]+))')


def parse_www_authenticate(header: Optional[str]) -> dict:
    """``Bearer resource_metadata="...", scope="a b"`` -> ``{"resource_metadata": ..., "scope": ...}``."""
    out: dict = {}
    for m in _PARAM.finditer(header or ""):
        out[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


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


async def probe_challenge(client: httpx.AsyncClient, resource_url: str) -> dict:
    """Ask the MCP endpoint something and read the ``WWW-Authenticate`` it answers with.

    Headers only: the body is never read, so a server that happens to stream
    cannot hold the probe open.
    """
    body = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": CLIENT_NAME.lower(), "version": "1"}}}
    try:
        async with client.stream(
            "POST", resource_url, json=body,
            headers={"Accept": "application/json, text/event-stream"},
        ) as resp:
            if resp.status_code == 401:
                return parse_www_authenticate(resp.headers.get("www-authenticate"))
    except httpx.HTTPError as exc:
        logger.debug("oauth: challenge probe of %s failed (%s)", resource_url, exc)
    return {}


def _authorization_server_candidates(issuer: str) -> list[str]:
    """RFC 8414 puts the well-known segment before the issuer's path; OIDC
    discovery appends it. Servers in the wild answer one or the other."""
    parts = urlsplit(issuer.rstrip("/"))
    origin, path = origin_of(issuer), parts.path.rstrip("/")
    if not path:
        return [f"{origin}/.well-known/oauth-authorization-server",
                f"{origin}/.well-known/openid-configuration"]
    return [f"{origin}/.well-known/oauth-authorization-server{path}",
            f"{origin}/.well-known/openid-configuration{path}",
            f"{origin}{path}/.well-known/openid-configuration"]


async def discover(resource_url: str, *, www_authenticate: Optional[str] = None) -> dict:
    """Metadata for the server behind ``resource_url``.

    Returns the authorization server's metadata plus ``resource`` (the audience
    to ask the token for) and ``scopes`` (a space-separated string, possibly empty).
    """
    parts = urlsplit(resource_url)
    origin, path = origin_of(resource_url), parts.path.rstrip("/")

    async with _client() as client:
        challenge = parse_www_authenticate(www_authenticate) if www_authenticate \
            else await probe_challenge(client, resource_url)

        prm = None
        candidates = [challenge.get("resource_metadata")] if challenge.get("resource_metadata") else []
        # RFC 9728 puts the path after the well-known segment; servers that host
        # one MCP endpoint often also answer the bare form.
        candidates += [f"{origin}/.well-known/oauth-protected-resource{path}",
                       f"{origin}/.well-known/oauth-protected-resource"]
        for candidate in candidates:
            prm = await _get_json(client, candidate)
            if prm:
                break

        # No protected-resource document: assume the server is its own
        # authorization server, the common single-host shape.
        issuers = [str(i) for i in ((prm or {}).get("authorization_servers") or []) if i] or [origin]

        as_meta, chosen = None, ""
        for issuer in issuers:
            for candidate in _authorization_server_candidates(issuer):
                found = await _get_json(client, candidate)
                if found and found.get("authorization_endpoint"):
                    as_meta, chosen = found, issuer.rstrip("/")
                    break
            if as_meta:
                break

    if not as_meta:
        raise OAuthError(
            f"{resource_url} asks for authorization but publishes no OAuth metadata "
            "Harvis can follow — paste an access token as a credential instead",
            code=CODE_NO_METADATA)
    if not as_meta.get("token_endpoint"):
        raise OAuthError(f"{chosen} advertises no token endpoint")
    methods = as_meta.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise OAuthError(f"{chosen} does not support PKCE S256, which Harvis requires")

    meta = dict(as_meta)
    meta["authorization_endpoint"] = require_http_url(meta["authorization_endpoint"], "authorize address")
    meta["token_endpoint"] = require_http_url(meta["token_endpoint"], "token address")
    meta["issuer"] = as_meta.get("issuer") or chosen
    meta["resource"] = (prm or {}).get("resource") or resource_url
    meta["scopes"] = challenge.get("scope") or " ".join((prm or {}).get("scopes_supported") or [])
    return meta


async def register_client(meta: dict, redirect_uri: str) -> dict:
    """RFC 7591 dynamic registration as a public client (PKCE, no secret)."""
    endpoint = meta.get("registration_endpoint")
    if not endpoint:
        raise OAuthError(
            f"{meta.get('issuer')} does not support dynamic client registration. Register Harvis "
            f"there by hand (redirect address {redirect_uri}) and enter the client ID.",
            code=CODE_NO_REGISTRATION)
    body = {
        "client_name": CLIENT_NAME, "client_uri": CLIENT_URI, "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if meta.get("scopes"):
        body["scope"] = meta["scopes"]
    async with _client() as client:
        try:
            resp = await client.post(endpoint, json=body)
        except httpx.HTTPError as exc:
            raise OAuthError(f"could not reach {endpoint}: {exc}") from exc
    if resp.status_code >= 400:
        raise OAuthError(f"client registration was refused ({resp.status_code}){_why(resp)}")
    try:
        info = resp.json()
    except ValueError as exc:
        raise OAuthError("client registration returned a non-JSON body") from exc
    if not isinstance(info, dict) or not info.get("client_id"):
        raise OAuthError("client registration returned no client_id")
    info["harvis_redirect_uri"] = redirect_uri
    return info


def _why(resp: httpx.Response) -> str:
    """The ``error`` / ``error_description`` of an OAuth error body, nothing else.

    Never echo the raw body: a token endpoint's failure can sit next to
    credentials, and these messages reach logs and the UI.
    """
    try:
        data = resp.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    bits = [str(data[k])[:200] for k in ("error", "error_description") if data.get(k)]
    return ": " + " — ".join(bits) if bits else ""
