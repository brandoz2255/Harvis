"""
Per-workspace ephemeral Docker terminal.

Each Harvis workspace can spin up its own isolated container, on the same
internal Docker network as OpenClaw + backend. The agent calls
`POST /api/tools/terminal/{workspace_id}/exec` with a shell command and
gets back stdout / stderr / exit_code.

Design choices for MVP:
- Lazy spawn on first `exec` (no upfront lifecycle hook required)
- Container name is deterministic: `harvis-ws-term-<workspace_id>`
- Container is `tail -f /dev/null` keepalive — exec runs commands via `docker exec`
- Default base image: `ubuntu:24.04` (configurable)
- Resource caps: 1 CPU / 512 MB by default (env-tunable)
- Teardown is explicit (call `teardown(workspace_id)`) — also runs on a periodic
  sweep that kills containers idle > HARVIS_TERMINAL_IDLE_TIMEOUT
- Feature-flagged via `HARVIS_TERMINAL_ENABLED` (default false)
"""

import asyncio
import json
import logging
import os
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import docker
from docker.errors import APIError, NotFound

logger = logging.getLogger(__name__)


_BASE_IMAGE = os.getenv("HARVIS_TERMINAL_IMAGE", "ubuntu:24.04")
_NETWORK = os.getenv("HARVIS_TERMINAL_NETWORK", "harvis_openclaw-internal")
_MEM_LIMIT = os.getenv("HARVIS_TERMINAL_MEM", "512m")
_CPU_QUOTA = float(os.getenv("HARVIS_TERMINAL_CPUS", "1.0"))
_DEFAULT_TIMEOUT_S = float(os.getenv("HARVIS_TERMINAL_DEFAULT_TIMEOUT_S", "30"))
_MAX_TIMEOUT_S = float(os.getenv("HARVIS_TERMINAL_MAX_TIMEOUT_S", "600"))
_IDLE_TIMEOUT_S = float(os.getenv("HARVIS_TERMINAL_IDLE_TIMEOUT_S", "86400"))  # 24h
_PERSISTENT = os.getenv("HARVIS_TERMINAL_PERSISTENT", "true").lower() in ("true", "1", "yes")
_OUTPUT_CAP_BYTES = int(os.getenv("HARVIS_TERMINAL_OUTPUT_CAP", "65536"))


def is_enabled() -> bool:
    """Default: ON. The env var is a kill-switch only.

    Set `HARVIS_TERMINAL_ENABLED=false` (or 0/no/off) to force-disable the
    feature even when prerequisites are healthy. With no override, readiness
    is decided by the runtime probe in `WorkspaceTerminalManager.probe()`.
    """
    raw = os.getenv("HARVIS_TERMINAL_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


@dataclass
class _ReadinessReport:
    """Structured result of the startup/runtime readiness probe."""
    ready: bool
    reason: str
    docker_ok: bool
    base_image_present: bool
    base_image: str
    network_present: bool
    network: str
    last_checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "docker_ok": self.docker_ok,
            "base_image_present": self.base_image_present,
            "base_image": self.base_image,
            "network_present": self.network_present,
            "network": self.network,
            "last_checked_at": self.last_checked_at,
        }


@dataclass
class _TerminalState:
    workspace_id: str
    container_name: str
    created_at: float
    last_used_at: float = field(default_factory=time.time)


