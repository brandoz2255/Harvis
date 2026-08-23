"""Sandboxed preview of files the assistant creates in the Claude subscription chat.

The subscription chat runs ``claude -p`` inside the ``harvis-claude-code`` sidecar. When the model
creates a file (an HTML page, an SVG, a doc…) it lands in a PER-USER directory on the shared
artifact volume — not on the user's laptop, not reachable by a browser except through Harvis.

  * ``chat_workdir`` / ``mkdir_workdir`` — persistent per-user sandbox (notes survive turns).
  * ``seed_sandbox`` — copy SANDBOX.md / README / notes.md / harvis-check.sh if missing.
  * ``list_new_files`` — renderable files THIS run produced (for the clickable preview footer).
  * ``GET /api/owui/chat-file?path=…`` — reads one such file back OUT of the sidecar so Harvis can
    render a live preview when the user clicks the path.

Isolation: a user can only read under their OWN workroot (``/data/artifacts/harvis-chat/u<id>/``);
the path is normalized server-side and re-checked against that prefix.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

_CONTAINER = os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code")
# Shared artifact volume (compose mounts artifact_data → /data/artifacts). /tmp died with
# the container and was per-run, so the model could not keep notes across turns.
_WORKROOT = os.getenv("HARVIS_CHAT_SANDBOX_ROOT", "/data/artifacts/harvis-chat")
_SANDBOX_SRC = "/home/claude/harvis-sandbox"
_MAX_BYTES = 2_000_000
# Scaffolding Harvis itself puts in the sandbox, plus the doc names a model habitually
# writes next to it. None of it is the user's work, and all of it used to show up in the
# preview footer and the Artifacts list as if it were. Compared lowercased.
_BOILERPLATE = {
    "sandbox.md",
    "readme.md",
    "readme",
    "notes.md",
    "harvis-check.sh",
    ".harvis-run-start",
    "about",
    "about.md",
    "about.txt",
    "index",
    "index.md",
    "index.txt",
}
# Directories that only ever hold machine output.
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".ipynb_checkpoints", ".pytest_cache"}

_TEXT_EXT = {
    ".html", ".htm", ".svg", ".css", ".js", ".mjs", ".ts", ".jsx", ".tsx", ".json", ".md",
    ".markdown", ".txt", ".csv", ".xml", ".yaml", ".yml", ".py", ".sh", ".sql",
}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"}
_ALLOWED_EXT = _TEXT_EXT | _IMG_EXT


def _uid(user) -> int:
    if isinstance(user, dict):
        return int(user.get("id") or 0)
    return int(getattr(user, "id", 0) or 0)


def chat_workdir(user_id, run_id: Optional[str] = None) -> str:
    """Persistent per-user sandbox inside the sidecar.

    ``run_id`` is ignored for the path (kept so callers do not change). Notes, scripts,
    and SANDBOX.md live here across turns. A marker file timestamps each run so the
    preview footer only lists files this turn created.
    """
    return f"{_WORKROOT}/u{int(user_id)}"


async def _dexec(*args: str, timeout: float = 8.0) -> tuple[int, bytes, bytes]:
    """Run one ``docker exec harvis-claude-code <args…>`` — args passed directly (NO shell)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", _CONTAINER, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, b"", b"docker missing"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return 124, b"", b"timeout"
    return proc.returncode or 0, out or b"", err or b""


async def seed_sandbox(workdir: str) -> None:
    """Copy SANDBOX.md / README / notes.md / harvis-check.sh if they are not already there.

    ``cp -n`` (no-clobber) so the model's notes.md is never overwritten. Best-effort.
    """
    if not workdir or ".." in workdir or "\x00" in workdir:
        return
    cmd = (
        f'cp -n {_SANDBOX_SRC}/* "{workdir}/" 2>/dev/null; '
        f'chmod +x "{workdir}/harvis-check.sh" 2>/dev/null; '
        f'touch "{workdir}/.harvis-run-start"; true'
    )
    await _dexec("sh", "-c", cmd, timeout=12.0)


async def mkdir_workdir(user_id, run_id: str = "") -> Optional[str]:
    """Create the persistent per-user sandbox, seed docs if missing, stamp this run."""
    wd = chat_workdir(user_id, run_id)
    rc, _out, _err = await _dexec("mkdir", "-p", wd)
    if rc != 0:
        return None
    await seed_sandbox(wd)
    return wd


async def list_new_files(user_id, run_id: str = "") -> list[str]:
    """Renderable files this run produced (full container paths) — for the preview footer."""
    wd = chat_workdir(user_id, run_id)
    marker = f"{wd}/.harvis-run-start"
    rc, out, _err = await _dexec(
        "find", wd, "-maxdepth", "4", "-type", "f", "-newer", marker, timeout=12.0
    )
    if rc != 0:
        rc, out, _err = await _dexec("find", wd, "-maxdepth", "4", "-type", "f")
        if rc != 0:
            return []
    files = [line.strip() for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
    out_paths: list[str] = []
    for f in files:
        name = os.path.basename(f)
        if name.lower() in _BOILERPLATE or name.startswith("."):
            continue
        if any(part in _SKIP_DIRS for part in f.split("/")):
            continue
        if os.path.splitext(f)[1].lower() in _ALLOWED_EXT:
            out_paths.append(f)
        if len(out_paths) >= 12:
            break
    return out_paths


def register_chat_file_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/chat-file")
    async def chat_file(request: Request, path: str = "", user=Depends(get_current_user)):
        uid = _uid(user)
        if not uid:
            raise HTTPException(status_code=401, detail="unauthorized")
        p = (path or "").strip()
        if not p or "\x00" in p or not p.startswith(_WORKROOT + "/"):
            raise HTTPException(status_code=400, detail="path must be under the chat sandbox")
        # Normalize server-side (POSIX, same as the container) and re-check the per-user prefix.
        # normpath collapses `..`, so a cross-user or escaping path fails this test.
        norm = os.path.normpath(p)
        root = chat_workdir(uid) + "/"
        if not norm.startswith(root):
            raise HTTPException(status_code=404, detail="not found")
        ext = os.path.splitext(norm)[1].lower()
        if ext not in _ALLOWED_EXT:
            raise HTTPException(status_code=415, detail="preview not supported for this file type")
        rc, out, _err = await _dexec("head", "-c", str(_MAX_BYTES), "--", norm)
        if rc != 0:
            raise HTTPException(status_code=404, detail="not found")
        name = os.path.basename(norm)
        mime = mimetypes.guess_type(name)[0] or ("image/png" if ext in _IMG_EXT else "text/plain")
        if ext in _IMG_EXT:
            return {
                "path": norm, "name": name, "mime": mime, "is_binary": True,
                "data_url": f"data:{mime};base64," + base64.b64encode(out).decode(),
            }
        return {
            "path": norm, "name": name, "mime": mime, "is_binary": False,
            "content": out.decode("utf-8", "replace"),
        }
