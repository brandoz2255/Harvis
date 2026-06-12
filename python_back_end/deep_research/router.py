"""
Deep Research API — /api/research/* (agentic multi-step research + visual reports).

Ported (trimmed) from Odysseus's research_routes.py:
  - auth via Harvis's auth_optimized (mirrors notebooks/router.py), owner-scoped
  - LLM via Harvis Ollama bridge (no endpoint-resolver / ModelEndpoint DB)
  - spinoff (chat-session seeding) dropped for v1

Endpoints:
  POST /api/research/start              — launch a research job (returns session_id)
  GET  /api/research/stream/{id}        — SSE progress stream
  GET  /api/research/status/{id}        — poll status
  GET  /api/research/active             — list this user's running jobs
  POST /api/research/cancel/{id}        — cancel
  POST /api/research/result/{id}        — fetch + consume result
  POST /api/research/result-peek/{id}   — fetch without consuming
  GET  /api/research/report/{id}        — visual HTML report
  GET  /api/research/library            — list completed research
  GET  /api/research/detail/{id}        — full JSON for one result
  POST /api/research/{id}/archive       — soft-archive / restore
  DELETE /api/research/{id}             — delete
  POST /api/research/{id}/hide-image    — hide an OG image in the report
  POST /api/research/{id}/unhide-images — clear hidden images
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .handler import RESEARCH_DATA_DIR, ResearchHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["deep-research"])

# Single shared handler (owns the in-memory task registry).
_handler = ResearchHandler()

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,128}$")

# Default Ollama model for research synthesis. Override per-request (body.model)
# or globally via DEEP_RESEARCH_MODEL. No keyword-based auto-routing.
DEFAULT_RESEARCH_MODEL = os.getenv("DEEP_RESEARCH_MODEL", "llama3.1:8b")


# ─── Auth (mirror notebooks/router.py — late import avoids circular import) ───
async def get_current_user_from_request(request: Request) -> Dict:
    from auth_optimized import get_current_user_optimized
    from fastapi.security import HTTPAuthorizationCredentials

    auth_header = request.headers.get("Authorization")
    credentials = None
    if auth_header and auth_header.startswith("Bearer "):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
    pool = getattr(request.app.state, "pg_pool", None)
    return await get_current_user_optimized(credentials=credentials, request=request, pool=pool)


def _owner(current_user: Dict) -> str:
    return str(current_user.get("id", ""))


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(400, "Invalid session ID format")


def _owns_in_memory(session_id: str, owner: str) -> bool:
    """Ownership check for an in-flight task; falls back to the on-disk JSON."""
    entry = _handler._active_tasks.get(session_id)
    if entry is not None:
        return entry.get("owner", "") == owner
    path = RESEARCH_DATA_DIR / f"{session_id}.json"
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("owner") == owner
    except Exception:
        return False


def _assert_owns_disk(session_id: str, owner: str) -> dict:
    """404-not-403 ownership gate for a session's on-disk JSON. Returns the data."""
    path = RESEARCH_DATA_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "Research not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(404, "Research not found")
    if data.get("owner") != owner:
        raise HTTPException(404, "Research not found")
    return data


# ─── Launch ───────────────────────────────────────────────────────────────────
class ResearchStartRequest(BaseModel):
    query: str
    max_rounds: int = Field(default=0, ge=0, le=20)  # 0 = Auto (AI decides), capped at 20
    model: Optional[str] = None
    search_provider: Optional[str] = None
    max_time: int = Field(default=300, ge=60, le=1800)
    extraction_timeout: Optional[int] = Field(default=None, ge=15, le=3600)
    extraction_concurrency: Optional[int] = Field(default=None, ge=1, le=12)
    category: Optional[str] = None


@router.post("/start")
async def research_start(body: ResearchStartRequest, current_user: Dict = Depends(get_current_user_from_request)):
    owner = _owner(current_user)
    session_id = f"rp-{uuid.uuid4().hex[:12]}"
    model = (body.model or DEFAULT_RESEARCH_MODEL).strip()
    effective_max_rounds = body.max_rounds if body.max_rounds > 0 else 20
    _handler.start_research(
        session_id=session_id, query=body.query, llm_model=model,
        max_time=body.max_time, max_rounds=effective_max_rounds,
        search_provider=body.search_provider or None, category=body.category or None,
        extraction_timeout=body.extraction_timeout,
        extraction_concurrency=body.extraction_concurrency, owner=owner,
    )
    return {"session_id": session_id, "status": "running", "query": body.query, "model": model}


@router.get("/active")
async def research_active(current_user: Dict = Depends(get_current_user_from_request)):
    owner = _owner(current_user)
    active = [
        {"session_id": sid, "query": e.get("query", ""), "status": "running",
         "progress": e.get("progress", {}), "started_at": e.get("started_at", 0)}
        for sid, e in _handler._active_tasks.items()
        if e.get("owner", "") == owner and e.get("status") == "running"
    ]
    return {"active": active}


