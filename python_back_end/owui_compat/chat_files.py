"""Sandboxed preview of files the assistant creates in the Claude subscription chat.

The subscription chat runs ``claude -p`` inside the ``harvis-claude-code`` sidecar. When the model
creates a file (an HTML page, an SVG, a doc…) it lands in a PER-USER / PER-RUN directory inside that
container — by design it is NOT on the user's machine and NOT reachable by a browser. This module:

  * ``chat_workdir`` / ``mkdir_workdir`` — the per-user, per-run sandbox path the chat runs in.
  * ``list_new_files`` — the renderable files a run produced (for the clickable "preview" footer).
  * ``GET /api/owui/chat-file?path=…`` — reads one such file back OUT of the sidecar so Harvis can
    render a live preview when the user clicks the path.

Isolation: a user can only read under their OWN workroot (``/tmp/harvis-chat/u<their-id>/``); the
path is normalized server-side and re-checked against that prefix (``..`` collapses out, so a
cross-user or escaping path fails the prefix test). Size- and type-capped; text/renderable only
(images returned as a data URL). The sidecar has no host mount, so a read is bounded to the sidecar
FS regardless.
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
_WORKROOT = "/tmp/harvis-chat"
_MAX_BYTES = 2_000_000

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
    """The per-user (optionally per-run) sandbox dir inside the sidecar."""
    base = f"{_WORKROOT}/u{int(user_id)}"
    return f"{base}/{run_id}" if run_id else base


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


async def mkdir_workdir(user_id, run_id: str) -> Optional[str]:
    """Create + return the per-run sandbox dir. None on failure (caller falls back to /tmp)."""
    wd = chat_workdir(user_id, run_id)
    rc, _out, _err = await _dexec("mkdir", "-p", wd)
    return wd if rc == 0 else None


async def list_new_files(user_id, run_id: str) -> list[str]:
    """Renderable files this run produced (full container paths) — for the preview footer."""
    wd = chat_workdir(user_id, run_id)
    rc, out, _err = await _dexec("find", wd, "-maxdepth", "4", "-type", "f")
    if rc != 0:
        return []
    files = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
    return [f for f in files if os.path.splitext(f)[1].lower() in _ALLOWED_EXT][:12]


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
