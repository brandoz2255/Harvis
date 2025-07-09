from fastapi import FastAPI, HTTPException, Request, UploadFile, File, WebSocket, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.websockets import WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn, os, sys, tempfile, uuid, base64, io, logging, re, requests, random
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import asyncpg
from gemini_api import query_gemini, is_gemini_configured
from typing import List, Optional, Dict, Any
from vison_models.llm_connector import query_qwen, query_llm

from pydantic import BaseModel
import torch, soundfile as sf
import whisper  # Import Whisper

# ─── Authentication Setup ──────────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@localhost:5432/database")

class AuthRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    avatar: Optional[str] = None

# ─── Authentication Utilities ───────────────────────────────────────────────────
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        logger.info(f"JWT payload: {payload}")
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id: int = int(user_id_str)
        logger.info(f"User ID from token: {user_id}")
    except (JWTError, ValueError) as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception
    
    conn = await get_db_connection()
    try:
        user = await conn.fetchrow("SELECT id, username, email, avatar FROM users WHERE id = $1", user_id)
        if user is None:
            logger.error(f"User not found for ID: {user_id}")
            raise credentials_exception
        logger.info(f"User found: {dict(user)}")
        return UserResponse(**dict(user))
    finally:
        await conn.close()

# ─── Local helper --------------------------------------------------------------
from chatterbox_tts import load_tts_model, generate_speech  # see second file below
from chatterbox.tts import ChatterboxTTS, punc_norm
import torch
import logging
import time

# Add the ollama_cli directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'ollama_cli'))
from vibe_agent import VibeAgent

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── VRAM Management ────────────────────────────────────────────────────────────
def get_vram_threshold():
    if not torch.cuda.is_available():
        return float('inf')

    total_mem = torch.cuda.get_device_properties(0).total_memory
    return max(int(total_mem * 0.8), 10 * 1024**3)

THRESHOLD_BYTES = get_vram_threshold()
logger.info(f"VRAM threshold set to {THRESHOLD_BYTES/1024**3:.1f} GiB")

def wait_for_vram(threshold=THRESHOLD_BYTES, interval=0.5):
    if not torch.cuda.is_available():
        return
    used = torch.cuda.memory_allocated()
    while used > threshold:
        logger.info(f"VRAM {used/1024**3:.1f} GiB > {threshold/1024**3:.1f} GiB. Waiting…")
        time.sleep(interval)
        used = torch.cuda.memory_allocated()
    torch.cuda.empty_cache()
    logger.info("VRAM is now below threshold. Proceeding with TTS.")

# ─── Global Model Variables ─────────────────────────────────────────────────────
tts_model = None
vibe_agent = VibeAgent(project_dir=os.getcwd())


def load_tts_model(force_cpu=False):
    global tts_model
    tts_device = "cuda" if torch.cuda.is_available() and not force_cpu else "cpu"

    if tts_model is None:
        try:
            logger.info(f"🔊 Loading TTS model on device: {tts_device}")
            tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            if "cuda" in str(e).lower():
                logger.warning(f"⚠️ CUDA load failed: {e}. Falling back to CPU...")
                try:
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                    logger.info("✅ Successfully loaded TTS model on CPU")
                except Exception as e2:
                    logger.error(f"❌ Failed to load TTS model on CPU: {e2}")
                    raise RuntimeError("TTS model loading failed on both CUDA and CPU.") from e2
            else:
                logger.error(f"❌ TTS model loading error: {e}")
                raise
    return tts_model

# ─── Generate Speech ────────────────────────────────────────────────────────────
def generate_speech(text, model, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    try:
        normalized = punc_norm(text)
        if torch.cuda.is_available():
            try:
                wav = model.generate(
                    normalized,
                    audio_prompt_path=audio_prompt,
                    exaggeration=exaggeration,
                    temperature=temperature,
                    cfg_weight=cfg_weight
                )
            except RuntimeError as e:
                if "CUDA" in str(e):
                    logger.error(f"CUDA Error: {e}")
                    torch.cuda.empty_cache()
                    try:
                        wav = model.generate(
                            normalized,
                            audio_prompt_path=audio_prompt,
                            exaggeration=exaggeration,
                            temperature=temperature,
                            cfg_weight=cfg_weight
                        )
                    except RuntimeError as e2:
                        logger.error(f"CUDA Retry Failed: {e2}")
                        raise ValueError("CUDA error persisted after cache clear") from e2
                else:
                    raise
        else:
            wav = model.generate(
                normalized,
                audio_prompt_path=audio_prompt,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
                device="cpu"
            )
        return (model.sr, wav.squeeze(0).numpy())
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise
# hey ─── Logging -------------------------------------------------------------------
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

class ResearchChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    model: str = DEFAULT_MODEL
    enableWebSearch: bool = True

class ScreenAnalysisRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)

