"""
TTS Service - FastAPI server for voice cloning and podcast generation
With RVC (Retrieval-based Voice Conversion) support for character voices
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from .engines.vibevoice_engine import VibeVoiceEngine
from .engines.rvc_engine import get_rvc_engine, RVC_MODELS_DIR
from .services.voice_catalog import get_voice_catalog_service, VoiceCatalogService
from .models.voice_model import (
    PodcastRequest,
    SpeechRequest,
    GenerationSettings
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/output"))
VOICES_DIR = Path(os.getenv("VOICES_DIR", "/app/voices"))
HOST = os.getenv("TTS_HOST", "0.0.0.0")
PORT = int(os.getenv("TTS_PORT", "8001"))

# Global engine instances
engine: Optional[VibeVoiceEngine] = None
rvc_engine = None
catalog_service: Optional[VoiceCatalogService] = None


# ─── RVC Request Models ───────────────────────────────────────────────────────

class RVCVoiceImportRequest(BaseModel):
    """Request model for importing RVC voice"""
    name: str
    slug: str
    category: str = "custom"
    description: Optional[str] = None
    pitch_shift: int = 0

class RVCSpeechRequest(BaseModel):
    """Request model for generating speech with RVC"""
    text: str
    base_voice_id: str  # Voice ID for base TTS
    rvc_voice_slug: str  # RVC voice to apply
    pitch_shift: int = 0
    settings: Optional[GenerationSettings] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global engine, rvc_engine, catalog_service
    
    logger.info("🎙️ Starting TTS Service...")
    
    # Ensure directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    RVC_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize TTS engine
    engine = VibeVoiceEngine()
    
    try:
        await engine.initialize()
        logger.info("✅ TTS Engine Ready!")
    except Exception as e:
        logger.error(f"❌ TTS Engine initialization failed: {e}")
    
    # Initialize RVC engine
    try:
        rvc_engine = get_rvc_engine()
        rvc_available = await rvc_engine.initialize()
        if rvc_available:
            logger.info("✅ RVC Engine Ready!")
        else:
            logger.warning(f"⚠️ RVC Engine not available: {rvc_engine.get_init_error()}")
    except Exception as e:
        logger.warning(f"⚠️ RVC Engine initialization failed: {e}")
        rvc_engine = None
    
    # Initialize voice catalog service
    try:
        catalog_service = get_voice_catalog_service()
        logger.info("✅ Voice Catalog Service Ready!")
    except Exception as e:
        logger.warning(f"⚠️ Voice Catalog Service initialization failed: {e}")
        catalog_service = None
    
    logger.info("✅ TTS Service Ready!")
    
    yield
    
    logger.info("🛑 Shutting down TTS Service...")


app = FastAPI(
    title="HARVIS TTS Service",
    description="Voice cloning and podcast generation using VibeVoice",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health & Status ─────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "engine_info": engine.get_engine_info() if engine else None
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "HARVIS TTS",
        "version": "0.2.0",
        "features": {
            "tts": True,
            "voice_cloning": True,
            "rvc": rvc_engine.is_available() if rvc_engine else False
        },
        "endpoints": {
            "health": "/health",
            "voices": "/voices",
            "clone": "/voices/clone",
            "generate_speech": "/generate/speech",
            "generate_podcast": "/generate/podcast",
            "presets": "/presets",
            "rvc_voices": "/rvc/voices",
            "rvc_import": "/rvc/voices/import",
            "rvc_speech": "/rvc/generate/speech"
        }
    }


# ─── Voice Management ────────────────────────────────────────────────────────

@app.get("/voices")
async def list_voices(user_id: Optional[str] = None):
    """List all available voices"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    voices = await engine.list_voices(user_id)
    return {
        "voices": voices,
        "count": len(voices)
    }


