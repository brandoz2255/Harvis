"""Reach a port inside a chat's box without giving the box a network.

The box runs with Docker network ``none`` (see terminal_container._spawn_isolated),
so nothing can connect to it by name or address — not the backend, not another
box. To show an app the box is serving, the backend opens a ``docker exec`` of
``socat - TCP:127.0.0.1:<port>`` inside it and speaks HTTP or WebSocket over that
exec's stdin/stdout. Docker frames the exec's output (8-byte header per chunk);
stdin goes in raw.

``transport()`` gives an httpx transport whose connections are such tunnels, and
``open_socket()`` a plain socket for libraries (websockets) that want one.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Any, Awaitable, Callable, Optional

import httpcore
import httpx

log = logging.getLogger("workspace.box_tunnel")

_USER = "1001:1001"
ClientGetter = Callable[[], Awaitable[Any]]


async def _docker_client() -> Any:
    from workspace.terminal_container import get_terminal_manager

    client = get_terminal_manager()._client  # noqa: SLF001
    if client is None:
        raise ConnectionError("docker client unavailable")
    return client


class ExecStream(httpcore.AsyncNetworkStream):
    """One ``docker exec`` of socat, read and written as a byte stream."""

    def __init__(self, raw: socket.socket, keep: Any) -> None:
        self._raw = raw
        self._keep = keep  # docker-py's socket wrapper: closing it with us, not before
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending = b""

    async def _open(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(sock=self._raw)

    async def _frame(self) -> bytes:
        """The next stdout chunk; b"" at end of stream. stderr chunks are dropped."""
        assert self._reader is not None
        while True:
            try:
                head = await self._reader.readexactly(8)
            except asyncio.IncompleteReadError:
                return b""
            kind, size = head[0], struct.unpack(">I", head[4:8])[0]
            try:
                body = await self._reader.readexactly(size)
            except asyncio.IncompleteReadError:
                return b""
            if kind == 1 and body:
                return body

    async def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        if not self._pending:
            try:
                self._pending = await asyncio.wait_for(self._frame(), timeout)
            except asyncio.TimeoutError:
                raise httpcore.ReadTimeout("box tunnel read timed out") from None
        out, self._pending = self._pending[:max_bytes], self._pending[max_bytes:]
        return out

    async def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        assert self._writer is not None
        self._writer.write(buffer)
        try:
            await asyncio.wait_for(self._writer.drain(), timeout)
        except asyncio.TimeoutError:
            raise httpcore.WriteTimeout("box tunnel write timed out") from None

    async def aclose(self) -> None:
        if self._writer is not None:
            self._writer.close()
        else:
            self._raw.close()
        try:
            self._keep.close()
        except Exception:  # noqa: BLE001
            pass

    async def start_tls(self, ssl_context: Any, server_hostname: Optional[str] = None,
                        timeout: Optional[float] = None) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("box apps are plain HTTP")

    def get_extra_info(self, info: str) -> Any:
        return None


def _exec_socat(client: Any, container: str, port: int) -> tuple[socket.socket, Any]:
    api = client.api
    ex = api.exec_create(container, ["socat", "-", f"TCP:127.0.0.1:{port}"],
                         stdin=True, stdout=True, stderr=False, tty=False, user=_USER)
    wrapped = api.exec_start(ex["Id"], socket=True)
    inner = getattr(wrapped, "_sock", wrapped)
    raw = inner.dup()  # our own descriptor, so docker-py's wrapper can't close it under us
    raw.setblocking(False)
    return raw, wrapped


async def connect(container: str, port: int, client_getter: ClientGetter = _docker_client) -> ExecStream:
    if not (1 <= port <= 65535):
        raise httpcore.ConnectError(f"bad port {port}")
    client = await client_getter()
    try:
        raw, keep = await asyncio.to_thread(_exec_socat, client, container, port)
    except Exception as exc:  # noqa: BLE001 — no such box, box stopped, Docker down
        raise httpcore.ConnectError(f"box {container!r} unreachable: {exc}") from None
    stream = ExecStream(raw, keep)
    await stream._open()
    return stream


class _Backend(httpcore.AsyncNetworkBackend):
    def __init__(self, client_getter: ClientGetter) -> None:
        self._client_getter = client_getter

    async def connect_tcp(self, host: str, port: int, timeout: Optional[float] = None,
                          local_address: Optional[str] = None, socket_options: Any = None,
                          ) -> httpcore.AsyncNetworkStream:
        try:
            return await asyncio.wait_for(connect(host, port, self._client_getter), timeout)
        except asyncio.TimeoutError:
            raise httpcore.ConnectTimeout(f"box {host!r} did not answer") from None

    async def connect_unix_socket(self, *a: Any, **kw: Any) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("not supported")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def transport(client_getter: ClientGetter = _docker_client) -> httpx.AsyncHTTPTransport:
    """An httpx transport where ``http://<box name>:<port>/`` is a port inside that box."""
    t = httpx.AsyncHTTPTransport(retries=0)
    t._pool = httpcore.AsyncConnectionPool(  # noqa: SLF001 — httpx has no public hook for this
        network_backend=_Backend(client_getter), max_connections=20, keepalive_expiry=30.0)
    return t


async def open_socket(container: str, port: int,
                      client_getter: ClientGetter = _docker_client) -> tuple[socket.socket, asyncio.Task]:
    """A connected socket for a port in the box, plus the task pumping it.

    One end of a socketpair goes to the caller; the other is pumped to and from
    the exec. Cancel the task (or close the socket) to tear it down."""
    stream = await connect(container, port, client_getter)
    ours, theirs = socket.socketpair()
    ours.setblocking(False)
    reader, writer = await asyncio.open_connection(sock=ours)

    async def down() -> None:
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                return
            writer.write(chunk)
            await writer.drain()

    async def up() -> None:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                return
            await stream.write(chunk)

    async def pump() -> None:
        tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            writer.close()
            await stream.aclose()

    return theirs, asyncio.create_task(pump())
