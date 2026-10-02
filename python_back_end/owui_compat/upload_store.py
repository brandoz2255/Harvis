"""Size-capped, streamed writes for the OWUI-compat upload route.

nginx's ``client_max_body_size 50m`` used to be the only guard: the backend read
every upload into memory whole, and the laptop's directly exposed port 8000 had
no limit at all. The cap here is the application's own and must agree with
nginx — HARVIS_MAX_UPLOAD_MB defaults to the same 50.
"""

from __future__ import annotations

import os
import re

_CHUNK = 1 << 20
DEFAULT_MAX_UPLOAD_MB = 50


class UploadTooLarge(Exception):
    def __init__(self, limit_bytes: int):
        self.limit_bytes = limit_bytes
        super().__init__(f"upload exceeds {limit_bytes // (1024 * 1024)} MB")

    @property
    def message(self) -> str:
        mb = self.limit_bytes // (1024 * 1024)
        return (f"File too large: uploads are limited to {mb} MB on this server "
                "(HARVIS_MAX_UPLOAD_MB). Attach a smaller file or a CSV export.")


_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def disk_suffix(filename: str | None) -> str:
    """The extension the stored file keeps on disk: short and alphanumeric, or
    none. The name is client-chosen; a NUL or a 300-character "extension" used
    to fail the write with a 500."""
    _, ext = os.path.splitext(filename or "")
    return ext.lower() if _SAFE_SUFFIX.fullmatch(ext) else ""


def display_name(filename: str | None, fallback: str) -> str:
    """The name shown in chat: control characters (Postgres rejects NUL) removed,
    at most 255 characters."""
    name = _CONTROL.sub("", filename or "").strip()[:255]
    return name or fallback


def max_upload_bytes() -> int:
    raw = os.getenv("HARVIS_MAX_UPLOAD_MB", "").strip()
    try:
        mb = int(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        mb = DEFAULT_MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


def content_length_exceeds(headers, limit_bytes: int) -> bool:
    """Cheap pre-check on the request's Content-Length (multipart framing adds a
    little, so only a clearly oversized body is rejected before reading)."""
    try:
        declared = int(headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return False
    return declared > limit_bytes + _CHUNK


async def save_upload(file, dest_path: str, limit_bytes: int) -> int:
    """Stream ``file`` (a Starlette UploadFile) to ``dest_path`` in 1 MiB chunks.

    Returns the byte count. Past the limit the partial file is removed and
    UploadTooLarge is raised, so nothing half-written is left on disk.
    """
    written = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit_bytes:
                    raise UploadTooLarge(limit_bytes)
                out.write(chunk)
    except BaseException:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise
    return written
