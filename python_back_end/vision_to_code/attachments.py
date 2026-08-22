"""Turn user attachments into real multimodal image parts.

Before this module, an uploaded screenshot reached the model as a *line of text*
("1. shot.png — image/png — file_id=..."). A model with eyes never got to use
them: it was told an image existed and left to guess. This resolves the bytes and
builds the OpenAI-style content parts the chat APIs actually accept:

    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}

Same shape as ``tools/openclaw_proxy.py`` vision-query and the Kimi chat path, so
model_proxy's existing list-of-parts handling covers it with no changes.

Byte resolution is deliberately narrow. ``file_id`` reads the sidecar metadata
written by ``POST /api/uploads``; ``path`` must resolve inside IMAGES_DIR; ``url``
accepts inline ``data:`` URIs and, because the Discord bot is a real producer of
attachments, Discord's own CDN — nothing else. An arbitrary URL here would make
this an SSRF primitive reachable from any chat message.

Every attachment that cannot be turned into an image part yields a human-readable
skip reason instead of vanishing. Silent skipping is how "the model ignored my
screenshot" becomes indistinguishable from "the model never received it".
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Same default as main.py:IMAGES_DIR — read at call time so tests can point it away.
def _images_dir() -> str:
    return os.getenv("IMAGES_DIR", "/app/images")


# Harvis has TWO upload stores and an attachment can come from either. `POST /api/uploads`
# writes IMAGES_DIR with a `.meta.json` sidecar; the chat/Build composer uploads through the
# OWUI-compat `POST /api/v1/files/`, which writes OWUI_FILES_DIR as `<uuid><ext>` and keeps
# the authoritative row in Postgres. Knowing only the first is why a Build attachment
# resolved to "no longer on disk" while its bytes sat in the other directory.
def _owui_files_dir() -> str:
    return os.getenv("OWUI_FILES_DIR", "/app/owui_files")


_FILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


# ── Ownership ────────────────────────────────────────────────────────────────
# A file id is picked by the client and proves nothing. Until Gate 8A this module
# resolved one straight to bytes, so any signed-in user could name someone else's
# upload and have Harvis read it out — as staged files to a CLI agent, or as an
# image part in their own conversation. Both stores are now checked against the
# caller's own id, and a caller that cannot name an owner gets nothing.
#
# The two stores prove ownership differently. IMAGES_DIR keeps a `.meta.json`
# sidecar that already records `user_id` (main.py's upload handler writes it), so
# that half needs no database. OWUI_FILES_DIR keeps only `<uuid><ext>` on disk and
# the authoritative row in Postgres, which this module deliberately cannot reach —
# see the note on `_owui_files_dir`. Rather than give it a pool, the app hands it a
# lookup at startup. With no lookup registered, the OWUI store is unreadable rather
# than unchecked: refusing a real attachment is a bug report, silently serving
# another user's file is a breach.
_OwnerLookup = Any  # async (file_id: str) -> int | None

_owui_owner_lookup: Optional[_OwnerLookup] = None


def set_owui_owner_lookup(fn: Optional[_OwnerLookup]) -> None:
    """Register how to ask Postgres who owns an OWUI-compat upload.

    Called once from the app's startup with a coroutine that reads
    ``owui_files.user_id``. Passing ``None`` unregisters it, which is what tests
    that must not touch a database do — and which correctly makes every OWUI-store
    attachment refuse rather than resolve.
    """
    global _owui_owner_lookup
    _owui_owner_lookup = fn


async def _owui_owner_of(file_id: str) -> tuple[Optional[int], Optional[str]]:
    """(owner_id, error). No lookup registered is an error, never an allow."""
    if _owui_owner_lookup is None:
        return None, ("this upload cannot be verified as yours on this deployment "
                      "(no file-ownership lookup is configured)")
    try:
        owner = await _owui_owner_lookup(file_id)
    except Exception as exc:
        logger.warning("attachments: owner lookup failed for %s: %s", file_id, exc)
        return None, "could not confirm who owns this upload"
    if owner is None:
        return None, f"upload {file_id} is no longer on disk"
    return int(owner), None


# Hosts we will fetch an attachment from. Discord attachment URLs are the only
# remote location Harvis itself produces (integrations/discord_workspace_bot.py);
# the web composer sends a relative `/api/v1/files/<id>/content` path plus a
# `file_id`, which resolves through the owned store above and never over HTTP.
# Public because workspace_router's text-inlining path must fetch from exactly
# the same set — one allowlist, not two that drift.
REMOTE_ATTACHMENT_HOSTS = frozenset({
    "cdn.discordapp.com",
    "media.discordapp.net",
})

_REMOTE_HOSTS = REMOTE_ATTACHMENT_HOSTS

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

# Cap what we will pull over the wire before resizing. A 20 MB PNG is already
# far past anything a screenshot needs.
_MAX_FETCH_BYTES = 20 * 1024 * 1024

DEFAULT_MAX_IMAGES = 4
DEFAULT_MAX_PX = 1024


def is_image_attachment(att: dict) -> bool:
    """True when this attachment looks like an image by MIME or by extension."""
    if not isinstance(att, dict):
        return False
    mime = str(att.get("mime_type") or "").lower()
    if mime.startswith("image/"):
        return True
    name = str(att.get("name") or att.get("filename") or "")
    loc = str(att.get("path") or att.get("url") or "")
    for candidate in (name, urlparse(loc).path if loc else ""):
        if candidate and os.path.splitext(candidate)[1].lower() in _IMAGE_EXTS:
            return True
    return False


def _label(att: dict, index: int) -> str:
    return str(att.get("name") or att.get("filename") or f"attachment {index}")


def _read_local(path: str) -> Optional[bytes]:
    with open(path, "rb") as fh:
        return fh.read()


def _owui_stored_file(file_id: str) -> Optional[str]:
    """The path of an OWUI-compat upload, or None.

    The row in ``owui_files`` is authoritative, but this module has no DB pool, and the
    filename is fully determined by the id: ``<file_id><ext>``. So match on the id and
    confirm the result is a direct child of OWUI_FILES_DIR. The id is validated first —
    it arrives from the client, and an unchecked one would be a traversal primitive.
    """
    if not _FILE_ID_RE.match(file_id or "") or os.sep in file_id or "/" in file_id:
        return None
    base = os.path.realpath(_owui_files_dir())
    try:
        names = os.listdir(base)
    except Exception:
        return None
    for name in sorted(names):
        stem, _ = os.path.splitext(name)
        if stem != file_id and name != file_id:
            continue
        real = os.path.realpath(os.path.join(base, name))
        if real.startswith(base + os.sep) and os.path.isfile(real):
            return real
    return None


async def _resolve_file_id(
    file_id: str, owner_id: Optional[int]
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(stored_path, mime_type, error) for an upload the caller owns.

    ``owner_id`` is the authenticated user the request is running as, not anything
    the client sent alongside the file id. Without one there is nobody to compare
    against, so nothing resolves.

    A file owned by someone else reports the same "no longer on disk" as a file id
    that was never real. That is deliberate: a distinct "not yours" would turn this
    into an oracle for which ids exist.
    """
    gone = f"upload {file_id} is no longer on disk"
    if owner_id is None:
        return None, None, "attachments can only be read for a signed-in user"

    base = _images_dir()
    meta_path = os.path.join(base, f"{file_id}.meta.json")
    if not os.path.exists(meta_path):
        owner, error = await _owui_owner_of(file_id)
        if owner is None:
            return None, None, error or gone
        if owner != int(owner_id):
            return None, None, gone
        owui = _owui_stored_file(file_id)
        if owui:
            return owui, _guess_mime(owui, ""), None
        return None, None, gone
    try:
        with open(meta_path) as fh:
            meta = json.load(fh)
    except Exception as exc:
        return None, None, f"upload metadata unreadable ({exc})"
    # A sidecar written before `user_id` was recorded has no owner to match, and an
    # unownable file is not a public one.
    meta_owner = meta.get("user_id")
    if meta_owner is None or int(meta_owner) != int(owner_id):
        return None, None, gone
    stored = str(meta.get("stored_path") or "")
    if not stored or not os.path.exists(stored):
        return None, None, f"upload {file_id} metadata points at a missing file"
    return stored, str(meta.get("mime_type") or ""), None


