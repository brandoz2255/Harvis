"""The right sidebar's Files and Terminal over each chat's sandbox (see sandbox.py).

In the browser the desktop app's filesystem bridge becomes REST calls on
``/api/fs/*`` (src/lib/desktop-fs.ts) and its PTY becomes one WebSocket per
terminal tab (src/lib/desktop-shim/terminal.ts). Both only ever see
``/sandbox/<session>/workspace`` paths, resolved inside the caller's own folder.

Terminal frames are small JSON text messages so resize rides the same socket:
client → ``{"t":"i","d":<keys>}`` / ``{"t":"r","c":cols,"r":rows}``;
server → ``{"t":"ready"}``, ``{"t":"o","d":<output>}``, ``{"t":"x","code":n}``,
``{"t":"e","message":...}``.
"""
from __future__ import annotations

import asyncio
import codecs
import json
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from auth_optimized import decode_token_fast, get_current_user_optimized

from . import sandbox

log = logging.getLogger("hermes_ui.sandbox")

router = APIRouter(tags=["hermes-ui"])

API = "/hermes-api/api"
_SHELL = ["/bin/sh", "-c", "command -v bash >/dev/null 2>&1 && exec bash -l || exec sh -l"]


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except sandbox.SandboxError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "not found") from exc
    except PermissionError as exc:
        raise HTTPException(403, "permission denied") from exc


@router.get(f"{API}/fs/list")
async def fs_list(path: str, user=Depends(get_current_user_optimized)):
    return await asyncio.to_thread(_guard, sandbox.list_dir, _uid(user), path)


@router.get(f"{API}/fs/read-text")
async def fs_read_text(path: str, user=Depends(get_current_user_optimized)):
    return await asyncio.to_thread(_guard, sandbox.read_text, _uid(user), path)


@router.get(f"{API}/fs/read-data-url")
async def fs_read_data_url(path: str, user=Depends(get_current_user_optimized)):
    return await asyncio.to_thread(_guard, sandbox.read_data_url, _uid(user), path)


@router.get(f"{API}/fs/git-root")
async def fs_git_root(path: str, user=Depends(get_current_user_optimized)):
    return await asyncio.to_thread(_guard, sandbox.git_root, _uid(user), path)


