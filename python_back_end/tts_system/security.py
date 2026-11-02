"""Guards for the TTS service, which publishes a port and trusts its callers.

``safe_child`` keeps a client-supplied voice id or slug inside its library folder
(``DELETE /voices/..`` used to remove the folder above it). ``require_internal_token``
protects the calls that bring model files in: an imported ``.pth`` is a pickle, so who
may upload one is a code-execution question. The token is TTS_INTERNAL_TOKEN, else the
shared HARVIS_GATEWAY_TOKEN; with neither set the import calls refuse everyone.
"""
from __future__ import annotations

import hmac
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def safe_child(root: Path, name: str) -> Path:
    """``root / name`` for a plain folder name; ValueError for anything that could leave ``root``."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or ".." in name:
        raise ValueError("invalid name")
    child = Path(root) / name
    if child.resolve().parent != Path(root).resolve():
        raise ValueError("invalid name")
    return child


def safe_child_or_404(root: Path, name: str, what: str = "Voice") -> Path:
    try:
        return safe_child(root, name)
    except ValueError:
        raise HTTPException(404, f"{what} not found") from None


def _expected_token() -> str:
    return os.getenv("TTS_INTERNAL_TOKEN") or os.getenv("HARVIS_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_TOKEN") or ""


async def require_internal_token(
    authorization: Optional[str] = Header(None),
    x_internal_token: Optional[str] = Header(None),
) -> None:
    expected = _expected_token()
    supplied = x_internal_token or (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(403, "Voice model import is limited to the Harvis backend")
