"""MCP client protocol — JSON-RPC 2.0 over newline-delimited JSON.

Harvis implements the client half of MCP here rather than depending on the
MCP Python SDK. Two reasons: the client surface we actually need is small
(``initialize`` · ``tools/list`` · ``tools/call``), and the backend image is
deliberately slim — the whole deploy track is fighting for megabytes, so an
SDK plus its transitive deps is a poor trade for ~200 lines.

The transport is whatever pair of asyncio streams the caller hands in. For a
stdio server that's a TCP connection to the bridge inside the server's
container (see runtime.py); for a remote HTTP server the caller uses
``HttpMcpSession`` instead. Both expose the same three methods so the tool
layer never branches on transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "harvis", "version": "1.2"}

# A server that hasn't answered initialize in this long is not going to.
_INIT_TIMEOUT = 60.0
# tools/list is cheap; tools/call can legitimately be slow (network, LLM calls).
_LIST_TIMEOUT = 30.0
_CALL_TIMEOUT = 120.0

# One JSON-RPC line can carry a whole tool result. 8 MB is far above any
# reasonable payload and far below anything that would exhaust the backend.
_MAX_LINE = 8 * 1024 * 1024


class McpError(RuntimeError):
    """A server-reported JSON-RPC error, or a protocol-level failure."""


class McpSession:
    """One live MCP session over a duplex stream pair.

    Not thread-safe and not re-entrant across event loops — the runtime owns
    exactly one session per (user, server) and serialises calls through it.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        label: str = "mcp",
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._label = label
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._pump: Optional[asyncio.Task] = None
        self._closed = False
        self.server_info: dict = {}
        self.capabilities: dict = {}

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Begin reading. Must be called before any request."""
        if self._pump is None:
            self._pump = asyncio.create_task(self._read_loop())

    async def initialize(self) -> dict:
        """MCP handshake. Returns the server's ``initialize`` result."""
        await self.start()
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                # We advertise nothing: Harvis does not currently serve
                # sampling or roots back to the server, and claiming a
                # capability we don't implement makes servers call into a
                # hole. An empty object is the honest declaration.
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout=_INIT_TIMEOUT,
        )
        self.server_info = (result or {}).get("serverInfo") or {}
        self.capabilities = (result or {}).get("capabilities") or {}
        await self._notify("notifications/initialized", {})
        return result or {}

    async def list_tools(self) -> list[dict]:
        """Every tool the server exposes, following ``nextCursor`` pagination."""
        tools: list[dict] = []
        cursor: Optional[str] = None
        # Bounded: a server paging forever must not hang the connect flow.
        for _ in range(50):
            params = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params, timeout=_LIST_TIMEOUT)
            page = (result or {}).get("tools") or []
            tools.extend(t for t in page if isinstance(t, dict))
            cursor = (result or {}).get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(
        self, name: str, arguments: dict, *, timeout: float = _CALL_TIMEOUT
    ) -> dict:
        """Invoke one tool. Returns the raw MCP result (content blocks + isError)."""
        return await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        ) or {}

    async def close(self) -> None:
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
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    # -- wire --------------------------------------------------------------

    async def _request(self, method: str, params: dict, *, timeout: float) -> Any:
        if self._closed:
            raise McpError("session closed")
        self._next_id += 1
        req_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise McpError(f"{method} timed out after {timeout:.0f}s") from exc
        finally:
            self._pending.pop(req_id, None)

    async def _notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self._writer.write(line)
        await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                try:
                    line = await self._reader.readuntil(b"\n")
                except asyncio.LimitOverrunError:
                    # Oversized frame: drain it rather than desync the stream.
                    logger.warning("mcp[%s]: oversized frame dropped", self._label)
                    await self._reader.read(_MAX_LINE)
                    continue
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    # Servers that print banners to stdout are common enough
                    # that this must not be fatal.
                    logger.debug("mcp[%s]: non-JSON stdout line ignored", self._label)
                    continue
                self._handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("mcp[%s]: read loop failed", self._label)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(McpError("server closed the connection"))
            self._pending.clear()

    def _handle(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            return
        msg_id = msg.get("id")
        if msg_id is not None and ("result" in msg or "error" in msg):
            fut = self._pending.get(msg_id)
            if fut is None or fut.done():
                return
            if "error" in msg:
                err = msg.get("error") or {}
                fut.set_exception(
                    McpError(f"{err.get('message') or 'server error'} "
                             f"(code {err.get('code')})")
                )
            else:
                fut.set_result(msg.get("result"))
            return
        # A request FROM the server (sampling, roots, elicitation). We declared
        # no capabilities, so answering "method not found" is correct and keeps
        # the server from blocking forever waiting on us.
        if msg_id is not None and msg.get("method"):
            asyncio.create_task(
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": "client declares no capabilities",
                        },
                    }
                )
            )


def flatten_content(result: dict) -> tuple[str, bool]:
    """Turn an MCP tool result into ``(text, ok)`` for the agent loop.

    MCP returns a list of typed content blocks; the tool loop consumes plain
    text. Non-text blocks are named rather than dropped silently, because a
    tool that returned an image and appears to have returned nothing is the
    kind of thing that reads as a bug for weeks.
    """
    if not isinstance(result, dict):
        return ("tool returned no result", False)

    is_error = bool(result.get("isError"))
    parts: list[str] = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} returned: {block.get('mimeType') or 'unknown type'}]")
        elif kind == "resource":
            res = block.get("resource") or {}
            if isinstance(res, dict) and res.get("text"):
                parts.append(str(res["text"]))
            else:
                parts.append(f"[resource: {(res or {}).get('uri') or 'unknown'}]")

    # Servers may answer with structuredContent and no text blocks at all.
    if not parts and result.get("structuredContent") is not None:
        try:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(result["structuredContent"]))

    text = "\n".join(p for p in parts if p).strip()
    if not text:
        text = "tool returned an error" if is_error else "tool returned no output"
    return (text, not is_error)
