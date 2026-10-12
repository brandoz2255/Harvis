"""Discover sources: find material on the web and add it to a notebook.

Fast research is one web search whose results the person ticks and adds as URL
sources. Deep research starts the existing multi-round research job, shows its
progress, then adds the finished report as a text source and offers the pages it
cited for import.

Nothing here fetches a page itself. Search goes through the shared search backend
(``agent_reach.tools.web_search``); every added URL becomes an ordinary URL source,
and the ingester reads it through the SSRF-safe client (public addresses only,
redirects re-checked, size capped). Deep research runs the existing job, gated by
the same per-person model limits as chat.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .manager import NotebookManager, NotebookNotFoundError
from .models import SourceType

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notebooks-discover"])

NOTEBOOK_STORAGE_PATH = os.getenv("NOTEBOOK_STORAGE_PATH", "/data/notebooks")
MAX_RESULTS = 10
MAX_ADD_AT_ONCE = 10
MAX_SOURCES_PER_NOTEBOOK = 50
SEARCHES_PER_MINUTE = 12
MIN_REPORT_CHARS = 200

_search_log: Dict[int, Deque[float]] = defaultdict(deque)


# notebooks.router includes this module at its bottom, so it is imported lazily here.
async def get_current_user_from_request(request: Request) -> Dict:
    from .router import get_current_user_from_request as _user

    return await _user(request)


def get_notebook_manager(request: Request) -> NotebookManager:
    from .router import get_notebook_manager as _manager

    return _manager(request)


# ─── Models ────────────────────────────────────────────────────────────────────
class DiscoverSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    max_results: int = Field(default=8, ge=1, le=MAX_RESULTS)


class DiscoverItem(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    title: Optional[str] = Field(default=None, max_length=300)


class DiscoverAddRequest(BaseModel):
    items: List[DiscoverItem] = Field(..., min_length=1, max_length=MAX_ADD_AT_ONCE)


class DeepStartRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    model: Optional[str] = None


# ─── Helpers ───────────────────────────────────────────────────────────────────
def site_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def clean_http_url(url: str) -> str:
    """The URL if it is plain http(s) with a host, else ''. Private hosts are refused later by the fetcher."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return url


def shape_results(raw: Dict[str, Any], limit: int) -> List[Dict[str, str]]:
    """Search backend output as title/site/snippet rows with only http(s) links."""
    rows: List[Dict[str, str]] = []
    for item in (raw or {}).get("results") or []:
        url = clean_http_url(str(item.get("url") or ""))
        if not url:
            continue
        rows.append({
            "title": (item.get("title") or "").strip() or site_of(url) or url,
            "url": url,
            "site": site_of(url),
            "snippet": (item.get("snippet") or "").strip()[:300],
        })
        if len(rows) >= limit:
            break
    return rows