class WorkspaceTerminalManager:
    """
    Owns the per-workspace terminal containers. One instance per backend process,
    accessed via `get_terminal_manager()`.
    """

    def __init__(self) -> None:
        try:
            self._client = docker.from_env()
        except Exception as exc:  # noqa: BLE001
            logger.error("WorkspaceTerminalManager: failed to init docker client: %s", exc)
            self._client = None
        self._terminals: dict[str, _TerminalState] = {}
        self._lock = asyncio.Lock()
        self._readiness: Optional[_ReadinessReport] = None
        self._readiness_ttl_s = 30.0  # re-probe at most this often

    # ── Readiness probe ────────────────────────────────────────────────────

    async def probe(self, *, force: bool = False) -> _ReadinessReport:
        """Check whether the terminal can actually launch containers right now.

        Verifies:
          1. Docker daemon is reachable (the docker.sock bind works)
          2. The configured network exists
          3. The base image is present locally (warns but does not fail when
             missing — the first `exec` call will pull it)

        Result is cached for `_readiness_ttl_s` seconds so the health endpoint
        can hit it on every poll without hammering the daemon. Pass `force=True`
        to bypass the cache.
        """
        if (
            not force
            and self._readiness
            and (time.time() - self._readiness.last_checked_at) < self._readiness_ttl_s
        ):
            return self._readiness

        docker_ok = False
        network_present = False
        base_image_present = False
        reasons: list[str] = []

        if self._client is None:
            reasons.append("docker client not initialized (is /var/run/docker.sock mounted?)")
        else:
            try:
                await asyncio.to_thread(self._client.ping)
                docker_ok = True
            except Exception as exc:  # noqa: BLE001
                reasons.append(f"docker ping failed: {exc}")

            if docker_ok:
                try:
                    await asyncio.to_thread(self._client.networks.get, _NETWORK)
                    network_present = True
                except NotFound:
                    reasons.append(
                        f"network {_NETWORK!r} not found — set HARVIS_TERMINAL_NETWORK "
                        "to an existing internal docker network"
                    )
                except Exception as exc:  # noqa: BLE001
                    reasons.append(f"network probe failed: {exc}")

                try:
                    await asyncio.to_thread(self._client.images.get, _BASE_IMAGE)
                    base_image_present = True
                except Exception:
                    # Missing locally is fine — first exec will pull. Note it.
                    reasons.append(
                        f"base image {_BASE_IMAGE!r} not present locally (will pull on first use)"
                    )

        # Ready means the daemon is up and the network exists. Missing image is
        # tolerated because container.run() will pull it on first use.
        ready = docker_ok and network_present
        if ready and not reasons:
            reason = "ok"
        elif ready:
            reason = "; ".join(reasons)
        else:
            reason = "; ".join(reasons) or "unknown failure"

        report = _ReadinessReport(
            ready=ready,
            reason=reason,
            docker_ok=docker_ok,
            base_image_present=base_image_present,
            base_image=_BASE_IMAGE,
            network_present=network_present,
            network=_NETWORK,
        )
        self._readiness = report
        return report

    def cached_readiness(self) -> Optional[_ReadinessReport]:
        return self._readiness

    # ── Container lifecycle ────────────────────────────────────────────────

    def _container_name(self, workspace_id: str) -> str:
        # Sanitize: docker names must match [a-zA-Z0-9_.-]
        safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in workspace_id)
        return f"harvis-ws-term-{safe[:48]}"

    def _volume_name(self, workspace_id: str) -> str:
        """Named volume mounted at /workspace inside the container.

        Lets the agent's files survive a container recreate (e.g., docker
        restart, OOM, manual `docker rm`). Persisted across reconnects so
        Discord sessions don't lose downloads / partial scripts when the
        backend redeploys. One volume per workspace/session id.
        """
        safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in workspace_id)
        return f"harvis-ws-vol-{safe[:48]}"

    async def _spawn(self, workspace_id: str) -> _TerminalState:
        """Create + start the container. Idempotent."""
        if self._client is None:
            raise RuntimeError("docker client unavailable")

        name = self._container_name(workspace_id)

        # If an existing container with this name is around, reuse it.
        try:
            existing = await asyncio.to_thread(self._client.containers.get, name)
            if existing.status != "running":
                await asyncio.to_thread(existing.start)
            state = _TerminalState(
                workspace_id=workspace_id,
                container_name=name,
                created_at=time.time(),
            )
            self._terminals[workspace_id] = state
            logger.info("[terminal:%s] reused existing container %s", workspace_id, name)
            return state
        except NotFound:
            pass

        # Fresh create.
        # Persistent design (HARVIS_TERMINAL_PERSISTENT=true, default ON):
        #   - auto_remove=False so stopped containers can be restarted with
        #     the same /workspace state intact.
        #   - Named docker volume mounted at /workspace so even a full
        #     container recreate (image bump, OOM, manual rm) preserves
        #     the agent's downloads / partial scripts / git clones.
        #   - One container + volume per workspace/session id — Discord
        #     sessions reusing the same session_key get the same container
        #     across messages, no spamming.
        vol_name = self._volume_name(workspace_id)
        if _PERSISTENT:
            volumes = {vol_name: {"bind": "/workspace", "mode": "rw"}}
            auto_remove = False
        else:
            volumes = {}
            auto_remove = True
        try:
            container = await asyncio.to_thread(
                self._client.containers.run,
                _BASE_IMAGE,
                command=["sh", "-c", "tail -f /dev/null"],
                name=name,
                detach=True,
                tty=False,
                stdin_open=True,
                network=_NETWORK,
                mem_limit=_MEM_LIMIT,
                nano_cpus=int(_CPU_QUOTA * 1_000_000_000),
                labels={
                    "harvis.role": "workspace-terminal",
                    "harvis.workspace_id": workspace_id,
                    "harvis.persistent": str(_PERSISTENT).lower(),
                    "harvis.volume": vol_name if _PERSISTENT else "",
                },
                auto_remove=auto_remove,
                restart_policy={"Name": "unless-stopped"} if _PERSISTENT else None,
                working_dir="/workspace",
                volumes=volumes,
            )
            # Best-effort: ensure /workspace exists writable
            try:
                await asyncio.to_thread(
                    container.exec_run,
                    ["sh", "-c", "mkdir -p /workspace && cd /workspace"],
                    demux=False,
                )
            except Exception:
                pass

            state = _TerminalState(
                workspace_id=workspace_id,
                container_name=name,
                created_at=time.time(),
            )
            self._terminals[workspace_id] = state
            logger.info(
                "[terminal:%s] spawned container %s (image=%s mem=%s cpus=%.1f "
                "persistent=%s vol=%s)",
                workspace_id, name, _BASE_IMAGE, _MEM_LIMIT, _CPU_QUOTA,
                _PERSISTENT, vol_name if _PERSISTENT else "-",
            )
            return state
        except APIError as exc:
            logger.error("[terminal:%s] container create failed: %s", workspace_id, exc)
            raise

    async def ensure(self, workspace_id: str) -> _TerminalState:
        """Spawn if missing, return state. Lazy."""
        async with self._lock:
            state = self._terminals.get(workspace_id)
            if state:
                # Verify the container is still alive (Docker may have killed it).
                try:
                    c = await asyncio.to_thread(self._client.containers.get, state.container_name)
                    if c.status == "running":
                        return state
                except NotFound:
                    pass
                # Stale → drop and respawn
                self._terminals.pop(workspace_id, None)
            return await self._spawn(workspace_id)

    async def teardown(self, workspace_id: str) -> bool:
        """Stop + remove the container. Returns True if something was removed."""
        async with self._lock:
            state = self._terminals.pop(workspace_id, None)
            name = state.container_name if state else self._container_name(workspace_id)
            if self._client is None:
                return False
            try:
                c = await asyncio.to_thread(self._client.containers.get, name)
            except NotFound:
                return False
            try:
                await asyncio.to_thread(c.stop, timeout=2)
            except Exception as exc:
                logger.warning("[terminal:%s] stop failed: %s", workspace_id, exc)
            # auto_remove handles deletion on stop, but try to ensure cleanup.
            try:
                await asyncio.to_thread(c.remove, force=True)
            except Exception:
                pass
            logger.info("[terminal:%s] torn down container %s", workspace_id, name)
            return True

    # ── Command execution ──────────────────────────────────────────────────

    async def exec(
        self,
        workspace_id: str,
        cmd: str,
        timeout_s: Optional[float] = None,
        workdir: str = "/workspace",
    ) -> dict:
        """Run a shell command in the workspace container.

        Returns: {stdout: str, stderr: str, exit_code: int, duration_ms: int,
                  truncated: bool, container: str}
        """
        if not cmd or not cmd.strip():
            raise ValueError("empty command")
        if self._client is None:
            raise RuntimeError("docker client unavailable")

        timeout = min(_MAX_TIMEOUT_S, max(1.0, timeout_s or _DEFAULT_TIMEOUT_S))
        state = await self.ensure(workspace_id)
        state.last_used_at = time.time()

        container = await asyncio.to_thread(self._client.containers.get, state.container_name)

        # Wrap in `timeout` so the docker exec actually returns even if the
        # command hangs forever. Coreutils `timeout` is in ubuntu by default.
        # Falls back to plain sh -c if `timeout` is missing on the base image.
        wrapped = f"timeout --kill-after=2 {int(timeout)}s sh -c {shlex.quote(cmd)}"

        t0 = time.time()
        try:
            result = await asyncio.to_thread(
                container.exec_run,
                ["sh", "-c", wrapped],
                workdir=workdir,
                demux=True,
                tty=False,
            )
        except APIError as exc:
            logger.warning("[terminal:%s] exec_run APIError: %s", workspace_id, exc)
            return {
                "stdout": "",
                "stderr": f"exec_run failed: {exc}",
                "exit_code": -1,
                "duration_ms": int((time.time() - t0) * 1000),
                "truncated": False,
                "container": state.container_name,
            }
        duration_ms = int((time.time() - t0) * 1000)

        exit_code = result.exit_code if result.exit_code is not None else -1
        stdout_b, stderr_b = result.output if isinstance(result.output, tuple) else (result.output, b"")
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")

        truncated = False
        if len(stdout) > _OUTPUT_CAP_BYTES:
            stdout = stdout[:_OUTPUT_CAP_BYTES] + f"\n…[stdout truncated at {_OUTPUT_CAP_BYTES} bytes]"
            truncated = True
        if len(stderr) > _OUTPUT_CAP_BYTES:
            stderr = stderr[:_OUTPUT_CAP_BYTES] + f"\n…[stderr truncated at {_OUTPUT_CAP_BYTES} bytes]"
            truncated = True

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "truncated": truncated,
            "container": state.container_name,
        }

    # ── Periodic janitor ───────────────────────────────────────────────────

    async def sweep_idle(self) -> int:
        """Reclaim idle terminals.

        In persistent mode (default): STOP idle containers but leave them
        + the named volume on disk so a returning user gets their /workspace
        intact on next exec. Frees memory + CPU without losing state.

        In ephemeral mode (HARVIS_TERMINAL_PERSISTENT=false): full teardown
        — stop + remove container, leave the volume in either mode.
        """
        now = time.time()
        stale = [
            wsid for wsid, state in list(self._terminals.items())
            if now - state.last_used_at > _IDLE_TIMEOUT_S
        ]
        for wsid in stale:
            try:
                if _PERSISTENT:
                    # Stop, keep the named volume + the container record.
                    # ensure() will restart it on next exec, /workspace intact.
                    state = self._terminals.pop(wsid, None)
                    if state and self._client is not None:
                        try:
                            c = await asyncio.to_thread(
                                self._client.containers.get, state.container_name,
                            )
                            await asyncio.to_thread(c.stop, timeout=5)
                            logger.info(
                                "[terminal:%s] persistent-sweep stopped %s "
                                "(volume + container preserved)",
                                wsid, state.container_name,
                            )
                        except NotFound:
                            pass
                        except Exception as exc:
                            logger.warning(
                                "[terminal:%s] persistent-sweep stop failed: %s",
                                wsid, exc,
                            )
                else:
                    await self.teardown(wsid)
            except Exception as exc:
                logger.warning("sweep teardown failed for %s: %s", wsid, exc)
        return len(stale)