@app.get("/voices/{voice_id}")
async def get_voice(voice_id: str):
    """Get a specific voice"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    voice = await engine.get_voice(voice_id)
    if not voice:
        raise HTTPException(404, f"Voice not found: {voice_id}")
    
    return voice


@app.post("/voices/clone")
async def clone_voice(
    voice_name: str = Query(..., description="Name for the cloned voice"),
    audio_sample: UploadFile = File(..., description="Audio sample (10-60 seconds)"),
    description: Optional[str] = Query(None, description="Voice description"),
    user_id: Optional[str] = Query(None, description="User identifier")
):
    """Clone a voice from an audio sample (supports clips of any length)"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    # Validate file type - be permissive for various audio formats
    content_type = audio_sample.content_type or ""
    filename = audio_sample.filename or ""
    valid_extensions = [".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".aac", ".opus", ".wma"]
    
    # Accept if content type starts with audio/ OR video/ (for video/webm etc) OR has valid extension
    is_audio_content_type = content_type.startswith("audio/") or content_type.startswith("video/")
    has_valid_extension = any(filename.lower().endswith(ext) for ext in valid_extensions)
    
    if not is_audio_content_type and not has_valid_extension:
        logger.warning(f"Rejected file: content_type={content_type}, filename={filename}")
        raise HTTPException(400, f"Invalid file type '{content_type}'. Please upload an audio file (.wav, .mp3, .m4a, etc.)")
    
    # Save uploaded file temporarily
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        content = await audio_sample.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        result = await engine.clone_voice(
            audio_path=tmp_path,
            voice_name=voice_name,
            description=description,
            user_id=user_id
        )
        
        if not result.get("success"):
            raise HTTPException(400, result.get("error", "Voice cloning failed"))
        
        return result
        
    finally:
        # Cleanup temp file
        Path(tmp_path).unlink(missing_ok=True)


@app.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a user voice"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    success = await engine.delete_voice(voice_id)
    if not success:
        raise HTTPException(404, f"Voice not found or cannot be deleted: {voice_id}")
    
    return {"success": True, "message": f"Voice {voice_id} deleted"}


# ─── Voice Presets ───────────────────────────────────────────────────────────

@app.get("/presets")
async def get_presets():
    """Get built-in voice presets"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    presets = engine.get_presets()
    
    # Check activation status
    presets_with_status = []
    for preset_id, preset_data in presets.items():
        activated = (VOICES_DIR / preset_id / "reference.wav").exists()
        presets_with_status.append({
            "preset_id": preset_id,
            **preset_data,
            "activated": activated
        })
    
    return {
        "presets": presets_with_status,
        "count": len(presets_with_status)
    }


@app.post("/presets/{preset_id}/activate")
async def activate_preset(
    preset_id: str,
    audio_sample: UploadFile = File(..., description="Reference audio for this preset")
):
    """Activate a built-in preset by providing reference audio"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    presets = engine.get_presets()
    if preset_id not in presets:
        raise HTTPException(404, f"Preset not found: {preset_id}")
    
    preset = presets[preset_id]
    
    # Clone voice with preset ID
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        content = await audio_sample.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        result = await engine.clone_voice(
            audio_path=tmp_path,
            voice_name=preset.get("name", preset_id),
            description=preset.get("description"),
            user_id=None  # Presets are global
        )
        
        if result.get("success"):
            # Move to preset directory
            import shutil
            voice_data = result.get("voice", {})
            old_id = voice_data.get("voice_id")
            if old_id:
                old_dir = VOICES_DIR / old_id
                new_dir = VOICES_DIR / preset_id
                if old_dir.exists():
                    if new_dir.exists():
                        shutil.rmtree(new_dir)
                    shutil.move(str(old_dir), str(new_dir))
                    
                    # Update metadata
                    metadata_path = new_dir / "metadata.json"
                    if metadata_path.exists():
                        import json
                        with open(metadata_path) as f:
                            metadata = json.load(f)
                        metadata["voice_id"] = preset_id
                        metadata["voice_type"] = "builtin"
                        with open(metadata_path, "w") as f:
                            json.dump(metadata, f, indent=2)
        
        return {"success": True, "preset_id": preset_id, "activated": True}
        
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ─── RVC Voice Management ─────────────────────────────────────────────────────

@app.get("/rvc/status")
async def rvc_status():
    """Get RVC engine status"""
    if not rvc_engine:
        return {"available": False, "error": "RVC engine not initialized"}
    
    return rvc_engine.engine_info()


@app.get("/rvc/voices")
async def list_rvc_voices():
    """List all available RVC character voices"""
    if not rvc_engine:
        return {"voices": [], "count": 0, "rvc_available": False}
    
    voices = await rvc_engine.list_available_models()
    return {
        "voices": voices,
        "count": len(voices),
        "rvc_available": rvc_engine.is_available(),
        "cached_models": rvc_engine.get_cached_models()
    }


@app.post("/rvc/voices/import")
async def import_rvc_voice(
    name: str = Form(..., description="Voice name (e.g., 'Peter Griffin')"),
    slug: str = Form(..., description="URL-friendly slug (e.g., 'peter_griffin')"),
    category: str = Form("custom", description="Category: cartoon, tv_show, celebrity, custom"),
    description: Optional[str] = Form(None, description="Voice description"),
    pitch_shift: int = Form(0, description="Default pitch shift (-12 to +12)"),
    model_file: UploadFile = File(..., description="RVC model file (.pth)"),
    index_file: Optional[UploadFile] = File(None, description="Optional index file (.index)")
):
    """Import an RVC voice model"""
    if not rvc_engine:
        raise HTTPException(503, "RVC engine not initialized")
    
    # Validate file types
    if not model_file.filename.endswith(".pth"):
        raise HTTPException(400, "Model file must be a .pth file")
    
    if index_file and not index_file.filename.endswith(".index"):
        raise HTTPException(400, "Index file must be a .index file")
    
    # Sanitize slug
    import re
    slug = re.sub(r'[^a-z0-9_]', '_', slug.lower())
    
    # Create voice directory
    voice_dir = RVC_MODELS_DIR / slug
    if voice_dir.exists():
        raise HTTPException(400, f"Voice with slug '{slug}' already exists")
    
    voice_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Save model file
        model_path = voice_dir / f"{slug}.pth"
        model_content = await model_file.read()
        model_path.write_bytes(model_content)
        
        # Save index file if provided
        index_path = None
        if index_file:
            index_path = voice_dir / f"{slug}.index"
            index_content = await index_file.read()
            index_path.write_bytes(index_content)
        
        # Save metadata
        metadata = {
            "name": name,
            "slug": slug,
            "category": category,
            "description": description,
            "pitch_shift": pitch_shift,
            "model_path": str(model_path),
            "index_path": str(index_path) if index_path else None,
            "created_at": __import__("datetime").datetime.utcnow().isoformat()
        }
        metadata_path = voice_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"✅ Imported RVC voice: {name} ({slug})")
        
        return {
            "success": True,
            "voice": metadata
        }
        
    except Exception as e:
        # Cleanup on failure
        if voice_dir.exists():
            shutil.rmtree(voice_dir)
        logger.error(f"❌ Failed to import RVC voice: {e}")
        raise HTTPException(500, f"Failed to import voice: {e}")