def _resolve_path(path: str) -> tuple[Optional[str], Optional[str]]:
    """(safe_path, error). A path must land inside IMAGES_DIR — no traversal out."""
    base = os.path.realpath(_images_dir())
    real = os.path.realpath(path if os.path.isabs(path) else os.path.join(base, path))
    if real != base and not real.startswith(base + os.sep):
        return None, "path is outside the uploads directory"
    if not os.path.exists(real):
        return None, "file no longer exists on disk"
    return real, None


async def _fetch_remote(url: str) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """(data, mime, error) for an allowlisted remote image URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, None, f"unsupported URL scheme {parsed.scheme!r}"
    host = (parsed.hostname or "").lower()
    if host not in _REMOTE_HOSTS:
        return None, None, (
            f"images are not fetched from {host or 'that host'} — upload the file "
            "instead of linking it"
        )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
    except Exception as exc:
        return None, None, f"download failed ({exc})"
    if len(data) > _MAX_FETCH_BYTES:
        return None, None, f"image is {len(data) // (1024 * 1024)} MB, over the 20 MB limit"
    return data, resp.headers.get("content-type", "").split(";")[0].strip() or None, None


def _shrink(data: bytes, mime: str, max_px: int) -> tuple[bytes, str]:
    """Cap the longest side at max_px. Returns the original on any failure.

    Mirrors the resize in tools/openclaw_proxy.py — a full-resolution screenshot
    blows past provider image limits and costs tokens for detail no model uses.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if max(img.size) <= max_px:
            return data, mime
        img.thumbnail((max_px, max_px), Image.LANCZOS)
        fmt = "JPEG" if mime == "image/jpeg" else "PNG"
        if fmt == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue(), f"image/{fmt.lower()}"
    except Exception as exc:
        logger.warning("vision attachment resize failed, sending original: %s", exc)
        return data, mime


