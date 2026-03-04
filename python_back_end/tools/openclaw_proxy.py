"""
OpenClaw tool proxy endpoints.

Provides safe, sandboxed tool access for OpenClaw agents.  All external web
fetches and document saves MUST go through these endpoints so that:
  1. RFC-1918 / loopback URLs are blocked before any network call.
  2. HTML content is sanitized and truncated before it reaches the LLM context.
  3. DOCX artifacts are created via the existing artifact system (DB + file storage).
  4. Every call is authenticated via the shared OPENCLAW_GATEWAY_TOKEN.

Endpoints:
  POST /api/tools/web-fetch      — fetch + extract text from a public URL
  POST /api/tools/document-save  — convert markdown → DOCX artifact
  POST /api/tools/file-analyze   — analyze uploaded file with Kimi vision,
                                   return structured document layout
"""

import asyncio
import ipaddress
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Truncate extracted text to this many characters (~8 000 tokens)
_MAX_TEXT_CHARS = 32_000

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # ULA IPv6
]

openclaw_proxy_router = APIRouter(prefix="/api/tools", tags=["openclaw-tools"])


# ─── Auth ──────────────────────────────────────────────────────────────────────

def _verify_openclaw_token(authorization: Optional[str]) -> None:
    """Only the OpenClaw pod (via shared OPENCLAW_GATEWAY_TOKEN) may call this."""
    if not OPENCLAW_GATEWAY_TOKEN:
        return  # dev / test mode — no token configured
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


# ─── URL validation ────────────────────────────────────────────────────────────

def _validate_url(url: str) -> None:
    """
    Reject URLs that point to private/internal addresses.

    Allowed: http:// and https:// pointing to routable public IPs.
    Rejected: RFC-1918, loopback, link-local, localhost, other schemes.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed URL")

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"URL scheme '{parsed.scheme}' is not allowed. Only http/https.",
        )

    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="URL has no hostname")

    # Reject by hostname
    lowered = hostname.lower()
    if lowered in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Requests to localhost are not allowed")

    # Try to resolve to an IP and check it
    try:
        addr = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                raise HTTPException(
                    status_code=400,
                    detail=f"Requests to private/internal address {hostname} are not allowed",
                )
    except ValueError:
        # Not an IP literal — that's fine, hostname-based URLs pass here.
        # (DNS resolution happens at fetch time; we can't pre-validate.)
        pass


# ─── Markdown → DOCX sections converter ───────────────────────────────────────

def _markdown_to_sections(markdown: str) -> List[Dict[str, Any]]:
    """
    Convert a markdown string into a list of DocumentSection dicts compatible
    with the existing `generate_document` DOCX generator.

    Supported constructs:
      # / ## / ### / #### — headings (level 1-4)
      - / * / + / 1. … — unordered and ordered list items
      > quote — block quote
      ``` fence ``` — code block (content kept; fence markers stripped)
      plain text — paragraph
    """
    sections: List[Dict[str, Any]] = []
    list_items: List[str] = []
    para_lines: List[str] = []
    in_code_block = False
    code_lines: List[str] = []

    def flush_list() -> None:
        if list_items:
            sections.append({"type": "list", "items": list_items[:]})
            list_items.clear()

    def flush_para() -> None:
        if para_lines:
            text = " ".join(para_lines).strip()
            if text:
                sections.append({"type": "paragraph", "content": text})
            para_lines.clear()

    def flush_code() -> None:
        if code_lines:
            sections.append({"type": "code", "content": "\n".join(code_lines)})
            code_lines.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        # ── Code fence toggle ───────────────────────────────────────────────
        if stripped.startswith("```"):
            if not in_code_block:
                flush_list()
                flush_para()
                in_code_block = True
            else:
                flush_code()
                in_code_block = False
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # ── Headings ────────────────────────────────────────────────────────
        heading_match = re.match(r"^(#{1,4}) (.+)$", stripped)
        if heading_match:
            flush_list()
            flush_para()
            level = len(heading_match.group(1))
            sections.append({
                "type": "heading",
                "level": level,
                "content": heading_match.group(2).strip(),
            })
            continue

        # ── Block quote ──────────────────────────────────────────────────────
        if stripped.startswith("> "):
            flush_list()
            flush_para()
            sections.append({"type": "quote", "content": stripped[2:].strip()})
            continue

        # ── Unordered list ───────────────────────────────────────────────────
        if re.match(r"^[-*+] ", stripped):
            flush_para()
            list_items.append(stripped[2:].strip())
            continue

        # ── Ordered list ─────────────────────────────────────────────────────
        ol_match = re.match(r"^\d+\. (.+)$", stripped)
        if ol_match:
            flush_para()
            list_items.append(ol_match.group(1).strip())
            continue

        # ── Horizontal rule ──────────────────────────────────────────────────
        if re.match(r"^[-*_]{3,}$", stripped):
            flush_list()
            flush_para()
            continue

        # ── Empty line ───────────────────────────────────────────────────────
        if not stripped:
            flush_list()
            flush_para()
            continue

        # ── Regular paragraph text ───────────────────────────────────────────
        if list_items:
            flush_list()
        para_lines.append(stripped)

    # Flush anything remaining
    flush_code()
    flush_list()
    flush_para()

    return sections


def _build_document_content(
    title: str,
    markdown: str,
    sources: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Build the `content` dict expected by ArtifactStorage / generate_document."""
    sections = _markdown_to_sections(markdown)

    # Append a References section if sources were provided
    if sources:
        sections.append({"type": "heading", "level": 2, "content": "References"})
        ref_items = [
            f"{s.get('title', 'Source')} — {s.get('url', '')}"
            for s in sources
            if s.get("url")
        ]
        if ref_items:
            sections.append({"type": "list", "items": ref_items})

    return {
        "title": title,
        "author": "Harvis AI",
        "sections": sections,
    }


