"""Page images and text for an office file, from the document sandbox's /render, and a workbook with its
formulas calculated, from its /recalc."""
import base64
import hashlib
import json
import logging
import os
import io
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import OrderedDict
from typing import Any, Dict, Optional

DEFAULT_URL = "http://sandbox:8080"
# Server side of /render: up to 30 s queued for the one job slot (SLOT_WAIT_S), 90 s of
# LibreOffice, 60 s of drawing pages, plus a margin. A shorter limit would give up on a
# render the sandbox is still doing.
TIMEOUT_S = 30 + 90 + 60 + 20
FORMATS = ("pptx", "docx", "xlsx", "pdf")
BUSY = "the document sandbox is busy or took too long to answer; try again shortly"


log = logging.getLogger(__name__)


class RenderUnavailable(Exception):
    """The sandbox could not produce page images; the message is fit to show a user. ``code`` is the HTTP
    status the sandbox answered with, when it answered."""
    code: Optional[int] = None


def _unavailable(message: str, code: Optional[int] = None) -> RenderUnavailable:
    err = RenderUnavailable(message)
    err.code = code
    return err


def _send(url: str, path: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(f"{url}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise _unavailable(BUSY, 429) from None
        raise _unavailable(f"the document sandbox refused the render (HTTP {exc.code})", exc.code) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise _unavailable(BUSY) from None
        raise _unavailable("the document sandbox is not running") from None


def _post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _send(url, "/render", payload, TIMEOUT_S)


async def render_pages(data: bytes, ext: str, max_pages: int = 20) -> dict:
    """{ok, pages: [{png_b64, width, height, text}], page_count} for pptx, docx, xlsx or pdf bytes."""
    ext = (ext or "").lower().lstrip(".")
    if ext not in FORMATS:
        raise RenderUnavailable(f"cannot render a .{ext} file")
    url = (os.environ.get("CODE_EXECUTOR_URL") or DEFAULT_URL).rstrip("/")
    payload = {"b64": base64.b64encode(data).decode(), "ext": ext, "max_pages": max_pages}
    from . import docs_limits               # not at the top: tests load this file on its own, outside the package
    try:
        reply = await docs_limits.RENDERS.run(_post, url, payload)
    except docs_limits.Busy:
        raise RenderUnavailable(BUSY) from None
    if not reply.get("ok"):
        raise RenderUnavailable(reply.get("error") or "the document sandbox could not render the file")
    return reply


# ---- /recalc: the same workbook with every formula calculated and its value saved --------------------------

# An export waits for this inline (it runs on a build thread with a 60 s limit), so it gives up well before
# that; the sandbox may carry on and finish, which only costs it the work.
RECALC_TIMEOUT_S = 25
RECALC_RETRY_S = 30             # after a failure to reach the sandbox, do not try again for this long
RECALC_MISSING_S = 300          # after a 404: an older sandbox image without /recalc; it needs a rebuild
_CACHE_ENTRIES = 8
_BAD_ENTRIES = 64
_MAX_CACHED_BYTES = 8 * 1024 * 1024
_lock = threading.Lock()
_cache: "OrderedDict[str, bytes]" = OrderedDict()     # sha256 of the workbook sent -> the recalculated bytes
_bad: "OrderedDict[str, None]" = OrderedDict()        # workbooks the sandbox answered "no" for; not asked twice
_skip_until = 0.0
_VOLATILE = ("docProps/core.xml", "docProps/app.xml")   # openpyxl stamps the save time into these on every export


def _content_key(data: bytes) -> str:
    """Identifies a workbook by what it holds, not by when it was saved: two exports of an unchanged sheet differ
    only in the timestamp openpyxl writes into docProps/core.xml, and hashing the raw bytes would make every
    export look new. Falls back to the raw bytes for anything that is not a readable zip."""
    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in sorted(z.namelist()):
                if name not in _VOLATILE:
                    digest.update(hashlib.sha256(name.encode()).digest() + hashlib.sha256(z.read(name)).digest())
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError):
        digest = hashlib.sha256(data)
    return digest.hexdigest()


_VOLATILE_CALL = re.compile(rb"<f[ >][^<]*?\b(?:TODAY|NOW)\s*\(", re.I)


def _uses_volatile(data: bytes) -> bool:
    """True when a formula calls TODAY or NOW: its value is the moment of the recalculation, so a kept copy goes stale."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return any(_VOLATILE_CALL.search(z.read(n)) for n in z.namelist() if n.startswith("xl/worksheets/"))
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, EOFError):
        return False


def recalc_xlsx(data: bytes) -> Optional[bytes]:
    """``data`` with every formula calculated, from the sandbox's /recalc; None when that is not possible.

    Never raises: a sandbox that is down, busy, slow, too old to have /recalc (404) or unable to open the file
    all give None, and the caller keeps the bytes it has. Results are kept by content hash, and a failure to
    reach the sandbox is remembered for a while so a dead sandbox costs one attempt, not one per export."""
    global _skip_until
    key = _content_key(data)
    volatile = _uses_volatile(data)                  # recalculated every time, never served from or kept in the cache
    with _lock:
        if key in _cache and not volatile:
            _cache.move_to_end(key)
            return _cache[key]
        if key in _bad or time.monotonic() < _skip_until:
            return None
    url = (os.environ.get("CODE_EXECUTOR_URL") or DEFAULT_URL).rstrip("/")
    try:
        reply = _send(url, "/recalc", {"b64": base64.b64encode(data).decode()}, RECALC_TIMEOUT_S)
    except RenderUnavailable as exc:
        with _lock:
            _skip_until = time.monotonic() + (RECALC_MISSING_S if exc.code == 404 else RECALC_RETRY_S)
        log.info("xlsx recalculation skipped: %s", exc)
        return None
    try:
        out = base64.b64decode(str(reply.get("b64") or ""), validate=True) if reply.get("ok") else b""
    except ValueError:
        out = b""
    with _lock:
        if not out.startswith(b"PK"):
            _bad[key] = None
            while len(_bad) > _BAD_ENTRIES:
                _bad.popitem(last=False)
            log.info("xlsx recalculation refused: %s", reply.get("error") or "no workbook returned")
            return None
        if len(out) <= _MAX_CACHED_BYTES and not volatile:
            _cache[key] = out
            while len(_cache) > _CACHE_ENTRIES:
                _cache.popitem(last=False)
    return out
