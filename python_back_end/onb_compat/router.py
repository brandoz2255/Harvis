"""
open-notebook compatibility facade — `/onb-api/*`.

Implements the endpoints the vendored open-notebook frontend calls
(`front_end/open-notebook/src/lib/api/*.ts`), backed by Harvis's notebooks
manager (`notebooks/manager.py`) + ingestion + rag_chat. Reuses the notebooks
router's manager + auth dependencies so a single Harvis JWT authenticates here too.

Scope (this slice): config + notebooks CRUD + notes CRUD + sources CRUD/ingest.
Chat sessions/context, transformations, podcasts, search, insights are added in a
follow-up slice (they need a `notebook_chat_sessions` table + rag_chat wiring).
"""

import os
import re
import json
import math
import asyncio
import uuid as _uuid
import logging
import httpx
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse

from notebooks.router import (
    get_notebook_manager,
    get_current_user_from_request,
    NOTEBOOK_STORAGE_PATH,
)
from notebooks.manager import (
    NotebookManager,
    NotebookNotFoundError,
    SourceNotFoundError,
    NoteNotFoundError,
)
from notebooks.models import (
    CreateNotebookRequest,
    UpdateNotebookRequest,
    CreateNoteRequest,
    UpdateNoteRequest,
    SourceType,
    NoteType,
)
from notebooks.ingestion import run_ingestion_task, IngestionService
from notebooks.rag_chat import RAGChatService

logger = logging.getLogger(__name__)

OLLAMA_URL = (
    os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_URL") or "http://ollama:11434"
)

# Chat model used when a session/request specifies none. These are a PREFERENCE
# order, not a guarantee: reliable non-reasoning instruct models first, because
# gpt-oss and friends intermittently emit every token into the `thinking` channel
# and return blank `response` content (empty chat bubble). This used to be a single
# hardcoded name, which meant a deploy without that exact model 404'd on every
# notebook chat call — so we now fall through to whatever Ollama actually has.
ONB_DEFAULT_CHAT_MODEL = os.getenv("ONB_DEFAULT_CHAT_MODEL", "").strip()
_PREFERRED_CHAT_MODELS = ("llama3.1:8b", "granite4.1:8b", "gemma4:e4b", "qwen3:4b")
_resolved_chat_model: Optional[str] = None