@router.post(f"{API}/fs/write-text")
async def fs_write_text(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPException(400, "content must be text")
    return await asyncio.to_thread(_guard, sandbox.write_text, _uid(user), str(body.get("path") or ""), content)


# ─── the sandbox itself: size, GPU, running apps, delete ─────────────────────

_gpu_runtime: Optional[bool] = None


async def _manager():
    from workspace.terminal_container import get_terminal_manager
    return get_terminal_manager()


async def gpu_available() -> bool:
    """A GPU the sandbox could be given: the Docker daemon has the NVIDIA runtime
    (and HARVIS_SANDBOX_GPU isn't 'off'). Probed once per process."""
    global _gpu_runtime
    if os.getenv("HARVIS_SANDBOX_GPU", "auto").strip().lower() in ("0", "off", "false", "no"):
        return False
    if _gpu_runtime is None:
        try:
            mgr = await _manager()
            info = await asyncio.to_thread(mgr._client.info) if mgr._client else {}  # noqa: SLF001
            _gpu_runtime = "nvidia" in (info.get("Runtimes") or {})
        except Exception:  # noqa: BLE001
            _gpu_runtime = False
    return _gpu_runtime


def parse_listening(proc_net: str) -> list[dict]:
    """LISTEN sockets from /proc/net/tcp{,6} text → [{port, public}] (public = not loopback-only)."""
    ports: dict[int, bool] = {}
    for line in proc_net.splitlines():
        cols = line.split()
        if len(cols) < 4 or cols[3] != "0A" or ":" not in cols[1]:
            continue
        addr, port_hex = cols[1].rsplit(":", 1)
        try:
            port = int(port_hex, 16)
        except ValueError:
            continue
        loopback = addr in ("0100007F", "00000000000000000000000001000000")
        ports[port] = ports.get(port, False) or not loopback
    return [{"port": p, "public": pub} for p, pub in sorted(ports.items()) if p > 0]


async def _listening(user_id: int, sid: str) -> tuple[bool, list[dict]]:
    """(container running, its listening ports) — never starts the container."""
    try:
        mgr = await _manager()
        if mgr._client is None:  # noqa: SLF001
            return False, []
        c = await asyncio.to_thread(mgr._client.containers.get, sandbox.container_name(user_id, sid))  # noqa: SLF001
        if c.status != "running":
            return False, []
        res = await asyncio.to_thread(c.exec_run, ["cat", "/proc/net/tcp", "/proc/net/tcp6"], user="1001:1001")
        return True, parse_listening((res.output or b"").decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — not created yet, or Docker unreachable
        return False, []


@router.get(f"{API}/sandbox/info")
async def sandbox_info(session: str, user=Depends(get_current_user_optimized)):
    uid = _uid(user)
    await asyncio.to_thread(_guard, sandbox.ensure_dir, uid, session)
    size = await asyncio.to_thread(sandbox.usage_bytes, uid, session)
    running, ports = await _listening(uid, session)
    prefix = sandbox.app_prefix(uid, session)
    return {
        "cwd": sandbox.virtual_cwd(session),
        "size_bytes": size,
        "warn_bytes": sandbox.WARN_BYTES,
        "over_warn": size > sandbox.WARN_BYTES,
        "gpu": sandbox.gpu_wanted(uid, session),
        "gpu_available": await gpu_available(),
        "running": running,
        "apps": [{**p, "url": f"{prefix}/{p['port']}/"} for p in ports],
    }


@router.post(f"{API}/sandbox/gpu")
async def sandbox_gpu(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    uid, session, on = _uid(user), str(body.get("session") or ""), bool(body.get("on"))
    if on and not await gpu_available():
        raise HTTPException(400, "No GPU is available to sandboxes on this server.")
    await asyncio.to_thread(_guard, sandbox.set_gpu, uid, session, on)
    # The container is recreated with (or without) the GPU the next time it's needed.
    mgr = await _manager()
    await mgr.drop_isolated(sandbox.runner_key(uid, session))
    return {"ok": True, "gpu": on}


@router.delete(f"{API}/sandbox")
async def sandbox_delete(session: str, user=Depends(get_current_user_optimized)):
    """Stop the chat's container and delete its folder — frees the disk. The next
    terminal or agent run starts an empty sandbox (with a new app-link secret)."""
    uid = _uid(user)
    key = _guard(sandbox.runner_key, uid, session)
    mgr = await _manager()
    await mgr.drop_isolated(key)
    await asyncio.to_thread(sandbox.delete_dir, uid, session)
    return {"ok": True}


# ─── terminal ────────────────────────────────────────────────────────────────

def _token_from(ws: WebSocket) -> Optional[str]:
    tok = ws.cookies.get("access_token")
    if tok:
        return tok
    auth = ws.headers.get("authorization") or ""
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


def _int(raw: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


async def _open_shell(user_id: int, cwd: str, cols: int, rows: int):
    """Start (or wake) the session's runner and exec a login shell in it.
    Returns (manager, runner state, docker api client, exec id, raw socket)."""
    from workspace.terminal_container import get_terminal_manager

    sid, _, inner = await asyncio.to_thread(sandbox.resolve, user_id, cwd, create=True)
    mgr = get_terminal_manager()
    if mgr._client is None:  # noqa: SLF001 — the manager exposes no public client
        raise sandbox.SandboxError("Docker isn't reachable from the Harvis backend, so the sandbox can't start.")
    state = await mgr.ensure_isolated(sandbox.runner_key(user_id, sid), sandbox.session_dir(user_id, sid))
    api = mgr._client.api  # noqa: SLF001
    exec_id = (await asyncio.to_thread(
        api.exec_create, state.container_name, cmd=_SHELL, stdin=True, tty=True, workdir=inner,
        environment={"TERM": "xterm-256color", "COLORTERM": "truecolor", "HOME": sandbox.CONTAINER_DIR}))["Id"]
    sock = await asyncio.to_thread(api.exec_start, exec_id, socket=True, tty=True)
    raw = getattr(sock, "_sock", sock)
    await asyncio.to_thread(api.exec_resize, exec_id, height=rows, width=cols)
    return mgr, state, api, exec_id, raw


@router.websocket(f"{API}/terminal/ws")
async def terminal_ws(ws: WebSocket):
    token = _token_from(ws)
    payload = decode_token_fast(token) if token else None
    try:
        user_id = int(payload.get("sub")) if payload else None
    except (TypeError, ValueError):
        user_id = None
    if user_id is None:
        await ws.close(code=4401, reason="sign in to Harvis first")
        return
    await ws.accept()
    q = ws.query_params
    cols, rows = _int(q.get("cols"), 80, 10, 500), _int(q.get("rows"), 24, 4, 300)
    try:
        mgr, state, api, exec_id, raw = await _open_shell(user_id, q.get("cwd") or "", cols, rows)
    except Exception as exc:  # noqa: BLE001
        message = str(exc) if isinstance(exc, sandbox.SandboxError) else "The sandbox couldn't start."
        if not isinstance(exc, sandbox.SandboxError):
            log.exception("hermes_ui: sandbox terminal failed to start for user %s", user_id)
        await ws.send_text(json.dumps({"t": "e", "message": message}))
        await ws.close(code=1011)
        return

    await ws.send_text(json.dumps({"t": "ready"}))
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    async def pump_out() -> None:
        while True:
            data = await asyncio.to_thread(raw.recv, 16384)
            if not data:
                return
            state.last_used_at = time.time()  # keeps the idle sweep off a busy terminal
            text = decoder.decode(data)
            if text:
                await ws.send_text(json.dumps({"t": "o", "d": text}))

    async def pump_in() -> None:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("t") == "i" and isinstance(msg.get("d"), str):
                await asyncio.to_thread(raw.sendall, msg["d"].encode("utf-8"))
            elif msg.get("t") == "r":
                await asyncio.to_thread(api.exec_resize, exec_id,
                                        height=_int(msg.get("r"), rows, 4, 300), width=_int(msg.get("c"), cols, 10, 500))

    tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        try:
            raw.close()
        except Exception:  # noqa: BLE001
            pass
        code = None
        try:
            code = (await asyncio.to_thread(api.exec_inspect, exec_id)).get("ExitCode")
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.send_text(json.dumps({"t": "x", "code": code}))
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
