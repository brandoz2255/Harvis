"""
FastAPI back-end with Chatterbox-TTS voice-cloning (Jarvis voice)
----------------------------------------------------------------
Put jarvis_voice.mp3 in the project root before running.
"""

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn, os, tempfile, uuid, base64, io, logging, re, requests, random
from gemini_api import query_gemini, is_gemini_configured
from typing import List, Optional, Dict, Any

from pydantic import BaseModel
from PIL import Image
import torch, soundfile as sf
from transformers import pipeline
import whisper  # Import Whisper

# ─── Local helper --------------------------------------------------------------
from chatterbox_tts import load_tts_model, generate_speech  # see second file below

# ─── Logging -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Paths ---------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "front_end")
JARVIS_VOICE_PATH = os.path.abspath(
    "jarvis_voice.mp3"
)  # Point to the file in project root

# ─── FastAPI init --------------------------------------------------------------
app = FastAPI(title="Jarves-TTS API")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    logger.info("Frontend directory mounted at %s", FRONTEND_DIR)

# ─── Device & models -----------------------------------------------------------
device = 0 if torch.cuda.is_available() else -1
logger.info("Using device: %s", "cuda" if device == 0 else "cpu")

try:
    logger.info("Loading image captioning model …")
    image_to_text = pipeline(
        "image-to-text", model="Salesforce/blip-image-captioning-base", device=device
    )
except Exception as e:
    logger.error("BLIP model failed: %s", e)
    image_to_text = None

# ─── Config --------------------------------------------------------------------
OLLAMA_URL = "http://ollama:11434"
DEFAULT_MODEL = "mistral"


# ─── Pydantic schemas ----------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    audio_prompt: Optional[str] = None  # overrides JARVIS_VOICE_PATH if provided
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5


class ScreenAnalysisRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)


# ─── Helpers -------------------------------------------------------------------
BROWSER_PATTERNS = [
    r"^(?:open|launch|go\s+to|navigate\s+to|take\s+me\s+to|visit)\s+",
    r"^(?:abre|abrír|navega\s+a|llévame\s+a|visita)\s+",
    r"^(?:search|look\s+up|google|find)\s+(?:for\s+)?",
    r"^(?:busca|buscar|encuentra|investigar?)\s+(?:sobre\s+)?",
    r"^(?:open|create)\s+(?:\d+\s+)?(?:new\s+)?tabs?",
    r"^(?:abre|crea)\s+(?:\d+\s+)?(?:nueva[s]?\s+)?pestaña[s]?",
]
is_browser_command = lambda txt: any(
    re.match(p, txt.lower().strip()) for p in BROWSER_PATTERNS
)


# ─── Routes --------------------------------------------------------------------
@app.get("/", tags=["frontend"])
async def root() -> FileResponse:
    index_html = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_html):
        return FileResponse(index_html)
    raise HTTPException(404, "Frontend not found")


# Import new modules
from screen_analyzer import analyze_image_base64
from llm_connector import query_mistral


@app.post("/api/analyze-and-respond")
async def analyze_and_respond(req: ScreenAnalysisRequest):
    try:
        # Get screen analysis data
        screen_data = analyze_image_base64(req.image)

        # Check for errors
        if "error" in screen_data:
            return {"commentary": screen_data["error"]}

        # Create prompt with both caption and OCR text
        prompt = (
            f"Here's what's on the user's screen:\n"
            f"BLIP Caption: {screen_data['caption']}\n"
            f"OCR Text: {screen_data['ocr_text']}\n"
            "Based on this, what should be the next action or response?"
        )

        # Get LLM response
        llm_response = query_mistral(prompt)

        return {"llm_response": llm_response}
    except Exception as e:
        return {"llm_response": f"Error analyzing screen: {e}"}


