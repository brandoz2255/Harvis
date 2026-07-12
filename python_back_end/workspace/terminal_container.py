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
import mimetypes
import os
import shlex
import time
import uuid
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
# Background jobs (Phase E1): hard ceiling on how long a detached job may run
# before the tail loop reaps it, and how long finished job records stay
# queryable in the in-memory registry.
_JOB_MAX_LIFETIME_S = float(os.getenv("HARVIS_JOB_MAX_LIFETIME_S", "3600"))
_JOB_POLL_INTERVAL_S = float(os.getenv("HARVIS_JOB_POLL_INTERVAL_S", "1.0"))
_JOB_RETENTION_S = float(os.getenv("HARVIS_JOB_RETENTION_S", "3600"))
# Cap on-disk BASE.out growth (container layer) — chatty jobs past this
# cumulative output size are reaped early by the tail loop.
_JOB_MAX_OUTPUT_BYTES = int(os.getenv("HARVIS_JOB_MAX_OUTPUT_BYTES", "10485760"))  # 10 MB
# Phase E2 — process artifacts: when a job finishes, files it wrote under its
# workdir are captured as workspace_artifacts. Caps: at most this many files,
# each at most _JOB_ARTIFACT_MAX_BYTES (default mirrors the existing 512 KiB
# artifact snapshot cap in workspace_router/isolation); bigger files get a
# placeholder row so the run record is still honest about what was produced.
_JOB_MAX_ARTIFACTS = int(os.getenv("HARVIS_JOB_MAX_ARTIFACTS", "50"))
_JOB_ARTIFACT_MAX_BYTES = int(os.getenv("HARVIS_JOB_ARTIFACT_MAX_BYTES", str(512 * 1024)))


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


