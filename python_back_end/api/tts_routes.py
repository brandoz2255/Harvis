"""
TTS API Routes - Proxy to TTS Service
"""

import os
import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])

# TTS Service URL
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "http://tts-service:8001")
TIMEOUT = httpx.Timeout(600.0, connect=10.0)  # 10 minute timeout for generation


# ─── Voice Management ────────────────────────────────────────────────────────

@router.get("/voices")
async def list_voices(user_id: Optional[str] = None):
    """List all available voices"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            params = {"user_id": user_id} if user_id else {}
            response = await client.get(f"{TTS_SERVICE_URL}/voices", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.warning(f"TTS service not available: {e}")
            # Return empty voices list when TTS service is unavailable
            return {"voices": [], "count": 0, "service_status": "unavailable"}


@router.get("/voices/{voice_id}")
async def get_voice(voice_id: str):
    """Get a specific voice"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(f"{TTS_SERVICE_URL}/voices/{voice_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


@router.post("/voices/clone")
async def clone_voice(
    voice_name: str = Query(..., description="Name for the cloned voice"),
    audio_sample: UploadFile = File(..., description="Audio sample (10-60 seconds)"),
    description: Optional[str] = Query(None, description="Voice description"),
    user_id: Optional[str] = Query(None, description="User identifier")
):
    """Clone a voice from an audio sample"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            # Read file content
            file_content = await audio_sample.read()
            
            # Build request
            files = {"audio_sample": (audio_sample.filename, file_content, audio_sample.content_type)}
            params = {"voice_name": voice_name}
            if description:
                params["description"] = description
            if user_id:
                params["user_id"] = user_id
            
            response = await client.post(
                f"{TTS_SERVICE_URL}/voices/clone",
                params=params,
                files=files
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.warning(f"TTS service not available for voice cloning: {e}")
            raise HTTPException(
                503, 
                "Voice cloning requires the TTS service to be running. "
                "Start it with: docker-compose up tts-service"
            )


@router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a user voice"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.delete(f"{TTS_SERVICE_URL}/voices/{voice_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


# ─── Voice Presets ───────────────────────────────────────────────────────────

@router.get("/presets")
async def get_presets():
    """Get built-in voice presets"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(f"{TTS_SERVICE_URL}/presets")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.warning(f"TTS service not available: {e}")
            # Return built-in presets metadata when TTS service is unavailable
            return {
                "presets": [
                    {"preset_id": "narrator_morgan", "name": "Morgan Freeman Style", "description": "Warm, authoritative narrator voice", "category": "narrator", "activated": False},
                    {"preset_id": "narrator_david", "name": "David Attenborough Style", "description": "Gentle, contemplative voice for nature content", "category": "narrator", "activated": False},
                    {"preset_id": "host_professional_male", "name": "Professional Host (Male)", "description": "Clear, engaging voice for podcasts", "category": "host", "activated": False},
                    {"preset_id": "host_professional_female", "name": "Professional Host (Female)", "description": "Warm, articulate voice for interviews", "category": "host", "activated": False},
                ],
                "count": 4,
                "service_status": "unavailable"
            }


@router.post("/presets/{preset_id}/activate")
async def activate_preset(
    preset_id: str,
    audio_sample: UploadFile = File(..., description="Reference audio for this preset")
):
    """Activate a built-in preset by providing reference audio"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            file_content = await audio_sample.read()
            files = {"audio_sample": (audio_sample.filename, file_content, audio_sample.content_type)}
            
            response = await client.post(
                f"{TTS_SERVICE_URL}/presets/{preset_id}/activate",
                files=files
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


# ─── Audio Generation ────────────────────────────────────────────────────────

@router.post("/generate/speech")
async def generate_speech(request: Dict[str, Any]):
    """Generate speech from text"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{TTS_SERVICE_URL}/generate/speech",
                json=request
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


@router.post("/generate/podcast")
async def generate_podcast(request: Dict[str, Any]):
    """Generate multi-speaker podcast"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{TTS_SERVICE_URL}/generate/podcast",
                json=request
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, e.response.text)
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


# ─── Audio Serving ───────────────────────────────────────────────────────────

@router.get("/audio/{filename}")
async def get_audio(filename: str):
    """Proxy audio file from TTS service"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(
                f"{TTS_SERVICE_URL}/audio/{filename}",
                follow_redirects=True
            )
            response.raise_for_status()
            
            return StreamingResponse(
                iter([response.content]),
                media_type=response.headers.get("content-type", "audio/wav"),
                headers={
                    "Content-Disposition": f'inline; filename="{filename}"'
                }
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, "Audio file not found")
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


@router.get("/voices/{voice_id}/sample")
async def get_voice_sample(voice_id: str):
    """Get the reference audio sample for a voice"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.get(
                f"{TTS_SERVICE_URL}/voices/{voice_id}/sample",
                follow_redirects=True
            )
            response.raise_for_status()
            
            return StreamingResponse(
                iter([response.content]),
                media_type="audio/wav",
                headers={
                    "Content-Disposition": f'inline; filename="{voice_id}_sample.wav"'
                }
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, "Voice sample not found")
        except httpx.RequestError as e:
            logger.error(f"TTS service connection error: {e}")
            raise HTTPException(503, "TTS service unavailable")


# ─── Health Check ────────────────────────────────────────────────────────────

@router.get("/health")
async def tts_health():
    """Check TTS service health"""
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        try:
            response = await client.get(f"{TTS_SERVICE_URL}/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {
                "status": "unavailable",
                "error": str(e)
            }
