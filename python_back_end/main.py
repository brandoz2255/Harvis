from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
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

# Define allowed origins
origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost",
    "http://127.0.0.1"
]

# Configure CORS with specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With"],
    expose_headers=["Content-Type", "Authorization"],
    max_age=3600
)

# Mount static files if directory exists
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    logger.info(f"Frontend directory mounted at {FRONTEND_DIR}")
else:
    logger.warning(f"Frontend directory not found at {FRONTEND_DIR}")

# Determine device
device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Using device: {device}")

# Initialize the image analysis model
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

# Pydantic models for request validation
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

# Routes
@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend files not found")

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        # For now, return a simple response since Ollama is not available
        return {
            "history": request.history + [{"user": request.message, "assistant": "I'm sorry, but the chat functionality is currently unavailable. Please check back later."}],
            "audio_path": None
        }
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    full_path = os.path.join(tempfile.gettempdir(), filename)
    if os.path.exists(full_path):
        return FileResponse(full_path, media_type="audio/wav")
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/analyze-screen")
async def analyze_screen(request: ScreenAnalysisRequest):
    try:
        # Remove the data URL prefix if present
        if ',' in request.image:
            image_data = request.image.split(',')[1]
        else:
            image_data = request.image
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Generate caption
        if image_to_text:
            logger.info("Analyzing screen content...")
            result = image_to_text(image)
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                caption = result[0].get('generated_text', '')
                if caption:
                    # Add some context to make it more conversational
                    commentary = f"I see {caption.lower()}"
                    
                    # Add some variety to the commentary
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

# Add error handling middleware
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        # Add CORS headers to all responses
        origin = request.headers.get("origin")
        if origin in ["*"] or (origin and origin.endswith(tuple(app.routes[0].path_regex.findall(request.url.path)))):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={
                "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*"
            }
        )

# Add OPTIONS handler for preflight requests
@app.options("/{full_path:path}")
async def options_handler(request: Request, full_path: str):
    origin = request.headers.get("origin")
    if origin not in ["*"]:
        return Response(status_code=400, content="Invalid origin")
    
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
            "Access-Control-Expose-Headers": "Content-Type, Authorization"
        }
    )

# Add CORS headers to all responses
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin in ["*"]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

if __name__ == "__main__":
    logger.info("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000) 