def _check_search_rate(user_id: int) -> None:
    now = time.monotonic()
    window = _search_log[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= SEARCHES_PER_MINUTE:
        raise HTTPException(429, "Too many searches in a minute. Wait a moment and try again.")
    window.append(now)


async def _own_notebook(manager: NotebookManager, notebook_id: UUID, user_id: int) -> None:
    try:
        await manager.get_notebook(notebook_id, user_id)
    except NotebookNotFoundError:
        raise HTTPException(404, "Notebook not found")


def _research():
    """The shared deep-research handler, or a 503 sentence when the feature is not installed."""
    try:
        # deep_research's package exports an APIRouter named `router`, so import the module by path.
        return importlib.import_module("deep_research.router")
    except Exception as exc:  # noqa: BLE001
        logger.warning("discover: deep research unavailable: %s", exc)
        raise HTTPException(503, "Deep research is not available on this server.")


def _own_run(dr, session_id: str, owner: str) -> None:
    dr._validate_session_id(session_id)
    if not dr._owns_in_memory(session_id, owner):
        raise HTTPException(404, "No research found for this run")


# ─── Fast research ─────────────────────────────────────────────────────────────
@router.post("/{notebook_id}/discover/search")
async def discover_search(
    notebook_id: UUID,
    body: DiscoverSearchRequest,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Web search for sources. Returns 5-10 results; nothing is added until the person ticks them."""
    await _own_notebook(manager, notebook_id, current_user["id"])
    _check_search_rate(int(current_user["id"]))
    from agent_reach.tools import web_search

    try:
        raw = await web_search(body.query, body.max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("discover: search failed: %s", exc)
        raise HTTPException(502, "The web search did not answer. Try again in a moment.")
    results = shape_results(raw, body.max_results)
    if not results:
        return {"query": body.query, "results": [], "message": "No results. Try different words."}
    return {"query": body.query, "results": results}


async def _add_urls(
    manager: NotebookManager,
    background_tasks: BackgroundTasks,
    notebook_id: UUID,
    user_id: int,
    items: List[Dict[str, str]],
    origin: str,
) -> Dict[str, Any]:
    """Create URL sources (skipping repeats) and queue each for the normal ingester."""
    from .ingestion import run_ingestion_task

    existing = await manager.list_sources(notebook_id, user_id)
    have = {(s.storage_path or "").rstrip("/") for s in existing}
    room = MAX_SOURCES_PER_NOTEBOOK - len(existing)
    added, skipped = [], []
    for item in items:
        url = clean_http_url(item.get("url", ""))
        if not url:
            skipped.append({"url": item.get("url", ""), "reason": "Only http and https links can be added."})
            continue
        if url.rstrip("/") in have:
            skipped.append({"url": url, "reason": "Already in this notebook."})
            continue
        if room <= 0:
            skipped.append({"url": url, "reason": f"A notebook holds at most {MAX_SOURCES_PER_NOTEBOOK} sources."})
            continue
        source = await manager.create_source(
            notebook_id=notebook_id,
            user_id=user_id,
            source_type=SourceType.URL,
            title=(item.get("title") or "").strip() or url,
            storage_path=url,
            metadata={"url": url, "discovered_by": origin},
        )
        background_tasks.add_task(run_ingestion_task, manager, source.id, user_id)
        have.add(url.rstrip("/"))
        room -= 1
        added.append({"id": str(source.id), "url": url, "title": source.title})
    return {"added": added, "skipped": skipped}


@router.post("/{notebook_id}/discover/add")
async def discover_add(
    notebook_id: UUID,
    body: DiscoverAddRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Add ticked results (or a report's cited pages) as URL sources."""
    await _own_notebook(manager, notebook_id, current_user["id"])
    items = [{"url": i.url, "title": i.title or ""} for i in body.items]
    return await _add_urls(manager, background_tasks, notebook_id, current_user["id"], items, "fast")


# ─── Deep research ─────────────────────────────────────────────────────────────
@router.post("/{notebook_id}/discover/deep")
async def discover_deep_start(
    notebook_id: UUID,
    body: DeepStartRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Start the existing deep-research job. Counts as one turn against the person's limits."""
    await _own_notebook(manager, notebook_id, current_user["id"])
    dr = _research()
    owner = str(current_user["id"])
    running = [
        sid for sid, e in dr._handler._active_tasks.items()
        if e.get("owner", "") == owner and e.get("status") == "running"
    ]
    if running:
        raise HTTPException(409, "A deep research run is already going. Wait for it to finish or cancel it.")
    from plugins.people.controls import require_turn

    pool = getattr(request.app.state, "pg_pool", None)
    model = await require_turn(pool, int(current_user["id"]), body.model or "")
    model = (model or await dr._resolve_research_model(request, current_user.get("id"))).strip()
    session_id = f"rp-{uuid.uuid4().hex[:12]}"
    dr._handler.start_research(
        session_id=session_id, query=body.query.strip(), llm_model=model, max_time=300, max_rounds=8, owner=owner
    )
    return {"session_id": session_id, "status": "running", "query": body.query.strip()}


@router.get("/{notebook_id}/discover/deep/{session_id}")
async def discover_deep_status(
    notebook_id: UUID,
    session_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    await _own_notebook(manager, notebook_id, current_user["id"])
    dr = _research()
    _own_run(dr, session_id, str(current_user["id"]))
    status = dr._handler.get_status(session_id)
    if status is None:
        raise HTTPException(404, "No research found for this run")
    progress = status.get("progress") or {}
    out = {
        "session_id": session_id,
        "status": status.get("status", "running"),
        "query": status.get("query", ""),
        "phase": progress.get("phase", ""),
        "message": str(progress.get("message") or "")[:300],
        "progress": progress,
    }
    if out["status"] == "done" and len((dr._handler.get_result(session_id) or "").strip()) < MIN_REPORT_CHARS:
        # The job ends "done" even when the model could not write the report (a model that is too
        # small or busy). Say so here instead of offering an import that cannot work.
        out["status"] = "error"
        out["error"] = (
            "The research read pages but could not write a report. The model may be too small or busy: "
            "try again, or pick a different model in the model picker."
        )
    elif out["status"] == "error":
        task = dr._handler._active_tasks.get(session_id) or {}
        out["error"] = str(task.get("result") or progress.get("message") or "The research run failed.")[:500]
    return out


@router.post("/{notebook_id}/discover/deep/{session_id}/cancel")
async def discover_deep_cancel(
    notebook_id: UUID,
    session_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    await _own_notebook(manager, notebook_id, current_user["id"])
    dr = _research()
    _own_run(dr, session_id, str(current_user["id"]))
    return {"cancelled": dr._handler.cancel_research(session_id)}


def _cited_pages(dr, session_id: str) -> List[Dict[str, str]]:
    seen, pages = set(), []
    for s in dr._handler.get_sources(session_id) or []:
        if not isinstance(s, dict):
            continue
        url = clean_http_url(str(s.get("url") or ""))
        if url and url not in seen:
            seen.add(url)
            pages.append({"url": url, "title": str(s.get("title") or url)[:300], "site": site_of(url)})
    return pages


@router.post("/{notebook_id}/discover/deep/{session_id}/import")
async def discover_deep_import(
    notebook_id: UUID,
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Add the finished report as a text source and list the pages it cited for import."""
    user_id = current_user["id"]
    await _own_notebook(manager, notebook_id, user_id)
    dr = _research()
    _own_run(dr, session_id, str(user_id))
    status = dr._handler.get_status(session_id) or {}
    if status.get("status") == "running":
        raise HTTPException(409, "The research is still running.")
    report = (dr._handler.get_result(session_id) or "").strip()
    if status.get("status") in ("error", "cancelled") or len(report) < MIN_REPORT_CHARS:
        raise HTTPException(422, "This run did not produce a report to add.")
    cited = _cited_pages(dr, session_id)

    for s in await manager.list_sources(notebook_id, user_id):
        if (s.metadata or {}).get("research_session") == session_id:
            return {"source": {"id": str(s.id), "title": s.title}, "already_added": True, "cited": cited}

    query = str(status.get("query") or "Research").strip()
    title = f"Research: {query[:80]}"
    user_dir = os.path.join(NOTEBOOK_STORAGE_PATH, str(user_id), str(notebook_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, f"{uuid.uuid4()}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# {title}\n\n{report}\n")
    source = await manager.create_source(
        notebook_id=notebook_id,
        user_id=user_id,
        source_type=SourceType.MARKDOWN,
        title=title,
        storage_path=path,
        content_text=report,
        metadata={"research_session": session_id, "discovered_by": "deep", "size": len(report), "extension": "md"},
    )
    from .ingestion import run_ingestion_task

    background_tasks.add_task(run_ingestion_task, manager, source.id, user_id)
    return {"source": {"id": str(source.id), "title": title}, "already_added": False, "cited": cited}
