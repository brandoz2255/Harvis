"""Agent Reach — lane-5 research capability (Harvis backend), NOT OpenClaw.

Zero-config Phase 1 channels only:
  - web_search — find pages for a query (same search agent the chat lane uses)
  - web_read   — public page text via Jina reader proxy (r.jina.ai)
  - yt_transcript — YouTube captions (existing research.extract.youtube)
  - gh_view    — public GitHub raw/API content
  - rss_read   — public RSS/Atom feeds

Cookie platforms (Twitter, Reddit, etc.) are explicitly out of default distro.
Never install Agent Reach into the egress-denied OpenClaw pod.

PRIVACY NOTE: ``web_read`` sends the target URL to the third-party reader
service at r.jina.ai. Every URL a user asks Harvis to read is therefore
disclosed to that operator. The returned payload carries ``"via": "jina"`` so
the disclosure is visible to the model and to any audit of the tool output.

SSRF CONTAINMENT (see ``_safe_get``): the URL scheme and host are checked, DNS
is resolved by us and every record must be public, the TCP connection is pinned
to one of those validated addresses, and redirects are followed manually so
every hop gets the same treatment. The pin is what closes the DNS-rebinding
window — without it, an attacker-controlled name can answer our validation
lookup with a public address and the client's own lookup with 169.254.169.254.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_MAX_CHARS = 24_000
_MAX_REDIRECTS = 5
_MAX_BODY_BYTES = 8 * 1024 * 1024
_USER_AGENT = (
    "Mozilla/5.0 (compatible; HarvisAgentReach/1.0; "
    "+https://github.com/dulc3/harvis-aidev)"
)


def agent_reach_enabled() -> bool:
    return (os.getenv("HARVIS_AGENT_REACH_ENABLED") or "").strip().lower() in _TRUTHY


class ReachBlocked(ValueError):
    """A URL (or a redirect hop) failed the SSRF checks."""


def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    # IPv6 transition forms can smuggle a private IPv4 through an IPv6 literal.
    mapped = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
    if mapped is not None and not _ip_is_public(str(mapped)):
        return False
    return True


def _resolve_public_ips(hostname: str, port: int) -> list[str]:
    """Resolve ``hostname`` and require EVERY answer to be a public address.

    Rejecting on *any* private record (rather than filtering down to the public
    ones) is deliberate: a name that answers with both a public and an internal
    address is a rebinding attempt, not a multi-homed host worth reaching.
    """
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".local"):
        raise ReachBlocked("URL host is not allowed (SSRF protection)")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ReachBlocked(f"could not resolve host {host!r}: {exc}") from exc
    ips: list[str] = []
    for info in infos:
        ip_str = info[4][0]
        if not _ip_is_public(ip_str):
            raise ReachBlocked("URL host resolves to a non-public address (SSRF protection)")
        if ip_str not in ips:
            ips.append(ip_str)
    if not ips:
        raise ReachBlocked(f"no usable address for host {host!r}")
    return ips


def _validate_public_https(url: str) -> str:
    """Scheme/host sanity plus a public-DNS check. Raises ReachBlocked."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ReachBlocked("URL must be http(s)")
    if not parsed.hostname:
        raise ReachBlocked("URL missing host")
    _resolve_public_ips(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    return url


def _pinned_request(
    client: httpx.AsyncClient,
    url: str,
    ip: str,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Request:
    """Build a GET whose TCP target is ``ip`` but whose Host/SNI stay the real name.

    TLS still verifies against the true hostname, because httpcore hands the
    ``sni_hostname`` extension to the SSL layer as ``server_hostname``.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    literal = f"[{ip}]" if ":" in ip else ip
    pinned = urlunparse(
        (
            parsed.scheme,
            f"{literal}:{port}",
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", _USER_AGENT)
    default_port = 443 if parsed.scheme == "https" else 80
    hdrs["Host"] = hostname if port == default_port else f"{hostname}:{port}"
    return client.build_request(
        "GET", pinned, headers=hdrs, extensions={"sni_hostname": hostname}
    )


async def _safe_get(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 25.0,
    host_allowlist: Optional[frozenset[str]] = None,
) -> httpx.Response:
    """GET a public URL, re-validating scheme, host, DNS and pin on EVERY hop.

    ``follow_redirects`` is off on purpose — httpx's own redirect handling would
    jump to hop 2 without any of these checks, which is the hole that made the
    initial-host-only validation decorative.
    """
    current = url
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout), follow_redirects=False
    ) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("https", "http"):
                raise ReachBlocked(f"redirect to non-http(s) scheme: {parsed.scheme!r}")
            if not parsed.hostname:
                raise ReachBlocked("URL missing host")
            if host_allowlist is not None and parsed.hostname.lower() not in host_allowlist:
                raise ReachBlocked(f"host {parsed.hostname!r} is not on this tool's allowlist")
            ips = _resolve_public_ips(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
            resp = await client.send(_pinned_request(client, current, ips[0], headers))

            # Defence in depth: confirm we actually spoke to the pinned address.
            stream = resp.extensions.get("network_stream")
            if stream is not None:
                peer = stream.get_extra_info("server_addr")
                if peer and not _ip_is_public(str(peer[0])):
                    await resp.aclose()
                    raise ReachBlocked("connection landed on a non-public address")

            if resp.is_redirect:
                location = resp.headers.get("location") or ""
                await resp.aclose()
                if not location:
                    raise ReachBlocked("redirect without a Location header")
                current = urljoin(current, location)
                continue

            if len(resp.content) > _MAX_BODY_BYTES:
                raise ReachBlocked("response body too large")
            resp.raise_for_status()
            return resp
    raise ReachBlocked(f"too many redirects (>{_MAX_REDIRECTS})")


async def web_read(url: str) -> dict[str, Any]:
    """Fetch readable text for a public URL via Jina reader (no cookies).

    The target URL is disclosed to r.jina.ai — see the module docstring.
    """
    _validate_public_https(url)
    # Jina reader: https://r.jina.ai/<url>
    resp = await _safe_get(
        f"https://r.jina.ai/{url}",
        headers={"Accept": "text/plain"},
        timeout=30.0,
    )
    text = (resp.text or "")[:_MAX_CHARS]
    return {"ok": True, "url": url, "via": "jina", "text": text, "chars": len(text)}


async def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Find pages for a query. Returns numbered results — no page bodies.

    Without this, a workspace agent could only ``web_read`` a URL it had to invent
    from memory, and a model's memory is exactly what a live question is asking it
    to go past. Measured: asked for "current details on gpt oss 20b" it guessed
    ``huggingface.co/EleutherAI/gpt-oss-20b`` (a repo that does not exist — its
    weights predate OpenAI's gpt-oss), read nothing, and answered about GPT-NeoX.
    The same search agent the chat lane uses returns openai.com and
    github.com/openai/gpt-oss as the top hits for that query.

    Results are numbered so a model that insists on citing ``[1]`` cites something
    real — the same reasoning as ``chat_reach._fmt_results``.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "query": q, "error": "empty query", "results": [], "count": 0}
    n = max(1, min(int(max_results or 5), 10))
    from research.web_search import WebSearchAgent

    # search_web is synchronous and does network I/O — off-thread it so one search
    # doesn't stall every other coroutine on the loop.
    agent = WebSearchAgent(max_results=n)
    raw = await asyncio.to_thread(agent.search_web, q, n)

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append({
            "n": len(results) + 1,
            "title": (r.get("title") or "").strip(),
            "url": url,
            "snippet": (r.get("snippet") or r.get("body") or "").strip()[:400],
        })
        if len(results) >= n:
            break
    if not results:
        # Honest empty: the caller's success test keys off ok, and "the search
        # returned nothing" must not read as "here are your results".
        return {"ok": False, "query": q, "error": "no results", "results": [], "count": 0}
    return {"ok": True, "query": q, "results": results, "count": len(results)}


async def yt_transcript(url: str) -> dict[str, Any]:
    _validate_public_https(url)
    from research.extract.youtube import extract_youtube

    # extract_youtube is synchronous and does network I/O; off-thread it so a
    # transcript fetch does not stall every other coroutine on the loop.
    result = await asyncio.to_thread(extract_youtube, url, timeout_s=25)
    result = result if isinstance(result, dict) else {}
    text = (result.get("text") or "")[:_MAX_CHARS]
    if not text:
        return {
            "ok": False,
            "url": url,
            "error": "no transcript available for this video",
            "title": result.get("title") or "",
            "text": "",
            "chars": 0,
            "source": result.get("source") or "youtube",
        }
    return {
        "ok": True,
        "url": url,
        "title": result.get("title") or "",
        "text": text,
        "chars": len(text),
        "source": result.get("source") or "youtube",
    }


_GH_HOSTS = frozenset(
    {
        "github.com",
        "www.github.com",
        "raw.githubusercontent.com",
        "gist.githubusercontent.com",
        "api.github.com",
    }
)

# owner/repo/path@ref  (documented form) and owner/repo@ref/path (also accepted).
_GH_SHORTHAND_TRAILING_REF = re.compile(r"^([^/@]+)/([^/@]+)/(.+?)(?:@([^/@]+))?$")
_GH_SHORTHAND_INLINE_REF = re.compile(r"^([^/@]+)/([^/@]+)@([^/]+)/(.+)$")


async def gh_view(url_or_path: str) -> dict[str, Any]:
    """Read a public GitHub file or gist via raw.githubusercontent / api.github.com.

    Accepts a full https URL on a GitHub host, or the shorthand
    ``owner/repo/path[@ref]`` (``owner/repo@ref/path`` also works).
    """
    raw = (url_or_path or "").strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in _GH_HOSTS:
            raise ReachBlocked(
                "gh_view only allows github.com / raw.githubusercontent.com hosts"
            )
        _validate_public_https(raw)
        fetch_url = raw
        if host in ("github.com", "www.github.com") and "/blob/" in parsed.path:
            # Convert blob URL → raw
            parts = parsed.path.strip("/").split("/")
            # owner/repo/blob/ref/path...
            if len(parts) >= 5 and parts[2] == "blob":
                owner, repo, ref = parts[0], parts[1], parts[3]
                rest = "/".join(parts[4:])
                fetch_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rest}"
    else:
        inline = _GH_SHORTHAND_INLINE_REF.match(raw)
        trailing = _GH_SHORTHAND_TRAILING_REF.match(raw)
        if inline:
            owner, repo, ref, path = inline.groups()
        elif trailing:
            owner, repo, path, ref = trailing.groups()
            ref = ref or "main"
        else:
            raise ValueError("Expected an https URL or owner/repo/path[@ref]")
        fetch_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

    try:
        resp = await _safe_get(
            fetch_url, headers={"Accept": "text/plain"}, host_allowlist=_GH_HOSTS
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"ok": False, "url": fetch_url, "error": "not found"}
        raise
    text = (resp.text or "")[:_MAX_CHARS]
    return {"ok": True, "url": fetch_url, "text": text, "chars": len(text)}


def _parse_feed(xml: str, max_items: int) -> tuple[bool, str, list[dict[str, str]]]:
    """Return (parsed_ok, feed_title, items).

    ``parsed_ok`` is False only when the payload could not be understood as a
    feed at all. A well-formed feed with zero entries is a real, empty feed and
    reports True — the caller must be able to tell "nothing published" apart
    from "we could not read this".
    """
    try:
        import feedparser  # type: ignore
    except ImportError:
        feedparser = None  # type: ignore[assignment]

    if feedparser is not None:
        try:
            parsed = feedparser.parse(xml)
        except Exception as exc:  # pragma: no cover - feedparser is very forgiving
            logger.warning("feedparser raised on feed body: %s", exc)
        else:
            entries = list(parsed.entries or [])
            title = getattr(parsed.feed, "title", "") or ""
            # bozo means malformed XML. feedparser still returns partial entries
            # for recoverable damage, so only treat it as a failure when it also
            # produced nothing usable.
            if entries or (not getattr(parsed, "bozo", 0) and title):
                items = [
                    {
                        "title": getattr(e, "title", "") or "",
                        "link": getattr(e, "link", "") or "",
                        "summary": (getattr(e, "summary", "") or "")[:500],
                    }
                    for e in entries[:max_items]
                ]
                return True, title, items

    # Fallback: regex titles/links out of <item> blocks.
    items: list[dict[str, str]] = []
    for m in re.finditer(
        r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>"
        r".*?<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>",
        xml,
        re.I | re.S,
    ):
        items.append({"title": m.group(1).strip(), "link": m.group(2).strip(), "summary": ""})
        if len(items) >= max_items:
            break
    if items:
        return True, "", items
    return False, "", []


async def rss_read(url: str, *, max_items: int = 10) -> dict[str, Any]:
    _validate_public_https(url)
    max_items = max(1, min(int(max_items or 10), 25))
    resp = await _safe_get(url)
    xml = resp.text or ""

    parsed_ok, title, items = _parse_feed(xml, max_items)
    if not parsed_ok:
        return {
            "ok": False,
            "url": url,
            "error": (
                "response was not a readable RSS/Atom feed "
                f"(content-type {resp.headers.get('content-type', 'unknown')!r}, "
                f"{len(xml)} chars)"
            ),
            "feed_title": "",
            "items": [],
            "count": 0,
        }
    return {"ok": True, "url": url, "feed_title": title, "items": items, "count": len(items)}


async def dispatch_agent_reach(name: str, args: dict) -> str:
    """Run one agent_reach.* tool. Returns text for the model. Never raises."""
    if not agent_reach_enabled():
        return (
            "DENIED: Agent Reach is disabled "
            "(set HARVIS_AGENT_REACH_ENABLED=1). Never install Agent Reach inside OpenClaw."
        )
    args = args if isinstance(args, dict) else {}
    try:
        if name == "agent_reach.web_search":
            out = await web_search(
                str(args.get("query") or args.get("q") or ""),
                max_results=int(args.get("max_results") or 5),
            )
        elif name == "agent_reach.web_read":
            out = await web_read(str(args.get("url") or ""))
        elif name == "agent_reach.yt_transcript":
            out = await yt_transcript(str(args.get("url") or ""))
        elif name == "agent_reach.gh_view":
            out = await gh_view(str(args.get("url") or args.get("path") or ""))
        elif name == "agent_reach.rss_read":
            out = await rss_read(
                str(args.get("url") or ""),
                max_items=int(args.get("max_items") or 10),
            )
        else:
            return f"ERROR: unknown Agent Reach tool '{name}'"
        import json

        # A tool that answered with ok:false is a failure, not a result. Say so in
        # the first token so the caller's success test cannot read it as success.
        if isinstance(out, dict) and out.get("ok") is False:
            return f"ERROR: {name} failed: {out.get('error') or 'no result'}"
        return json.dumps(out, ensure_ascii=False)[:_MAX_CHARS]
    except ReachBlocked as exc:
        logger.warning("agent_reach %s blocked: %s", name, exc)
        return f"DENIED: {name} blocked: {exc}"
    except Exception as exc:
        logger.warning("agent_reach %s failed: %s", name, exc)
        return f"ERROR: {name} failed: {exc}"
