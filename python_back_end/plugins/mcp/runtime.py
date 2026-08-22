"""MCP server runtime — spawns and holds live sessions to a user's servers.

## Why containers

The plugin catalog's ``install`` cards promise "Harvis runs the server itself
(stdio via npx/uvx)". The backend image has neither: it is ``python:3.12-slim``
with no Node and no uv, deliberately, because the deploy track is fighting for
image size. Adding a Node toolchain to the API image to run third-party npm
packages would be the worst of both worlds — bigger image AND arbitrary
untrusted code executing as the backend.

So an MCP server runs the same way an untrusted repo does: as a sibling
container on an isolated network, from the polyglot sandbox image that already
ships Node 20 + npx + uv + uvx, with capabilities dropped, no-new-privileges,
resource caps, no host mounts, and no route to pgsql / the LLM / other users'
data. This reuses the hardening the Repo Runner already proved rather than
inventing a second, weaker sandbox.

## Why a TCP bridge

An MCP stdio server speaks newline-JSON on stdin/stdout. Reaching those across
a container boundary means the Docker attach socket, which is a multiplexed
blocking stream that fits asyncio badly. Instead the container's main process
is a ~30-line Python bridge (the image has python3) that listens on a port and
pumps a socket to the real server's stdio. The backend then opens a plain
asyncio TCP connection. Nothing is published to the host — the port is only
reachable from the isolated network the backend is already dual-homed onto.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from .protocol import McpError, McpSession
from .types import McpServerConfig, Transport

logger = logging.getLogger(__name__)

_FALSY = {"0", "false", "no", "off", ""}

BRIDGE_PORT = 9010

# The bridge runs INSIDE the sandbox container as PID 1. Passed as a single
# argv element to `python3 -c`, so no shell is involved and the MCP server's
# own argv needs no quoting.
_BRIDGE_SRC = r'''
import asyncio, os, sys

PORT = int(os.environ.get("HARVIS_MCP_BRIDGE_PORT", "9010"))
ARGV = sys.argv[1:]

async def handle(reader, writer):
    proc = await asyncio.create_subprocess_exec(
        *ARGV,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async def to_proc():
        try:
            while True:
                d = await reader.read(65536)
                if not d:
                    break
                proc.stdin.write(d)
                await proc.stdin.drain()
        except Exception:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
    async def to_sock():
        try:
            while True:
                d = await proc.stdout.read(65536)
                if not d:
                    break
                writer.write(d)
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
    async def drain_err():
        # Surface the server's stderr in `docker logs` — otherwise a server
        # that fails to start looks identical to one that hangs.
        try:
            while True:
                d = await proc.stderr.readline()
                if not d:
                    break
                sys.stderr.write(d.decode("utf-8", "replace"))
                sys.stderr.flush()
        except Exception:
            pass
    await asyncio.gather(to_proc(), to_sock(), drain_err())
    await proc.wait()

async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    async with server:
        await server.serve_forever()

asyncio.run(main())
'''


def runtime_enabled() -> bool:
    """Off by default. Running third-party MCP servers is code execution, and
    every other exec surface in this repo ships behind a flag."""
    return os.getenv("HARVIS_MCP_RUNTIME_ENABLED", "").strip().lower() not in _FALSY


def _sandbox_image() -> str:
    return os.getenv("HARVIS_MCP_SANDBOX_IMAGE", "harvis-repo-sandbox:local")


def _sandbox_network() -> str:
    return os.getenv("HARVIS_MCP_SANDBOX_NETWORK", "harvis_repo-sandbox")


def _idle_timeout_s() -> int:
    try:
        return max(60, int(os.getenv("HARVIS_MCP_IDLE_TIMEOUT_S", "900")))
    except ValueError:
        return 900


def _max_sessions() -> int:
    try:
        return max(1, int(os.getenv("HARVIS_MCP_MAX_SESSIONS", "8")))
    except ValueError:
        return 8


# npx/uvx are the two launchers the catalog's install cards use. Anything else
# is a config the user hand-wrote; allow a small explicit set rather than an
# arbitrary command, so a compromised catalog row can't name /bin/sh.
_ALLOWED_COMMANDS = {"npx", "uvx", "uv", "node", "python3", "python"}


@dataclass
class _Session:
    key: str
    config: McpServerConfig
    session: McpSession
    container_id: Optional[str]
    tools: list[dict] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class McpRuntime:
    """Holds live MCP sessions keyed by (user_id, server_name)."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._spawn_lock = asyncio.Lock()

    # -- public ------------------------------------------------------------

    async def list_tools(self, cfg: McpServerConfig) -> list[dict]:
        """Tools exposed by one server. Connects on first use."""
        sess = await self._acquire(cfg)
        return list(sess.tools)

    async def call_tool(
        self, cfg: McpServerConfig, tool_name: str, arguments: dict
    ) -> dict:
        sess = await self._acquire(cfg)
        async with sess.lock:
            sess.last_used = time.monotonic()
            return await sess.session.call_tool(tool_name, arguments)

    async def disconnect(self, user_id: int, server_name: str) -> bool:
        key = f"{user_id}:{server_name}"
        sess = self._sessions.pop(key, None)
        if sess is None:
            return False
        await self._teardown(sess)
        return True

    async def reap_idle(self) -> int:
        """Close sessions unused for longer than the idle timeout."""
        cutoff = time.monotonic() - _idle_timeout_s()
        stale = [k for k, s in self._sessions.items() if s.last_used < cutoff]
        for key in stale:
            sess = self._sessions.pop(key, None)
            if sess is not None:
                logger.info("mcp: reaping idle session %s", key)
                await self._teardown(sess)
        return len(stale)

    def live_keys(self) -> list[str]:
        return sorted(self._sessions)

    # -- internals ---------------------------------------------------------

    async def _acquire(self, cfg: McpServerConfig) -> _Session:
        if not runtime_enabled():
            raise McpError(
                "the MCP runtime is disabled on this deployment "
                "(set HARVIS_MCP_RUNTIME_ENABLED=1 to enable it)"
            )
        key = f"{cfg.user_id}:{cfg.server_name}"
        existing = self._sessions.get(key)
        if existing is not None:
            existing.last_used = time.monotonic()
            return existing

        async with self._spawn_lock:
            # Re-check: another caller may have connected while we waited.
            existing = self._sessions.get(key)
            if existing is not None:
                existing.last_used = time.monotonic()
                return existing

            await self.reap_idle()
            if len(self._sessions) >= _max_sessions():
                raise McpError(
                    f"too many live MCP servers ({len(self._sessions)}); "
                    "disconnect one before connecting another"
                )

            sess = await self._connect(cfg)
            self._sessions[key] = sess
            return sess

    async def _connect(self, cfg: McpServerConfig) -> _Session:
        if cfg.transport != Transport.STDIO:
            raise McpError(
                f"transport '{cfg.transport.value}' is not supported yet — "
                "only stdio servers can be run by this deployment"
            )
        return await self._connect_stdio(cfg)

    async def _connect_stdio(self, cfg: McpServerConfig) -> _Session:
        command = (cfg.command or "").strip()
        if not command:
            raise McpError(f"server '{cfg.server_name}' has no command configured")
        if command not in _ALLOWED_COMMANDS:
            raise McpError(
                f"command '{command}' is not an allowed MCP launcher "
                f"(allowed: {', '.join(sorted(_ALLOWED_COMMANDS))})"
            )
        argv = [command] + [str(a) for a in (cfg.args or [])]

        container_id, host = await asyncio.to_thread(self._spawn_container, cfg, argv)
        try:
            reader, writer = await self._dial(host, BRIDGE_PORT)
            session = McpSession(reader, writer, label=cfg.server_name)
            await session.initialize()
            tools = await session.list_tools()
        except Exception:
            await asyncio.to_thread(self._kill_container, container_id)
            raise

        logger.info(
            "mcp: connected %s (%s) — %d tools",
            cfg.server_name,
            (session.server_info or {}).get("name") or "unknown server",
            len(tools),
        )
        return _Session(
            key=f"{cfg.user_id}:{cfg.server_name}",
            config=cfg,
            session=session,
            container_id=container_id,
            tools=tools,
        )

    async def _dial(
        self, host: str, port: int, *, attempts: int = 40
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """The bridge needs a moment to bind. Retry rather than sleep-and-hope."""
        last: Optional[Exception] = None
        for _ in range(attempts):
            try:
                return await asyncio.open_connection(host, port)
            except (ConnectionError, OSError) as exc:
                last = exc
                await asyncio.sleep(0.25)
        raise McpError(f"MCP server did not start listening: {last}")

    def _spawn_container(self, cfg: McpServerConfig, argv: list[str]) -> tuple[str, str]:
        """Blocking. Returns (container_id, reachable_host)."""
        import docker  # imported lazily: the API path must import with no docker present

        client = docker.from_env()
        env = {str(k): str(v) for k, v in (cfg.env or {}).items()}
        env["HARVIS_MCP_BRIDGE_PORT"] = str(BRIDGE_PORT)
        # npx/uvx write caches; give them a writable HOME inside the container.
        env.setdefault("HOME", "/tmp")

        name = f"harvis-mcp-{cfg.user_id}-{_safe_name(cfg.server_name)}"
        try:
            old = client.containers.get(name)
            old.remove(force=True)
        except Exception:
            pass

        container = client.containers.run(
            _sandbox_image(),
            command=["python3", "-c", _BRIDGE_SRC] + argv,
            name=name,
            detach=True,
            environment=env,
            network=_sandbox_network(),
            # Same hardening as the repo sandbox: this is third-party code.
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=os.getenv("HARVIS_MCP_SANDBOX_MEM", "768m"),
            nano_cpus=int(float(os.getenv("HARVIS_MCP_SANDBOX_CPUS", "1.0")) * 1e9),
            pids_limit=256,
            # No host mounts, no published ports: reachable only from the
            # isolated network the backend is already attached to.
            labels={"harvis.mcp": "1", "harvis.mcp.user": str(cfg.user_id)},
        )
        container.reload()
        nets = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        ip = ""
        for net in nets.values():
            ip = (net or {}).get("IPAddress") or ""
            if ip:
                break
        # Prefer the container name (docker DNS on a user-defined network);
        # fall back to the address if DNS is unavailable.
        return container.id, (name if not ip else ip)

    def _kill_container(self, container_id: Optional[str]) -> None:
        if not container_id:
            return
        try:
            import docker

            docker.from_env().containers.get(container_id).remove(force=True)
        except Exception:
            logger.debug("mcp: container cleanup failed for %s", container_id)

    async def _teardown(self, sess: _Session) -> None:
        try:
            await sess.session.close()
        except Exception:
            pass
        await asyncio.to_thread(self._kill_container, sess.container_id)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or ""))[:48]


# Process-wide runtime. One per backend worker.
mcp_runtime = McpRuntime()
