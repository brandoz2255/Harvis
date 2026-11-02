"""Downloads for Studio artifacts: a data table as CSV, a slide deck as PPTX.

``onb_compat.router`` calls :func:`register` once, so these routes live on its router
(prefix ``/onb-api``) with its own auth and manager dependencies. Both routes are scoped to
the caller: the artifact must belong to the notebook in the URL and to the signed-in person.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from . import studio_kinds as kinds

logger = logging.getLogger(__name__)

CSV_TYPE = "text/csv; charset=utf-8"
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


async def _load_artifact(manager: Any, clean_uuid: Callable[[str], Any], notebook_id: str, artifact_id: str,
                         user_id: Any, kind: str) -> Dict[str, Any]:
    try:
        nb_uuid, art_uuid = clean_uuid(notebook_id), clean_uuid(artifact_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id")
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT kind, title, content FROM onb_notebook_artifacts "
            "WHERE id = $1 AND notebook_id = $2 AND user_id = $3",
            art_uuid, nb_uuid, user_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if row["kind"] != kind:
        raise HTTPException(status_code=400, detail=f"This artifact is a {row['kind']}, not a {kind}.")
    content: Optional[Any] = row["content"]
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            content = None
    if not isinstance(content, dict):
        raise HTTPException(status_code=409, detail="This artifact has no readable content.")
    return {"title": row["title"], "content": content}


def _download(body: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def register(router: APIRouter, *, auth: Callable[..., Any], get_manager: Callable[..., Any],
             clean_uuid: Callable[[str], Any]) -> None:
    @router.get("/notebooks/{notebook_id}/artifacts/{artifact_id}/export.csv")
    async def export_data_table_csv(
        notebook_id: str,
        artifact_id: str,
        request: Request,
        current_user: Dict = Depends(auth),
        manager: Any = Depends(get_manager),
    ):
        art = await _load_artifact(manager, clean_uuid, notebook_id, artifact_id, current_user["id"], "data_table")
        name = kinds.safe_filename(art["content"].get("title") or art["title"], "data-table", "csv")
        return _download(kinds.table_to_csv(art["content"]), CSV_TYPE, name)

    @router.get("/notebooks/{notebook_id}/artifacts/{artifact_id}/export.pptx")
    async def export_slides_pptx(
        notebook_id: str,
        artifact_id: str,
        request: Request,
        current_user: Dict = Depends(auth),
        manager: Any = Depends(get_manager),
    ):
        art = await _load_artifact(manager, clean_uuid, notebook_id, artifact_id, current_user["id"], "slides")
        try:
            body = await asyncio.to_thread(kinds.slides_to_pptx, art["content"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ImportError:
            raise HTTPException(status_code=501, detail="PowerPoint export needs the python-pptx package on the server.")
        name = kinds.safe_filename(art["content"].get("title") or art["title"], "slides", "pptx")
        return _download(body, PPTX_TYPE, name)