async def _default_chat_model() -> str:
    """
    Best available local chat model: explicit env override, else the first
    preferred model Ollama actually reports, else any installed generative model.
    Cached after the first successful resolution.
    """
    global _resolved_chat_model

    if ONB_DEFAULT_CHAT_MODEL:
        return ONB_DEFAULT_CHAT_MODEL
    if _resolved_chat_model:
        return _resolved_chat_model

    installed: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
        if resp.status_code == 200:
            installed = [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        logger.warning("onb_compat: could not list Ollama models", exc_info=True)

    for name in _PREFERRED_CHAT_MODELS:
        if name in installed:
            _resolved_chat_model = name
            return name

    generative = [m for m in installed if "embed" not in m.lower()]
    if generative:
        _resolved_chat_model = generative[0]
        logger.info(
            "onb_compat: none of %s installed; defaulting to %s",
            ", ".join(_PREFERRED_CHAT_MODELS), generative[0],
        )
        return generative[0]

    logger.error(
        "onb_compat: Ollama at %s reports no usable chat model — notebook chat "
        "will fail until one is pulled (e.g. `ollama pull llama3.1:8b`).",
        OLLAMA_URL,
    )
    return _PREFERRED_CHAT_MODELS[0]

router = APIRouter(prefix="/onb-api", tags=["onb_compat"])


# ─── Translators: Harvis models → open-notebook response shapes ────────────────

# open-notebook's frontend was built for SurrealDB-style record ids ("source:<uuid>",
# "note:<uuid>", "source_insight:<uuid>") and threads them through source cards,
# citation clicks, and sourcesApi.get unchanged. The Harvis facade stores bare UUIDs,
# so accept either form: strip a leading recognised type prefix before parsing.
_ID_TYPE_PREFIXES = ("source_insight", "source", "note", "insight")


def _clean_uuid(raw: str) -> UUID:
    s = (raw or "").strip()
    if ":" in s:
        head, tail = s.split(":", 1)
        if head in _ID_TYPE_PREFIXES:
            s = tail.strip()
    return UUID(s)


def _iso(dt) -> str:
    return dt.isoformat() if hasattr(dt, "isoformat") else (str(dt) if dt else "")


def nb_to_onb(nb) -> Dict[str, Any]:
    return {
        "id": str(nb.id),
        "name": nb.title or "",
        "emoji": getattr(nb, "emoji", None),
        "description": nb.description or "",
        "archived": not getattr(nb, "is_active", True),
        "created": _iso(nb.created_at),
        "updated": _iso(nb.updated_at),
        "source_count": nb.source_count or 0,
        "note_count": nb.note_count or 0,
    }


def note_to_onb(n) -> Dict[str, Any]:
    nt = n.type.value if hasattr(n.type, "value") else (n.type or "user_note")
    return {
        "id": str(n.id),
        "title": n.title,
        "content": n.content,
        "note_type": nt,
        "created": _iso(n.created_at),
        "updated": _iso(n.updated_at),
    }


def source_to_onb(s, full_text: Optional[str] = None) -> Dict[str, Any]:
    t = s.type.value if hasattr(s.type, "value") else (s.type or "")
    sp = getattr(s, "storage_path", None)
    asset = None
    if sp:
        asset = {"url": sp} if t in ("url", "youtube") else {"file_path": sp}
    status = s.status.value if hasattr(s.status, "value") else (s.status or "")
    d = {
        "id": str(s.id),
        "title": s.title,
        "topics": [],
        "asset": asset,
        "embedded": (getattr(s, "chunk_count", 0) or 0) > 0,
        "embedded_chunks": getattr(s, "chunk_count", 0) or 0,
        "insights_count": 0,
        "created": _iso(s.created_at),
        "updated": _iso(s.updated_at),
        "file_available": bool(sp),
        "status": status,
    }
    if full_text is not None:
        d["full_text"] = full_text
        d["notebooks"] = [str(s.notebook_id)]
    return d


def _onb_type_to_harvis(ext: str) -> SourceType:
    ext = (ext or "").lower()
    if ext == "pdf":
        return SourceType.PDF
    if ext in ("md", "markdown"):
        return SourceType.MARKDOWN
    if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
        return SourceType.IMAGE
    if ext in ("mp3", "wav", "m4a", "ogg"):
        return SourceType.AUDIO
    return SourceType.DOC


# ─── Config (frontend calls /api/config on boot via ConnectionGuard) ───────────

@router.get("/config")
async def onb_config():
    return {"version": "harvis-onb", "latestVersion": None, "hasUpdate": False,
            "dbStatus": {"connected": True}}


@router.get("/auth/status")
async def auth_status():
    # Harvis handles auth at the shell; the vendored app skips its own login when
    # auth_enabled=false, and the client still sends Harvis's JWT (validated per-call).
    return {"auth_enabled": False}


# ─── Notebooks ─────────────────────────────────────────────────────────────────

@router.get("/notebooks")
async def list_notebooks(
    request: Request,
    archived: Optional[bool] = None,
    order_by: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    notebooks, _ = await manager.list_notebooks(current_user["id"], limit=200, offset=0)
    return [nb_to_onb(nb) for nb in notebooks]


@router.get("/notebooks/{notebook_id}")
async def get_notebook(
    notebook_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        nb = await manager.get_notebook(UUID(notebook_id), current_user["id"])
        return nb_to_onb(nb)
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")


@router.post("/notebooks")
async def create_notebook(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    raw_name = (body.get("name") or "").strip()
    # No name prompt: a blank new notebook gets a placeholder + default emoji now; the AI
    # generates a real title + emoji once its first source lands (POST .../autoname below).
    name = raw_name or "New notebook"
    emoji = body.get("emoji") or (None if raw_name else "\U0001F4D3")  # 📓
    nb = await manager.create_notebook(
        current_user["id"],
        CreateNotebookRequest(title=name, description=body.get("description"), emoji=emoji),
    )
    return nb_to_onb(nb)


@router.post("/notebooks/{notebook_id}/autoname")
async def onb_autoname_notebook(
    notebook_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Generate an emoji (and, for still-untitled notebooks, a title) from the notebook's
    sources via the LLM. Mirrors the native /api/notebooks/{id}/autoname logic."""
    try:
        nbid = UUID(notebook_id)
        nb = await manager.get_notebook(nbid, current_user["id"])
        sources = await manager.list_sources(nbid, current_user["id"])
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")

    current_title = (nb.title or "").strip()
    is_untitled = current_title.lower() in ("", "untitled", "untitled notebook", "new notebook")
    fallback_title = (
        (sources[0].title if sources and sources[0].title else current_title) or "Untitled notebook"
    )

    gen_title, gen_emoji, gen_synopsis = None, None, None
    if sources:
        # Include a short content excerpt per source, not just the title — a generic
        # source title (e.g. "Pasted text") alone yields a generic notebook name, so
        # feed the LLM what the content is actually ABOUT.
        snippet_by_id: Dict[str, str] = {}
        try:
            sids = [s.id for s in sources[:6]]
            async with manager.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, content_text FROM notebook_sources WHERE id = ANY($1::uuid[])",
                    sids,
                )
            for row in rows:
                txt = (row["content_text"] or "").strip()
                if txt:
                    snippet_by_id[str(row["id"])] = " ".join(txt.split())[:240]
        except Exception as e:
            logger.debug(f"onb autoname snippet fetch failed: {e}")
        source_lines = "\n".join(
            (
                f"- {(s.title or 'Untitled source')} ({getattr(s.type, 'value', s.type)})"
                + (f": {snippet_by_id[str(s.id)]}" if str(s.id) in snippet_by_id else "")
            )
            for s in sources[:12]
        )
        prompt = (
            "You are titling and summarizing a research notebook built from the sources "
            "below (titles + content excerpts). Produce three things:\n"
            "1. title — a broad, descriptive title capturing the SINGLE most general "
            "overarching theme across ALL the sources; comprehensive and evocative (e.g. "
            '"The Evolution of Gaming: From Ancient Stones to Adaptive AI" for a mix of '
            "game-history sources). It should read like a real notebook/article title, "
            "NOT a 2-4 word label. As more sources are added the theme should broaden to "
            "the most general topic that covers them all.\n"
            "2. emoji — one emoji that fits the overall theme.\n"
            "3. synopsis — a 3 to 5 sentence paragraph describing the topics covered and "
            "the general scope of the collection, grounded in the sources (start it like "
            '"The provided sources examine...").\n'
            "Respond with ONLY a compact JSON object: "
            '{"title": "...", "emoji": "...", "synopsis": "..."}. '
            "No prose, no markdown, no code fences.\n\n"
            f"Number of sources: {len(sources)}\nSources:\n" + source_lines
        )
        try:
            from notebooks.rag_chat import FALLBACK_MODELS
        except Exception:
            FALLBACK_MODELS = []
        autoname_models = ["granite4.1:8b", "llama3.1:8b", "gemma4:e4b"]
        autoname_models += [m for m in FALLBACK_MODELS if m not in autoname_models]
        for model in autoname_models:
            try:
                async with httpx.AsyncClient(timeout=60.0) as c:
                    r = await c.post(
                        f"{OLLAMA_URL.rstrip('/')}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False,
                              "options": {"temperature": 0.4, "num_predict": 400, "num_ctx": 4096}},
                    )
                if r.status_code != 200:
                    continue
                text = (r.json().get("response") or "").strip()
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if not m:
                    continue
                obj = json.loads(m.group(0))
                gen_title = ((obj.get("title") or "").strip().strip('"').strip())[:140] or None
                gen_emoji = ((obj.get("emoji") or "").strip())[:8] or None
                gen_synopsis = ((obj.get("synopsis") or obj.get("description") or "").strip())[:1800] or None
                if gen_title or gen_emoji or gen_synopsis:
                    logger.info(f"onb autoname {notebook_id}: model={model} title={gen_title!r} emoji={gen_emoji!r} synopsis_len={len(gen_synopsis or '')}")
                    break
            except Exception as e:
                logger.debug(f"onb autoname model {model} failed: {e}")
                continue

    # The frontend owns WHEN to (re)name (it calls this as sources accumulate, and
    # freezes once the user renames manually), so when the LLM produced a title we
    # persist it regardless of the untitled check — only fall back to the existing /
    # first-source title when generation failed.
    if gen_title:
        final_title = gen_title
    elif current_title and not is_untitled:
        final_title = current_title
    else:
        final_title = fallback_title
    final_emoji = gen_emoji or getattr(nb, "emoji", None) or "\U0001F4D3"
    final_description = gen_synopsis or getattr(nb, "description", None)
    try:
        await manager.update_notebook(
            nbid, current_user["id"],
            UpdateNotebookRequest(
                title=final_title if final_title != current_title else None,
                emoji=final_emoji,
                # Only (over)write the synopsis when we actually generated one; never
                # wipe an existing description with an empty value.
                description=gen_synopsis if gen_synopsis else None,
            ),
        )
    except Exception as e:
        logger.error(f"onb autoname persist failed: {e}")
    return {"title": final_title, "emoji": final_emoji, "description": final_description or ""}


@router.put("/notebooks/{notebook_id}")
async def update_notebook(
    notebook_id: str,
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        # archived=true → soft-delete (Harvis is_active=FALSE). name/description → update.
        if body.get("archived") is True:
            await manager.delete_notebook(UUID(notebook_id), current_user["id"])
            nb = await manager.get_notebook(UUID(notebook_id), current_user["id"])  # may 404
            return nb_to_onb(nb)
        nb = await manager.update_notebook(
            UUID(notebook_id), current_user["id"],
            UpdateNotebookRequest(title=body.get("name"), description=body.get("description")),
        )
        return nb_to_onb(nb)
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")


@router.get("/notebooks/{notebook_id}/delete-preview")
async def delete_preview(
    notebook_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        stats = await manager.get_notebook_stats(UUID(notebook_id), current_user["id"])
        nb = await manager.get_notebook(UUID(notebook_id), current_user["id"])
        return {
            "notebook_id": notebook_id,
            "notebook_name": nb.title,
            "note_count": stats.get("note_count", 0),
            "exclusive_source_count": stats.get("source_count", 0),
            "shared_source_count": 0,
        }
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")


@router.delete("/notebooks/{notebook_id}")
async def delete_notebook(
    notebook_id: str,
    request: Request,
    delete_exclusive_sources: bool = False,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    ok = await manager.delete_notebook(UUID(notebook_id), current_user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return {"message": "deleted", "deleted_notes": 0, "deleted_sources": 0, "unlinked_sources": 0}


# Link / unlink a source to a notebook. Harvis sources are single-notebook, so
# "link" is a no-op (already owned) and "unlink" deletes the source from it.
@router.post("/notebooks/{notebook_id}/sources/{source_id}")
async def link_source(notebook_id: str, source_id: str, request: Request,
                      current_user: Dict = Depends(get_current_user_from_request),
                      manager: NotebookManager = Depends(get_notebook_manager)):
    return {"message": "linked"}


@router.delete("/notebooks/{notebook_id}/sources/{source_id}")
async def unlink_source(notebook_id: str, source_id: str, request: Request,
                        current_user: Dict = Depends(get_current_user_from_request),
                        manager: NotebookManager = Depends(get_notebook_manager)):
    await manager.delete_source(_clean_uuid(source_id), current_user["id"])
    return {"message": "unlinked"}


# ─── Notes ───────────────────────────────────────────────────────────────────

@router.get("/notes")
async def list_notes(
    request: Request,
    notebook_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if not notebook_id:
        return []
    notes, _ = await manager.list_notes(UUID(notebook_id), current_user["id"], limit=200, offset=0)
    return [note_to_onb(n) for n in notes]


@router.get("/notes/{note_id}")
async def get_note(note_id: str, request: Request,
                   current_user: Dict = Depends(get_current_user_from_request),
                   manager: NotebookManager = Depends(get_notebook_manager)):
    try:
        n = await manager.get_note(_clean_uuid(note_id), current_user["id"])
        return note_to_onb(n)
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")


@router.post("/notes")
async def create_note(body: Dict[str, Any], request: Request,
                      current_user: Dict = Depends(get_current_user_from_request),
                      manager: NotebookManager = Depends(get_notebook_manager)):
    nb_id = body.get("notebook_id")
    if not nb_id:
        raise HTTPException(status_code=400, detail="notebook_id required")
    nt = body.get("note_type") or "user_note"
    try:
        ntype = NoteType(nt)
    except Exception:
        ntype = NoteType.USER_NOTE
    n = await manager.create_note(
        UUID(nb_id), current_user["id"],
        CreateNoteRequest(type=ntype, title=body.get("title"), content=body.get("content") or ""),
    )
    return note_to_onb(n)


@router.put("/notes/{note_id}")
async def update_note(note_id: str, body: Dict[str, Any], request: Request,
                      current_user: Dict = Depends(get_current_user_from_request),
                      manager: NotebookManager = Depends(get_notebook_manager)):
    try:
        n = await manager.update_note(
            _clean_uuid(note_id), current_user["id"],
            UpdateNoteRequest(title=body.get("title"), content=body.get("content")),
        )
        return note_to_onb(n)
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, request: Request,
                      current_user: Dict = Depends(get_current_user_from_request),
                      manager: NotebookManager = Depends(get_notebook_manager)):
    await manager.delete_note(_clean_uuid(note_id), current_user["id"])
    return {"message": "deleted"}


# ─── Sources ─────────────────────────────────────────────────────────────────

@router.get("/sources")
async def list_sources(
    request: Request,
    notebook_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if notebook_id:
        srcs = await manager.list_sources(UUID(notebook_id), current_user["id"])
        return [source_to_onb(s) for s in srcs]
    # Global list: all sources across the user's notebooks (the Sources page).
    notebooks, _ = await manager.list_notebooks(current_user["id"], limit=200, offset=0)
    out: List[Dict[str, Any]] = []
    for nb in notebooks:
        try:
            for s in await manager.list_sources(nb.id, current_user["id"]):
                out.append(source_to_onb(s))
        except Exception:
            continue
    return out


@router.get("/sources/{source_id}")
async def get_source(source_id: str, request: Request,
                     current_user: Dict = Depends(get_current_user_from_request),
                     manager: NotebookManager = Depends(get_notebook_manager)):
    try:
        s = await manager.get_source(_clean_uuid(source_id), current_user["id"])
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    # The extracted transcript/article text lives in notebook_sources.content_text
    # (ingestion populates it for url/pdf/doc/youtube/image/text). For link sources
    # storage_path is the URL — reading it as a file fails — so prefer content_text;
    # fall back to a local file only when content_text is empty.
    full_text = ""
    try:
        async with manager.db_pool.acquire() as conn:
            full_text = (await conn.fetchval(
                "SELECT content_text FROM notebook_sources WHERE id = $1", _clean_uuid(source_id)
            )) or ""
    except Exception:
        full_text = ""
    if not full_text:
        sp = getattr(s, "storage_path", None)
        try:
            if sp and os.path.exists(sp):
                with open(sp, "r", encoding="utf-8", errors="ignore") as f:
                    full_text = f.read()
        except Exception:
            full_text = ""
    return source_to_onb(s, full_text=full_text)


@router.post("/sources")
async def create_source(
    request: Request,
    background_tasks: BackgroundTasks,
    type: str = Form(...),
    notebook_id: Optional[str] = Form(None),
    notebooks: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    transformations: Optional[str] = Form(None),
    embed: str = Form("false"),
    delete_source: str = Form("false"),
    async_processing: str = Form("false"),
    file: Optional[UploadFile] = File(None),
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    user_id = current_user["id"]
    nb_id = notebook_id
    if not nb_id and notebooks:
        try:
            arr = json.loads(notebooks)
            nb_id = arr[0] if arr else None
        except Exception:
            nb_id = None
    if not nb_id:
        raise HTTPException(status_code=400, detail="notebook_id (or notebooks[]) required")
    nb_uuid = UUID(nb_id)
    await manager.get_notebook(nb_uuid, user_id)  # ownership check

    if type == "link":
        if not url:
            raise HTTPException(status_code=400, detail="url required for type=link")
        src = await manager.create_source(
            nb_uuid, user_id, SourceType.URL, title or url, storage_path=url, metadata={},
        )
    elif type == "text":
        user_dir = os.path.join(NOTEBOOK_STORAGE_PATH, str(user_id), str(nb_uuid))
        os.makedirs(user_dir, exist_ok=True)
        path = os.path.join(user_dir, f"{_uuid.uuid4()}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
        src = await manager.create_source(
            nb_uuid, user_id, SourceType.TEXT, title or "Text", storage_path=path, metadata={},
        )
    elif type == "upload":
        if not file:
            raise HTTPException(status_code=400, detail="file required for type=upload")
        user_dir = os.path.join(NOTEBOOK_STORAGE_PATH, str(user_id), str(nb_uuid))
        os.makedirs(user_dir, exist_ok=True)
        fname = file.filename or "file"
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "bin"
        path = os.path.join(user_dir, f"{_uuid.uuid4()}.{ext}")
        with open(path, "wb") as f:
            f.write(await file.read())
        src = await manager.create_source(
            nb_uuid, user_id, _onb_type_to_harvis(ext), title or fname,
            storage_path=path, original_filename=fname, metadata={},
        )
    else:
        raise HTTPException(status_code=400, detail=f"unknown source type: {type}")

    background_tasks.add_task(run_ingestion_task, manager, src.id, user_id)
    return source_to_onb(src)


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, request: Request,
                        current_user: Dict = Depends(get_current_user_from_request),
                        manager: NotebookManager = Depends(get_notebook_manager)):
    await manager.delete_source(_clean_uuid(source_id), current_user["id"])
    return {"message": "deleted"}


@router.get("/sources/{source_id}/status")
async def source_status(source_id: str, request: Request,
                        current_user: Dict = Depends(get_current_user_from_request),
                        manager: NotebookManager = Depends(get_notebook_manager)):
    try:
        s = await manager.get_source(_clean_uuid(source_id), current_user["id"])
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    status = s.status.value if hasattr(s.status, "value") else (s.status or "")
    return {"status": status, "message": status, "processing_info": {}}


@router.post("/sources/{source_id}/retry")
async def retry_source(source_id: str, request: Request, background_tasks: BackgroundTasks,
                       current_user: Dict = Depends(get_current_user_from_request),
                       manager: NotebookManager = Depends(get_notebook_manager)):
    try:
        s = await manager.get_source(_clean_uuid(source_id), current_user["id"])
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    background_tasks.add_task(run_ingestion_task, manager, s.id, current_user["id"])
    return source_to_onb(s)


# ─── Chat: sessions + execute + context ────────────────────────────────────────

def _session_to_onb(row, message_count: int = 0) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"] or "New Chat",
        "created": _iso(row["created_at"]),
        "updated": _iso(row["updated_at"]),
        "message_count": message_count,
        "model_override": row["model_override"],
        "notebook_id": str(row["notebook_id"]),
    }


def _msg_to_onb(row) -> Dict[str, Any]:
    out = {
        "id": str(row["id"]),
        "type": row["role"],  # 'human' | 'ai'
        "content": row["content"],
        "timestamp": _iso(row["created_at"]),
    }
    cits = row.get("citations") if hasattr(row, "get") else None
    if cits:
        if isinstance(cits, str):
            try:
                cits = json.loads(cits)
            except Exception:
                cits = []
        if cits:
            out["citations"] = cits
    return out


def _pick_locator(quote: str) -> str:
    """A clean, findable single-line locator from a cited chunk. Overlap chunks can
    start mid-word (e.g. "e's Notebook LM!" from a "Google's Notebook LM!" cut), so
    pick the first sentence-like line and drop a leading partial-word fragment."""
    for line in (quote or "").splitlines():
        line = line.strip()
        if len(line) < 12:
            continue
        words = line.split()
        # drop a leading mid-word fragment (first token starts lowercase)
        if words and words[0][:1].islower():
            words = words[1:]
        cand = " ".join(words).strip()
        if len(cand) >= 16:
            return cand[:120]
    return (quote or "").strip()[:120]


def _build_citations_payload(cits) -> List[Dict[str, Any]]:
    """One entry PER cited chunk, in context order — `index` i corresponds to the
    model's `[cite:i]` marker. Each carries its OWN chunk snippet + locator so a chip
    jumps to the exact passage that grounded that sentence (NOT a per-source first
    chunk). The frontend assigns display numbers by distinct source_id + dedups."""
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(cits or [], 1):
        quote = (getattr(c, "quote", "") or "").strip()
        out.append({
            "index": i,
            "source_id": str(getattr(c, "source_id", "") or ""),
            "title": getattr(c, "source_title", None) or "",
            "snippet": quote[:280],
            "locator": _pick_locator(quote),
        })
    return out


def _context_source_ids(context: Dict[str, Any]) -> Optional[List[str]]:
    """Pull source ids out of open-notebook's execute `context.sources`. If none can
    be extracted, return None (search all the notebook's sources) rather than wrongly
    answering 'no context'."""
    ids: List[str] = []
    for item in (context or {}).get("sources", []) or []:
        if isinstance(item, dict):
            v = item.get("id") or item.get("source_id") or (item.get("source") or {}).get("id")
            if v:
                ids.append(str(v))
        elif isinstance(item, str):
            ids.append(item)
    return ids or None


@router.get("/chat/sessions")
async def list_chat_sessions(
    request: Request,
    notebook_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if not notebook_id:
        return []
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.id, s.notebook_id, s.title, s.model_override, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM notebook_chat_session_messages m WHERE m.session_id = s.id) AS mc
            FROM notebook_chat_sessions s
            WHERE s.notebook_id = $1 AND s.user_id = $2
            ORDER BY s.updated_at DESC
        """, UUID(notebook_id), current_user["id"])
    return [_session_to_onb(r, r["mc"]) for r in rows]


@router.post("/chat/sessions")
async def create_chat_session(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    nb = body.get("notebook_id")
    if not nb:
        raise HTTPException(status_code=400, detail="notebook_id required")
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO notebook_chat_sessions (notebook_id, user_id, title, model_override)
            VALUES ($1, $2, $3, $4)
            RETURNING id, notebook_id, title, model_override, created_at, updated_at
        """, UUID(nb), current_user["id"], body.get("title") or "New Chat", body.get("model_override"))
    return _session_to_onb(row, 0)


@router.get("/chat/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    async with manager.db_pool.acquire() as conn:
        s = await conn.fetchrow("""
            SELECT id, notebook_id, title, model_override, created_at, updated_at
            FROM notebook_chat_sessions WHERE id = $1 AND user_id = $2
        """, UUID(session_id), current_user["id"])
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        msgs = await conn.fetch("""
            SELECT id, role, content, citations, created_at FROM notebook_chat_session_messages
            WHERE session_id = $1 ORDER BY created_at
        """, UUID(session_id))
    d = _session_to_onb(s, len(msgs))
    d["messages"] = [_msg_to_onb(m) for m in msgs]
    return d


@router.put("/chat/sessions/{session_id}")
async def update_chat_session(
    session_id: str,
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    sets, params = [], [UUID(session_id), current_user["id"]]
    idx = 3
    if body.get("title") is not None:
        sets.append(f"title = ${idx}"); params.append(body["title"]); idx += 1
    if "model_override" in body:
        sets.append(f"model_override = ${idx}"); params.append(body.get("model_override")); idx += 1
    sets.append("updated_at = now()")
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            UPDATE notebook_chat_sessions SET {', '.join(sets)}
            WHERE id = $1 AND user_id = $2
            RETURNING id, notebook_id, title, model_override, created_at, updated_at
        """, *params)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_onb(row)


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM notebook_chat_sessions WHERE id = $1 AND user_id = $2",
            UUID(session_id), current_user["id"],
        )
    return {"message": "deleted"}


# The RAG model cites numbered ("[SOURCE 1: Para 5]", "[S1]", bare "SOURCE 1, Para 3")
# OR by title ("[Source: <Title-or-URL>, Para 5]"). Map each to a PER-OCCURRENCE
# "[cite:i]" marker, where i is the 1-based index of the cited context chunk (==
# _build_citations_payload[i-1]). Keeping the index (not collapsing to source_id)
# lets each inline chip jump to the EXACT passage; the frontend numbers by distinct
# source + dedups for display.
_SOURCE_NUM_RE = re.compile(r"\[\s*S(?:OURCE)?\s*(\d+)\s*(?::[^\]]*)?\]", re.IGNORECASE)
_SOURCE_TITLE_RE = re.compile(r"\[\s*sources?\s*:\s*([^\]]+?)\s*\]", re.IGNORECASE)
# Bare (un-bracketed) "SOURCE 1" / "SOURCE 1, Para 3" — the model often forgets the
# brackets. Spelled-out SOURCE only (not bare "S1") to avoid false positives.
_SOURCE_BARE_RE = re.compile(
    r"\bSOURCE\s+(\d+)(?:\s*[,:]?\s*(?:para|page|section)\s*\.?\s*\d+)?", re.IGNORECASE
)
_PARA_TAIL_RE = re.compile(r",\s*(?:para|page|section|p\.|pg)\b.*$", re.IGNORECASE)


def _rewrite_source_citations(answer: str, cits) -> str:
    if not answer or not cits:
        return answer
    n_cits = len(cits)

    # title → first context-chunk index for that source title
    title_to_idx = {}
    for i, c in enumerate(cits, 1):
        t = (getattr(c, "source_title", "") or "").strip().lower()
        if t:
            title_to_idx.setdefault(t, i)

    def _by_title(m):
        key = _PARA_TAIL_RE.sub("", m.group(1).strip()).strip().lower()
        if not key:
            return m.group(0)
        idx = title_to_idx.get(key)
        if not idx:
            for t, i in title_to_idx.items():
                if t in key or key in t:
                    idx = i
                    break
        return f"[cite:{idx}]" if idx else m.group(0)

    def _by_num(m):
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            return m.group(0)
        return f"[cite:{n}]" if 1 <= n <= n_cits else m.group(0)

    # Title form first (runs on the raw answer); bracketed-numbered next; bare
    # (un-bracketed) "SOURCE N" last. None matches the "[cite:i]" output of the
    # others ("cite" doesn't start with S / has no title colon-form).
    answer = _SOURCE_TITLE_RE.sub(_by_title, answer)
    answer = _SOURCE_NUM_RE.sub(_by_num, answer)
    answer = _SOURCE_BARE_RE.sub(_by_num, answer)
    return answer


@router.post("/chat/execute")
async def chat_execute(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    session_id = body.get("session_id")
    message = (body.get("message") or "").strip()
    if not session_id or not message:
        raise HTTPException(status_code=400, detail="session_id and message required")
    uid = current_user["id"]
    async with manager.db_pool.acquire() as conn:
        s = await conn.fetchrow("""
            SELECT id, notebook_id, model_override FROM notebook_chat_sessions
            WHERE id = $1 AND user_id = $2
        """, UUID(session_id), uid)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    model = body.get("model_override") or s["model_override"] or await _default_chat_model()
    source_ids = _context_source_ids(body.get("context") or {})

    rag = RAGChatService(manager)
    cits = []
    try:
        answer, cits = await rag.answer_for_session(
            s["notebook_id"], message, model, source_ids=source_ids,
        )
    except Exception as e:
        logger.error(f"chat_execute failed: {e}")
        answer = f"(error generating a response: {e})"
    # Turn "[SOURCE N]" markers into clickable "[source:<id>]" references.
    answer = _rewrite_source_citations(answer, cits)
    citations_payload = _build_citations_payload(cits)

    async with manager.db_pool.acquire() as conn:
        u = await conn.fetchrow("""
            INSERT INTO notebook_chat_session_messages (session_id, role, content)
            VALUES ($1, 'human', $2) RETURNING id, role, content, created_at
        """, UUID(session_id), message)
        a = await conn.fetchrow("""
            INSERT INTO notebook_chat_session_messages (session_id, role, content, citations)
            VALUES ($1, 'ai', $2, $3::jsonb)
            RETURNING id, role, content, citations, created_at
        """, UUID(session_id), answer, json.dumps(citations_payload))
        await conn.execute(
            "UPDATE notebook_chat_sessions SET updated_at = now() WHERE id = $1",
            UUID(session_id),
        )
    return {"session_id": session_id, "messages": [_msg_to_onb(u), _msg_to_onb(a)]}


@router.post("/chat/context")
async def chat_context(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Preview the context for the current source/note selection (token/char counts)."""
    cc = body.get("context_config") or {}
    src_modes: Dict[str, str] = cc.get("sources") or {}
    note_modes: Dict[str, str] = cc.get("notes") or {}
    included_sources = [sid for sid, mode in src_modes.items() if mode not in ("off", "none", None, "")]
    included_notes = [nid for nid, mode in note_modes.items() if mode not in ("off", "none", None, "")]

    char_count = 0
    ctx_sources: List[Dict[str, Any]] = []
    ctx_notes: List[Dict[str, Any]] = []
    async with manager.db_pool.acquire() as conn:
        if included_sources:
            rows = await conn.fetch("""
                SELECT s.id, s.title,
                       COALESCE(SUM(LENGTH(c.content)), 0) AS chars
                FROM notebook_sources s
                LEFT JOIN notebook_chunks c ON c.source_id = s.id
                WHERE s.id = ANY($1::uuid[])
                GROUP BY s.id, s.title
            """, [UUID(x) for x in included_sources])
            for r in rows:
                char_count += int(r["chars"] or 0)
                ctx_sources.append({"id": str(r["id"]), "title": r["title"]})
        if included_notes:
            rows = await conn.fetch("""
                SELECT id, title, COALESCE(LENGTH(content), 0) AS chars
                FROM notebook_notes WHERE id = ANY($1::uuid[])
            """, [UUID(x) for x in included_notes])
            for r in rows:
                char_count += int(r["chars"] or 0)
                ctx_notes.append({"id": str(r["id"]), "title": r["title"]})

    return {
        "context": {"sources": ctx_sources, "notes": ctx_notes},
        "token_count": char_count // 4,
        "char_count": char_count,
    }


# ─── Transformations + Insights (open-notebook contract) ───────────────────────
# open-notebook model: a "transformation" is a reusable named prompt; an "insight"
# is the RESULT of applying one to a source. Harvis stores results in
# `notebook_transformations` (CHECK-valid types) and has no transformation-def store,
# so the facade serves built-in transformations from code + custom ones from
# `notebook_transformation_defs`, and runs them synchronously (httpx async, no loop
# block) on the source's extracted text → persisted as a notebook_transformations row.

_ONB_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")

# id == notebook_transformations.transformation_type CHECK-valid value.
_BUILTIN_TRANSFORMATIONS = [
    {"id": "summarize", "title": "Summary",
     "description": "Concise summary of the source's main ideas.",
     "prompt": "Provide a concise summary of the following content. Focus on the main ideas and key information:\n\n{content}"},
    {"id": "key_points", "title": "Key Points",
     "description": "Key points and takeaways as a bulleted list.",
     "prompt": "Extract the key points and takeaways from the following content as a bulleted list:\n\n{content}"},
    {"id": "questions", "title": "Study Questions",
     "description": "Study questions generated from the content.",
     "prompt": "Generate 5-10 study questions based on the following content. Include a mix of factual and analytical questions:\n\n{content}"},
    {"id": "outline", "title": "Outline",
     "description": "Structured outline with main topics and subtopics.",
     "prompt": "Create a structured outline of the following content with main topics and subtopics:\n\n{content}"},
    {"id": "simplify", "title": "Simplify",
     "description": "Rewrite in simpler, general-audience language.",
     "prompt": "Rewrite the following content in simpler language that a general audience can understand:\n\n{content}"},
    {"id": "critique", "title": "Critique",
     "description": "Critical analysis: strengths, weaknesses, assumptions, gaps.",
     "prompt": "Provide a critical analysis of the following content — its strengths, weaknesses, assumptions, and gaps:\n\n{content}"},
    {"id": "action_items", "title": "Action Items",
     "description": "Action items, recommendations, and next steps.",
     "prompt": "Extract action items, recommendations, and next steps from the following content:\n\n{content}"},
    {"id": "quiz", "title": "Quiz",
     "description": "A multiple-choice quiz grounded in this content.",
     "prompt": "Create a quiz of 8-12 questions based ONLY on the following content. For each question give: the question, four options labelled A-D, the correct answer, and a one-line explanation. Format as clean Markdown with each question numbered. Do not invent facts beyond the content.\n\n{content}"},
    {"id": "flashcards", "title": "Flashcards",
     "description": "A study flashcard deck grounded in this content.",
     "prompt": "Create 15-20 study flashcards based ONLY on the following content. Format each as a Markdown list item exactly like: **Front:** <term or question> — **Back:** <answer or definition>. Cover the most important concepts. Do not invent facts beyond the content.\n\n{content}"},
    {"id": "study_guide", "title": "Study Guide",
     "description": "A structured study guide grounded in this content.",
     "prompt": "Create a structured study guide from ONLY the following content, in Markdown, with these sections: ## Key Concepts (5-7 bullets), ## Detailed Notes (per concept: a short explanation and an example), ## Key Terms (term: definition), ## Common Pitfalls, ## Practice Questions (3-5 with answers). Do not invent facts beyond the content.\n\n{content}"},
]
_BUILTIN_BY_ID = {t["id"]: t for t in _BUILTIN_TRANSFORMATIONS}

_DEFAULT_TRANSFORM_INSTRUCTIONS = (
    "You are an expert analyst. Apply the requested transformation to the provided "
    "content accurately and concisely. Output only the transformed result."
)
# Per-process store for the global default-prompt (v1 — not DB-persisted).
_onb_default_prompt = {"transformation_instructions": _DEFAULT_TRANSFORM_INSTRUCTIONS}


def _transform_to_onb(t: Dict[str, Any], *, created: str = "", updated: str = "") -> Dict[str, Any]:
    return {
        "id": str(t["id"]),
        "name": t.get("name") or t.get("title") or "",
        "title": t.get("title") or "",
        "description": t.get("description") or "",
        "prompt": t.get("prompt") or "",
        "apply_default": bool(t.get("apply_default", False)),
        "created": created,
        "updated": updated,
    }


def _insight_to_onb(row) -> Dict[str, Any]:
    created = _iso(row["created_at"])
    return {
        "id": str(row["id"]),
        "source_id": str(row["source_id"]) if row["source_id"] else "",
        "insight_type": row["transformation_type"],
        "content": row["transformed_content"] or "",
        "created": created,
        "updated": created,
    }


async def _resolve_transformation(tid: str, user_id, manager: NotebookManager) -> Optional[Dict[str, Any]]:
    """Resolve a transformation_id → {prompt, db_type} from built-ins or the custom table."""
    if tid in _BUILTIN_BY_ID:
        b = _BUILTIN_BY_ID[tid]
        return {"prompt": b["prompt"], "db_type": b["id"], "id": b["id"]}
    try:
        tid_uuid = UUID(str(tid))
    except (ValueError, TypeError):
        return None
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, prompt FROM notebook_transformation_defs WHERE id = $1 AND user_id = $2",
            tid_uuid, user_id,
        )
    if r:
        return {"prompt": r["prompt"], "db_type": "custom", "id": str(r["id"])}
    return None


async def _run_transformation_llm(prompt_template: str, content: str, model: str) -> str:
    prompt = (prompt_template or "{content}").replace("{content}", (content or "")[:8000])
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{_ONB_OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "") or ""


# -- Transformations: list / create / default-prompt / execute / get / update / delete
# (literal sub-paths declared BEFORE the {transformation_id} param route.)

@router.get("/transformations")
async def onb_list_transformations(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    out = [_transform_to_onb(t) for t in _BUILTIN_TRANSFORMATIONS]
    try:
        async with manager.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, title, description, prompt, apply_default, created_at, updated_at "
                "FROM notebook_transformation_defs WHERE user_id = $1 ORDER BY created_at",
                current_user["id"],
            )
        for r in rows:
            out.append(_transform_to_onb(
                {"id": r["id"], "name": r["name"], "title": r["title"],
                 "description": r["description"], "prompt": r["prompt"],
                 "apply_default": r["apply_default"]},
                created=_iso(r["created_at"]), updated=_iso(r["updated_at"])))
    except Exception as e:
        logger.warning(f"onb_compat: custom transformations unavailable: {e}")
    return out


@router.post("/transformations")
async def onb_create_transformation(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    name = ((body or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO notebook_transformation_defs (user_id, name, title, description, prompt, apply_default) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "RETURNING id, name, title, description, prompt, apply_default, created_at, updated_at",
            current_user["id"], name, (body.get("title") or name), (body.get("description") or ""),
            (body.get("prompt") or ""), bool(body.get("apply_default", False)),
        )
    return _transform_to_onb(
        {"id": r["id"], "name": r["name"], "title": r["title"], "description": r["description"],
         "prompt": r["prompt"], "apply_default": r["apply_default"]},
        created=_iso(r["created_at"]), updated=_iso(r["updated_at"]))


@router.get("/transformations/default-prompt")
async def onb_get_default_prompt(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return {"transformation_instructions": _onb_default_prompt["transformation_instructions"]}


@router.put("/transformations/default-prompt")
async def onb_put_default_prompt(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    val = (body or {}).get("transformation_instructions")
    if isinstance(val, str) and val.strip():
        _onb_default_prompt["transformation_instructions"] = val
    return {"transformation_instructions": _onb_default_prompt["transformation_instructions"]}


@router.post("/transformations/execute")
async def onb_execute_transformation(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    tid = (body or {}).get("transformation_id")
    input_text = (body or {}).get("input_text") or ""
    model = (body or {}).get("model_id") or await _default_chat_model()
    t = await _resolve_transformation(tid, current_user["id"], manager)
    if not t:
        raise HTTPException(status_code=404, detail="Transformation not found")
    try:
        output = await _run_transformation_llm(t["prompt"], input_text, model)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Model request failed: {e}")
    return {"output": output, "transformation_id": str(tid), "model_id": model}


# Ollama structured-output schemas — constrain small models to the EXACT shape the
# interactive renderers need (passed as `format`, not just "json").
_QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["q", "options", "answer"],
            },
        }
    },
    "required": ["questions"],
}
_FLASHCARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                "required": ["front", "back"],
            },
        }
    },
    "required": ["cards"],
}


def _normalize_quiz(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Coerce model output to [{q, options[str], answer:int, explanation}] — tolerant of
    the ways small models wander (A/B/C/D keys, letter answers, stray fields)."""
    raw = data.get("questions") or data.get("quiz") or data.get("items") if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        q_text = item.get("q") or item.get("question") or item.get("text") or ""
        opts = item.get("options")
        if not isinstance(opts, list):
            lettered = []
            for k in ("A", "B", "C", "D", "E", "F"):
                if k in item:
                    v = item[k]
                    if isinstance(v, list):
                        v = v[0] if v else ""
                    lettered.append(str(v))
            opts = lettered
        opts = [str(o) for o in opts if o not in (None, "")] if isinstance(opts, list) else []
        if not str(q_text).strip() or len(opts) < 2:
            continue
        ans = item.get("answer")
        if isinstance(ans, str):
            mm = re.search(r"\d+", ans)
            if mm:
                ans = int(mm.group())
            elif ans.strip().upper() in ("A", "B", "C", "D", "E", "F"):
                ans = "ABCDEF".index(ans.strip().upper())
            else:
                ans = 0
        if not isinstance(ans, int) or ans < 0 or ans >= len(opts):
            ans = 0
        out.append({
            "q": str(q_text),
            "options": opts,
            "answer": ans,
            "explanation": str(item.get("explanation") or item.get("rationale") or ""),
        })
    return out


def _normalize_flashcards(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Coerce model output to [{front, back}] — tolerant of term/definition aliases."""
    raw = data.get("cards") or data.get("flashcards") or data.get("items") if isinstance(data, dict) else []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        front = item.get("front") or item.get("term") or item.get("question") or item.get("q") or ""
        back = item.get("back") or item.get("definition") or item.get("answer") or item.get("a") or ""
        if not str(front).strip() or not str(back).strip():
            continue
        out.append({"front": str(front), "back": str(back)})
    return out


def _artifact_row_to_log(row) -> Dict[str, Any]:
    """Normalize an onb_notebook_artifacts row to the Studio-log shape."""
    content = row["content"]
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception as e:
            logger.warning("artifact %s: JSONB decode failed: %s", row["id"], e)
            content = {}
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "title": row["title"] or row["kind"],
        "format": row["format"],
        "content": content,
        "status": "ready",
        "audio_url": None,
        "error_message": None,
        "created_at": _iso(row["created_at"]),
    }


async def _persist_and_return_artifact(
    manager, notebook_id, user_id, kind, title, fmt, content_obj, model
) -> Dict[str, Any]:
    """INSERT a generated artifact and return it in the Studio-log shape."""
    try:
        nb_uuid = _clean_uuid(notebook_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notebook id")
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO onb_notebook_artifacts "
            "(notebook_id, user_id, kind, title, format, content, model_used) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7) "
            "RETURNING id, kind, title, format, content, created_at",
            nb_uuid, user_id, kind, title, fmt, json.dumps(content_obj), model,
        )
    return _artifact_row_to_log(row)


# NotebookLM-style "Reports": every Markdown generator the Studio offers.
# study_guide predates the rest; briefing / faq / timeline complete the set.
_MARKDOWN_GENERATORS: Dict[str, Dict[str, str]] = {
    "study_guide": {
        "title": "Study Guide",
        "prompt": (
            "Create a structured study guide based ONLY on the following content, in clean "
            "Markdown with these sections: ## Key Concepts (5-7 bullets), ## Detailed Notes "
            "(per concept: a short explanation and an example), ## Key Terms (term: definition), "
            "## Common Pitfalls, ## Practice Questions (3-5 with answers). Do not invent facts.\n\n"
            "{content}"
        ),
    },
    "briefing": {
        "title": "Briefing Doc",
        "prompt": (
            "Write a briefing document based ONLY on the following content, in clean Markdown "
            "with these sections: ## Overview (2-3 sentence executive summary), ## Key Themes "
            "(the main themes, each with a short explanation), ## Important Facts & Figures "
            "(bulleted, with concrete numbers/names/dates from the content), ## Notable Quotes "
            "(verbatim quotes worth remembering, quoted and attributed to their source), "
            "## Implications & Open Questions. Be precise and neutral. Do not invent facts.\n\n"
            "{content}"
        ),
    },
    "faq": {
        "title": "FAQ",
        "prompt": (
            "Create a Frequently Asked Questions document based ONLY on the following content, "
            "in clean Markdown. Write 8-12 questions a curious reader would actually ask, each "
            "as a '### ' heading followed by a clear 2-4 sentence answer grounded strictly in "
            "the content. Order them from fundamental to advanced. Do not invent facts.\n\n"
            "{content}"
        ),
    },
    "timeline": {
        "title": "Timeline",
        "prompt": (
            "Create a timeline document based ONLY on the following content, in clean Markdown "
            "with two sections: ## Timeline — a chronological bulleted list of events, each as "
            "'**<date or ordering>** — <what happened>' (if the content has no explicit dates, "
            "order events logically and say so); and ## Cast of Characters — the people/"
            "organizations/entities involved, each with a one-line description of their role. "
            "Do not invent facts.\n\n"
            "{content}"
        ),
    },
}


@router.post("/notebooks/{notebook_id}/generate")
async def onb_notebook_generate(
    notebook_id: str,
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Generate a grounded artifact from the notebook's source + note content —
    or, when `source_ids` is given, from ONLY those (checked) sources.
    quiz / flashcards return STRUCTURED JSON (for an interactive UI); the report
    kinds (study_guide / briefing / faq / timeline) return Markdown."""
    import json
    import re

    from .podcasts import _resolve_notebook_content

    kind = (body or {}).get("kind") or ""
    if kind not in ("quiz", "flashcards") and kind not in _MARKDOWN_GENERATORS:
        raise HTTPException(status_code=400, detail=f"Unknown generator: {kind}")

    # Ownership: 404 unless this notebook belongs to the caller (autoname pattern).
    try:
        nb_uuid = _clean_uuid(notebook_id)
        await manager.get_notebook(nb_uuid, current_user["id"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notebook id")
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")

    # Optional selected-source grounding (NotebookLM-style checkboxes).
    raw_ids = (body or {}).get("source_ids")
    source_ids: Optional[List[UUID]] = None
    if isinstance(raw_ids, list) and raw_ids:
        try:
            source_ids = [_clean_uuid(str(s)) for s in raw_ids[:12]]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid source id in source_ids")

    content = await _resolve_notebook_content(manager, notebook_id, None, source_ids=source_ids)
    if not content or not content.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "The selected sources have no extracted content to generate from yet."
                if source_ids
                else "This notebook has no source content to generate from yet."
            ),
        )
    model = (body or {}).get("model_id") or await _default_chat_model()

    if kind in _MARKDOWN_GENERATORS:
        gen = _MARKDOWN_GENERATORS[kind]
        try:
            output = await _run_transformation_llm(gen["prompt"], content, model)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Model request failed: {e}")
        return await _persist_and_return_artifact(
            manager, notebook_id, current_user["id"], kind, gen["title"],
            "markdown", {"markdown": output}, model,
        )

    if kind == "quiz":
        prompt = (
            "Create 8-10 multiple-choice questions based ONLY on the following content. Return "
            'ONLY a JSON object exactly like {"questions":[{"q":"question text","options":["A","B",'
            '"C","D"],"answer":0,"explanation":"why"}]} where "answer" is the 0-based index of the '
            "correct option. No prose, no Markdown, no code fences. Do not invent facts beyond the "
            "content.\n\n{content}"
        )
    else:  # flashcards
        prompt = (
            "Create 12-18 study flashcards based ONLY on the following content. Return ONLY a JSON "
            'object exactly like {"cards":[{"front":"term or question","back":"answer or '
            'definition"}]}. No prose, no Markdown, no code fences. Do not invent facts beyond the '
            "content.\n\n{content}"
        )
    # Constrain the model to the EXACT shape via Ollama structured outputs (a JSON
    # schema as `format`), then normalize defensively — small models still wander.
    schema = _QUIZ_SCHEMA if kind == "quiz" else _FLASHCARDS_SCHEMA
    full_prompt = prompt.replace("{content}", content[:8000])
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{_ONB_OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": False, "format": schema},
            )
            resp.raise_for_status()
            raw = (resp.json().get("response") or "").strip()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Model request failed: {e}")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    data: Dict[str, Any] = {}
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}

    if kind == "quiz":
        questions = _normalize_quiz(data)
        if not questions:
            raise HTTPException(status_code=502, detail="The model didn't return a usable quiz — try again.")
        title = f"Quiz · {len(questions)} questions"
        return await _persist_and_return_artifact(
            manager, notebook_id, current_user["id"], "quiz", title, "json",
            {"questions": questions}, model,
        )
    cards = _normalize_flashcards(data)
    if not cards:
        raise HTTPException(status_code=502, detail="The model didn't return usable flashcards — try again.")
    title = f"Flashcards · {len(cards)} cards"
    return await _persist_and_return_artifact(
        manager, notebook_id, current_user["id"], "flashcards", title, "json",
        {"cards": cards}, model,
    )


@router.get("/notebooks/{notebook_id}/artifacts")
async def onb_notebook_artifacts(
    notebook_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Unified Studio log for ONE notebook: quiz / flashcards / study_guide artifacts
    PLUS this notebook's podcasts, newest first. The Studio rail renders this."""
    try:
        nb_uuid = _clean_uuid(notebook_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notebook id")
    user_id = current_user["id"]
    items: List[Dict[str, Any]] = []
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, kind, title, format, content, created_at "
            "FROM onb_notebook_artifacts WHERE notebook_id = $1 AND user_id = $2 "
            "ORDER BY created_at DESC",
            nb_uuid, user_id,
        )
        items.extend(_artifact_row_to_log(r) for r in rows)
        # Podcasts for THIS notebook (standalone_podcasts.notebook_id is TEXT = nb uuid).
        try:
            # Match both the canonical uuid string AND the raw path param — podcasts.py
            # stores whatever the client sent, so be tolerant of prefix/case differences.
            prows = await conn.fetch(
                "SELECT id, title, status, audio_url, error_message, created_at "
                "FROM standalone_podcasts WHERE notebook_id = ANY($1::text[]) AND user_id = $2 "
                "ORDER BY created_at DESC",
                list({str(nb_uuid), notebook_id}), user_id,
            )
        except Exception as e:
            logger.warning("artifacts: podcast sub-query failed for notebook %s: %s", notebook_id, e)
            prows = []
        for r in prows:
            items.append({
                "id": str(r["id"]),
                "kind": "podcast",
                "title": r["title"] or "Podcast",
                "format": "audio",
                "content": None,
                "status": r["status"] or "pending",
                "audio_url": r["audio_url"],
                "error_message": r["error_message"],
                "created_at": _iso(r["created_at"]),
            })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


@router.delete("/notebooks/{notebook_id}/artifacts/{artifact_id}")
async def onb_delete_artifact(
    notebook_id: str,
    artifact_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Delete a generated artifact (quiz/flashcards/study_guide). Podcasts are deleted
    via the existing /podcasts/episodes/{id} endpoint."""
    try:
        aid = _clean_uuid(artifact_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid artifact id")
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM onb_notebook_artifacts WHERE id = $1 AND user_id = $2",
            aid, current_user["id"],
        )
    return {"status": "deleted"}


# Structured-output schema for suggested questions (NotebookLM-style chips shown
# on the notebook chat's empty state).
_SUGGESTED_QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
}


@router.post("/notebooks/{notebook_id}/suggest-questions")
async def onb_suggest_questions(
    notebook_id: str,
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Suggest 4-6 questions a reader could ask THIS notebook's sources —
    rendered as clickable chips in the chat's empty state (NotebookLM parity).
    Grounded in the sources; returns {"questions": []} when there's no content
    (never a 5xx — the chips are decorative, the chat must keep working)."""
    from .podcasts import _resolve_notebook_content

    # Ownership: 404 unless this notebook belongs to the caller.
    try:
        nb_uuid = _clean_uuid(notebook_id)
        await manager.get_notebook(nb_uuid, current_user["id"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notebook id")
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")

    content = await _resolve_notebook_content(manager, notebook_id, None)
    if not content or not content.strip():
        return {"questions": []}

    model = (body or {}).get("model_id") or await _default_chat_model()
    prompt = (
        "You are looking at the source material of a research notebook. Suggest 5 "
        "specific, interesting questions a curious reader could ask about this material. "
        "Each question must be answerable FROM the content below (no outside knowledge), "
        "under 90 characters, and phrased naturally. Return ONLY a JSON object exactly "
        'like {"questions":["...","..."]}. No prose, no Markdown.\n\n'
        + content[:6000]
    )
    try:
        from notebooks.rag_chat import FALLBACK_MODELS
    except Exception:
        FALLBACK_MODELS = []
    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    questions: List[str] = []
    for m in candidates[:3]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{_ONB_OLLAMA_URL}/api/generate",
                    json={
                        "model": m, "prompt": prompt, "stream": False,
                        "format": _SUGGESTED_QUESTIONS_SCHEMA,
                        "options": {"temperature": 0.5, "num_predict": 400, "num_ctx": 4096},
                    },
                )
            if resp.status_code != 200:
                continue
            raw = (resp.json().get("response") or "").strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            try:
                data = json.loads(raw)
            except Exception:
                mm = re.search(r"\{.*\}", raw, re.DOTALL)
                data = json.loads(mm.group(0)) if mm else {}
            got = data.get("questions") if isinstance(data, dict) else None
            if isinstance(got, list):
                seen = set()
                for q in got:
                    q = " ".join(str(q).split()).strip()
                    if q and len(q) <= 160 and q.lower() not in seen:
                        seen.add(q.lower())
                        questions.append(q)
                if questions:
                    break
        except Exception as e:
            logger.debug("onb suggest-questions model %s failed: %s", m, e)
            continue
    return {"questions": questions[:6]}


@router.get("/transformations/{transformation_id}")
async def onb_get_transformation(
    transformation_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if transformation_id in _BUILTIN_BY_ID:
        return _transform_to_onb(_BUILTIN_BY_ID[transformation_id])
    try:
        tid_uuid = UUID(transformation_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Transformation not found")
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, name, title, description, prompt, apply_default, created_at, updated_at "
            "FROM notebook_transformation_defs WHERE id = $1 AND user_id = $2",
            tid_uuid, current_user["id"],
        )
    if not r:
        raise HTTPException(status_code=404, detail="Transformation not found")
    return _transform_to_onb(
        {"id": r["id"], "name": r["name"], "title": r["title"], "description": r["description"],
         "prompt": r["prompt"], "apply_default": r["apply_default"]},
        created=_iso(r["created_at"]), updated=_iso(r["updated_at"]))


@router.put("/transformations/{transformation_id}")
async def onb_update_transformation(
    transformation_id: str,
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if transformation_id in _BUILTIN_BY_ID:
        raise HTTPException(status_code=400, detail="Built-in transformations can't be edited")
    try:
        tid_uuid = UUID(transformation_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Transformation not found")
    b = body or {}
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "UPDATE notebook_transformation_defs SET "
            "name = COALESCE($3, name), title = COALESCE($4, title), "
            "description = COALESCE($5, description), prompt = COALESCE($6, prompt), "
            "apply_default = COALESCE($7, apply_default), updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 "
            "RETURNING id, name, title, description, prompt, apply_default, created_at, updated_at",
            tid_uuid, current_user["id"], b.get("name"), b.get("title"),
            b.get("description"), b.get("prompt"), b.get("apply_default"),
        )
    if not r:
        raise HTTPException(status_code=404, detail="Transformation not found")
    return _transform_to_onb(
        {"id": r["id"], "name": r["name"], "title": r["title"], "description": r["description"],
         "prompt": r["prompt"], "apply_default": r["apply_default"]},
        created=_iso(r["created_at"]), updated=_iso(r["updated_at"]))


@router.delete("/transformations/{transformation_id}")
async def onb_delete_transformation(
    transformation_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    if transformation_id in _BUILTIN_BY_ID:
        raise HTTPException(status_code=400, detail="Built-in transformations can't be deleted")
    try:
        tid_uuid = UUID(transformation_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Transformation not found")
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM notebook_transformation_defs WHERE id = $1 AND user_id = $2",
            tid_uuid, current_user["id"],
        )
    return {"ok": True}


# -- Insights (transformation results applied to a source) + command-status shim

@router.get("/sources/{source_id}/insights")
async def onb_list_source_insights(
    source_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        sid = _clean_uuid(source_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Source not found")
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, source_id, transformation_type, transformed_content, created_at "
            "FROM notebook_transformations WHERE source_id = $1 AND user_id = $2 "
            "ORDER BY created_at DESC",
            sid, current_user["id"],
        )
    return [_insight_to_onb(r) for r in rows]


@router.post("/sources/{source_id}/insights")
async def onb_create_source_insight(
    source_id: str,
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    tid = (body or {}).get("transformation_id")
    t = await _resolve_transformation(tid, current_user["id"], manager)
    if not t:
        raise HTTPException(status_code=404, detail="Transformation not found")
    try:
        sid = _clean_uuid(source_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Source not found")
    async with manager.db_pool.acquire() as conn:
        srow = await conn.fetchrow(
            "SELECT notebook_id, content_text FROM notebook_sources WHERE id = $1", sid)
    if not srow:
        raise HTTPException(status_code=404, detail="Source not found")
    content = srow["content_text"]
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Source has no extracted content to transform")
    insight_model = await _default_chat_model()
    try:
        output = await _run_transformation_llm(t["prompt"], content, insight_model)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Model request failed: {e}")
    if not output.strip():
        raise HTTPException(status_code=500, detail="Empty response from model")
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO notebook_transformations "
            "(notebook_id, source_id, user_id, transformation_type, original_content, transformed_content, model_used) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
            srow["notebook_id"], sid, current_user["id"], t["db_type"],
            content[:2000], output, insight_model,
        )
    insight_id = str(r["id"])
    # Synchronous: the work is already done + persisted; command status is "completed".
    return {
        "status": "completed",
        "message": "Insight created",
        "source_id": source_id,
        "transformation_id": str(tid),
        "command_id": insight_id,
    }


@router.get("/insights/{insight_id}")
async def onb_get_insight(
    insight_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        iid = _clean_uuid(insight_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Insight not found")
    async with manager.db_pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, source_id, transformation_type, transformed_content, created_at "
            "FROM notebook_transformations WHERE id = $1 AND user_id = $2",
            iid, current_user["id"],
        )
    if not r:
        raise HTTPException(status_code=404, detail="Insight not found")
    return _insight_to_onb(r)


@router.delete("/insights/{insight_id}")
async def onb_delete_insight(
    insight_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    try:
        iid = _clean_uuid(insight_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Insight not found")
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM notebook_transformations WHERE id = $1 AND user_id = $2",
            iid, current_user["id"],
        )
    return {"ok": True}


@router.get("/commands/jobs/{command_id}")
async def onb_command_status(
    command_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    # Facade transformations run synchronously, so any referenced job is already done.
    return {"job_id": command_id, "status": "completed"}


# ─── Source quality for notebook web search ───────────────────────────────────
# A notebook source has to be READ, not merely linked: the picked URL is ingested,
# chunked and embedded. NotebookLM's Discover only offers documents its reader can
# actually digest — articles, papers, documentation — and quietly drops forums,
# social feeds, video and storefronts. Ours forwarded raw DuckDuckGo hits, so a
# search handed back Reddit threads and YouTube pages that ingest into a source
# with nothing readable in it.
#
# Two rules, applied in order:
#
#   1. NON_ARTICLE_HOSTS are DROPPED, not down-ranked. A Reddit thread is not a
#      weak article; it is not an article. No relevance score should be able to
#      promote it into a corpus meant to be cited.
#   2. What survives is ordered by how document-shaped it is, so references and
#      long-form pieces rise above thin listing pages.
#
# Deliberately NOT dropped: Stack Overflow, GitHub and the like. They are Q&A and
# repository pages rather than prose, but they extract cleanly and are often the
# best available source for a technical question — the thing the user is usually
# researching here.

_NON_ARTICLE_HOSTS = (
    # discussion and social — no stable article body to extract
    "reddit.com", "quora.com", "answers.yahoo.com",
    "x.com", "twitter.com", "facebook.com", "instagram.com", "threads.net",
    "tiktok.com", "pinterest.", "tumblr.com", "vk.com", "mastodon.",
    "discord.com", "t.me", "telegram.me", "whatsapp.com",
    # video and audio — the page carries a player, not a document
    "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com",
    "soundcloud.com", "spotify.com",
    # commerce and listings
    "amazon.", "ebay.", "etsy.com", "walmart.com", "aliexpress.",
    "indeed.com", "glassdoor.com", "yelp.com", "tripadvisor.",
    # search engines and aggregators (a results page is never a source)
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "search.brave.com",
    "news.google.com",
)

# Hosts whose pages are reference material almost by definition.
_REFERENCE_HOSTS = (
    "arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "nature.com", "science.org", "sciencedirect.com", "springer.com",
    "onlinelibrary.wiley.com", "jstor.org", "ieee.org", "dl.acm.org",
    "biorxiv.org", "medrxiv.org", "journals.plos.org", "ssrn.com",
    "wikipedia.org", "who.int", "oecd.org", "worldbank.org", "nih.gov",
)

# Path fragments that mark a page as a written piece rather than an index.
_ARTICLE_PATH_HINTS = (
    "/blog", "/article", "/post", "/news", "/story", "/docs", "/documentation",
    "/guide", "/tutorial", "/research", "/paper", "/publication", "/report",
    "/wiki/", "/journal", "/essay", "/analysis", "/explainer",
)

# Extensions that are a file to download, not a page to read. PDF is absent on
# purpose: the ingester reads PDFs, and they are frequently the primary source.
_NON_DOCUMENT_EXTS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav", ".m4a",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".dmg", ".iso",
)


def _readable_source(url: str) -> bool:
    """False for anything that would ingest into an unusable notebook source."""
    u = (url or "").lower()
    if not u.startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlparse

        parsed = urlparse(u)
        host, path = parsed.netloc, parsed.path
    except Exception:
        return False
    if not host:
        return False
    # Strip the port and any leading www. before matching, so "reddit.com:443"
    # and "www.reddit.com" are caught by the same entry.
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    for bad in _NON_ARTICLE_HOSTS:
        # Entries ending in "." are prefix rules (pinterest. → pinterest.co.uk).
        if bad.endswith(".") and host.startswith(bad):
            return False
        if host == bad or host.endswith("." + bad):
            return False
    if path.endswith(_NON_DOCUMENT_EXTS):
        return False
    # A bare host with no path is a homepage: a feed, not a document.
    if path in ("", "/"):
        return False
    return True


def _article_shape_score(url: str, snippet: str) -> float:
    """How document-shaped a surviving result looks. Ordering only — never a gate."""
    u = (url or "").lower()
    score = 0.0
    if any(h in u for h in _REFERENCE_HOSTS):
        score += 1.0
    if u.endswith(".edu") or ".edu/" in u or u.endswith(".gov") or ".gov/" in u:
        score += 0.6
    if any(h in u for h in _ARTICLE_PATH_HINTS):
        score += 0.5
    if u.endswith(".pdf"):
        score += 0.4
    # A dated path (/2026/03/…) is the classic article permalink shape.
    if re.search(r"/(19|20)\d{2}/", u):
        score += 0.3
    # A real summary means the crawler found prose on the page.
    n = len((snippet or "").strip())
    if n >= 240:
        score += 0.4
    elif n >= 120:
        score += 0.2
    # Deep query strings are usually app state, not a permalink.
    if u.count("&") >= 3:
        score -= 0.3
    return score


# ─── Web search for new sources (open-notebook "Search the web") ───────────────
# The agent searches the web (Harvis WebSearchAgent / DuckDuckGo) and returns
# candidate sources; the UI lets the user pick which to import (each becomes a
# normal URL source via POST /sources). search_web is sync → offload to a thread.

@router.post("/sources/web-search")
async def onb_source_web_search(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    query = ((body or {}).get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    try:
        max_results = int((body or {}).get("max_results") or 8)
    except (ValueError, TypeError):
        max_results = 8
    max_results = max(1, min(max_results, 20))
    # Over-fetch: the readability filter below removes whole classes of result, so
    # asking for exactly max_results would routinely return a short list.
    fetch_n = min(max_results * 4, 40)
    try:
        from research.web_search import WebSearchAgent
        agent = WebSearchAgent(max_results=fetch_n)
        results = await asyncio.to_thread(agent.search_web, query, fetch_n)
    except Exception as e:
        logger.warning(f"onb_compat web-search failed for '{query}': {e}")
        raise HTTPException(status_code=502, detail=f"Web search failed: {e}")

    kept: List[Dict[str, Any]] = []
    seen = set()
    dropped = 0
    for r in (results or []):
        if not isinstance(r, dict):
            continue
        url = r.get("url") or r.get("href") or r.get("link") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        if not _readable_source(url):
            dropped += 1
            continue
        snippet = r.get("snippet") or r.get("body") or r.get("description") or ""
        kept.append({
            "title": r.get("title") or url,
            "url": url,
            "snippet": snippet,
            "source": r.get("source") or "",
            "_shape": _article_shape_score(url, snippet),
        })

    # Stable within equal scores: the search engine's own ranking is the tiebreak,
    # so this reorders by document-shape without discarding relevance order.
    kept.sort(key=lambda x: x["_shape"], reverse=True)
    out = [{k: v for k, v in r.items() if k != "_shape"} for r in kept[:max_results]]
    if dropped:
        logger.info(
            "onb_compat web-search '%s': dropped %d non-article result(s), returning %d",
            query, dropped, len(out),
        )
    return {"query": query, "results": out}


# ─── Settings + Models + Credentials (open-notebook Settings / Models pages) ────
# The Settings form + Default-Models selectors get a real per-user JSONB store; the
# models list is the same union `/api/models` serves the main chat (see _all_models);
# credentials live in Harvis Integrations, so open-notebook's own key form is stubbed
# minimal-real and the page loads instead of spinning.

_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "default_content_processing_engine_doc": "auto",
    "default_content_processing_engine_url": "auto",
    "default_embedding_option": "ask",
    "auto_delete_files": "no",
    "youtube_preferred_languages": ["en"],
}
_MODEL_DEFAULT_SLOTS = (
    "default_chat_model",
    "default_transformation_model",
    "default_tools_model",
    "large_context_model",
    "default_embedding_model",
    "default_text_to_speech_model",
    "default_speech_to_text_model",
)
async def _model_defaults_defaults() -> Dict[str, Any]:
    """Settings-panel defaults. Resolved per call so the chat slots reflect what
    this deploy actually has installed rather than a name baked in at import."""
    chat_model = await _default_chat_model()
    return {
        "default_chat_model": chat_model,
        "default_transformation_model": chat_model,
        "default_tools_model": chat_model,
        "large_context_model": chat_model,
        "default_embedding_model": "nomic-embed-text",
        "default_text_to_speech_model": None,
        "default_speech_to_text_model": None,
    }


def _jsonb(v):
    """asyncpg may hand back JSONB as str or already-parsed dict — normalise to dict."""
    if v is None:
        return {}
    if isinstance(v, str):
        try:
            return json.loads(v) or {}
        except Exception:
            return {}
    return dict(v)


async def _ensure_onb_settings_table(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS onb_user_settings ("
        " user_id INTEGER PRIMARY KEY,"
        " settings JSONB NOT NULL DEFAULT '{}'::jsonb,"
        " model_defaults JSONB NOT NULL DEFAULT '{}'::jsonb,"
        " updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


async def _read_onb_settings(manager, user_id):
    async with manager.db_pool.acquire() as conn:
        await _ensure_onb_settings_table(conn)
        r = await conn.fetchrow(
            "SELECT settings, model_defaults FROM onb_user_settings WHERE user_id = $1",
            user_id,
        )
    s = dict(_SETTINGS_DEFAULTS)
    md = await _model_defaults_defaults()
    if r:
        s.update(_jsonb(r["settings"]))
        md.update(_jsonb(r["model_defaults"]))
    return s, md


async def _write_onb_settings(manager, user_id, settings=None, model_defaults=None):
    async with manager.db_pool.acquire() as conn:
        await _ensure_onb_settings_table(conn)
        await conn.execute(
            "INSERT INTO onb_user_settings (user_id, settings, model_defaults) "
            "VALUES ($1, COALESCE($2::jsonb, '{}'::jsonb), COALESCE($3::jsonb, '{}'::jsonb)) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "settings = COALESCE($2::jsonb, onb_user_settings.settings), "
            "model_defaults = COALESCE($3::jsonb, onb_user_settings.model_defaults), "
            "updated_at = now()",
            user_id,
            json.dumps(settings) if settings is not None else None,
            json.dumps(model_defaults) if model_defaults is not None else None,
        )


async def _list_ollama_models() -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{OLLAMA_URL.rstrip('/')}/api/tags")
            r.raise_for_status()
            return r.json().get("models", []) or []
    except Exception as e:  # pragma: no cover - network
        logger.warning(f"onb_compat: ollama /api/tags failed: {e}")
        return []


def _ollama_model_type(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("embed", "bge", "nomic", "minilm", "mxbai")):
        return "embedding"
    return "language"


def _model_to_onb(
    name: str, provider: str = "ollama", display: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "id": name,
        "name": display or name,
        "provider": provider,
        "type": _ollama_model_type(name),
        "credential": None,
        "created": "",
        "updated": "",
    }


async def _all_models(request: Request, user_id: Any) -> List[Dict[str, Any]]:
    """Every model this user can actually pick, in open-notebook shape.

    The notebook picker used to list the local Ollama tag list and nothing else, so a
    user with a verified Claude (or other cloud) credential saw none of it here even
    though the main chat picker did. This reads the SAME three sources `/api/models`
    composes for the chat, so the two pickers cannot drift apart:

      1. native  — Ollama, llama-server, vLLM, desktop and external hosts
      2. cloud   — per-user, and only when the credential is VERIFIED in Integrations
      3. Hermes  — when the engine flag is on and a Hermes is reachable

    Every source is additive and fail-open: one being unreachable narrows the list,
    it never empties it. The bare Ollama tag list runs last as the floor, so the
    picker still works if the native lister itself is down.
    """
    out: List[Dict[str, Any]] = []
    seen = set()

    def _add(name: Any, provider: str, display: Any = None) -> None:
        name = (name or "").strip() if isinstance(name, str) else ""
        if not name or name in seen:
            return
        seen.add(name)
        out.append(_model_to_onb(name, provider, display if isinstance(display, str) else None))

    # 1. Native. list_models() reads current_user.id and nothing else off the user,
    #    so a namespace with that one field is a faithful caller here.
    try:
        from types import SimpleNamespace
        from main import list_models as _native_list_models

        native = await _native_list_models(request, SimpleNamespace(id=user_id))
        for m in (native or {}).get("models", []) or []:
            _add(m.get("name"), m.get("provider") or "harvis", m.get("displayName"))
    except Exception:
        logger.warning("onb_compat: native model list unavailable", exc_info=True)

    pool = getattr(request.app.state, "pg_pool", None)

    # 2. Per-user cloud models. Fail-closed inside cloud_chat: no verified credential
    #    means an empty list, never an error and never a decrypted secret.
    try:
        from owui_compat.cloud_chat import cloud_chat_model_entries

        for m in await cloud_chat_model_entries(pool, user_id):
            _add((m or {}).get("id"), (m or {}).get("owned_by") or "cloud", (m or {}).get("name"))
    except Exception:
        logger.warning("onb_compat: cloud model list unavailable", exc_info=True)

    # 3. Hermes, when reachable.
    try:
        from owui_compat.hermes_chat import hermes_chat_model_entry

        hm = await hermes_chat_model_entry(pool, user_id)
        if hm:
            _add(hm.get("id"), hm.get("owned_by") or "hermes-agent", hm.get("name"))
    except Exception:
        logger.warning("onb_compat: hermes model entry unavailable", exc_info=True)

    # 4. Floor: the raw tag list, in case (1) failed outright.
    for m in await _list_ollama_models():
        _add(m.get("name") or m.get("model"), "ollama")

    return out


@router.get("/settings")
async def onb_get_settings(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    s, _ = await _read_onb_settings(manager, current_user["id"])
    return s


@router.put("/settings")
async def onb_put_settings(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    s, _ = await _read_onb_settings(manager, current_user["id"])
    for k, v in (body or {}).items():
        if k in _SETTINGS_DEFAULTS:
            s[k] = v
    await _write_onb_settings(manager, current_user["id"], settings=s)
    return s


# Literal /models sub-paths declared BEFORE any /models/{id} param route.
@router.get("/models")
async def onb_list_models(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return await _all_models(request, current_user["id"])


@router.get("/models/defaults")
async def onb_get_model_defaults(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    _, md = await _read_onb_settings(manager, current_user["id"])
    return md


@router.put("/models/defaults")
async def onb_put_model_defaults(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    _, md = await _read_onb_settings(manager, current_user["id"])
    for k, v in (body or {}).items():
        if k in _MODEL_DEFAULT_SLOTS:
            md[k] = v
    await _write_onb_settings(manager, current_user["id"], model_defaults=md)
    return md


@router.get("/models/providers")
async def onb_model_providers(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    # Report the providers this user actually has models from, rather than asserting
    # "ollama" on a box that may have none and three cloud engines connected.
    models = await _all_models(request, current_user["id"])
    available: List[str] = []
    for m in models:
        p = m.get("provider") or "ollama"
        if p not in available:
            available.append(p)
    supported = {
        p: sorted({m["type"] for m in models if (m.get("provider") or "ollama") == p})
        for p in available
    }
    return {
        "available": available,
        "unavailable": [],
        "supported_types": supported,
    }


@router.post("/models/auto-assign")
async def onb_models_auto_assign(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    models = await _all_models(request, current_user["id"])
    langs = [m["id"] for m in models if m.get("type") == "language"]
    embs = [m["id"] for m in models if m.get("type") == "embedding"]
    _, md = await _read_onb_settings(manager, current_user["id"])
    assigned: Dict[str, str] = {}
    skipped: List[str] = []
    missing: List[str] = []

    def pick(slot, pool):
        if md.get(slot):
            skipped.append(slot)
            return
        if pool:
            md[slot] = pool[0]
            assigned[slot] = pool[0]
        else:
            missing.append(slot)

    for slot in ("default_chat_model", "default_transformation_model", "default_tools_model", "large_context_model"):
        pick(slot, langs)
    pick("default_embedding_model", embs)
    await _write_onb_settings(manager, current_user["id"], model_defaults=md)
    return {"assigned": assigned, "skipped": skipped, "missing": missing}


@router.post("/models/sync")
async def onb_models_sync(
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    models = await _all_models(request, current_user["id"])
    counts: Dict[str, int] = {}
    for m in models:
        p = m.get("provider") or "ollama"
        counts[p] = counts.get(p, 0) + 1
    results = {
        p: {"provider": p, "discovered": n, "new": 0, "existing": n} for p, n in counts.items()
    }
    return {"results": results, "total_discovered": len(models), "total_new": 0}


@router.post("/models/{model_id:path}/test")
async def onb_test_model(
    model_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    # Only a local model can be pinged here. Firing an Ollama /api/generate at a
    # cloud id used to report every Claude model as broken; and a real cloud probe
    # would decrypt a key and bill the user for a button labelled "test". So: ping
    # what is local, and for everything else say precisely which check did pass.
    provider = "ollama"
    for m in await _all_models(request, current_user["id"]):
        if m.get("id") == model_id:
            provider = m.get("provider") or "ollama"
            break

    if provider != "ollama":
        return {
            "success": True,
            "message": (
                f"Not pinged — {model_id} is served by {provider}. It is listed because "
                f"its credential is verified in Integrations; that check is what passed."
            ),
            "details": model_id,
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{OLLAMA_URL.rstrip('/')}/api/generate",
                json={"model": model_id, "prompt": "ping", "stream": False,
                      "options": {"num_predict": 1}},
            )
            r.raise_for_status()
        return {"success": True, "message": "Model responded.", "details": model_id}
    except Exception as e:
        return {"success": False, "message": str(e)[:200], "details": model_id}


@router.delete("/models/{model_id:path}")
async def onb_delete_model(
    model_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    # Models are managed by Ollama, not a facade registry — nothing to delete.
    return {"message": "ok"}


@router.post("/models")
async def onb_create_model(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    name = ((body or {}).get("name") or "").strip()
    return _model_to_onb(name)


# ── Credentials: Harvis owns these in Integrations (owui_compat/engine_auth), not
# here. The facade reports "configured" so open-notebook's own key UI stays out of
# the way; the models it unlocks arrive through _all_models() instead. ──
@router.get("/credentials/status")
async def onb_cred_status(
    request: Request, current_user: Dict = Depends(get_current_user_from_request)
):
    return {"configured": {}, "source": {}, "encryption_configured": True}


@router.get("/credentials/env-status")
async def onb_cred_env_status(
    request: Request, current_user: Dict = Depends(get_current_user_from_request)
):
    return {}


@router.get("/credentials/by-provider/{provider}")
async def onb_cred_by_provider(
    provider: str, request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return []


@router.post("/credentials/migrate-from-env")
async def onb_cred_migrate_env(
    request: Request, current_user: Dict = Depends(get_current_user_from_request)
):
    return {"message": "Harvis is local-first (Ollama) — no environment credentials to migrate.",
            "migrated": [], "skipped": [], "errors": []}


@router.post("/credentials/migrate-from-provider-config")
async def onb_cred_migrate_pc(
    request: Request, current_user: Dict = Depends(get_current_user_from_request)
):
    return {"message": "Nothing to migrate.", "migrated": [], "skipped": [], "errors": []}


@router.get("/credentials")
async def onb_list_credentials(
    request: Request,
    provider: Optional[str] = None,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return []


@router.post("/credentials")
async def onb_create_credential(
    body: Dict[str, Any], request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(
        status_code=501,
        detail="Cloud API-key storage isn't enabled — Harvis runs on local Ollama models.",
    )


@router.post("/credentials/{credential_id}/test")
async def onb_cred_test(
    credential_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return {"provider": "", "success": False, "message": "Not applicable on local Ollama."}


@router.post("/credentials/{credential_id}/discover")
async def onb_cred_discover(
    credential_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return {"credential_id": credential_id, "provider": "", "discovered": []}


@router.post("/credentials/{credential_id}/register-models")
async def onb_cred_register(
    credential_id: str, body: Dict[str, Any], request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return {"created": 0, "existing": 0}


@router.get("/credentials/{credential_id}")
async def onb_get_credential(
    credential_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=404, detail="No such credential.")


@router.put("/credentials/{credential_id}")
async def onb_update_credential(
    credential_id: str, body: Dict[str, Any], request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    raise HTTPException(status_code=501, detail="Cloud API-key storage isn't enabled.")


@router.delete("/credentials/{credential_id}")
async def onb_delete_credential(
    credential_id: str, request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
):
    return {"message": "ok", "deleted_models": 0}


# ─── ADD THIS IMPORT near the top of the file (StreamingResponse is NOT yet imported) ───
# from fastapi.responses import StreamingResponse


# ════════════════════════════════════════════════════════════════════════════════
# ASK & SEARCH (open-notebook contract: src/lib/api/search.ts, hooks/use-ask.ts)
# Cross-notebook semantic search + multi-search "ask the knowledge base" SSE.
# ════════════════════════════════════════════════════════════════════════════════

# Ollama URL for the LLM-planning / answering steps in /search/ask. Mirrors the
# resolution used elsewhere in this module (router.py:1292) and rag_chat's default.
_ASK_OLLAMA_URL = OLLAMA_URL


def _sse(event: Dict[str, Any]) -> str:
    """Format one Server-Sent-Event data frame the open-notebook reader expects.

    use-ask.ts splits the stream on '\\n', keeps lines beginning with 'data: ',
    and JSON-parses the remainder. We emit a single-line JSON payload followed by
    the blank-line terminator so each frame is self-contained.
    """
    return f"data: {json.dumps(event, default=str)}\n\n"


async def _ask_ollama_generate(model: str, prompt: str, *, timeout: float = 180.0) -> str:
    """One-shot non-streaming Ollama /api/generate call (mirrors _run_transformation_llm
    at router.py:934 and onb_test_model at router.py:1533). Returns response text or ''."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{_ASK_OLLAMA_URL.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return (resp.json().get("response") or "").strip()
    except Exception as e:  # noqa: BLE001 — surfaced to the SSE/HTTP caller as text
        logger.error(f"ask ollama generate failed (model={model}): {e}")
        return ""


def _coerce_jsonb(v: Any) -> Dict[str, Any]:
    """asyncpg returns JSONB as str OR dict depending on codec config — normalise."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (ValueError, TypeError):
            return {}
    return v if isinstance(v, dict) else {}


async def _search_user_chunks(
    manager: "NotebookManager",
    user_id: int,
    query_embedding: List[float],
    limit: int,
    minimum_score: float = 0.0,
) -> List[Dict[str, Any]]:
    """Cross-notebook pgvector cosine search over ALL of the user's source chunks.

    notebook_chunks has no user_id, so we scope ownership by joining through
    notebook_sources → notebooks (matches manager.search_chunks at manager.py:331,
    extended to every active notebook the user owns). Results are grouped by parent
    source (best chunk per source wins; matched chunk snippets collected as `matches`).
    """
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
    # Over-fetch chunks so that after per-source grouping we still have `limit` parents.
    fetch_k = max(limit * 6, limit)
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id            AS chunk_id,
                   c.source_id     AS source_id,
                   c.content       AS content,
                   s.title         AS source_title,
                   s.type          AS source_type,
                   s.created_at    AS created_at,
                   s.updated_at    AS updated_at,
                   1 - (c.embedding <=> $1::vector) AS similarity
            FROM notebook_chunks c
            JOIN notebook_sources s ON c.source_id = s.id
            JOIN notebooks n        ON c.notebook_id = n.id
            WHERE n.user_id = $2
              AND n.is_active = TRUE
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector
            LIMIT $3
            """,
            embedding_str, user_id, fetch_k,
        )

    grouped: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        score = float(r["similarity"])
        # A degenerate / zero stored embedding can make cosine similarity NaN/Inf,
        # which FastAPI's strict JSON response serializer rejects ("Out of range
        # float values are not JSON compliant"). Clamp to a finite value.
        if not math.isfinite(score):
            score = 0.0
        if score < minimum_score:
            continue
        sid = str(r["source_id"])
        snippet = (r["content"] or "")[:300]
        existing = grouped.get(sid)
        if existing is None:
            grouped[sid] = {
                "id": sid,
                "title": r["source_title"] or "Untitled source",
                "parent_id": f"source:{sid}",
                "final_score": score,
                "relevance": score,
                "similarity": score,
                "score": score,
                "matches": [snippet] if snippet else [],
                "type": "source",
                "source_type": r["source_type"],
                "created": (r["created_at"].isoformat() if r["created_at"] else ""),
                "updated": (r["updated_at"].isoformat() if r["updated_at"] else ""),
                "_content": snippet,
            }
        else:
            if score > existing["final_score"]:
                existing["final_score"] = score
                existing["relevance"] = score
                existing["similarity"] = score
                existing["score"] = score
            if snippet and len(existing["matches"]) < 3:
                existing["matches"].append(snippet)

    out = sorted(grouped.values(), key=lambda x: x["final_score"], reverse=True)
    return out[:limit]


async def _search_user_notes(
    manager: "NotebookManager",
    user_id: int,
    query: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """ILIKE keyword fallback over the user's notes (notebook_notes is keyed by
    user_id directly and has NO embedding column — manager.py:387). Pure text match."""
    pattern = f"%{query.strip()}%"
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notebook_notes
            WHERE user_id = $1
              AND (title ILIKE $2 OR content ILIKE $2)
            ORDER BY updated_at DESC
            LIMIT $3
            """,
            user_id, pattern, limit,
        )
    results: List[Dict[str, Any]] = []
    for r in rows:
        nid = str(r["id"])
        content = r["content"] or ""
        results.append({
            "id": nid,
            "title": r["title"] or "Untitled note",
            "parent_id": f"note:{nid}",
            "final_score": 0.5,           # text match has no cosine score
            "relevance": 0.5,
            "score": 0.5,
            "matches": [content[:300]] if content else [],
            "type": "note",
            "source_type": "note",
            "created": (r["created_at"].isoformat() if r["created_at"] else ""),
            "updated": (r["updated_at"].isoformat() if r["updated_at"] else ""),
            "_content": content[:300],
        })
    return results


@router.post("/search")
async def onb_search(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Cross-notebook search (open-notebook /search contract, types/search.ts).

    body: {query, type:'text'|'vector', limit, search_sources, search_notes, minimum_score}
    Returns: {results: SearchResult[], total_count, search_type}, parent-grouped with
    parent_id = 'source:<id>' | 'note:<id>'.
    """
    query = (body.get("query") or "").strip()
    if not query:
        return {"results": [], "total_count": 0, "search_type": body.get("type") or "text"}

    search_type = body.get("type") or "vector"
    try:
        limit = int(body.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    search_sources = body.get("search_sources", True)
    search_notes = body.get("search_notes", True)
    try:
        minimum_score = float(body.get("minimum_score") or 0.0)
    except (TypeError, ValueError):
        minimum_score = 0.0

    uid = current_user["id"]
    results: List[Dict[str, Any]] = []

    # Sources: vector search when type=='vector' (embed the query), ILIKE-on-chunks
    # otherwise. Notes are ILIKE-only (not embedded).
    if search_sources:
        if search_type == "vector":
            ingestion = IngestionService(manager)
            query_embedding = await ingestion.get_query_embedding(query)
            if query_embedding:
                results.extend(
                    await _search_user_chunks(manager, uid, query_embedding, limit, minimum_score)
                )
            else:
                logger.warning("onb_search: embedding unavailable, falling back to text on sources")
                results.extend(await _search_sources_text(manager, uid, query, limit))
        else:
            results.extend(await _search_sources_text(manager, uid, query, limit))

    if search_notes:
        results.extend(await _search_user_notes(manager, uid, query, limit))

    # Merge + rank across sources and notes, then trim.
    results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
    results = results[:limit]
    for r in results:
        r.pop("_content", None)

    return {
        "results": results,
        "total_count": len(results),
        "search_type": search_type,
    }


async def _search_sources_text(
    manager: "NotebookManager",
    user_id: int,
    query: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """ILIKE keyword fallback over the user's source chunks (parent-grouped). Used for
    type=='text' search and when embeddings are unavailable."""
    pattern = f"%{query.strip()}%"
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (s.id)
                   s.id            AS source_id,
                   s.title         AS source_title,
                   s.type          AS source_type,
                   s.created_at    AS created_at,
                   s.updated_at    AS updated_at,
                   c.content       AS content
            FROM notebook_chunks c
            JOIN notebook_sources s ON c.source_id = s.id
            JOIN notebooks n        ON c.notebook_id = n.id
            WHERE n.user_id = $1
              AND n.is_active = TRUE
              AND c.content ILIKE $2
            ORDER BY s.id, c.chunk_index
            LIMIT $3
            """,
            user_id, pattern, limit,
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        sid = str(r["source_id"])
        snippet = (r["content"] or "")[:300]
        out.append({
            "id": sid,
            "title": r["source_title"] or "Untitled source",
            "parent_id": f"source:{sid}",
            "final_score": 0.5,
            "relevance": 0.5,
            "score": 0.5,
            "matches": [snippet] if snippet else [],
            "type": "source",
            "source_type": r["source_type"],
            "created": (r["created_at"].isoformat() if r["created_at"] else ""),
            "updated": (r["updated_at"].isoformat() if r["updated_at"] else ""),
            "_content": snippet,
        })
    return out


@router.post("/search/ask")
async def onb_search_ask(
    body: Dict[str, Any],
    request: Request,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager),
):
    """Multi-search "ask the knowledge base" — text/event-stream (use-ask.ts reader).

    Full upstream-faithful strategy:
      1. emit {type:'strategy', reasoning, searches:[{term,instructions}]}  (LLM plans 2-4 searches)
      2. for each planned search: cross-notebook retrieval + LLM answer → emit {type:'answer', content}
      3. synthesise → emit {type:'final_answer', content}
      4. emit {type:'complete'}
    Any failure → emit {type:'error', message}.

    body: {question, strategy_model, answer_model, final_answer_model}
    """
    question = (body.get("question") or "").strip()
    ask_default = await _default_chat_model()
    strategy_model = (body.get("strategy_model") or ask_default).strip()
    answer_model = (body.get("answer_model") or ask_default).strip()
    final_model = (body.get("final_answer_model") or ask_default).strip()
    uid = current_user["id"]

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    ingestion = IngestionService(manager)

    async def _retrieve(term: str) -> List[Dict[str, Any]]:
        """Vector retrieve for one search term across the user's whole knowledge base,
        with an ILIKE fallback if embeddings are unavailable for this deploy."""
        emb = await ingestion.get_query_embedding(term)
        if emb:
            return await _search_user_chunks(manager, uid, emb, limit=5)
        return await _search_sources_text(manager, uid, term, limit=5)

    async def event_stream():
        try:
            # ── 1. STRATEGY: ask the planner LLM for 2-4 searches ─────────────────
            strategy_prompt = (
                "You are a research strategist for a personal knowledge base. Break the "
                "user's question into 2 to 4 focused search queries that will retrieve the "
                "most relevant passages. Respond with ONLY a JSON object of the form:\n"
                '{"reasoning": "<one sentence on your plan>", '
                '"searches": [{"term": "<search query>", "instructions": "<what to look for>"}]}\n'
                "Do not include any prose outside the JSON.\n\n"
                f"User question: {question}"
            )
            raw = await _ask_ollama_generate(strategy_model, strategy_prompt)

            reasoning = ""
            searches: List[Dict[str, str]] = []
            if raw:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        reasoning = (parsed.get("reasoning") or "").strip()
                        for s in (parsed.get("searches") or []):
                            term = (s.get("term") or "").strip()
                            if term:
                                searches.append({
                                    "term": term,
                                    "instructions": (s.get("instructions") or "").strip(),
                                })
                    except (ValueError, TypeError):
                        pass

            # Fallback plan if the planner produced nothing usable.
            if not searches:
                reasoning = reasoning or "Searching the knowledge base for the question directly."
                searches = [{"term": question, "instructions": "Find any directly relevant material."}]
            searches = searches[:4]

            yield _sse({"type": "strategy", "reasoning": reasoning, "searches": searches})
            await asyncio.sleep(0)

            # ── 2. PER-SEARCH retrieval + answer ──────────────────────────────────
            collected_answers: List[str] = []
            for s in searches:
                term = s["term"]
                instructions = s.get("instructions") or ""
                hits = await _retrieve(term)

                if not hits:
                    content = f"No relevant material found in your knowledge base for: {term}"
                    collected_answers.append(content)
                    yield _sse({"type": "answer", "content": content})
                    await asyncio.sleep(0)
                    continue

                context_parts = []
                for i, h in enumerate(hits, 1):
                    body_text = h.get("_content") or " ".join(h.get("matches") or [])
                    context_parts.append(f"[{i}] {h.get('title')}: {body_text}")
                context_text = "\n".join(context_parts)[:8000]

                answer_prompt = (
                    "You are a research assistant answering ONLY from the provided context. "
                    "If the context does not contain the answer, say so plainly.\n\n"
                    f"Search focus: {term}\n"
                    f"What to look for: {instructions}\n\n"
                    f"Context:\n{context_text}\n\n"
                    f"Original question: {question}\n\n"
                    "Write a concise, grounded answer for this search."
                )
                content = await _ask_ollama_generate(answer_model, answer_prompt)
                if not content:
                    content = f"(no answer generated for: {term})"
                collected_answers.append(content)
                yield _sse({"type": "answer", "content": content})
                await asyncio.sleep(0)

            # ── 3. SYNTHESIS: final answer from all sub-answers ───────────────────
            joined = "\n\n".join(
                f"Search {i}: {searches[i-1]['term']}\n{ans}"
                for i, ans in enumerate(collected_answers, 1)
            )[:12000]
            final_prompt = (
                "You are synthesising a final answer from several focused searches over the "
                "user's knowledge base. Combine the findings below into one cohesive, accurate "
                "answer to the user's question. Do not invent facts beyond the findings.\n\n"
                f"User question: {question}\n\n"
                f"Findings:\n{joined}\n\n"
                "Final answer:"
            )
            final_answer = await _ask_ollama_generate(final_model, final_prompt)
            if not final_answer:
                final_answer = "\n\n".join(collected_answers) or "No answer could be generated."

            yield _sse({"type": "final_answer", "content": final_answer})
            await asyncio.sleep(0)
            yield _sse({"type": "complete"})

        except Exception as e:  # noqa: BLE001 — stream a structured error frame
            logger.error(f"onb_search_ask failed: {e}")
            yield _sse({"type": "error", "message": str(e)[:500]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