@router.get("/status/{session_id}")
async def research_status(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    if not _owns_in_memory(session_id, _owner(current_user)):
        raise HTTPException(404, "No research found for this session")
    status = _handler.get_status(session_id)
    if status is None:
        raise HTTPException(404, "No research found for this session")
    return status


@router.get("/stream/{session_id}")
async def research_stream(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    if not _owns_in_memory(session_id, _owner(current_user)):
        raise HTTPException(404, "No research found for this session")

    async def _generate():
        last = None
        while True:
            status = _handler.get_status(session_id)
            if status is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            st = status.get("status", "")
            progress = status.get("progress", {})
            if progress != last:
                last = progress
                yield f"data: {json.dumps({**progress, 'status': st})}\n\n"
            if st != "running":
                final = {"status": st, "final": True}
                task = _handler._active_tasks.get(session_id, {})
                if st == "error" and task.get("result"):
                    final["error"] = str(task["result"])[:500]
                yield f"data: {json.dumps(final)}\n\n"
                return
            await asyncio.sleep(1.5)

    return StreamingResponse(
        _generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/cancel/{session_id}")
async def research_cancel(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    if not _owns_in_memory(session_id, _owner(current_user)):
        raise HTTPException(404, "No research found for this session")
    return {"cancelled": _handler.cancel_research(session_id)}


@router.post("/result/{session_id}")
async def research_result(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    if not _owns_in_memory(session_id, _owner(current_user)):
        raise HTTPException(404, "No research result available")
    result = _handler.get_result(session_id)
    if result is None:
        raise HTTPException(404, "No research result available")
    sources = _handler.get_sources(session_id) or []
    raw_findings = _handler.get_raw_findings(session_id) or []
    _handler.clear_result(session_id)
    return {"result": result, "sources": sources, "raw_findings": raw_findings}


@router.post("/result-peek/{session_id}")
async def research_result_peek(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    if not _owns_in_memory(session_id, _owner(current_user)):
        raise HTTPException(404, "No research found for this session")
    result = _handler.get_result(session_id)
    if result is None:
        data = _handler._get_session_json(session_id)
        if data:
            return {"result": data.get("result", ""), "sources": data.get("sources", []),
                    "raw_findings": data.get("raw_findings", []), "category": data.get("category") or ""}
        raise HTTPException(404, "No research result available")
    return {"result": result, "sources": _handler.get_sources(session_id) or [],
            "raw_findings": _handler.get_raw_findings(session_id) or [], "category": ""}


@router.get("/report/{session_id}")
async def research_report(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    _assert_owns_disk(session_id, _owner(current_user))
    try:
        html = _handler.get_report_html(session_id)
    except Exception as e:
        logger.error("deep_research: report error: %s", e, exc_info=True)
        raise HTTPException(500, f"Report generation failed: {e}")
    if html is None:
        raise HTTPException(404, "No visual report available for this session")
    return HTMLResponse(content=html)


@router.get("/library")
async def research_library(
    current_user: Dict = Depends(get_current_user_from_request),
    search: Optional[str] = Query(None),
    sort: str = Query("recent"),
    limit: int = Query(50),
    archived: bool = Query(False),
):
    owner = _owner(current_user)
    items = []
    for p in RESEARCH_DATA_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("owner") != owner:
                continue
            if bool(d.get("archived")) != archived:
                continue
            query = d.get("query", "")
            if search and search.lower() not in query.lower():
                continue
            items.append({
                "id": p.stem, "query": query, "category": d.get("category") or "",
                "source_count": len(d.get("sources", [])), "status": d.get("status", "done"),
                "duration": (d.get("stats") or {}).get("Duration", ""),
                "rounds": (d.get("stats") or {}).get("Rounds", ""),
                "started_at": d.get("started_at", 0), "completed_at": d.get("completed_at", 0),
                "archived": bool(d.get("archived")),
            })
        except Exception:
            continue
    if sort == "recent":
        items.sort(key=lambda x: x["completed_at"] or 0, reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda x: x["completed_at"] or 0)
    elif sort == "most-messages":
        items.sort(key=lambda x: x["source_count"], reverse=True)
    elif sort == "alpha":
        items.sort(key=lambda x: x["query"].lower())
    return {"research": items[:limit], "total": len(items)}


@router.get("/detail/{session_id}")
async def research_detail(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    return _assert_owns_disk(session_id, _owner(current_user))


@router.post("/{session_id}/archive")
async def research_archive(session_id: str, current_user: Dict = Depends(get_current_user_from_request), archived: bool = Query(True)):
    _validate_session_id(session_id)
    data = _assert_owns_disk(session_id, _owner(current_user))
    data["archived"] = bool(archived)
    (RESEARCH_DATA_DIR / f"{session_id}.json").write_text(json.dumps(data), encoding="utf-8")
    return {"ok": True, "id": session_id, "archived": bool(archived)}


@router.delete("/{session_id}")
async def research_delete(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    _assert_owns_disk(session_id, _owner(current_user))
    (RESEARCH_DATA_DIR / f"{session_id}.json").unlink(missing_ok=True)
    return {"deleted": True}


class HideImageRequest(BaseModel):
    url: str


@router.post("/{session_id}/hide-image")
async def research_hide_image(session_id: str, body: HideImageRequest, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    _assert_owns_disk(session_id, _owner(current_user))
    if not _handler.hide_image(session_id, body.url):
        raise HTTPException(404, "Research not found")
    return {"ok": True}


@router.post("/{session_id}/unhide-images")
async def research_unhide_images(session_id: str, current_user: Dict = Depends(get_current_user_from_request)):
    _validate_session_id(session_id)
    _assert_owns_disk(session_id, _owner(current_user))
    if not _handler.unhide_all_images(session_id):
        raise HTTPException(404, "Research not found")
    return {"ok": True}
