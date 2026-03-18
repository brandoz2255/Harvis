
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import logging
import uuid
import os
import soundfile as sf
# Import model_manager to access Chatterbox generation directly for debugging

from tts_engine_manager import (
    TTSMode, set_mode, get_mode, generate_speech as tts_generate,
    generate_podcast_segment, get_engine_status, unload_all_engines
)
from voice_model_manager import (
    VoiceModelManager, download_popular_model, POPULAR_MODELS
)

router = APIRouter(tags=["local-podcast"])
logger = logging.getLogger(__name__)

voice_manager = VoiceModelManager()

class PodcastSegmentRequest(BaseModel):
    text: str
    character_voice: str
    
class VoiceModelDownloadRequest(BaseModel):
    url: str
    name: Optional[str] = None
    tags: Optional[List[str]] = None

class TTSModeRequest(BaseModel):
    mode: str  # "interactive", "podcast", "lightweight"

@router.post("/api/tts/set-mode")
async def api_set_tts_mode(req: TTSModeRequest):
    """Set the TTS generation mode"""
    mode_map = {
        "interactive": TTSMode.INTERACTIVE,
        "podcast": TTSMode.PODCAST,
        "lightweight": TTSMode.LIGHTWEIGHT
    }
    
    if req.mode not in mode_map:
        raise HTTPException(400, f"Invalid mode. Use: {list(mode_map.keys())}")
    
    set_mode(mode_map[req.mode])
    return {"status": "ok", "mode": req.mode}

@router.get("/api/tts/status")
async def api_get_tts_status():
    """Get status of all TTS engines"""
    return get_engine_status()

@router.post("/api/podcast/generate-segment")
async def api_generate_podcast_segment(req: PodcastSegmentRequest):
    """Generate a podcast segment with character voice"""
    try:
        sr, audio = generate_podcast_segment(
            req.text,
            req.character_voice,
            voice_models_dir=str(voice_manager.models_dir)
        )
        
        # Save to temp file
        output_path = f"/tmp/podcast_segment_{uuid.uuid4()}.wav"
        sf.write(output_path, audio, sr)
        
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename=f"segment_{req.character_voice}.wav"
        )
        
    except FileNotFoundError as e:
        raise HTTPException(404, f"Voice model not found: {req.character_voice}")
    except Exception as e:
        logger.error(f"Podcast generation failed: {e}")
        raise HTTPException(500, str(e))

@router.get("/api/voice-models/list")
async def api_list_voice_models(tag: Optional[str] = None):
    """List available voice models"""
    models = voice_manager.list_models(tag=tag)
    return {
        "count": len(models),
        "models": [
            {
                "name": m.name,
                "epochs": m.epochs,
                "size_mb": m.file_size_mb,
                "tags": m.tags,
                "has_index": m.index_path is not None
            }
            for m in models
        ]
    }

@router.get("/api/voice-models/popular")
async def api_list_popular_models():
    """List pre-configured popular voice models"""
    return {
        "models": list(POPULAR_MODELS.keys()),
        "note": "Use POST /api/voice-models/download-popular/{name} to download"
    }

@router.post("/api/voice-models/download")
async def api_download_voice_model(req: VoiceModelDownloadRequest):
    """Download a voice model from HuggingFace URL"""
    info = voice_manager.download_model(
        req.url,
        name=req.name,
        tags=req.tags
    )
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb,
        "epochs": info.epochs
    }

@router.post("/api/voice-models/download-popular/{name}")
async def api_download_popular_model(name: str):
    """Download a pre-configured popular voice model"""
    if name not in POPULAR_MODELS:
        raise HTTPException(404, f"Unknown model. Available: {list(POPULAR_MODELS.keys())}")
    
    info = download_popular_model(name, voice_manager)
    
    if info is None:
        raise HTTPException(500, "Download failed")
    
    return {
        "status": "ok",
        "name": info.name,
        "size_mb": info.file_size_mb
    }

@router.delete("/api/voice-models/{name}")
async def api_delete_voice_model(name: str):
    """Delete a voice model"""
    if voice_manager.delete_model(name):
        return {"status": "ok", "deleted": name}
    raise HTTPException(404, f"Model not found: {name}")
