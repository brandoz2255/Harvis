"""MCP over HTTP — the remote half of the client.

``protocol.py`` speaks MCP down a pair of asyncio streams, which is what a
stdio server behind the container bridge gives us. A hosted server (Higgsfield,
Linear, Notion's remote endpoint, anything on a URL) speaks one of two HTTP
transports instead, and this module implements both against the same
``_McpMethods`` surface, so ``tool_bridge`` never learns that remote servers
exist.

**Streamable HTTP** (spec revision 2025-03-26, what new servers ship) is one
endpoint that takes a POSTed JSON-RPC message and answers either with a single
JSON body or with an SSE stream carrying the reply. The server may hand back an
``Mcp-Session-Id`` on initialize which every later request must echo.

**HTTP+SSE** (revision 2024-11-05, the legacy shape) is two channels: a long
lived GET that streams every server→client message, whose first event names a
second URL that client→server messages get POSTed to.

Which one a URL speaks is not reliably declared anywhere, and the transport
label stored on a connection is frequently wrong — Higgsfield's own row said
``sse`` while the endpoint is streamable. So ``open_http_session`` *tries* one
and falls back to the other rather than trusting the label. A 401 stops the
search immediately: that is an auth problem, not a transport mismatch, and
retrying the other shape would only produce a second misleading error.

SSRF: the backend is dual-homed onto the internal network with pgsql, ollama
and openclaw on it, so a connection URL is attacker-reachable infrastructure if
it is left unchecked. ``guard_url`` resolves the host and refuses private,
loopback and link-local addresses unless ``HARVIS_MCP_ALLOW_PRIVATE_URLS`` is
set (which a self-hoster pointing at a LAN server legitimately needs). This is
a connect-time check and therefore does not defeat DNS rebinding — stated
plainly rather than implied away.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from .protocol import (
    _CALL_TIMEOUT,
    _INIT_TIMEOUT,
    _LIST_TIMEOUT,
    CLIENT_INFO,
    McpAuthRequired,
    McpError,
    McpTransportError,
    _McpMethods,
)

logger = logging.getLogger(__name__)

_FALSY = {"0", "false", "no", "off", ""}

# A hosted server's reply can be large; the same 8 MB ceiling the stdio side
# uses keeps one connector from eating the backend.
_MAX_BODY = 8 * 1024 * 1024

# The legacy transport cannot send anything until the GET stream has named the
# POST endpoint. If that never arrives the URL is not an SSE endpoint.
_ENDPOINT_TIMEOUT = 20.0

STREAMABLE = "streamable-http"
LEGACY_SSE = "sse"


class _WrongTransport(McpError):
    """This URL does not speak the shape we tried. Internal to negotiation."""


# -- SSRF guard ------------------------------------------------------------


def _allow_private() -> bool:
    return os.getenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "").strip().lower() not in _FALSY


def _classify(ip: str) -> Optional[str]:
    """Return a refusal reason for this address, or None if it is fine."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    # Cloud metadata lives here. No MCP server ever legitimately does, so this
    # one stays refused even when private addresses are allowed.
    if addr.is_link_local:
        # Cloud metadata lives here and no allow-flag should reach it, so this
        # reason is phrased as final — it is the one refusal with no escape.
        return "a link-local address, which is never allowed"
    if _allow_private():
        return None
    if addr.is_loopback:
        return "a loopback address"
    if addr.is_private:
        return "a private address"
    if addr.is_reserved or addr.is_multicast:
        return "a reserved address"
    return None


def guard_url(url: str) -> str:
    """Validate a connection URL. Returns it stripped, or raises McpError."""
    raw = (url or "").strip()
    if not raw:
        raise McpError("remote connections need a URL")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise McpError(f"unsupported URL scheme '{parts.scheme or 'none'}' — use http or https")
    host = parts.hostname
    if not host:
        raise McpError("that URL has no host")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError as exc:
        raise McpError(f"could not resolve '{host}': {exc}") from exc
    for info in infos:
        reason = _classify(info[4][0])
        if reason:
            hint = (
                ""
                if "never allowed" in reason
                else "; set HARVIS_MCP_ALLOW_PRIVATE_URLS=1 to allow connecting "
                     "to servers on your own network"
            )
            raise McpError(f"'{host}' resolves to {reason}{hint}")
    return raw


