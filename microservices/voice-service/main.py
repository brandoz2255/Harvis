"""
Voice Service - Speech-to-Text (Whisper) and Text-to-Speech (Chatterbox)
Handles all voice processing functionality
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import os
import tempfile
import uuid
from typing import Optional
import torch
import whisper
import soundfile as sf

# Import TTS module
try:
    from chatterbox_tts import generate_speech
    TTS_AVAILABLE = True
except Exception as e:
    logging.warning(f"TTS not available: {e}")
    TTS_AVAILABLE = False

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI App
app = FastAPI(
    title="Harvis Voice Service",
    description="Speech-to-Text and Text-to-Speech Processing",
    version="1.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global models (loaded on demand)
whisper_model = None
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

# Pydantic Models
class TranscribeRequest(BaseModel):
    audio_data: str  # Base64 encoded audio

class TTSRequest(BaseModel):
    text: str
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

# Model Management
def load_whisper():
    """Load Whisper model on demand"""
    global whisper_model
    if whisper_model is None:
        logger.info(f"Loading Whisper model: {WHISPER_MODEL_SIZE}")
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("✅ Whisper model loaded")
    return whisper_model

def unload_whisper():
    """Unload Whisper model to free memory"""
    global whisper_model
    if whisper_model is not None:
        del whisper_model
        whisper_model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("✅ Whisper model unloaded")

def safe_generate_speech(text, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    """Generate speech with error handling"""
    try:
        if not TTS_AVAILABLE:
            logger.warning("TTS not available - skipping audio generation")
            return None, None

        result = generate_speech(text, audio_prompt, exaggeration, temperature, cfg_weight)
        if result is None or result == (None, None):
            logger.warning("TTS unavailable - skipping audio generation")
            return None, None
        return result
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return None, None

def safe_save_audio(sr, wav, prefix="response"):
    """Save audio to file, returning filepath or None"""
    if sr is None or wav is None:
        logger.warning("TTS unavailable - no audio to save")
        return None

    try:
        filename = f"{prefix}_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info(f"Audio written to {filepath}")
        return f"/api/audio/{filename}"
    except Exception as e:
        logger.error(f"Failed to save audio file: {e}")
        return None

# Health Check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "voice-service",
        "tts_available": TTS_AVAILABLE,
        "whisper_loaded": whisper_model is not None
    }

# Speech-to-Text Endpoint
@app.post("/api/mic-chat", tags=["voice"])
async def mic_chat(
    file: UploadFile = File(...),
    model: str = Form("mistral"),
    session_id: Optional[str] = Form(None),
    research_mode: str = Form("false")
):
    """
    Process voice input - transcribe audio to text
    Note: This endpoint returns transcription only.
    The core-api will forward to appropriate AI service for response.
    """
    try:
        is_research_mode = research_mode.lower() == "true"
        logger.info(f"🎤 Voice input received, research mode: {is_research_mode}")

        # Save uploaded file
        contents = await file.read()
        logger.info(f"Received audio: {len(contents)} bytes")

        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="No audio data received")

        # Detect audio format from header
        header = contents[:4]
        if header == b'RIFF':
            file_ext = ".wav"
        elif header == b'OggS':
            file_ext = ".ogg"
        elif header.startswith(b'ID3') or header.startswith(b'\xff\xfb'):
            file_ext = ".mp3"
        elif header.startswith(b'\x1a\x45\xdf\xa3'):
            file_ext = ".webm"
        else:
            file_ext = ".wav"

        tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}{file_ext}")
        with open(tmp_path, "wb") as f:
            f.write(contents)

        # Transcribe audio
        logger.info("🎤 Transcribing audio with Whisper...")
        model_instance = load_whisper()
        result = model_instance.transcribe(tmp_path, fp16=torch.cuda.is_available())
        transcribed_text = result["text"].strip()

        # Cleanup
        os.remove(tmp_path)

        logger.info(f"✅ Transcription complete: {transcribed_text}")

        return {
            "transcription": transcribed_text,
            "language": result.get("language", "en"),
            "session_id": session_id,
            "model": model,
            "research_mode": is_research_mode
        }

    except Exception as e:
        logger.exception("Voice processing failed")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Unload Whisper after use to free memory
        unload_whisper()

# Text-to-Speech Endpoint
@app.post("/api/tts", tags=["voice"])
async def text_to_speech(req: TTSRequest):
    """
    Convert text to speech using Chatterbox TTS
    """
    try:
        logger.info(f"🔊 TTS request: {req.text[:50]}...")

        if not TTS_AVAILABLE:
            raise HTTPException(status_code=503, detail="TTS service not available")

        # Generate speech
        sr, wav = safe_generate_speech(
            req.text,
            req.audio_prompt,
            req.exaggeration,
            req.temperature,
            req.cfg_weight
        )

        if sr is None or wav is None:
            raise HTTPException(status_code=503, detail="TTS generation failed")

        # Save audio file
        audio_path = safe_save_audio(sr, wav, prefix="tts")

        if audio_path is None:
            raise HTTPException(status_code=500, detail="Failed to save audio")

        logger.info(f"✅ TTS complete: {audio_path}")

        return {
            "audio_path": audio_path,
            "text": req.text,
            "status": "success"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail=str(e))

# STT-only endpoint
@app.post("/api/stt", tags=["voice"])
async def speech_to_text(file: UploadFile = File(...)):
    """
    Speech-to-Text only endpoint (no AI response)
    """
    try:
        logger.info("🎤 STT-only request")

        # Save uploaded file
        contents = await file.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="No audio data received")

        tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.wav")
        with open(tmp_path, "wb") as f:
            f.write(contents)

        # Transcribe
        model_instance = load_whisper()
        result = model_instance.transcribe(tmp_path, fp16=torch.cuda.is_available())
        transcribed_text = result["text"].strip()

        # Cleanup
        os.remove(tmp_path)
        unload_whisper()

        logger.info(f"✅ STT complete: {transcribed_text}")

        return {
            "text": transcribed_text,
            "language": result.get("language", "en")
        }

    except Exception as e:
        logger.exception("STT failed")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