def _guess_mime(name: str, fallback: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext in _IMAGE_EXTS:
        return f"image/{ext.lstrip('.')}"
    return fallback or "image/png"


async def resolve_attachment_bytes(
    att: dict, index: int = 1, *, owner_id: Optional[int] = None
) -> tuple[Optional[bytes], str, Optional[str]]:
    """(data, mime, error) for one attachment, by the narrow rules this module allows.

    ``data:`` URI → inline; ``file_id`` → an upload ``owner_id`` owns; ``path`` →
    inside IMAGES_DIR only; ``url`` → the Discord CDN allowlist only. Anything else
    is an error string, never a silent empty result.

    ``owner_id`` is keyword-only and defaults to ``None`` so that a caller which
    forgets it fails closed on every stored upload instead of inheriting whatever
    the previous positional argument happened to be.
    """
    name = _label(att, index)
    mime = str(att.get("mime_type") or "")
    url = str(att.get("url") or "")

    if url.startswith("data:"):
        try:
            header, _, payload = url.partition(",")
            return base64.b64decode(payload), (header[5:].split(";")[0] or mime), None
        except Exception as exc:
            return None, mime, f"inline image data was unreadable ({exc})"

    if att.get("file_id"):
        stored, meta_mime, error = await _resolve_file_id(str(att["file_id"]), owner_id)
        if not stored:
            return None, mime, error
        try:
            return await asyncio.to_thread(_read_local, stored), (mime or meta_mime or ""), None
        except Exception as exc:
            return None, mime, f"could not read the stored upload ({exc})"

    if att.get("path"):
        safe, error = _resolve_path(str(att["path"]))
        if not safe:
            return None, mime, error
        try:
            return await asyncio.to_thread(_read_local, safe), mime, None
        except Exception as exc:
            return None, mime, f"could not read the file ({exc})"

    if url:
        data, remote_mime, error = await _fetch_remote(url)
        return data, (mime or remote_mime or ""), error

    return None, mime, "no file location was recorded for it"


# ── Staging attachments on disk (for engines that read files, not image parts) ──
# The CLI engines (Claude Code, Kimi Code, Codex, OpenCode, Hermes) drive their own
# tool loop inside a sidecar container. They cannot be handed a multimodal part and
# they cannot reach the Harvis API — the sidecars mount /data/artifacts and nothing
# else. So the bytes have to BE THERE, on the working tree, before the CLI starts.

STAGE_DIRNAME = "harvis-attachments"

DEFAULT_MAX_STAGED = 8
DEFAULT_MAX_STAGED_BYTES = 25 * 1024 * 1024

_SAFE_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)


def _safe_filename(name: str, index: int) -> str:
    """A basename that can only land inside the staging dir. No traversal, no
    separators, no leading dot (a dotfile is invisible to a `ls` the agent runs)."""
    base = os.path.basename(str(name or "").strip().replace("\\", "/"))
    cleaned = "".join(c for c in base if c in _SAFE_NAME_CHARS).strip().replace(" ", "_")
    cleaned = cleaned.lstrip(".")
    if not cleaned or cleaned in (".", ".."):
        cleaned = f"attachment-{index}"
    return cleaned[:120]


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


