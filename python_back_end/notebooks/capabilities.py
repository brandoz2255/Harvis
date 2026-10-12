"""What this server can do for a notebook right now, so the UI can say so up front.

Each entry is ``{"ready": bool, "reason": str}``. ``reason`` is one plain sentence
shown next to a disabled control or an "Under construction" badge; it is empty when
the feature is ready. Nothing here changes state, and every probe is short.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notebooks-capabilities"])


async def _user(request: Request) -> Dict:
    from .router import get_current_user_from_request

    return await get_current_user_from_request(request)


def _entry(ready: bool, reason: str = "", **extra: Any) -> Dict[str, Any]:
    return {"ready": bool(ready), "reason": "" if ready else reason, **extra}


def _embedder() -> Dict[str, Any]:
    from .ingestion import EMBEDDING_MODEL, IngestionService

    installed = IngestionService._installed_models()
    if not installed:
        return _entry(False, "No model is installed for reading sources. Run: ollama pull nomic-embed-text")
    wanted = EMBEDDING_MODEL.split(":")[0]
    dedicated = any(n.split(":")[0] == wanted for n in installed)
    return _entry(True, model=EMBEDDING_MODEL if dedicated else installed[0], dedicated=dedicated)


def _speech_to_text() -> Dict[str, Any]:
    try:
        import transcription

        state = transcription.status()
    except Exception:
        return _entry(False, "Speech-to-text is not installed on this server.")
    if state.get("server_transcribes"):
        return _entry(True, provider=state.get("provider"))
    return _entry(False, "This server has no speech-to-text turned on, so audio files cannot be transcribed.")


def _images() -> Dict[str, Any]:
    ocr = bool(shutil.which("tesseract"))
    vision = ""
    try:
        from vison_models.llm_connector import resolve_vision_model

        vision = resolve_vision_model() or ""
    except Exception:
        vision = ""
    if vision or ocr:
        return _entry(True, vision_model=vision, ocr=ocr)
    return _entry(False, "No vision model or OCR is available. Run: ollama pull llava")


async def _speech_out() -> Dict[str, Any]:
    if os.environ.get("TTS_URL"):
        url = os.environ["TTS_URL"].rstrip("/")
    else:
        from .podcast_audio import speech_url

        url = speech_url().rsplit("/v1/", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(url)
        if resp.status_code < 500:
            return _entry(True)
    except Exception:
        pass
    return _entry(False, "The speech service is not running, so podcasts will be saved as a script only.")


def _web_search() -> Dict[str, Any]:
    try:
        from agent_reach.tools import web_search  # noqa: F401
    except Exception:
        return _entry(False, "Web search is not available on this server.")
    return _entry(True)


def _deep_research() -> Dict[str, Any]:
    try:
        import deep_research.router  # noqa: F401
    except Exception:
        return _entry(False, "Deep research is not available on this server.")
    return _entry(True)


@router.get("/meta/capabilities")
async def notebook_capabilities(current_user: Dict = Depends(_user)):
    embedder, images = await asyncio.gather(asyncio.to_thread(_embedder), asyncio.to_thread(_images))
    return {
        "embedder": embedder,
        "audio_sources": await asyncio.to_thread(_speech_to_text),
        "image_sources": images,
        "podcast_audio": await _speech_out(),
        "web_search": _web_search(),
        "deep_research": _deep_research(),
    }