class SynthesizeSpeechRequest(BaseModel):
    text: str
    audio_prompt: Optional[str] = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5

class VibeCommandRequest(BaseModel):
    command: str
    mode: str = "assistant"

class AnalyzeAndRespondRequest(BaseModel):
    image: str  # base-64 image (data-URI or raw)
    model: str = DEFAULT_MODEL
    system_prompt: Optional[str] = None

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

# ─── Authentication Endpoints ─────────────────────────────────────────────────────
@app.post("/api/auth/signup", response_model=TokenResponse, tags=["auth"])
async def signup(request: SignupRequest):
    conn = await get_db_connection()
    try:
        # Check if user already exists
        existing_user = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1 OR username = $2",
            request.email, request.username
        )
        if existing_user:
            raise HTTPException(status_code=409, detail="User with this email or username already exists")
        
        # Hash password and create user
        hashed_password = get_password_hash(request.password)
        user_id = await conn.fetchval(
            "INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id",
            request.username, request.email, hashed_password
        )
        
        # Create access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user_id)}, expires_delta=access_token_expires
        )
        
        return TokenResponse(access_token=access_token, token_type="bearer")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        await conn.close()

@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(request: AuthRequest):
    conn = await get_db_connection()
    try:
        user = await conn.fetchrow(
            "SELECT id, password FROM users WHERE email = $1",
            request.email
        )
        if not user or not verify_password(request.password, user["password"]):
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user["id"])}, expires_delta=access_token_expires
        )
        
        return TokenResponse(access_token=access_token, token_type="bearer")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        await conn.close()

@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
async def get_current_user_info(current_user: UserResponse = Depends(get_current_user)):
    return current_user

# Import new modules




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
                "Reply in ≤25 spoken-style words, sprinkling brief Spanish when natural, Be bilangual about 80 percent english and 20 percent spanish"
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
        # Decode base64 image and save to a temporary file
        image_data = base64.b64decode(req.image.split(",")[1])
        temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
        with open(temp_image_path, "wb") as f:
            f.write(image_data)

        # Use Qwen to caption the image
        qwen_prompt = "Describe this image in detail."
        qwen_caption = query_qwen(temp_image_path, qwen_prompt)
        os.remove(temp_image_path) # Clean up temp file

        if "[Qwen error]" in qwen_caption:
            raise HTTPException(status_code=500, detail=qwen_caption)

        # Use LLM to get a response based on the caption
        llm_system_prompt = "You are an AI assistant that helps users understand what's on their screen. Provide a concise and helpful response based on the screen content."
        llm_user_prompt = f"Here's what's on the user's screen: {qwen_caption}\nWhat should they do next?"
        llm_response = query_llm(llm_user_prompt, system_prompt=llm_system_prompt)

        return {"commentary": qwen_caption, "llm_response": llm_response}

    except Exception as e:
        logger.error("Screen analysis failed: %s", e)
        raise HTTPException(500, str(e)) from e

@app.post("/api/analyze-and-respond", tags=["vision"])
async def analyze_and_respond(req: AnalyzeAndRespondRequest):
    """
    Analyze screen with Qwen vision model and get LLM response using selected model.
    """
    try:
        # Decode base64 image and save to a temporary file
        image_data = base64.b64decode(req.image.split(",")[1])
        temp_image_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.png")
        with open(temp_image_path, "wb") as f:
            f.write(image_data)

        # Use Qwen to analyze the image
        qwen_prompt = "Analyze this screen in detail. Describe what you see, including any text, UI elements, applications, and content visible."
        qwen_analysis = query_qwen(temp_image_path, qwen_prompt)
        os.remove(temp_image_path)  # Clean up temp file

        if "[Qwen error]" in qwen_analysis:
            raise HTTPException(status_code=500, detail=qwen_analysis)

        # Use the selected LLM model to generate a response based on Qwen's analysis
        # Use custom system prompt if provided, otherwise use default
        system_prompt = req.system_prompt or "You are Jarvis, an AI assistant analyzing what the user is seeing on their screen. Provide helpful insights, suggestions, or commentary about what you observe. Be conversational and helpful."
        
        if req.model == "gemini-1.5-flash":
            # Use Gemini for response
            llm_response = query_gemini(f"Screen analysis: {qwen_analysis}\n\nPlease provide helpful insights about this screen.", [])
        else:
            # Use Ollama for response
            
            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Screen analysis: {qwen_analysis}\n\nPlease provide helpful insights about this screen."},
                ],
                "stream": False,
            }

            logger.info(f"→ Asking Ollama with model {req.model}")
            resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
            
            if resp.status_code != 200:
                logger.error("Ollama error %s: %s", resp.status_code, resp.text)
                raise HTTPException(status_code=500, detail="LLM request failed")
            
            llm_response = resp.json().get("message", {}).get("content", "").strip()

        return {
            "response": llm_response,
            "screen_analysis": qwen_analysis,
            "model_used": req.model
        }

    except Exception as e:
        logger.error("Analyze and respond failed: %s", e)
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

