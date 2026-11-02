"""Outbound URL safety: what the backend may fetch or browse for an agent or a chat.

Anything not globally routable is refused (RFC 1918, loopback, link-local, the tailnet,
ULA), at validation and again on every redirect hop. The env names keep their OPENCLAW_
prefix so existing deployments keep their allow and deny lists.
"""

import asyncio
import ipaddress
import os
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

# Domain policy
_ALLOWLIST = [h.strip().lower() for h in os.getenv("OPENCLAW_WEB_ALLOWLIST", "").split(",") if h.strip()]
_DENYLIST = [h.strip().lower() for h in os.getenv("OPENCLAW_WEB_DENYLIST", "").split(",") if h.strip()]

def _blocked_reason(ip: str) -> Optional[str]:
    """Why this address may not be fetched, or None. Anything not globally routable is out:
    RFC 1918, loopback, link-local (cloud metadata), CGNAT 100.64/10 (the tailnet), ULA, reserved."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    if addr.is_global and not addr.is_multicast:
        return None
    return "a private or internal address"


def _ensure_resolved_addresses_public(hostname: str) -> None:
    """
    Block IP literals or hostnames whose DNS resolves to private/internal addresses
    (SSRF / DNS-rebinding protection).
    """
    host = (hostname or "").strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        candidates = [host]
    except ValueError:
        try:
            candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except OSError:
            # Unresolvable: the fetch itself fails with a clear error.
            return
    for ip in candidates:
        reason = _blocked_reason(ip)
        if reason:
            raise HTTPException(
                status_code=400,
                detail=f"Requests to {hostname} are not allowed: it resolves to {reason}",
            )


class _PublicOnlyTransport(httpx.AsyncBaseTransport):
    """Re-checks every hop, so a public URL cannot redirect the backend onto pgsql,
    the tailnet or the metadata address. httpx hands each redirect back here.

    The check above only answers "is this name public right now"; the connection is
    made by the inner transport, which resolves again. A name that answers public to
    the check and internal to the connect (DNS rebinding) would get through, so the
    inner transport dials only the addresses it has vetted itself."""

    def __init__(self) -> None:
        from plugins.hermes_ui import providers

        self._inner = providers.guarded_transport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from plugins.hermes_ui import providers

        if request.url.scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="Only http and https URLs can be fetched")
        await asyncio.to_thread(_ensure_resolved_addresses_public, request.url.host)
        try:
            return await self._inner.handle_async_request(request)
        except providers.EndpointValidationError:
            raise HTTPException(status_code=400, detail="Requests to that address are not allowed") from None

    async def aclose(self) -> None:
        await self._inner.aclose()


# ─── URL validation ────────────────────────────────────────────────────────────

def _validate_url(url: str, *, live_web: bool = False) -> None:
    """
    Reject URLs that point to private/internal addresses.

    Allowed: http:// and https:// pointing to routable public IPs.
    Rejected: RFC-1918, loopback, link-local, localhost, other schemes.

    When live_web=True, domain allow/deny lists are skipped (user acknowledged
    unrestricted access).  Private-IP and localhost checks are ALWAYS enforced.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed URL")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"URL scheme '{parsed.scheme}' is not allowed. Only http/https.",
        )

    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="URL has no hostname")

    # Reject by hostname — always enforced regardless of live_web
    lowered = hostname.lower()
    if lowered in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Requests to localhost are not allowed")

    # Domain allow/deny lists (suffix match) — skipped in live_web mode
    if not live_web:
        if _DENYLIST:
            for bad in _DENYLIST:
                if lowered == bad or lowered.endswith("." + bad):
                    raise HTTPException(status_code=400, detail=f"Domain '{lowered}' is blocked")
        if _ALLOWLIST:
            ok = False
            for good in _ALLOWLIST:
                if lowered == good or lowered.endswith("." + good):
                    ok = True
                    break
            if not ok:
                raise HTTPException(status_code=400, detail=f"Domain '{lowered}' is not allowlisted")

    _ensure_resolved_addresses_public(lowered)


def _validate_browser_url(url: str, *, live_web: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Tier 3 browsing requires https URLs")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="URL has no hostname")
    if hostname in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Requests to localhost are not allowed")

    # With X-Live-Web (workspace live_web), skip hostname allowlist — same policy as web-fetch.
    # OPENCLAW_BROWSER_ALLOWLIST=* also skips the allowlist (still enforces https + non-private DNS).
    if not live_web:
        raw_allow = os.getenv("OPENCLAW_BROWSER_ALLOWLIST", "").strip()
        if raw_allow != "*":
            allow = [h.strip().lower() for h in raw_allow.split(",") if h.strip()]
        else:
            allow = ["*"]  # sentinel: skip check below
        if allow != ["*"] and not allow:
            # Default Tier 3 hosts — broad research set (override with OPENCLAW_BROWSER_ALLOWLIST)
            allow = [
                "example.com",
                "www.example.com",
                # Google
                "google.com",
                "google.dev",
                "googleapis.com",
                "gstatic.com",
                "googleusercontent.com",
                "gemini.google.com",
                "ai.google.dev",
                "blog.google",
                "chromium.org",
                # Microsoft / GitHub
                "github.com",
                "gist.github.com",
                "raw.githubusercontent.com",
                "microsoft.com",
                "azure.com",
                "visualstudio.com",
                "bing.com",
                "msn.com",
                # Search & reference
                "duckduckgo.com",
                "www.duckduckgo.com",
                "wikipedia.org",
                "wikimedia.org",
                "archive.org",
                # Social / comms
                "reddit.com",
                "x.com",
                "twitter.com",
                "linkedin.com",
                "facebook.com",
                "instagram.com",
                "youtube.com",
                "youtu.be",
                "discord.com",
                "slack.com",
                # News / media
                "news.ycombinator.com",
                "ycombinator.com",
                "bbc.co.uk",
                "bbc.com",
                "reuters.com",
                "nytimes.com",
                "theguardian.com",
                "apnews.com",
                # AI / dev tools
                "claude.ai",
                "anthropic.com",
                "console.anthropic.com",
                "docs.anthropic.com",
                "openai.com",
                "platform.openai.com",
                "cursor.com",
                "docs.cursor.com",
                "httpstat.us",
                "ollama.com",
                "huggingface.co",
                "kaggle.com",
                "colab.research.google.com",
                # Docs & learning
                "stackoverflow.com",
                "serverfault.com",
                "superuser.com",
                "stackexchange.com",
                "developer.mozilla.org",
                "docs.python.org",
                "nodejs.org",
                "npmjs.com",
                "pypi.org",
                "react.dev",
                "nextjs.org",
                "tailwindcss.com",
                "kubernetes.io",
                "docker.com",
                "docs.docker.com",
                # Cloud & infra docs
                "aws.amazon.com",
                "cloud.google.com",
                "docs.aws.amazon.com",
                # Registries & CDNs (common page assets)
                "unpkg.com",
                "jsdelivr.net",
                "cdn.jsdelivr.net",
                "cdnjs.cloudflare.com",
                "cloudflare.com",
                "fastly.com",
                # Commerce / general
                "amazon.com",
                "apple.com",
            ]
        if allow != ["*"]:
            ok = any(hostname == h or hostname.endswith("." + h) for h in allow)
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail=f"Domain '{hostname}' is not allowlisted for interactive browsing",
                )

    _ensure_resolved_addresses_public(hostname)
