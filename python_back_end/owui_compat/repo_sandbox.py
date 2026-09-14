"""Adaptive Workspace Repo Runner — ISOLATED dev-server sandbox.

This is the higher-lane capability behind the honest 403 gate: it actually runs
an untrusted public repo's dev server so the Repo Runner can show the running app.

Security model (why this is safe to run untrusted code):
  * A dedicated docker network ``harvis_repo-sandbox`` that carries NO Harvis
    service — the sandbox CANNOT reach pgsql / ollama / openclaw / other users'
    data. It is a bridge network (not ``internal: true``) so ``npm install`` can
    reach the public registry — the only thing the code could exfil is the
    already-public repo. The backend is dual-homed onto it purely to run the
    readiness probe against the dev-server port; it never mounts the artifact
    volume into the sandbox.
    RESIDUAL RISK (be honest): because the backend sits on this network, the
    sandbox CAN reach ``backend:8000`` — but every backend API is JWT-
    authenticated and the sandbox holds no Harvis credentials, so this is an
    authenticated surface, not an open door. A production / multi-user deploy
    should still add a K8s NetworkPolicy locking the sandbox down further.
  * The live preview is a PUBLISHED PORT: the container's dev port (3000) is
    published to an auto-assigned host port bound to 127.0.0.1 only, and the
    iframe loads the app directly at the root of that origin. No path-proxy,
    no base-path rewriting — and the distinct localhost origin keeps the
    untrusted app isolated from Harvis's own origin (localStorage / JWT).
  * The repo is cloned FRESH inside the sandbox (its own copy) — the sandbox
    never touches ``/data/artifacts``.
  * Resource caps (memory / CPU), hard timeouts on every phase, a global cap on
    concurrent sandboxes, and idle teardown bound the blast radius.
  * Gated OFF by default (``HARVIS_ADAPTIVE_REPO_RUN_ENABLED``) + per-run approval
    in the UI. When off, nothing here ever runs.

Nothing is faked: install/start run real commands, the dev-server log is real,
and readiness is a real HTTP probe. If the server never becomes reachable we say
so with the real log tail — never a fake "running".
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import httpx

from . import fab_repo

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# The polyglot sandbox image (repo-sandbox-engine/Dockerfile) carries Node 20 +
# npm/corepack + Python 3.11 + uv, so Harvis can adapt to Node OR Python repos.
# Default to it so a deployment that flips the run flag on without also setting the
# image env (e.g. the K8s path) doesn't silently fall back to a node-only sandbox
# where every Python install command fails with "uv: not found".
_IMAGE = os.getenv("HARVIS_ADAPTIVE_REPO_SANDBOX_IMAGE", "harvis-repo-sandbox:local")
_NETWORK = os.getenv("HARVIS_ADAPTIVE_REPO_SANDBOX_NETWORK", "harvis_repo-sandbox")
_MEM = os.getenv("HARVIS_ADAPTIVE_REPO_SANDBOX_MEM", "1500m")
_CPUS = float(os.getenv("HARVIS_ADAPTIVE_REPO_SANDBOX_CPUS", "1.5"))
_CLONE_TIMEOUT = int(os.getenv("HARVIS_ADAPTIVE_REPO_CLONE_TIMEOUT_S", "90"))
_INSTALL_TIMEOUT = int(os.getenv("HARVIS_ADAPTIVE_REPO_INSTALL_TIMEOUT_S", "420"))
_READY_TIMEOUT = int(os.getenv("HARVIS_ADAPTIVE_REPO_READY_TIMEOUT_S", "120"))
_IDLE_TIMEOUT = int(os.getenv("HARVIS_ADAPTIVE_REPO_IDLE_TIMEOUT_S", "1800"))  # 30m
_MAX_SANDBOXES = int(os.getenv("HARVIS_ADAPTIVE_REPO_MAX_SANDBOXES", "4"))
_PORT = fab_repo._DEV_PORT
_LOG = "/repo/.harvis-dev.log"


def run_enabled() -> bool:
    """The dev-server sandbox is gated OFF by default (untrusted-code execution)."""
    return (os.getenv("HARVIS_ADAPTIVE_REPO_RUN_ENABLED") or "").strip().lower() in _TRUTHY


ProgressCB = Callable[[str, dict], Awaitable[None]]


@dataclass
class _Sandbox:
    space_id: str
    container_name: str
    status: str = "pending"           # pending|cloning|installing|starting|running|failed|stopped
    port: int = _PORT
    host_port: int = 0
    framework: str = ""
    error: str = ""
    log_tail: str = ""
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    # The run's progress callback, kept so the idle sweeper can persist a truthful
    # "stopped" status when it reaps a still-'running' box (otherwise the UI shows a
    # live badge over a dead sandbox forever — it stops polling once running).
    on_persist: Optional[ProgressCB] = None


class RepoSandboxManager:
    """Per-space dev-server sandboxes on the isolated repo-sandbox network."""

    def __init__(self) -> None:
        try:
            import docker
            self._client = docker.from_env()
        except Exception as exc:  # noqa: BLE001
            logger.error("RepoSandboxManager: docker client init failed: %s", exc)
            self._client = None
        self._boxes: dict[str, _Sandbox] = {}
        self._lock = asyncio.Lock()

    # ── readiness ──────────────────────────────────────────────────────────
    async def probe(self) -> dict:
        if self._client is None:
            return {"ready": False, "reason": "docker client unavailable (is /var/run/docker.sock mounted?)"}
        try:
            await asyncio.to_thread(self._client.ping)
        except Exception as exc:  # noqa: BLE001
            return {"ready": False, "reason": f"docker ping failed: {exc}"}
        try:
            await asyncio.to_thread(self._client.networks.get, _NETWORK)
        except Exception:  # noqa: BLE001
            return {"ready": False, "reason": f"network {_NETWORK!r} not found — add it to docker-compose + `docker compose up -d`"}
        return {"ready": True, "reason": "ok", "network": _NETWORK, "image": _IMAGE}

    # ── container lifecycle ────────────────────────────────────────────────
    def _name(self, space_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in space_id)
        return f"harvis-repo-sbx-{safe[:40]}"

    # Subclass hooks: the workspace runner reuses this whole lifecycle but labels its
    # boxes differently, mounts a directory instead of cloning into an empty one, and
    # keeps its dev log out of the mounted tree.
    _ROLE = "repo-sandbox"
    _LOG_PATH = _LOG

    async def _spawn(self, space_id: str, volumes: Optional[dict] = None,
                     user: Optional[str] = None) -> int:
        """Create the sandbox container with the dev port PUBLISHED to a docker
        auto-assigned host port (bound to 127.0.0.1 only). Returns that host port
        (0 if docker didn't report one).

        ``volumes`` is the docker-py bind spec; None keeps the historical behaviour of
        an empty container that gets a fresh ``git clone``. ``user`` ("uid:gid") is for
        the bind-mounted case: capabilities are dropped, so root here has NO
        CAP_DAC_OVERRIDE and cannot write into a directory owned by someone else."""
        name = self._name(space_id)
        # Remove any stale container with this name first (idempotent fresh run).
        try:
            old = await asyncio.to_thread(self._client.containers.get, name)
            await asyncio.to_thread(old.remove, force=True)
        except Exception:  # noqa: BLE001
            pass
        container = await asyncio.to_thread(
            self._client.containers.run,
            _IMAGE,
            command=["sh", "-c", "tail -f /dev/null"],
            name=name,
            detach=True,
            network=_NETWORK,
            mem_limit=_MEM,
            nano_cpus=int(_CPUS * 1_000_000_000),
            pids_limit=512,
            # This container runs untrusted, injection-prone repo code. Strip all
            # Linux capabilities and block privilege escalation to bound the blast
            # radius. It stays root (the `uv pip install --system` path writes to
            # system site-packages), but a capability-stripped no-new-privileges
            # root is far less dangerous than a full-cap one.
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            labels={"harvis.role": self._ROLE, "harvis.space_id": space_id},
            working_dir="/repo",
            auto_remove=False,
            volumes=volumes or {},
            ports={f"{_PORT}/tcp": ("127.0.0.1", None)},  # None = auto-assign a free host port
            **({"user": user} if user else {}),
        )
        host_port = 0
        try:
            await asyncio.to_thread(container.reload)
            bindings = container.attrs["NetworkSettings"]["Ports"][f"{_PORT}/tcp"]
            host_port = int(bindings[0]["HostPort"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[repo-sbx:%s] could not read published host port: %s", space_id, exc)
        logger.info("[repo-sbx:%s] spawned %s (image=%s net=%s mem=%s host_port=%s)",
                    space_id, name, _IMAGE, _NETWORK, _MEM, host_port)
        return host_port

    async def _exec(self, name: str, cmd: str, *, timeout: int, workdir: str = "/repo",
                    env: Optional[dict] = None) -> tuple[int, str]:
        """One-shot exec with a hard timeout. Returns (exit_code, combined output)."""
        container = await asyncio.to_thread(self._client.containers.get, name)
        wrapped = f"timeout --kill-after=5 {int(timeout)}s sh -lc {shlex.quote(cmd)}"
        try:
            res = await asyncio.to_thread(
                container.exec_run, ["sh", "-lc", wrapped],
                workdir=workdir, demux=False, environment=env or {},
            )
        except Exception as exc:  # noqa: BLE001
            return 1, f"exec failed: {exc}"
        out = (res.output or b"").decode("utf-8", errors="replace")
        return (res.exit_code if res.exit_code is not None else -1), out

    async def _exec_detached(self, name: str, cmd: str, *, workdir: str = "/repo",
                             env: Optional[dict] = None) -> None:
        container = await asyncio.to_thread(self._client.containers.get, name)
        await asyncio.to_thread(
            container.exec_run, ["sh", "-lc", cmd],
            workdir=workdir, environment=env or {}, detach=True,
        )

    async def _log_tail(self, name: str, lines: int = 40) -> str:
        rc, out = await self._exec(
            name, f"tail -n {lines} {self._LOG_PATH} 2>/dev/null || true", timeout=10)
        return out.strip()

    async def _await_ready(self, space_id: str, name: str, port: int) -> tuple[bool, str]:
        """Poll the dev server over the isolated network until it answers or times out."""
        deadline = time.time() + _READY_TIMEOUT
        url = f"http://{name}:{port}/"
        last_tail = ""
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.time() < deadline:
                # If the container died, stop early.
                try:
                    c = await asyncio.to_thread(self._client.containers.get, name)
                    if c.status not in ("running", "created"):
                        return False, await self._log_tail(name)
                except Exception:  # noqa: BLE001
                    return False, last_tail
                try:
                    r = await client.get(url)
                    # Any HTTP response (even 404/500) means the server is up + reachable.
                    if r.status_code < 600:
                        return True, await self._log_tail(name)
                except Exception:  # noqa: BLE001
                    pass
                last_tail = await self._log_tail(name)
                await asyncio.sleep(2.0)
        return False, last_tail or "(dev server produced no output)"

    # ── the run orchestration ──────────────────────────────────────────────
    async def run(self, space_id: str, clone_url: str, install_cmd: str, dev_cmd: str,
                  env: dict, framework: str, progress: ProgressCB) -> dict:
        """Full sequence: spawn → clone → install → start → probe. Persists progress
        via the async ``progress(status, fields)`` callback. Returns final state."""
        if self._client is None:
            return {"ok": False, "status": "failed", "error": "docker client unavailable"}
        url = fab_repo.validate_url(clone_url)
        if not url:
            return {"ok": False, "status": "failed", "error": "invalid repo url"}

        running = sum(1 for b in self._boxes.values() if b.status in ("cloning", "installing", "starting", "running"))
        if running >= _MAX_SANDBOXES and space_id not in self._boxes:
            return {"ok": False, "status": "failed",
                    "error": f"sandbox capacity reached ({_MAX_SANDBOXES} running) — stop another preview first"}

        box = _Sandbox(space_id=space_id, container_name=self._name(space_id), port=_PORT, framework=framework)
        box.on_persist = progress
        self._boxes[space_id] = box

        async def _set(status: str, **fields) -> None:
            box.status = status
            box.last_used_at = time.time()
            for k, v in fields.items():
                setattr(box, k, v)
            await progress(status, {"port": box.port, "host_port": box.host_port,
                                    "framework": box.framework,
                                    "error": box.error, "log_tail": box.log_tail})

        try:
            await _set("cloning")
            box.host_port = await self._spawn(space_id)
            if not box.host_port:
                # No published host port → the browser could never reach the preview;
                # fail honestly instead of showing a live-but-blank state.
                await _set("failed", error="could not publish a preview port")
                await self.stop(space_id)
                return {"ok": False, "status": "failed", "error": "could not publish a preview port"}
            rc, out = await self._exec(box.container_name,
                                       f"rm -rf /repo && git clone --depth 1 {shlex.quote(url)} /repo",
                                       timeout=_CLONE_TIMEOUT, workdir="/")
            if rc != 0:
                await _set("failed", error="clone failed", log_tail=out[-2000:])
                await self.stop(space_id)
                return {"ok": False, "status": "failed", "error": "clone failed", "log": out}

            await _set("installing")
            # corepack ships with node:20 — enable it so pnpm/yarn projects install.
            rc, out = await self._exec(box.container_name,
                                       f"(corepack enable >/dev/null 2>&1 || true); {install_cmd}",
                                       timeout=_INSTALL_TIMEOUT)
            if rc != 0:
                # Common on the DNS-restricted cluster: registry unreachable.
                hint = " (registry unreachable? offline installs fail on the K8s cluster)" if ("ENOTFOUND" in out or "getaddrinfo" in out or "network" in out.lower()) else ""
                await _set("failed", error=f"install failed{hint}", log_tail=out[-2500:])
                await self.stop(space_id)
                return {"ok": False, "status": "failed", "error": f"install failed{hint}", "log": out}

            await _set("starting", log_tail=out[-1500:])
            start_env = {"CI": "1", "BROWSER": "none", "PORT": str(_PORT), "HOST": "0.0.0.0", **(env or {})}
            await self._exec_detached(box.container_name, f"exec {dev_cmd} > {_LOG} 2>&1", env=start_env)

            ready, tail = await self._await_ready(space_id, box.container_name, box.port)
            if not ready:
                await _set("failed", error="dev server did not become reachable", log_tail=tail[-2500:])
                await self.stop(space_id)
                return {"ok": False, "status": "failed", "error": "dev server did not become reachable", "log": tail}

            await _set("running", log_tail=tail[-2000:])
            logger.info("[repo-sbx:%s] running at %s:%s (host_port=%s, %s)",
                        space_id, box.container_name, box.port, box.host_port, framework)
            return {"ok": True, "status": "running", "port": box.port, "host_port": box.host_port,
                    "framework": framework, "log": tail}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[repo-sbx:%s] run failed", space_id)
            await _set("failed", error=f"sandbox error: {exc}")
            await self.stop(space_id)
            return {"ok": False, "status": "failed", "error": str(exc)}

    # ── lifecycle helpers ──────────────────────────────────────────────────
    def state(self, space_id: str) -> Optional[dict]:
        box = self._boxes.get(space_id)
        if not box:
            return None
        return {"status": box.status, "port": box.port, "host_port": box.host_port,
                "framework": box.framework, "error": box.error, "log_tail": box.log_tail}

    async def stop(self, space_id: str) -> bool:
        async with self._lock:
            box = self._boxes.pop(space_id, None)
        name = box.container_name if box else self._name(space_id)
        if self._client is None:
            return False
        try:
            c = await asyncio.to_thread(self._client.containers.get, name)
        except Exception:  # noqa: BLE001
            return False
        try:
            await asyncio.to_thread(c.remove, force=True)
            logger.info("[repo-sbx:%s] stopped %s", space_id, name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[repo-sbx:%s] stop failed: %s", space_id, exc)
            return False

    async def sweep_idle(self) -> int:
        now = time.time()
        stale = [(sid, b) for sid, b in list(self._boxes.items())
                 if b.status in ("failed", "stopped") or now - b.last_used_at > _IDLE_TIMEOUT]
        for sid, b in stale:
            # A still-live box reaped for idleness must have its persisted preview
            # corrected, or the UI keeps showing a green "Live" badge over a dead
            # sandbox indefinitely (the client stops polling once running).
            if b.status in ("cloning", "installing", "starting", "running") and b.on_persist:
                try:
                    await b.on_persist("stopped", {
                        "port": b.port, "host_port": 0, "framework": b.framework,
                        "error": "sandbox reaped after idle timeout", "log_tail": b.log_tail,
                    })
                except Exception:  # noqa: BLE001
                    logger.warning("[repo-sbx:%s] idle-reap persist failed", sid)
            await self.stop(sid)
        return len(stale)


_singleton: Optional[RepoSandboxManager] = None


def get_manager() -> RepoSandboxManager:
    global _singleton
    if _singleton is None:
        _singleton = RepoSandboxManager()
    return _singleton


async def run_sweeper(interval: int = 60) -> None:
    """Background loop (scheduled at startup) that reaps idle + terminal sandboxes."""
    while True:
        await asyncio.sleep(interval)
        try:
            await get_manager().sweep_idle()
        except Exception:  # noqa: BLE001
            pass
