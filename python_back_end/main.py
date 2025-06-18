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
from transformers.pipelines import pipeline
import logging
from chatbot import (
    chat_with_voice,
    transcribe_and_chat,
    load_tts_model,
    generate_speech
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the absolute path to the project root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

# === Pydantic Models ===
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = "mistral"
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ScreenAnalysisRequest(BaseModel):
    image: str

# === Routes ===

@app.get("/api/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend files not found")

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        # Use the chat_with_voice function from chatbot.py
        history = request.history + [{"role": "user", "content": request.message}]
        audio_path = None

        # Call chat_with_voice to get the response and audio
        new_history, (sample_rate, wav_data) = chat_with_voice(
            request.message,
            history,
            request.model,
            request.audio_prompt,
            request.exaggeration,
            request.temperature,
            request.cfg_weight
        )

        # Save the audio to a file if needed
        if wav_data is not None:
            temp_dir = tempfile.gettempdir()
            filename = f"response_{uuid.uuid4()}.wav"
            filepath = os.path.join(temp_dir, filename)
            sf.write(filepath, wav_data, sample_rate)
            audio_path = filename

        return {
            "history": new_history,
            "audio_path": audio_path
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