# Research endpoints using the new research module with LangChain
from agent_research import research_agent, fact_check_agent, comparative_research_agent

@app.post("/api/research-chat", tags=["research"])
async def research_chat(req: ResearchChatRequest):
    """
    Enhanced research chat endpoint with comprehensive web search and analysis
    """
    try:
        if not req.message:
            return {"error": "Message is required"}, 400

        # Call the enhanced research agent
        response_data = research_agent(req.message, req.model)

        # Format response for chat interface
        if "error" in response_data:
            response_content = f"Research Error: {response_data['error']}"
        else:
            # Format the comprehensive research response
            analysis = response_data.get("analysis", "No analysis available")
            sources = response_data.get("sources", [])
            sources_found = response_data.get("sources_found", 0)
            
            response_content = f"{analysis}\n\n"
            
            if sources:
                response_content += f"**Sources ({sources_found} found):**\n"
                for i, source in enumerate(sources[:5], 1):  # Limit to top 5 sources
                    response_content += f"{i}. [{source['title']}]({source['url']})\n"

        # Update history with assistant reply
        new_history = req.history + [{"role": "assistant", "content": response_content}]

        return {"history": new_history, "response": response_content}

    except Exception as e:
        logger.exception("Research chat endpoint crashed")
        raise HTTPException(500, str(e))

class FactCheckRequest(BaseModel):
    claim: str
    model: str = DEFAULT_MODEL

class ComparativeResearchRequest(BaseModel):
    topics: List[str]
    model: str = DEFAULT_MODEL

@app.post("/api/fact-check", tags=["research"])
async def fact_check(req: FactCheckRequest):
    """
    Fact-check a claim using web search and analysis
    """
    try:
        result = fact_check_agent(req.claim, req.model)
        return result
    except Exception as e:
        logger.exception("Fact-check endpoint crashed")
        raise HTTPException(500, str(e))

@app.post("/api/comparative-research", tags=["research"])
async def comparative_research(req: ComparativeResearchRequest):
    """
    Compare multiple topics using web research
    """
    try:
        if len(req.topics) < 2:
            raise HTTPException(400, "At least 2 topics are required for comparison")
        
        result = comparative_research_agent(req.topics, req.model)
        return result
    except Exception as e:
        logger.exception("Comparative research endpoint crashed")
        raise HTTPException(500, str(e))

# ─── Warmup ────────────────────────────────────────────────────────
try:
    logger.info("Preloading TTS and Whisper…")
    _ = load_tts_model()
    _ = whisper.load_model("base")
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

@app.post("/api/vibe/command")
async def vibe_command(req: VibeCommandRequest):
    vibe_agent.mode = req.mode
    response_text, _ = vibe_agent.process_command(req.command)
    return {"response": response_text}

@app.websocket("/api/ws/vibe")
async def websocket_vibe_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            mode = data.get("mode", "assistant")

            if command:
                vibe_agent.mode = mode
                await vibe_agent.process_command(command, websocket)
            else:
                await websocket.send_json({"type": "error", "content": "No command received"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.send_json({"type": "error", "content": f"WebSocket error: {e}"})

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
# huh2.0

@app.post("/api/synthesize-speech", tags=["tts"])
async def synthesize_speech(req: SynthesizeSpeechRequest):
    """
    Synthesizes speech from text using the TTS model.
    This endpoint is called by worker nodes.
    """
    try:
        tts = load_tts_model()

        audio_prompt_path = req.audio_prompt or JARVIS_VOICE_PATH
        if not os.path.isfile(audio_prompt_path):
            logger.warning(
                "Audio prompt %s not found, falling back to default voice.",
                audio_prompt_path,
            )
            audio_prompt_path = None

        sr, wav = generate_speech(
            text=req.text,
            model=tts,
            audio_prompt=audio_prompt_path,
            exaggeration=req.exaggeration,
            temperature=req.temperature,
            cfg_weight=req.cfg_weight,
        )

        filename = f"response_{uuid.uuid4()}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)
        logger.info("Audio written to %s", filepath)

        return {"audio_path": f"/api/audio/{filename}"}

    except Exception as e:
        logger.exception("TTS synthesis endpoint crashed")
        raise HTTPException(500, str(e)) from e