_manager_singleton: Optional[WorkspaceTerminalManager] = None


def get_terminal_manager() -> WorkspaceTerminalManager:
    global _manager_singleton
    if _manager_singleton is None:
        _manager_singleton = WorkspaceTerminalManager()
    return _manager_singleton


async def terminal_status(*, force_probe: bool = False) -> dict[str, Any]:
    """Combined readiness view for the health endpoint and the exec gate.

    Shape:
      {
        "enabled": bool,            # kill-switch (HARVIS_TERMINAL_ENABLED)
        "ready": bool,              # daemon + network reachable
        "available": bool,          # enabled AND ready — what callers should check
        "reason": str,              # one-line explanation
        "probe": {<_ReadinessReport>},
      }
    """
    enabled = is_enabled()
    if not enabled:
        return {
            "enabled": False,
            "ready": False,
            "available": False,
            "reason": "killed by HARVIS_TERMINAL_ENABLED=false",
            "probe": None,
        }
    mgr = get_terminal_manager()
    report = await mgr.probe(force=force_probe)
    return {
        "enabled": True,
        "ready": report.ready,
        "available": report.ready,
        "reason": report.reason,
        "probe": report.to_dict(),
    }


# ─── Workspace-event emission ─────────────────────────────────────────────────
# When the terminal is invoked from inside a Harvis workspace task, we want the
# progress banner (Discord, /api/workspaces/<id>/events SSE, chat bridge) to
# show "💻 Harvis terminal: <cmd>" the same way it shows browser/exec calls.
# OpenClawClient owns the in-memory `seq` counter for live events, but other
# subscribers replay from the DB — so we pick the next seq via `MAX(seq)+1`,
# write directly to `workspace_events`, and (best-effort) push the same payload
# onto the live broadcaster if one is registered for this workspace.