@app.get("/rvc/voices/{slug}")
async def get_rvc_voice(slug: str):
    """Get details about an RVC voice"""
    voice_dir = RVC_MODELS_DIR / slug
    metadata_path = voice_dir / "metadata.json"
    
    if not metadata_path.exists():
        raise HTTPException(404, f"RVC voice not found: {slug}")
    
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    metadata["is_cached"] = rvc_engine.is_cached(slug) if rvc_engine else False
    return metadata


@app.delete("/rvc/voices/{slug}")
async def delete_rvc_voice(slug: str):
    """Delete an RVC voice"""
    voice_dir = RVC_MODELS_DIR / slug
    
    if not voice_dir.exists():
        raise HTTPException(404, f"RVC voice not found: {slug}")
    
    # Unload from cache first
    if rvc_engine and rvc_engine.is_cached(slug):
        await rvc_engine.unload_model(slug)
    
    # Delete directory
    shutil.rmtree(voice_dir)
    logger.info(f"🗑️ Deleted RVC voice: {slug}")
    
    return {"success": True, "message": f"Deleted RVC voice: {slug}"}


@app.post("/rvc/voices/{slug}/cache")
async def cache_rvc_voice(slug: str):
    """Pre-load an RVC voice into VRAM cache"""
    if not rvc_engine:
        raise HTTPException(503, "RVC engine not initialized")
    
    if not rvc_engine.is_available():
        raise HTTPException(503, f"RVC not available: {rvc_engine.get_init_error()}")
    
    resolved = rvc_engine.get_model_path(slug)
    if not resolved:
        raise HTTPException(404, f"RVC voice not found: {slug}")
    model_path, index_path = resolved

    success = await rvc_engine.load_model(
        slug=slug,
        model_path=model_path,
        index_path=index_path,
    )
    
    if not success:
        raise HTTPException(500, f"Failed to cache voice: {slug}")
    
    return {
        "success": True,
        "slug": slug,
        "cached": True,
        "cached_models": rvc_engine.get_cached_models()
    }


@app.post("/rvc/voices/{slug}/uncache")
async def uncache_rvc_voice(slug: str):
    """Remove an RVC voice from VRAM cache"""
    if not rvc_engine:
        raise HTTPException(503, "RVC engine not initialized")
    
    success = await rvc_engine.unload_model(slug)
    
    return {
        "success": success,
        "slug": slug,
        "cached": False,
        "cached_models": rvc_engine.get_cached_models()
    }


@app.post("/rvc/generate/speech")
async def generate_rvc_speech(request: RVCSpeechRequest):
    """Generate speech with RVC voice conversion"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    if not rvc_engine or not rvc_engine.is_available():
        raise HTTPException(503, "RVC engine not available")
    
    resolved = rvc_engine.get_model_path(request.rvc_voice_slug)
    if not resolved:
        raise HTTPException(404, f"RVC voice not found: {request.rvc_voice_slug}")
    model_path, index_path = resolved
    
    settings = request.settings.dict() if request.settings else {}
    
    # Generate speech with RVC post-processing
    audio_path, duration = await engine.generate_speech(
        text=request.text,
        voice_id=request.base_voice_id,
        settings=settings,
        rvc_voice_slug=request.rvc_voice_slug,
        rvc_model_path=model_path,
        rvc_index_path=index_path,
        rvc_pitch_shift=request.pitch_shift or 0,
    )
    
    if not audio_path:
        raise HTTPException(500, "Speech generation with RVC failed")
    
    return {
        "success": True,
        "audio_url": f"/audio/{Path(audio_path).name}",
        "audio_path": audio_path,
        "duration": duration,
        "rvc_voice": request.rvc_voice_slug
    }


# ─── Voice Catalog (voice-models.com) ─────────────────────────────────────────

class VoiceImportUrlRequest(BaseModel):
    """Request model for importing voice from URL"""
    url: str
    name: str
    slug: str
    category: str = "custom"
    description: str = ""
    pitch_shift: int = 0
    user_id: str


@app.get("/rvc/catalog/search")
async def search_voice_catalog(
    q: str = Query("", description="Search query"),
    category: str = Query("", description="Filter by category"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Results per page")
):
    """Search voice models from voice-models.com catalog"""
    if not catalog_service:
        raise HTTPException(503, "Voice catalog service not initialized")
    
    results = await catalog_service.search(
        query=q,
        category=category,
        page=page,
        per_page=per_page
    )
    
    return results


@app.get("/rvc/catalog/popular")
async def get_popular_voices(
    limit: int = Query(20, ge=1, le=100, description="Number of voices to return")
):
    """Get popular voice models"""
    if not catalog_service:
        raise HTTPException(503, "Voice catalog service not initialized")
    
    voices = await catalog_service.get_popular(limit=limit)
    return {"voices": voices, "count": len(voices)}


@app.get("/rvc/catalog/categories")
async def get_voice_categories():
    """Get available voice categories"""
    if not catalog_service:
        raise HTTPException(503, "Voice catalog service not initialized")
    
    categories = await catalog_service.get_categories()
    return {"categories": categories}


@app.post("/rvc/voices/import-url")
async def import_voice_from_url(request: VoiceImportUrlRequest):
    """
    Import a voice model from URL (e.g., from voice-models.com)
    
    Downloads the zip file, extracts .pth and .index files,
    and saves to user's RVC models directory.
    """
    if not catalog_service:
        raise HTTPException(503, "Voice catalog service not initialized")
    
    if not request.url:
        raise HTTPException(400, "Download URL is required")
    
    if not request.user_id:
        raise HTTPException(400, "User ID is required")
    
    logger.info(f"🔄 Importing voice from URL: {request.url} for user {request.user_id}")
    
    result = await catalog_service.download_and_import(
        url=request.url,
        name=request.name,
        slug=request.slug,
        category=request.category,
        user_id=request.user_id,
        description=request.description,
        pitch_shift=request.pitch_shift
    )
    
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Import failed"))
    
    return result


@app.get("/rvc/voices/user/{user_id}")
async def list_user_rvc_voices(user_id: str):
    """List RVC voices for a specific user"""
    if not catalog_service:
        raise HTTPException(503, "Voice catalog service not initialized")

    # Combine shared + legacy + user-specific models
    voices = await rvc_engine.list_available_models(user_id=user_id) if rvc_engine else []

    return {"voices": voices, "count": len(voices), "user_id": user_id}


# ─── Audio Generation ────────────────────────────────────────────────────────

@app.post("/generate/speech")
async def generate_speech(request: SpeechRequest):
    """Generate speech from text"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    settings = request.settings.dict() if request.settings else {}
    
    audio_path, duration = await engine.generate_speech(
        text=request.text,
        voice_id=request.voice_id,
        settings=settings
    )
    
    if not audio_path:
        raise HTTPException(500, "Speech generation failed")
    
    return {
        "success": True,
        "audio_url": f"/audio/{Path(audio_path).name}",
        "audio_path": audio_path,
        "duration": duration
    }