# ─── Request / Response models ──────────────────────────────────────────────────

class WebFetchRequest(BaseModel):
    url: str
    purpose: str = "research"


class DocumentSaveRequest(BaseModel):
    title: str
    content: str           # markdown
    format: str = "docx"
    sources: List[Dict[str, str]] = []
    user_id: int


# ─── Endpoints ───────────────────────────────────────────────────────────────

@openclaw_proxy_router.post("/web-fetch")
async def web_fetch(
    req: WebFetchRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Fetch a public URL and return sanitized, truncated text.

    Auth: Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
    Rejects RFC-1918, loopback, localhost.  Strips scripts/styles before extraction.
    """
    authorization = request.headers.get("Authorization")
    _verify_openclaw_token(authorization)
    _validate_url(req.url)

    # Import extraction helpers (lazy — keeps startup fast if trafilatura is heavy)
    from research.extract.html_trafilatura import extract_html

    _USER_AGENT = (
        "Mozilla/5.0 (compatible; HarvisResearchBot/1.0; "
        "+https://github.com/dulc3/harvis-aidev)"
    )

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: extract_html(
                url=req.url,
                html=None,
                user_agent=_USER_AGENT,
                timeout_s=20,
            ),
        )
    except Exception as exc:
        logger.warning("web-fetch: failed to fetch %s: %s", req.url, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}")

    if not result.get("success") and not result.get("text"):
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract text from URL: {req.url}",
        )

    text: str = result.get("text") or ""
    title: str = result.get("title") or req.url

    # Truncate to token budget
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "\n\n[... truncated ...]"

    word_count = len(text.split())

    logger.info(
        "web-fetch: url=%s title=%r words=%d purpose=%s",
        req.url, title, word_count, req.purpose,
    )

    return {
        "url": req.url,
        "title": title,
        "text": text,
        "word_count": word_count,
    }


@openclaw_proxy_router.post("/document-save")
async def document_save(
    req: DocumentSaveRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Convert markdown content to a DOCX artifact and persist it.

    Auth: Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
    Returns artifact_id and download_url on success.
    """
    authorization = request.headers.get("Authorization")
    _verify_openclaw_token(authorization)

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool not available")

    # Import artifact system
    from artifacts.storage import ArtifactStorage
    from artifacts.models import ArtifactManifest, ArtifactType

    storage = ArtifactStorage()

    doc_content = _build_document_content(
        title=req.title,
        markdown=req.content,
        sources=req.sources,
    )

    manifest = ArtifactManifest(
        artifact_type=ArtifactType.DOCUMENT,
        title=req.title,
        description=f"Research document: {req.title}",
        content=doc_content,
    )

    try:
        artifact_id = await storage.create_artifact(
            pool=pool,
            user_id=req.user_id,
            manifest=manifest,
        )
    except Exception as exc:
        logger.error("document-save: failed to create artifact record: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create artifact: {exc}")

    # Generate the DOCX file synchronously (fast, sub-second)
    try:
        ok = await storage.generate_artifact(pool, artifact_id)
        if not ok:
            raise HTTPException(
                status_code=500,
                detail="DOCX generation failed — check artifact logs",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("document-save: generate_artifact failed for %s: %s", artifact_id, exc)
        raise HTTPException(status_code=500, detail=f"DOCX generation error: {exc}")

    artifact_id_str = str(artifact_id)
    download_url = f"/api/artifacts/{artifact_id_str}/download"

    logger.info(
        "document-save: artifact_id=%s title=%r user_id=%d",
        artifact_id_str, req.title, req.user_id,
    )

    return {
        "artifact_id": artifact_id_str,
        "download_url": download_url,
    }


# ─── File analyze ──────────────────────────────────────────────────────────────

_KIMI_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
_UPLOADS_DIR = os.getenv("IMAGES_DIR", "/app/images")

_VISION_PROMPT = """You are analyzing a document image. Extract its complete structure and content.

Return ONLY a JSON object with this exact shape (no markdown, no extra text):
{
  "title": "document title if visible, else empty string",
  "document_type": "one of: report, proposal, memo, letter, form, invoice, table, diagram, other",
  "sections": [
    {
      "heading": "section heading text, empty string if no heading",
      "level": 1,
      "content": "full paragraph text of this section"
    }
  ],
  "tables": [
    {
      "caption": "table caption or empty string",
      "headers": ["col1", "col2"],
      "rows": [["val1", "val2"], ["val3", "val4"]]
    }
  ],
  "lists": [
    {
      "heading": "list heading or empty string",
      "items": ["item 1", "item 2"]
    }
  ],
  "key_points": ["brief bullet summary of the most important points"]
}

Be thorough — extract ALL visible text, preserving the logical hierarchy.
If a section has sub-sections, represent them as separate entries with level 2 or 3."""


class FileAnalyzeRequest(BaseModel):
    file_id: str      # UUID from POST /api/uploads
    user_id: int      # used to fetch the Moonshot API key from DB
    hint: str = ""    # optional user hint e.g. "this is a project proposal"


@openclaw_proxy_router.post("/file-analyze")
async def file_analyze(
    req: FileAnalyzeRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Analyze an uploaded file with Kimi vision and return structured document layout.

    Auth: Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
    Loads the file stored by POST /api/uploads, converts to images, sends to Kimi
    vision, returns JSON structure OpenClaw can use with harvis-document skill.
    """
    authorization = request.headers.get("Authorization")
    _verify_openclaw_token(authorization)

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool not available")

    # ── Load file from uploads dir ─────────────────────────────────────────────
    # Find the file — we store it as {file_id}.{ext} + {file_id}.meta.json
    meta_path = os.path.join(_UPLOADS_DIR, f"{req.file_id}.meta.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail=f"File {req.file_id} not found")

    try:
        import json as _json
        with open(meta_path) as f:
            meta = _json.load(f)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file metadata: {exc}")

    mime_type: str = meta.get("mime_type", "application/octet-stream")
    stored_path: str = meta.get("stored_path", "")
    if not stored_path or not os.path.exists(stored_path):
        raise HTTPException(status_code=404, detail=f"File data for {req.file_id} not found")

    # ── Read + convert to base64 images ────────────────────────────────────────
    from file_processing import convert_file_to_images, is_vision_compatible_file

    if not is_vision_compatible_file(mime_type):
        raise HTTPException(
            status_code=422,
            detail=f"File type '{mime_type}' is not supported for vision analysis",
        )

    try:
        with open(stored_path, "rb") as f:
            raw_bytes = f.read()
        import base64 as _b64
        file_b64 = _b64.b64encode(raw_bytes).decode()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    try:
        image_pairs = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: convert_file_to_images(file_b64, mime_type),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to convert file to images: {exc}")

    if not image_pairs:
        raise HTTPException(
            status_code=422,
            detail="Could not convert file to images for vision analysis",
        )

    # ── Fetch Moonshot API key for this user ───────────────────────────────────
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT api_key_encrypted, api_url
                FROM user_api_keys
                WHERE user_id = $1 AND provider_name = 'moonshot' AND is_active = TRUE
                """,
                req.user_id,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error fetching API key: {exc}")

    if not row:
        raise HTTPException(
            status_code=400,
            detail="No Moonshot API key configured for this user — add it in Settings",
        )

    # Reuse the decrypt helper already in main scope
    try:
        from main import decrypt_api_key
        moonshot_api_key = decrypt_api_key(row["api_key_encrypted"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt API key: {exc}")

    moonshot_base = (row.get("api_url") or _KIMI_BASE_URL).rstrip("/")

    # ── Build vision request to Kimi ───────────────────────────────────────────
    prompt_text = _VISION_PROMPT
    if req.hint:
        prompt_text += f"\n\nUser hint: {req.hint}"

    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for img_b64, img_mime in image_pairs:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img_mime};base64,{img_b64}"},
        })

    payload = {
        "model": "kimi-k2.5",
        "messages": [{"role": "user", "content": content}],
        "temperature": 1.0,
        "max_tokens": 4096,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{moonshot_base}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {moonshot_api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            kimi_data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("file-analyze: Kimi API error %s: %s", exc.response.status_code, exc.response.text)
        raise HTTPException(status_code=502, detail=f"Kimi API error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("file-analyze: Kimi request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Kimi request failed: {exc}")

    # ── Parse JSON from Kimi's response ───────────────────────────────────────
    raw_text: str = (
        kimi_data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    ).strip()

    # Strip markdown fences if Kimi wrapped the JSON anyway
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text.strip())

    try:
        import json as _json
        structure = _json.loads(raw_text)
    except Exception:
        # Kimi didn't return clean JSON — return raw text so OpenClaw can still work
        logger.warning("file-analyze: Kimi did not return valid JSON, returning raw text")
        structure = {"raw_description": raw_text}

    logger.info(
        "file-analyze: file_id=%s user_id=%d pages=%d",
        req.file_id, req.user_id, len(image_pairs),
    )

    return {
        "file_id": req.file_id,
        "mime_type": mime_type,
        "pages_analyzed": len(image_pairs),
        "structure": structure,
    }
