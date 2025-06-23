from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import tempfile
import uuid
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import base64
import io
from PIL import Image
import torch
import soundfile as sf
from transformers import pipeline
import logging
import requests
import re

from chatterbox_tts import load_tts_model, generate_speech

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the absolute path to the project root directory
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "front_end")

# Initialize FastAPI app
app = FastAPI()

# Optional: serve frontend via FastAPI (usually Nginx does this)
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    logger.info(f"Frontend directory mounted at {FRONTEND_DIR}")
else:
    logger.warning(f"Frontend directory not found at {FRONTEND_DIR}")

# Determine device
device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Using device: {device}")

# Load image analysis model
try:
    logger.info("Loading image analysis model...")
    image_to_text = pipeline(
        "image-to-text",
        model="Salesforce/blip-image-captioning-base",
        device=device
    )
    logger.info("Image analysis model loaded successfully")
except Exception as e:
    logger.error(f"Error loading image analysis model: {e}")
    image_to_text = None

# ─── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_URL = "http://ollama:11434"
DEFAULT_MODEL = "mistral"
JARVES_PROMPT = """You are "Harvis (Pronounced Harvis)", a voice-first local assistant. Reply in under 25 spoken-style words, 
sprinkling brief Spanish when natural. Begin each answer with a short verbal acknowledgment (e.g., "Claro," "¡Por supuesto!", "Right away"), 
then immediately run the requested command via the host system. After execution, return a concise verbal status or result; 
if silent completion is better, say nothing. Never output code blocks, markdown, or explanations—just compact, conversational responses.

You have full voice interaction capabilities including:
- Opening browser tabs ("abre una nueva pestaña con...")
- Searching the web ("busca información sobre...")
- Navigating to websites ("llévame a...")

Always respond as if you are speaking directly to the user, keeping responses brief and natural."""

# === Pydantic Models ===
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ScreenAnalysisRequest(BaseModel):
    image: str

# ─── Helper Functions ───────────────────────────────────────────────────────────
def is_browser_command(text: str) -> bool:
    """Determine if the text is a browser command."""
    browser_patterns = [
        r'^(?:open|launch|go\s+to|navigate\s+to|take\s+me\s+to|visit)\s+',
        r'^(?:abre|abrír|navega\s+a|llévame\s+a|visita)\s+',
        r'^(?:search|look\s+up|google|find)\s+(?:for\s+)?',
        r'^(?:busca|buscar|encuentra|investigar?)\s+(?:sobre\s+)?',
        r'^(?:open|create)\s+(?:\d+\s+)?(?:new\s+)?tabs?',
        r'^(?:abre|crea)\s+(?:\d+\s+)?(?:nueva[s]?\s+)?pestaña[s]?'
    ]
    text_lower = text.lower().strip()
    return any(re.match(pattern, text_lower) for pattern in browser_patterns)

# === Routes ===
@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend files not found")

@app.post("/chat")
async def chat_legacy(request: ChatRequest):
    """Legacy endpoint that mirrors /api/chat functionality for backward compatibility"""
    return await chat(request)

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        history = request.history + [{"role": "user", "content": request.message}]
        
        if is_browser_command(request.message):
            try:
                from trash.browser import smart_url_handler, search_google, open_new_tab

                result = smart_url_handler(request.message)

                if isinstance(result, dict) and result.get("type") == "search":
                    response_text = search_google(result["query"])
                else:
                    response_text = open_new_tab(result)
            except Exception as e:
                logger.error(f"Browser command error: {e}")
                response_text = "¡Ay! Had trouble with that browser action. ¿Intentamos de nuevo?"
        else:
            enhanced_prompt = f"""You are "Jarves (Pronounced Harves)", a voice-first local assistant.
Reply in under 25 spoken-style words, sprinkling brief Spanish when natural.
Begin each answer with a short verbal acknowledgment (e.g., "Claro," "¡Por supuesto!", "Right away").

IMPORTANT: Only use browser commands when explicitly asked to:
- Open websites ("abre una pestaña con...")
- Search the web ("busca información sobre...")
- Navigate ("llévame a...")

For all other questions, just have a natural conversation.
Current user message: {request.message}"""

            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": request.model,
                    "prompt": request.message,
                    "system": enhanced_prompt,
                    "stream": False
                }
            )
            
            if response.ok:
                response_text = response.json().get("response", "").strip()
            else:
                raise HTTPException(status_code=response.status_code, detail=response.text)

        new_history = history + [{"role": "assistant", "content": response_text}]
        
        tts = load_tts_model()
        sample_rate, wav_data = generate_speech(
            response_text,
            tts,
            request.audio_prompt,
            request.exaggeration,
            request.temperature,
            request.cfg_weight
        )

        temp_dir = tempfile.gettempdir()
        filename = f"response_{uuid.uuid4()}.wav"
        filepath = os.path.join(temp_dir, filename)
        sf.write(filepath, wav_data, sample_rate)

        return {
            "history": new_history,
            "audio_path": filename
        }

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/audio/{filename}")
async def serve_audio(filename: str):
    full_path = os.path.join(tempfile.gettempdir(), filename)
    if os.path.exists(full_path):
        return FileResponse(full_path, media_type="audio/wav")
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/analyze-screen")
async def analyze_screen(request: ScreenAnalysisRequest):
    try:
        if ',' in request.image:
            image_data = request.image.split(',')[1]
        else:
            image_data = request.image

        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))

        if image_to_text:
            logger.info("Analyzing screen content...")
            result = image_to_text(image)

            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                caption = result[0].get('generated_text', '')
                if caption:
                    commentary = f"I see {caption.lower()}"
                    prefixes = [
                        "Looking at your screen, ",
                        "I notice that ",
                        "On your screen, ",
                        "I can see that ",
                        "Currently, "
                    ]
                    import random
                    commentary = random.choice(prefixes) + commentary
                    logger.info(f"Generated commentary: {commentary}")
                    return {"commentary": commentary}

            logger.warning("Failed to generate meaningful commentary")
            return {"commentary": "I'm having trouble analyzing the screen content right now."}
        else:
            logger.warning("Image analysis model not available")
            return {"commentary": "I'm having trouble analyzing the screen content right now."}

    except Exception as e:
        logger.error(f"Error in analyze-screen endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# === Main entry ===
if __name__ == "__main__":
    logger.info("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)