"""Rendered page images of an exported document, kept briefly in memory.

POST /harvis/docs/preview exports the document, has the sandbox draw its pages, and
caches the result here. The page PNGs are fetched one by one by URL, and /check reads
the same entry for its page text, so a preview followed by a check renders once.

The cache is per process and bounded: ~64 MB of pages across all users, ~10 minutes
from the last time an entry was asked for. Every entry records who made it, and a
fetch by anyone else is a miss, so one user cannot read another's pages by key.
"""
from __future__ import annotations

import base64
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

from .docs_export import FORMATS
from .docs_parse import parse_harvis_doc
from .docs_render_client import FORMATS as RENDERABLE
from .docs_render_client import RenderUnavailable, render_pages  # noqa: F401 - the route and the tests patch it here

MAX_PAGES = 20
CACHE_BYTES = 64 * 1024 * 1024
TTL_S = 600
URL_PREFIX = "/hermes-api/api/harvis/docs/preview"

_now = time.monotonic                                   # tests move the clock by replacing this


@dataclass
class Rendered:
    owner: str
    fmt: str
    page_count: int
    pages: list[dict] = field(default_factory=list)     # {png: bytes, width, height, text}
    expires: float = 0.0

    @property
    def size(self) -> int:
        return sum(len(p["png"]) + len(p["text"]) for p in self.pages)

    def listing(self, key: str) -> dict:
        return {"format": self.fmt, "page_count": self.page_count,
                "pages": [{"index": i, "width": p["width"], "height": p["height"],
                           "url": f"{URL_PREFIX}/{key}/{i}.png"} for i, p in enumerate(self.pages)]}


class PreviewCache:
    def __init__(self, cap_bytes: int = CACHE_BYTES, ttl_s: float = TTL_S) -> None:
        self.cap_bytes, self.ttl_s = cap_bytes, ttl_s
        self._items: "OrderedDict[str, Rendered]" = OrderedDict()
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = _now()
        for key in [k for k, v in self._items.items() if v.expires <= now]:
            del self._items[key]

    def get(self, key: str, owner: str) -> Optional[Rendered]:
        """The entry for ``key`` if it is this owner's and still fresh; asking renews it."""
        with self._lock:
            self._purge()
            item = self._items.get(key)
            if item is None or item.owner != owner:
                return None
            item.expires = _now() + self.ttl_s
            self._items.move_to_end(key)
            return item

    def put(self, key: str, item: Rendered) -> Rendered:
        with self._lock:
            # One document bigger than the whole cache keeps the pages that fit rather than evicting itself.
            while item.size > self.cap_bytes and len(item.pages) > 1:
                item.pages.pop()
            item.expires = _now() + self.ttl_s
            self._items[key] = item
            self._items.move_to_end(key)
            self._purge()
            while sum(v.size for v in self._items.values()) > self.cap_bytes and len(self._items) > 1:
                self._items.popitem(last=False)
            return item

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


cache = PreviewCache()


def user_key(user: Any) -> str:
    """A stable id for the signed-in user (the auth dependency returns a dict)."""
    if isinstance(user, dict):
        for name in ("id", "user_id", "email", "username"):
            if user.get(name) is not None:
                return str(user[name])
    return str(user)


def cache_key(owner: str, fmt: str, source: str, title: Optional[str], max_pages: int) -> str:
    h = hashlib.sha256()
    for part in (owner, fmt, title or "", str(max_pages), source):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def primary_format(source: str) -> str:
    """The file a document of this kind is normally downloaded as: deck pptx, doc docx, pdf pdf, sheet xlsx."""
    return FORMATS[parse_harvis_doc(source).kind][0]


def renderable(fmt: str) -> bool:
    return fmt in RENDERABLE


async def render_entry(owner: str, fmt: str, data: bytes, max_pages: int) -> Rendered:
    """Ask the sandbox for the pages of ``data``. Raises RenderUnavailable."""
    reply = await render_pages(data, fmt, max_pages)
    pages = []
    for p in reply.get("pages") or []:
        try:
            png = base64.b64decode(p.get("png_b64") or "", validate=False)
        except ValueError:
            continue
        if png:
            pages.append({"png": png, "width": int(p.get("width") or 0), "height": int(p.get("height") or 0),
                          "text": str(p.get("text") or "")})
    if not pages:
        raise RenderUnavailable("the document sandbox returned no pages")
    return Rendered(owner, fmt, int(reply.get("page_count") or len(pages)), pages)
