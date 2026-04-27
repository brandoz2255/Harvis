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
  POST /api/tools/vision-query   — analyze a base64 image with Kimi K2.5 vision,
                                   called by OpenClaw agents for Discord image attachments
"""

import asyncio
import ipaddress
import logging
import os
import re
import socket
import json
import base64
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from workspace.gateway_auth import resolve_gateway_caller

logger = logging.getLogger(__name__)

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Truncate extracted text to this many characters (~8 000 tokens)
_MAX_TEXT_CHARS = 32_000

# Maximum raw HTML bytes fetched per request (prevents huge downloads)
_MAX_FETCH_BYTES = int(os.getenv("OPENCLAW_WEB_FETCH_MAX_BYTES", "2000000"))  # 2MB

# Per-session rate limits (best-effort in-memory)
_RATE_WINDOW_S = int(os.getenv("OPENCLAW_WEB_RATE_WINDOW_S", "60"))
_RATE_MAX_SEARCH = int(os.getenv("OPENCLAW_WEB_RATE_MAX_SEARCH", "10"))
_RATE_MAX_FETCH = int(os.getenv("OPENCLAW_WEB_RATE_MAX_FETCH", "20"))
_rate_state: Dict[str, Dict[str, List[float]]] = {}  # key -> {"search":[ts], "fetch":[ts]}

# Domain policy
_ALLOWLIST = [h.strip().lower() for h in os.getenv("OPENCLAW_WEB_ALLOWLIST", "").split(",") if h.strip()]
_DENYLIST = [h.strip().lower() for h in os.getenv("OPENCLAW_WEB_DENYLIST", "").split(",") if h.strip()]

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # ULA IPv6
]


def _ensure_resolved_addresses_public(hostname: str) -> None:
    """
    Block IP literals or hostnames whose DNS resolves to private/internal addresses
    (SSRF / DNS-rebinding protection).
    """
    try:
        addr = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                raise HTTPException(
                    status_code=400,
                    detail=f"Requests to private/internal address {hostname} are not allowed",
                )
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                ip = info[4][0]
                addr = ipaddress.ip_address(ip)
                for net in _PRIVATE_NETWORKS:
                    if addr in net:
                        raise HTTPException(
                            status_code=400,
                            detail=f"DNS for {hostname} resolved to private/internal address {ip}",
                        )
        except HTTPException:
            raise
        except Exception:
            # If DNS fails here, let the downstream fetch/browser surface errors.
            pass


openclaw_proxy_router = APIRouter(prefix="/api/tools", tags=["openclaw-tools"])

browser_proxy_router = APIRouter(prefix="/api/tools/browser", tags=["openclaw-browser"])


# ─── Auth ──────────────────────────────────────────────────────────────────────

async def _verify_openclaw_token(request: Request, authorization: Optional[str]) -> None:
    """Allow bundled token or any verified BYO token."""
    await resolve_gateway_caller(request, authorization)


async def _audit(
    request: Request,
    *,
    session_key: str,
    tool: str,
    input_obj: Dict[str, Any],
    status_code: int,
    output_meta: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO openclaw_tool_audit(session_key, tool, input, output_meta, status_code, error)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                """,
                session_key,
                tool,
                json.dumps(input_obj),
                json.dumps(output_meta or {}),
                status_code,
                error,
            )
    except Exception:
        # Never break the tool call due to logging.
        return


# ─── URL validation ────────────────────────────────────────────────────────────

