"""
Cody - Headless AI Assistant
A streamlined FastAPI application with ChatterboxTTS, Ollama, and Whisper
"""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uvicorn
import os
import sys
import logging
import tempfile
import uuid
import soundfile as sf
import whisper
import requests
from pathlib import Path

# ChatterboxTTS import
try:
    from chatterbox.tts import ChatterboxTTS, punc_norm
except ImportError:
    print("⚠️  ChatterboxTTS not available")
    ChatterboxTTS = None

# ─── Configuration ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TTS_DEVICE = os.getenv("TTS_DEVICE", "cuda" if os.path.exists("/dev/nvidia0") else "cpu")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", "mistral")

# Audio output directory
AUDIO_DIR = Path("/tmp/cody_audio")
AUDIO_DIR.mkdir(exist_ok=True)

# Global models
whisper_model = None
tts_model = None

# ─── Pydantic Models ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = DEFAULT_OLLAMA_MODEL
    history: Optional[List[Dict[str, str]]] = []
    stream: Optional[bool] = False

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "default"

class TranscribeResponse(BaseModel):
    text: str
    language: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    audio_path: Optional[str] = None
    model: str

# ─── Lifespan Context Manager ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup, cleanup on shutdown"""
    global whisper_model, tts_model

    logger.info("🚀 Starting Cody - Headless AI Assistant")

    # Load Whisper model
    try:
        logger.info(f"📥 Loading Whisper model: {WHISPER_MODEL}")
        whisper_model = whisper.load_model(WHISPER_MODEL)
        logger.info("✅ Whisper model loaded successfully")
    except Exception as e:
        logger.error(f"❌ Failed to load Whisper model: {e}")

    # Load ChatterboxTTS model
    if ChatterboxTTS:
        try:
            logger.info(f"📥 Loading ChatterboxTTS on {TTS_DEVICE}")
            tts_model = ChatterboxTTS.from_pretrained(device=TTS_DEVICE)
            logger.info("✅ ChatterboxTTS model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load ChatterboxTTS: {e}")
            tts_model = None

    # Verify Ollama connection
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            logger.info(f"✅ Ollama connected. Available models: {[m['name'] for m in models]}")
        else:
            logger.warning(f"⚠️  Ollama responded with status {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Ollama: {e}")

    logger.info("✅ Cody initialization complete")

    yield

    # Cleanup
    logger.info("🧹 Shutting down Cody...")
    if whisper_model:
        del whisper_model
    if tts_model:
        del tts_model
    logger.info("✅ Shutdown complete")

# ─── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Cody - Headless AI Assistant",
    description="AI assistant with voice input/output and LLM capabilities",
    version="1.0.0",
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

# ─── Health Check ───────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Cody AI Assistant",
        "whisper": whisper_model is not None,
        "tts": tts_model is not None,
        "ollama_url": OLLAMA_URL
    }

# ─── Ollama Integration ─────────────────────────────────────────────────────────
def query_ollama(prompt: str, model: str = DEFAULT_OLLAMA_MODEL, history: List[Dict[str, str]] = None) -> str:
    """Query Ollama LLM"""
    try:
        messages = []

        # Add history if provided
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

        # Add current prompt
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False
        }

        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("message", {}).get("content", "")
        else:
            logger.error(f"Ollama error: {response.status_code} - {response.text}")
            return f"Error: Ollama returned status {response.status_code}"

    except Exception as e:
        logger.error(f"Failed to query Ollama: {e}")
        return f"Error querying Ollama: {str(e)}"

# ─── Speech-to-Text (Whisper) ───────────────────────────────────────────────────
@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe audio file to text using Whisper"""
    if not whisper_model:
        raise HTTPException(status_code=503, detail="Whisper model not loaded")

    try:
        # Save uploaded file temporarily
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        content = await file.read()
        temp_file.write(content)
        temp_file.close()

        # Transcribe
        logger.info(f"🎤 Transcribing audio file: {file.filename}")
        result = whisper_model.transcribe(temp_file.name)

        # Cleanup
        os.unlink(temp_file.name)

        return TranscribeResponse(
            text=result["text"].strip(),
            language=result.get("language")
        )

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Text-to-Speech (ChatterboxTTS) ─────────────────────────────────────────────
@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using ChatterboxTTS"""
    if not tts_model:
        raise HTTPException(status_code=503, detail="TTS model not loaded")

    try:
        logger.info(f"🔊 Generating speech for: {request.text[:50]}...")

        # Normalize text
        normalized_text = punc_norm(request.text) if hasattr(tts_model, 'punc_norm') else request.text

        # Generate audio
        audio_array = tts_model.generate(normalized_text)

        # Save to file
        audio_id = str(uuid.uuid4())
        audio_path = AUDIO_DIR / f"{audio_id}.wav"
        sf.write(str(audio_path), audio_array, 24000)

        return {
            "audio_path": f"/audio/{audio_id}.wav",
            "text": request.text
        }

    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Chat Endpoint ──────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat with AI - returns text and optional audio"""
    try:
        logger.info(f"💬 Chat request: {request.message[:100]}")

        # Query Ollama
        response_text = query_ollama(
            prompt=request.message,
            model=request.model,
            history=request.history
        )

        # Generate audio if TTS is available
        audio_path = None
        if tts_model and response_text:
            try:
                normalized_text = punc_norm(response_text)
                audio_array = tts_model.generate(normalized_text)

                audio_id = str(uuid.uuid4())
                audio_file = AUDIO_DIR / f"{audio_id}.wav"
                sf.write(str(audio_file), audio_array, 24000)

                audio_path = f"/audio/{audio_id}.wav"
            except Exception as e:
                logger.error(f"TTS generation failed: {e}")

        return ChatResponse(
            response=response_text,
            audio_path=audio_path,
            model=request.model
        )

    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Voice Chat Endpoint ────────────────────────────────────────────────────────
@app.post("/voice-chat")
async def voice_chat(
    file: UploadFile = File(...),
    model: str = DEFAULT_OLLAMA_MODEL
):
    """Voice input -> AI response with voice output"""
    if not whisper_model:
        raise HTTPException(status_code=503, detail="Whisper model not loaded")

    try:
        # 1. Transcribe audio input
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        content = await file.read()
        temp_file.write(content)
        temp_file.close()

        logger.info(f"🎤 Transcribing voice input...")
        transcription = whisper_model.transcribe(temp_file.name)
        user_text = transcription["text"].strip()
        os.unlink(temp_file.name)

        logger.info(f"📝 User said: {user_text}")

        # 2. Query Ollama
        response_text = query_ollama(prompt=user_text, model=model)

        # 3. Generate audio response
        audio_path = None
        if tts_model and response_text:
            try:
                normalized_text = punc_norm(response_text)
                audio_array = tts_model.generate(normalized_text)

                audio_id = str(uuid.uuid4())
                audio_file = AUDIO_DIR / f"{audio_id}.wav"
                sf.write(str(audio_file), audio_array, 24000)

                audio_path = f"/audio/{audio_id}.wav"
            except Exception as e:
                logger.error(f"TTS generation failed: {e}")

        return {
            "user_input": user_text,
            "response": response_text,
            "audio_path": audio_path,
            "model": model
        }

    except Exception as e:
        logger.error(f"Voice chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Audio File Server ──────────────────────────────────────────────────────────
@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve generated audio files"""
    audio_path = AUDIO_DIR / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio_path, media_type="audio/wav")

# ─── Ollama Models List ─────────────────────────────────────────────────────────
@app.get("/models")
async def list_models():
    """List available Ollama models"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return {"models": [m["name"] for m in models]}
        else:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch models")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "cody:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )
