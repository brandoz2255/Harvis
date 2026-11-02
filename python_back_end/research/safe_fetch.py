"""Fetching pages that a search engine, or another web page, picked.

The research code reads URLs nobody on this server chose: search results, and wherever
a public page redirects. On a shared host that is a way to make the server fetch
``http://169.254.169.254/...`` or ``http://pgsql:5432/`` and print what came back into
the report. ``fetch`` dials only public addresses (``providers.guarded_sync_client``
resolves once, vets every answer and connects to the vetted one), ignores environment
proxies and re-checks each redirect hop. ``enabled`` says when to use it: on a shared
host, whoever asked, because the URL is not the asker's. A local install keeps plain
``requests``.
"""
from __future__ import annotations

import contextlib
import contextvars
import zlib
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from plugins.hermes_ui import providers

MAX_REDIRECTS = 5
MAX_BYTES = 10 * 1024 * 1024
_FRAMING_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}
# httpx decodes br and zstd a whole raw chunk at a time before any size check, so a
# few KB of brotli can inflate to gigabytes. Ask for gzip/deflate only, refuse anything
# else, and inflate here with a hard output limit (same rule as agent_reach.tools).
_ACCEPT_ENCODING = "gzip, deflate"
_INFLATE_STEP = 256 * 1024


class FetchBlocked(ValueError):
    """The URL, or a redirect it led to, is not one this server will fetch."""


_forced: contextvars.ContextVar[bool] = contextvars.ContextVar("safe_fetch_forced", default=False)


@contextlib.contextmanager
def forced() -> Iterator[None]:
    """Guard every fetch made inside the block, whatever the exposure mode. For a URL
    that arrived in a chat message: the address is vetted at connect time and each
    redirect hop is re-vetted, on a local install too."""
    token = _forced.set(True)
    try:
        yield
    finally:
        _forced.reset(token)


def enabled() -> bool:
    from plugins.exposure import shared

    return _forced.get() or shared()


def is_youtube_host(url: str) -> bool:
    """True only when the URL's host is YouTube itself. A substring test passes
    ``http://pgsql:5432/?youtube.com``, which yt-dlp's generic extractor would then fetch."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in ("youtube.com", "youtu.be"))


def _encoding(headers: httpx.Headers) -> str:
    names = [n.strip() for n in (headers.get("content-encoding") or "").lower().split(",")]
    names = [n for n in names if n and n != "identity"]
    if not names:
        return ""
    if len(names) == 1 and names[0] in ("gzip", "x-gzip", "deflate"):
        return "deflate" if names[0] == "deflate" else "gzip"
    raise FetchBlocked("unsupported content encoding")


def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    """The decoded body, never holding more than ``max_bytes`` of it."""
    encoding = _encoding(resp.headers)
    body = bytearray()
    raw_total = 0
    inflater = None
    first = True
    for chunk in resp.iter_raw():
        raw_total += len(chunk)
        if raw_total > max_bytes:
            raise FetchBlocked("response too large")
        if not encoding:
            body += chunk
            continue
        if inflater is None:
            inflater = zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS)
        data = chunk
        while data and not inflater.eof:
            try:
                piece = inflater.decompress(data, min(_INFLATE_STEP, max_bytes - len(body) + 1))
            except zlib.error:
                if first and encoding == "deflate":
                    inflater = zlib.decompressobj(-zlib.MAX_WBITS)  # raw deflate, no zlib header
                    first = False
                    continue
                raise FetchBlocked("response could not be decompressed") from None
            first = False
            body += piece
            if len(body) > max_bytes:
                raise FetchBlocked("response too large")
            data = inflater.unconsumed_tail
        if inflater.eof:
            break
    return bytes(body)


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    timeout: float = 15.0,
    max_bytes: int = MAX_BYTES,
    network_backend: Optional[httpcore.NetworkBackend] = None,
    vet: Callable[[Any], None] = providers._require_global,
) -> httpx.Response:
    """GET (or HEAD) a public URL, following redirects by hand. Raises ``FetchBlocked``
    for a refused address or hop, ``httpx.HTTPError`` for ordinary network failures.
    The refusal never says which internal name or address was behind the URL."""
    current = url
    headers = {**{k: v for k, v in (headers or {}).items() if k.lower() != "accept-encoding"},
               "Accept-Encoding": _ACCEPT_ENCODING}
    try:
        with providers.guarded_sync_client(network_backend, vet, timeout=timeout) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                if urlsplit(current).scheme not in ("http", "https"):
                    raise FetchBlocked("not an http(s) URL")
                with client.stream(method, current, headers=headers) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location") or ""
                        if not location:
                            raise FetchBlocked("redirect without a Location header")
                        current = urljoin(current, location)
                        continue
                    body = _read_capped(resp, max_bytes)
                    kept = [(k, v) for k, v in resp.headers.items() if k.lower() not in _FRAMING_HEADERS]
                    return httpx.Response(resp.status_code, headers=kept, content=body, request=resp.request)
            raise FetchBlocked("too many redirects")
    except providers.EndpointValidationError:
        raise FetchBlocked("address not allowed") from None