async def materialize_attachments(
    attachments: list[dict] | None,
    dest_dir: str,
    *,
    owner_id: Optional[int] = None,
    subdir: str = STAGE_DIRNAME,
    max_files: int = DEFAULT_MAX_STAGED,
    max_bytes: int = DEFAULT_MAX_STAGED_BYTES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Write the user's attachments into ``dest_dir/subdir`` as real files.

    Returns ``(staged, skipped)``. Each staged entry carries ``name``, ``path``
    (absolute), ``rel`` (relative to ``dest_dir``), ``mime_type``, ``size`` and
    ``is_image``. ``skipped`` holds one plain-English line per attachment that
    could NOT be staged — callers must surface it, because a file the agent never
    received must not read as a file it chose to ignore.

    ``owner_id`` is the user the run belongs to. It matters more here than anywhere
    else in this module: staged files land on a working tree a CLI agent then reads
    at will, so an unowned upload would be handed over wholesale.
    """
    staged: list[dict[str, Any]] = []
    skipped: list[str] = []
    if not attachments or not dest_dir:
        return staged, skipped

    stage_dir = os.path.join(dest_dir, subdir)
    try:
        await asyncio.to_thread(os.makedirs, stage_dir, 0o755, True)
    except Exception as exc:
        return staged, [f"could not create the attachment folder ({exc})"]

    items = list(attachments)
    if len(items) > max_files:
        skipped.append(f"only the first {max_files} of {len(items)} attachments were staged")
        items = items[:max_files]

    used: set[str] = set()
    for index, att in enumerate(items, start=1):
        if not isinstance(att, dict):
            continue
        name = _label(att, index)
        data, mime, error = await resolve_attachment_bytes(att, index, owner_id=owner_id)
        if data is None:
            skipped.append(f"{name}: {error or 'could not be loaded'}")
            continue
        if len(data) > max_bytes:
            skipped.append(f"{name}: {len(data) // (1024 * 1024)} MB is over the {max_bytes // (1024 * 1024)} MB staging limit")
            continue

        fname = _safe_filename(name, index)
        if fname in used:  # two uploads with the same name must not clobber each other
            stem, ext = os.path.splitext(fname)
            fname = f"{stem}-{index}{ext}"
        used.add(fname)

        target = os.path.join(stage_dir, fname)
        try:
            await asyncio.to_thread(_write_file, target, data)
        except Exception as exc:
            skipped.append(f"{name}: could not be written to the workspace ({exc})")
            continue

        staged.append({
            "name": name,
            "path": target,
            "rel": os.path.join(subdir, fname),
            "mime_type": _guess_mime(name, mime) if is_image_attachment(att) else (mime or ""),
            "size": len(data),
            "is_image": is_image_attachment(att),
        })

    return staged, skipped


def staged_attachment_brief(staged: list[dict], skipped: list[str]) -> str:
    """The prompt block that tells a file-reading agent where its attachments ARE.

    Deliberately authoritative about the local paths: the generic attachment block
    the router prepends names an HTTP file URL, and a CLI running inside a sidecar
    has no route to that URL. Left alone, the agent spends its whole run trying to
    fetch a file that is already sitting next to it.
    """
    if not staged and not skipped:
        return ""
    lines = ["[Attached files — ALREADY ON DISK in your working directory]"]
    for item in staged:
        kind = "image" if item.get("is_image") else (item.get("mime_type") or "file")
        lines.append(f"- ./{item['rel']}  ({item['name']}, {kind}, {item['size']} bytes)")
    if staged:
        lines += [
            "",
            "Read these paths directly with your file-read tool. They are relative to your",
            "working directory and are the SAME files the user attached — do NOT try to",
            "download them, curl them, or resolve any URL mentioned elsewhere in this brief.",
        ]
        if any(i.get("is_image") for i in staged):
            lines.append(
                "At least one is an image: open it with your file-read tool so you can see it, "
                "and describe what you see before acting on it."
            )
    if skipped:
        # Its own section, not more bullets under the staged list — an agent that reads
        # these as readable paths goes hunting for files that were never written.
        lines += ["", "[Attachments that could NOT be delivered — no file exists for these]"]
        lines += [f"- {reason}" for reason in skipped]
        lines.append(
            "Say plainly that the unavailable attachment(s) could not be read. Never guess "
            "at their contents."
        )
    return "\n".join(lines) + "\n\n"


async def build_image_parts(
    attachments: list[dict] | None,
    *,
    owner_id: Optional[int] = None,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_px: int = DEFAULT_MAX_PX,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve image attachments into multimodal content parts.

    Returns ``(parts, skipped)`` where ``parts`` are ready to append to a
    message's content list and ``skipped`` holds one plain-English line per
    image we could NOT deliver. Callers must surface ``skipped`` — an image the
    model never saw must not read as an image it chose to ignore.

    ``owner_id`` is the authenticated user whose uploads may be read. Without
    one, a stored ``file_id`` resolves to nothing and is reported as skipped —
    an image is not worth handing another user's file to a model.
    """
    parts: list[dict[str, Any]] = []
    skipped: list[str] = []
    if not attachments:
        return parts, skipped

    images = [a for a in attachments if is_image_attachment(a)]
    if len(images) > max_images:
        skipped.append(
            f"only the first {max_images} of {len(images)} images were sent to the model"
        )
        images = images[:max_images]

    for index, att in enumerate(images, start=1):
        name = _label(att, index)
        data, mime, error = await resolve_attachment_bytes(att, index, owner_id=owner_id)

        if data is None:
            skipped.append(f"{name}: {error or 'could not be loaded'}")
            continue

        mime = _guess_mime(name, mime)
        data, mime = await asyncio.to_thread(_shrink, data, mime, max_px)
        parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{base64.b64encode(data).decode()}"
            },
        })

    return parts, skipped
