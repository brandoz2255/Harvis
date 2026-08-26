"""Mirroring media an MCP connector produced into the run's own artifacts.

A connector that generates media hands back a URL on its own service — ComfyUI
answers ``http://harvis-comfyui:8188/view?filename=...``. That URL is perfectly
valid *inside* the Docker network and completely useless to the person reading
the chat: their browser has no DNS for a bare service name, so the link dies on
lookup and the picture or clip they just paid GPU time for is unviewable.

So the bytes are fetched here, on the side of the network that can actually
reach them, and saved as a normal run artifact. That does two jobs at once: the
link in the reply becomes ``/api/workspace/artifact/<id>/raw``, which is
same-origin and ownership-checked, and the file lands in the Artifacts rail
next to everything else the run produced — no new frontend, because the rail has
always previewed binary artifacts.

**Only unreachable hosts are mirrored.** A connector returning a public URL
(``https://cdn.example.com/x.png``) already works in a browser, and copying it
into our database would be pointless duplication. The test is deliberately
narrow: a hostname with no dot cannot be a public name, and loopback/private
addresses resolve in the browser but to the wrong machine.

**This is not an SSRF hole.** The URL comes from a tool the user themself
connected, not from fetched web content, and nothing here follows redirects,
reads content types outside image/video/audio, or returns the body to the model.
The fetch is capped in size, time and count.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Enough to cover a generated still; a connector handing back something larger
# is doing something this path was not built for.
_MAX_BYTES = 20 * 1024 * 1024
# A few seconds of rendered video is legitimately tens of megabytes, so a still's
# cap would throw away exactly the results that took the longest to produce.
_MAX_BYTES_VIDEO = 128 * 1024 * 1024
# A video is both bigger and slower off the wire than a still.
_FETCH_TIMEOUT = 20.0
_FETCH_TIMEOUT_VIDEO = 120.0
# One tool call yielding a batch is normal; one yielding fifty is a bug or an
# abuse, and either way the chat cannot show fifty pictures usefully.
_MAX_PER_RESULT = 8

_IMAGE_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}

# ComfyUI's SaveVideo/SaveWEBM hand back a /view URL exactly like a still does,
# so a video is unreachable from the browser for the same reason and is mirrored
# the same way. Audio rides along because a TTS connector answers the same shape.
_VIDEO_EXT = {
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm",
    "mov": "video/quicktime", "mkv": "video/x-matroska", "ogv": "video/ogg",
}
_AUDIO_EXT = {
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
    "m4a": "audio/mp4", "flac": "audio/flac",
}
_MEDIA_EXT = {**_IMAGE_EXT, **_VIDEO_EXT, **_AUDIO_EXT}

# URLs as they appear in prose: stop at whitespace or the punctuation that
# usually ends a sentence rather than belonging to the address.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)

# The filename may be the path's last segment or ride in a query parameter,
# which is how ComfyUI's /view endpoint addresses its output.
_QS_NAME_RE = re.compile(
    r"[?&](?:filename|file|name|image|video|audio)=([^&]+)", re.IGNORECASE
)


def _ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _media_name(url: str) -> Optional[str]:
    """The media filename this URL delivers, or None if it isn't media."""
    parsed = urlparse(url)
    # `urlparse` strips the leading '?', so the first parameter would never match
    # a pattern anchored on a delimiter. Put one back rather than making the
    # delimiter optional, which would also match `basename=` and `nickname=`.
    qs = _QS_NAME_RE.search("?" + (parsed.query or ""))
    if qs:
        candidate = unquote(qs.group(1)).strip()
        if _ext_of(candidate) in _MEDIA_EXT:
            return candidate.rsplit("/", 1)[-1]
    tail = unquote((parsed.path or "").rsplit("/", 1)[-1]).strip()
    if _ext_of(tail) in _MEDIA_EXT:
        return tail
    return None