@app.post("/api/chat", tags=["chat"])
async def chat(req: ChatRequest, request: Request):
    """
    Main conversational endpoint.
    Produces: JSON {history, audio_path}
    """
    try:
        # ── 1. Update dialogue history with the latest user turn
        history = req.history + [{"role": "user", "content": req.message}]
        response_text: str

        # ── 2. Browser automation branch -------------------------------------------------
        if is_browser_command(req.message):
            try:
                from trash.browser import smart_url_handler, search_google, open_new_tab

                result = smart_url_handler(req.message)
                response_text = (
                    search_google(result["query"])
                    if isinstance(result, dict) and result.get("type") == "search"
                    else open_new_tab(result)
                )
            except Exception as e:
                logger.error("Browser cmd failed: %s", e)
                response_text = "¡Ay! Hubo un problema con esa acción del navegador."
        # ── 3. LLM generation branch ------------------------------------------------------
        elif req.model == "gemini-1.5-flash":
            response_text = query_gemini(req.message, req.history)
        else:
            system_prompt = (
                'You are "Jarves", a voice-first local assistant. '
                "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural. "
                'Begin each answer with a short verbal acknowledgment (e.g., "Claro,", "¡Por supuesto!", "Right away").'
            )
            OLLAMA_ENDPOINT = "/api/chat"  # single source of truth

            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.message},
                ],
                "stream": False,
            }

            logger.info("→ Asking Ollama %s with model %s", OLLAMA_ENDPOINT, req.model)

            resp = requests.post(
                f"{OLLAMA_URL}{OLLAMA_ENDPOINT}", json=payload, timeout=90
            )

            if resp.status_code != 200:
                logger.error("Ollama error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()

            response_text = resp.json().get("message", {}).get("content", "").strip()

        # ── 4. Update history with assistant reply
        new_history = history + [{"role": "assistant", "content": response_text}]

        # ── 5. Text-to-speech -----------------------------------------------------------
        tts = load_tts_model()  # lazy global singleton

        # Handle audio prompt path
        audio_prompt_path = req.audio_prompt or JARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            logger.warning(
                "Audio prompt %s not found, falling back to default voice.",
                audio_prompt_path,
            )
            audio_prompt_path = None

        # Debug logging for the audio prompt path
        if audio_prompt_path:
            if not os.path.exists(audio_prompt_path):
                logger.warning(f"JARVIS voice prompt missing at: {audio_prompt_path}")
            else:
                logger.info(f"Cloning voice using prompt: {audio_prompt_path}")

        sr, wav = generate_speech(
            text=response_text,
            model=tts,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
        )

        # ── 6. Persist WAV to /tmp so nginx (or FastAPI fallback) can serve it ------------
        filename = f"response_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info("Audio written to %s", filepath)

        return {
            "history": new_history,
            "audio_path": f"/api/audio/{filename}",  # FastAPI route below (or nginx alias /audio/)
        }

    except Exception as e:
        logger.exception("Chat endpoint crashed")
        raise HTTPException(500, str(e)) from e


@app.get("/api/audio/{filename}", tags=["audio"])
async def serve_audio(filename: str):
    """
    FastAPI static audio fallback (use nginx /audio alias in production for speed).
    """
    full_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(full_path):
        raise HTTPException(404, f"Audio file not found: {filename}")
    return FileResponse(full_path, media_type="audio/wav")


@app.post("/api/analyze-screen", tags=["vision"])
async def analyze_screen(req: ScreenAnalysisRequest):
    try:
        # Log the size of the incoming image data
        logger.info(f"Received image data size: {len(req.image) if req.image else 0} bytes")

        # Get screen analysis data using the dedicated function
        screen_data = analyze_image_base64(req.image)

        # Log the screen analysis data
        logger.info(f"Screen analysis data: {screen_data}")

        # Check for errors from screen analysis
        if "error" in screen_data:
            raise HTTPException(500, detail=screen_data["error"])

        # Create prompt with both caption and OCR text
        prompt = (
            f"Here's what's on the user's screen:\n"
            f"BLIP Caption: {screen_data['caption']}\n"
            f"OCR Text: {screen_data['ocr_text']}\n"
            "Based on this, what should be the next action or response?"
        )

        # Get LLM response
        llm_response = query_mistral(prompt)

        return {"commentary": screen_data["caption"], "llm_response": llm_response}
    except Exception as e:
        logger.error("Screen analysis failed: %s", e)
        raise HTTPException(500, str(e)) from e



# Load Whisper (once, at the top)
whisper_model = whisper.load_model("base")  # or "small", "medium", "large"


@app.post("/api/mic-chat", tags=["voice"])
async def mic_chat(file: UploadFile = File(...)):
    try:
        # Save uploaded file to temp
        contents = await file.read()
        tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.wav")
        with open(tmp_path, "wb") as f:
            f.write(contents)

        # Transcribe it
        result = whisper_model.transcribe(tmp_path)
        message = result.get("text", "").strip()
        logger.info(f"MIC input transcribed: {message}")

        if not message:
            raise HTTPException(400, "Could not transcribe anything.")

        # Now use existing chat logic
        chat_req = ChatRequest(message=message)
        return await chat(chat_req, request=None)

    except Exception as e:
        logger.exception("Mic chat failed")
        raise HTTPException(500, str(e))


# ─── Warmup ────────────────────────────────────────────────────────
try:
    logger.info("Preloading TTS and Whisper and BLIP…")
    _ = load_tts_model()
    _ = whisper.load_model("base")
    _ = pipeline(
        "image-to-text", model="Salesforce/blip-image-captioning-base", device=device
    )
except Exception as e:
    logger.error("Preload failed: %s", e)

# ─── Dev entry-point -----------------------------------------------------------


@app.get("/api/ollama-models", tags=["models"])
async def get_ollama_models():
    """
    Fetches the list of available models from the Ollama server.
    """
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        ollama_model_names = [model["name"] for model in models]

        if is_gemini_configured():
            ollama_model_names.insert(
                0, "gemini-1.5-flash"
            )  # Add Gemini to the beginning

        return ollama_model_names
    except requests.exceptions.RequestException as e:
        logger.error(f"Could not connect to Ollama: {e}")
        raise HTTPException(
            status_code=503, detail="Could not connect to Ollama server"
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
# huh2.0
