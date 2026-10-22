"""Page images and text for an office file, from the document sandbox's /render."""
import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

DEFAULT_URL = "http://sandbox:8080"
# Server side of /render: up to 30 s queued for the one job slot (SLOT_WAIT_S), 90 s of
# LibreOffice, 60 s of drawing pages, plus a margin. A shorter limit would give up on a
# render the sandbox is still doing.
TIMEOUT_S = 30 + 90 + 60 + 20
FORMATS = ("pptx", "docx", "xlsx", "pdf")
BUSY = "the document sandbox is busy or took too long to answer; try again shortly"


class RenderUnavailable(Exception):
    """The sandbox could not produce page images; the message is fit to show a user."""


def _post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(f"{url}/render", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RenderUnavailable(BUSY) from None
        raise RenderUnavailable(f"the document sandbox refused the render (HTTP {exc.code})") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise RenderUnavailable(BUSY) from None
        raise RenderUnavailable("the document sandbox is not running") from None


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
