"""The harvis-doc pipeline as agent tools: one declaration, three wire shapes.

Chat turns write a ``harvis-doc`` block and the panel exports it. An agent that is not in
a chat turn (a Claude or Kimi sidecar over MCP, the workspace loop) had no way to reach
the same parsers, exporters and page renderer, so it could only write a file by hand and
never see the result. These tools hand it the same pipeline:

    DOCS_TOOLS ──► openai_tools()     OpenAI-compatible function tools
               ──► anthropic_tools()  Claude, via input_schema
               ──► mcp_tools()        MCP ``tools/list``
               ──► dispatch()         the one execution path for all of them

Same shape as :mod:`cad_tools`, minus its database ownership rules: nothing here reads
another user's data. The one write is ``docs_export`` storing a file under the caller's own
id in the existing ``owui_files`` store, which ``GET /api/v1/files/{id}/content`` serves back
to that user alone. A model never names a user id, a path or a storage key.

Every tool validates its inputs, runs blocking work in a thread under a timeout, and
returns ``({ok, ...}, ok)``; none raises to the caller. Builds and renders share the bounded threads
and the per-user rate limit in :mod:`plugins.hermes_ui.docs_limits` with the REST routes; when those
are full the tool answers with an error that says to wait. ``docs_preview`` returns page images
as ``payload["images"]``; :func:`image_blocks` turns them into MCP image content and
:func:`as_text` leaves them out of the text a non-vision loop reads.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import io
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from plugins.hermes_ui import docs_export, docs_limits
from plugins.hermes_ui.docs_export import FORMATS, MAX_SOURCE_BYTES, MEDIA_TYPES, ExportError

from .docs_tools_checks import validate_source

logger = logging.getLogger(__name__)

KINDS = ("deck", "doc", "sheet", "pdf")
EXPORT_FORMATS = tuple(MEDIA_TYPES)
RENDER_FORMATS = ("pptx", "docx", "xlsx", "pdf")
MAX_PREVIEW_PAGES = 6
DEFAULT_PREVIEW_PAGES = 3
MAX_IMAGE_WIDTH = 1024
MAX_PAGE_TEXT = 2000
MAX_INLINE_BYTES = 2 * 1024 * 1024
MAX_TITLE_CHARS = 200

EXPORT_TIMEOUT_S = 90
LIGHT_TIMEOUT_S = 20
RENDER_TIMEOUT_S = 200
CHECK_PAGES = 20                    # same page budget as the Hermes check route


@dataclass
class DocsToolContext:
    """What the model does not get to say: the authenticated caller and the store."""

    pool: Any = None
    user_id: int | None = None
    source: str = "mcp"


_SOURCE = {
    "type": "string",
    "maxLength": MAX_SOURCE_BYTES,
    "description": ("The harvis-doc text: a header (---, kind:, title:, outline:, ---) then the body. "
                    "The outer four-backtick harvis-doc fence is optional. Call docs_guide for the format."),
}
_KIND = {"type": "string", "enum": list(KINDS), "description": "deck = slides, doc = report or memo, sheet = spreadsheet, pdf."}


def _tool(name: str, description: str, properties: dict, required: list[str], read_only: bool) -> dict:
    return {"name": name, "description": description, "read_only": read_only,
            "schema": {"type": "object", "properties": properties, "required": list(required),
                       "additionalProperties": False}}


DOCS_TOOLS: list[dict] = [
    _tool("docs_guide",
          "Get the rules for writing a harvis-doc of one kind (deck, doc, sheet, pdf). Read this once before "
          "writing a document; it covers the header, slide and section layout, and the table, chart and "
          "timeline blocks.",
          {"kind": _KIND}, ["kind"], read_only=True),
    _tool("docs_validate",
          "Check a harvis-doc without making a file. Returns ok, kind, title, parts and a list of problems: "
          "unclosed fences, unknown kind, chart or timeline lines that would be dropped, bad sheet formulas.",
          {"source": _SOURCE}, ["source"], read_only=True),
    _tool("docs_export",
          "Make the real file from a harvis-doc: pptx or pdf for a deck, docx, pdf or md for a doc, xlsx or csv "
          "for a sheet. Returns the filename and a download_url the user can open.",
          {"source": _SOURCE,
           "format": {"type": "string", "enum": list(EXPORT_FORMATS),
                      "description": "deck: pptx or pdf. doc: docx, pdf or md. pdf: pdf or docx. sheet: xlsx or csv."},
           "title": {"type": "string", "maxLength": MAX_TITLE_CHARS,
                     "description": "File title. Optional; defaults to the title in the header."}},
          ["source", "format"], read_only=False),
    _tool("docs_preview",
          "Render pages of the finished document as images so you can look at your own slides or pages, plus "
          "each page's text. Use after docs_validate passes. Returns at most 6 pages.",
          {"source": _SOURCE,
           "format": {"type": "string", "enum": list(RENDER_FORMATS),
                      "description": "File type to render. Optional; defaults to pptx, docx, xlsx or pdf by kind."},
           "max_pages": {"type": "integer", "minimum": 1, "maximum": MAX_PREVIEW_PAGES,
                         "description": f"Pages to return, 1 to {MAX_PREVIEW_PAGES}. Default {DEFAULT_PREVIEW_PAGES}."}},
          ["source"], read_only=True),
    _tool("docs_check",
          "Run the document quality checks (layout, overflow, empty parts) on a harvis-doc and list what to fix. "
          "Returns ok and findings. Call it after docs_validate and fix every finding before exporting.",
          {"source": _SOURCE}, ["source"], read_only=True),
]

TOOL_NAMES: tuple[str, ...] = tuple(t["name"] for t in DOCS_TOOLS)
READ_ONLY_TOOLS: frozenset[str] = frozenset(t["name"] for t in DOCS_TOOLS if t["read_only"])


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

def _strictify(schema: dict) -> dict:
    """OpenAI strict mode: every property required, optional ones accept null."""
    out = copy.deepcopy(schema)
    required = set(out.get("required") or [])
    for name, prop in out["properties"].items():
        if name not in required:
            prop["type"] = [prop["type"], "null"]
            if "enum" in prop:
                prop["enum"] = [*prop["enum"], None]
    out["required"] = list(out["properties"])
    return out


def openai_tools(*, strict: bool = True) -> list[dict]:
    out = []
    for t in DOCS_TOOLS:
        fn: dict[str, Any] = {"name": t["name"], "description": t["description"],
                              "parameters": _strictify(t["schema"]) if strict else copy.deepcopy(t["schema"])}
        if strict:
            fn["strict"] = True
        out.append({"type": "function", "function": fn})
    return out


def anthropic_tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": copy.deepcopy(t["schema"])}
            for t in DOCS_TOOLS]


def mcp_tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "inputSchema": copy.deepcopy(t["schema"])}
            for t in DOCS_TOOLS]


# ---------------------------------------------------------------------------
# Argument checks
# ---------------------------------------------------------------------------

class _Refused(Exception):
    """A bad argument; the message is written for the model that sent it."""


def _fail(message: str, **extra) -> tuple[dict, bool]:
    return ({"ok": False, "error": message, **extra}, False)


def _source(args: dict) -> str:
    src = args.get("source")
    if not isinstance(src, str) or not src.strip():
        raise _Refused("source is required: the harvis-doc text.")
    if len(src.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _Refused(f"source is larger than {MAX_SOURCE_BYTES // 1000} KB.")
    return src


def _choice(args: dict, key: str, allowed: tuple[str, ...], default: str | None = None) -> str:
    raw = args.get(key)
    if raw is None or raw == "":
        if default is None:
            raise _Refused(f"{key} is required. Use one of: {', '.join(allowed)}.")
        return default
    value = str(raw).strip().lower().lstrip(".") if isinstance(raw, str) else ""
    if value not in allowed:
        raise _Refused(f"{key} must be one of: {', '.join(allowed)}.")
    return value


def _pages(args: dict) -> int:
    raw = args.get("max_pages")
    if raw is None:
        return DEFAULT_PREVIEW_PAGES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise _Refused(f"max_pages must be a number from 1 to {MAX_PREVIEW_PAGES}.") from None
    return max(1, min(n, MAX_PREVIEW_PAGES))


async def _blocking(fn: Callable, *a, timeout: float):
    """Quick work (reading a guide, validating): the shared thread pool, under a timeout."""
    return await asyncio.wait_for(asyncio.to_thread(fn, *a), timeout)


async def _build(fn: Callable, *a, timeout: float, counted: "tuple[str, DocsToolContext] | None" = None):
    """Export or check: a docs_limits.BUILDS slot, held until the thread ends even after the timeout.
    Raises docs_limits.Busy when every slot is taken, after refunding the ``counted`` (kind, ctx) rate hit."""
    try:
        return await docs_limits.BUILDS.run(fn, *a, timeout=timeout)
    except docs_limits.Busy:
        if counted:
            docs_limits.refund(counted[0], _rate_key(counted[1]))
        raise


def _rate_key(ctx: "DocsToolContext") -> str:
    return str(ctx.user_id) if ctx.user_id else f"anonymous-{ctx.source}"


def _rate(kind: str, ctx: "DocsToolContext") -> None:
    """Raises docs_limits.RateLimited when this caller has used up their ``kind`` allowance. The key is the same
    user id the REST routes use, so a person's tabs and their agents share one allowance."""
    docs_limits.hit(kind, _rate_key(ctx))


