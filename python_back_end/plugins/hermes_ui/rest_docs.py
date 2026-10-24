"""The harvis-doc routes: export a block as a file, preview its pages, check it for problems.

    POST /harvis/docs/export   the block as pptx, docx, xlsx, pdf, csv or md (docs_export.FORMATS)
    POST /harvis/docs/preview  page images from the document sandbox, served by GET .../preview/{key}/{n}.png
    POST /harvis/docs/check    code checks on the file, plus a look at the pages by a local vision model

All three read at most MAX_BODY_BYTES of request before parsing JSON, and give the export
EXPORT_TIMEOUT_S, so one large or slow document cannot hold a worker.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from auth_optimized import get_current_user_optimized

from . import docs_limits, docs_preview
from .docs_check import check_pages, check_source, page_label, sort_issues
from .docs_check_pixels import check_pixels
from .docs_export import FORMATS, MAX_SOURCE_BYTES, ExportError, content_disposition, export_doc, parse_for_export
from .docs_parse import parse_harvis_doc
from .docs_preview import RenderUnavailable, cache, cache_key, primary_format, renderable, user_key
from .docs_vision import vision_check

log = logging.getLogger("hermes_ui.docs")

router = APIRouter(prefix="/hermes-api/api")

EXPORT_TIMEOUT_S = 60
# Builds run on docs_limits.BUILDS, shared with the agent tools: a build that times out keeps its slot until its
# thread ends, and a request that finds every slot taken is refused rather than queued behind them.
RENDER_TIMEOUT_S = 150
# A source at the 1 MB limit can grow to about twice that once JSON escapes its quotes, newlines and accents.
MAX_BODY_BYTES = 2 * MAX_SOURCE_BYTES + 100_000
_KEY = re.compile(r"[0-9a-f]{64}")
_PAGE = re.compile(r"(\d{1,3})\.png")


# ---- reading a request ------------------------------------------------------------------------

async def _read_json(request: Request) -> dict:
    """The JSON object in the body, reading no more than MAX_BODY_BYTES of it. Raises HTTPException."""
    too_big = HTTPException(413, "The request is larger than the document limit (about 2 MB).")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_big
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:                       # Content-Length can be absent or wrong
            raise too_big
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks))
    except ValueError:
        raise HTTPException(400, "The request body must be JSON.")
    if not isinstance(body, dict):
        raise HTTPException(400, "The request body must be a JSON object.")
    return body


def _source_of(body: dict) -> str:
    source = body.get("source")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(400, "The document is empty.")
    if len(source) > MAX_SOURCE_BYTES:                  # cheap check before the encode in parsing
        raise HTTPException(400, "The document is larger than 1 MB.")
    return source


def _title_of(body: dict) -> Optional[str]:
    return body["title"] if isinstance(body.get("title"), str) else None


def _page_format(body: dict, source: str) -> str:
    """The format to draw: the one asked for, else the kind's primary file. Raises HTTPException."""
    fmt = body.get("format")
    kind = parse_harvis_doc(source).kind
    fmt = fmt.strip().lower() if isinstance(fmt, str) and fmt.strip() else primary_format(source)
    if fmt not in FORMATS[kind]:
        raise HTTPException(400, f"A {kind} has no {fmt} file. Use {' or '.join(FORMATS[kind])}.")
    if not renderable(fmt):
        raise HTTPException(400, f"A {fmt} file has no pages to draw. Use "
                                 f"{' or '.join(f for f in FORMATS[kind] if renderable(f))}.")
    return fmt


def _rate(kind: str, user) -> None:
    """429 when this user has used up their ``kind`` allowance (docs_limits.RATE_LIMITS)."""
    try:
        docs_limits.hit(kind, user_key(user))
    except docs_limits.RateLimited as exc:
        raise HTTPException(429, exc.message, headers={"Retry-After": str(exc.retry_after)})


def _fit(source: str, fmt: str) -> None:
    """400 when export_doc would refuse this source/format. Run before _rate and _timed, so a request that cannot
    build neither counts against the allowance nor takes a build slot (parsing a 1 MB source takes ~15 ms)."""
    try:
        parse_for_export(source, fmt.strip().lower())
    except ExportError as exc:
        raise HTTPException(400, str(exc))


async def _timed(fn, *args: Any, counted: tuple[str, Any] | None = None):
    """``fn(*args)`` on a build thread, given up on after EXPORT_TIMEOUT_S (the thread finishes in the background).

    503 when docs_limits.MAX_BUILDS builds are already running; the ``counted`` (kind, user) rate hit is refunded,
    since the build never ran."""
    try:
        return await docs_limits.BUILDS.run(fn, *args, timeout=EXPORT_TIMEOUT_S)
    except docs_limits.Busy:
        if counted:
            docs_limits.refund(counted[0], user_key(counted[1]))
        raise HTTPException(503, docs_limits.BUSY_MESSAGE)
    except asyncio.TimeoutError:
        raise HTTPException(504, f"The document took longer than {EXPORT_TIMEOUT_S} seconds to build. "
                                 "Try a shorter document.")


# ---- export -----------------------------------------------------------------------------------