@dataclass
class _JobState:
    """One detached background job (Phase E1).

    Lifecycle: running → done (exit 0) | exited (exit != 0) | killed (user
    DELETE) | reaped (hit _JOB_MAX_LIFETIME_S) | error (tail loop crashed).
    """
    job_id: str
    workspace_id: str
    container_name: str
    base: str  # /tmp/harvis-job-<jid> — .pid / .out / .exit live beside it
    command: str
    workdir: str = "/workspace"  # E2: artifact capture scans under this
    user_id: Optional[int] = None  # E2: persisted for post-restart ownership
    status: str = "running"
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    offset: int = 0  # bytes of BASE.out already streamed
    exit_code: Optional[int] = None
    tail_task: Optional[Any] = field(default=None, repr=False)


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
        # The in-memory job registry is the source of truth for the CURRENT
        # process; E2 mirrors every lifecycle change into the workspace_jobs
        # table (best-effort) and reattach_running_jobs() rebuilds this dict
        # from it after a backend restart — resuming tails of live wrappers
        # and finalizing ones that finished while the backend was down.
        self._jobs: dict[str, _JobState] = {}
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

    # ── Background jobs (Phase E1 — non-blocking exec) ─────────────────────

    async def exec_bg(
        self,
        workspace_id: str,
        cmd: str,
        workdir: str = "/workspace",
        pool=None,
        user_id: Optional[int] = None,
    ) -> str:
        """Start `cmd` DETACHED in the workspace container; return a job_id
        immediately.

        Mechanism: a pid/out/exit-file wrapper at BASE=/tmp/harvis-job-<jid>.
        The wrapper (launched via a detached docker exec, so this call never
        waits on the command) writes its own pid to BASE.pid, runs the user
        command with stdout+stderr → BASE.out, then writes the exit status to
        BASE.exit. A local asyncio task tails BASE.out incrementally and emits
        terminal_output events (each chunk capped at _OUTPUT_CAP_BYTES); when
        BASE.exit appears it emits ONE final tool_result and stops.

        The wrapper is started under `setsid` (present in ubuntu base) so its
        pid is the process-GROUP leader — that pgid is what kill_job signals.
        """
        if not cmd or not cmd.strip():
            raise ValueError("empty command")
        if self._client is None:
            raise RuntimeError("docker client unavailable")

        state = await self.ensure(workspace_id)
        state.last_used_at = time.time()
        container = await asyncio.to_thread(
            self._client.containers.get, state.container_name
        )

        jid = uuid.uuid4().hex[:12]
        base = f"/tmp/harvis-job-{jid}"
        wrapper = (
            f"echo $$ > {base}.pid; "
            f": > {base}.out; "
            f"sh -c {shlex.quote(cmd)} > {base}.out 2>&1; "
            f"echo $? > {base}.exit"
        )
        # setsid → wrapper becomes session + process-group leader, so
        # `kill -TERM -<pid>` reaches every descendant. Fallback keeps the
        # job runnable on images without util-linux (pkill path in kill_job).
        launcher = (
            "if command -v setsid >/dev/null 2>&1; "
            f"then exec setsid sh -c {shlex.quote(wrapper)}; "
            f"else exec sh -c {shlex.quote(wrapper)}; fi"
        )
        try:
            await asyncio.to_thread(
                container.exec_run,
                ["sh", "-c", launcher],
                workdir=workdir,
                detach=True,
            )
        except APIError as exc:
            logger.error("[job:%s] detached exec launch failed: %s", jid, exc)
            raise RuntimeError(f"job launch failed: {exc}")

        job = _JobState(
            job_id=jid,
            workspace_id=workspace_id,
            container_name=state.container_name,
            base=base,
            command=cmd,
            workdir=workdir,
            user_id=user_id,
        )
        self._jobs[jid] = job
        # E2: durable record — job_status + reattach_running_jobs survive a
        # backend restart via this row. Best-effort: a DB hiccup never blocks
        # the (already launched) job.
        await self._db_job_insert(pool, job)
        job.tail_task = asyncio.create_task(self._tail_job(job, container, pool))
        logger.info(
            "[job:%s] started background job in %s (ws=%s)",
            jid, state.container_name, workspace_id,
        )
        return jid

    async def _tail_job(self, job: _JobState, container, pool) -> None:
        """Poll BASE.out for new bytes + BASE.exit for completion.

        Doubles as the max-lifetime guard (mirrors sweep_idle): a job older
        than _JOB_MAX_LIFETIME_S is force-killed and marked 'reaped'. Also
        bumps the terminal's last_used_at so sweep_idle never stops a
        container mid-job.
        """
        target = {"kind": "sandbox", "id": job.container_name}
        # Set when the task is CANCELLED (backend shutdown): the job is still running in
        # the container, so we must NOT finalize/clean it up — reattach adopts it on boot.
        _shutdown_cancel = False
        try:
            while True:
                await asyncio.sleep(_JOB_POLL_INTERVAL_S)

                st = self._terminals.get(job.workspace_id)
                if st:
                    st.last_used_at = time.time()

                if job.status != "running":  # kill_job flipped it
                    break

                # 1. Incremental chunk: only bytes past the stored offset,
                #    capped per chunk at _OUTPUT_CAP_BYTES.
                chunk_b = b""
                try:
                    res = await asyncio.to_thread(
                        container.exec_run,
                        ["sh", "-c",
                         f"tail -c +{job.offset + 1} {job.base}.out 2>/dev/null"
                         f" | head -c {_OUTPUT_CAP_BYTES}"],
                        demux=False,
                    )
                    chunk_b = res.output or b""
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[job:%s] tail read failed: %s", job.job_id, exc)
                if chunk_b:
                    job.offset += len(chunk_b)
                    await emit_terminal_event(
                        pool, job.workspace_id,
                        event_type="terminal_output",
                        payload={
                            "tool": _TERMINAL_TOOL_NAME,
                            "stream": "stdout",
                            "content": chunk_b.decode("utf-8", errors="replace"),
                            "target": target,
                            "job_id": job.job_id,
                        },
                    )
                    # On-disk cap: BASE.out grows in the container layer for
                    # the job's whole life — reap chatty jobs early.
                    if job.offset > _JOB_MAX_OUTPUT_BYTES:
                        logger.warning(
                            "[job:%s] output exceeded "
                            "HARVIS_JOB_MAX_OUTPUT_BYTES=%s — reaping",
                            job.job_id, _JOB_MAX_OUTPUT_BYTES,
                        )
                        await emit_terminal_event(
                            pool, job.workspace_id,
                            event_type="terminal_output",
                            payload={
                                "tool": _TERMINAL_TOOL_NAME,
                                "stream": "stdout",
                                "content": (
                                    f"\n…[job {job.job_id} output exceeded "
                                    f"{_JOB_MAX_OUTPUT_BYTES} bytes — reaped]\n"
                                ),
                                "target": target,
                                "job_id": job.job_id,
                            },
                        )
                        await self._signal_job(job, container)
                        job.status = "reaped"
                        break
                    if len(chunk_b) >= _OUTPUT_CAP_BYTES:
                        continue  # more buffered — drain before exit check

                # 2. Done? BASE.exit only exists once the wrapper finished.
                res = await asyncio.to_thread(
                    container.exec_run,
                    ["sh", "-c", f"cat {job.base}.exit 2>/dev/null"],
                    demux=False,
                )
                raw = (res.output or b"").decode("utf-8", errors="replace").strip()
                if raw:
                    # Drain before recording exit: bytes written between the
                    # chunk read above and this exit check would otherwise be
                    # dropped — often the last (most important) lines.
                    while True:
                        try:
                            res = await asyncio.to_thread(
                                container.exec_run,
                                ["sh", "-c",
                                 f"tail -c +{job.offset + 1} {job.base}.out 2>/dev/null"
                                 f" | head -c {_OUTPUT_CAP_BYTES}"],
                                demux=False,
                            )
                            tail_b = res.output or b""
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "[job:%s] drain read failed: %s", job.job_id, exc,
                            )
                            break
                        if not tail_b:
                            break
                        job.offset += len(tail_b)
                        await emit_terminal_event(
                            pool, job.workspace_id,
                            event_type="terminal_output",
                            payload={
                                "tool": _TERMINAL_TOOL_NAME,
                                "stream": "stdout",
                                "content": tail_b.decode("utf-8", errors="replace"),
                                "target": target,
                                "job_id": job.job_id,
                            },
                        )
                        if job.offset > _JOB_MAX_OUTPUT_BYTES:
                            await emit_terminal_event(
                                pool, job.workspace_id,
                                event_type="terminal_output",
                                payload={
                                    "tool": _TERMINAL_TOOL_NAME,
                                    "stream": "stdout",
                                    "content": (
                                        f"\n…[job {job.job_id} output exceeded "
                                        f"{_JOB_MAX_OUTPUT_BYTES} bytes — "
                                        f"remainder dropped]\n"
                                    ),
                                    "target": target,
                                    "job_id": job.job_id,
                                },
                            )
                            break
                    try:
                        job.exit_code = int(raw.split()[0])
                    except ValueError:
                        job.exit_code = -1
                    job.status = "done" if job.exit_code == 0 else "exited"
                    break

                # 3. Max-lifetime guard — reap runaways.
                if time.time() - job.started > _JOB_MAX_LIFETIME_S:
                    logger.warning(
                        "[job:%s] exceeded HARVIS_JOB_MAX_LIFETIME_S=%ss — reaping",
                        job.job_id, _JOB_MAX_LIFETIME_S,
                    )
                    await self._signal_job(job, container)
                    job.status = "reaped"
                    break
        except NotFound:
            logger.warning("[job:%s] container vanished mid-job", job.job_id)
            job.status = "error"
        except asyncio.CancelledError:
            # Backend shutdown / task cancel — the job is STILL RUNNING in the sandbox
            # container. Leave its pid/out/exit files AND the 'running' DB row intact so
            # reattach_running_jobs adopts it on the next boot. Skip ALL cleanup below.
            _shutdown_cancel = True
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[job:%s] tail loop crashed: %s", job.job_id, exc)
            job.status = "error"
        finally:
            # On shutdown-cancellation the job is still alive in the container — do NONE
            # of the finalize/janitor below, or reattach can't adopt it on the next boot.
            if not _shutdown_cancel:
                job.finished = time.time()
                code = job.exit_code if job.exit_code is not None else -1
                duration_ms = int((job.finished - job.started) * 1000)
                # E2: persist the terminal state (done/exited/killed/reaped/error)
                # so post-restart job_status lookups keep answering. Best-effort.
                try:
                    await self._db_job_finish(pool, job)
                except Exception:  # noqa: BLE001
                    pass
                # E2: capture files the job wrote under its workdir as artifacts
                # BEFORE the final tool_result (complete trace) and BEFORE the
                # janitor below (BASE.pid is the find -newer marker). Skipped when
                # the container vanished (status 'error'). Never crashes the job.
                if job.status != "error":
                    try:
                        await self._capture_job_artifacts(job, container, pool)
                    except Exception as _cap_exc:  # noqa: BLE001
                        logger.warning(
                            "[job:%s] artifact capture failed: %s", job.job_id, _cap_exc,
                        )
                try:
                    await emit_terminal_event(
                        pool, job.workspace_id,
                        event_type="tool_result",
                        payload={
                            "tool": _TERMINAL_TOOL_NAME,
                            "success": job.status == "done" and code == 0,
                            "summary": (
                                f"job {job.job_id} {job.status} "
                                f"exit={code} dur={duration_ms}ms"
                            ),
                            "args": {"command": job.command},
                            "output": {
                                "exit_code": code,
                                "duration_ms": duration_ms,
                                "status": job.status,
                            },
                            "job_id": job.job_id,
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
                # Janitor: BASE.{pid,out,exit} are dead weight in the container
                # layer once the final tool_result is recorded.
                try:
                    await asyncio.to_thread(
                        container.exec_run,
                        ["sh", "-c",
                         f"rm -f {job.base}.pid {job.base}.out {job.base}.exit"],
                        demux=False,
                    )
                except Exception:  # noqa: BLE001
                    pass

    async def _signal_job(self, job: _JobState, container) -> bool:
        """Terminate the wrapper AND its children via the pidfile.

        Docker's exec API has no kill endpoint — the pidfile IS the kill
        mechanism. The script waits briefly for the pidfile (a DELETE can land
        in the sub-second window before the wrapper writes it), sends SIGTERM
        to the negative pgid (wrapper is a setsid group leader) with
        pkill -P / plain kill as fallback, escalates to SIGKILL after a short
        grace, then VERIFIES death with `kill -0` and echoes a marker.
        Returns True only when death was confirmed.
        """
        script = (
            f'i=0; while [ ! -f {job.base}.pid ] && [ "$i" -lt 20 ]; do '
            f'sleep 0.1; i=$((i + 1)); done; '
            f'if [ ! -f {job.base}.pid ]; then echo HARVIS_NO_PIDFILE; exit 0; fi; '
            f'p=$(cat {job.base}.pid); '
            f'kill -TERM -"$p" 2>/dev/null; '
            f'pkill -TERM -P "$p" 2>/dev/null; '
            f'kill -TERM "$p" 2>/dev/null; '
            f'sleep 1; '
            f'kill -KILL -"$p" 2>/dev/null; '
            f'pkill -KILL -P "$p" 2>/dev/null; '
            f'kill -KILL "$p" 2>/dev/null; '
            f'sleep 0.2; '
            f'if kill -0 -"$p" 2>/dev/null || kill -0 "$p" 2>/dev/null; '
            f'then echo HARVIS_STILL_ALIVE; else echo HARVIS_KILLED; fi'
        )
        res = await asyncio.to_thread(
            container.exec_run, ["sh", "-c", script], demux=False,
        )
        out = (res.output or b"").decode("utf-8", errors="replace")
        return "HARVIS_KILLED" in out

    async def kill_job(self, job_id: str) -> bool:
        """Kill a running background job.

        Returns True only when the process group's death was CONFIRMED. If
        the job already finished (BASE.exit present) this returns False and
        leaves the tail loop to record the real exit code; on an unconfirmed
        kill it leaves status='running' so the tail loop + lifetime reaper
        stay armed.
        """
        job = self._jobs.get(job_id)
        if job is None or job.status != "running":
            return False
        if self._client is None:
            raise RuntimeError("docker client unavailable")
        try:
            container = await asyncio.to_thread(
                self._client.containers.get, job.container_name
            )
        except NotFound:
            # container gone → process is dead anyway
            job.status = "killed"  # tail loop sees this, emits final tool_result
            logger.info("[job:%s] container gone — marking killed", job_id)
            return True

        # Already finished? Don't stomp the real exit code — the tail loop
        # records it on its next poll.
        try:
            res = await asyncio.to_thread(
                container.exec_run,
                ["sh", "-c", f"test -f {job.base}.exit && echo HARVIS_EXITED"],
                demux=False,
            )
            if b"HARVIS_EXITED" in (res.output or b""):
                return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("[job:%s] exit-file check failed: %s", job_id, exc)

        confirmed = False
        try:
            confirmed = await self._signal_job(job, container)
        except NotFound:
            confirmed = True  # container gone mid-kill → process is dead
        except Exception as exc:  # noqa: BLE001
            logger.warning("[job:%s] kill signal failed: %s", job_id, exc)
        if not confirmed:
            # No verified death → keep status='running' so the tail loop and
            # the lifetime reaper keep watching the (possibly live) job.
            logger.warning(
                "[job:%s] kill not confirmed — leaving job running", job_id,
            )
            return False
        job.status = "killed"  # tail loop sees this, emits final tool_result
        logger.info("[job:%s] killed via pidfile signal (confirmed)", job_id)
        return True

    def get_job(self, job_id: str) -> Optional[_JobState]:
        return self._jobs.get(job_id)

    async def job_status(self, job_id: str, pool=None) -> Optional[dict]:
        job = self._jobs.get(job_id)
        if job is not None:
            out: dict[str, Any] = {
                "job_id": job.job_id,
                "status": job.status,
                "started": job.started,
                "workspace_id": job.workspace_id,
            }
            if job.exit_code is not None:
                out["exit_code"] = job.exit_code
            if job.finished is not None:
                out["finished"] = job.finished
            return out
        # E2 fallback: the in-memory registry died with the last backend
        # process (or the record was retention-pruned) — answer from the
        # persisted workspace_jobs row so GET-after-restart still works.
        if pool is None:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, workspace_id, status, exit_code,
                           EXTRACT(EPOCH FROM started_at)  AS started,
                           EXTRACT(EPOCH FROM finished_at) AS finished
                    FROM workspace_jobs WHERE id = $1
                    """,
                    job_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[job:%s] status DB fallback failed: %s", job_id, exc)
            return None
        if row is None:
            return None
        out = {
            "job_id": row["id"],
            "status": row["status"] or "unknown",
            "started": float(row["started"]) if row["started"] is not None else None,
            "workspace_id": row["workspace_id"],
        }
        if row["exit_code"] is not None:
            out["exit_code"] = int(row["exit_code"])
        if row["finished"] is not None:
            out["finished"] = float(row["finished"])
        return out

    # ── Job persistence (Phase E2) ─────────────────────────────────────────
    # All DB writes here are BEST-EFFORT: a database hiccup must never crash
    # a launched job or its tail loop — the in-memory registry stays the
    # source of truth for the current process; the table is the restart net.

    async def _db_job_insert(self, pool, job: _JobState) -> None:
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO workspace_jobs
                        (id, workspace_id, user_id, command, workdir, status,
                         base_path, container_name, started_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, to_timestamp($9))
                    ON CONFLICT (id) DO NOTHING
                    """,
                    job.job_id, job.workspace_id, job.user_id, job.command,
                    job.workdir, job.status, job.base, job.container_name,
                    job.started,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[job:%s] DB insert failed (job unaffected): %s", job.job_id, exc,
            )

    async def _db_job_finish(self, pool, job: _JobState) -> None:
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE workspace_jobs SET status = $2, exit_code = $3, "
                    "finished_at = to_timestamp($4) WHERE id = $1",
                    job.job_id, job.status, job.exit_code,
                    job.finished or time.time(),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[job:%s] DB finish-update failed (job unaffected): %s",
                job.job_id, exc,
            )

    async def _db_job_mark_lost(self, pool, job_id: str) -> None:
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE workspace_jobs SET status = 'lost', finished_at = NOW() "
                    "WHERE id = $1 AND status = 'running'",
                    job_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[job:%s] DB lost-update failed: %s", job_id, exc)

    # ── Process artifacts (Phase E2) ─────────────────────────────────────────

    async def _capture_job_artifacts(self, job: _JobState, container, pool) -> None:
        """Record files the finished job WROTE under its workdir as artifacts.

        BASE.pid (written by the wrapper at launch, removed only by the tail
        loop's janitor AFTER this runs) is the `find -newer` marker, so only
        files touched during the job's lifetime are captured. Secret-named
        files are never captured (fail closed: if the filter can't be
        imported, nothing is). Caps: _JOB_MAX_ARTIFACTS files, each up to
        _JOB_ARTIFACT_MAX_BYTES (larger files get an honest placeholder row).
        UTF-8-decodable content → workspace_artifacts.content; binary
        (STL/3MF/G-code/PNG…) → content_bytes. Each saved file emits the
        Phase-B typed 'artifact' trace event on the job's workspace stream —
        safe on emit_terminal_event's DB seq because sandbox-job workspaces
        have no live run-loop seq counter to collide with.
        """
        if pool is None:
            return
        try:
            from .workspace_router import _db_save_artifact  # noqa: WPS433
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[job:%s] artifact helper unavailable — skipping capture: %s",
                job.job_id, exc,
            )
            return
        try:
            from .orchestration.isolation import _is_secret_artifact  # noqa: WPS433
        except Exception as exc:  # noqa: BLE001
            # No secret filter → capture nothing (never risk exposing keys).
            logger.warning(
                "[job:%s] secret filter unavailable — skipping capture: %s",
                job.job_id, exc,
            )
            return

        wd = (job.workdir or "/workspace").rstrip("/") or "/"
        marker = f"{job.base}.pid"
        list_cmd = (
            f"test -f {marker} && find {shlex.quote(wd)} -xdev -type f "
            f"-newer {marker} "
            "-not -path '*/.git/*' -not -path '*/node_modules/*' "
            "-not -path '*/__pycache__/*' -not -path '*/.venv/*' "
            f"2>/dev/null | head -n {_JOB_MAX_ARTIFACTS * 4}"
        )
        res = await asyncio.to_thread(
            container.exec_run, ["sh", "-c", list_cmd], demux=False,
        )
        listing = (res.output or b"").decode("utf-8", errors="replace")
        paths = [p for p in (ln.strip() for ln in listing.splitlines()) if p]
        if not paths:
            return

        captured = 0
        for fp in paths:
            if captured >= _JOB_MAX_ARTIFACTS:
                logger.info(
                    "[job:%s] artifact cap HARVIS_JOB_MAX_ARTIFACTS=%s reached",
                    job.job_id, _JOB_MAX_ARTIFACTS,
                )
                break
            rel = fp[len(wd):].lstrip("/") if fp.startswith(wd) else fp.lstrip("/")
            name = rel.rsplit("/", 1)[-1]
            if not rel or name.startswith("harvis-job-"):
                continue  # never capture our own pid/out/exit plumbing
            if _is_secret_artifact(rel):
                continue  # never expose .env / keys / credentials

            # One exec per file: first line = byte size, rest = base64 body
            # (only when within the per-file cap). base64 keeps binary intact
            # through the exec text channel.
            read_cmd = (
                f'f={shlex.quote(fp)}; s=$(wc -c < "$f" 2>/dev/null || echo -1); '
                f'echo "$s"; if [ "$s" -ge 0 ] && [ "$s" -le {_JOB_ARTIFACT_MAX_BYTES} ]; '
                'then base64 "$f" 2>/dev/null; fi'
            )
            try:
                res = await asyncio.to_thread(
                    container.exec_run, ["sh", "-c", read_cmd], demux=False,
                )
                out = (res.output or b"").decode("ascii", errors="replace")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[job:%s] artifact read failed for %r: %s",
                    job.job_id, rel, exc,
                )
                continue
            first, _, b64_body = out.partition("\n")
            try:
                size = int(first.strip())
            except ValueError:
                continue
            if size < 0:
                continue

            content: Optional[str] = None
            content_bytes: Optional[bytes] = None
            if size > _JOB_ARTIFACT_MAX_BYTES:
                content = f"<{size} bytes — not snapshotted>"
            else:
                import base64 as _b64  # noqa: WPS433
                try:
                    raw = _b64.b64decode("".join(b64_body.split()), validate=False)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    content = raw.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    content_bytes = raw  # binary → BYTEA column

            try:
                aid = await _db_save_artifact(
                    pool, job.workspace_id, "file",
                    path=rel, content=content, content_bytes=content_bytes,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[job:%s] artifact save failed for %r: %s",
                    job.job_id, rel, exc,
                )
                continue
            if not aid:
                continue
            captured += 1
            mime = mimetypes.guess_type(rel)[0] or (
                "application/octet-stream" if content_bytes is not None
                else "text/plain"
            )
            await emit_terminal_event(
                pool, job.workspace_id,
                event_type="artifact",
                payload={
                    "run_id": job.workspace_id,
                    "artifact_id": aid,
                    "path": rel,
                    "mime_type": mime,
                    "size_bytes": size,
                    "label": name or "file",
                    "job_id": job.job_id,
                },
            )
        if captured:
            logger.info(
                "[job:%s] captured %d artifact(s) from %s",
                job.job_id, captured, wd,
            )

    # ── Restart reconnect (Phase E2) ─────────────────────────────────────────

    async def reattach_running_jobs(self, pool) -> int:
        """Reconnect to jobs that were 'running' when the backend last died.

        The detached wrapper + its /tmp/harvis-job-<jid>.{pid,out,exit} files
        survive inside the sandbox container across a backend restart; only
        the in-memory registry is gone. For each workspace_jobs row still
        marked running:

          • container + BASE.exit present → the job finished while we were
            down: finalize now (exit code, DB row, artifact capture, final
            tool_result, janitor) WITHOUT re-streaming old output.
          • container + BASE.out present → still live: re-register an
            in-memory _JobState (offset 0, so output re-streams from the top)
            and resume the tail loop.
          • container or job files gone → mark the row 'lost'.

        Returns how many jobs were re-registered or finalized. Best-effort:
        called once from the main.py startup task; never raises upward.
        """
        if pool is None or self._client is None:
            return 0
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, workspace_id, user_id, command, workdir,
                           base_path, container_name,
                           EXTRACT(EPOCH FROM started_at) AS started
                    FROM workspace_jobs WHERE status = 'running'
                    """
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("job reattach: workspace_jobs query failed: %s", exc)
            return 0

        count = 0
        for row in rows:
            jid = row["id"]
            if jid in self._jobs:
                continue  # already tracked in this process
            base = row["base_path"] or f"/tmp/harvis-job-{jid}"
            try:
                container = await asyncio.to_thread(
                    self._client.containers.get, row["container_name"] or ""
                )
                # Refresh the cached status: a container fetched right after a backend
                # restart can carry a STALE status, and start() on an already-running
                # container raises 409 — which must NOT get a live job marked 'lost'.
                # The file-probe below is the real liveness check.
                try:
                    await asyncio.to_thread(container.reload)
                except Exception:  # noqa: BLE001
                    pass
                if container.status not in ("running", "restarting"):
                    try:
                        await asyncio.to_thread(container.start)
                    except Exception as _sx:  # noqa: BLE001 (already running / transient)
                        logger.info("[job:%s] reattach: container start skipped (%s)", jid, _sx)
            except NotFound:
                logger.info("[job:%s] reattach: container gone — marking lost", jid)
                await self._db_job_mark_lost(pool, jid)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[job:%s] reattach: container unusable (%s) — marking lost",
                    jid, exc,
                )
                await self._db_job_mark_lost(pool, jid)
                continue

            job = _JobState(
                job_id=jid,
                workspace_id=row["workspace_id"],
                container_name=row["container_name"],
                base=base,
                command=row["command"] or "",
                workdir=row["workdir"] or "/workspace",
                user_id=row["user_id"],
                started=(
                    float(row["started"]) if row["started"] is not None
                    else time.time()
                ),
            )

            try:
                res = await asyncio.to_thread(
                    container.exec_run,
                    ["sh", "-c",
                     f"if [ -f {base}.exit ]; then echo \"EXIT:$(cat {base}.exit)\"; "
                     f"elif [ -f {base}.out ]; then echo RUNNING; else echo GONE; fi"],
                    demux=False,
                )
                probe = (res.output or b"").decode("utf-8", errors="replace").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[job:%s] reattach: probe failed: %s", jid, exc)
                continue

            if probe.startswith("EXIT:"):
                raw = probe[5:].strip()
                try:
                    job.exit_code = int(raw.split()[0])
                except (ValueError, IndexError):
                    job.exit_code = -1
                job.status = "done" if job.exit_code == 0 else "exited"
                job.finished = time.time()
                self._jobs[jid] = job
                await self._db_job_finish(pool, job)
                try:
                    await self._capture_job_artifacts(job, container, pool)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[job:%s] reattach: artifact capture failed: %s", jid, exc,
                    )
                duration_ms = int((job.finished - job.started) * 1000)
                try:
                    await emit_terminal_event(
                        pool, job.workspace_id,
                        event_type="tool_result",
                        payload={
                            "tool": _TERMINAL_TOOL_NAME,
                            "success": job.exit_code == 0,
                            "summary": (
                                f"job {jid} {job.status} exit={job.exit_code} "
                                f"dur={duration_ms}ms (finalized after backend restart)"
                            ),
                            "args": {"command": job.command},
                            "output": {
                                "exit_code": job.exit_code,
                                "duration_ms": duration_ms,
                                "status": job.status,
                                "reattached": True,
                            },
                            "job_id": jid,
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.to_thread(
                        container.exec_run,
                        ["sh", "-c", f"rm -f {base}.pid {base}.out {base}.exit"],
                        demux=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                count += 1
                logger.info(
                    "[job:%s] reattach: finalized (exit=%s)", jid, job.exit_code,
                )
            elif probe == "RUNNING":
                self._jobs[jid] = job
                job.tail_task = asyncio.create_task(
                    self._tail_job(job, container, pool)
                )
                count += 1
                logger.info("[job:%s] reattach: resumed tail loop", jid)
            else:
                await self._db_job_mark_lost(pool, jid)
                logger.info(
                    "[job:%s] reattach: job files gone — marking lost", jid,
                )
        return count

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

        # Prune finished background-job records past retention. Running jobs
        # are never pruned here — their tail loop owns their lifecycle (and
        # enforces _JOB_MAX_LIFETIME_S itself).
        for jid, job in list(self._jobs.items()):
            if job.finished is not None and now - job.finished > _JOB_RETENTION_S:
                self._jobs.pop(jid, None)

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
# `allocate_event_seq` below is THE single seq allocator for workspace_events:
# both this module's emit_terminal_event AND workspace_router's run loop draw
# from it, so terminal/trace side-channel events can never collide with the
# run's own event stream (the old split — loop counter here, MAX(seq)+1 there —
# produced duplicate (workspace_id, seq) pairs that broke SSE resume-by-seq).

_TERMINAL_TOOL_NAME = "harvis-terminal"

# Per-workspace locks serializing seq allocation: without them the 1 Hz tail
# loops, parallel jobs, and foreground exec interleave MAX(seq)+1 reads and
# produce duplicate seq values (breaking SSE resume-by-seq).
_event_seq_locks: dict[str, asyncio.Lock] = {}

# Per-workspace next-seq cache. Seeded from the DB (MAX(seq)+1) on the first
# allocation, then handed out strictly monotonically from memory under the
# per-workspace lock. Entries are intentionally NEVER popped for the process
# lifetime: an eager cleanup could race an allocated-but-not-yet-inserted seq
# and re-issue it from a stale DB read. One int per run — negligible memory.
_event_seq_next: dict[str, int] = {}


def _event_seq_lock(workspace_id: str) -> asyncio.Lock:
    lock = _event_seq_locks.get(workspace_id)
    if lock is None:
        lock = _event_seq_locks.setdefault(workspace_id, asyncio.Lock())
    return lock


async def _next_event_seq(pool, workspace_id: str) -> int:
    """Pick the next monotonic seq for this workspace's event stream."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(MAX(seq) + 1, 0) AS next_seq "
            "FROM workspace_events WHERE workspace_id = $1",
            workspace_id,
        )
    return int(row["next_seq"]) if row else 0


async def allocate_event_seq(pool, workspace_id: str) -> int:
    """THE single collision-safe seq allocator for workspace_events.

    Every writer (emit_terminal_event here, _db_save_event's callers in
    workspace_router's run loop) MUST obtain its seq from this function.
    Under the per-workspace asyncio.Lock: the first allocation seeds from the
    DB's MAX(seq)+1, subsequent ones are handed out from the in-memory cache —
    strictly monotonic, no duplicates within this process. (The backend is a
    single uvicorn process; the guarded uq_workspace_events_ws_seq unique index
    is the cross-process backstop.) pool=None (broadcast-only mode) seeds at 0."""
    async with _event_seq_lock(workspace_id):
        nxt = _event_seq_next.get(workspace_id)
        if nxt is None:
            nxt = await _next_event_seq(pool, workspace_id) if pool is not None else 0
        _event_seq_next[workspace_id] = nxt + 1
        return nxt


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
        seq = await allocate_event_seq(pool, workspace_id)
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