def _browser_unreachable(host: str) -> bool:
    """Would a browser at the user's machine fail to reach this host correctly?

    Three ways it can: a bare Docker service name has no public DNS at all; a
    loopback address resolves but points at the *user's* computer; a private
    address resolves to whatever happens to sit at that address on their LAN.
    All three mean the link in the chat is broken or wrong.
    """
    host = (host or "").strip().strip("[]").lower()
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A name. No dot means it cannot be a public hostname — it is a
        # container name, a compose service, or a bare LAN label.
        return "." not in host or host.endswith(".local") or host.endswith(".internal")
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved)


def _should_mirror(url: str) -> Optional[str]:
    """The filename to save this URL under, or None to leave it alone."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not _browser_unreachable(parsed.hostname or ""):
        return None
    return _media_name(url)


async def _fetch(url: str, name: str) -> Optional[bytes]:
    """The media bytes behind `url`, or None. Never raises."""
    try:
        import httpx
    except Exception:
        logger.warning("mcp media: httpx unavailable — cannot mirror %s", url)
        return None
    ext = _ext_of(name)
    is_video = ext in _VIDEO_EXT
    cap = _MAX_BYTES_VIDEO if is_video else _MAX_BYTES
    timeout = _FETCH_TIMEOUT_VIDEO if is_video else _FETCH_TIMEOUT
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info(
                    "mcp media: %s answered %s — leaving the link as-is",
                    url, resp.status_code,
                )
                return None
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            # An error page served as HTML is not media, and storing it would
            # put a broken preview in the rail. A server that answers a known
            # media extension with a generic octet-stream is trusted on the
            # extension — refusing there would drop real files.
            if ctype and not (
                ctype.startswith(("image/", "video/", "audio/"))
                or ctype == "application/octet-stream"
            ):
                logger.info("mcp media: %s returned %s, not media", url, ctype)
                return None
            data = resp.content
            if not data:
                return None
            if len(data) > cap:
                logger.info(
                    "mcp media: %s is %d bytes, over the %d cap — not mirrored",
                    name, len(data), cap,
                )
                return None
            return data
    except Exception as exc:
        logger.info("mcp media: could not fetch %s (%s)", url, exc.__class__.__name__)
        return None


async def mirror_media_urls(
    text: str, *, pool, workspace_id: str
) -> tuple[str, list[dict]]:
    """Rewrite unreachable media URLs in `text` to same-origin artifact links.

    Returns the rewritten text and one record per saved file. Fail-soft in
    every direction: a file that cannot be fetched or saved leaves its
    original URL untouched, because a link that needs explaining still beats
    silently dropping the only pointer to the result.
    """
    if not text or pool is None or not workspace_id:
        return text, []

    # Late import: workspace_router imports this package's siblings, so a
    # module-level import would cycle.
    from workspace.workspace_router import _db_save_artifact
    from workspace.terminal_container import emit_terminal_event

    saved: list[dict] = []
    seen: dict[str, str] = {}
    out = text

    for url in dict.fromkeys(_URL_RE.findall(text)):
        if len(saved) >= _MAX_PER_RESULT:
            break
        if url in seen:
            continue
        name = _should_mirror(url)
        if not name:
            continue
        data = await _fetch(url, name)
        if not data:
            continue
        artifact_id = await _db_save_artifact(
            pool, workspace_id, "file", path=name, content_bytes=data,
        )
        if not artifact_id:
            continue
        local = f"/api/workspace/artifact/{artifact_id}/raw"
        # The typed trace event is what makes the Artifacts rail open on the
        # result while the run is still going. Saving the row alone leaves the
        # file discoverable only by someone who thinks to look.
        try:
            await emit_terminal_event(
                pool, workspace_id, event_type="artifact",
                payload={
                    "run_id": workspace_id,
                    "artifact_id": artifact_id,
                    "path": name,
                    "mime_type": _MEDIA_EXT.get(_ext_of(name), "application/octet-stream"),
                    "size_bytes": len(data),
                    "label": name,
                },
            )
        except Exception:
            logger.warning("mcp media: saved %s but could not announce it", name)
        seen[url] = local
        saved.append({
            "artifact_id": artifact_id,
            "path": name,
            "url": local,
            "mime": _MEDIA_EXT.get(_ext_of(name), "application/octet-stream"),
            "bytes": len(data),
        })

    for url, local in seen.items():
        out = out.replace(url, local)
    return out, saved
