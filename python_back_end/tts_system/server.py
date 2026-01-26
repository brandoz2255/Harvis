"""
TTS Service - FastAPI server for voice cloning and podcast generation
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .engines.vibevoice_engine import VibeVoiceEngine
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

# Global engine instance
engine: Optional[VibeVoiceEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global engine
    
    logger.info("🎙️ Starting TTS Service...")
    
    # Ensure directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize engine
    engine = VibeVoiceEngine()
    
    try:
        await engine.initialize()
        logger.info("✅ TTS Service Ready!")
    except Exception as e:
        logger.error(f"❌ Engine initialization failed: {e}")
        # Continue anyway, will fail on first request
    
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
        "version": "0.1.0",
        "endpoints": {
            "health": "/health",
            "voices": "/voices",
            "clone": "/voices/clone",
            "generate_speech": "/generate/speech",
            "generate_podcast": "/generate/podcast",
            "presets": "/presets"
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
    """Clone a voice from an audio sample"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    # Validate file type
    content_type = audio_sample.content_type or ""
    if not content_type.startswith("audio/"):
        # Also accept common audio extensions
        filename = audio_sample.filename or ""
        valid_extensions = [".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"]
        if not any(filename.lower().endswith(ext) for ext in valid_extensions):
            raise HTTPException(400, "Invalid file type. Please upload an audio file.")
    
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
    """Generate multi-speaker podcast"""
    if not engine:
        raise HTTPException(503, "TTS engine not initialized")
    
    # Convert script to dict format
    script = [{"speaker": s.speaker, "text": s.text, "voice_id": s.voice_id} 
              for s in request.script]
    
    settings = request.settings.dict() if request.settings else {}
    settings["normalize_audio"] = request.normalize_audio
    settings["add_silence_between_speakers"] = request.add_silence_between_speakers
    
    result = await engine.generate_podcast(
        script=script,
        voice_mapping=request.voice_mapping,
        settings=settings
    )
    
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "Podcast generation failed"))
    
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
