"""VibeCode session Run & Preview — the Build/Code tab's own dev-server sandbox.

The Repo Runner (``repo_sandbox``) answers "run this public GitHub repo". This
answers the other half: **run the code the agent just wrote in this session**, with
no GitHub anywhere in the loop. Same container, same network, same caps, same idle
reaper — the ONE difference is where the code comes from:

    repo_sandbox      : empty container  →  git clone <public url> /repo
    workspace_sandbox : bind-mount THIS session's directory at /repo

Everything else is inherited, deliberately, so there is exactly one implementation
of "spawn a capability-stripped box on the isolated network, start a dev server,
probe it for real, publish it on 127.0.0.1, reap it when idle".

Why a bind mount and not a copy:
  * the preview must show what the editor shows — a copy goes stale the moment the
    agent writes another file, and HMR (Vite/Next) would have nothing to watch;
  * ``npm install`` needs to write ``node_modules`` somewhere, and writing it into
    the session is what makes the second Run fast.

The mount is read-WRITE, and that grants the sandbox no authority it did not
already have: the workspace runner's own ``exec`` tool already runs commands in
that same directory. What the mount must never do is widen past ONE session, so
the source path is resolved from the DB row, ``realpath``-ed, and checked to be
strictly inside the sessions root before it is handed to docker.

Host-path resolution: the backend spawns SIBLING containers through the docker
socket, so a mount source is interpreted by the daemon on the HOST, not inside this
container. ``/data/artifacts`` is a named volume here, so its host path is read at
runtime from our own container's mount table — never hardcoded, so this keeps
working on a laptop, on the Mac VM, and under K8s alike.

Gated OFF by default behind ``HARVIS_VIBECODE_RUN_ENABLED`` plus a per-run approval
in the UI, exactly like the repo runner.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from typing import Optional

from .repo_sandbox import (
    _IDLE_TIMEOUT,
    _INSTALL_TIMEOUT,
    _PORT,
    _TRUTHY,
    ProgressCB,
    RepoSandboxManager,
    _Sandbox,
)

logger = logging.getLogger(__name__)

# Where session workspaces live INSIDE this container. The DB stores absolute paths
# under this root; anything outside it is refused rather than mounted.
_SESSIONS_ROOT = os.getenv(
    "HARVIS_VIBECODE_SESSIONS_ROOT", "/data/artifacts/harvis-vibecode-sessions"
)
_MAX_SANDBOXES = int(os.getenv("HARVIS_VIBECODE_MAX_SANDBOXES", "3"))

# The container runs as the session directory's owner, who has no home directory of
# its own inside the image. npm, corepack, pip and uv all need somewhere to write a
# cache, and without this they fail on a read-only /root or a missing $HOME.
_SANDBOX_HOME = {
    "HOME": "/tmp",
    "npm_config_cache": "/tmp/.npm",
    "XDG_CACHE_HOME": "/tmp/.cache",
}


def run_enabled() -> bool:
    """Running session code is gated OFF by default — it is code execution."""
    return (os.getenv("HARVIS_VIBECODE_RUN_ENABLED") or "").strip().lower() in _TRUTHY


# ── container-path → host-path ────────────────────────────────────────────────
_host_root_cache: Optional[tuple[str, str]] = None  # (container_mountpoint, host_source)


def _resolve_mount_root(client) -> Optional[tuple[str, str]]:
    """Find which of OUR mounts contains the sessions root, and what the HOST calls it.

    Returns ``(destination_in_this_container, source_on_host)`` — e.g.
    ``("/data/artifacts", "/var/lib/docker/volumes/harvis_artifact_data/_data")``.
    None when it cannot be determined, in which case running is refused with a real
    reason rather than mounting a guess.
    """
    global _host_root_cache
    if _host_root_cache is not None:
        return _host_root_cache
    # An explicit override wins — the escape hatch for a deployment whose layout the
    # self-inspection below cannot see (a nested runtime, a rootless daemon).
    override = (os.getenv("HARVIS_VIBECODE_HOST_ARTIFACT_ROOT") or "").strip()
    if override:
        _host_root_cache = ("/data/artifacts", override)
        return _host_root_cache
    if client is None:
        return None
    try:
        me = client.containers.get(socket.gethostname())
        mounts = me.attrs.get("Mounts") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("workspace_sandbox: could not inspect own container: %s", exc)
        return None
    # Longest matching destination wins, so a dedicated mount for the sessions dir
    # would be preferred over the artifact volume that merely contains it.
    best: Optional[tuple[str, str]] = None
    for m in mounts:
        dest = (m.get("Destination") or "").rstrip("/")
        src = m.get("Source") or ""
        if not dest or not src:
            continue
        if _SESSIONS_ROOT == dest or _SESSIONS_ROOT.startswith(dest + "/"):
            if best is None or len(dest) > len(best[0]):
                best = (dest, src)
    if best is None:
        logger.warning(
            "workspace_sandbox: no mount of this container contains %s — set "
            "HARVIS_VIBECODE_HOST_ARTIFACT_ROOT to the host path", _SESSIONS_ROOT,
        )
        return None
    _host_root_cache = best
    return best


def host_path_for(workspace_path: str, client=None) -> tuple[Optional[str], str]:
    """Translate a session's in-container path to the host path docker must mount.

    Returns ``(host_path, reason)``; ``host_path`` is None on refusal and ``reason``
    then says why, in words a user can act on. Refuses anything that does not
    ``realpath`` to a directory strictly inside the sessions root — the single check
    that keeps one session's sandbox out of every other session's files.
    """
    if not workspace_path:
        return None, "this session has no workspace directory"
    real = os.path.realpath(workspace_path)
    root = os.path.realpath(_SESSIONS_ROOT)
    if real != root and not real.startswith(root + os.sep):
        return None, "session workspace is outside the sessions root"
    if real == root:
        return None, "refusing to run the whole sessions root"
    if not os.path.isdir(real):
        return None, "session workspace directory no longer exists on disk"
    pair = _resolve_mount_root(client)
    if not pair:
        return None, (
            "cannot map the session directory to a host path — set "
            "HARVIS_VIBECODE_HOST_ARTIFACT_ROOT"
        )
    dest, src = pair
    rel = os.path.relpath(real, dest)
    if rel.startswith(".."):
        return None, "session workspace is outside the mapped volume"
    return os.path.join(src, rel), "ok"


def _owner_of(path: str) -> tuple[int, int]:
    """The uid:gid that owns the session directory, for the container to run as.

    Capabilities are dropped in the sandbox, so root there has no CAP_DAC_OVERRIDE
    and cannot write into a directory another uid owns — which is every session
    directory, since the backend creates them as its own unprivileged user. Running
    as the owner is what lets ``npm install`` write ``node_modules``. The numbers are
    the same on both sides of the bind mount: uids are numeric, not translated.
    """
    st = os.stat(path)
    return st.st_uid, st.st_gid


class WorkspaceSandboxManager(RepoSandboxManager):
    """Dev-server sandboxes for VibeCode sessions — one box per session."""

    _ROLE = "vibecode-sandbox"
    # Outside /repo on purpose: the mount is the user's own source tree, and a dev
    # log dropped in it would show up in the diff the agent and the editor read.
    _LOG_PATH = "/tmp/harvis-dev.log"

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        # ``stop()`` drops the box from the live table, so without this the next
        # /preview says "never ran" one second after you pressed Stop. The Repo
        # Runner does not need it — it persists every status to a DB row — but this
        # lane's state IS the manager, so the last status has to survive the box.
        self._stopped: dict[str, dict] = {}

    def state(self, space_id: str) -> Optional[dict]:  # type: ignore[override]
        return super().state(space_id) or self._stopped.get(space_id)

    async def stop(self, space_id: str) -> bool:  # type: ignore[override]
        last = super().state(space_id)
        ok = await super().stop(space_id)
        if last:
            # host_port 0 because the port is gone with the container; keeping the
            # old number would invite the UI to link somewhere that refuses.
            #
            # A failed run stops itself on the way out, so this is also the last
            # chance to keep WHY it failed. Overwriting that with a bare "stopped"
            # would throw away the only message the user could act on.
            failed = last.get("status") == "failed"
            self._stopped[space_id] = {
                **last, "host_port": 0,
                "status": "failed" if failed else "stopped",
                "error": last.get("error", "") if failed else "",
            }
            # Bounded: this only ever holds one small dict per session run in this
            # process, but "only ever" is how leaks start.
            while len(self._stopped) > 50:
                self._stopped.pop(next(iter(self._stopped)))
        return ok

    def _name(self, space_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in space_id)
        return f"harvis-vibe-sbx-{safe[:40]}"

    async def run(  # type: ignore[override]
        self,
        session_id: str,
        workspace_path: str,
        install_cmd: Optional[str],
        dev_cmd: str,
        env: dict,
        framework: str,
        progress: ProgressCB,
    ) -> dict:
        """spawn (with the session mounted) → install if needed → start → probe.

        No clone phase: the code is already there. ``install_cmd`` may be None — a
        hand-written page has nothing to install, and inventing an install step for
        it would only produce a confusing failure.
        """
        if self._client is None:
            return {"ok": False, "status": "failed", "error": "docker client unavailable"}
        if not dev_cmd:
            return {"ok": False, "status": "failed",
                    "error": "no dev command for this workspace — nothing to run"}

        host_src, why = host_path_for(workspace_path, self._client)
        if not host_src:
            return {"ok": False, "status": "failed", "error": why}

        running = sum(1 for b in self._boxes.values()
                      if b.status in ("cloning", "installing", "starting", "running"))
        if running >= _MAX_SANDBOXES and session_id not in self._boxes:
            return {"ok": False, "status": "failed",
                    "error": f"preview capacity reached ({_MAX_SANDBOXES} running) — stop another preview first"}

        box = _Sandbox(space_id=session_id, container_name=self._name(session_id),
                       port=_PORT, framework=framework)
        box.on_persist = progress
        self._boxes[session_id] = box
        self._stopped.pop(session_id, None)

        async def _set(status: str, **fields) -> None:
            box.status = status
            box.last_used_at = time.time()
            for k, v in fields.items():
                setattr(box, k, v)
            await progress(status, {"port": box.port, "host_port": box.host_port,
                                    "framework": box.framework,
                                    "error": box.error, "log_tail": box.log_tail})

        try:
            # "starting" is the honest first status when install is skipped; the UI
            # ladder reads the status, so never announce a phase that will not run.
            await _set("installing" if install_cmd else "starting")
            uid, gid = _owner_of(os.path.realpath(workspace_path))
            box.host_port = await self._spawn(
                session_id, volumes={host_src: {"bind": "/repo", "mode": "rw"}},
                user=f"{uid}:{gid}",
            )
            if not box.host_port:
                await _set("failed", error="could not publish a preview port")
                await self.stop(session_id)
                return {"ok": False, "status": "failed", "error": "could not publish a preview port"}

            if install_cmd:
                rc, out = await self._exec(
                    box.container_name,
                    f"(corepack enable >/dev/null 2>&1 || true); {install_cmd}",
                    timeout=_INSTALL_TIMEOUT,
                    env=_SANDBOX_HOME,
                )
                if rc != 0:
                    hint = (" (registry unreachable?)"
                            if ("ENOTFOUND" in out or "getaddrinfo" in out) else "")
                    await _set("failed", error=f"install failed{hint}", log_tail=out[-2500:])
                    await self.stop(session_id)
                    return {"ok": False, "status": "failed",
                            "error": f"install failed{hint}", "log": out}
                await _set("starting", log_tail=out[-1500:])

            start_env = {"CI": "1", "BROWSER": "none", "PORT": str(_PORT),
                         "HOST": "0.0.0.0", **_SANDBOX_HOME, **(env or {})}
            await self._exec_detached(
                box.container_name,
                f"exec {dev_cmd} > {self._LOG_PATH} 2>&1", env=start_env)

            ready, tail = await self._await_ready(session_id, box.container_name, box.port)
            if not ready:
                await _set("failed", error="dev server did not become reachable",
                           log_tail=tail[-2500:])
                await self.stop(session_id)
                return {"ok": False, "status": "failed",
                        "error": "dev server did not become reachable", "log": tail}

            await _set("running", log_tail=tail[-2000:])
            logger.info("[vibe-sbx:%s] running at %s:%s (host_port=%s, %s)",
                        session_id, box.container_name, box.port, box.host_port, framework)
            return {"ok": True, "status": "running", "port": box.port,
                    "host_port": box.host_port, "framework": framework, "log": tail}
        except Exception as exc:  # noqa: BLE001
            logger.exception("[vibe-sbx:%s] run failed", session_id)
            await _set("failed", error=f"sandbox error: {exc}")
            await self.stop(session_id)
            return {"ok": False, "status": "failed", "error": str(exc)}


_singleton: Optional[WorkspaceSandboxManager] = None


def get_manager() -> WorkspaceSandboxManager:
    global _singleton
    if _singleton is None:
        _singleton = WorkspaceSandboxManager()
    return _singleton


async def run_sweeper(interval: int = 60) -> None:
    """Reap idle + terminal session sandboxes. Separate from the repo runner's
    sweeper because the two managers hold separate box tables."""
    while True:
        await asyncio.sleep(interval)
        try:
            await get_manager().sweep_idle()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "run_enabled", "host_path_for", "get_manager", "run_sweeper",
    "WorkspaceSandboxManager", "_IDLE_TIMEOUT",
]
