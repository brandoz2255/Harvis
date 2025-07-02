
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import requests
import os
import logging
import google.generativeai as genai

# --- Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL for the main backend with GPU capabilities
MAIN_BACKEND_URL = os.getenv("MAIN_BACKEND_URL", "http://127.0.0.1:8000")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- FastAPI App Initialization ---
app = FastAPI(title="Jarvis Worker Node API")

# --- Gemini Configuration ---
is_gemini_configured_flag = bool(GEMINI_API_KEY)
if is_gemini_configured_flag:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini API configured successfully.")
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}")
        is_gemini_configured_flag = False
else:
    logger.warning("GEMINI_API_KEY not found. Gemini functionality will be disabled.")

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = "mistral"
    # TTS options are forwarded to the main backend
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = "mistral"

class ScreenAnalysisRequest(BaseModel):
    image: str  # base64 encoded image

# --- Helper Functions ---
def query_gemini(message: str, history: List[Dict[str, Any]]):
    if not is_gemini_configured_flag:
        raise HTTPException(status_code=503, detail="Gemini API is not configured on this worker.")
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        # Gemini API uses a different history format
        gemini_history = []
        for item in history:
            role = 'user' if item['role'] == 'user' else 'model'
            gemini_history.append({'role': role, 'parts': [item['content']]})
        
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(message)
        return response.text
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise HTTPException(status_code=500, detail=f"Error communicating with Gemini API: {str(e)}")

def query_ollama(message: str, model: str, history: List[Dict[str, Any]]):
    system_prompt = (
        'You are "Jarves", a voice-first local assistant. '
        "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural. "
        'Begin each answer with a short verbal acknowledgment (e.g., "Claro,").'
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message},
        ],
        "stream": False,
    }
    try:
        logger.info(f"Forwarding request to Ollama model: {model}")
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except requests.RequestException as e:
        logger.error(f"Ollama request failed: {e}")
        raise HTTPException(status_code=503, detail=f"Could not connect to Ollama server: {e}")

# --- API Endpoints ---

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Handles chat requests. Gets a text response from Ollama or Gemini,
    then forwards a request to the main backend to synthesize audio.
    """
    try:
        # 1. Get text response from the appropriate model
        history = req.history
        if req.model == "gemini-1.5-flash":
            response_text = query_gemini(req.message, history)
        else:
            response_text = query_ollama(req.message, req.model, history)

        new_history = history + [
            {"role": "user", "content": req.message},
            {"role": "assistant", "content": response_text}
        ]

        # 2. Forward to main backend for Text-to-Speech
        logger.info("Forwarding text to main backend for TTS")
        tts_payload = {
            "text": response_text,
            "audio_prompt": req.audio_prompt,
            "exaggeration": req.exaggeration,
            "temperature": req.temperature,
            "cfg_weight": req.cfg_weight,
        }
        # This new endpoint needs to be created on the main backend
        tts_response = requests.post(f"{MAIN_BACKEND_URL}/api/synthesize-speech", json=tts_payload, timeout=60)
        tts_response.raise_for_status()
        
        # The main backend returns the path to the audio file it's hosting
        audio_path = tts_response.json().get("audio_path")

        return {
            "history": new_history,
            "audio_path": f"{MAIN_BACKEND_URL}{audio_path}" # Return the full URL to the audio
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions to return proper status codes
        raise e
    except Exception as e:
        logger.exception("Worker chat endpoint crashed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mic-chat")
async def mic_chat(file: UploadFile = File(...)):
    """
    Forwards audio file to the main backend for transcription and processing.
    The main backend will transcribe, chat, and TTS, returning the final response.
    """
    try:
        logger.info("Forwarding microphone input to main backend")
        files = {'file': (file.filename, await file.read(), file.content_type)}
        response = requests.post(f"{MAIN_BACKEND_URL}/api/mic-chat", files=files, timeout=60)
        response.raise_for_status()
        
        # The main backend returns a full response with history and a full audio URL
        data = response.json()
        if 'audio_path' in data and not data['audio_path'].startswith('http'):
             data['audio_path'] = f"{MAIN_BACKEND_URL}{data['audio_path']}"

        return data
    except Exception as e:
        logger.exception("Mic chat forwarding failed")
        raise HTTPException(500, str(e))


@app.post("/api/analyze-screen")
async def analyze_screen(req: ScreenAnalysisRequest):
    """
    Forwards a base64 image to the main backend for analysis.
    """
    try:
        logger.info("Forwarding screen analysis request to main backend")
        response = requests.post(f"{MAIN_BACKEND_URL}/api/analyze-screen", json={"image": req.image}, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.exception("Screen analysis forwarding failed")
        raise HTTPException(500, str(e))


@app.post("/api/research-chat")
async def research_chat(req: ResearchChatRequest):
    """
    Forwards research requests to the main backend, which has the research agent.
    """
    try:
        logger.info("Forwarding research chat request to main backend")
        response = requests.post(f"{MAIN_BACKEND_URL}/api/research-chat", json=req.dict(), timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.exception("Research chat forwarding failed")
        raise HTTPException(500, str(e))


@app.get("/api/ollama-models")
async def get_ollama_models():
    """
    Fetches the list of available models from the local Ollama server.
    """
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        ollama_model_names = [model["name"] for model in models]

        if is_gemini_configured_flag:
            ollama_model_names.insert(0, "gemini-1.5-flash")

        return ollama_model_names
    except requests.RequestException as e:
        logger.error(f"Could not connect to Ollama: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to Ollama server")

if __name__ == "__main__":
    import uvicorn
    # Use 0.0.0.0 to be accessible within a container
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