def _fit(source: str, fmt: str) -> None:
    """Refuse what export_doc would refuse (wrong kind for the format, empty, unfinished) before _rate and _build, so
    it neither counts against the allowance nor takes a build slot."""
    try:
        docs_export.parse_for_export(source, fmt)
    except ExportError as exc:
        raise _Refused(str(exc)) from None


def _primary_format(source: str) -> str:
    from plugins.hermes_ui.docs_parse import parse_harvis_doc
    return FORMATS[parse_harvis_doc(source).kind][0]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _t_guide(args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    kind = _choice(args, "kind", KINDS)
    from .doc_bridge import _skill_body
    body = await _blocking(_skill_body, kind, timeout=LIGHT_TIMEOUT_S)
    return ({"ok": True, "kind": kind, "formats": list(FORMATS[kind]),
             "guide": ("Write ONE harvis-doc: the header then the body. Pass the whole text as `source` to "
                       "docs_validate, docs_preview and docs_export.\n\n" + body)}, True)


async def _t_validate(args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    return (await _blocking(validate_source, _source(args), timeout=LIGHT_TIMEOUT_S)), True


def _store_file(data: bytes, filename: str) -> tuple[str, str]:
    """Write the bytes into the owui_files directory; the caller records the row. (id, path)."""
    from owui_compat import upload_store
    root = os.getenv("OWUI_FILES_DIR", "/app/owui_files")
    os.makedirs(root, exist_ok=True)
    file_id = str(uuid.uuid4())
    path = os.path.join(root, f"{file_id}{upload_store.disk_suffix(filename)}")
    with open(path, "wb") as out:
        out.write(data)
    return file_id, path


async def _save(ctx: DocsToolContext, data: bytes, filename: str, media_type: str) -> dict | None:
    """Store under the caller's id. ``None`` when there is nowhere to store it."""
    if ctx.pool is None or not ctx.user_id:
        return None
    file_id, path = await asyncio.to_thread(_store_file, data, filename)
    try:
        async with ctx.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO owui_files (id, user_id, filename, path, content_type, size, meta) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                file_id, int(ctx.user_id), filename, path, media_type, len(data),
                json.dumps({"source": "docs_tools"}))
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return {"file_id": file_id, "download_url": f"/api/v1/files/{file_id}/content"}


async def _t_export(args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    source = _source(args)
    fmt = _choice(args, "format", EXPORT_FORMATS)
    title = args.get("title")
    if title is not None and not isinstance(title, str):
        raise _Refused("title must be a string.")
    title = (title or "").strip()[:MAX_TITLE_CHARS] or None
    _fit(source, fmt)
    _rate("export", ctx)
    try:
        out = await _build(docs_export.export_doc, source, fmt, title, timeout=EXPORT_TIMEOUT_S,
                           counted=("export", ctx))
    except ExportError as exc:
        return _fail(str(exc))
    base = {"ok": True, "filename": out.filename, "format": fmt, "media_type": out.media_type,
            "bytes": len(out.data)}
    try:
        stored = await _save(ctx, out.data, out.filename, out.media_type)
    except Exception:
        logger.exception("docs_export: storing %s failed", out.filename)
        stored = None
    if stored:
        return ({**base, **stored, "message": f"Saved {out.filename}. The user can open the download_url."}, True)
    if len(out.data) > MAX_INLINE_BYTES:
        return _fail(f"{out.filename} is {len(out.data)} bytes and the file store is unavailable, so it "
                     "cannot be returned inline (limit 2 MB).")
    return ({**base, "data_b64": base64.b64encode(out.data).decode("ascii"),
             "message": "The file store is unavailable, so the file is returned as base64 in data_b64."}, True)


def _downscale(png_b64: str, width: int, height: int) -> tuple[str, int, int]:
    """PNG at most MAX_IMAGE_WIDTH wide. Unchanged if Pillow is missing or the image is small."""
    if width <= MAX_IMAGE_WIDTH and width > 0:
        return png_b64, width, height
    try:
        from PIL import Image
    except ImportError:
        return png_b64, width, height
    with Image.open(io.BytesIO(base64.b64decode(png_b64))) as img:
        w, h = img.size
        if w > MAX_IMAGE_WIDTH:
            img = img.resize((MAX_IMAGE_WIDTH, max(1, round(h * MAX_IMAGE_WIDTH / w))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii"), img.size[0], img.size[1]


async def _t_preview(args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    source = _source(args)
    max_pages = _pages(args)
    fmt = args.get("format")
    fmt = _choice(args, "format", RENDER_FORMATS) if fmt else _primary_format(source)
    if fmt not in RENDER_FORMATS:
        return _fail(f"A {fmt} file cannot be previewed. Use one of: {', '.join(RENDER_FORMATS)}.")
    from plugins.hermes_ui.docs_render_client import RenderUnavailable, render_pages
    _fit(source, fmt)
    _rate("preview", ctx)
    try:
        out = await _build(docs_export.export_doc, source, fmt, None, timeout=EXPORT_TIMEOUT_S,
                           counted=("preview", ctx))
        reply = await asyncio.wait_for(render_pages(out.data, fmt, max_pages), RENDER_TIMEOUT_S)
    except ExportError as exc:
        return _fail(str(exc))
    except RenderUnavailable as exc:
        return _fail(str(exc))
    pages, images = [], []
    for n, page in enumerate((reply.get("pages") or [])[:max_pages], 1):
        png, w, h = await asyncio.to_thread(_downscale, page.get("png_b64") or "",
                                            int(page.get("width") or 0), int(page.get("height") or 0))
        if png:
            images.append({"data": png, "mimeType": "image/png"})
        pages.append({"page": n, "width": w, "height": h, "text": str(page.get("text") or "")[:MAX_PAGE_TEXT]})
    total = int(reply.get("page_count") or len(pages))
    return ({"ok": True, "format": fmt, "page_count": total, "shown": len(pages), "pages": pages,
             "images": images}, True)


async def _t_check(args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    source = _source(args)
    try:
        from plugins.hermes_ui.docs_check import check_pages, check_source, sort_issues
    except ImportError:
        return _fail("checks not available")
    _rate("check", ctx)
    issues, files, doc = await _build(check_source, source, None, timeout=EXPORT_TIMEOUT_S,
                                      counted=("check", ctx))
    checked = {"code": True, "render": False}
    fmt = (FORMATS.get(doc.kind) or ("",))[0]
    if fmt in RENDER_FORMATS and fmt in files:
        from plugins.hermes_ui.docs_render_client import RenderUnavailable, render_pages
        try:
            reply = await asyncio.wait_for(render_pages(files[fmt], fmt, CHECK_PAGES), RENDER_TIMEOUT_S)
            texts = [str(p.get("text") or "") for p in reply.get("pages") or []]
            issues = issues + check_pages(doc, texts, fmt)
            checked["render"] = True
        except (RenderUnavailable, asyncio.TimeoutError):
            pass                                  # no page images is not a failed check
    issues = sort_issues(issues)
    return ({"ok": not any(i.get("severity") == "error" for i in issues), "issues": issues,
             "checked": checked}, True)


_HANDLERS: dict[str, Callable[[dict, DocsToolContext], Awaitable[tuple[dict, bool]]]] = {
    "docs_guide": _t_guide, "docs_validate": _t_validate, "docs_export": _t_export,
    "docs_preview": _t_preview, "docs_check": _t_check,
}


async def dispatch(name: str, args: dict, ctx: DocsToolContext) -> tuple[dict, bool]:
    """Run one tool. Returns ``(payload, ok)`` and never raises."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _fail(f"no such tool: {name}. Tools: {', '.join(TOOL_NAMES)}.")
    if not isinstance(args, dict):
        return _fail("arguments must be an object.")
    allowed = next(t for t in DOCS_TOOLS if t["name"] == name)["schema"]["properties"]
    extra = sorted(k for k in args if k not in allowed)
    if extra:
        return _fail(f"{', '.join(extra)} is not an argument of {name}. Arguments: {', '.join(allowed)}.")
    try:
        return await handler(args, ctx)
    except _Refused as exc:
        return _fail(str(exc))
    except docs_limits.RateLimited as exc:
        return _fail(f"{exc.message} Do not retry before then.", retry_after_s=exc.retry_after)
    except docs_limits.Busy:
        return _fail(docs_limits.BUSY_MESSAGE, retry_after_s=15)
    except asyncio.TimeoutError:
        return _fail(f"{name} took too long and was stopped. Try a smaller document.")
    except Exception:
        logger.exception("docs tool %s failed unexpectedly", name)
        return _fail(f"{name} failed unexpectedly.")


def image_blocks(payload: dict) -> list[dict]:
    """MCP image content blocks for a payload that carries page images."""
    return [{"type": "image", "data": i["data"], "mimeType": i.get("mimeType", "image/png")}
            for i in payload.get("images") or [] if i.get("data")]


def without_images(payload: dict) -> dict:
    if "images" not in payload:
        return payload
    return {**{k: v for k, v in payload.items() if k != "images"}, "images": len(payload["images"] or [])}


def as_text(payload: dict, ok: bool) -> str:
    """The result as the plain text a chat tool loop reads (page images left out)."""
    try:
        return json.dumps(without_images(payload), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)