@router.post("/harvis/docs/export")
async def export_document(request: Request, user=Depends(get_current_user_optimized)):
    body = await _read_json(request)
    source, fmt = _source_of(body), body.get("format")
    if not isinstance(fmt, str) or not fmt.strip():
        raise HTTPException(400, "A format is required.")
    _fit(source, fmt)
    _rate("export", user)
    try:
        # Rendering is CPU work (weasyprint especially); keep it off the event loop.
        out = await _timed(export_doc, source, fmt, _title_of(body), counted=("export", user))
    except ExportError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.exception("hermes_ui: document export failed (format=%s)", fmt)
        raise HTTPException(500, "The document could not be exported.")
    return Response(content=out.data, media_type=out.media_type,
                    headers={"Content-Disposition": content_disposition(out.filename)})


# ---- preview ----------------------------------------------------------------------------------

async def _render(owner: str, key: str, fmt: str, data: bytes, max_pages: int):
    """Render ``data`` in the sandbox and cache the pages. 503 when the sandbox cannot."""
    try:
        item = await asyncio.wait_for(docs_preview.render_entry(owner, fmt, data, max_pages), RENDER_TIMEOUT_S)
    except RenderUnavailable as exc:
        raise HTTPException(503, f"preview unavailable: {exc}")
    except asyncio.TimeoutError:
        raise HTTPException(504, "The pages took too long to draw. Try a shorter document.")
    return cache.put(key, item)


def _max_pages(body: dict) -> int:
    raw = body.get("max_pages", docs_preview.MAX_PAGES)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise HTTPException(400, "max_pages must be a whole number.")
    return min(max(raw, 1), docs_preview.MAX_PAGES)


@router.post("/harvis/docs/preview")
async def preview_document(request: Request, user=Depends(get_current_user_optimized)):
    body = await _read_json(request)
    source = _source_of(body)
    fmt, title, pages = _page_format(body, source), _title_of(body), _max_pages(body)
    owner = user_key(user)
    key = cache_key(owner, fmt, source, title, pages)
    item = cache.get(key, owner)
    if item is None:
        _fit(source, fmt)
        _rate("preview", user)                          # a cached page costs nothing, so it is not counted
        try:
            out = await _timed(export_doc, source, fmt, title, counted=("preview", user))
        except ExportError as exc:
            raise HTTPException(400, str(exc))
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            log.exception("hermes_ui: document preview export failed (format=%s)", fmt)
            raise HTTPException(500, "The document could not be exported.")
        item = await _render(owner, key, fmt, out.data, pages)
    return item.listing(key)


@router.get("/harvis/docs/preview/{key}/{name}")
async def preview_page(key: str, name: str, user=Depends(get_current_user_optimized)):
    page = _PAGE.fullmatch(name)
    item = cache.get(key, user_key(user)) if _KEY.fullmatch(key) and page else None
    if item is None or int(page.group(1)) >= len(item.pages):
        raise HTTPException(404, "That page preview has expired. Preview the document again.")
    return Response(content=item.pages[int(page.group(1))]["png"], media_type="image/png",
                    headers={"Cache-Control": "private, max-age=600"})


# ---- check ------------------------------------------------------------------------------------

@router.post("/harvis/docs/check")
async def check_document(request: Request, user=Depends(get_current_user_optimized)):
    started = time.monotonic()
    body = await _read_json(request)
    source = _source_of(body)
    fmt, title = _page_format(body, source), _title_of(body)
    owner = user_key(user)
    _rate("check", user)
    try:
        issues, files, doc = await _timed(check_source, source, title, counted=("check", user))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.exception("hermes_ui: document check failed")
        raise HTTPException(500, "The document could not be checked.")
    checked: dict[str, Any] = {"code": True, "vision": False, "render": False}

    key = cache_key(owner, fmt, source, title, docs_preview.MAX_PAGES)
    item = cache.get(key, owner)
    if item is None and fmt in files:
        try:
            item = await _render(owner, key, fmt, files[fmt], docs_preview.MAX_PAGES)
        except HTTPException as exc:                  # no pages is not a failed check: the code checks stand
            log.info("hermes_ui: check ran without page images (%s)", exc.detail)
    if item is not None:
        checked["render"] = True
        issues += check_pages(doc, [p["text"] for p in item.pages], fmt)
        try:                                          # pixel checks read the cached images; they never fail a check
            issues += await asyncio.to_thread(check_pixels, [p["png"] for p in item.pages], page_label(fmt),
                                              last_may_be_short=fmt != "pptx")
        except Exception:  # noqa: BLE001
            log.warning("hermes_ui: pixel check failed", exc_info=True)
        if body.get("vision") is True:                # opt in: a missing key means no, as the UI's unticked box sends
            await _look(item, fmt, body, issues, checked, started + RENDER_TIMEOUT_S)
    return {"issues": sort_issues(issues), "checked": checked}


async def _look(item, fmt: str, body: dict, issues: list, checked: dict, deadline: float) -> None:
    """Add the vision model's findings to ``issues``; any failure leaves the code checks as they were.

    ``deadline`` is a time.monotonic() value; the vision pass looks at no page after it."""
    requested = body.get("model") if isinstance(body.get("model"), str) else None
    try:
        seen = await vision_check([p["png"] for p in item.pages], page_label(fmt), requested, deadline=deadline)
    except Exception:  # noqa: BLE001 - vision never blocks the check
        log.exception("hermes_ui: vision check failed")
        return
    if seen.get("busy"):
        checked["vision_busy"] = True
        return
    if seen.get("timed_out"):
        checked["vision_timeout"] = True
    if seen["model"]:
        checked["model"] = seen["model"]
    if seen["done"]:
        checked["vision"] = True
        if seen["skipped"]:
            checked["vision_partial"] = True
        issues += seen["issues"]