async def guard_url_async(url: str) -> str:
    return await asyncio.to_thread(guard_url, url)


# -- SSE framing -----------------------------------------------------------


class _SseDecoder:
    """Minimal ``text/event-stream`` decoder — ``event`` and ``data`` only.

    Hand-rolled rather than pulled from a library because the two transports
    need slightly different dispatch and the format is a dozen lines.
    """

    def __init__(self) -> None:
        self._event = ""
        self._data: list[str] = []

    def feed(self, line: str) -> Optional[tuple[str, str]]:
        """Feed one line. Returns ``(event, data)`` when a frame completes."""
        if line == "":
            if not self._data:
                self._event = ""
                return None
            frame = (self._event or "message", "\n".join(self._data))
            self._event = ""
            self._data = []
            return frame
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "data":
            self._data.append(value)
        return None


# -- the session -----------------------------------------------------------


class HttpMcpSession(_McpMethods):
    """One MCP session against a URL, in either HTTP transport shape."""

    def __init__(
        self,
        url: str,
        *,
        mode: str = STREAMABLE,
        headers: Optional[dict] = None,
        label: str = "mcp",
    ) -> None:
        super().__init__()
        self._url = url
        self._mode = mode
        self._label = label
        self._extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self._session_id: Optional[str] = None
        self._initialized = False
        self._closed = False
        self._next_id = 0
        # Legacy transport only: replies arrive out-of-band on the GET stream.
        self._pending: dict[int, asyncio.Future] = {}
        self._post_url: Optional[str] = None
        self._endpoint_ready = asyncio.Event()
        self._pump: Optional[asyncio.Task] = None
        self._pump_error: Optional[Exception] = None
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(_CALL_TIMEOUT, connect=15.0, read=_CALL_TIMEOUT),
        )

    @property
    def mode(self) -> str:
        return self._mode

    # -- lifecycle ---------------------------------------------------------

    async def _open(self) -> None:
        if self._mode != LEGACY_SSE or self._pump is not None:
            return
        self._pump = asyncio.create_task(self._sse_pump())
        timed_out = False
        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), _ENDPOINT_TIMEOUT)
        except asyncio.TimeoutError:
            timed_out = True
        # The pump sets the event on failure too, so that a 401 surfaces as a
        # 401 rather than as a timeout. Waking up is not the same as succeeding.
        if timed_out or self._pump_error is not None or not self._post_url:
            err = self._pump_error or _WrongTransport(
                "no SSE endpoint event arrived — this URL is not an HTTP+SSE endpoint"
            )
            await self.close()
            raise err

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except (asyncio.CancelledError, Exception):
                pass
            self._pump = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpError("session closed"))
        self._pending.clear()
        # Streamable HTTP sessions are server-side state; releasing them is
        # politeness that costs one request and prevents leaked sessions.
        if self._mode == STREAMABLE and self._session_id:
            try:
                await self._client.delete(
                    self._url, headers=self._headers(), timeout=10.0
                )
            except Exception:
                pass
        try:
            await self._client.aclose()
        except Exception:
            pass

    # -- headers -----------------------------------------------------------

    def _headers(self, *, accept: str = "application/json, text/event-stream") -> dict:
        headers = {
            "Accept": accept,
            "Content-Type": "application/json",
            "User-Agent": f"harvis-mcp/{CLIENT_INFO.get('version', '1.0')}",
        }
        headers.update(self._extra_headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._initialized:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    # -- request plumbing --------------------------------------------------

    def _envelope(self, method: str, params: dict) -> tuple[dict, int]:
        self._next_id += 1
        rid = self._next_id
        return (
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
            rid,
        )

    async def _request(self, method: str, params: dict, *, timeout: float) -> Any:
        if self._closed:
            raise McpTransportError("session closed")
        payload, rid = self._envelope(method, params)
        if self._mode == STREAMABLE:
            result = await self._streamable_request(payload, rid, timeout)
        else:
            result = await self._legacy_request(payload, rid, timeout)
        if method == "initialize":
            self.protocol_version = (
                (result or {}).get("protocolVersion") or self.protocol_version
            )
            self._initialized = True
        return result

    async def _notify(self, method: str, params: dict) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        target = self._url if self._mode == STREAMABLE else (self._post_url or self._url)
        try:
            resp = await self._client.post(
                target, json=payload, headers=self._headers(), timeout=30.0
            )
            # A notification's only failure worth surfacing is auth.
            if resp.status_code == 401:
                raise self._auth_error(resp)
        except httpx.HTTPError as exc:
            logger.debug("mcp[%s]: notification %s failed: %s", self._label, method, exc)

    def _auth_error(self, resp: httpx.Response) -> McpAuthRequired:
        return McpAuthRequired(
            "the server requires authorization",
            www_authenticate=resp.headers.get("www-authenticate", ""),
            url=self._url,
        )

    def _unwrap(self, msg: Any, rid: int) -> tuple[bool, Any]:
        """``(is_our_reply, result)``. Raises on a JSON-RPC error for our id."""
        if not isinstance(msg, dict) or msg.get("id") != rid:
            return (False, None)
        if "error" in msg:
            err = msg.get("error") or {}
            raise McpError(
                f"{err.get('message') or 'server error'} (code {err.get('code')})"
            )
        return (True, msg.get("result"))

    # -- streamable HTTP ---------------------------------------------------

    async def _streamable_request(self, payload: dict, rid: int, timeout: float) -> Any:
        try:
            async with self._client.stream(
                "POST",
                self._url,
                json=payload,
                headers=self._headers(),
                timeout=httpx.Timeout(timeout, connect=15.0, read=timeout),
            ) as resp:
                if resp.status_code == 401:
                    raise self._auth_error(resp)
                if resp.status_code in (404, 405, 406, 415):
                    await resp.aread()
                    raise _WrongTransport(
                        f"{self._url} answered {resp.status_code} to a streamable-HTTP POST"
                    )
                if resp.status_code >= 400:
                    body = (await resp.aread())[:400].decode("utf-8", "replace")
                    raise McpError(f"server returned HTTP {resp.status_code}: {body}")

                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self._session_id = sid

                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
                if ctype == "text/event-stream":
                    return await self._read_stream_for(resp, rid)
                body = await resp.aread()
                if not body.strip():
                    raise _WrongTransport("empty body where a JSON-RPC reply was expected")
                if ctype and ctype != "application/json":
                    raise _WrongTransport(f"unexpected content-type '{ctype}'")
                try:
                    msg = json.loads(body[:_MAX_BODY])
                except ValueError as exc:
                    raise _WrongTransport(f"reply was not JSON: {exc}") from exc
                for candidate in msg if isinstance(msg, list) else [msg]:
                    ours, result = self._unwrap(candidate, rid)
                    if ours:
                        return result
                raise McpError("server replied without answering the request")
        except httpx.HTTPError as exc:
            raise McpTransportError(
                f"could not reach {self._url}: {exc}"
            ) from exc

    async def _read_stream_for(self, resp: httpx.Response, rid: int) -> Any:
        """Consume an SSE reply stream until our own answer shows up."""
        decoder = _SseDecoder()
        async for line in resp.aiter_lines():
            frame = decoder.feed(line.rstrip("\r"))
            if frame is None:
                continue
            _event, data = frame
            if not data.strip():
                continue
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            for candidate in msg if isinstance(msg, list) else [msg]:
                if self._is_server_request(candidate):
                    asyncio.create_task(self._decline(candidate))
                    continue
                ours, result = self._unwrap(candidate, rid)
                if ours:
                    return result
        raise McpError("the reply stream ended before the server answered")

    def _is_server_request(self, msg: Any) -> bool:
        return (
            isinstance(msg, dict)
            and msg.get("method") is not None
            and msg.get("id") is not None
        )

    async def _decline(self, msg: dict) -> None:
        """We advertise no capabilities, so a server request gets a clean no."""
        target = self._url if self._mode == STREAMABLE else (self._post_url or self._url)
        try:
            await self._client.post(
                target,
                json={
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "error": {"code": -32601, "message": "client declares no capabilities"},
                },
                headers=self._headers(),
                timeout=15.0,
            )
        except Exception:
            pass

    # -- legacy HTTP+SSE ---------------------------------------------------

    async def _legacy_request(self, payload: dict, rid: int, timeout: float) -> Any:
        if not self._post_url:
            raise McpError("the SSE endpoint has not been announced yet")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            resp = await self._client.post(
                self._post_url, json=payload, headers=self._headers(), timeout=timeout
            )
            if resp.status_code == 401:
                raise self._auth_error(resp)
            if resp.status_code >= 400:
                raise McpError(
                    f"server returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise McpTransportError(
                f"{payload.get('method')} timed out after {timeout:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise McpError(f"could not reach {self._post_url}: {exc}") from exc
        finally:
            self._pending.pop(rid, None)

    async def _sse_pump(self) -> None:
        """Hold the GET stream open and dispatch everything that arrives."""
        decoder = _SseDecoder()
        try:
            async with self._client.stream(
                "GET",
                self._url,
                headers=self._headers(accept="text/event-stream"),
                timeout=httpx.Timeout(None, connect=15.0, read=None),
            ) as resp:
                if resp.status_code == 401:
                    self._pump_error = self._auth_error(resp)
                    self._endpoint_ready.set()
                    return
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
                if resp.status_code >= 400 or ctype != "text/event-stream":
                    self._pump_error = _WrongTransport(
                        f"{self._url} answered {resp.status_code} "
                        f"({ctype or 'no content-type'}) to an SSE GET"
                    )
                    self._endpoint_ready.set()
                    return
                async for line in resp.aiter_lines():
                    frame = decoder.feed(line.rstrip("\r"))
                    if frame is None:
                        continue
                    self._dispatch(*frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._pump_error = McpError(f"SSE stream failed: {exc}")
            self._endpoint_ready.set()
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(
                        McpTransportError("server closed the stream")
                    )
            self._pending.clear()

    def _dispatch(self, event: str, data: str) -> None:
        if event == "endpoint":
            # Servers send this relative far more often than absolute.
            self._post_url = urljoin(self._url, data.strip())
            self._endpoint_ready.set()
            return
        if not data.strip():
            return
        try:
            msg = json.loads(data)
        except ValueError:
            return
        for candidate in msg if isinstance(msg, list) else [msg]:
            if self._is_server_request(candidate):
                asyncio.create_task(self._decline(candidate))
                continue
            if not isinstance(candidate, dict):
                continue
            fut = self._pending.get(candidate.get("id"))
            if fut is None or fut.done():
                continue
            if "error" in candidate:
                err = candidate.get("error") or {}
                fut.set_exception(
                    McpError(f"{err.get('message') or 'server error'} (code {err.get('code')})")
                )
            else:
                fut.set_result(candidate.get("result"))


# -- negotiation -----------------------------------------------------------


async def open_http_session(
    url: str,
    *,
    headers: Optional[dict] = None,
    label: str = "mcp",
    prefer: str = "",
) -> tuple[HttpMcpSession, list[dict]]:
    """Connect, handshake and list tools. Returns ``(session, tools)``.

    Tries the likelier transport first and falls back to the other, because the
    stored transport label is advisory at best.
    """
    safe_url = await guard_url_async(url)
    path = urlsplit(safe_url).path.rstrip("/")
    sse_first = prefer == LEGACY_SSE or path.endswith("/sse")
    order = [LEGACY_SSE, STREAMABLE] if sse_first else [STREAMABLE, LEGACY_SSE]

    first_error: Optional[Exception] = None
    for mode in order:
        session = HttpMcpSession(safe_url, mode=mode, headers=headers, label=label)
        try:
            await session.initialize()
            tools = await session.list_tools()
            return (session, tools)
        except McpAuthRequired:
            # Not a transport problem. Trying the other shape would only
            # replace a true 401 with a misleading 404.
            await session.close()
            raise
        except _WrongTransport as exc:
            await session.close()
            first_error = first_error or exc
            logger.debug("mcp[%s]: %s transport rejected — %s", label, mode, exc)
            continue
        except Exception:
            await session.close()
            raise
    raise McpError(
        f"{url} did not answer as either a streamable-HTTP or an HTTP+SSE MCP "
        f"endpoint ({first_error})"
    )