def _validate_url(url: str, *, live_web: bool = False) -> None:
    """
    Reject URLs that point to private/internal addresses.

    Allowed: http:// and https:// pointing to routable public IPs.
    Rejected: RFC-1918, loopback, link-local, localhost, other schemes.

    When live_web=True, domain allow/deny lists are skipped (user acknowledged
    unrestricted access).  Private-IP and localhost checks are ALWAYS enforced.
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

    # Reject by hostname — always enforced regardless of live_web
    lowered = hostname.lower()
    if lowered in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Requests to localhost are not allowed")

    # Domain allow/deny lists (suffix match) — skipped in live_web mode
    if not live_web:
        if _DENYLIST:
            for bad in _DENYLIST:
                if lowered == bad or lowered.endswith("." + bad):
                    raise HTTPException(status_code=400, detail=f"Domain '{lowered}' is blocked")
        if _ALLOWLIST:
            ok = False
            for good in _ALLOWLIST:
                if lowered == good or lowered.endswith("." + good):
                    ok = True
                    break
            if not ok:
                raise HTTPException(status_code=400, detail=f"Domain '{lowered}' is not allowlisted")

    _ensure_resolved_addresses_public(lowered)


def _is_live_web(request: Request) -> bool:
    """Check if the request has the X-Live-Web header (user-acknowledged unrestricted access)."""
    return request.headers.get("X-Live-Web", "").lower() in ("true", "1", "yes")


# Live web rate limits — relaxed compared to controlled mode
_RATE_MAX_SEARCH_LIVE = int(os.getenv("OPENCLAW_WEB_RATE_MAX_SEARCH_LIVE", "30"))
_RATE_MAX_FETCH_LIVE = int(os.getenv("OPENCLAW_WEB_RATE_MAX_FETCH_LIVE", "60"))


def _rate_limit(key: str, kind: str, max_events: int) -> None:
    now = asyncio.get_event_loop().time()
    bucket = _rate_state.setdefault(key, {}).setdefault(kind, [])
    # prune
    cutoff = now - _RATE_WINDOW_S
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= max_events:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {kind}")
    bucket.append(now)


async def _require_interactive(
    request: Request,
    *,
    workspace_id: str,
    capability_token: str,
) -> int:
    """
    Validate Tier 3 capability token for a specific workspace_id.
    Returns owning user_id on success.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    if not capability_token:
        raise HTTPException(status_code=401, detail="Missing capability token")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, interactive_enabled, capability_token, expires_at
            FROM workspace_web_caps
            WHERE workspace_id = $1
            """,
            workspace_id,
        )
    if not row:
        raise HTTPException(status_code=403, detail="Interactive browsing not enabled for this workspace")
    if not row.get("interactive_enabled"):
        raise HTTPException(status_code=403, detail="Interactive browsing disabled for this workspace")
    if (row.get("capability_token") or "") != capability_token:
        raise HTTPException(status_code=403, detail="Invalid capability token")
    exp = row.get("expires_at")
    if exp is not None:
        # asyncpg returns datetime
        if exp.timestamp() < time.time():
            raise HTTPException(status_code=403, detail="Capability token expired")
    return int(row.get("user_id") or 0)


def _validate_browser_url(url: str, *, live_web: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Tier 3 browsing requires https URLs")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="URL has no hostname")
    if hostname in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Requests to localhost are not allowed")

    # With X-Live-Web (workspace live_web), skip hostname allowlist — same policy as web-fetch.
    # OPENCLAW_BROWSER_ALLOWLIST=* also skips the allowlist (still enforces https + non-private DNS).
    if not live_web:
        raw_allow = os.getenv("OPENCLAW_BROWSER_ALLOWLIST", "").strip()
        if raw_allow != "*":
            allow = [h.strip().lower() for h in raw_allow.split(",") if h.strip()]
        else:
            allow = ["*"]  # sentinel: skip check below
        if allow != ["*"] and not allow:
            # Default Tier 3 hosts — broad research set (override with OPENCLAW_BROWSER_ALLOWLIST)
            allow = [
                "example.com",
                "www.example.com",
                # Google
                "google.com",
                "google.dev",
                "googleapis.com",
                "gstatic.com",
                "googleusercontent.com",
                "gemini.google.com",
                "ai.google.dev",
                "blog.google",
                "chromium.org",
                # Microsoft / GitHub
                "github.com",
                "gist.github.com",
                "raw.githubusercontent.com",
                "microsoft.com",
                "azure.com",
                "visualstudio.com",
                "bing.com",
                "msn.com",
                # Search & reference
                "duckduckgo.com",
                "www.duckduckgo.com",
                "wikipedia.org",
                "wikimedia.org",
                "archive.org",
                # Social / comms
                "reddit.com",
                "x.com",
                "twitter.com",
                "linkedin.com",
                "facebook.com",
                "instagram.com",
                "youtube.com",
                "youtu.be",
                "discord.com",
                "slack.com",
                # News / media
                "news.ycombinator.com",
                "ycombinator.com",
                "bbc.co.uk",
                "bbc.com",
                "reuters.com",
                "nytimes.com",
                "theguardian.com",
                "apnews.com",
                # AI / dev tools
                "claude.ai",
                "anthropic.com",
                "console.anthropic.com",
                "docs.anthropic.com",
                "openai.com",
                "platform.openai.com",
                "cursor.com",
                "docs.cursor.com",
                "httpstat.us",
                "ollama.com",
                "huggingface.co",
                "kaggle.com",
                "colab.research.google.com",
                # Docs & learning
                "stackoverflow.com",
                "serverfault.com",
                "superuser.com",
                "stackexchange.com",
                "developer.mozilla.org",
                "docs.python.org",
                "nodejs.org",
                "npmjs.com",
                "pypi.org",
                "react.dev",
                "nextjs.org",
                "tailwindcss.com",
                "kubernetes.io",
                "docker.com",
                "docs.docker.com",
                # Cloud & infra docs
                "aws.amazon.com",
                "cloud.google.com",
                "docs.aws.amazon.com",
                # Registries & CDNs (common page assets)
                "unpkg.com",
                "jsdelivr.net",
                "cdn.jsdelivr.net",
                "cdnjs.cloudflare.com",
                "cloudflare.com",
                "fastly.com",
                # Commerce / general
                "amazon.com",
                "apple.com",
            ]
        if allow != ["*"]:
            ok = any(hostname == h or hostname.endswith("." + h) for h in allow)
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail=f"Domain '{hostname}' is not allowlisted for interactive browsing",
                )

    _ensure_resolved_addresses_public(hostname)


class BrowserSessionRequest(BaseModel):
    workspace_id: str
    capability_token: str
    headless: bool = True


class BrowserNavigateRequest(BaseModel):
    workspace_id: str
    capability_token: str
    sessionId: str
    url: str


class BrowserActRequest(BaseModel):
    workspace_id: str
    capability_token: str
    sessionId: str
    action: str
    selector: Optional[str] = None
    text: Optional[str] = None
    key: Optional[str] = None
    timeoutMs: int = 10000


class BrowserScreenshotRequest(BaseModel):
    workspace_id: str
    capability_token: str
    sessionId: str


class BrowserCloseRequest(BaseModel):
    workspace_id: str
    capability_token: str
    sessionId: str


@browser_proxy_router.post("/session")
async def browser_session(req: BrowserSessionRequest, request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")

    user_id = await _require_interactive(
        request, workspace_id=req.workspace_id, capability_token=req.capability_token
    )

    # First session creation may download geckodriver; allow more time.
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post("http://browser-runner:8765/session", json={"headless": bool(req.headless)})
    if r.status_code != 200:
        await _audit(
            request,
            session_key=session_key,
            tool="browser/session",
            input_obj={"workspace_id": req.workspace_id, "headless": bool(req.headless)},
            status_code=r.status_code,
            error=r.text[:2000],
        )
        raise HTTPException(status_code=502, detail="Browser runner error")

    data = r.json()
    await _audit(
        request,
        session_key=session_key,
        tool="browser/session",
        input_obj={"workspace_id": req.workspace_id, "headless": bool(req.headless)},
        status_code=200,
        output_meta={"user_id": user_id},
    )
    return data


@browser_proxy_router.post("/navigate")
async def browser_navigate(req: BrowserNavigateRequest, request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    await _require_interactive(request, workspace_id=req.workspace_id, capability_token=req.capability_token)
    _validate_browser_url(req.url, live_web=_is_live_web(request))

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        r = await client.post(
            "http://browser-runner:8765/navigate",
            json={"sessionId": req.sessionId, "url": req.url},
        )
    if r.status_code != 200:
        await _audit(
            request,
            session_key=session_key,
            tool="browser/navigate",
            input_obj={"workspace_id": req.workspace_id, "url": req.url},
            status_code=r.status_code,
            error=r.text[:2000],
        )
        raise HTTPException(status_code=502, detail="Browser runner error")

    data = r.json()
    await _audit(
        request,
        session_key=session_key,
        tool="browser/navigate",
        input_obj={"workspace_id": req.workspace_id, "url": req.url},
        status_code=200,
        output_meta={"current_url": data.get("url")},
    )
    return data


@browser_proxy_router.post("/act")
async def browser_act(req: BrowserActRequest, request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    await _require_interactive(request, workspace_id=req.workspace_id, capability_token=req.capability_token)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(
            "http://browser-runner:8765/act",
            json={
                "sessionId": req.sessionId,
                "action": req.action,
                "selector": req.selector,
                "text": req.text,
                "key": req.key,
                "timeoutMs": req.timeoutMs,
            },
        )
    if r.status_code != 200:
        await _audit(
            request,
            session_key=session_key,
            tool="browser/act",
            input_obj={"workspace_id": req.workspace_id, "action": req.action, "selector": req.selector},
            status_code=r.status_code,
            error=r.text[:2000],
        )
        raise HTTPException(status_code=502, detail="Browser runner error")

    data = r.json()
    await _audit(
        request,
        session_key=session_key,
        tool="browser/act",
        input_obj={"workspace_id": req.workspace_id, "action": req.action, "selector": req.selector},
        status_code=200,
    )
    return data


@browser_proxy_router.post("/screenshot")
async def browser_screenshot(req: BrowserScreenshotRequest, request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    await _require_interactive(request, workspace_id=req.workspace_id, capability_token=req.capability_token)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        r = await client.post("http://browser-runner:8765/screenshot", json={"sessionId": req.sessionId})
    if r.status_code != 200:
        await _audit(
            request,
            session_key=session_key,
            tool="browser/screenshot",
            input_obj={"workspace_id": req.workspace_id},
            status_code=r.status_code,
            error=r.text[:2000],
        )
        raise HTTPException(status_code=502, detail="Browser runner error")

    png_b64 = (r.json() or {}).get("pngBase64") or ""
    if not png_b64:
        raise HTTPException(status_code=502, detail="Browser runner did not return screenshot data")

    # Store as a file artifact (path only; no raw bytes sent to OpenClaw)
    artifact_dir = os.environ.get("ARTIFACT_STORAGE_DIR", "/data/artifacts")
    os.makedirs(os.path.join(artifact_dir, "browser"), exist_ok=True)
    filename = f"{req.workspace_id}-{int(time.time())}.png"
    rel_path = f"browser/{filename}"
    abs_path = os.path.join(artifact_dir, rel_path)
    with open(abs_path, "wb") as f:
        f.write(base64.b64decode(png_b64))

    await _audit(
        request,
        session_key=session_key,
        tool="browser/screenshot",
        input_obj={"workspace_id": req.workspace_id},
        status_code=200,
        output_meta={"path": rel_path},
    )
    return {"artifact_path": rel_path}


@browser_proxy_router.post("/close")
async def browser_close(req: BrowserCloseRequest, request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    await _require_interactive(request, workspace_id=req.workspace_id, capability_token=req.capability_token)

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        r = await client.post("http://browser-runner:8765/close", json={"sessionId": req.sessionId})
    await _audit(
        request,
        session_key=session_key,
        tool="browser/close",
        input_obj={"workspace_id": req.workspace_id},
        status_code=r.status_code,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Browser runner error")
    return r.json()


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


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 8
    purpose: str = "research"


class DocumentSaveRequest(BaseModel):
    title: str
    content: str           # markdown
    format: str = "docx"
    sources: List[Dict[str, str]] = []
    user_id: int


# ─── Endpoints ───────────────────────────────────────────────────────────────

@openclaw_proxy_router.post("/search")
async def web_search(
    req: WebSearchRequest,
    request: Request,
) -> Dict[str, Any]:
    """
    Perform a web search and return structured results only (no page content).

    Auth: Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
    Intended for Tier 2 research: search → pick URLs → use /api/tools/web-fetch.
    """
    authorization = request.headers.get("Authorization")
    await _verify_openclaw_token(request, authorization)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    live_web = _is_live_web(request)
    _rate_limit(session_key, "search", _RATE_MAX_SEARCH_LIVE if live_web else _RATE_MAX_SEARCH)

    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    max_results = int(req.max_results or 0)
    if max_results <= 0:
        max_results = 10 if live_web else 8
    max_cap = 25 if live_web else 15
    if max_results > max_cap:
        max_results = max_cap

    # Reuse the existing research provider implementation.
    from research.search.providers.ddg import DDGProvider

    provider = DDGProvider()

    def _run():
        hits = provider.search([query], max_results=max_results)
        out: List[Dict[str, Any]] = []
        for h in hits[:max_results]:
            out.append(
                {
                    "title": getattr(h, "title", "") or "",
                    "url": getattr(h, "url", "") or "",
                    "snippet": getattr(h, "snippet", "") or "",
                    "source": getattr(h, "source", "ddg") or "ddg",
                }
            )
        # Remove empty URLs defensively
        out = [r for r in out if r.get("url")]
        return out

    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run)
    except Exception as exc:
        logger.warning("search: failed query=%r: %s", query, exc)
        raise HTTPException(status_code=502, detail=f"Search failed: {exc}")

    logger.info("search: query=%r results=%d purpose=%s", query, len(results), req.purpose)
    await _audit(
        request,
        session_key=session_key,
        tool="search",
        input_obj={"query": query, "max_results": max_results, "purpose": req.purpose},
        status_code=200,
        output_meta={"result_count": len(results)},
    )
    return {
        "query": query,
        "results": results,
        "policy": {"tier": "2-live" if live_web else "2"},
    }


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
    await _verify_openclaw_token(request, authorization)
    live_web = _is_live_web(request)
    _validate_url(req.url, live_web=live_web)
    session_key = request.headers.get("X-OpenClaw-SessionKey", "unknown")
    _rate_limit(session_key, "fetch", _RATE_MAX_FETCH_LIVE if live_web else _RATE_MAX_FETCH)

    # Import extraction helpers (lazy — keeps startup fast if trafilatura is heavy)
    from research.extract.html_trafilatura import extract_html

    _USER_AGENT = (
        "Mozilla/5.0 (compatible; HarvisResearchBot/1.0; "
        "+https://github.com/dulc3/harvis-aidev)"
    )

    parsed = urlparse(req.url)
    if parsed.scheme != "https" and not live_web:
        raise HTTPException(status_code=400, detail="Tier 2 web-fetch requires https URLs")

    # Fetch HTML ourselves so we can enforce content-type + size caps before extraction.
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(req.url)
            content_type = (resp.headers.get("content-type") or "").lower()
            if not any(
                t in content_type
                for t in ("text/html", "text/plain", "application/json", "application/xhtml+xml")
            ):
                raise HTTPException(
                    status_code=415,
                    detail=f"Unsupported content-type: {content_type or 'unknown'}",
                )
            raw = resp.content or b""
            if len(raw) > _MAX_FETCH_BYTES:
                raw = raw[:_MAX_FETCH_BYTES]
            html = raw.decode(errors="replace")

        # Extract text from fetched content
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: extract_html(
                url=req.url,
                html=html,
                user_agent=_USER_AGENT,
                timeout_s=20,
            ),
        )
    except HTTPException:
        raise
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

    await _audit(
        request,
        session_key=session_key,
        tool="web-fetch",
        input_obj={"url": req.url, "purpose": req.purpose},
        status_code=200,
        output_meta={"word_count": word_count, "title": title, "truncated": len(text) >= _MAX_TEXT_CHARS},
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
    await _verify_openclaw_token(request, authorization)

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

_KIMI_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
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
    await _verify_openclaw_token(request, authorization)

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


# ─── Vision query ───────────────────────────────────────────────────────────────

class VisionQueryRequest(BaseModel):
    image_b64: str          # raw base64, no data-URI prefix
    mime_type: str = "image/png"
    question: str = "Describe this image in detail."


@openclaw_proxy_router.post("/vision-query")
async def vision_query(
    req: VisionQueryRequest,
    request: Request,
) -> Dict[str, Any]:
    """Analyze a base64 image with Kimi K2.5 vision.

    Auth: Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
    Called by OpenClaw agents when they receive Discord image attachments.
    """
    _verify_openclaw_token(request.headers.get("Authorization"))

    # Resize if needed — cap at 1024px on longest side to stay within Moonshot limits
    try:
        import base64 as _b64
        import io
        from PIL import Image
        raw = _b64.b64decode(req.image_b64)
        img = Image.open(io.BytesIO(raw))
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024), Image.LANCZOS)
            buf = io.BytesIO()
            fmt = "JPEG" if req.mime_type == "image/jpeg" else "PNG"
            img.save(buf, format=fmt)
            req = req.model_copy(update={
                "image_b64": _b64.b64encode(buf.getvalue()).decode(),
                "mime_type": f"image/{fmt.lower()}",
            })
    except Exception as resize_err:
        logger.warning("vision-query: resize failed, using original: %s", resize_err)

    moonshot_key = os.getenv("MOONSHOT_API_KEY", "")
    moonshot_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1").rstrip("/")
    if not moonshot_key:
        raise HTTPException(status_code=503, detail="MOONSHOT_API_KEY not configured")

    content = [
        {"type": "text", "text": req.question},
        {"type": "image_url",
         "image_url": {"url": f"data:{req.mime_type};base64,{req.image_b64}"}},
    ]
    payload = {
        "model": "kimi-k2.5",
        "messages": [{"role": "user", "content": content}],
        "temperature": 1.0,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{moonshot_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {moonshot_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("vision-query: Kimi API error %s: %s", exc.response.status_code, exc.response.text[:200])
        raise HTTPException(status_code=502,
            detail=f"Moonshot vision error ({exc.response.status_code}): {exc.response.text[:200]}")
    except Exception as exc:
        logger.error("vision-query: request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Vision request failed: {exc}")

    analysis: str = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    ).strip()

    logger.info("vision-query: completed, response_len=%d", len(analysis))

    return {"analysis": analysis}