_TERMINAL_TOOL_NAME = "harvis-terminal"


async def _next_event_seq(pool, workspace_id: str) -> int:
    """Pick the next monotonic seq for this workspace's event stream."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(MAX(seq) + 1, 0) AS next_seq "
            "FROM workspace_events WHERE workspace_id = $1",
            workspace_id,
        )
    return int(row["next_seq"]) if row else 0


async def _broadcast_live(workspace_id: str, event_type: str, payload: dict, seq: int) -> None:
    """Push the event onto the running workspace's live broadcaster, if any."""
    try:
        from workspace.workspace_router import _workspace_broadcasters  # noqa: WPS433
        from workspace.openclaw_client import OpenClawEvent  # noqa: WPS433
    except Exception:
        return
    broadcaster = _workspace_broadcasters.get(workspace_id)
    if broadcaster is None:
        return
    try:
        evt = OpenClawEvent(event_type, dict(payload))
        await broadcaster.put((seq, evt))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[terminal:%s] live broadcast skipped: %s", workspace_id, exc)


async def emit_terminal_event(
    pool,
    workspace_id: str,
    *,
    event_type: str,
    payload: dict,
) -> None:
    """Persist a terminal-related workspace event and fan it out live.

    Banner pipeline:
      tool_call  →  ⚙️  Harvis terminal: `<cmd preview>`
      tool_result → ✅  Harvis terminal complete  /  ❌ Harvis terminal failed
    """
    if pool is None:
        return
    try:
        seq = await _next_event_seq(pool, workspace_id)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_events (workspace_id, seq, event_type, payload, ts)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                workspace_id, seq, event_type, json.dumps(payload),
            )
        await _broadcast_live(workspace_id, event_type, payload, seq)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[terminal:%s] failed to emit %s event: %s",
            workspace_id, event_type, exc,
        )


def build_tool_call_payload(cmd: str) -> dict:
    """Shape a `tool_call` payload that the Discord progress formatter renders."""
    preview = (cmd or "").strip().splitlines()[0] if cmd else ""
    return {
        "tool": _TERMINAL_TOOL_NAME,
        "args": {"command": cmd, "preview": preview[:120]},
    }


def build_tool_result_payload(cmd: str, result: dict[str, Any]) -> dict:
    """Shape a `tool_result` payload from a terminal exec result dict."""
    exit_code = int(result.get("exit_code", -1) or 0)
    success = exit_code == 0
    stdout = (result.get("stdout") or "")
    stderr = (result.get("stderr") or "")
    return {
        "tool": _TERMINAL_TOOL_NAME,
        "success": success,
        "summary": (
            f"exit={exit_code} dur={result.get('duration_ms', 0)}ms "
            f"out={len(stdout)}B err={len(stderr)}B"
        ),
        "args": {"command": cmd},
        "output": {
            "exit_code": exit_code,
            "duration_ms": result.get("duration_ms", 0),
            "truncated": bool(result.get("truncated", False)),
            "stdout_preview": stdout[:400],
            "stderr_preview": stderr[:400],
        },
    }