@app.post("/generate/podcast")
async def generate_podcast(request: PodcastRequest):
    """Generate multi-speaker podcast with optional RVC voices"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    # Convert script to dict format
    script = [{"speaker": s.speaker, "text": s.text, "voice_id": s.voice_id} 
              for s in request.script]
    
    settings = request.settings.dict() if request.settings else {}
    settings["normalize_audio"] = request.normalize_audio
    settings["add_silence_between_speakers"] = request.add_silence_between_speakers
    
    # Build RVC voice mapping if RVC voices are specified
    rvc_voice_mapping = {}
    if hasattr(request, 'rvc_voice_mapping') and request.rvc_voice_mapping:
        for speaker, rvc_slug in request.rvc_voice_mapping.items():
            resolved = rvc_engine.get_model_path(rvc_slug) if rvc_engine else None
            if resolved:
                model_path, index_path = resolved
                rvc_voice_mapping[speaker] = {
                    "slug": rvc_slug,
                    "model_path": model_path,
                    "index_path": index_path,
                    "pitch_shift": 0,
                }
    
    result = await engine.generate_podcast(
        script=script,
        voice_mapping=request.voice_mapping,
        settings=settings,
        rvc_voice_mapping=rvc_voice_mapping
    )
    
    if not result.get("success"):
        # Preserve engine-provided debugging details (e.g., why segments were skipped)
        raise HTTPException(
            status_code=500,
            detail={
                "error": result.get("error", "Podcast generation failed"),
                "details": result.get("details"),
            },
        )
    
    return result


# ─── Audio Serving ───────────────────────────────────────────────────────────

@app.get("/audio/{filename}")
async def get_audio(filename: str):
    """Serve generated audio file"""
    file_path = OUTPUT_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(404, f"Audio file not found: {filename}")
    
    # Determine content type
    suffix = file_path.suffix.lower()
    content_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg"
    }
    content_type = content_types.get(suffix, "audio/wav")
    
    return FileResponse(
        file_path,
        media_type=content_type,
        filename=filename
    )


@app.get("/voices/{voice_id}/sample")
async def get_voice_sample(voice_id: str):
    """Get the reference audio sample for a voice"""
    sample_path = VOICES_DIR / voice_id / "reference.wav"
    
    if not sample_path.exists():
        raise HTTPException(404, f"Voice sample not found: {voice_id}")
    
    return FileResponse(
        sample_path,
        media_type="audio/wav",
        filename=f"{voice_id}_sample.wav"
    )


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    """Run the TTS server"""
    uvicorn.run(
        "tts_system.server:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
